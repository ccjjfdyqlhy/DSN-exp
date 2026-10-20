# 应用开发指南

> 读者：要给现有应用加功能，或要从零写一个新应用的人。
> 本文给出**推荐的写法**，并明确指出哪些现存代码**不要抄**。

---

## 一、先选路线

```
你要做的东西需要 Web 界面吗？
  ├─ 是 → 需要多子系统 + 技能吗？
  │        ├─ 是 → 照 dsn_study 写（Runtime + AppBundle + FlaskGateway）
  │        └─ 否 → 照 dsn_ui 写（FastAPI），但注意它不走 AppBundle
  └─ 否 → 终端工具？
           ├─ 简单 → 照 coding_agent 写（AgentRuntime + 工具）
           └─ 极简 → 照 text_agent 写（Runtime + AgentLoop）
```

| 你的需求 | 参考实现 | 行数 |
|---|---|---:|
| 学会最小可用组合 | `apps/text_agent` | 106 |
| 加工具、加持久化 | `apps/coding_agent` | 186 |
| 加人格 / 情绪 / 话题 | `apps/emotion_exp` | 836 |
| 加 Web + 技能 + 多子系统 | `apps/dsn_study` | 10k |

---

## 二、最小可用应用（照着改）

### 2.1 结构

```
apps/my_app/
├── __init__.py
├── entry.py        # 供 launcher 调用：def main()
├── __main__.py     # 供 python -m apps.my_app 调用
└── app.py          # 真正的实现
```

### 2.2 `entry.py` 与 `__main__.py`

```python
# apps/my_app/entry.py
from __future__ import annotations

def main() -> None:
    from apps.my_app.__main__ import main as run
    run()
```

```python
# apps/my_app/__main__.py
from __future__ import annotations

def main() -> None:
    from infra.orchestrator import OpenAICompatClient
    from apps.my_app.app import MyApp
    import os

    client = OpenAICompatClient(
        api_key=os.environ.get("OPENAI_API_KEY", ""),
        base_url=os.environ.get("OPENAI_API_BASE", "https://api.deepseek.com/v1"),
        model=os.environ.get("MAIN_MODEL_NAME", "deepseek-chat"),
    )
    MyApp(client).run_repl()

if __name__ == "__main__":
    main()
```

### 2.3 注册到启动器

在 `apps.yaml` 里加一段（**不是**改 `launcher.py`——yaml 是推荐方式）：

```yaml
my_app:
  entry: apps.my_app.entry
  description: 我的应用
```

```bash
python main.py --list            # 确认已注册
python main.py --app my_app
```

> `launcher.py` 里有一份内置清单，`apps.yaml` 用 `setdefault` 合并；
> **内置清单优先**。所以新应用只能通过 yaml 注册。

---

## 三、装配 Agent 的三种写法

### 3.1 最简：直接用 `AgentLoop`（推荐入门）

```python
from harness import Tool, ToolRegistry
from harness.agent import AgentLoop
from infra.orchestrator import ChatMessage

tools = ToolRegistry()
tools.register(Tool(
    name="greet",
    description="问候用户",
    handler=lambda name: f"你好，{name}",
    parameters={"type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"]},
))

loop = AgentLoop(client, tools, max_steps=6)
result = loop.run([ChatMessage.user("向小明问好")], system_prompt="你是助手")
print(result.reply)
```

**要点**：

- `loop.run()` 内部是 `asyncio.run()`，**不能在已有事件循环里调用**；
- `max_steps <= 0` 表示不限制；
- 工具名会被编码成 wire 名（`greet` 没有点号，无需关心）。

### 3.2 中等：用 `AgentRuntime` 门面

```python
from harness import AgentRuntime

agent = AgentRuntime(
    client,
    name="my-agent",
    system_prompt="你是一名助手",
    max_steps=8,
)
result = agent.run_with_tools("帮我看看这个仓库")
print(result.reply)
```

`AgentRuntime` 已经帮你建好 `Runtime` / `Settings` / `ToolRegistry` / `Conversation`。
加工具用 `agent.register_tool(...)`（见 `apps/coding_agent/app.py:42`）。

> ⚠️ `AgentRuntime` 的**记忆只写不读**——写入的记忆不会进入上下文。
> 需要真正的记忆请自己管理上下文。

### 3.3 声明式：用 `AgentSpec`

```python
from harness.agent import AgentAssembler, AgentSpec

spec = AgentSpec(
    name="code-assistant",
    system_prompt="你是一名资深工程师",
    tools="standard",              # 18 个标准工具
    toolbox={"enabled": True},     # 两阶段激活
    max_steps=12,
    workspace=".",
)
agent = AgentAssembler(client).assemble(spec)
print(agent.run("列出当前目录").reply)
```

