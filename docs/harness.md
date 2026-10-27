# harness/ —— Agent 核心层

> 读者：要修改 Agent 行为（循环、工具、上下文、管线）的维护者。
> 这一层**不认识任何业务**：它只处理“消息进、事件出”。业务语义属于 `apps/`。

---

## 一、核心对象与它们的关系

```
AgentAssembler            AgentLoop                 ToolRegistry
  (装配 spec)      ──►    (轮次循环)         ──►   (工具表)
                              │                        │
                              │ 用 IChatClient 调模型   │ ToolboxManager 两阶段激活
                              ▼                        ▼
                        infra IChatClient         Tool.run_async()
```

最简可用形态（来自 `harness/sdk.py`）：

```python
from harness import create_agent, tool

@tool
def add(a: int, b: int) -> int:
    """两数相加"""
    return a + b

agent = create_agent(model="deepseek-chat", api_key="sk-...", tools=[add])
print(agent.chat("计算 123 + 456"))
```

---

## 二、AgentLoop：一次任务怎么跑完

文件：`harness/agent/loop.py`

### 2.1 三条执行路径

| 方法 | 用途 | 是否流式 | 是否有收束轮 |
|---|---|---|---|
| `run(messages)` | 同步，内部 `asyncio.run` | 否 | 是 |
| `run_async(messages)` | 异步，原生工具调用 | 否 | 是 |
| `run_stream(messages)` | 异步流式，产 `StreamEvent` | 是 | 是 |
| `run_rounds(round_runner, state)` | **通用骨架**，由应用提供每轮策略 | 否 | **否** |

> `run_rounds` 是超集能力：DSN 应用的引擎用它来驱动自己的轮次策略
> （见 `apps/dsn/plugins/pipeline.py` 的 `_dsn_agent_round`）。它只负责
> 步数迭代与 `on_progress` 生命周期，每轮做什么完全由调用方决定。

### 2.2 原生路径的控制流

```
msgs = [system_prompt] + messages
schema = adapter.build_tools_schema(tools)      # 或 toolbox.build_schema(activated)

while max_steps <= 0 or step < max_steps:      # max_steps<=0 表示不限制
    response = await client.invoke(msgs, schema)
    parsed   = adapter.parse(response)          # 拆成 (文本, tool_calls)
    wire 名还原为内部名（file__read → file.read）

    if 没有 tool_calls:                          # 完成
        final_reply = parsed.text; break

    if toolbox 启用:                             # 先处理 toolbox 索引调用
        tool_calls, toolbox_results = toolbox.handle_calls(tool_calls)

    for tc in tool_calls:                       # 逐个执行
        result = await tool.run_async(**tc.arguments)
        executions.append(...)

    msgs += [assistant(tool_calls), *tool_results]   # 回喂

    if step >= max_steps - 1:                   # 最后一轮
        收束轮 → 禁止工具，强制给结论 → break
    step += 1
```

### 2.3 四个容易误解的地方

**① `max_steps <= 0` 表示不限制。** 这不是 bug，是刻意设计（`loop.py:203`）。
界面上的「最大步数」填 0 或负数即无限执行。

**② 收束轮（finalize）。** 步数耗尽时若模型还在调工具，答案会“戛然而止”。
因此 `_finalize_after_max_steps()`（`loop.py:494`）会追加一条收束指令，
并以**空 tools schema** 再调一次模型，强制它给结论。收束失败会静默降级
（`loop.py:537` 的 `except` 只 warning），最终回退为占位文本
「…[已达到步数上限，且未能生成收束答复…]」。

