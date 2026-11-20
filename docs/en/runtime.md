# Managed Runtime

> English translation of [../runtime.md](../runtime.md) — the Chinese original is authoritative.

> Reader: maintainers who need an agent to recover after a crash and **not repeat side effects**.
> Goal: after reading this, you can answer "after the crash, which things did I already do, and which am I unsure about".

---

## In one sentence

> **The journal is the truth; the checkpoint is only an accelerator.**

---

## 1. Why this is needed

The existing `aicf/harness/transcript.py` is a "conversation text snapshot": it can recover
*what was said*, but it cannot guarantee *side effects are not repeated*. A crash replay
could send a request twice, write a file twice, or charge twice.

The managed runtime exists to solve exactly this: **the running instance may die, but task
state and execution results are not lost, and a replay never produces the side effect a
second time.**

---

## 2. The two-level structure

```
Event Journal (WAL, append-only)      ← the sole source of truth for facts
        │  periodically
        ▼
Checkpoint (snapshot, discardable)    ← speeds up recovery, not a source of truth
```

| | Journal | Checkpoint |
|---|---|---|
| Semantics | What happened | Where things stood at that moment |
| Discardable | ❌ no | ✅ yes |
| If corrupted | You lose facts | Just replay from the journal |
| Write pattern | Append-only | Overwrite |

**If a checkpoint is corrupted, recovery must still work by replaying from the journal** —
this is the requirement of §8.2, use case 7. The snapshot stores the journal watermark
(the reserved key `__journal_seq__`), so "events after the checkpoint" can be located precisely.

---

## 3. The state model

| Entity | What it is | Key fields |
|---|---|---|
| **Session** | Logical container for one session/task | id, tenant, artifact_id, deployment_id, workspace_id, status, budget |
| **Turn** | One execution unit driven by a user input | id, session_id, seq, status, input, checkpoint_ref, usage, cost, stop_reason |
| **Event** | An append-only atomic fact | session_id, turn_id, seq, kind, payload, ts, idempotency_key |
| **Deployment** | One agent version deployed on a Runtime | id, artifact_id, spec, replicas, strategy, status |
| **Workspace** | The writable state space of one run | id, session_id, root, spec(fs/net/secret), status |

Status enums:

```text
SessionStatus:  ACTIVE / SUSPENDED / COMPLETED / FAILED / EXPIRED
TurnStatus:     PENDING / RUNNING / AWAITING_APPROVAL / SUCCEEDED / FAILED /
                INTERRUPTED / CANCELLED
DeploymentStatus: PENDING / ROLLOUT / HEALTHY / DEGRADED / ROLLED_BACK
WorkspaceStatus:  READY / LOCKED / RELEASED / EXPIRED
```

`AWAITING_APPROVAL` is a **persistent** state, not an in-memory wait —
if the process exits while an approval is pending, after a restart the turn is still
in this state and the decision can be filled in later.

---

## 4. Idempotent execution

### Idempotency keys

```
idempotency_key = sha256(session_id | turn_seq | tool_name | canonical_args)
```

`canonical_args` is a **stable serialization**: keys sorted, non-string keys converted to
strings, non-serializable values falling back to `repr`. The same arguments must always
yield the same key — equivalent arguments with different key order
(`{'a':1,'b':2}` vs `{'b':2,'a':1}`) must hit the same cache entry.

### Effect levels and replay policy

| Level | On recovery |
|---|---|
| `pure` | Can be replayed automatically (replay has no side effects) |
| `idempotent` | Can be replayed automatically (repeating it is harmless) |
| `effectful` | **Never replayed automatically** |

**An unknown effect is always treated as `effectful`** (fail-safe).

### The three phases: intent → execute → result

```
write the intent event  →  execute the tool  →  write the result event
```

If recovery sees only an intent and **no** matching result, the process died mid-execution:
the outcome of this call is **unknown** — the external system may be untouched,
or half-changed.

Mark it `unknown_outcome` and **hand it to a human; never replay on your own**.

### Where the protection sits: the moment before execution

```python
# aicf/infra/runtime/managed.py
if effect == EFFECT_EFFECTFUL and self._pending_intent(key) is not None:
    raise UnknownOutcomeError(unknown)
```

