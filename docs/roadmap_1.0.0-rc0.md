# AICF 1.0.0-rc0 可执行计划

> 这份文档是 `AICF-1.0.0-rc0-ARCHITECTURE.md`（本地工作稿）的**执行版**：
> 把「打算怎么改」翻译成「谁改哪个文件、怎么验收、什么时候算做完」。
>
> 读者：要动手实现 1.0.0-rc0 的维护者。
> 基线：`harness-refactor` 分支 @ v0.6.2（`789cf6b`）。
>
> **本文档的每一条验收标准都对应一个可执行的测试**（测试即文档）。
> 文档与代码不一致时，以测试为准，并回来改文档。

---

## 一、rc0 的一句话目标

> 让一个 Agent 能被**安全地、幂等地、可评测地**跑完一次长任务，
> 并且它的每一次变更都能被对比、被卡口拦住、被回滚。

### 完成定义（DoD）

rc0 只有三条 DoD，全部是**可执行**的：

| # | DoD | 判定方式 |
|---|---|---|
| 1 | 一个 agent 在被 `kill -9` 一次之后仍能恢复并给出正确结果 | `tests/fault/` 里的崩溃恢复用例 |
| 2 | 它的每一次工具调用要么被审批放行、要么被策略拒绝并留下审计 | `tests/test_rc0_guard.py` + `tests/test_rc0_approval.py` |
| 3 | 它的这次运行能被一个 ≥30 case 的评测集打分，并生成一份四闸门报告 | `aicf eval` + `aicf gate` |

**不满足这三条，就不算 rc0 完成** —— 哪怕其它模块都写了。

---

## 二、现状基线（可验证，不是估计）

| 项 | 改造前 | 现在（2026-11-18 复核） | 怎么验证 |
|---|---|---|---|---|
| 核心代码量 | `aicf/harness/` 20.8k 行 + `aicf/infra/` 16.6k 行 | `aicf/harness/` 26.1k 行 + `aicf/infra/` 24.1k 行 | `find harness infra -name '*.py' \| xargs wc -l` |
| 测试基线 | 600 passed / 3 skipped | 1142 passed / 16 skipped（只算入库用例） | `pytest -q tests/` |
| 审批 / 人在回路 | 零命中 | `aicf/harness/approval/`：协议 + broker + 会话缓存 | `grep -ri approv aicf/harness/ aicf/infra/` |
| 沙箱 / 隔离 | 零命中 | `aicf/harness/tools/sandbox/`：路径判定 + restricted + namespaced；**守卫默认挂后端**，SDK 与 CLI 的默认路径都走沙箱后端（restricted 档：执行前判定 + ulimit + 环境变量白名单，**不是** OS 级隔离） | `grep -ri sandbox aicf/harness/ aicf/infra/` |
| 幂等 | 零命中 | `aicf/harness/runtime_client.py` + `aicf/infra/runtime/idempotency.py`，两份实现由交叉测试钉住 | `grep -ri idempot aicf/harness/ aicf/infra/` |
| Agent Identity | 只有用户态 `uid + scopes` | `aicf/infra/control/identity.py`：AgentIdentity + 委托链（子 scope ⊆ 父 scope，越权即拒）+ audit.delegation | `tests/test_rc1_control.py` |
| Artifact / 控制面 | 零命中 | `aicf/infra/control/`：AgentArtifact（一种声明多处消费）、生命周期状态机（release 必须携带 pass 的 Gate 报告）、成本账本、BYO 纳管 | `tests/test_rc1_control.py` |
| Experiment / Run Version | 零命中 | `aicf/infra/eval/{experiment,run_version}.py`（最小版） | `grep -ri experiment aicf/harness/ aicf/infra/` |
| Workflow / Planner | 零命中 | `aicf/harness/kernel/{workflow,planner}.py`：DAG（并行分支 + 逆序补偿）与 Planner-Executor（结构化计划 + 有界重规划）| `tests/test_rc1_kernels.py` |
| 遥测 | 有事件词表，无 trace/span 模型 | `aicf/harness/telemetry/` + `aicf/infra/observability/{span,trace,audit}.py`；audit.* 事件已接线到不可删 AuditStore（SDK/CLI 默认路径） | `tests/test_rc1_audit_wiring.py` |

> 中间一列是策划案在改造前的结论，右列是 2026-11-18 重新核对的结果。
> 每一行的验证命令都还能跑，所以「缺口是否真的补上了」是一个可以核对的事实，
> 而不是一句总结。Agent Identity 与 Artifact 两行是**故意**没补的：
> 它们属于 rc1 的控制面。

---

## 三、工作流分解

八个交付物（R1–R8），拆成 11 个可并行的任务。
依赖规则：**契约层 → 能力层 → 集成层 → 验证层**。

