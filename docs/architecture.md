# 架构总览

> 读者：需要改动本仓库代码的维护者。
> 目标：读完之后你能准确回答「某个功能应该写在哪一层」「改这里会牵连谁」。

本文只讲**结构与边界**；单层细节见 [harness.md](harness.md)、[infra.md](infra.md)，
应用装配见 [app-development.md](app-development.md)。

---

## 一、三层与唯一允许的依赖方向

```
        ┌──────────────────────────────────────────────┐
        │  apps/        业务语义：做什么               │
        │  dsn · dsn_ui · dsn_study · coding_agent ...  │
        └───────────────────┬──────────────────────────┘
                            │ import harness.* / infra.*
        ┌───────────────────▼──────────────────────────┐
        │  harness/     Agent 逻辑：怎么想、怎么动手   │
        │  agent · tools · pipeline · memory · SDK     │
        └───────────────────┬──────────────────────────┘
                            │ import infra.*
        ┌───────────────────▼──────────────────────────┐
        │  infra/       资源：模型从哪来、状态存哪     │
        │  orchestrator · resources · store · policy   │
        └──────────────────────────────────────────────┘
```

**规则：箭头只能向下。** 判断新代码该放哪一层，问三个问题：

| 问题 | 是 → |
|---|---|
| 它认识“语音/学习/陪伴/界面”这类词吗？ | `apps/` |
| 它关心“消息进、工具出、上下文预算”吗？ | `harness/` |
| 它只管进程、HTTP、显存、磁盘、密钥吗？ | `infra/` |

### 当前存在的两处违规（已知技术债）

| 文件 | 逆向依赖 | 影响 |
|---|---|---|
| `infra/observability/core.py:12` | `from harness.pipeline.events import EventBus` | `EventLogger` 在全仓库无调用者，属**死代码 + 违规**的组合，可直接删除 |
| `infra/cache.py:10` | `from harness.memory.vector import VectorIndex` | 与 `harness/memory/vector.py:13` 反向引用 `infra.models.base` 构成**循环依赖**；`SemanticCache` 在 infra 外无真实消费者 |

两处都指向“没有真实消费者”的代码，因此**斩断风险很低**。详情与修复建议见
[technical-debt.md](technical-debt.md)。

---

## 二、一次请求怎么走完三层

以「用户在 Web 控制台发一条消息」为例，这是全仓库最典型的路径：

```
浏览器 POST /v1/chat/completions
   │
   ▼  apps/dsn_ui/server.py          路由层：解析请求、决定 api_mode
   ▼  apps/dsn_ui/agent.py           协调层：组装上下文、选择模型、发起流式
   │      ├─ 组装 system prompt（dsn 模式才做）
   │      ├─ 情绪刺激 / 话题记忆（dsn 模式才做）
   │      └─ 选择 IChatClient
   ▼  harness/agent/loop.py          Agent 循环：invoke → 解析 tool_calls → 执行 → 回喂
   │      ├─ harness/tools/          工具注册表与执行
   │      └─ harness/context_assembly.py  上下文预算剪裁
   ▼  infra/orchestrator            模型层：选端点、管插槽、发 HTTP、读 SSE
   │      ├─ ModelOrchestrator     模型注册表与状态
   │      ├─ ModelScheduler        显存插槽与驱逐
   │      └─ LocalServerLauncher   必要时拉起 llama-server 子进程
   ▼
SSE 流回浏览器
```

**关键分界**：`apps/dsn_ui/agent.py` 里的 `api_mode` 决定是否注入 DSN 那套
提示词/情绪/记忆。`passthrough` 模式下 harness 与 infra 的行为完全不变，
只是跳过了应用层的增强——这正是分层的价值所在。

---

## 三、模块地图

### `infra/` —— 只关心资源，不认识业务

| 子模块 | 职责 | 关键类 |
|---|---|---|
| `orchestrator/` | 模型编排与契约 | `IChatClient` `ModelOrchestrator` `ModelScheduler` `LocalServerLauncher` |
| `orchestrator/router.py` | 双轨制编排：本地引擎 + 远程 API | `ModelSourceType` `ModelSpec` |
| `orchestrator/dynamic_router.py` | 端点可用性学习 | `DynamicRouter` `MonitorStore` |
| `resources/` | 异构资源池（ASR/TTS） | `ResourcePool` `ResourceLease` `ResourceSpec` |
| `policy/` | 可插拔行为策略 | `ModelRouter` `TokenMeter` `TokenBudget` `DurationPredictor` `CacheWarmer` `RetryPolicy` |
| `store/` | 持久化 | `SqliteStore` `SessionStore` `MigrationRunner` |
| `tasks/` | 任务抽象与调度 | `Task` `TaskExecutorRegistry` `TaskScheduler` `AsyncTaskStore` |
| `gateway/` | Web 网关适配 | `IGateway` `FlaskGateway` |
| `auth/` | 认证 | `APIKeyManager` `SessionManager` `TOTP` `UserStore` |
| `observability/` | 指标与用量 | `MetricsCollector` `UsageTracker` |
| `runtime.py` | DI 容器 + 生命周期 | `Runtime` |
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

### `apps/` —— 业务与装配

| 应用 | 定位 | 启动方式 |
|---|---|---|
| `dsn_ui` | Web 控制台，日常主入口 | `python main.py --app dsn_ui` / `python -m apps.dsn_ui.server` |
| `dsn` | 语音陪伴，规模最大（58k 行），包含最多历史包袱 | `python main.py`（默认） |
| `dsn_study` | 学习助手，**装配范式最规范** | `python main.py --app dsn_study` |
| `coding_agent` | 编码助手，**最小可读范例**（186 行） | `python -m apps.coding_agent` |
| `densechat` | WebUI 复刻 | `python -m apps.densechat` |
| `emotion_exp` | 情绪状态机实验 | `python -m apps.emotion_exp` |
| `text_agent` | 占位示例（106 行） | `python main.py --app text_agent` |

各应用细节见 [apps.md](apps.md)。

---

## 四、贯穿全层的三个概念

理解这三个概念，大部分代码就能读懂了。

### 1. `Runtime`：依赖注入容器

`infra/runtime.py` 提供进程内的服务注册表，替代到处传参或读全局。

```python
rt = Runtime(name="dsn")
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

`dsn` 用 9 个 bundle 拆解自身（core/voice/companion/personal/media/vision/
tracking/agent_api/maintenance），`dsn_study` 是单应用完整走通这条链路的典范。

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

因此 `apps/dsn_ui/topic_manager.py` 现在会**额外产出一段 `SEG_TAIL`**：

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
| `Runtime._default_runtime` | `infra/runtime.py:32` | 全局兜底运行时，测试之间可能串味 |

此外有两个“并存的调度器”需要警惕：`ResourcePool` **继承**了 `ModelScheduler`
但**不共享**它的单例，而 `apps/dsn/models/*.py` 又直接用 `ModelScheduler.get_instance()`。
因此同一进程里可能同时存在两套互不可见的插槽配额。

---

## 六、命名与文档约定

- **代码完全 snake_case**（PEP 8）。唯一例外：vendored 的 `apps/dsn/pyncm` 与外部 API 属性名。
- **注释即缺陷数据库**：本仓库不给 `infra/` 留 `TODO`/`FIXME`（实测全目录 0 个），
  而是把「这里曾经出过什么 bug、为什么这么写」写成中文长注释贴在代码旁。
  **改代码时请保留这些注释**——它们是这个项目最重要的知识载体。
- 面向用户的字段/接口用英文；面向维护者的解释用中文。

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
