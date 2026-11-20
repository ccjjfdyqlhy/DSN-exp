# aicf-core

> **The floor, not the app.** aicf is the layer an agent system stands on:
> long-running, persistent, stable, safe and auditable — bottom-up, across
> modalities, with as many agents as the job needs.

A private companion, a study assistant, an on-call ops agent, a research
pipeline — the floor underneath is the same one.

**AICF** = Agent Infrastructure Cybernetics Framework · Apache-2.0

[English] | [简体中文](README_zh.md)

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![CI](https://img.shields.io/github/actions/workflow/status/ccjjfdyqlhy/aicf-core/ci.yml?branch=main&label=CI&style=for-the-badge)](https://github.com/ccjjfdyqlhy/aicf-core/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/endpoint?url=https%3A%2F%2Fccjjfdyqlhy.github.io%2Faicf-core%2Ftests.json)](https://github.com/ccjjfdyqlhy/aicf-core/actions/workflows/ci.yml)
[![Local First](https://img.shields.io/badge/local--first-100%25-8A2BE2?style=for-the-badge)](docs/architecture.md)
[![Modalities](https://img.shields.io/badge/modalities-text%20%C2%B7%20speech%20%C2%B7%20vision-8A2BE2?style=for-the-badge)](docs/infra.md)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue?style=for-the-badge)](LICENSE)

---

## Three guarantees

> **Run one long task safely, idempotently, and measurably.**

Most agent frameworks assume the process lives. This one assumes it will not.

| | The claim | How you can check it |
|---|---|---|
| **Safe** | Every tool call goes through a policy gate and, when the tool has side effects, an approval step. Anything undecided is **denied**. A tool that starts a process is checked before it runs — path scope, network target, `ulimit`s, environment whitelist — but it still runs with the operator's privileges: there is **no OS-level sandbox** (no container / micro-vm) yet. | `aicf tool exec proc.run --args '{"command":"rm -rf /"}'` → refused |
| **Idempotent** | A crashed run can be resumed without repeating side effects. `effectful` calls are never auto-replayed. | `pytest tests/fault/` — real `kill -9` in a subprocess |
| **Measurable** | Every run produces a trace; every change is scored against a dataset and stopped by a four-gate report. | `aicf eval` → `aicf gate` |

---

## What is in the floor

The floor is what your agent system stands on. Here is what lives on it —
and because all of it lives here, the same floor serves any scenario.

### Bottom-up, not top-down

Applications are not carved out of this framework. They grow on top of it.

```
your app          companion · study assistant · on-call ops · research · anything
   ▲
skills            declarative packages, out-of-tree, validated by the framework
   ▲
aicf/harness      turn loop · tool protocol · context · memory · sessions · pipeline · multi-agent
   ▲
aicf/infra        model routing · resource pool · storage · gateway · auth · policy
```

`aicf/harness/` never imports an application; `aicf/infra/` never imports
business semantics. Dependencies point **downward only**.

### Long-running, and persistent about it

`aicf/infra/runtime/` assumes the process will not survive: the journal is
the source of truth, checkpoints only accelerate it, idempotency keys stop an
`effectful` call from replaying, and a lease + fencing-token scheduler lets
another instance take over without two of them writing at once. Memory is
layered — working, episodic, semantic, profile (`aicf/harness/memory/`) — and
persisted through `aicf/infra/store/`.

### Safe by default, and auditable

`aicf/harness/policy/` decides, `aicf/harness/approval/` asks a human when a
call has side effects, and **anything undecided is denied**.
`aicf/infra/observability/audit.py` keeps the record the business cannot
delete. There is no OS-level sandbox yet — [docs/security.md](docs/security.md)
states exactly what is and is not protected.

### Full-modal: text, speech, vision

`aicf/infra/resources/` runs speech and vision locally: ASR (FunASR,
in-process), TTS (GPT-SoVITS over HTTP) and VLM (a local llama-server) sit in
one pool, scheduled by slot and reclaimed when they go idle. Text runs through
`aicf/infra/models/` and `aicf/infra/orchestrator/`. When training and
inference want the same card, `DeviceGate` in
`aicf/infra/orchestrator/scheduler.py` is the one place that arbitrates.

And the interaction layer is in the framework now, not in a private app:
`aicf/harness/voice/` streams TTS **sentence by sentence** (first sentence
plays while the next synthesizes), filters fake ASR input (noise / humming /
keyboard gibberish — a real classifier is a port, heuristics ship as the
fallback), runs **perception mode** (continuous conversation where silence
means listening) and a **heartbeat** (proactively speaks when idle, on your
hook). Three profiles in `aicf resources profile` — `resident` / `balanced` /
`eco` — make the always-available-vs-VRAM tradeoff explicit instead of
implicit.

### Many agents, one floor

`aicf/harness/agent/collab.py` gives you role types, delegation and a
mailbox; `swarm.py` adds a blackboard; `team.py` composes them.
`aicf/infra/control/` adds agent identity — every delegation is recorded, and
an artifact can only be released if its gate report passed.

### Skills are the ecosystem

`aicf/harness/skills/` loads skill packages from outside the repo: a
`skill.yaml` with JSON-Schema tool declarations, a prompt file, and plain
Python. The framework validates them before an agent ever sees them.

---

## Ninety seconds

```bash
pip install aicf-core
```

Every step below runs **offline** — no API key — and each one shows the
output you should actually see. The walkthrough ends **green**.

```bash
# 1. Scaffold a project: entry points wired, no business logic. Fill in the meat.
aicf init demo && cd demo

# 2. What does each tool actually do? Effect level, declared write level, required scopes.
aicf tool list
#    tool        effect      sandbox    net    destructive  version
#    file.edit   effectful   workspace  none   false        1.0
#    file.read   pure        readonly   none   false        1.0
#    ...

# 3. Try to run a shell. It has side effects — so it waits for a human.
aicf tool exec proc.run --args '{"command":"rm -rf /"}' --policy strict
#    Error: 工具 proc.run 被策略拒绝（approval）：CLI 未开启 --yes
```

Then your first success, still offline:

```bash
# 4. Run a whole dataset: one turn per case, one trace per case.
aicf run --dataset offline --trace-dir traces/
#    ✓ offline_pipeline_replies [offline] done
#    … 6 case，trace 落 traces/

# 5. Score it.
aicf eval --dataset offline --traces traces/ --out run.json
#    用例 6/6 通过（数据集 offline，hash …）

# 6. Stop the release if anything regressed, got too expensive, or broke a rule.
aicf gate --run run.json --out gate.json
#    闸门判定: 通过
#      [PASS] quality: 关键用例通过率 100.0%（1/1），达标
#      [PASS] safety: 未发现安全违规（扫描 6 个用例）
```

Two datasets ship with the package, on purpose:

- `offline` — pipeline smoke: reply arrives, no phantom tool calls, budget
  fields recorded. **Passes offline by design.** It tells you the floor works.
- `basic` — 40 quality cases (file io / computation / refusal / safety / …).
  It needs a real model to pass: the stub never calls tools, and the eval
  engine refuses to count an echo as an answer. That is not a bug — a smoke
  dataset passing would tell you nothing about model quality.

`aicf eval --group refusal,safety` scores a subset (the run record shows
which subset it was). A 30-line, zero-dependency Python example that prints
results lives at [examples/minimal.py](examples/minimal.py).

---

## Install

```bash
pip install aicf-core
```

> **Check what you got.** `aicf --version` must print `1.0.0` or newer.
> Releases before `1.0.0` shipped **no `aicf` command at all**. They are yanked
> on PyPI, but **some mirrors still serve them** — and pip installs a yanked
> release without a word when it is the only candidate the mirror carries.
> So if `aicf --version` prints `0.6.x`, your install is broken: take it from
> PyPI directly.
>
> ```bash
> pip install -U --index-url https://pypi.org/simple aicf-core
> ```

That is the whole library — the agent kernel and the model/tool/runtime layer.
The floor is the library; **applications live on top of it**, in their own
repositories (the web console is [`aicf-ui`](https://github.com/ccjjfdyqlhy/aicf-ui)).

Optional extras, installed only when you need them:

```bash
pip install "aicf-core[personality]"   # personality dynamics (PEV3)
pip install "aicf-core[decisions]"     # System-1 decision head
pip install "aicf-core[learning]"      # trajectory → dataset → judge → promotion loop
pip install "aicf-core[finetune]"      # local SFT (pulls torch)
pip install "aicf-core[mcp]"           # external MCP tool servers
pip install "aicf-core[all]"           # everything
```

---

## Migrating from ≤ 1.0.0rc3

`1.0.0` moves both layers under one top-level package. The reason is practical:
`harness` and `infra` are **already taken on PyPI**, and a library should not
squat on someone else's name inside your environment.

| Before (≤ 1.0.0rc3) | Now (1.0.0+) |
|---|---|
| `from harness import create_agent` | `from aicf.harness import create_agent` |
| `from harness.tools import ToolRegistry` | `from aicf.harness.tools import ToolRegistry` |
| `from infra.models.base import IChatClient` | `from aicf.infra.models.base import IChatClient` |

Distribution, CLI and import name now line up: `pip install aicf-core` →
the `aicf` command → `import aicf.harness`. (`from aicf import create_agent`
works too — it is the same symbol, forwarded lazily.)

---

## Just want to write an agent? Five symbols.

```python
from aicf.harness import create_agent, tool     # the two you write with
from aicf.harness.tools import ToolRegistry     # when you manage tools yourself
from aicf.infra.models.base import IChatClient # the model interface
```

| Symbol | What it is |
|---|---|
| `tool` | turns a typed function into a tool (schema generated from the signature) |
| `Agent` | an agent bound to a client — `chat()` / `run()` / `chat_stream()` |
| `create_agent` | one-liner factory: model + key + tools |
| `ToolRegistry` | the tool table (only if you register them yourself) |
| `IChatClient` | the model interface — implement it to plug in your own backend |

```python
from aicf.harness import create_agent, tool

@tool
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b

agent = create_agent(
    model="deepseek-chat",
    base_url="https://api.deepseek.com/v1",
    api_key="sk-...",                 # or just export OPENAI_API_KEY
    tools=[add],
)

result = agent.run("what is 17 + 25?")
print(result)                        # the result is string-like
```

Any OpenAI-compatible endpoint works. For a local model, point `base_url` at your
`llama-server` / LM Studio, or hand `create_agent` a client
(`aicf.infra.orchestrator.LlamaCppChat`, `LMStudioChat`, `OpenAICompatClient`, …).

---

## When should you use what?

Honest answer first: aicf is not the answer to everything. Against
LangGraph / Temporal / CrewAI the difference is structural, not aesthetic:

| | aicf-core | LangGraph | Temporal | CrewAI |
|---|---|---|---|---|
| Core idea | a **policy → approval → sandbox → audit** floor under every tool call, plus an idempotent, resumable runtime and a four-gate release report | graph orchestration over LLM steps | durable execution for long-running business workflows | role-based multi-agent scripting |
| Choose it when | an agent touches real files, shells, or networks and every call must be attributable, resumable, and evaluable | you want explicit control flow over model steps | you need workflow guarantees for business logic, LLM or not | you want a fast role-play prototype |
| Deliberately not its job | cross-machine orchestration (a deployment concern) and prompt engineering | safety rails, audit stores, idempotency — not its theme | LLM-native concepts (tool contracts, approvals, eval gates) | durable runtime, audits, release gates |
| Migration path | tools are plain functions: guard **one** tool behind the policy engine, then the next | graph edges → `workflow` kernel declarations (`aicf run --kernel workflow`) | activities → tools with effect declarations | role prompts → skill packages ([spec](docs/skill-spec.md)) |
| What the floor gives you that they don't | append-only audit store, `kill -9` recovery, crash-injection tests, offline eval + release gate in CI | — | — | — |

Migration cost in one line: aicf asks for **declarations you would eventually
want anyway** (a ToolSpec per tool, a policy file, a gate report) — start
with one guarded tool and grow.

---

## The repo in one minute

Two layers, dependencies pointing **downward only**:

```
aicf/harness/   Agent core    turn loop · tools · context · memory · pipeline · sessions · SDK
    │                        knows nothing about any product
    ▼
aicf/infra/     Infra         model routing · resource pool · storage · gateway · auth · policy
```

On top of them: `aicf/harness/kernel/` (workflow + planner),
`aicf/infra/control/` (agent artifacts, lifecycle, cost ledger),
`aicf/harness/skills/` (the skill ecosystem), `aicf/infra/eval/` (dataset,
four gates), `aicf/infra/runtime/` (journal, checkpoint, recovery).

Products that use it live in their own repositories and depend on
`aicf-core` and nothing else:

| Repository | What it is |
|---|---|
| [`aicf-ui`](https://github.com/ccjjfdyqlhy/aicf-ui) | Web console — models, chat, resources, System-1 decisions |

---

## Status

`aicf-core` is at **1.0.0** — the first release that installs and runs.
The definition of done for rc0 is three executable claims, and all three hold
(each one is pinned to a test):

1. an agent that is `kill -9`'d once still resumes and produces the right answer;
2. every tool call was either approved or refused — with an audit trail;
3. the run can be scored by a ≥30-case dataset and produce a four-gate report.

**Those guarantees hold on the default paths.** An agent built with
`create_agent` comes with a guard, and `proc.run` runs with the operator's
privileges but scoped to the workspace — a path check before the process
starts, `ulimit`s and an environment whitelist, not an OS-level sandbox.
Both the SDK and the CLI write the tool intents into the journal — so after a
crash the runtime can tell which side effects may already have happened.

**1.0.0** closes the six items the rc0 roadmap listed as missing: the control
plane, the workflow and planner kernels, agent identity with delegation, the
sampling loop with bad case feedback, the scheduler with the workspace
isolation, and the audit trail the business cannot delete. It also moves both
layers under one top-level package (`aicf.harness` / `aicf.infra` — see
[Migrating](#migrating-from--100rc3) above) and adds the release gate that
proves the installed wheel works. The release note is
[docs/releases/v1.0.0.md](docs/releases/v1.0.0.md).

What is left is OS-level isolation (a container or a micro vm — the
`isolated` backend tier is not built) and the deployment matters: the cross
machine orchestration and the transport of the runtime you bring yourself.
The plan, the acceptance criteria and the status of each workstream live in
[docs/roadmap_1.0.0-rc0.md](docs/roadmap_1.0.0-rc0.md).

**Reproducible numbers** (every one comes with its reproduce command —
`python benchmarks/run_benchmarks.py`):

| Number | Reference value | What it measures |
|---|---|---|
| Guard-chain round trip | p50 ≈ 0.28 ms, p95 ≈ 0.38 ms | one local call through policy + idempotency check + audit (pure tool, N=300) |
| Journal replay recovery | ≈ 1 ms / 200 events | full journal replay when no checkpoint is usable (worst-case recovery) |
| Layered-memory L1 compaction | ≈ 3.35× | characters in vs out when the session layer summarizes |
| Crash-recovery success rate | 46/46 = 100% | `tests/fault/` injection layer: real `kill -9`, duplicate delivery, corrupted checkpoints |

Details and caveats: [benchmarks/README.md](benchmarks/README.md).

---

## Development

```bash
git clone https://github.com/ccjjfdyqlhy/aicf-core.git && cd aicf-core
pip install -e ".[mcp,anthropic,socks]"
pip install pytest pytest-asyncio
python -m pytest -q tests/
```

---

## Documentation

| I want to… | Read this |
|---|---|
| Get from zero to a running agent | [docs/getting-started.md](docs/getting-started.md) |
| Know what 1.0.0-rc0 is doing and how it is verified | [docs/roadmap_1.0.0-rc0.md](docs/roadmap_1.0.0-rc0.md) |
| Learn the module map and dependency rules | [docs/architecture.md](docs/architecture.md) |
| Understand the security model (deny-by-default, approval, sandbox tiers, audit) | [docs/security.md](docs/security.md) |
| Understand the managed runtime (journal, checkpoint, idempotency, recovery) | [docs/runtime.md](docs/runtime.md) |
| Understand the evaluation loop (dataset, gates, run versions, regression) | [docs/evaluation.md](docs/evaluation.md) |
| Use the core as a library | [docs/sdk_guide.md](docs/sdk_guide.md) |
| Go deeper into the agent loop / tools / context | [docs/harness.md](docs/harness.md) |
| Go deeper into model routing / resources / storage | [docs/infra.md](docs/infra.md) |
| Know which traps not to step into before changing code | [docs/maintenance.md](docs/maintenance.md) |
| Configuration keys / environment variables | [docs/configuration.md](docs/configuration.md) |
| The public skill-package spec (the ecosystem's interface) | [docs/skill-spec.md](docs/skill-spec.md) |
| Community channels and contribution paths | [docs/community.md](docs/community.md) |
| Known tech debt and its fix priority | [docs/technical-debt.md](docs/technical-debt.md) |

Core docs also have English translations in [docs/en/](docs/en/)
(security / runtime / evaluation / getting-started); the Chinese originals
remain authoritative.

---

## Community

- **Questions & discussions**: [GitHub Discussions](https://github.com/ccjjfdyqlhy/aicf-core/discussions)
- **Bugs & features**: [GitHub Issues](https://github.com/ccjjfdyqlhy/aicf-core/issues) (templates provided)
- **Security**: please follow [SECURITY.md](SECURITY.md) — do not open a public issue
- Paths for a first contribution: [CONTRIBUTING.md](CONTRIBUTING.md) · [docs/community.md](docs/community.md)

---

## License

Apache-2.0

---

<sub>Site: <https://ccjjfdyqlhy.github.io/aicf-core/> · 中文版: [README_zh.md](README_zh.md)</sub>