```
                    ┌─────────────────────────────┐
                    │ T1 共享契约层               │  ← 必须先落地
                    │ ToolSpec / Policy / Approval│
                    │ Sandbox / Telemetry /       │
                    │ RuntimeClient / 事件词表v2  │
                    └──────────────┬──────────────┘
        ┌────────────────┬──────────┴────────┬────────────────┐
        ▼                ▼                   ▼                ▼
   ┌─────────┐     ┌──────────┐       ┌──────────┐     ┌──────────┐
   │ R1 准入 │     │ R3 沙箱  │       │ R4 运行时│     │ R6 评测  │
   │ +统一入口│    │ restricted│      │ Journal  │     │ Dataset  │
   │ (T2)    │     │ namespaced│     │ +幂等    │     │ +Gate    │
   └────┬────┘     │ (T3)     │       │ (T4)     │     │ (T5)     │
        │          └──────────┘       └──────────┘     └──────────┘
        ▼
   ┌─────────┐     ┌──────────┐
   │ R2 审批 │     │ R5 遥测  │
   │ (T6)    │     │ Trace v1 │
   └────┬────┘     │ (T7)     │
        │          └──────────┘
        ▼
   ┌──────────────────────────────────────┐
   │ 执行内核 SPI：ExecutionKernel (T8)    │
   └──────────────────┬───────────────────┘
                      ▼
      ┌───────────────┬──────────────────┐
      ▼               ▼                  ▼
 ┌─────────┐   ┌──────────┐      ┌──────────┐
 │ R7 故障 │   │ R8 CLI   │      │ R8 文档  │
 │ 注入测试│   │ (T10)    │      │ (T11)    │
 │ (T9)    │   └──────────┘      └──────────┘
 └─────────┘
```

### 任务清单

| 任务 | 交付物 | 主要文件 | 验收标准 | 状态 |
|---|---|---|---|---|
| **T1** | 共享契约层 | `aicf/harness/tools/spec.py`、`aicf/harness/policy/base.py`、`aicf/harness/approval/base.py`、`aicf/harness/tools/sandbox/base.py`、`aicf/harness/telemetry/base.py`、`aicf/harness/runtime_client.py`、`aicf/harness/agent/events.py` | 所有新模块可独立 import；**不 import aicf.infra**；既有测试全绿 | ✅ 完成 |
| **T2** | R1 ToolSpec + 准入策略 + 统一入口 | `aicf/infra/policy/engine.py`、`aicf/harness/tools/guard.py`、`aicf/harness/tools/registry.py`、`aicf/harness/tools/base.py`、`aicf/harness/tools/standard.py` | 未声明 sandbox 的工具按最严格档；越权调用被拒并记审计；默认不挂 guard 时旧用法不受影响 | ✅ 完成 |
| **T3** | R3 沙箱 | `aicf/harness/tools/sandbox/{paths,restricted,namespaced}.py`、`aicf/harness/tools/shell.py` | 路径逃逸被拦；出网被拦；降级时 `degraded=True` 可见 | ✅ 完成 |
| **T4** | R4 托管运行时 | `aicf/infra/runtime/*` | 幂等键稳定；journal seq 单调；恢复不重复执行 `pure` 工具；`effectful` 标 `unknown_outcome` | ✅ 完成 |
| **T5** | R6 评测闭环 | `aicf/infra/eval/*`、`aicf/harness/datasets/basic.yaml` | ≥30 case 可跑；四闸门报告；安全闸门 0 容忍；`aicf/infra/eval` 不 import `harness` | ✅ 完成（40 case / 7 分组） |
| **T6** | R2 审批链路 | `aicf/harness/approval/{broker,session,events}.py` | 超时 = 拒绝；会话级放行缓存；等待期间进程退出可恢复补填 | ✅ 完成 |
| **T7** | R5 遥测标准化 | `aicf/harness/telemetry/*`、`aicf/infra/observability/{trace,audit}.py` | 既有事件 kind 不变；JSONL trace；统一 `redact()` | ✅ 完成 |
| **T8** | 执行内核 SPI | `aicf/harness/kernel/*` | `ExecutionKernel` 协议；能力协商收敛；旧 `AgentLoop` API 不破坏 | ✅ 完成 |
| **T9** | R7 故障注入测试 | `tests/fault/*` | §8.2 的 7 条用例全部可自动运行 | ✅ 完成（7/7，59 条：46 条运行 + 11 条变异 + 2 条元测试） |
| **T10** | R8 CLI | `aicf/harness/cli/*`、`pyproject.toml` | `aicf --help` 可用；run → eval → gate 跑通 | ✅ 完成 |
| **T11** | R8 文档 | `docs/*`、`README*.md` | 每条验收标准映射到一个测试 | ✅ 完成 |
| **T12** | 默认路径的安全接线 | `aicf/harness/tools/{guard,standard,registry,base}.py`、`aicf/harness/agent/assembler.py` | 守卫默认挂沙箱后端（restricted 档）；`proc.run` 走沙箱后端的判定与限制；`batch.run` 走守卫；SDK 路径默认装守卫 | ✅ 完成（`test_rc0_default_path_security.py` 13 条，修复前 12 条红） |
| **T13** | 托管运行时接入 CLI | `aicf/harness/cli/{common,runcmd,toolcmd,sessioncmd}.py` | `aicf run` / `tool exec` 落 journal；`session resume` 能算出恢复计划 | ✅ 完成（`test_rc0_cli_session.py` 5 条，修复前 4 条红） |
| **T14** | 记忆读回 | `aicf/harness/memory/in_memory.py`、`aicf/harness/sdk.py` | `enable_memory=True` 会写入并召回，关键词检索支持中文 | ✅ 完成（`test_rc0_memory.py` 7 条） |
| **T15** | CI 门禁补齐 | `.github/workflows/ci.yml` | contract 与 eval 两个 job；变异层进 nightly；test job 不再误收故障层 | ✅ 完成 |