> ⚠️ **已知缺陷**：收束轮把 user 消息直接追加在 tool 消息之后，违反大多数
> Jinja chat_template 的角色交替要求（`tool` 之后必须是 `assistant`）。
> 部分模型会因此抛错，正好被上面的 `except` 吞掉 → 用户看到占位文本。
> 详见 [technical-debt.md](technical-debt.md#p0-1-收束轮的角色序列非法)。

**③ `StreamEvent.kind` 的实际取值比 docstring 多。** docstring 列了 6 种，
实际共 **9 种**：`round_start` `delta` `reasoning` `tool_call` `tool_result`
`reply` `done` `timings` `usage`（`loop.py:350-492`）。
消费端请按「未知 kind 直接忽略」来写。

**④ `AgentRunResult.steps` 是推导值，不是真实轮数。**
它由 `len(executions) + 1` 推算（`loop.py:280`），工具调用行为不同的两轮可能得到
不同的 steps。需要精确轮数请自己计数。

### 2.4 工具调用参数分片合并

不同 provider 的流式 tool_calls 行为不一致（真分片 / 累积值 / 完整重发），
`_merge_tool_arguments()`（`loop.py:28`）兼容三种情形。**改这里前先读懂那段注释**，
判断顺序很关键：必须先识别“新片段是完整 JSON”，否则会被错误地当成分片拼接。

---

## 三、AgentSpec：声明式装配

文件：`harness/agent/assembler.py`

`AgentSpec` 只有 **11 个字段**，一个 spec 描述一个 Agent 的完整行为：

```python
spec = AgentSpec(
    name="code-assistant",
    system_prompt="你是一名资深工程师。",
    prompts_dir="prompts/",
    max_steps=8,
    workspace=".",
    tools="standard",          # 或 list[Tool] / 自定义注册表
    toolbox={"enabled": True}, # 两阶段工具激活
    router={...},               # ModelRouter 配置
    budget={"token_cap": 200000, "cost_cap": 0.5},
    memory=True,
    model="gpt-4o-mini",
)
agent = AgentAssembler(client).assemble(spec)
result = agent.run("帮我看看这个仓库");
```

`AssembledAgent` 暴露 `loop` / `tools` / `run()` / `run_async()`。

> ⚠️ **已知缺口**：`router` 与 `budget` 会被组装，但**并未真正接线到循环**
> （`AssembledAgent.run` 里的 `meter.record({})` 是空占位）。
> 也就是说 Token 经济闭环目前是**设计完成、接入未完成**的状态。
> 详见 [technical-debt.md](technical-debt.md#p1-1-token-经济闭环未接入)。

---

## 四、工具系统

文件：`harness/tools/`

### 4.1 三个基础对象

| 对象 | 作用 |
|---|---|
| `Tool` | 名字 + 描述 + JSON Schema + 执行函数（支持同步/异步） |
| `ToolResult` | `success` / `output` / `error` / `status` / `hint`，**状态会回喂模型** |
| `ToolRegistry` | 注册、查找、`replace=True` 覆盖、`names()` 列举 |

`tool_from_function()`（`function_tool.py`）把普通函数按**类型注解 + docstring**
自动生成 schema，`@tool` 装饰器就是它的语法糖。

### 4.2 wire 名编码

模型看到的工具名必须是扁平字符串（不少 provider 不接受带点的名字），
因此内部名 `file.read` 会编码成 wire 名 `file__read`，调用时再还原。
**这是隐式约定**：跨 provider 透传工具时要注意命名空间会被压平。

### 4.3 两阶段 toolbox 激活

工具过多会让 prompt 爆炸。`ToolboxManager` 的做法是：

```
第 1 阶段：只下发「索引工具」，模型可查询有哪些工具可用
第 2 阶段：模型确认后，把真正需要的工具 schema 加入激活集合
```

启用方式：`AgentSpec(toolbox={"enabled": True})` 或 SDK 的 `enable_toolbox=True`。
在 `AgentLoop` 里表现为每轮重算 `build_schema(activated)`。

### 4.4 18 个标准工具（`harness/tools/standard.py`）

| 命名空间 | 工具 |
|---|---|
| `file` | `read` `write` `edit` `list` `tree` |
| `text` | `chunk` `extract_json` `diff` |
| `code` | `syntax_check` `locate_symbol` `diagnose` |
| `proc` | `run`（带超时与输出截断） |
| `web` | `fetch` |
| `project` | `summary` `snapshot` `todo` |
| `batch` | `run`（批量执行已注册工具） |
| `cache` | `recall` |

注册：`install_standard_tools(registry, deps=ToolDeps(...), include=["file"])`。
`ToolDeps` 注入 workspace、codegraph 等依赖——标准工具**不读全局**，依赖全部显式传入。

`file.edit` 有两种定位方式：行号 `target='path:10-20'`，或内容锚点
`target='path' + match='<old text>'`（**推荐**，抗 read 截断，且要求 match 唯一）。

### 4.5 外部 MCP 工具源（`harness/tools/mcp.py`）

把外部 MCP（Model Context Protocol）服务器的工具接入 `ToolRegistry`：
远端工具以 `mcp.<服务器名>.<工具名>` 注册，inputSchema 原样透传，
AgentLoop / ToolboxManager / wire 名编码对它们完全无感。

```
MCPManager ──┬─ stdio 子进程（uvx/npx 拉起的社区服务器）
             ├─ Streamable HTTP（transport: http）
             └─ 旧版 HTTP+SSE（transport: sse）
```

**三种入口**（效果等价）：

```python
# 1. SDK 参数
agent = create_agent(..., mcp_config="mcp_servers.yaml")
agent = create_agent(..., mcp_servers=[{"name": "fetch", "transport": "stdio",
                                        "command": "uvx", "args": ["mcp-server-fetch"]}])
# 2. AgentSpec 声明
spec = AgentSpec(..., mcp={"config": "mcp_servers.yaml", "servers": [...]})
# 3. 直接用管理器
manager = MCPManager.from_yaml("mcp_servers.yaml")
await manager.load_tools(registry)
```

**惰性连接是刻意的设计**（理解不了这里就会踩坑）：

- `assemble()` 是同步的，而 MCP 会话绑定事件循环（stdio 子进程随循环销毁），
  所以装配期**只创建管理器、零连接**；
- SDK 的 `Agent` 在首个异步入口（`chat_async` / `run_async` / `chat_stream`）
  自动完成「连接 + list_tools + 注册」；服务端可用 `await agent._assembled.setup_mcp()`
  在 lifespan 里显式预热；
- 同步 `chat()` 每次对话是独立的事件循环，stdio 子进程在对话结束即被回收，
  下次调用靠 handler 里的**重连一次机制**自动恢复 —— 功能正确但每次重启子进程，
  长驻服务请用异步入口。

**失败隔离与超时**：单台服务器连不上只影响它自己的工具（`manager.status()`
可查各服务器状态）；单次调用超时返回 `ToolResult.retry`；非超时异常自动重连
一次再试。`tool_allowlist` / `tool_blocklist` 控制注册范围。

**已知限制**：工具结果里的 Image / EmbeddedResource 内容目前只回传计数
（`images_omitted` / `resources_omitted`），不直接喂图——等前端支持多模态
工具结果后再放开。服务器端工具变更（`tools/list_changed`）不自动感知，
调 `await manager.refresh()` 手动刷新。

依赖：官方 SDK `mcp>=1.2`（延迟导入，未安装时其余 harness 功能不受影响，
仅外部 MCP 不可用并报清晰指引）。配置文件格式见仓库根 `mcp_servers.yaml`
与 [configuration.md](configuration.md)。

---

## 五、上下文装配

### 5.1 分段预算剪裁（`harness/context_assembly.py`）

把注入上下文的东西抽象成**四类段**，各自有优先级与预算：

| 段 | 常量 | 内容 | 取舍顺序 |
|---|---|---|---|
| 备忘 | `SEG_MEMO` | 长期要点、用户画像 | 最优先保留 |
| 摘要 | `SEG_SUMMARY` | 历史对话的压缩摘要 | 次优先 |
| 原文 | `SEG_VERBATIM` | 相关话题的原始对话 | 预算紧张时先裁 |
| 尾部 | `SEG_TAIL` | 最近 N 轮原文 | 最后才裁 |

`SegmentedContextAssembler` 按 `ContextBudget` 逐段装箱，超预算时按上表顺序裁剪。
**新增一类上下文时，正确做法是声明一个新段**，而不是往 system prompt 里硬拼字符串——
这样它自动获得预算安全。

### 5.2 `@` 指令采集（`harness/context_gatherer.py`）

用户输入里的 `@req` / `@sym` / `@grep` / `@ls` / `@tree` 会被 `ContextGatherer`
解析成结构化请求并抓取内容，注入上下文后再把指令本身从文本里去掉。

### 5.3 三区上下文与推测预取

`harness/agent/context.py` 提供 `ThreeZoneContext`（system / 历史 / 当前）与
`SpeculativePrefetch`：模型输出 `[FETCH: ...]` 占位符时提前抓取，下一轮替换。

---

## 六、管线与插件

文件：`harness/pipeline/`

### 6.1 8 个 HookPoint（`base.py:18`）

```
INBOUND       入站处理 / 过滤（可短路）
PRE_FILTER    ASR 输入过滤（可短路）        ← dsn 兼容
PREPARE       上下文组装 / system prompt    ← harness 原生
PRE_PROCESS   dsn 兼容名（PRE_FILTER → 组装 prompt → 本阶段）
MODEL_INVOKE  模型调用
POST_PROCESS  后处理 / 工具执行 / 记忆更新
POST_TTS      TTS 合成                     ← dsn 兼容
OUTPUT        输出渲染 / 投递
```

> `PREPARE` 与 `PRE_PROCESS` 语义相近但**故意保留为两个成员**：harness 侧用
> `PREPARE` 自己组装上下文，dsn 侧用 `PRE_PROCESS`。两套应用各用各的名字，互不串扰。

### 6.2 插件调度语义

`PluginManager` 按 **`priority` 升序**调度（**值小者先执行**）。
这是从 dsn 沿用下来的约定，harness 最初是降序、已对齐——**改排序前请确认没有应用依赖它**。

`dispatch` / `dispatch_except` / `dispatch_only` 支持按名字过滤。

> ⚠️ **已知缺陷（P0）**：`EventBus.publish()` 中保存 fire-and-forget 任务的
> `_bus_tasks` 是 `__init__` 里的**局部变量**，而 `publish` 里当作全局名引用，
> 因此**任何异步订阅者在同步 publish 时都会抛 `NameError`**（被外层 `except` 吞掉，
> 只留一条「处理器异常」日志）。实测已复现。修法：改成 `self._bus_tasks = set()`。
> 详情见 [technical-debt.md](technical-debt.md#p0-2-eventbus-异步订阅失效)。

> ⚠️ **注意 `AgentLoop` 不经过 `Pipeline`。** 二者是并列能力：
> `AgentLoop` 直接调用 `IChatClient` 并执行工具；`Pipeline` 是应用自己编排的钩子链
> （DSN 用它，dsn_ui 不用）。读旧文档里「AgentLoop → Pipeline → 工具层」的时序图时要注意这点。

---

## 七、其余模块

| 模块 | 说明 |
|---|---|
| `memory/` | `MemoryStore` 契约 + `InMemoryStore` + `VectorIndex`（余弦检索）。DSN 的真实记忆系统在 `apps/dsn/memory/`，这里只是抽象 |
| `personality/` | PEV3：50 维特质向量、贝叶斯演化、动态快照、证据累积、角色卡。**这是本仓库最完整的子系统之一** |
| `prompts/` | `PromptEngine` + `PromptFragment`，支持模块化提示词与预设 |
| `skills/` | `SkillLoader`：从目录加载技能定义并注册为工具 |
| `codegraph/` | 导入图、符号定位、全文搜索、文件监听。支撑 `code.locate_symbol` / `code.diagnose` |
| `conversation.py` | `Conversation` 消息列表 + `ConversationManager` 多会话管理 |
| `groupchat.py` | 多角色群聊编排 |
| `agent/subagent.py` | 主管-工人委派：拆任务、并发执行、汇总 |
| `agent/swarm.py` | 平级黑板共识：多成员读写 `Blackboard` 收敛观点 |
| `agent/modes.py` | `agent` / `oneshot` / `swarm` 三模式切换 |

---

## 八、改这一层时的检查清单

- [ ] 新能力是否**场景无关**？如果出现了“语音/学习/提醒”字样，它应该去 `apps/`。
- [ ] 是否破坏 `IChatClient` 契约？`stream()` 只能 yield `str` 或约定 dict。
- [ ] 是否新增了全局状态？优先走 `Runtime` 或显式参数注入。
- [ ] 工具改动是否同时更新了 schema 与执行逻辑？（两者分离，容易只改一半）
- [ ] 改 `AgentLoop` 后，`run_async` 与 `run_stream` **两条路径要一起验证**——
      历史上它们多次出现行为不一致（收束轮补丁就是这么来的）。
- [ ] 跑 `python -m pytest tests/test_harness_*.py -q`。
