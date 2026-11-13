# dsn_study 上下文内核（Context Kernel）

学习场景的长上下文**唯一装配入口**：把「学习状态 / 长期事实 / 会话摘要 / 最近对话」
四类动态内容，按**一个全局预算**裁剪成一段统一文本，拼进 system prompt。

本包只负责**动态层**（system prompt 的静态层仍由 `apps/dsn_study/prompts/` 管）。

实现契约见 `apps/dsn_study/REBUILD_SPEC.md` §2；设计动机见 `apps/dsn_study/REFACTOR_PLAN.md` §3。

---

## 1. 职责与边界

| 做 | 不做 |
|---|---|
| 采集各来源内容 → 裁剪 → 渲染成一段文本 | 不碰静态层 prompt、不碰人格、不调 LLM |
| 记录每次装配的痕迹（`ContextTrace`），失败一律留痕 | 不静默吞异常（旧实现 `_memory_preamble` 直接 `return ""`） |
| 原文轮次与派生事实的落库 | 不做轮次压缩（压缩器是另一件事，属 `context_facts` 的写入侧） |

依赖方向恒为 **`types ← budget ← kernel ← {sources, store}`**，
不得反向 import、不得成环：

```
types.py     纯数据（零依赖）
   ↑
budget.py    fit()：纯函数裁剪
   ↑
kernel.py    build() / render()：编排
   ↑
sources.py   四个来源实现        store.py   ContextStore（读写 context_turns / context_facts）
```

---

## 2. 接口

### 2.1 类型（`types.py`）

```python
ContextBlock(kind, source, text, priority=0, pinned=False, meta={})   # frozen
TurnContext(uid, session_id, message, round_index, is_asr=False, chat_id=0)
BlockTrace(kind, source, chars, status, reason="")                    # frozen，裁剪痕迹
ContextTrace(blocks, total_chars, budget_chars, degraded, collect_ms, kept=[])
```

* `kind`：`state` / `facts` / `summary` / `tail` / `tool_state`
* `source`：`plan` / `review` / `errorbook` / `memo` / `compactor` / `session`
* `ContextTrace.kept`：裁剪后幸存的块（**含正文**）。`BlockTrace` 按契约只带元信息，
  而 `render(trace)` 需要正文，所以正文另存一份 —— 这是对契约的**附加字段**，
  不破坏任何既有签名。

### 2.2 预算与裁剪（`budget.py`）

```python
ContextBudget(total_chars=6000, tail_chars=2000,
              state_chars=400, facts_chars=400, summary_chars=800)
FitResult(kept, dropped, truncated, total_chars, truncated_blocks=[])
fit(blocks, budget) -> FitResult        # 纯函数
```

各 kind 的软上限（`state_chars` / `facts_chars` / `summary_chars`）是
**该 kind 内所有块的合计**，不是每块各算一份：例如三个 state 子块
（今日计划 / 到期复习 / 错题本）合计不超过 `state_chars`，
超出时按 priority 从高到低整体丢弃并记原因。

裁剪规则（契约 §2.2 逐条落地）：

| # | 规则 | 实现要点 |
|---|---|---|
| 1 | `total_chars` 是**全局**硬上限，**含 tail** | tail 先占额度，其余块填剩余；`FitResult.total_chars` 恒为实际注入字符数 |
| 2 | **tail 保底** | tail 块永不丢；额度至少放得下**最后一条 user 消息**；极端情况（预算比一条消息还小）保底优先，允许溢出并留痕 |
| 3 | 其余块按 `priority` 从高到低填剩余额度 | 同优先级按输入顺序（稳定） |
| 4 | **截断保留尾部**（`text[-n:]`） | 只对 tail 段截断；**保留头部**是旧实现 F1 的根因 |
| 5 | **禁止静默丢中段** | 非 tail 块**要么整体保留、要么整体丢弃**；丢弃原因写进 `FitResult.dropped` |
| 6 | 截断标记长度**先预留** | 标记 `TRUNCATE_MARKER = "…（前文已省略）\n"` 放在前面，正文只留 `room - len(marker)` 字，产出恒 ≤ 额度 |
| 7 | **纯函数** | 只用 `dataclasses.replace` 生成新块，**不改入参**；同输入必同输出 |
| 8 | `pinned=True` 永远保留 | 整体保留、计入全局上限；额度不够时保底（允许溢出并留痕） |

> **保底 > 上限**：`tail` 与 `pinned` 是红线（R9 最近轮次无条件保留），
> 宁可让 `total_chars` 略微溢出，也不丢最近对话或用户钉住的块。
> 溢出在 `ContextTrace.total_chars` / `budget_chars` 上直接可见。

### 2.3 存储（`store.py`）

```python
ContextStore(db)                       # db 需有 _get_connection()
  .init_tables()                       # 幂等：CREATE TABLE IF NOT EXISTS + PRAGMA table_info 补列
  .record_turn(turn, user_msg, assistant_reply) -> int     # INSERT OR REPLACE，幂等
  .recent_turns(uid, session_id, limit) -> list[dict]       # 按 round_index **升序**
  .count_turns(uid, session_id) -> int
  .add_fact(uid, scope, kind, text, *, source="", ref_id="", importance=0.5) -> int
  .facts(uid, scope, kind, limit=20) -> list[dict]
```

* `scope`：`user` / `session`；`kind`：`memo` / `summary` / `profile`
* `ref_id` 非空时 `add_fact` **先查后插**（另有 `(uid, ref_id)` 唯一索引兜底）→ 幂等
* 旧库（表已存在但缺列）由 `_ensure_columns()` 按 `PRAGMA table_info` 补齐