### 当前测试基线

```text
1282 passed,  1 skipped     # 本机全量（2026-11-20；入库口径不含本机专用的
                            # test_dsn_existence_loop.py，见下方说明）
  46 passed, 13 skipped     # 故障注入层 tests/fault/（2.1s；跳过的 13 条是变异层，默认不跑）
 128 passed                 # rc1/rc2 对齐新增（控制面 / 内核 / 发现 / 记忆 /
                            # 抽样回流 / 租约隔离 / 审计接线 / CLI / 契约）
```

改造前的基线是 **600 passed / 3 skipped**（本地口径；只算入库用例是 **562 / 3**）。
两个数字差 38 条，来自 `tests/test_dsn_existence_loop.py`。它依赖不在本仓的 `apps/`，
按 `.git/local-only-policy.txt` 留在本机。增量里包含（入库口径，共 568 条）：
契约层 25 条、依赖方向 198 条、准入与守卫 28 条、审批 16 条、
沙箱 40 条、运行时 50 条、评测 66 条、遥测 55 条、
内核 15 条、CLI 16 条、故障注入 59 条（46 运行 + 13 跳过）。

> **变异层默认不跑**：`RUN_MUTATION=1 pytest -q tests/fault/mutation/`（约 20s）。

### 变异测试层（rc0 之后要维护的东西）

`tests/fault/mutation/` 验证的是**测试套件本身有没有牙齿**：
11 条变异，每条拆掉实现里的一条保护（幂等缓存、journal 去重、
checkpoint 损坏检测、awaiting_approval 状态、审批补填、路径越界判定……），
然后断言对应用例**立刻变红**。

为什么值得做：「测试全绿」不能证明「kill -9 后仍能恢复」——
恒真断言也是全绿的。变异测试证明的是「每条保护一旦被拆掉，
对应用例立刻变红」。

两条元测试保证这个工具自己不出事：
- 假变异（拆一个没人依赖的东西）必须被如实报告为**「没被抓住」**
- 补丁打不上时（实现改名了）必须报 `MUTATION_NOT_APPLIED`，
  **大声说「变异没生效」**，而不是安静地报告「全部通过」

跑法：`RUN_MUTATION=1 python -m pytest -q tests/fault/mutation/`（21.6s）。
**rc1 待办**：把它加进 nightly CI。

### 与策划案的偏离（都有理由）

| 策划案 | 实际 | 为什么 |
|---|---|---|
| `apps/aicf_cli/` | `aicf/harness/cli/` | 仓库已完成「收敛为纯库」的拆分，`apps/` 已 gitignore。CLI 是核心库的门面，要随 `pip install aicf-core` 一起可用 |
| `datasets/basic.yaml` | `aicf/harness/datasets/basic.yaml` | 顶层 `datasets` 作为可 import 的包会污染全局命名空间，且与 HuggingFace 的 `datasets` 同名。放进 `aicf/harness/` 后既是包数据又不抢名字 |
| `aicf/infra/runtime.py` | `aicf/infra/runtime/di.py` | 同名包会遮蔽同名模块 —— `aicf/infra/runtime/` 一旦存在，`aicf/infra/runtime.py` 就永远不会被加载。DI 容器整体迁入，包级 `Runtime` 仍指向它，harness 侧 API 不变 |
| 托管运行时叫 `Runtime` | 叫 `ManagedRuntime` | 包级 `Runtime` 是冻结的 DI 容器 API，不能改。`aicf/infra/runtime/managed.py` 里有 `Runtime = ManagedRuntime` 别名 |
| `aicf eval --artifact a.yaml` | `aicf eval --traces <path>` | Artifact 资产模型属 rc1 的控制面。rc0 的 eval 消费的是 **trace**（这是运行的事实），artifact 只作为 run version 的元数据参与 |
| `aicf run <artifact.yaml>` | `aicf run --artifact <path>` | run 的第一个位置参数留给用户输入；声明走显式 flag，让 `aicf run "..."` 的旧用法不破坏 |
| 托管运行时的 `scheduler.py` / `isolation.py` | rc2 才落 | 策划案 §6.1 把两个文件画在 rc0 的目录树里，但 §4.2.4/§7.3 把「调度与隔离」归入 rc2 —— 以行为描述为准 |