The protection must sit at **the moment the intent is written**, not only inside
`execute_tool`. Reason: `aicf/harness/tools/guard.py` implements its own
"check cache → write intent → execute → write result" path; if the protection lived
only in `execute_tool`, that path could bypass it → double charging.

Cross-layer recognition (`aicf.infra` must not `import aicf.harness`): each side has its
own `UnknownOutcomeError`, and they recognize each other via the `unknown_outcome`
marker attribute. **When recognition fails, treat it as a denial** — the worst
outcome is merely an imprecise error message.

### An effectful tool raising is also an unknown outcome

An exception does not mean "nothing happened" (the external system may be half-changed).
Being conservative is safer than an optimistic retry. Only `pure` / `idempotent`
are replayed automatically.

---

## 5. The recovery flow

```
load latest checkpoint → replay journal after checkpoint → resume the turn
```

```python
from aicf.infra.runtime import SqliteRuntimeStore, recover

plan = recover(port, session_id)
plan.replayable   # 可以安全重放的调用
plan.unknown      # 结果未知 —— 需要人工确认
```

*(Inline comments: "calls that are safe to replay" / "outcome unknown — needs human confirmation".)*

### Two easy-to-miss pitfalls

**Pitfall one: pairing side effects requires scanning the full journal, not "after the checkpoint".**
The intent may have been written before the checkpoint, with the result after it — or not at all.
Looking only at "after the checkpoint" misses the most dangerous class:
**in-flight calls that straddle a checkpoint**.

**Pitfall two: the result cache is an accelerator; the journal is the truth.**
On a cache miss, fall back to querying the journal — otherwise the window where
"the event was written but the cache write failed" would let an already-completed
effectful tool execute a second time. `resume()` backfills the cache from the journal.

---

## 6. Event deduplication

Events carry a `seq`; consumers deduplicate by `seq`. Every event consumer
(trace, audit, cost) must tolerate duplicate delivery — the standard combination of
"at-least-once delivery + idempotent consumption".

The journal itself provides `dedupe()`.

**seq allocation does not collide even across processes**
(verified in tests with 3 processes allocating concurrently).

---

## 7. Storage

All DB access is funneled behind `StorePort`:

```python
class StorePort(Protocol):
    upsert_session / get_session
    upsert_turn / get_turn / list_turns / last_open_turn
    append_event / list_events / last_event_seq
    put_checkpoint / load_checkpoint / list_checkpoints
    get_tool_result / put_tool_result / find_tool_event
```

rc0 only promises **single-machine semantics** (SQLite). Swapping in Postgres at rc1
must not change upper-layer callers — that is the reason all storage access is
tucked behind one Protocol.

---

## 8. Usage

```python
from aicf.infra.runtime import ManagedRuntime, SqliteRuntimeStore, migrate_runtime
from aicf.infra.store.sqlite import SqliteStore

store = SqliteStore('runtime.db')
migrate_runtime(store)
port = SqliteRuntimeStore(store)

runtime = ManagedRuntime(port, session_id='s1')
runtime.start_session()
runtime.start_turn(0)

# 工具调用：execute_tool 会自动处理 intent → 执行 → result 三段式
outcome = runtime.execute_tool(
    tool='charge_card', fn=lambda: charge(100), args={'amount': 100},
    effect='effectful',
)
```

*(Inline comment: "tool call: `execute_tool` handles the intent → execute → result three-phase flow automatically".)*

### After a crash

```bash
aicf session resume <session_id> --db runtime.db
```

The output explicitly lists two classes of call: **safe to replay** and
**outcome unknown**. The latter is never replayed automatically —
a human must confirm before anything is decided.

---

## 9. The decision left to rc1

**The plan of calls awaiting replay goes in the checkpoint, not the journal.**

Rationale: the journal is an append-only stream of facts and also feeds the audit and
backup pipelines; putting raw arguments into it carries a sensitivity cost
(arguments may contain secrets / PII). The checkpoint is already where agent state
lives, is discardable, and carries less semantic weight.

The sensitivity of the two pipelines naturally stays separate.

If rc1 needs "auto-replay without re-planning", go through a checkpoint blob —
do not add arguments to the journal.

---

## See also

- [security.md](../security.md) — approval, audit, identity
- [evaluation.md](../evaluation.md) — how to prove these behaviors have not regressed
- [roadmap_1.0.0-rc0.md](../roadmap_1.0.0-rc0.md) — milestones and acceptance checklist
