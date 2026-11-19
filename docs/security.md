# 安全模型

> 读者：要给 AICF 装上工具、或者要审查一条工具调用为什么被放行/拒绝的维护者。
> 目标：读完之后你能准确回答「这次调用凭什么执行」「凭什么没执行」。

---

## 一句话

> **默认拒绝。** 没有策略授权的工具调用一律拒绝，
> 而不是「默认允许、记录一下」。

---

## 一、威胁模型

我们要防的不是「恶意用户」，而是**一个被诱导的模型**：
提示注入、外部网页、工具输出里藏的指令，都可能让模型调起
一个它本来不该调的工具。

所以防线不建在「模型会不会乱来」上，而是建在**每一次调用都要过闸**上：

```
模型想调工具
   → ToolSpec：这个工具声明了什么副作用、要什么权限
   → PolicyEngine：策略允许吗？身份有权限吗？（显式 deny 永远赢）
   → ApprovalBroker：需要人点头吗？（超时 = 拒绝）
   → 幂等检查：这个调用是不是已经做过了？
   → Sandbox：在什么隔离档里执行？（降级必须可见）
   → 审计：全部记下来
```

**任何一环不确定，结果都是拒绝。** 判定不出来不是「放行」的理由。

---

## 二、工具契约：`ToolSpec`

```python
@dataclass(frozen=True)
class ToolSpec:
    name: str
    version: str = '1.0'
    effect: Literal['pure', 'idempotent', 'effectful'] = 'effectful'
    scopes: tuple[str, ...] = ()                 # 需要的授权范围
    sandbox: Literal['none','readonly','workspace','isolated'] = 'isolated'
    network: Literal['none','allowlist','full'] = 'none'
    destructive: bool = False
```

### 未声明 = 最严格

没有 `spec` 的工具，按 `effectful + isolated + 需审批` 处理。

这条规则的全部意义在于：**「忘写声明」不能等于「静默放开权限」**。
声明缺失是一个**配置错误**，配置错误必须表现为「更严」而不是「更松」。

例外只有一个：`AnnotatedTool(read_only=True)` —— 「只读」本身就是一条
显式声明，所以可以据此收窄到 `pure + readonly`。

### 副作用分级

| 等级 | 含义 | 恢复时能自动重放吗 | 默认要审批吗 |
|---|---|---|---|
| `pure` | 纯计算，不改任何东西 | ✅ | 否 |
| `idempotent` | 写操作但重复执行无害 | ✅ | 否 |
| `effectful` | 发消息 / 扣款 / 改外部系统 | ❌ **绝不** | ✅ |

`effectful` 的恢复策略是整个安全模型里最关键的一条：
**宁可让任务卡住等人确认，也不能重复扣款。**

---

## 三、准入策略

求值顺序（先命中先生效）：

1. **显式 deny 规则** —— 永远赢，哪怕后面有 allow 规则
2. **越权检查** —— 工具所需 scope 不在身份 scope 内 → 拒绝（理由 `scope`）
3. **显式 allow 规则** —— 如只读工具白名单
4. **风险阈值** —— `risk <= threshold` 自动放行
5. **默认拒绝** → 需要人工审批

风险等级由工具契约算出：

| 条件 | 风险 |
|---|---|
| `destructive=True` | high |
| `effect=effectful` | high |
| `effect=idempotent` | medium |
| `effect=pure` | low |
| `network=full` | 升一级 |
| `sandbox=none` | 升一级（从 low 起） |

**策略引擎自己抛异常时按拒绝处理。** 把安全模型建立在「策略服务永远可用」
这个假设上，而那正是它挂掉的时候。

---

## 四、审批（人在回路）

### 决策取值

| 决策 | 含义 |
|---|---|
| `approve` / `approve_once` | 放行这一次 |
| `approve_always` | 放行并按 `scope` 记住 |
| `deny` | 拒绝 |
| `timeout` | 等待超时 —— **语义上等于拒绝** |