### 并行开发的代价（实测）

四个工作流并行开工，**契约层（T1）先行**是决定性的：

- 契约层落地后，R4（运行时）、R6（评测）、R7（故障注入）三个工作流的
  用例**第一次写就全绿**，且没发现实现 bug —— 因为测试是对着契约写的，
  不是对着实现猜的
- 两处**必须各写一份**的契约（幂等键公式、`UnknownOutcomeError` 的识别标记），
  用**交叉测试**钉住，而不是靠约定文档

代价是路线图里新增的两条风险（R-9 契约漂移、R-10 双实现漂移）——
这两条在契约层先行的情况下都没有变成事故。

---

## 四、每个交付物的详细验收

### R1 · ToolSpec 与统一入口

**核心不变式**：一个工具调用**只能**从 `ToolRegistry.execute*()` 出去。

```
Agent → ToolRegistry.execute_async() → ToolGuard → PolicyEngine
                                                     → ApprovalBroker
                                                     → 幂等检查（RuntimeClient）
                                                     → handler（沙箱经 ToolContext 注入）
```

- 未声明 `spec` 的工具 → `effectful + isolated + 需审批`（**「忘写声明」不等于静默放开**）
- `read_only=True` 的工具 → `pure + readonly`（只读本身就是一条显式声明）
- 策略求值顺序：显式 deny → 越权检查 → 显式 allow → 风险阈值 → 默认拒绝
- 策略引擎自己抛异常 → 按拒绝处理（fail-closed）
- 审批超时 → 拒绝；「没有审批代理」→ 拒绝
- 没有挂 guard → legacy 直连模式，打**一次**显著告警

> **为什么必须 fail-closed**：判定失败时「先执行了再说」等于把安全模型
> 建立在「策略服务永远可用」这个假设上，而那正是它挂掉的时候。

### R2 · 审批链路

| 形态 | 用途 | 实现 |
|---|---|---|
| 同步等待 | CLI / 本地控制台 | `LocalApprovalBroker(resolver=...)` |
| 异步回填 | Web 控制台（SSE 推 `approval_request`） | `LocalApprovalBroker()` + `submit(id, decision)` |

- 放行作用域：`once` / `session` / `tool:<name>` / `always`
- **未知作用域不记缓存**（当成「永久放行」是安全事故）
- 超时是**独立事件** `approval_timeout`，不能混进 `deny` ——
  事故复盘时「没人理」和「被拒绝」含义完全不同
- 待决请求可导出 / 恢复 → 审批等待期间进程退出，重启后仍 `awaiting_approval`

### R3 · 沙箱

| 后端 | 机制 | 强度 | 何时用 |
|---|---|---|---|
| `none` | 直接 subprocess | 无 | 仅测试 |
| `restricted` | 子进程 + `ulimit` + 路径白名单 + 环境变量白名单 | 弱 | 默认降级档 |
| `namespaced` | namespace / bubblewrap / nsjail | 中 | Linux 生产 |
| `isolated` | 容器 / 微虚机 | 强 | rc1 |

**降级原则**：检测不到强隔离后端时**不报错阻断**，但必须 `degraded=True`
并在事件与审计里标注。上层策略可以选择「降级即拒绝」。
**绝不允许「以为自己在沙箱里」。**

### R4 · 托管运行时

```
Event Journal (WAL, 只追加)     ← 事实的唯一真相来源
        │ 周期性
        ▼
Checkpoint (快照, 可丢弃)       ← 加速恢复，不是真相来源
```

- 幂等键：`sha256(session_id | turn_seq | tool_name | canonical_args)`
- 副作用分级：
  - `pure` — 可自由重放
  - `idempotent` — 可自动重放
  - `effectful` — **默认不自动重放**
- `effectful` 强制「先写 intent → 执行 → 写 result」；
  恢复时只有 intent 没有 result → 标 `unknown_outcome`，**交给人，绝不擅自重放**
- 恢复流程：`load checkpoint → replay journal → 继续 turn`；
  checkpoint 损坏时从 journal 重放

