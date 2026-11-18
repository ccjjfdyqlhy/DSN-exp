# 托管运行时

> 读者：要让 Agent 在崩溃后恢复、且**不重复产生副作用**的维护者。
> 目标：读完之后你能回答「崩溃之后，哪些事我做过了、哪些事我不确定」。

---

## 一句话

> **Journal 是真相，Checkpoint 只是加速器。**

---

## 一、为什么需要它

现有 `harness/transcript.py` 是「对话文本快照」：能恢复*说了什么*，
但不能保证*副作用不重复*。一次崩溃重放可能重复发请求、重复写文件、
重复扣款。

托管运行时解决的就是这件事：**让运行实例可以死，但任务状态和执行结果不会丢，
而且重放不会产生第二次副作用。**

---

## 二、两级结构

```
Event Journal (WAL, 只追加)          ← 事实的唯一真相来源
        │  周期性
        ▼
Checkpoint (快照, 可丢弃)            ← 加速恢复，不是真相来源
```

| | Journal | Checkpoint |
|---|---|---|
| 语义 | 发生了什么 | 当时到哪了 |
| 可丢弃 | ❌ 不能 | ✅ 可以 |
| 损坏后果 | 丢事实 | 从 journal 重放即可 |
| 写入方式 | 只追加 | 覆盖写 |

**Checkpoint 损坏时必须能从 journal 重放恢复** —— 这是 §8.2 用例 7 的要求。
快照里存了 journal 水位线（`__journal_seq__` 保留键），
所以「检查点之后的事件」能精确定位。

---

## 三、状态模型

| 实体 | 是什么 | 关键字段 |
|---|---|---|
| **Session** | 一次会话/任务的逻辑容器 | id, tenant, artifact_id, deployment_id, workspace_id, status, budget |
| **Turn** | 一次用户输入驱动的执行单元 | id, session_id, seq, status, input, checkpoint_ref, usage, cost, stop_reason |
| **Event** | 只追加的原子事实 | session_id, turn_id, seq, kind, payload, ts, idempotency_key |
| **Deployment** | 一个 Agent 版本在某 Runtime 上的部署实例 | id, artifact_id, spec, replicas, strategy, status |
| **Workspace** | 一次运行的可写状态空间 | id, session_id, root, spec(fs/net/secret), status |

状态枚举：

```text
SessionStatus:  ACTIVE / SUSPENDED / COMPLETED / FAILED / EXPIRED
TurnStatus:     PENDING / RUNNING / AWAITING_APPROVAL / SUCCEEDED / FAILED /
                INTERRUPTED / CANCELLED
DeploymentStatus: PENDING / ROLLOUT / HEALTHY / DEGRADED / ROLLED_BACK
WorkspaceStatus:  READY / LOCKED / RELEASED / EXPIRED
```

`AWAITING_APPROVAL` 是一个**持久的**状态，不是内存里的等待 ——
审批等待期间进程退出，重启后 turn 仍处于这个状态，决策可补填。

---

## 四、幂等执行

### 幂等键

```
idempotency_key = sha256(session_id | turn_seq | tool_name | canonical_args)
```

`canonical_args` 是**稳定序列化**：键排序、非字符串键转字符串、
不可序列化的值退化成 `repr`。同样的参数必须得到同样的键 ——
键顺序不同的等价参数（`{'a':1,'b':2}` vs `{'b':2,'a':1}`）必须命中同一条缓存。

### 副作用分级与重放策略

| 等级 | 恢复时 |
|---|---|
| `pure` | 可自动重放（重放无副作用） |
| `idempotent` | 可自动重放（重复执行无害） |
| `effectful` | **绝不自动重放** |

**未知 effect 一律按 `effectful` 处理**（fail-safe）。

### 三段式：intent → 执行 → result

```
写 intent 事件  →  执行工具  →  写 result 事件
```

恢复时如果只看到 intent、**没有**对应的 result，说明进程在执行中途死了：
这次调用的结果**未知** —— 外部系统可能没动，也可能动了一半。

此时标记 `unknown_outcome`，**交给人，绝不擅自重放**。

### 保护点在哪：执行前那一刻

```python
# infra/runtime/managed.py
if effect == EFFECT_EFFECTFUL and self._pending_intent(key) is not None:
    raise UnknownOutcomeError(unknown)
```

