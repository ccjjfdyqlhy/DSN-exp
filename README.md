<div align="center">

# aicf-core

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![CI](https://img.shields.io/github/actions/workflow/status/ccjjfdyqlhy/aicf-core/ci.yml?branch=main&label=CI&style=for-the-badge)](https://github.com/ccjjfdyqlhy/aicf-core/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/endpoint?url=https%3A%2F%2Fccjjfdyqlhy.github.io%2Faicf-core%2Ftests.json)](https://github.com/ccjjfdyqlhy/aicf-core/actions/workflows/ci.yml)
[![Local First](https://img.shields.io/badge/local--first-100%25-8A2BE2?style=for-the-badge)](docs/architecture.md)
[![Modalities](https://img.shields.io/badge/modalities-text%20%C2%B7%20speech%20%C2%B7%20vision-8A2BE2?style=for-the-badge)](docs/infra.md)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue?style=for-the-badge)](LICENSE)

**The floor that makes an agent unkillable.**
Specialized for companion systems — online for the long haul, responding the
moment you speak.

[English] | [简体中文](README_zh.md)

</div>

## What is aicf-core

aicf-core is agent infrastructure specialized for one job: **companion
systems that stay online for the long haul and respond the moment you
speak.** A system like that cannot go down with the machine or drop a
sentence mid-conversation — so the floor under it must be unkillable and
always awake.

Most agent frameworks assume the process stays alive. aicf-core assumes the
opposite: the process gets killed — a crash, an OOM, a deploy restart, a stray
`kill -9` — and the task still finishes. State lives in a journal, `effectful`
calls are never replayed, and another instance can take over.

Around that runtime sits everything an agent system needs before it can be
trusted: a policy gate and human approval in front of every tool call, an
audit trail the application cannot delete, layered memory, multi-agent
collaboration, local speech and vision, and an evaluation loop that decides
what may be released.

**AICF** = Agent Infrastructure Cybernetics Framework · Apache-2.0. It is a
library, not an app — applications grow on top of it, in their own
repositories (the web console is
[`aicf-ui`](https://github.com/ccjjfdyqlhy/aicf-ui)).

## Three guarantees

> **Run one long task safely, idempotently, and measurably.**

| | The guarantee | How to verify |
|---|---|---|
| **Safe** | Every tool call passes a policy gate; anything with side effects waits for a human; anything undecided is **denied**. | `aicf tool exec proc.run --args '{"command":"rm -rf /"}'` → refused |
| **Unkillable** | Kill it mid-run and it resumes where it stopped — without repeating side effects. Fault injection with a real `kill -9`: 46/46 recovered. | `pytest tests/fault/` |
| **Measurable** | Every run produces a trace; every change is scored against a dataset and can be blocked from release by a four-gate report. | `aicf eval` → `aicf gate` |

One honest caveat: tools run with the operator's privileges — path scope,
`ulimit`s and an environment whitelist are checked before a process starts,
but there is **no OS-level sandbox yet**.
[docs/security.md](docs/security.md) states exactly what is and is not
protected.

## Ninety seconds

```bash
pip install aicf-core

# scaffold a project: entry points wired, no business logic
aicf init demo && cd demo
```

Every step below runs **offline** — no API key — and the walkthrough ends green.

```bash
# 1. Try to run a shell. It has side effects — so it waits for a human.
aicf tool exec proc.run --args '{"command":"rm -rf /"}' --policy strict
#    → refused

# 2. Run a whole dataset offline: one turn, one trace per case.
aicf run --dataset offline --trace-dir traces/

# 3. Score it. A regression, a cost overrun or a safety violation stops the release.
aicf eval --dataset offline --traces traces/ --out run.json
aicf gate --run run.json --out gate.json
```

An agent in five lines:

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
print(agent.run("what is 17 + 25?"))
```

Any OpenAI-compatible endpoint works. For a local model, point `base_url` at
your `llama-server` / LM Studio.

## What is inside

```
your app / skills
   ▲
aicf/harness    turn loop · tools · context · memory · sessions · multi-agent
   ▲
aicf/infra      model routing · resource pool · storage · gateway · auth · policy
```

Dependencies point **downward only**: `harness` never imports an application,
`infra` never imports business semantics. The module map lives in
[docs/architecture.md](docs/architecture.md).

Also in the box, one line each:

- **Multi-agent** — roles, delegation, mailbox, blackboard; every delegation is on the record
- **Voice & vision** — local ASR / TTS / VLM in one scheduled pool; perception mode (silence means listening), an idle heartbeat that speaks first, a `resident` profile that keeps models warm
- **Skills** — out-of-tree packages, validated by the framework before an agent ever sees them
- **Learning loop** — trajectory → dataset → judge → promotion, gated by the same four gates

## Install

```bash
pip install aicf-core
```

> `aicf --version` must print `1.0.0` or newer. Releases before `1.0.0`
> shipped no `aicf` command; they are yanked on PyPI, but some mirrors still
> serve them — install from official PyPI:
> `pip install -U --index-url https://pypi.org/simple aicf-core`

Optional extras, installed only when you need them:

```bash
pip install "aicf-core[personality]"   # personality dynamics
pip install "aicf-core[decisions]"     # System-1 decision head
pip install "aicf-core[learning]"      # trajectory → dataset → judge → promotion
pip install "aicf-core[finetune]"      # local SFT (pulls torch)
pip install "aicf-core[mcp]"           # external MCP tool servers
pip install "aicf-core[all]"           # everything
```

## Documentation

| I want to… | Read this |
|---|---|
| Get from zero to a running agent | [docs/getting-started.md](docs/getting-started.md) |
| The module map and dependency rules | [docs/architecture.md](docs/architecture.md) |
| The security model (deny-by-default, approval, sandbox tiers, audit) | [docs/security.md](docs/security.md) |
| The managed runtime (journal, idempotency, recovery) | [docs/runtime.md](docs/runtime.md) |
| The evaluation loop (datasets, gates, regression) | [docs/evaluation.md](docs/evaluation.md) |
| The core as a library | [docs/sdk_guide.md](docs/sdk_guide.md) |
| The skill-package spec | [docs/skill-spec.md](docs/skill-spec.md) |
| Reproducible numbers | [benchmarks/README.md](benchmarks/README.md) |
| Roadmap and workstream status | [docs/roadmap_1.0.0-rc0.md](docs/roadmap_1.0.0-rc0.md) |
| Everything else | [docs/](docs/) |

Core docs also have English translations in [docs/en/](docs/en/); the Chinese
originals remain authoritative.

## Community

- **Questions & discussions**: [GitHub Discussions](https://github.com/ccjjfdyqlhy/aicf-core/discussions)
- **Bugs & features**: [GitHub Issues](https://github.com/ccjjfdyqlhy/aicf-core/issues)
- **Security**: follow [SECURITY.md](SECURITY.md) — do not open a public issue
- **First contribution**: [CONTRIBUTING.md](CONTRIBUTING.md)

## License

Apache-2.0

---

<sub>Site: <https://ccjjfdyqlhy.github.io/aicf-core/></sub>