> **幂等键实现有两份**（`aicf/harness/runtime_client.py` 与 `aicf/infra/runtime/idempotency.py`），
> 因为依赖规则禁止 `infra` → `harness`。用一条**交叉测试**钉住两份实现一致。

### R5 · 遥测标准化

- 事件词表**只增不改**：既有 kind 一个不动，只加三个可选字段
  （`trace_id` / `span_id` / `seq`），旧生产者不带它们时消费方必须容忍
- Kernel 只发事件，**不做格式化**；`aicf/infra/observability` 负责扇出成 trace
- `args_digest` 只存参数的**哈希与长度**，敏感值替换为 `***`
- 统一 `redact()`，避免各处漏改

### R6 · 评测闭环

断言语言（**刻意做小，不做通用编程语言**）：
`tool_called` / `output_contains` / `output_matches` / `max_tool_calls` /
`forbid_tools` / `no_side_effect` / `cost_tokens` / `latency_ms` / `assert_fn`

四道闸门（任一不过即阻断发布）：

| 闸门 | 判定 | 默认阈值 |
|---|---|---|
| 质量 | 关键 case 通过率 | 100% |
| 回归 | 相对 baseline 的指标下降 | 任一指标下降 > 2% |
| 成本 | 单 case / 单会话成本 | 不超过 baseline × 1.2 |
| 安全 | forbidden_tool / sandbox_escape / 越权 | **0 容忍（硬失败）** |

> 安全闸门**不参与平均** —— 一次越权不能被其它指标的高分抵消。

---

## 五、测试策略

### 五层

| 层 | 目标 | 门禁 |
|---|---|---|
| L1 单元 | 纯函数与协议 | 每次提交 |
| L2 契约 | 端口实现一致性（沙箱后端、store、evaluator 互换） | 每次提交 |
| L3 集成 | 端到端一轮对话 + 工具（假模型 `aicf/infra/orchestrator/stub.py`） | 每次提交 |
| L4 故障注入 | kill -9 / 断网 / 超时 / 重复投递 | 每夜 |
| L5 评测 | Dataset 回归 + Gate | 每次发布 |

### 必须存在的故障注入用例（对应 JD 第 2 条）

1. 工具执行中途 `kill -9` → 重启 → 恢复 → `pure` 不重复、`effectful` 标 `unknown_outcome`
2. 同一 `idempotency_key` 重复投递 3 次 → 副作用只发生 1 次
3. 审批等待期间进程退出 → 重启后仍 `awaiting_approval`，决策可补填
4. 沙箱内 `cat ../../etc/passwd` → 被拦并记审计
5. 沙箱内出网到非 allowlist 域名 → 被拦并记 `net:deny`
6. 事件重复投递 → 消费方按 `seq` 去重，不重复计费
7. checkpoint 损坏 → 从 journal 重放恢复

### CI 门禁

`ci.yml` 现在有四个 job：`test`（每次提交，python 3.10 - 3.13，排除 fault/mutation）、
`build`（构建 + 元数据检查）、`contract`（契约层 + 依赖方向单列）、`eval`（评测层 +
`aicf eval`/`aicf gate` 冒烟）、`fault`（nightly + 手动触发，跑 `tests/fault/`）。

策划案 §8.3 的四个 job 形态至此全部落地。

---

## 六、风险登记册（含本轮新增）

| # | 风险 | 影响 | 缓解 | 触发条件 |
|---|---|---|---|---|
| R-1 | 范围膨胀 | 高 | rc0 只做 R1–R8；每项交付物必须有可执行验收 | 出现「顺手把 rc1 也做了」 |
| R-2 | 半成品安全比没安全更危险 | 高 | 降级必须 `degraded=True` 且事件可见；策略可选择「降级即拒绝」 | 沙箱后端探测失败 |
| R-3 | 幂等做不彻底 | 高 | 依赖规则 5 + CI 里静态 grep `subprocess` / `os.system` + 审计兜底 | 出现绕过 registry 的调用点 |
| R-4 | 双轨期无限延长 | 中 | 每个版本公告点名 legacy 使用方；2 个版本后删 legacy 直连 | v1.0.0 发布时仍有 legacy |
| R-5 | bus factor = 1 | 高 | 协议先行（Protocol + contract test），新人能在不改实现的前提下加后端 | —— |
| R-6 | 没有真实业务流量 | 中 | 公开任务集 + 本地多场景；rc1 起支持线上抽样 | —— |
| R-7 | sqlite 撑不住生产 | 中 | 所有存储访问走 `StorePort`；rc1 换 Postgres 不改上层 | —— |
| R-8 | 评测集变成负担 | 中 | 断言语言做小；回归集冻结只增不删 | case 数增长但无人维护 |
| **R-9** | **契约漂移**（本轮新增） | **高** | T1 契约层先行；每个契约模块有契约测试；并行工作流只依赖协议不依赖实现 | 出现「两个工作流对同一个字段名理解不同」 |
| **R-10** | **两份幂等键实现漂移**（本轮新增） | 中 | `infra` 不能 import `harness`（依赖规则），只能各写一份 → 用交叉测试钉住 | 交叉测试变红 |