保护必须落在**写 intent 的那一刻**，而不是只在 `execute_tool` 里。
原因：`harness/tools/guard.py` 自己实现了
「查缓存 → 写 intent → 执行 → 写结果」这条路径，
如果保护只在 `execute_tool`，这条路径就能绕过去 → 重复扣款。

跨层识别（`infra` 不能 `import harness`）：两侧各有一份
`UnknownOutcomeError`，靠 `unknown_outcome` 标记属性互相认出。
**认不出来时一律按拒绝处理** —— 最坏后果只是错误文案不够精确。

### effectful 抛异常也算结果未知

异常不代表「什么都没发生」（外部系统可能改了一半）。
保守处理比乐观重试安全。只有 `pure` / `idempotent` 才自动重放。

---

## 五、恢复流程

```
load latest checkpoint → replay journal after checkpoint → 继续 turn
```

```python
from infra.runtime import SqliteRuntimeStore, recover

plan = recover(port, session_id)
plan.replayable   # 可以安全重放的调用
plan.unknown      # 结果未知 —— 需要人工确认
```

### 两个容易漏的坑

**坑一：副作用配对要扫全量 journal，不是「检查点之后」。**
intent 可能写在检查点之前，result 在之后甚至没有。
只看「检查点之后」会漏掉最危险的那一类：**跨检查点的在途调用**。

**坑二：结果缓存是加速器，journal 是真相。**
缓存未命中时回落到 journal 查询 —— 否则「事件写成功、缓存写失败」的
那个窗口会让已完成的 effectful 工具被重复执行。
`resume()` 会用 journal 回灌缓存。

---

## 六、事件去重

事件带 `seq`，消费方按 `seq` 去重。所有事件消费方（trace、审计、成本）
都要能容忍重复投递 —— 这是「至少一次投递 + 幂等消费」的标准组合。

Journal 本身提供 `dedupe()`。

**seq 分配在多进程下也不撞车**（测试里用 3 个进程并发分配验证过）。

---

## 七、存储

所有 DB 访问收敛在 `StorePort` 后面：

```python
class StorePort(Protocol):
    upsert_session / get_session
    upsert_turn / get_turn / list_turns / last_open_turn
    append_event / list_events / last_event_seq
    put_checkpoint / load_checkpoint / list_checkpoints
    get_tool_result / put_tool_result / find_tool_event
```

rc0 只承诺**单机语义**（SQLite）。rc1 换 Postgres 不改上层调用方 ——
这就是把所有存储访问收在一个 Protocol 后面的理由。

---

## 八、用法

```python
from infra.runtime import ManagedRuntime, SqliteRuntimeStore, migrate_runtime
from infra.store.sqlite import SqliteStore

store = SqliteStore('runtime.db')
migrate_runtime(store)
port = SqliteRuntimeStore(store)

runtime = ManagedRuntime(port, session_id='s1')
runtime.start_session()
runtime.start_turn(0)

# 工具调用：execute_tool 会自动处理 intent → 执行 → result 三段式
outcome = runtime.execute_tool(
    tool='charge_card', fn=lambda: charge(100), args={'amount': 100},
    effect='effectful',
)
```

### 崩溃之后

```bash
aicf session resume <session_id> --db runtime.db
```

输出会明确列出**可安全重放**和**结果未知**两类调用。
后者不会自动重放 —— 需要人工确认后再决定。

---

## 九、留给 rc1 的决定

**待重放的调用计划放 checkpoint，不放 journal。**

理由：journal 是只追加的事实流，也是审计与备份链路，
往里塞参数原文有敏感性成本（参数里可能有密钥 / PII）；
而 checkpoint 本来就是存 agent 状态的地方，可丢弃，语义压力小。

两条链路的敏感性天然分开。

如果 rc1 需要「不重新规划就自动重放」，走 checkpoint blob，
不要往 journal 里加参数。

---

## 相关

- [security.md](security.md) —— 审批、审计、身份
- [evaluation.md](evaluation.md) —— 怎么证明这些行为没退化
- [roadmap_1.0.0-rc0.md](roadmap_1.0.0-rc0.md) —— 里程碑与验收清单