### 2.4 来源（`sources.py`）

```python
class ContextSource(Protocol):
    name: str
    def collect(self, turn: TurnContext) -> list[ContextBlock]: ...
```

| 来源 | 内容 | 依赖（**构造注入**） | 产出 kind/source/priority |
|---|---|---|---|
| `StudyStateSource` | 今日计划 / 到期复习 / 错题本 | `plan_engine` / `graph_store` / `question_store` | `state` / `plan`·`review`·`errorbook` / 80 |
| `MemoSource` | 长期备忘 | `ContextStore` | `facts` / `memo` / 60 |
| `SummarySource` | 会话摘要 | `ContextStore` | `summary` / `compactor` / 50 |
| `TailSource` | 最近 N 轮原文 | `ContextStore` | `tail` / `session` / 100 |

**容错**：`StudyStateSource` 的三个子块**各自** try/except，任一 store 异常只丢那一块；
每个 source 整体再由 kernel 兜一层，失败记进 `trace.degraded`，其它来源照常。

### 2.5 内核（`kernel.py`）

```python
ContextKernel(store, sources, budget=None, trace_sink=None)
  .build(turn) -> ContextTrace        # 采集 → 裁剪 → 留痕（可落库）
ContextKernel.render(trace) -> str    # 静态方法，纯函数
```

渲染格式（唯一口径，常量集中在 `types.py`）：

```text
[系统上下文 · 供你参考，不要复述]
- [学习状态] …
- [长期事实] …
- [会话摘要] …
[最近对话]
用户：…
助手：…
```

* `kind == 'tail'` 的块**不加** `- [标签]` 前缀（原样保留对话形态）
* 空文本的块不出现；没有任何内容时 `render()` 返回空串
* **每个块一行**（同一 kind 的多个块各占一行，来源可追溯 —— 例如学习状态的三块
  会渲染成三行 `- [学习状态] …`）

---

## 3. 怎么用

```python
from apps.dsn_study.context import (
    ContextKernel, ContextStore, ContextBudget,
    StudyStateSource, MemoSource, SummarySource, TailSource,
)

store = ContextStore(db)          # db：QuestionBankDBManager 之类的（有 _get_connection()）

kernel = ContextKernel(
    store,
    sources=[
        StudyStateSource(plan_engine=app.plan_engine,
                         graph_store=app.graph_store,
                         question_store=app.question_store),
        MemoSource(store, limit=10),
        SummarySource(store, limit=5),
        TailSource(store, rounds=3),
    ],
    budget=ContextBudget(total_chars=6000, tail_chars=2000),
    trace_sink=lambda trace: logger.info("ctx trace: %s", trace.summary()),
)

trace = kernel.build(turn)                       # turn: TurnContext
system_text = ContextKernel.render(trace)        # 拼进 system prompt（一条 system 消息）

# 本轮结束后落库（幂等，可重放）
store.record_turn(turn, turn.message, assistant_reply)
```

写派生事实（摘要 / 备忘）：

```python
store.add_fact(uid, scope="user", kind="memo", text="用户偏好先给思路再给答案",
               source="user", ref_id="memo:pref:think-first")
```

---

## 4. 与契约的差异（实现取舍）

契约 `REBUILD_SPEC.md` §2 是硬要求，本包**逐条落地**；下面几处是**附加**或**细化**，
不破坏任何既有签名：

| # | 差异 | 原因 |
|---|---|---|
| 1 | `ContextTrace` 增加字段 `kept: list[ContextBlock] = []` | 契约的 `BlockTrace` 只带元信息（无正文），而 `render(trace)` 需要正文才能渲染；正文另存一份，`blocks` 仍是契约原样的元信息列表 |
| 2 | `FitResult` 增加字段 `truncated_blocks: list[ContextBlock] = []` | 让 kernel 能精确标记"哪个 kept 块是被截断的"，避免靠 kind/source/chars 猜（会重复计数） |
| 3 | 截断**只发生在 tail 块** | 契约规则 5 明文要求非 tail 块"整体保留或整体丢弃"，不做截断 |
| 4 | tail 截断点对齐**轮次边界** | 契约规则 4 只说"保留尾部"；对齐轮次边界可避免留下半句话（比 `text[-n:]` 更可用） |
| 5 | tail 保底三级兜底 | 放得下一轮 → 留完整轮次；放不下 → 只留**最后一条 user 消息**；再放不下 → 留原始尾部若干字 |
| 6 | **保底 > 上限**：`pinned` 块与 tail 的最后一条 user 消息可能让 `total_chars` 略微溢出 | 红线 R9（最近轮次无条件保留）比全局上限更硬；溢出在 `trace.total_chars` / `budget_chars` 上直接可见 |
| 7 | `recent_turns()` 按 `round_index` **升序**返回 | 契约未规定顺序；对话形态需要"先旧后新" |
| 8 | `collect_ms` 单位是**毫秒** | 字段名带 `ms` |
| 9 | `ContextStore.__init__` 会调用一次 `init_tables()` | 建表幂等，构造完即可用；`init_tables()` 仍公开且可重复调用 |

---

## 5. 单测

```bash
python3 -m pytest tests/test_dsn_study_context_kernel.py -q -p no:cacheprovider
```

覆盖：8 条裁剪规则各至少一条、来源失败降级、渲染格式、存储幂等与建表幂等。