> **R-9 是本轮并行开发最大的风险**。四个工作流同时开工时，
> 「审批请求的载荷长什么样」「幂等键怎么算」这类问题如果各答各的，
> 集成时会以非常难查的方式失败。所以 T1 把所有跨工作流的数据形状
> 先定死，并要求每个工作流**只依赖协议**。

---

## 七、rc1 / rc2 的接口预留

下面这些接口在 rc0 时**提前留好**，rc1/rc2 落地时没有回头重写 rc0 ——
这张表现在同时是「已兑现清单」：

| 预留 | 位置 | rc1 怎么用 |
|---|---|---|
| `ExecutionKernel` 协议 | `aicf/harness/kernel/base.py` | 加 `WorkflowKernel` / `PlannerKernel`，业务代码只换类 |
| `KernelResult.status = 'awaiting_approval'` | `aicf/harness/kernel/base.py` | rc1 的发布闸门要能挂起一个待审批的运行 |
| `RuntimeClient` 协议 | `aicf/harness/runtime_client.py` | rc1 跨进程 / 跨机恢复，Kernel 侧不用改 |
| `PolicyEngine` 协议 | `aicf/harness/policy/base.py` | rc1 加「按 artifact 下发策略」，实现换掉即可 |
| `ApprovalBroker` 协议 | `aicf/harness/approval/base.py` | rc1 的 Web 控制台用异步回填形态 |
| `Sandbox` 协议 | `aicf/harness/tools/sandbox/base.py` | rc1 加 `isolated` 后端（容器） |
| `CapabilitySet` | `aicf/harness/kernel/capability.py` | rc1 的 Workflow 按能力选并行度 |
| `ToolSpec.version` | `aicf/harness/tools/spec.py` | rc1 的 artifact 用**版本引用**而非名字引用 |

---

## 八、版本与发布

- rc0 期间版本号保持 `0.6.x`；**不**提前跳到 `1.0.0rc0`。
  理由：策划案原打算先跳版本号，但仓库随后经历了「收敛为纯库」的拆分
  （`d8ae89b`）并回到 `0.6.2` 发布（`1c8d133`）。**版本号要在 DoD 达成、
  准备发第一个 rc 的时候再跳** —— 半成品的 rc 标签比没有标签更糟。
- rc0 达成后：`version = "1.0.0rc0"`，发 tag `v1.0.0rc0`，
  `aicf.harness.__version__` 同步（`tests/test_version.py` 会检查三处一致）
- 公开 API 冻结从 rc0 开始；新增事件 kind / ToolSpec 字段一律**只增不改**

---

## 九、验收清单（逐条可勾选）

> 勾选状态反映 rc0 的实际进展。每一项后面的括号是**钉住它的测试**。

### 安全

- [x] 未声明 `spec` 的工具按 `effectful + isolated + 需审批` 处理
      （`test_rc0_guard.py::test_tool_without_spec_is_treated_as_strictest`）
- [x] 越权调用被拒，理由分类为 `scope`，并留审计
      （`test_rc0_guard.py::test_scope_violation_is_denied`）
- [x] 显式 deny 规则永远赢过 allow 规则
      （`test_rc0_guard.py::test_deny_rule_beats_allow_rule`）
- [x] 策略引擎异常 → 拒绝（不是放行）
      （`test_rc0_guard.py::test_policy_failure_fails_closed`）
- [x] 审批超时 → 拒绝，且记为独立的 `approval_timeout`
      （`test_rc0_approval.py::test_timeout_emits_its_own_event`）
- [x] 没有审批代理 → 拒绝
      （`test_rc0_guard.py::test_missing_approval_broker_denies_by_default`）
- [x] 沙箱路径逃逸（`../`、符号链接）被拦
      （`tests/fault/test_sandbox_path_escape.py`；判定层在 `sandbox/paths.py`，
      执行层在 `sandbox/restricted.py`）
- [x] 沙箱出网被拦
      （`tests/fault/test_sandbox_network_deny.py`）
- [x] 沙箱降级时 `degraded=True` 可见
      （restricted 档**永远** degraded=True —— 它是「检查」不是「隔离」，
      强隔离在 namespaced 档；见 `sandbox/restricted.py` 的文件头注释）
