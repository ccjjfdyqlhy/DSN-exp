# application development guide

for people adding a feature to the web console or starting a new application.
this guide shows the supported shapes and points out code you should not copy.

## pick a shape

applications live in their own repositories and depend on `aicf-core`.
choose the smallest shape that fits:

- terminal tool with a few tools: use `AgentLoop` directly;
- terminal tool that needs history and a facade: use `AgentRuntime`;
- product with standard tools, a toolbox, or many registrations: use `AgentSpec`;
- web product with routes and lifecycle: add `AppBundle` and an HTTP layer.

| need | reference |
|---|---|
| web console with models, resources and decisions | `aicf-ui` repository |
| the three agent assembly options | this document |

a new repository starts like this:

```bash
mkdir my-app && cd my-app && git init
```

```toml
dependencies = ["aicf-core>=0.6,<0.7"]
```

hard rule: core must never depend on an application. if a change needs a
product concept inside `harness`, it belongs in the application repository or it
needs to be designed as a generic mechanism first.

## minimum application

### layout

```text
my_app/
|-- __init__.py
|-- entry.py        # launcher entry: def main()
|-- __main__.py     # python -m my_app
`-- app.py          # implementation
```

### `entry.py` and `__main__.py`

```python
# my_app/entry.py
from __future__ import annotations


def main() -> None:
    from my_app.__main__ import main as run
    run()
```

```python
# my_app/__main__.py
from __future__ import annotations


def main() -> None:
    import os

    from infra.orchestrator import OpenAICompatClient
    from my_app.app import MyApp

    client = OpenAICompatClient(
        api_key=os.environ.get("OPENAI_API_KEY", ""),
        base_url=os.environ.get("OPENAI_API_BASE", "https://api.deepseek.com/v1"),
        model=os.environ.get("MAIN_MODEL_NAME", "deepseek-chat"),
    )
    MyApp(client).run_repl()


if __name__ == "__main__":
    main()
```

## assemble an agent

### direct `AgentLoop`

```python
from harness import Tool, ToolRegistry
from harness.agent import AgentLoop
from infra.orchestrator import ChatMessage

tools = ToolRegistry()
tools.register(Tool(
    name="greet",
    description="greet a user",
    handler=lambda name: f"hello, {name}",
    parameters={"type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"]},
))

loop = AgentLoop(client, tools, max_steps=6)
result = loop.run([ChatMessage.user("greet xiaoming")], system_prompt="you are an assistant")
print(result.reply)
```

notes:

- `loop.run()` calls `asyncio.run()` internally, so it cannot run inside an
  existing event loop;
- `max_steps <= 0` means no limit;
- tool names become wire names, and a name without a dot needs no special care.

### `AgentRuntime` facade

```python
from harness import AgentRuntime

agent = AgentRuntime(
    client,
    name="my-agent",
    system_prompt="you are an assistant",
    max_steps=8,
)
result = agent.run_with_tools("look at this repository")
print(result.reply)
```

`AgentRuntime` builds `Runtime`, `Settings`, `ToolRegistry` and `Conversation`
for you. add tools with `agent.register_tool(...)`.

`AgentRuntime` writes memory but does not read it back into the context. manage
the context yourself if you need real recall.

### declarative `AgentSpec`

```python
from harness.agent import AgentAssembler, AgentSpec

spec = AgentSpec(
    name="code-assistant",
    system_prompt="you are a senior engineer",
    tools="standard",
    toolbox={"enabled": True},
    max_steps=12,
    workspace=".",
)
agent = AgentAssembler(client).assemble(spec)
print(agent.run("list the current directory").reply)
```

`AgentSpec.router` and `AgentSpec.budget` are assembled but not applied. see
[technical-debt.md](technical-debt.md) for the open item.

| situation | use |
|---|---|
| learning, simple logic, full control | `AgentLoop` |
| history plus a small facade | `AgentRuntime` |
| standard tools, toolbox, many registrations | `AgentSpec` |

## register tools

### generate a schema from a function

```python
from harness import tool


@tool
def read_config(path: str, section: str = "default") -> dict:
    """Read one section of a config file."""
    ...
```

the schema comes from type annotations and the docstring. limits:

- `list` and `dict` produce `{"type": "array"}` and `{"type": "object"}` without
  item schemas;
- `Optional`, `Union` and `Literal` collapse to `string`.

build `Tool(...)` and write `parameters` by hand when you need exact control.

### return values

returning a dict or a string wraps it as `ToolResult.ok(...)`. to show the model
why a call failed and what to try next, return `ToolResult.fail(...)` or
`ToolResult.retry(...)`. `status` and `hint` go back to the model with the
result.

## write a web application

```python
from flask import Flask

from harness import AgentRuntime, AppBundle, AppBundleRegistry, Runtime, Settings
from infra.orchestrator import ModelProviderRegistry, OpenAICompatClient


def create_application():
    app = Flask(__name__)

    runtime = Runtime(name="my_web_app")
    runtime.register("settings", Settings())
    runtime.set_default()

    providers = ModelProviderRegistry()
    providers.register_chat("openai", lambda: OpenAICompatClient(...))
    runtime.register("model_provider", providers)

    agent = AgentRuntime(providers.get_chat_client("openai"), name="my-agent")
    runtime.register("agent", agent)

    from my_app.api import bp
    app.register_blueprint(bp)

    bundles = AppBundleRegistry(runtime)
    bundles.add(MyBundle())
    bundles.install_all()
    runtime.start()
    bundles.start_all()
    return app
```

override only the lifecycle methods you need:

```python
from harness import AppBundle


class MyBundle(AppBundle):
    name = "my"
    version = "0.1"

    def install(self, runtime):
        runtime.register("my_service", MyService())

    def start(self, runtime):
        runtime.get("my_service").warm_up()

    def stop(self):
        ...
```

## write a skill

a skill is a loadable bundle of tools and prompt text:

```text
skills/builtin/my_skill/
|-- skill.yaml
|-- prompts/
|   `-- instruction.md
`-- tools/
    `-- my_tools.py
```

`skill.yaml` looks like this:

```yaml
name: my_skill
display_name: my skill
description: what this skill does
activation:
  auto_activate: false
  keywords: [keyword1, keyword2]
tools:
  - name: my_tool
    module: tools.my_tools
    class: MyTool
```

`harness/skills/` provides the base classes and the loader. an application can
register semantic capabilities for dependency injection, as described in
[skills.md](skills.md).

## avoid

| location | problem |
|---|---|
| shell tools with `shell=True` and no path check | arbitrary command execution |
| calculator tools built on `eval` with a character allowlist | trivially bypassed |
| large modules of globals forwarded through several layers | hard to trace and test |
| `except Exception: pass` | hides the failure and makes support impossible |
| one file that registers every route | fragile catch-all ordering |
| two nearly identical stream and invoke branches | fixes land in one branch only |

## checklist

- [ ] `entry.py` exposes `main()` and `__main__.py` calls it
- [ ] imports use `aicf_*` package paths, not `apps.*`
- [ ] model clients come from `infra.orchestrator`
- [ ] tools are registered in `ToolRegistry`, not called directly from business code
- [ ] long tasks get a sensible `max_steps`; remember that 0 means no limit
- [ ] configuration comes from environment variables with defaults in one module
- [ ] the repository has a test for the new behavior
- [ ] the repository documents its entry point and port
