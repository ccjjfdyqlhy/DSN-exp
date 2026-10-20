# AICF SDK 嵌入指南

> 读者：想在**自己的 Python 项目**里用 AICF，而不是跑仓库里的应用的人。
> SDK 的导入包名是 `harness`，分发名是 `aicf`。

---

## 一、安装与引入

```bash
pip install -e .        # 在仓库根目录，以可编辑模式安装
```

```python
from harness import create_agent, tool, Agent
```

> `pip install -e .` 只安装 **框架**（`harness` + `infra`）与其最小依赖
> （openai / requests / PyYAML / python-dotenv）。
> 需要 Flask / FastAPI 等应用依赖时，装 `pip install -e .[full]` 或直接用 `requirements.txt`。

---

## 二、最小用法

### 2.1 创建 Agent

```python
from harness import create_agent

agent = create_agent(
    model="deepseek-chat",
    api_key="sk-...",
    base_url="https://api.deepseek.com/v1",   # 任何 OpenAI 兼容端点
    system_prompt="你是一个代码分析助手。",
)

print(agent.chat("你好！"))
print(agent.chat("我刚才说了什么？"))   # 自动维持多轮历史
```

`create_agent` 的完整参数：

| 参数 | 说明 |
|---|---|
| `model` | 模型名（默认 `gpt-4o-mini`） |
| `api_key` / `base_url` | 端点凭据；留空则读环境变量 |
| `client` | 直接传入自定义 `IChatClient`（优先于上面三项） |
| `system_prompt` | 系统提示词 |
| `tools` | `"standard"` / 函数列表 / `Tool` 列表 |
| `max_steps` | 工具调用最大步数（默认 8；**0 或负数 = 不限制**） |
| `workspace` | 标准文件工具的根目录 |
| `budget_cap` / `token_cap` | 预算与 Token 上限 |
| `enable_toolbox` | 两阶段工具激活（工具多时防 prompt 爆炸） |
| `enable_memory` | 启用向量记忆 |

### 2.2 定义工具

```python
from harness import create_agent, tool

@tool
def get_user_info(user_id: int) -> str:
    """根据用户 ID 查询用户信息"""
    return f"User {user_id}: Alice (VIP)"

@tool
def calculate_discount(price: float, rate: float) -> float:
    """计算折后价格"""
    return price * rate

agent = create_agent(model="gpt-4o", tools=[get_user_info, calculate_discount])
print(agent.chat("查一下用户 1001，并算算 500 打八折"))
```

schema 由**类型注解 + docstring** 自动生成。限制：`list`/`dict` 不带 items，
`Optional`/`Union` 退化�� string。需要精确控制时直接构造 `Tool(...)` 手写 schema。

运行时追加工具：`agent.add_tool(fn)`。

### 2.3 流式输出

```python
import asyncio
from harness import create_agent

agent = create_agent(model="deepseek-chat")

async def main():
    async for event in agent.chat_stream("写一首关于秋天的五言绝句"):
        if event.kind == "delta":
            print(event.content, end="", flush=True)
        elif event.kind == "tool_call":
            print(f"\n[调用工具: {event.tool_call['name']}]")
        elif event.kind == "done":
            print("\n[完成]")

asyncio.run(main())
```

`StreamEvent.kind` 实际有 **9 种**：`round_start` `delta` `reasoning` `tool_call`
`tool_result` `reply` `done` `timings` `usage`。
**消费端请按「未知 kind 忽略」来写**，不要枚举断言。

### 2.4 无状态单次任务

```python
result = agent.run("分析这段日志是否存在异常：[ERROR] Timeout connecting to DB")
print(result.reply)
print(f"工具调用 {len(result.tool_executions)} 次")
```

`AgentRunResult` 字段：`reply` / `tool_executions` / `steps` / `hit_max_steps`。

> ⚠️ `steps` 是**推导值**（`len(tool_executions) + 1`），不是真实轮数。

