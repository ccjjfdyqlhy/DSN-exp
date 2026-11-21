# Security Model

> English translation of [../security.md](../security.md) — the Chinese original is authoritative.

> Reader: maintainers who are attaching tools to AICF, or auditing why a given tool call was allowed or denied.
> Goal: after reading this, you can answer precisely "why was this call allowed to execute" and "why was it not".

---

## In one sentence

> **Deny by default.** A tool call without a policy grant is always rejected —
> not "allowed by default and logged".

---

## 1. Threat model

What we defend against is not the "malicious user" but **a model that has been talked into something**:
prompt injection, external web pages, or instructions hidden in tool output can all make the model
invoke a tool it should never have called.

So the line of defense is not built on "will the model behave itself", but on
**every single call passing through the gate**:

```
The model wants to call a tool
   → ToolSpec: what side effects does the tool declare, what scopes does it need
   → PolicyEngine: does the policy allow it? does the identity have the scopes? (explicit deny always wins)
   → ApprovalBroker: does a human need to approve? (timeout = denial)
   → Idempotency check: has this call already been made?
   → Sandbox: which isolation level does it run at? (downgrades must be visible)
   → Audit: everything is recorded
```

**If any link in the chain is uncertain, the result is a denial.** "I couldn't decide"
is never a reason to allow.

---

## 2. Tool contract: `ToolSpec`

```python
@dataclass(frozen=True)
class ToolSpec:
    name: str
    version: str = '1.0'
    effect: Literal['pure', 'idempotent', 'effectful'] = 'effectful'
    scopes: tuple[str, ...] = ()                 # 需要的授权范围
    sandbox: Literal['none','readonly','workspace','isolated'] = 'isolated'
    network: Literal['none','allowlist','full'] = 'none'
    destructive: bool = False
```

*(Inline comment: "required authorization scopes.")*

### Undeclared means strictest

A tool without a `spec` is treated as `effectful + isolated + approval required`.

The entire point of this rule: **"forgot to declare" must never be equivalent to
"silently widened permissions"**. A missing declaration is a **configuration error**,
and a configuration error must manifest as "stricter", not "looser".

There is exactly one exception: `AnnotatedTool(read_only=True)` — "read-only" is itself
an explicit declaration, so the defaults can be narrowed to `pure + readonly` based on it.

### Effect levels

| Level | Meaning | Auto-replay on recovery? | Approval required by default? |
|---|---|---|---|
| `pure` | Pure computation, changes nothing | ✅ | No |
| `idempotent` | A write, but repeating it is harmless | ✅ | No |
| `effectful` | Sends messages / charges money / mutates external systems | ❌ **never** | ✅ |

The recovery policy for `effectful` is the single most important rule in the whole security model:
**it is better to stall the task and wait for a human to confirm than to charge the card twice.**

---

## 3. Admission policy

Evaluation order (first match wins):

1. **Explicit deny rules** — always win, even when an allow rule exists later
2. **Scope check** — a scope the tool requires is not in the identity's scopes → deny (reason `scope`)
3. **Explicit allow rules** — e.g. a read-only tool allowlist
4. **Risk threshold** — `risk <= threshold` is allowed automatically
5. **Default deny** → requires manual approval

The risk level is computed from the tool contract:

| Condition | Risk |
|---|---|
| `destructive=True` | high |
| `effect=effectful` | high |
| `effect=idempotent` | medium |
| `effect=pure` | low |
| `network=full` | bump one level |
| `sandbox=none` | bump one level (starting from low) |

**When the policy engine itself raises an exception, the call is treated as denied.**
Do not build a security model on the assumption that "the policy service is always
available" — that assumption breaks at exactly the moment it goes down.

---

## 4. Approval (human in the loop)

### Decision values

| Decision | Meaning |
|---|---|
| `approve` / `approve_once` | Allow this one call |
| `approve_always` | Allow and remember it per `scope` |
| `deny` | Deny |
| `timeout` | The wait timed out — **semantically equal to a denial** |

### Approval scopes

| scope | What it covers |
|---|---|
| `once` | This call only; nothing is cached |
| `session` | The tool is allowed for the rest of this session |
| `tool:<name>` | The tool is allowed across sessions |
| `always` | The tool is allowed permanently |

**Unknown scopes are never cached.** Treating a scope you don't understand as
"allowed forever" is a security incident.

### Two waiting modes

