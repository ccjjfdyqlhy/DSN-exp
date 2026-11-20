# 控制面（Control Plane）

> 策划案 §4.5 / rc1 C2–C6 的落地说明。读者：要接控制面、要发布 artifact、
> 要做成本归因的人。

## 它管什么

控制面回答四个经营问题：

| 问题 | 载体 | 存储 |
|---|---|---|
| 这个 Agent 的声明是什么？ | `AgentArtifact`（`aicf/infra/control/artifact.py`） | `control_artifact` |
| 它现在处于生命周期的哪一步？ | `ArtifactStore.transition`（`aicf/infra/control/lifecycle.py`） | `control_lifecycle_event` |
| 它花了多少钱？ | `CostLedger`（`aicf/infra/control/cost.py`） | `control_cost_ledger` |
| 外部框架的进程怎么纳管？ | `ByoRegistry`（`aicf/infra/control/adoption.py`） | 内存登记 |

表结构按策划案 §5.1 原样建（迁移 id `rc1_control_001`），
存储走 `IStore` —— 换 Postgres 不动上层。

## AgentArtifact：一种声明，多处消费

`agents/research.yaml` 是活的示例。同一份 yaml 同时是：

- **部署描述**（`spec.runtime.deployment`）
- **评测配置**（`RunVersion` 冻结的就是这份内容，`aicf/infra/eval/run_version.py`）
- **成本归因维度**（`spec.cost_model.per_1k_tokens` → `price_tokens()`）
- **命令行装配**（`aicf run --artifact agents/research.yaml`）

工具用**版本引用**（`shell@v3`）而非名字引用：上游升级不打断线上。

## 生命周期：每次迁移都是不可变事件

```
DRAFT ──review──▶ REVIEWING ──approve──▶ APPROVED ──release──▶ RELEASED(canary)
                        ▲                    │                    │
                        │                    └──rollback──────────┘
                        │                    ▼
                        └──reject──── DISPUTED          ROLLED_OUT ──deprecate──▶ DEPRECATED ──▶ ARCHIVED
```

两条硬规则：

1. **release 必须携带 `verdict=pass` 的 Gate 报告**。`ArtifactStore.publish`
   在任何状态迁移**之前**先校验报告 —— 一次失败的发布不留中间态。
2. **版本不可变**。同一个 `(id, version)` 写入不同内容直接抛
   `VersionConflictError`；改声明 = 升版本。

回滚只回退一步（`RELEASED/ROLLED_OUT → ROLLED_BACK`），与
`aicf/harness/learning/promotion.py` 的既定语义一致。

## AgentIdentity 与委托

`aicf/infra/control/identity.py`。与 `aicf/infra/auth/base.py` 的用户态 `Identity`
不混用：一个回答「哪个人在操作」，一个回答「哪个 Agent 拿着什么权限」。

- 子 Agent 的 scope 必须是**父 scope 的子集**，越权直接抛 `DelegationError`
- `delegation_chain` 记录完整授权路径，审计可回答「这个权限最初从哪来」
- 委托落 `audit.delegation` 事件（§4.4.7 的词表）
- `credential_refs` 只存引用（`vault://…`），明文永不落日志

## BYO 纳管

统一纳管的关键是**协议**而非实现：外部进程只要提供 `RuntimeClient`
协议的六个方法（`emit` / `record_tool_intent` / `record_tool_result` /
`lookup_tool_result` / `idempotency_key` / `checkpoint`），`ByoRegistry.adopt()`
就把它收敛成 `RuntimeClientView`，事件镜像给平台 —— 评测与成本归因
对 BYO 进程与 Managed 进程一视同仁。

## CLI 面

```bash
aicf artifact validate agents/research.yaml      # 声明校验（不落库）
aicf artifact show agents/research.yaml          # 解析后的声明
aicf artifact publish agents/research.yaml --gate <report_id>  # 发布
aicf artifact list                               # 目录快照（含状态与可做动作）
aicf artifact history research-assistant         # 生命周期事件
aicf artifact rollback research-assistant 0.4.2 --reason "回归"
```

发布被阻断的情形（都是非 0 退出码）：没带 `--gate`、报告不存在、
报告 verdict 不是 `pass`。

## 租约与工作区（部署侧的伙伴模块）

- `aicf/infra/runtime/scheduler.py`：写租约 + 心跳 + **围栏令牌**。接管把
  epoch 加一，旧实例的续约与携带旧 epoch 的写入都会被拒 ——
  这就是「实例可替换、结果不重复」的机制。
- `aicf/infra/runtime/isolation.py`：工作区 spec{fs, net, secret}。
  路径判定（resolve 后判前缀，防 `../` 与 symlink）与
  `aicf/harness/tools/sandbox/paths.py` 由交叉测试钉住结论一致。

## 测试

| 模块 | 测试 |
|---|---|
| artifact / 生命周期 / 存储 / 账本 / BYO / 委托 | `tests/test_rc1_control.py` |
| Workflow / Planner 内核 | `tests/test_rc1_kernels.py` |
| ToolDiscovery | `tests/test_rc1_tools_discovery.py` |
| Grounded / 分层记忆 | `tests/test_rc1_grounding_memory.py` |
| 抽样 / 回流 | `tests/test_rc1_eval_loop.py` |
| 租约 / 工作区 | `tests/test_rc1_scheduler_isolation.py` |
| 审计接线 | `tests/test_rc1_audit_wiring.py` |
| artifact CLI | `tests/test_rc1_cli_artifact.py` |
| 契约与加载器 | `tests/test_rc1_contracts.py` |