### 放行作用域

| scope | 作用范围 |
|---|---|
| `once` | 只这一次，不记缓存 |
| `session` | 本会话内该工具都放行 |
| `tool:<name>` | 该工具跨会话放行 |
| `always` | 该工具永久放行 |

**未知作用域不记缓存。** 把「没搞懂的 scope」当成「永久放行」是安全事故。

### 两种等待形态

| 形态 | 场景 | 实现 |
|---|---|---|
| 同步等待 | CLI / 本地控制台 | `LocalApprovalBroker(resolver=...)` |
| 异步回填 | Web 控制台（SSE 推事件，人点一下再回填） | `LocalApprovalBroker()` + `submit(id, decision)` |

### 超时是独立事件

超时发 `approval_timeout`，**不混进 `deny`**。
事故复盘时「没人理」和「被拒绝」是两件完全不同的事：
前者是流程问题，后者是权限问题。

### 挂起与恢复

审批等待期间进程退出，重启后这次调用必须仍处于 `awaiting_approval`，
决策可以补填。实现上：待决请求可导出（`broker.pending()`），
重启后 `restore_pending()` 重新挂起。

---

## 五、沙箱

| 后端 | 机制 | 强度 |
|---|---|---|
| `none` | 直接 subprocess | 无（仅测试） |
| `restricted` | 子进程 + `ulimit` + 路径白名单 + 环境变量白名单 | 弱（默认降级档） |
| `namespaced` | namespace / bubblewrap / nsjail | 中 |
| `isolated` | 容器 / 微虚机 | 强（rc1） |

### 降级原则

检测不到强隔离后端时**不报错阻断**，但必须：

- `SandboxResult.degraded = True`
- 事件与审计里标注 `sandbox_degraded`
- 上层策略可以选择「降级即拒绝」

**绝不允许「以为自己在沙箱里」。** 这条是硬要求：
一个不知道自己没被隔离的沙箱，比没有沙箱更危险。

### 路径与网络

- **文件**：路径先 `resolve` 再判前缀，防 `../` 与符号链接逃逸
- **网络**：档位 + 域名 allowlist；出网请求经统一出口记录
- **进程**：子进程树清理收进沙箱内部，工具不再自己 `killpg`

### the write levels (the tool's own declaration decides)

A tool declares with `ToolSpec.sandbox` which boundary it needs, and the
shell tool turns that declaration into the path rules of its request:

| `spec.sandbox` | the path rules of the request |
|---|---|
| `readonly` | the working directory goes to `readonly_paths`, `cwd_writable=False` |
| `workspace` | the working directory goes to `writable_paths` |
| `none` / `isolated` | the working directory stays writable |

**Why the working directory is a writable root by default**: it is the
workspace of the turn, and a model writing into its own workspace is
normal work, not something to block.

**Why `cwd_writable` has to exist**: that convenience rule turns a
read-only project back into a writable one, so the write boundary would
be theatre. `PathPolicy.cwd_writable` and `SandboxRequest.cwd_writable`
are the switch that turns it off, and the read-only level turns it off.

**Where the declaration changes**: the tool's declaration changes, not
the backend's behaviour, because the policy, the approval and the audit
all read that one declaration. `ToolSpec` is a frozen dataclass, so a
new level means a new spec (`dataclasses.replace`), not a field write.

---

## 六、身份与凭据

```python
@dataclass(frozen=True)
class AgentIdentity:
    agent_id: str
    tenant: str
    scopes: tuple[str, ...]
    delegated_by: str | None = None
    delegation_chain: tuple[str, ...] = ()
    credential_refs: tuple[str, ...] = ()
```

- **委托授权**：子 Agent 的 scope 必须是父 scope 的子集；
  `delegation_chain` 记录完整授权路径，审计要能回答「这个权限最初从哪来」
- **凭据**：工具只拿到 `CredentialRef`，由运行时在注入时 resolve；
  日志、事件、trace 里一律替换为 `***`