| Mode | Setting | Implementation |
|---|---|---|
| Synchronous wait | CLI / local console | `LocalApprovalBroker(resolver=...)` |
| Asynchronous backfill | Web console (SSE pushes events; a human clicks, then the decision is filled back in) | `LocalApprovalBroker()` + `submit(id, decision)` |

### Timeout is a separate event

A timeout emits `approval_timeout`, **not** `deny`.
In incident retrospectives, "nobody responded" and "it was denied" are two entirely
different things: the former is a process problem, the latter a permissions problem.

### Suspension and recovery

If the process exits while an approval is pending, after a restart the call must still be in
`awaiting_approval`, and the decision can be filled in later. Implementation: pending requests
can be exported (`broker.pending()`); after a restart, `restore_pending()` re-suspends them.

---

## 5. Sandbox

| Backend | Mechanism | Strength |
|---|---|---|
| `none` | Direct subprocess | None (testing only) |
| `restricted` | Subprocess + `ulimit` + path allowlist + env-var allowlist | Weak (the default degraded level) |
| `namespaced` | Namespaces / bubblewrap / nsjail | Medium |
| `isolated` | Containers / micro-VMs | Strong (rc1) |

### Degradation principles

When no strong-isolation backend can be detected, the system **does not error out and block**,
but it must:

- `SandboxResult.degraded = True` (always True at the `restricted` level; the tool passes
  this flag back to the caller — it is part of the `proc.run` return payload)
- When the sandbox rejects something, the violation record carries the `degraded` flag,
  and the guard logs `tool_blocked` and `audit.denied` with `reason='sandbox'`
- "Deny on degradation" is a **choice reserved to the upper policy layer**, but the current
  policy engine has no such switch yet, and the `sandbox_degraded` event in the event
  vocabulary has no producer yet — the current state is "degradation is visible",
  not "degradation can deny"

**"Believing you are sandboxed when you are not" is never allowed.** This is a hard requirement:
a sandbox that does not know it failed to isolate is more dangerous than no sandbox at all.

### Paths and network

- **Files**: paths are `resolve`d before the prefix check, to prevent `../` and symlink escapes
- **Network**: level + domain allowlist; **once judged, never allowed through**, and a
  `net:deny` is recorded (the `restricted` level cannot actually cut the network — a command
  connecting straight to an IP cannot be stopped; only approval and post-hoc audit backstop it)
- **Processes**: the process tree of a one-shot execution (`proc.run`) is reaped by the sandbox,
  and signals go only to the **child's own** process group (the pgid is verified not to be the
  caller's before signaling); session-style shell tools still reap their own process trees

### the write levels (the tool's own declaration decides)

A tool declares with `ToolSpec.sandbox` which boundary it needs, and the
shell tool turns that declaration into the path rules of its request:

| `spec.sandbox` | the path rules of the request |
|---|---|
| `readonly` | the working directory goes to `readonly_paths`, `cwd_writable=False` |
| `workspace` | the working directory goes to `writable_paths` |
| `none` / `isolated` | the working directory stays writable |

**Why the working directory is a writable root by default**: it is the
workspace of the turn, and a model writing into its own workspace is
normal work, not something to block.

**Why `cwd_writable` has to exist**: that convenience rule turns a
read-only project back into a writable one, so the write boundary would
be theatre. `PathPolicy.cwd_writable` and `SandboxRequest.cwd_writable`
are the switch that turns it off, and the read-only level turns it off.

**Where the declaration changes**: the tool's declaration changes, not
the backend's behaviour, because the policy, the approval and the audit
all read that one declaration. `ToolSpec` is a frozen dataclass, so a
new level means a new spec (`dataclasses.replace`), not a field write.

---

## 6. Identity and credentials

```python
@dataclass(frozen=True)
class AgentIdentity:
    agent_id: str
    tenant: str
    scopes: tuple[str, ...]
    delegated_by: str | None = None
    delegation_chain: tuple[str, ...] = ()
    credential_refs: tuple[str, ...] = ()
```

- **Delegation**: a child agent's scopes must be a subset of the parent's scopes;
  `delegation_chain` records the full delegation path, so the audit trail can answer
  "where did this permission originally come from"
- **Credentials**: a tool only ever receives a `CredentialRef`, resolved by the runtime
  at injection time; in logs, events, and traces it is always replaced with `***`
- **Out-of-scope means deny**: a scope the tool requires is not in the identity's scopes
  → deny immediately and record it in the audit log

