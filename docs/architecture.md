# 架构总览

> 读者：需要改动本仓库代码的维护者。
> 目标：读完之后你能准确回答「某个功能应该写在哪一层」「改这里会牵连谁」。

本文只讲**结构与边界**；单层细节见 [harness.md](harness.md)、[infra.md](infra.md)，
应用装配见 [app-development.md](app-development.md)。

---

## 一、两层与唯一允许的依赖方向

```text
aicf-ui (separate repository) -> depends on aicf-core
harness/                      -> agent logic: turn loop, tools, context, memory
infra/                        -> resources: models, storage, gateway, policy
```

this repository contains only the two library layers. the web console lives in
its own repository.

**rule: dependencies point down only.** ask three questions when placing new code:

| question | yes -> |
|---|---|
| does it know about a user interface or a product feature? | `aicf-ui` repository |
| does it care about messages in, tools out, or a context budget? | `harness/` |
| does it only manage processes, http, vram, disk or secrets? | `infra/` |

### 曾经的两处违规（2026-10 已修复）

| 文件 | 曾经的逆向依赖 | 现在的状态 |
|---|---|---|
| `infra/observability/core.py` | `from harness.pipeline.events import EventBus` | 已改掉；向量原语下沉到 `infra/vector.py`，`infra/cache.py` 不再依赖 `harness.memory.vector` |
| `infra/cache.py` | `from harness.memory.vector import VectorIndex` | 已改掉，与 `harness/memory/vector.py` 的循环依赖消失 |

**1.0.0-rc0 增加了两条硬规则，并有测试兜底**：

1. `infra/eval/` 与 `infra/runtime/` **不得 import `harness`** ——
   评测层只认自己定义的 `Trace` / `ToolCall`，harness 事件流靠
   `trace_from_events()` 适配（只读 dict）。
2. `harness/` 依赖 `infra/` 时**只允许依赖 Protocol** ——
   契约（`ToolSpec` / `PolicyEngine` / `ApprovalBroker` / `Sandbox` /
   `TelemetryPort` / `RuntimeClient`）全部住在 `harness/`，
   实现在 `infra/`，由应用装配时注入。

代价是两处**同名契约**需要在两侧各写一份实现
（幂等键公式、`UnknownOutcomeError` 的识别标记），
用**交叉测试**钉住，而不是靠约定文档。

---

## 二、一次请求怎么走完三层

the typical path for one console message:

1. the browser sends `POST /v1/chat/completions`.
2. `aicf_ui/server.py` parses the request and picks `api_mode`.
3. `aicf_ui/agent.py` assembles context, chooses a model and starts the stream.
4. `harness/agent/loop.py` invokes the model, runs tool calls and feeds results back.
5. `harness/tools/` executes tools; `harness/context_assembly.py` trims the budget.
6. `infra/orchestrator` selects an endpoint, manages slots, sends http and reads sse.
7. the stream returns to the browser.

**The important boundary:** `api_mode` decides whether the console injects its
product prompts and memory. In `passthrough` mode harness and infra behave
exactly the same; only the application layer is skipped. That is the value of the
split.

---

## 三、模块地图

### `infra/` —— 只关心资源，不认识业务

| 子模块 | 职责 | 关键类 |
|---|---|---|
| `orchestrator/` | 模型编排与契约 | `IChatClient` `ModelOrchestrator` `ModelScheduler` `LocalServerLauncher` |
| `orchestrator/router.py` | 双轨制编排：本地引擎 + 远程 API | `ModelSourceType` `ModelSpec` |
| `orchestrator/dynamic_router.py` | 端点可用性学习 | `DynamicRouter` `MonitorStore` |
| `resources/` | 异构资源池（ASR/TTS/VLM） | `ResourcePool` `ResourceLease` `ResourceSpec` |
| `policy/` | 可插拔行为策略 | `ModelRouter` `TokenMeter` `TokenBudget` `DurationPredictor` `CacheWarmer` `RetryPolicy` |
| `store/` | 持久化 | `SqliteStore` `SessionStore` `MigrationRunner` |
| `tasks/` | 任务抽象与调度 | `Task` `TaskExecutorRegistry` `TaskScheduler` `AsyncTaskStore` |
| `gateway/` | Web 网关适配 | `IGateway` `FlaskGateway` |
| `auth/` | 认证 | `APIKeyManager` `SessionManager` `TOTP` `UserStore` |
| `observability/` | 指标与用量 + **trace 扇出 + 审计** | `MetricsCollector` `UsageTracker` `TraceCollector` `AuditLog` |
| `runtime/di.py` | DI 容器 + 生命周期（原 `runtime.py` 迁入，见下方说明） | `Runtime` |
| `runtime/` | **托管运行时**（D2）：状态模型 / journal / checkpoint / 幂等 / 恢复 | `ManagedRuntime` `Journal` `CheckpointStore` `recover` |
| `eval/` | **评测闭环**（D6）：数据集 / 求值 / 四闸门 / run version / 回归 | `Evaluator` `GateEvaluator` `load_dataset` `RunVersion` |
| `policy/engine.py` | **工具准入策略**（实现 `harness.policy.base.PolicyEngine`） | `RulePolicyEngine` |
| `subapps.py` | 应用场景包 | `AppBundle` `AppBundleRegistry` |
| `settings.py` | 命名空间化配置 | `Settings` `Namespace` |
| `cache.py` | 语义缓存（L2 向量） | `SemanticCache` |
| `models/` | ⚠️ **兼容 shim** | — |

