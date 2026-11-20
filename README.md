<div align="center">
<img src="docs/header.svg" width="1200" alt="aicf-core — the agent engine behind your local agent">
</div>

# aicf-core

> **The engine, not the app.** A scenario-agnostic agent core: turn loop, tool protocol,
> context assembly, memory, sessions, multi-agent collaboration — and nothing else.

**AICF** = Agent Infrastructure Cybernetics Framework · Apache-2.0

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Local First](https://img.shields.io/badge/local--first-100%25-8A2BE2?style=for-the-badge)](docs/architecture.md)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue?style=for-the-badge)](LICENSE)
[![CI](https://github.com/ccjjfdyqlhy/aicf-core/actions/workflows/ci.yml/badge.svg)](https://github.com/ccjjfdyqlhy/aicf-core/actions/workflows/ci.yml)

---

## One promise

> **Run one long task safely, idempotently, and measurably.**

Most agent frameworks assume the process lives. This one assumes it will not.

| | The claim | How you can check it |
|---|---|---|
| **Safe** | Every tool call goes through a policy gate, an approval step when the tool has side effects, and a sandbox. Anything undecided is **denied**. | `aicf tool exec proc.run --args '{"command":"rm -rf /"}'` → refused |
| **Idempotent** | A crashed run can be resumed without repeating side effects. `effectful` calls are never auto-replayed. | `pytest tests/fault/` — real `kill -9` in a subprocess |
| **Measurable** | Every run produces a trace; every change is scored against a dataset and stopped by a four-gate report. | `aicf eval` → `aicf gate` |

---

## Ninety seconds

```bash
pip install aicf-core
```

```bash
# 1. What does each tool actually do? Effect level, sandbox tier, required scopes.
aicf tool list

# 2. Try to run a shell. It has side effects — so it waits for a human.
aicf tool exec proc.run --args '{"command":"rm -rf /"}' --policy strict
#    Error: 工具 proc.run 被策略拒绝（approval）：CLI 未开启 --yes

# 3. Run one turn. It leaves a trace.
aicf run "summarize this repo" --trace trace.jsonl

# 4. Score a dataset (it ships with the package). Traces are matched to cases
#    by --case-id, so a dataset run records one trace per case:
#      aicf run "<input>" --case-id <case_id> --trace traces/<case_id>.jsonl
aicf eval --dataset basic --traces traces/ --out run.json

# 5. Stop the release if anything regressed, got too expensive, or broke a rule.
aicf gate --run run.json --out gate.json
```

No API key required for any of the above — it runs offline against a stub model.

One honest caveat: the stub model never calls a tool, so the dataset cases
**do not pass locally**. `aicf gate` is a CI device: it expects one trace per
case (that is what `--case-id` is for) and blocks a release whose critical
cases are missing.

---

## Install

```bash
pip install aicf-core
```

That is the whole library — the agent kernel and the model/tool/runtime layer.
It has **no application code and no UI**: the web console lives in its own repository
([`aicf-ui`](https://github.com/ccjjfdyqlhy/aicf-ui)).

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
from aicf.harness import create_agent, tool   # the three you write with
from aicf.harness.tools import ToolRegistry   # when you manage tools yourself
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

## The repo in 30 seconds

Two layers, dependencies pointing **downward only**:

```
aicf/harness/   Agent core    turn loop · tools · context · memory · pipeline · sessions · SDK
    │                        knows nothing about any product
    ▼
aicf/infra/     Infra         model routing · resource pool · storage · gateway · auth · policy
```

```
apps/  →  gone. The web console now lives in its own repository:
```

| Repository | What it is |
|---|---|
| [`aicf-ui`](https://github.com/ccjjfdyqlhy/aicf-ui) | Web console — models, chat, resources, System-1 decisions |

It depends on `aicf-core` and nothing else.

---

## Status

`aicf-core` is at **1.0.0rc3**. The definition of done for rc0 is three
executable claims, and all three hold (each one is pinned to a test):

1. an agent that is `kill -9`'d once still resumes and produces the right answer;
2. every tool call was either approved or refused — with an audit trail;
3. the run can be scored by a ≥30-case dataset and produce a four-gate report.

**Those guarantees hold on the default paths.** An agent built with
`create_agent` comes with a guard, `proc.run` executes inside a workspace
sandbox, and both the SDK and the CLI write the tool intents into the journal
— so after a crash the runtime can tell which side effects may already have
happened.

**rc3** closes the six items the rc0 roadmap listed as missing: the control
plane, the workflow and planner kernels, agent identity with delegation, the
sampling loop with bad case feedback, the scheduler with the workspace
isolation, and the audit trail the business cannot delete. The release note is
[docs/releases/v1.0.0rc3.md](docs/releases/v1.0.0rc3.md).

What is left is the isolated sandbox (a container or a micro vm) and the
deployment matters: the cross machine orchestration and the transport of the
runtime you bring yourself. The plan, the acceptance criteria and the status
of each workstream live in
[docs/roadmap_1.0.0-rc0.md](docs/roadmap_1.0.0-rc0.md).

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
| Know what 1.0.0-rc0 is doing and how it is verified | [docs/roadmap_1.0.0-rc0.md](docs/roadmap_1.0.0-rc0.md) |
| Learn the module map and dependency rules | [docs/architecture.md](docs/architecture.md) |
| Understand the security model (deny-by-default, approval, sandbox, audit) | [docs/security.md](docs/security.md) |
| Understand the managed runtime (journal, checkpoint, idempotency, recovery) | [docs/runtime.md](docs/runtime.md) |
| Understand the evaluation loop (dataset, gates, run versions, regression) | [docs/evaluation.md](docs/evaluation.md) |
| Use the core as a library | [docs/sdk_guide.md](docs/sdk_guide.md) |
| Go deeper into the agent loop / tools / context | [docs/harness.md](docs/harness.md) |
| Go deeper into model routing / resources / storage | [docs/infra.md](docs/infra.md) |
| Know which traps not to step into before changing code | [docs/maintenance.md](docs/maintenance.md) |
| Configuration keys / environment variables | [docs/configuration.md](docs/configuration.md) |
| Known tech debt and its fix priority | [docs/technical-debt.md](docs/technical-debt.md) |

---

## License

Apache-2.0