### Redaction has exactly one implementation

The `redact()` in `aicf/infra/observability/redact.py` is the **only** redaction
implementation; `aicf/harness/telemetry/exporter.py` and `aicf/infra/observability/audit.py`
both re-export it directly, and there are tests asserting all three are the same function
(`audit_redact is exporter_redact is infra_redact`).

Rationale: when redaction logic is scattered everywhere, the first thing to leak is
always some unremarkable branch.

**Exception**: **references** such as `credential_ref` are not redacted.
Keys ending in `_ref` / `_id` / `_name` are treated as references —
masking a reference as `***` erases exactly the most critical information in the
audit trail. The goal of redaction is "don't leak secrets", not "don't leak any information".

---

## 7. Audit

```
audit.tool_call{identity, tool, version, args_digest, effect, sandbox, decision, duration, outcome}
audit.denied{reason: policy|scope|sandbox|approval}
audit.secret_access{credential_ref, tool}
audit.delegation{from, to, scopes}
```

- Audit events share the **same stream** as business events, but are **stored independently**
- `AuditStore` simply **does not offer** `delete` / `clear` / `truncate` / `pop`
  (tests assert those attributes do not exist); `AuditLog.clear()` explicitly raises
  `AuditImmutableError` rather than AttributeError
- The only deletion path is `purge_expired(retention_seconds>0)` (passing 0 raises
  ValueError immediately)
- `args_digest` stores only the **hash and length** of the arguments, never the plaintext

"Cannot be deleted" is not perfectionism: the entire value of an audit log is that
it can still be queried after something goes wrong.

---

## 8. The dual-track period

```
Old path: Agent → ToolRegistry → handler (direct subprocess)
New path: Agent → ToolRegistry → ToolGuard → PolicyEngine → Approval → Sandbox → handler
```

- The new path has approval and audit enabled by default
- The old path (no guard attached) is kept, but at startup it prints a **single** prominent
  warning: 「当前为 legacy 直连模式：无审批、无审计、无幂等保护」
  (gloss: "currently in legacy direct mode: no approval, no audit, no idempotency protection")
- The environment variable `AICF_SECURITY_MODE=strict|legacy` controls the default mode;
  the default is `strict` (new installs)

### The default path is now the new path

Agents created by `create_agent` and by the `aicf` CLI **carry the guard by default**,
and `ToolGuard` **attaches `RestrictedSandbox` by default** (the degraded level:
subprocess + ulimit + path allowlist + env-var allowlist). The strong-isolation level
is only swapped in with **explicit assembly** — neither `NamespacedSandbox` nor
`detect_best_backend()` is on the default path.

This means:

- `proc.run` runs with the operator's privileges, but scoped to the workspace: paths and
  outbound network targets are checked before launch, ulimit is applied, and environment
  variables go through an allowlist. **This is not OS-level isolation** — the process is not
  confined to any container or namespace; the checks happen **before execution**, they do
  not **contain the process**;
- with no sandbox backend available, the tool prints a prominent warning instead of
  "pretending it is sandboxed";
- to go back to the old behavior: `AICF_SECURITY_MODE=legacy`, or detach the guard
  (`registry.detach_guard()`).

**The legacy direct path still exists in 1.0.0** — `AICF_SECURITY_MODE=legacy`
turns it on (no approval, no audit, no idempotency protection).

---

## 9. FAQ

**Q: Do read-only tools need approval too?**
No. A tool with `effect=pure` has low risk and is allowed automatically.
Declaring a `spec` gets you that — but **not declaring is never less safe**
(the default is the strictest).

**Q: What happens if the policy engine goes down?**
The call is treated as denied and the tool does not execute. Better to stop than to allow.

**Q: What if no sandbox is available?**
It degrades to `restricted` and is flagged `degraded=True`, visible in events.
The upper policy layer can be configured to deny on degradation.

**Q: Why are approval timeouts recorded separately?**
In incident retrospectives, "nobody responded" and "it was denied" mean entirely different
things: the former calls for fixing a process, the latter for fixing permissions.
Mixed together, you can no longer tell which one to fix.

---

## See also

- [roadmap_1.0.0-rc0.md](../roadmap_1.0.0-rc0.md) — planned work and acceptance checklist
- [runtime.md](../runtime.md) — idempotency and recovery
- [evaluation.md](../evaluation.md) — how the safety gate blocks a release
- [architecture.md](../architecture.md) — dependency rules
