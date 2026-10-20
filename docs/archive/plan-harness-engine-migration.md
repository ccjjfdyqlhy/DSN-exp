# AICF 引擎迁移 — 阶段状态与计划

> 状态: **目标达成** | 关联目标: "AICF 引擎是 dsn 引擎的超集，dsn 完全依赖 AICF 全局引擎"
> 原则: 全程不提交 git（HEAD 保持 a35da2e）。
>
> 注：本文记录迁移完成时的状态。此后基础设施模块已从 harness/ 迁至 infra/，
> 下文中模型、任务、Runtime 等基础设施路径按 `infra/` 更新；管线、插件、Agent、
> 记忆、提示词等 Agent 核心仍位于 `harness/`。

## 目标达成标准（全部验证通过）

对话核心链路五要素 + 模型环节全部走 harness 全局引擎：

| 环节 | AICF 超集能力 | dsn 依赖收口 | 验证 |
|------|------------------|--------------|------|
| 管线 | HookPoint 超集（PRE_FILTER/PRE_PROCESS/POST_TTS）、Context 超集（dsn 全字段）、hook_order 可配 | ChatPipeline 子类化 harness Pipeline；base/manager 再导出 shim | test_harness_pipeline + boot |
| 插件 | Plugin/AsyncPlugin/PluginManager（升序调度，dsn 语义） | 13 个 dsn 插件经 harness PluginManager 注册 | boot 冒烟 |
| Agent | AgentLoop.run_rounds 轮次策略骨架 | _run_agent_loop 经 harness AgentLoop 驱动 | test_agent_loop_harness 四场景等价 |
| 任务 | TaskStatus 超集（+MISSED/SKIPPED）、TaskPriority、TaskManagerPort、TaskExecutorRegistry | dsn 类型/契约/分派来自 infra/tasks；8 类执行器注册 | test_harness_tasks + boot |
| 记忆 | MemoryStorePort 契约、pack/unpack/cosine 向量原语 | dsn 检索原语即 harness/memory 函数；MemorySystem 符合契约 | test_harness_memory + boot |
| 模型 | IChatClient/IEmbeddingClient/ModelProviderRegistry（infra/models） | OpenAIChat/LMStudioChat 实现 invoke/stream 契约桥；boot 注册 model_provider | test_harness_models + boot |
| 服务 | Runtime DI 容器（infra/runtime.py） + AppBundle（infra/subapps.py） + FlaskGateway（infra/gateway） | db/engine/task_manager/memory_system/prompt_engine/skill_registry/auth_manager/model_provider 全经 infra Runtime 解析 | 综合集成检查 11/11 |

最终验证: 191 项测试通过，5 个预存失败与 HEAD 基线一致（零新增回归）；
综合集成检查 11/11（pipeline/plugin_manager/agent/tasks/memory/models/Runtime/shim 身份）；
boot 装配 0.6s 完成，9 个 AppBundle。

## 关键语义变更（必须保留）

- PluginManager 调度为 **priority 升序**（dsn 约定，值小者先执行）——harness 原为降序，已对齐；
- harness Context/HookPoint 为纯增量超集（新字段/新钩子均带默认值，通用场景不受影响）；
- dsn Task 增加 type/id 兼容桥；dsn 模型客户端 invoke/stream 为新增契约入口（原 API 不变）。

## 可选后续（超出目标范围，未实施）

1. 记忆/任务 DB 实现深上移：MemorySystem/TopicManager/TaskManager 核心迁入 AICF
   （需 infra/store 抽象解耦 ChatDBManager）——与 Agent 核心场景无关的设计存在张力，故未纳入目标。
2. shim 清理：apps/dsn/plugins/base.py、manager.py 已是纯 harness 再导出，
   可直接把各调用点的 import 改为 harness（纯机械改动，无功能变化）。
3. 模型客户端深接入：ModelsPlugin 从 infra/models 的 model_provider 解析客户端（替代直接构造）。

## 预存失败清单（与本次迁移无关）

- tests/test_skills_system.py 4 项（技能加载路径问题，迁移前即失败）
- tests/test_harness_coding.py::test_model_router_select_and_switch（router 语义，未触碰）