### `harness/` —— 只关心「消息进、事件出」

| 子模块 | 职责 | 关键类 |
|---|---|---|
| `agent/loop.py` | Agent 循环 | `AgentLoop` `StreamEvent` `AgentRunResult` `RoundResult` |
| `agent/assembler.py` | 声明式装配 | `AgentSpec` `AgentAssembler` `AssembledAgent` |
| `agent/adapters.py` | 工具调用解析 | `NativeToolCallAdapter` `TaggedToolCallAdapter` |
| `agent/subagent.py` | 主管-工人委派 | `SubAgentRunner` `SubTask` |
| `agent/swarm.py` | 平级黑板共识 | `SwarmRuntime` `Blackboard` |
| `agent/context.py` | 三区上下文 + 推测预取 | `ThreeZoneContext` `SpeculativePrefetch` |
| `agent/modes.py` | 模式切换 | `AgentMode` `ModeState` |
| `agent_runtime.py` | 运行时封装 | `AgentRuntime` |
| `tools/` | 工具抽象与标准工具 | `Tool` `ToolRegistry` `ToolboxManager` `install_standard_tools` |
| `tools/spec.py` | **工具契约**（副作用等级 / 沙箱档位 / 授权范围） | `ToolSpec` `stricter_than` |
| `tools/guard.py` | **工具调用的唯一入口**（策略 → 审批 → 幂等 → 沙箱） | `ToolGuard` `GuardResult` |
| `tools/sandbox/` | 隔离执行（路径判定 / restricted / namespaced） | `Sandbox` `SandboxRequest` `SandboxResult` |
| `policy/` | 准入策略的**协议**（实现住在 infra/policy/engine.py） | `PolicyEngine` `PolicyDecision` `PolicyRule` |
| `approval/` | 审批（人在回路） | `ApprovalRequest` `ApprovalDecision` `ApprovalBroker` |
| `kernel/` | **执行内核 SPI**（ReAct / Workflow / Planner 可替换） | `ExecutionKernel` `KernelContext` `CapabilitySet` |
| `telemetry/` | 遥测协议与 span 工具 | `TelemetryPort` `Span` `SpanHandle` |
| `runtime_client.py` | Kernel → Runtime 的**唯一出口** | `RuntimeClient` `ToolIntent` `idempotency_key` |
| `context_assembly.py` | 分段预算剪裁 | `SegmentedContextAssembler` `ContextBudget` `ContextSegment` |
| `context_gatherer.py` | `@` 指令采集 | `ContextGatherer` |
| `pipeline/` | 通用管线 | `Pipeline` `Plugin` `HookPoint` `EventBus` `OutputRenderer` |
| `memory/` | 记忆抽象 | `MemoryStore` `VectorIndex` |
| `personality/` | 人格与角色卡 | `PersonalitySystemV3` `CharacterCard` |
| `prompts/` | 模块化提示词 | `PromptEngine` `PromptFragment` |
| `skills/` | 技能加载 | `SkillLoader` |
| `codegraph/` | 代码图谱 | `ImportGraph`（builder/symbol/search/watcher） |
| `conversation.py` | 会话管理 | `Conversation` `ConversationManager` |
| `groupchat.py` | 群聊 | — |
| `sdk.py` | 嵌入式 SDK | `Agent` `create_agent` `tool` |

### the web console repository

| product | purpose | entry point |
|---|---|---|
| `aicf-ui` | web console: models, chat, resources, system-1 decisions | `python -m aicf_ui.server` |

see [apps.md](apps.md) for the repository relationship.

---

## 四、贯穿全层的三个概念

理解这三个概念，大部分代码就能读懂了。

### 1. `Runtime`：依赖注入容器

`infra/runtime/di.py` 提供进程内的服务注册表，替代到处传参或读全局。
（1.0.0-rc0 起 DI 容器迁入 `infra/runtime/` 包内 —— 同名包会遮蔽同名模块，
`infra/runtime.py` 一旦存在就不会被加载。包级 `infra.runtime.Runtime` 仍指向它。）

```python
rt = Runtime(name="my_app")
rt.register("db", db)
rt.register_factory("engine", lambda: create_engine(rt.get("db")))

engine = rt.resolve("engine")     # 惰性构造
rt.on_start(hook); rt.start()      # 生命周期
Runtime.current()                  # 任意位置取当前运行时
```

键可以是 `str` 或 `type`；`type` 会被归一化为 `module.QualName` 避免撞名。
`Runtime.activate()` 是上下文管理器，用于测试隔离。