- [x] 凭据 / 敏感参数不出现在日志、事件、trace 里
      （`test_rc0_guard.py::test_args_digest_does_not_leak_plaintext`）

### 幂等

- [x] 幂等键对等价参数（键顺序不同）稳定
      （`test_rc0_runtime.py`，含 aicf/harness/infra 两侧的交叉测试）
- [x] 同一幂等键重复投递 3 次 → 副作用只发生 1 次
      （`tests/fault/test_idempotent_delivery.py`，5 例）
- [x] `kill -9` 后恢复：`pure` 不重复执行
      （`tests/fault/test_crash_recovery.py`，真 `os._exit(9)` 子进程）
- [x] `kill -9` 后恢复：`effectful` 标 `unknown_outcome` 且不自动重放
      （`tests/fault/test_crash_recovery.py::test_kill9_during_effectful_tool_blocks_automatic_replay`）
- [x] 审批等待期间进程退出 → 仍 `awaiting_approval`，决策可补填
      （`tests/fault/test_approval_crash_resume.py`，真 SIGKILL）
- [x] checkpoint 损坏 → 从 journal 重放恢复
      （`tests/fault/test_checkpoint_corruption.py`，8 例，两种损坏形态）

### 可评测

- [x] ≥30 case 的 dataset 可跑 —— **实际 40 case / 7 分组**
      （`test_rc0_eval.py::test_basic_dataset_has_enough_cases_and_groups`）
- [x] 四闸门报告含每道闸门的判定与失败明细
      （`test_rc0_eval.py`、`test_rc0_cli.py::test_run_to_eval_to_gate_chain`）
- [x] 安全闸门 0 容忍（不参与平均）
      （`test_rc0_eval.py`，含「没有关闭硬失败的开关」这条不变量）
- [x] RunVersion 冻结快照（commit + artifact + dataset hash + model + tool 版本）
      （`test_rc0_eval.py::test_run_version_freezes_everything`）
- [x] 相对 baseline 的逐指标差异可输出
      （`test_rc0_eval.py`）

### 工程

- [x] 既有 600 个测试全绿（改造不破坏现有用户）—— **当前 1142 passed / 16 skipped**
- [x] 所有新增模块可独立 import
      （`test_rc0_contracts.py`）
- [x] `harness` 不 import `infra` 的实现（只依赖协议）
      （`test_rc0_contracts.py::test_contract_modules_do_not_import_infra`）
- [x] `aicf/infra/eval` 不 import `harness`
      （模块级 import 扫描 + 子进程运行期断言）
- [x] `aicf --help` 可用；run → eval → gate 跑通
      （`test_rc0_cli.py`，已从 pip 安装验证）
- [x] README 徽章是 CI 自动生成的真实数字
      （徽章指向 CI workflow 状态，不再写死测试数）
- [x] 文档里每条验收标准都能指到一个测试
      （本文档每条勾选项后都标了测试名）

### 额外加的一条

- [x] **用例不是恒真断言** —— 变异测试验证：拆掉实现里的 11 条保护，
      对应用例立刻变红
      （`tests/fault/mutation/`；变异层默认不跑，需显式开启）

### 默认路径也要有闸门

- [x] **沙箱不是声明而已** —— `proc.run` 的 ToolSpec 声明了 `sandbox="workspace"`，
      但 handler 曾经直接跑裸 subprocess。工作区内可用、工作区外被拦，
      且违规进审计（`test_rc0_default_path_security.py`）
- [x] **SDK 路径也要装守卫** —— `create_agent` 装出来的 Agent 带守卫，
      策略 / 审批 / 沙箱 / 审计 / 幂等都在默认路径上生效
- [x] **没有旁路** —— `batch.run` 曾经直接调 handler，绕过整条链路；
      现在内层调用也走注册表
- [x] **CLI 落 journal** —— `aicf run` 与 `aicf tool exec` 的工具意图写进
      托管运行时，`aicf session resume` 能算出「哪些事我可能已经做过了」

---

## 十、诚实清单（2026-11-20 复核）

上一版清单里的六条欠账，全部在 rc1/rc2 工作流里补齐了。
补齐的方式与测试如下 —— 这张表保留，只是方向反过来：
从「我们欠什么」变成「我们怎么证明还清了」。

