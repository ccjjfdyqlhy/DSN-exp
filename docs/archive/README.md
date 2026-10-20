# 归档文档

> 这里保存**已完成的一次性记录**与**已被取代的旧版文档**。
> 保留它们的原因：其中记录了当时的决策背景，排查历史问题时可能有用。

## ⚠️ 阅读警告

**这些文档描述的架构已经过时，不要作为现状依据。**
当前架构请看 [../architecture.md](../architecture.md)。

---

## 文件清单

### `plan-harness-engine-migration.md`

AICF 引擎迁移的完成记录（目标：让 `dsn` 完全依赖 `harness` 全局引擎）。
**状态：已完成**。其中提到的路径此后又经历了一次 `harness/` → `infra/` 的搬迁，
因此文档里的部分路径（如 `infra/models`）需按当前目录理解。

### `aicf-overview.md`

AICF 分层与资源池概念的初版总览。**已被取代**：

- 分层结构 → [../architecture.md](../architecture.md)
- 资源池细节 → [../infra.md](../infra.md)

其中仍然准确且有参考价值的部分：资源池三种形态（进程内 / adopt / 托管）的描述、
租约（Lease）语义的说明。

### `harness-architecture-current.md`

某个时间点的 harness 架构图。**已被取代** → [../harness.md](../harness.md)。

**已知错误**（阅读时请注意）：

- 时序图里画了「AgentLoop → Pipeline」，实际 **AgentLoop 不经过 Pipeline**，
  二者是并列能力；
- 写的是「5 个 HookPoint」，实际 **8 个**；
- 写的是「17 个标准工具」，实际 **18 个**；
- 把 `SpeculativePrefetch` / `[FETCH:]` 画在主链路，实际**零调用点**。

### `architecture-harness-v2.md`

「v2 创新架构」的设计愿景。**主体设计尚未落地**，作为路线图参考：

- 策略对象一级公民 → 对象存在（`infra/policy/`），但**未接入 AgentLoop**；
- 声明式 Agent → `AgentSpec` 存在，但 `router`/`budget` 字段不生效；
- Token 经济闭环 → **不存在**（只组装未接线）；
- 上下文资产化 → 分段预算**已实现**（见 [../harness.md](../harness.md)）；
- 层级智能体原语 → `subagent` 已接入，`swarm` 零调用。

各项的当前状态与修复优先级见 [../technical-debt.md](../technical-debt.md)。
