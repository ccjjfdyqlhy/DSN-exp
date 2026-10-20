# AICF 系统架构图（当前代码）

> 依据 infra/ 与 harness/ 源码模块结构绘制（2026-08-14，v0.4.0+ 重构后；分层命名按 AICF 更新）。
> `infra/` = 基础设施与运行时管理（orchestrator / resources / runtime / subapps / settings /
> cache / store / observability / tasks / gateway / auth / policy）；
> `harness/` = Agent 核心（agent / tools / pipeline / personality / memory / prompts / skills /
> codegraph / context assembly / SDK）。

## 一、分层架构

```mermaid
flowchart TB
    subgraph L0["入口 / 装配层"]
        LA["launcher.py<br/>应用选择器"] --> APPS["apps/*<br/>AppBundle 应用"]
        RT["infra/runtime.py<br/>Runtime DI 容器 + 生命周期"]
        SUB["infra/subapps.py<br/>AppBundleRegistry"]
        ST["infra/settings.py<br/>Settings / Namespace"]
        ART["harness/agent_runtime.py<br/>AgentRuntime"]
    end

    subgraph L1["Agent 编排层"]
        SPEC["AgentSpec / AgentAssembler<br/>声明式装配"]
        LOOP["AgentLoop<br/>轮次循环 · run_stream"]
        CTX3["ThreeZoneContext"]
        PF["SpeculativePrefetch [FETCH:]"]
        SUBAG["SubAgentRunner"]
        SW["SwarmRuntime + Blackboard"]
        MODE["ModeState"]
        ADAPT["NativeToolCallAdapter<br/>原生 JSON toolcall（默认）"]
    end

    subgraph L2["上下文层"]
        SCA["SegmentedContextAssembler<br/>预算剪裁"]
        GATH["ContextGatherer @指令"]
        SC["infra/cache.py<br/>SemanticCache L1/L2"]
        CONV["Conversation / Manager"]
    end

    subgraph L3["策略层 · Token 经济闭环（infra/policy）"]
        RTR["ModelRouter（唯一实现）<br/>flash/pro/注册档位/预算压力"]
        METER["TokenMeter + UsageRecord<br/>（唯一实现，infra/observability 复用）"]
        BUD["TokenBudget"]
        PRED["DurationPredictor"]
        WARM["CacheWarmer"]
        RETRY["RetryPolicy"]
    end

    subgraph L4["模型层 · 编排（infra/models）"]
        MC["IChatClient / IEmbeddingClient"]
        OA["OpenAICompatClient<br/>原生 toolcall + 流式"]
        LS["LMStudioChat<br/>本地 · 原生 toolcall + SSE 流式"]
        FC["FailoverChat<br/>多端点故障转移（观察回调）"]
        SCH["ModelScheduler<br/>FIFO/优先级驱逐/VRAM 编排"]
        DR["DynamicRouter + MonitorStore<br/>端点可用性学习"]
        REG["ModelProviderRegistry"]
        RP["infra/resources<br/>ResourcePool<br/>异构资源池（ASR/TTS）"]
    end

    subgraph L5["管线层"]
        PIP["Pipeline · HookPoint"]
        PM["PluginManager"]
        PLUG["Plugin / AsyncPlugin"]
        EB["EventBus"]
        OR["OutputRenderer"]
        OF["OutputFilter"]
    end

    subgraph L6["工具层"]
        TR["ToolRegistry + ToolResult<br/>status/hint 状态回喂"]
        TB["ToolboxManager 两阶段激活"]
        STD["standard.py · 17 工具<br/>（含 batch.run 实装 + code.diagnose）"]
        FN["tool_from_function"]
        SL["SkillLoader"]
    end

    subgraph L7["能力服务层"]
        MEM["harness/memory<br/>Memory · VectorIndex"]
        TSK["infra/tasks<br/>Tasks · Scheduler(SQLite)"]
        CG["harness/codegraph<br/>Codegraph · FileWatcher"]
        PE["harness/prompts<br/>PromptEngine"]
        STORE["infra/store<br/>Store · SqliteStore/SessionStore"]
        AUTH["infra/auth<br/>Auth · Session/TOTP/APIKey"]
        GW["infra/gateway<br/>Gateway · FlaskGateway"]
        OBS["infra/observability<br/>Observability · UsageTracker"]
    end

    L0 --> L1
    L1 --> L2 & L3 & L6
    L3 --> L4
    L2 --> L5
    L1 --> L7
    L6 --> L7
    L2 --> L7
```

## 二、一次请求的数据流（含 toolcall 状态回喂）

```mermaid
sequenceDiagram
    participant U as 用户输入
    participant A as AgentLoop
    participant C as 上下文装配
    participant P as Policy 策略层
    participant M as 模型层
    participant Pi as Pipeline
    participant T as 工具层
    participant S as 能力服务

    U->>A: message
    A->>C: 三段式 + @指令采集 + 符号预取
    C->>P: Router 选档 → Meter 预算检查
    P->>M: invoke/stream（原生 JSON toolcall）
    M-->>A: 流式响应 / tool_calls
    A->>Pi: 5 个 HookPoint 处理
    A->>T: Toolbox 两阶段 → 标准工具
    T-->>A: ToolResult{status, hint, output/error}
    A->>A: adapter 组装 tool_result（含状态+提示）回喂模型
    A-->>U: 输出流
    Note over P: 记账 → Budget 压力 → Predictor 学习 → Warmer 保活
```

## 三、多模型协同 / 本地-API 编排（从 DSN 广义化）

| DSN 原实现 | AICF 广义实现 | 广义化方式 |
|---|---|---|
| apps/dsn/models/scheduler.py | infra/models/scheduler.py | 去 Config 依赖；profiles_dir/超时/load_fn 注入 |
| apps/dsn/models/dynamic_router.py | infra/models/dynamic_router.py | AccountProvider/ManagedAccount 协议；manual_schedule 回调 |
| apps/dsn/models/api_accounts.py FailoverChat | infra/models/failover.py | IChatClient 契约 + on_observation 回调 + 流式故障转移 |
| apps/dsn/models/clients.py LMStudioChat | infra/models/lmstudio.py | 原生 toolcall + SSE 流式；DSN 保留视觉/历史扩展 |

DSN 侧全部改为 AICF 的薄子类（scheduler/dynamic_router/api_accounts/clients），
boot 经 ModelProviderRegistry 注册 openai/lmstudio/embedding 工厂。

## 四、本轮清理与强化

- ✅ 合并重复：ModelRouter 唯一实现在 infra/policy/router.py（含 TierConfig 多档）；
  UsageRecord/fmt_tokens/in_peak_hours 唯一实现在 infra/policy/token_meter.py，
  infra/observability.usage 复用；旧 infra/models/router.py 与 usage 本地副本删除。
- ✅ 原生 JSON toolcall：NativeToolCallAdapter 默认 + OpenAI/LMStudio 客户端
  均走原生 function calling；toolcall 结果回喂含 success/status/output/error/hint。
- ✅ 工具集 17 个：batch.run 实装（按已注册工具批量执行），新增 code.diagnose。
- ✅ 驼峰命名：AICF（infra/ + harness/）与 DSN 自有代码已全部 snake_case（仅 vendored pyncm
  与 stdlib/外部 API 属性名例外，不改动）。