> ⚠️ `AgentSpec` 的 `router` / `budget` 字段**会被组装但不生效**。
> 见 [technical-debt.md](technical-debt.md#p1-1-token-经济闭环未接入)。

**三种写法怎么选**：

| 场景 | 用哪个 |
|---|---|
| 学习 / 逻辑简单 / 完全自定义 | `AgentLoop` 直接 |
| 需要会话历史与少量便利 | `AgentRuntime` |
| 需要标准工具集 / toolbox / 大量注册 | `AgentSpec` |

---

## 四、注册工具

### 4.1 从函数自动生成（推荐）

```python
from harness import tool

@tool
def read_config(path: str, section: str = "default") -> dict:
    """读取配置文件的某一节。"""
    ...
```

schema 由**类型注解 + docstring** 自动生成。注意限制：

- `list` / `dict` 只生成 `{"type": "array"}` / `{"type": "object"}`，**不带 items**；
- `Optional[...]` / `Union` / `Literal` 一律退化成 `string`。

需要精确控制 schema 时，直接构造 `Tool(...)` 并手写 `parameters`。

### 4.2 返回值约定

返回 dict 或字符串即可，会被包成 `ToolResult.ok(...)`。
想让模型看到**失败原因与下一步提示**，返回 `ToolResult.fail(...)` 或 `ToolResult.retry(...)`——
`status` 与 `hint` 会一并回喂给模型，这是本项目工具系统的一个特色。

---

## 五、写一个 Flask Web 应用（照 dsn_study）

完整装配链：

```python
from flask import Flask
from harness import Runtime, Settings, AgentRuntime, AppBundle, AppBundleRegistry
from infra.gateway import FlaskGateway
from infra.orchestrator import ModelProviderRegistry, OpenAICompatClient

def create_application():
    app = Flask(__name__)

    # 1. 依赖注入容器
    rt = Runtime(name="my_web_app")
    rt.register("settings", Settings());
    rt.set_default();

    # 2. 模型提供者注册表
    reg = ModelProviderRegistry()
    reg.register_chat("openai", lambda: OpenAICompatClient(...))
    rt.register("model_provider", reg)

    # 3. Agent
    agent = AgentRuntime(reg.get_chat_client("openai"), name="my-agent")
    rt.register("agent", agent)

    # 4. 路由蓝图
    from apps.my_app.api import bp
    app.register_blueprint(bp)

    # 5. AppBundle 生命周期
    bundles = AppBundleRegistry(rt)
    bundles.add(MyBundle())
    bundles.install_all()
    rt.start()
    bundles.start_all()
    return app
```

`AppBundle` 的子类只需覆写需要的方法：

```python
from harness import AppBundle

class MyBundle(AppBundle):
    name = "my"
    version = "1.0"

    def install(self, runtime):
        runtime.register("my_service", MyService())

    def start(self, runtime):
        runtime.get("my_service").warm_up()

    def stop(self):
        ...
```

> 真实范例见 `apps/dsn_study/boot.py`，它顶部的注释就是完整装配顺序的提纲。

---

## 六、写一个技能

技能是「一组工具 + 一段提示词」的可装卸单元。目录结构：

```
skills/builtin/my_skill/
├── skill.yaml
├── prompts/
│   └── instruction.md
└── tools/
    └── my_tools.py
```

`skill.yaml` 大致形状（字段以 `apps/dsn_study/skills/builtin/*/skill.yaml` 为准）：

```yaml
name: my_skill
display_name: 我的技能
description: 这个技能能做什么
activation:
  auto_activate: false        # 靠关键词触发两阶段 toolbox 激活
  keywords: [关键词1, 关键词2]
tools:
  - name: my_tool
    module: tools.my_tools
    class: MyTool
```

**注意**：`apps/dsn` 与 `apps/dsn_study` 各有一套技能加载器，接口不完全相同；
`harness/skills/` 里的 `Skill` / `SkillRegistry` 是基类，应用侧各自重写了实现。
新写技能前先确认目标应用的加载器。

---

## 七、不要抄的地方

以下现存代码**存在安全问题或反模式**，写新应用时请避开：

| 位置 | 问题 |
|---|---|
| `apps/coding_agent/skills.py` 的 `run_bash` | `shell=True` 且无路径校验 |
| `apps/text_agent/app.py` 的 `_calc` | 用 `eval`，靠字符白名单防护 |
| `apps/dsn/boot.py` | 20+ 个模块级全局，被三层转发（`api/app.py` → `main.py`） |
| `apps/dsn` 的 `except Exception: pass` 风格 | 静默吞异常，排障极难 |
| `apps/dsn_ui/server.py` 的路由注册方式 | 3000 行单文件集中注册，注意 catch-all 顺序 |
| `apps/dsn_ui/agent.py` 的 `chat_stream` / `chat_invoke` | 两份重复分支逻辑，容易改漏 |

---

## 八、新应用的检查清单

- [ ] 有 `entry.py`（`main()`）和 `__main__.py`；
- [ ] 在 `apps.yaml` 注册，`python main.py --list` 能看到；
- [ ] 不 import `apps.dsn.main`（会在导入期触发 onboarding）；
- [ ] 模型客户端来自 `infra.orchestrator`，不是自己再造一套；
- [ ] 工具注册进 `ToolRegistry`，而不是在业务码里硬编码调用；
- [ ] 长任务给 `max_steps` 一个合理值（注意 0 = 不限制）；
- [ ] 配置文件读环境变量，默认值写在 `config.py`；
- [ ] 加一个 `tests/test_<app>.py`；
- [ ] 在 README 的应用表里登记。