---

## 三、预算与工具箱参数的实际状态

```python
agent = create_agent(
    model="deepseek-chat",
    token_cap=100000,
    budget_cap=0.5,
    enable_toolbox=True,
)
```

| 参数 | 状态 |
|---|---|
| `enable_toolbox` | ✅ **真正生效**，两阶段激活会改变下发的 schema |
| `enable_memory` | ⚠️ 会创建记忆存储，但记忆**不会进入上下文** |
| `token_cap` / `budget_cap` | ⚠️ 会被组装成 `TokenBudget`，但 **AgentLoop 不检查预算** |

这是诚实的状态说明。需要真正的预算控制，请在应用层自己计量
（参考 `infra/policy/token_meter.py` 的 `TokenMeter`，手动在每轮后 `record()`）。

---

## 四、用自己的客户端

任何满足 `IChatClient` 协议的对象都能传进来：

```python
from infra.orchestrator.base import IChatClient, ChatMessage, ChatResponse
from harness import create_agent

class MyClient:
    model = "my-model"
    def invoke(self, messages, tools=None, *, temperature=0.7, max_tokens=4096, timeout=300):
        return ChatResponse(content="我的回答", tool_calls=[])
    async def stream(self, messages, tools=None, **kw):
        yield "分片1"
        yield "分片2"

agent = create_agent(client=MyClient())
```

这在测试里非常有用——仓库自带的 `StubChatClient` 就是这么用的。

---

## 五、直接用底层组件

不想用 `create_agent` 时，可以自己拼装：

```python
from harness.agent import AgentLoop
from harness import ToolRegistry, Tool
from infra.orchestrator import ChatMessage, OpenAICompatClient

client = OpenAICompatClient(model="...", api_key="...", base_url="...")
tools = ToolRegistry()
tools.register(Tool(name="echo", description="回显",
                    handler=lambda text: text,
                    parameters={"type":"object",
                                "properties":{"text":{"type":"string"}},
                                "required":["text"]}))

loop = AgentLoop(client, tools, max_steps=5)
result = loop.run([ChatMessage.user("echo 你好")])
```

> ⚠️ `loop.run()` 内部是 `asyncio.run()`，**不能在已有事件循环里调用**；
> 在 async 环境请用 `await loop.run_async(...)`。

---

## 六、常用底层组件速查

| 想要 | 导入 |
|---|---|
| 上下文预算剪裁 | `from harness import ContextBudget, SegmentedContextAssembler` |
| 模块化提示词 | `from harness import PromptEngine, PromptFragment` |
| 标准工具集 | `from harness import install_standard_tools, ToolDeps` |
| @ 指令采集 | `from harness import ContextGatherer` |
| 会话管理 | `from harness import Conversation, ConversationManager` |
| 依赖注入 | `from harness import Runtime` |
| 配置命名空间 | `from harness import Settings` |
| 持久化 | `from infra.store import SessionStore, SqliteStore` |
| 用量统计 | `from infra.observability import UsageTracker` |
| 模型路由策略 | `from infra.policy import ModelRouter, TokenMeter, TokenBudget` |

---

## 七、注意事项

1. **单例副作用**：`infra.orchestrator` 里有 `ModelOrchestrator` / `ModelScheduler` 两个
   进程级单例。若你在同一进程里既用 SDK 又用别的方式建模型，注意它们会互相影响。

2. **`run()` 与事件循环**：同步 API 内部 `asyncio.run`，异步上下文请用 `*_async` 版本。

3. **工具名编码**：带命名空间的工具名（如 `file.read`）会被编码成 `file__read` 发给模型，
   调用时自动还原。你自己的客户端实现如果不是 OpenAI 语义，要注意这一点。

4. **不要 import `apps.*`**：SDK 的价值就在于只依赖 `harness` + `infra`。
   `apps/` 下的任何东西都不应该出现在你的项目里。