- **越权即拒**：工具所需 scope 不在身份 scope 内 → 直接拒绝并记审计

### 脱敏只有一个出口

`harness.telemetry.exporter.redact()` 是**唯一**的脱敏实现，
`infra/observability/audit.py` 直接 re-export 它，并有测试断言两者是同一个函数
（`audit_redact is exporter_redact`）。

理由：脱敏逻辑散落在各处时，最先漏掉的一定是某个不起眼的分支。

**例外**：`credential_ref` 这类**引用**不脱敏。
以 `_ref` / `_id` / `_name` 结尾的键按「引用」处理 ——
把引用抹成 `***` 等于把审计里最关键的信息擦掉。
脱敏的目标是「不泄露秘密」，不是「不泄露任何信息」。

---

## 七、审计

```
audit.tool_call{identity, tool, version, args_digest, effect, sandbox, decision, duration, outcome}
audit.denied{reason: policy|scope|sandbox|approval}
audit.secret_access{credential_ref, tool}
audit.delegation{from, to, scopes}
```

- 审计与业务事件**同流**，但**独立存储**
- `AuditStore` 干脆**不提供** `delete` / `clear` / `truncate` / `pop`
  （测试断言这些属性不存在）；`AuditLog.clear()` 明确抛 `AuditImmutableError`
  而不是 AttributeError
- 唯一删除路径是 `purge_expired(retention_seconds>0)`（传 0 直接 ValueError）
- `args_digest` 只存参数的**哈希与长度**，不放明文

「不可删」不是洁癖：审计的价值全在「出事之后还能查」。

---

## 八、双轨期

```
旧路径：Agent → ToolRegistry → handler（直接 subprocess）
新路径：Agent → ToolRegistry → ToolGuard → PolicyEngine → Approval → Sandbox → handler
```

- 新路径默认开启审批与审计
- 旧路径（没有挂 guard）保留，但启动时打**一次**显著告警：
  「当前为 legacy 直连模式：无审批、无审计、无幂等保护」
- 环境变量 `AICF_SECURITY_MODE=strict|legacy` 控制默认模式，
  默认 `strict`（新安装）

### 默认路径现在挂的是新路径

`create_agent` 与 `aicf` 装出来的 Agent **默认带守卫**，
`ToolGuard` 也**默认挂一个沙箱后端**（`RestrictedSandbox`，
探测到强隔离后端时可以换成 `NamespacedSandbox`）。

这意味着：

- `proc.run` 在工作区沙箱里跑 —— 声明了 `sandbox="workspace"` 就要真的兑现；
- 没有沙箱后端时，工具会打显著告警而不是「假装自己在沙箱里」；
- 想退回旧行为：`AICF_SECURITY_MODE=legacy`，或把守卫摘掉
  （`registry.detach_guard()`）。

**legacy 直连路径在 1.0.0 正式版移除。** 每个版本公告会点名还在用 legacy 的地方。

---

## 九、常见问题

**Q：只读工具也要审批吗？**
不要。`effect=pure` 的工具风险为 low，自动放行。
声明 `spec` 就能享受这一点 —— 但**不声明也不会更不安全**（默认最严格）。

**Q：策略引擎挂了会怎样？**
按拒绝处理，工具不执行。宁可停下也不放行。

**Q：沙箱不可用会怎样？**
降级到 `restricted` 并标 `degraded=True`，事件里可见。
上层策略可以配成「降级即拒绝」。

**Q：为什么审批超时要单独记？**
「没人理」和「被拒绝」在事故复盘里含义完全不同：前者要改流程，
后者要改权限。混在一起就查不出该改哪个。

---

## 相关

- [roadmap_1.0.0-rc0.md](roadmap_1.0.0-rc0.md) —— 计划与验收清单
- [runtime.md](runtime.md) —— 幂等与恢复
- [evaluation.md](evaluation.md) —— 安全闸门如何阻断发布
- [architecture.md](architecture.md) —— 依赖规则