### 2. `AppBundle`：应用的装配单元

`infra/subapps.py` 定义应用的生命周期契约，`AppBundleRegistry` 按序驱动：

```
runtime 就绪 → bundle.install(runtime)   注册服务、技能、任务、路由
runtime.start() → bundle.start(runtime)  启动后台线程、加载模型
runtime.stop()  → bundle.stop()          释放资源（逆序）
```

an application can split itself into several bundles (core, media, vision,
tracking, agent api, maintenance) and let the registry install and start them in
order. one bundle is enough for a small product.

### 3. `IChatClient`：唯一模型契约

所有后端都实现同一个 Protocol（`infra/orchestrator/base.py:175`），因此上层
**永远不需要知道模型是本地进程还是远程 API**：

```python
class IChatClient(Protocol):
    model: str
    def invoke(messages, tools=None, *, temperature, max_tokens, timeout) -> ChatResponse
    async def stream(...) -> AsyncGenerator
```

`stream()` 的产出契约：`str` 表示文本增量；`dict` 表示结构化事件
（`content` / `tool_calls` / `usage` / `timings` / `reasoning`）。

---

## 五、上下文保底：最近对话永不丢失

「弹性上下文」会按预算裁剪历史，这是它省 token 的代价。
但有一条硬约束：**最近几轮对话必须无条件注入**。

### 两类段的分工

| 段 | 参与共享预算？ | 作用 |
|---|---|---|
| `SEG_VERBATIM`（当前话题原文） | ✅ 会被裁 | 提供完整的相关历史 |
| `SEG_TAIL`（最近 N 轮） | ❌ 保底注入 | 保证「刚刚说过的话」永远在上下文里 |

`harness/context_assembly.py::plan()` 对 `SEG_TAIL` 按 `unbounded` 语义原样保留。

### 一个曾经会丢消息的坑

调用方若只提交 `SEG_VERBATIM`，一旦预算耗尽，**包含最近一轮的那整段会被裁掉**，
用户看到的现象就是「弹性上下文偶尔丢失上一条消息」。

因此 `aicf-ui 仓的 aicf_ui/topic_manager.py` 现在会**额外产出一段 `SEG_TAIL`**：

- 取当前话题最近 `budget.tail_rounds` 轮的原文；
- 不参与共享预算，因此任何裁剪策略都动不了它；
- 若当前话题原文**本来就没被裁**（完整包含尾部文本），则跳过注入，避免重复。

> 新增调用方时，请照此模式：**完整历史走 SEG_VERBATIM，最近 N 轮走 SEG_TAIL**。
> 回归测试见 `tests/test_context_retention.py`。

---
## 五、单例与全局状态清单（改代码前必读）

本仓库大量使用**进程级单例**。它们在放便装配的同时，也是最容易出问题的区域。

| 全局 | 位置 | 危害 |
|---|---|---|
| `ModelOrchestrator._instance` | `infra/orchestrator/router.py:82` | `get_instance()` 首次调用后**参数被忽略**；`reset_instance()` 会 shutdown 所有 launcher |
| `ModelScheduler._instance` | `infra/orchestrator/scheduler.py:94` | 被 `ModelOrchestrator.__init__` 改写 `max_concurrent`（router.py:101） |
| `_ACTIVE_LAUNCHERS` | `infra/orchestrator/local_engine.py:49` | 全局模型子进程回收点，配合 `atexit` 使用 |
| `local_http_session()` / `local_probe_session()` | `orchestrator/base.py:15/45` | **必须区分**：流式用前者、探针用后者；混用会误判未就绪并触发重拉 |
| `Runtime._default_runtime` | `infra/runtime/di.py` | 全局兜底运行时，测试之间可能串味 |

there are two schedulers to watch: `ResourcePool` inherits from `ModelScheduler`
but does not share its singleton. application code that also calls
`ModelScheduler.get_instance()` can end up with two independent slot budgets in
one process.

---

## 六、命名与文档约定

- code uses `snake_case` per pep 8. the only exceptions are vendored third-party
  packages and external api attribute names.
- comments are a defect database: `infra/` carries no `TODO` or `FIXME`. instead,
  each non-obvious workaround records the bug that caused it and why the current
  shape is required. preserve those comments when editing the code.
- new comments, docstrings and user-facing strings are plain english.

---

## 七、规模与质量基线

使用 `fuck-u-code` 对整个仓库做过静态分析（排除 `temp/`、`logs/`、`prototypes/`）
作为基线参考：

| 指标 | 数值 |
|---|---|
| 分析文件数 | 581 |
| 综合评分 | 77.57 / 100 |
| 循环复杂度 | 10.11% |
| 认知复杂度 | 12.88% |
| 注释比例 | 33.60% |
| 错误处理 | 31.37% |

结构性问题（复杂度、嵌套、重复）整体健康；**主要短板是错误处理与文件长度**，
集中在少数几个巨型文件上。热点文件与处理建议见 [technical-debt.md](technical-debt.md)。