| 上一版欠账 | 现状 | 钉住它的测试 |
|---|---|---|
| 不可删审计存储没接线 | `ToolGuard` 增加 `audit` 参数（鸭子类型：会 `record(kind, payload)` 即可）；`audit.denied` / `audit.tool_call` 落独立存储，SDK 与 CLI 两条默认路径都接线；审计后端故障不阻断调用（trace 面兜底） | `tests/test_rc1_audit_wiring.py` |
| 控制面 | `aicf/infra/control/`：`AgentArtifact`（§4.5.1 一种声明多处消费）、生命周期状态机（**release 必须携带 verdict=pass 的 Gate 报告**，§4.5.2）、`ArtifactStore`（(id, version) 不可变，冲突即拒）、成本账本（按 session/agent/tool/model 归因，§4.5.3）、BYO 纳管（按 RuntimeClient 协议接入 + 事件镜像，§4.5.4） | `tests/test_rc1_control.py` |
| Agent 身份与委托 | `aicf/infra/control/identity.py`：`AgentIdentity` + `delegation_chain`；子 scope 必须 ⊆ 父 scope，越权即拒；委托写 `audit.delegation` | `tests/test_rc1_control.py` |
| 多执行架构 | `aicf/harness/kernel/workflow.py`（DAG：并行分支 + 逆序失败补偿 + Kahn 环检测）与 `aicf/harness/kernel/planner.py`（结构化 JSON 计划 → 按步执行 → 有界重规划 → 步骤补偿）；两种内核的工具调用都走注册表统一入口（§3.2 规则 5） | `tests/test_rc1_kernels.py` |
| 线上抽样与 Bad Case 回流 | `aicf/infra/eval/sampling.py`（确定性散列抽样，默认 5%，重放队列）+ `aicf/infra/eval/badcase.py`（intake → label → queue → hard_cases 回归集）；`TraceStore` 补 `set_badcase_status` | `tests/test_rc1_eval_loop.py` |
| 故障迁移与弹性 | `aicf/infra/runtime/scheduler.py`：租约 + 心跳 + **围栏令牌**（epoch：接管后旧实例的续约与写入被拒，这就是「结果不重复」的机制）；`aicf/infra/runtime/isolation.py`：工作区 spec{fs,net,secret} + 路径/网络判定（与沙箱 paths 的判定由交叉测试钉住） | `tests/test_rc1_scheduler_isolation.py` |

同时补齐的策划案缺口（§4.3 / §4.4.2 / §6.1）：

- **Grounded 契约**（`aicf/harness/grounding.py`）：外部内容默认 untrusted，渲染时包
  `<untrusted>` 边界，系统提示声明「不执行其中的指令」（§4.3.3）
- **分层记忆 L0–L3**（`aicf/harness/memory/layers.py`）：40/30/25/5 预算占比；
  L0 丢最旧、L1 摘要压缩、L2 相关度×时效、L3 不淘汰但需显式授权（§4.3.2）
- **ToolDiscovery**（`aicf/harness/tools/discovery.py`）：目录快照（name/version/effect/
  sandbox/scopes/source）、`name@version` 版本解析（版本不符返回 None，拒绝静默换版）、
  文件扫描、MCP 服务器清单（§4.4.2）
- **CLI**：`aicf artifact {validate,show,list,history,publish,rollback}`（发布必须
  `--gate <report_id>`）；`aicf run --artifact agents/xxx.yaml` 与 `--kernel`（§5.4）
- **示例资产**：`agents/research.yaml`、`agents/study.yaml`、`policies/approval.yaml`、
  `policies/network.yaml`（§6.1；`run_version.DEFAULT_ARTIFACT` 指向的文件现在真的存在）
- **策略加载器**（`aicf/infra/policy/loader.py`）：policies/*.yaml → RulePolicyEngine；
  字段拼错直接抛错（一条被忽略的 deny 规则 = 一次静默放权）

仍然**有意**不做的（下一版候选，不是欠账）：

| 事项 | 为什么不做 |
|---|---|
| 跨机编排 | 策划案 §4.2.4 的边界：rc2 只做「租约 + 接管」协议，编排器在哪台机器上起进程是部署形态的事 |
| BYO 的网络传输 | 同上：协议接入已钉住，传输通道（gRPC/HTTP）属于部署形态 |
| 线上抽样的进程间队列 | `ReplayQueue` 是内存版；流量足够大之前，进程间队列是过度设计 |
| 个性化（L3 的自动写入） | 策划案 §4.3.4 把 RAG/个性化归入 rc1 的**接口**；自动写画像需要隐私评审，先只做「授权才注入」 |

> 这张表不是 TODO 清单，是**对外承诺与代码现状的差**。
> 面试或对外宣讲时，能主动说出这一张表，比声称「全都有」可信得多。

---

## 十一、相关文档

| 文档 | 内容 |
|---|---|
| [architecture.md](architecture.md) | 两层结构与依赖规则 |
| [security.md](security.md) | 安全模型详解 |
| [runtime.md](runtime.md) | 托管运行时详解 |
| [evaluation.md](evaluation.md) | 评测闭环详解 |
| [maintenance.md](maintenance.md) | 改代码前的不变量清单 |
| [technical-debt.md](technical-debt.md) | 已知技术债 |
