# AICF 架构总览

> AICF —— **Agent Infrastructure Cybernetics Framework**（智能体基础设施控制论框架）。
> 本文给出分层结构、依赖方向与资源池概念；细节分别见
> [harness-architecture-current.md](harness-architecture-current.md)、
> [architecture-harness-v2.md](architecture-harness-v2.md)。

---

## 一、分层与依赖方向

AICF 把"让智能体跑起来"所需的底座拆成三层，依赖方向自上而下单向：

```
┌─────────────────────────────────────────────────────────────┐
│ apps/          具体应用（业务语义）                          │
│   dsn · dsn_ui · dsn_study · coding_agent                    │
│   emotion_exp · densechat · text_agent                       │
└───────────────────────────┬─────────────────────────────────┘
                            │ 依赖
┌───────────────────────────▼─────────────────────────────────┐
│ harness/       Agent 核心（场景无关的智能体逻辑）            │
│   agent · agent_runtime · tools · pipeline · personality     │
│   memory · prompts · skills · codegraph · conversation       │
│   groupchat · context_assembly · context_gatherer · sdk      │
└───────────────────────────┬─────────────────────────────────┘
                            │ 依赖
┌───────────────────────────▼─────────────────────────────────┐
│ infra/         基础设施与运行时管理                          │
│   orchestrator · resources · runtime · subapps · settings    │
│   cache · store · observability · tasks · gateway · auth     │
│   policy                                                     │
└─────────────────────────────────────────────────────────────┘
```

关键边界：

- **`infra/` 不知道任何业务语义**，只提供"资源怎么被管起来、怎么被调度、怎么被拉起"；
- **`harness/` 只关心"消息进、输出流/事件出"**，不关心语音、人格、提醒等应用语义，
  这些由 `apps/` 下的 AppBundle 提供；
- **`apps/` 只做装配与业务实现**，不重复实现框架能力。

> 分层只体现在目录与依赖方向上，**导入路径不变**：基础设施是 `infra.*`，
> Agent 核心与 SDK 是 `harness.*`。AICF 是项目级定位名称。

---

## 二、`infra/` —— 基础设施与运行时管理

| 模块 | 职责 |
|---|---|
| `infra/orchestrator/` | 模型编排与路由、客户端契约（`IChatClient` / `IEmbeddingClient`）、本地引擎与调度器 |
| `infra/resources/` | 异构资源池：`ResourceKind` / `ResourceSpec` / `ResourceLease` / `ResourcePool` + 启动器 |
| `infra/runtime.py` | Runtime DI 容器 + 生命周期 |
| `infra/subapps.py` | AppBundle 抽象基类 + 装配器 |
| `infra/settings.py` | 命名空间化配置 |
| `infra/cache.py` | 语义缓存 |
| `infra/store/` | 持久化（IStore / Migration / SqliteStore） |
| `infra/observability/` | 用量追踪等可观测性能力 |
| `infra/tasks/` | 任务抽象与执行器注册 |
| `infra/gateway/` | Web 网关（IGateway / FlaskGateway） |
| `infra/auth/` | 认证（Identity / APIKey / TOTP / Session） |
| `infra/policy/` | 策略对象：路由、Token 计量与预算、耗时预测、缓存保活 |

---

## 三、`harness/` —— Agent 核心

| 模块 | 职责 |
|---|---|
| `harness/agent/` | Agent 循环（`AgentLoop`）、声明式装配（`AgentSpec`）、子代理与 swarm、模式切换 |
| `harness/agent_runtime.py` | Agent 运行时 |
| `harness/tools/` | 工具抽象、注册表、标准工具集 |
| `harness/pipeline/` | 通用管线（Plugin / Pipeline / EventBus / OutputRenderer） |
| `harness/personality/` | 人格与角色卡 |
| `harness/memory/` | 记忆抽象（IMemoryStore / VectorIndex） |
| `harness/prompts/` | 模块化提示词引擎 |
| `harness/skills/` | 技能加载 |
| `harness/codegraph/` | 代码图谱与文件监听 |
| `harness/context_assembly.py` | 分段上下文装配与预算剪裁 |
| `harness/context_gatherer.py` | @ 指令上下文采集 |
| `harness/conversation.py` | 会话管理 |
| `harness/groupchat.py` | 群聊 |
| `harness/sdk.py` | 嵌入式 SDK（`Agent` / `create_agent` / `@tool`） |

---

## 四、统一异构资源池

现实中的计算资源形态完全不同：有的模型加载在**本进程内**（没有 HTTP 端点），
有的是**已经在跑的 HTTP 服务**（框架只接不拉），有的需要**由框架拉起子进程**。
资源池的价值就是把这些差异收敛到同一套**描述、调度与生命周期**语义上。

### 4.1 池化调度

`ResourcePool` 继承模型编排层的 `ModelScheduler`，因此资源天然获得与模型一致的：

- **优先级**（`priority`，数值越大越优先）；
- **常驻 / 即时回收**（`resident` / `immediate`）；
- **并发插槽**与等待超时（`set_max_concurrent` / `slot_status`）；
- **加载 / 卸载钩子**与**优雅停机**。

### 4.2 登记：`ResourceSpec` + `load_fn` / `unload_fn`

```python
pool.register_resource(name, spec, load_fn, unload_fn)
```

- `ResourceSpec` 描述资源：`kind` / `display_name` / 调度字段
  （`priority` / `resident` / `immediate` / `orchestrated` / 超时）
  以及连接信息（`base_url` / `endpoint` / `vram_estimate_mb` / `extra`）；
- `load_fn` / `unload_fn` 是**调度钩子**：加载失败必须返回 `False` 而不是抛异常；
- 启动器可用 `launcher.create_scheduler_hooks()` 直接生成这一对钩子。

**当前资源种类只有 ASR 与 TTS**（`ResourceKind.ASR` / `ResourceKind.TTS`）。
LLM 由 `infra/orchestrator` 的模型调度承担；`ResourceKind` 只包含已实装的成员。

### 4.3 使用：租约（Lease）

```python
with pool.acquire("tts") as lease:
    url = lease.url          # 进程内资源为空串
    ...                       # 期间该资源被独占 / 计数
# 退出即归还；release() 幂等
```

`ResourceLease` 既是上下文管理器，也可手动 `release()`；释放动作即退出调度器的
`use()` 上下文，回收引用计数与插槽。

### 4.4 启动器：三种资源形态

`infra/resources/launchers.py` 把形态归一到底层
`infra/orchestrator.local_engine.LocalServerLauncher`（就绪探针 / 优雅停机 /
SIGTERM→SIGKILL）之上，只覆盖差异点：

| 启动器 | 资源形态 | 说明 |
|---|---|---|
| `InProcessModelLauncher` | 进程内模型 | 模型加载在本进程内，无 HTTP 端点，`is_ready()` 的语义是"模型对象存在"（如 FunASR） |
| `HTTPServiceLauncher`（adopt 模式） | 既有 HTTP 服务 | 只探测接入、不拉起、不停进程（如 TTS） |
| `HTTPServiceLauncher`（托管模式） | 子进程 | 由 `start_command` 拉起命令行；`preflight()` 校验可执行文件，`child_env()` 注入设备环境变量 |

### 4.5 扩展点（尚未实现）

`build_command()` 与 `child_env()` 是资源启动的注入点，**当前只支持直接命令行拉起**。
**conda 环境启动器与 docker 容器启动器在代码库中尚不存在**；如需支持，应在
`infra/resources/launchers.py` 这一层新增 `LocalServerLauncher` 子类
（用 `build_command()` 返回 `conda run ...` / `docker run ...`，
用 `child_env()` 注入环境），而不是在本层假定它们已经可用。

---

## 五、生命周期与调度

```
register_resource(name, spec, load_fn, unload_fn)
        │
        ▼
   ensure_running() / acquire()          ← 优先级 · 插槽 · 等待超时
        │
        ├─ load_fn  →  start(wait_ready=True)  就绪探针
        │
        ▼
   ResourceLease（with 语句内独占使用）
        │
        ▼
   release() → refcount / 插槽回收
        │
        ▼
   stop_resource() → unload_fn → 优雅停机（SIGTERM → SIGKILL）
```

常驻资源不会被插槽压力卸载；即时资源在任务排空后立即卸载，并可临时抢占空闲资源。

---

## 六、Agent 运行时（`harness/`）

资源池之上是 Agent 运行时：`AgentLoop` 驱动轮次循环，工具通过 `ToolRegistry` 注册与调用，
上下文由 `SegmentedContextAssembler` 按预算剪裁，策略层（`infra/policy`）负责
路由、Token 计量与预算、耗时预测与缓存保活。应用只需声明 `AgentSpec` 完成装配。

详见 [harness-architecture-current.md](harness-architecture-current.md) 与
[architecture-harness-v2.md](architecture-harness-v2.md)。
