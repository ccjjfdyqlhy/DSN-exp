# dsn_study 长上下文 + 人格系统 · 重建契约

> 本文件是**实现契约**，不是愿望清单。两个新包（`context/` 与 `persona/`）
> 都按这里写的接口实现，接线由集成方负责。
>
> 底座已在 2026-11-11 修好并由 `apps/harness_lab` 验证（60/60 通过）：
> 蒸馏预算与静默失败、状态落库、证据重启失忆、`plan()` 副作用、
> 兜底串串味、缓存不分用户 —— 全部已修。

---

## 0. 红线（碰了就是回归）

| # | 红线 | 守它的测试 |
|---|---|---|
| R1 | 学习上下文必须进 system prompt，且走 `ctx.extra["learning_context"]` **显式通道**（不能只靠 contextvars —— 管线在自己线程里跑） | `test_dsn_study_context_fix.py::test_system_prompt_plugin_renders_learning_context` |
| R2 | `build(uid=...)` 不得清空本轮上下文 | `test_dsn_study_context_fix.py::test_build_with_uid_keeps_turn_context` |
| R3 | `{personality}` / `{user_context}` / `{skills}` 三个占位符必须全部被渲染，不得裸露 | `test_dsn_study_prompts.py::test_prompt_has_no_unrendered_placeholders` |
| R4 | system prompt 逐轮重建；禁用技能后指令文本立即消失 | `test_dsn_study_prompts.py::test_disabled_skill_prompt_disappears` |
| R5 | 人格段落必须在 prompt 里，内容来自 study 自己的角色卡 | `test_dsn_study_personality.py::test_personality_prompt_in_system_prompt` |
| R6 | 人格系统故障不得让整轮对话失败 | `test_dsn_study_personality.py::test_personality_failure_degrades_gracefully` |
| R7 | 人格闭环必须真跑：一轮对话后 `total_interactions` 增加、`affinity_value` 变化 | `test_dsn_study_personality.py::test_interaction_updates_affinity` |
| R8 | 人格回写必须**后台异步**、不阻塞回复；语音轮不做人格判定 | 延迟实测 |
| R9 | 最近 N 轮原文必须**无条件**保留（任何预算下都在） | `test_context_retention.py::test_recent_message_survives_any_budget` |
| R10 | 所有 system 内容合并成**一条** `ChatMessage.system(...)` | `test_dsn_study_topics.py::test_single_system_message_rule` |
| R13 | 语音轮必须同样带学习上下文；短回复上限默认关 | `test_dsn_study_context_fix.py::test_voice_mode_also_renders_learning_context` |
| R14 | `AgentRuntime.run_with_tools` 必须支持 per-call `system_prompt` | `test_dsn_study_prompts.py::test_agent_runtime_accepts_per_call_system_prompt` |
| R15 | `/api/personality/*` 五个路由必须挂载，契约码 200/400/503/500 不变 | `test_dsn_study_personality.py::test_personality_api_routes_mounted` |
| R17 | `memory_v2` / `chat_rounds` / `memory_embeds` 字段与语义不得变（旧库在线） | `test_dsn_study_memory.py` |
| R18 | `MemorySystem` 必须满足 `MemoryStorePort` | `test_dsn_study_topics.py::test_memory_system_satisfies_port` |
| R26 | `boot.create_application` 源码里必须同时出现 `"character_cards"` 和 `"PERSONALITY_DEFAULT_CARD"` | `test_dsn_study_personality.py::test_study_cards_dir_is_not_dsns` |
| R28 | `StudyEngine` 必须保留私有方法 `_learning_context` | `test_dsn_study_context_fix.py::test_engine_exposes_learning_context_helper` |
| R29 | 禁止裸 import 顶层包 | `test_dsn_study_functional_parity.py::test_no_broken_top_level_imports` |

---

## 1. Feature Gate（由集成方实现，两个包都要用它）

`apps/dsn_study/gating.py`：

```python
def flag(name: str, default: str = "") -> str: ...      # 运行时求值
def enabled(name: str, default: bool = False) -> bool: ...
def snapshot() -> dict[str, str]: ...
```

优先级：环境变量 `DSN_FLAG_<NAME>` > `.dsn/feature_flags.json` > 默认值。
求值失败一律回退默认值并记一条 warning。**不是 import 期快照**。

开关键：

| 键 | 默认 | 含义 |
|---|---|---|
| `context_engine` | `v2` | `v2` = 新 Context Kernel；`v1` = 旧路径（接线方保留） |
| `persona_engine` | `v2` | `v2` = 新 Persona Kernel；`v1` = 旧 PEV3 直连 |
| `persona_llm_judge` | `false` | 是否用 LLM 判定事件（默认关：热路径不排队） |

---

## 2. Context Kernel —— `apps/dsn_study/context/`

依赖方向恒为 `types ← budget ← kernel ← {sources, store}`，**不得反向 import**。

### 2.1 `types.py`（零依赖）

```python
@dataclass(frozen=True)
class ContextBlock:
    kind: str          # 'state' | 'facts' | 'summary' | 'tail' | 'tool_state'
    source: str        # 'plan' | 'review' | 'errorbook' | 'memo' | 'compactor' | 'session'
    text: str
    priority: int = 0  # 越大越先保留
    pinned: bool = False
    meta: dict = field(default_factory=dict)

@dataclass(frozen=True)
class TurnContext:
    uid: int
    session_id: str
    message: str
    round_index: int
    is_asr: bool = False
    chat_id: int = 0

@dataclass(frozen=True)
class BlockTrace:
    kind: str; source: str; chars: int
    status: str          # 'kept' | 'dropped' | 'truncated'
    reason: str = ""

@dataclass
class ContextTrace:
    blocks: list[BlockTrace]
    total_chars: int
    budget_chars: int
    degraded: list[str]      # 缺席/失败的来源
    collect_ms: float
    def summary(self) -> dict: ...
```

### 2.2 `budget.py`（纯函数，必须可独立测试）

```python
@dataclass(frozen=True)
class ContextBudget:
    total_chars: int = 6000      # 全局硬上限，**含 tail**
    tail_chars: int = 2000
    state_chars: int = 400
    facts_chars: int = 400
    summary_chars: int = 800

@dataclass
class FitResult:
    kept: list[ContextBlock]
    dropped: list[BlockTrace]
    truncated: list[BlockTrace]
    total_chars: int

def fit(blocks: list[ContextBlock], budget: ContextBudget) -> FitResult: ...
```

**规则（逐条都要有单测）**：

1. `total_chars` 是**全局**上限，所有块合计 ≤ 它。
2. **tail 保底**：先给 `kind == 'tail'` 分配 `tail_chars`，且 tail 的内容
   （尤其是最后一条 user 消息）**必须完整保留**；预算再小也不能丢。
3. 其余块按 `priority` 从高到低填剩余额度。
4. **截断保留尾部**（`text[-n:]`），不保留头部。
5. **禁止静默丢中段**：非 tail 的块要么**整体保留**、要么**整体丢弃**，
   丢弃时在 `FitResult.dropped` 里记原因。**不做"保留头 + 丢掉中间"的截断。**
6. 截断标记（若使用）长度**先预留**，实际产出恒 ≤ 上限。
7. **纯函数**：不改传入的 block（用 `dataclasses.replace`），同一输入必得同一输出。
8. `pinned=True` 的块永远保留（仍计入上限）。

### 2.3 `store.py`

```python
class ContextStore:
    def __init__(self, db): ...          # db 需有 _get_connection()
    def init_tables(self) -> None: ...
    def record_turn(self, turn: TurnContext, user_msg: str, assistant_reply: str) -> int
    def recent_turns(self, uid: int, session_id: str, limit: int) -> list[dict]
    def add_fact(self, uid: int, scope: str, kind: str, text: str, *,
                 source: str = "", ref_id: str = "", importance: float = 0.5) -> int
    def facts(self, uid: int, scope: str, kind: str, limit: int = 20) -> list[dict]
    def count_turns(self, uid: int, session_id: str) -> int
```

**表结构（必须用 `MigrationRunner` 或幂等 `CREATE TABLE IF NOT EXISTS`；旧库要能补列）**：

```sql
CREATE TABLE IF NOT EXISTS context_turns (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  uid           INTEGER NOT NULL,
  session_id    TEXT    NOT NULL,
  round_index   INTEGER NOT NULL,
  user_msg      TEXT    NOT NULL,
  assistant_reply TEXT  NOT NULL,
  created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
  UNIQUE(uid, session_id, round_index)
);
CREATE INDEX IF NOT EXISTS idx_ctx_turns_session
  ON context_turns(uid, session_id, round_index);

CREATE TABLE IF NOT EXISTS context_facts (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  uid          INTEGER NOT NULL,
  scope        TEXT NOT NULL,     -- 'user' | 'session'
  kind         TEXT NOT NULL,     -- 'memo' | 'summary' | 'profile'
  text         TEXT NOT NULL,
  importance   REAL NOT NULL DEFAULT 0.5,
  source       TEXT NOT NULL DEFAULT '',
  ref_id       TEXT NOT NULL DEFAULT '',
  created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ctx_facts_lookup
  ON context_facts(uid, scope, kind, importance DESC, created_at DESC);
```

**写入必须幂等**：`record_turn` 用 `INSERT OR REPLACE`（靠唯一键）；
`add_fact` 在 `ref_id` 非空时用 `INSERT OR IGNORE`（靠 `uid, ref_id` 唯一索引，
若不便建唯一索引则在 Python 层先查后插）。

### 2.4 `sources.py`

```python
class ContextSource(Protocol):
    name: str
    def collect(self, turn: TurnContext) -> list[ContextBlock]: ...
```

必须实现的四个来源（**各自独立失败，失败只记 degraded，不影响其它**）：

| 来源 | 内容 | 依赖 | 产出 kind / priority |
|---|---|---|---|
| `StudyStateSource` | 今日计划 / 到期复习 / 错题本 | `plan_engine` / `graph_store` / `question_store`（**由构造参数注入**，不要自己 import） | `state` / 80 |
| `MemoSource` | 长期备忘 | `ContextStore` | `facts` / 60 |
| `SummarySource` | 会话摘要 | `ContextStore` | `summary` / 50 |
| `TailSource` | 最近 N 轮原文 | `ContextStore` | `tail` / 100（保底） |

**`StudyStateSource` 的三个子块必须分别 try/except**：任一 store 异常只丢那一块，
其余照常（现状是整个 `_build_preamble` 一起挂）。

### 2.5 `kernel.py`

```python
class ContextKernel:
    def __init__(self, store: ContextStore, sources: list[ContextSource],
                 budget: ContextBudget | None = None,
                 trace_sink: Callable[[ContextTrace], None] | None = None): ...
    def build(self, turn: TurnContext) -> ContextTrace: ...
    @staticmethod
    def render(trace: ContextTrace) -> str: ...
```

- `build`：依次调用各 source（**每个 source 包 try/except**，失败记进
  `trace.degraded`）→ 汇总成 blocks → `fit()` → 产出 `ContextTrace`。
- `render`：**统一格式**，禁止各处硬编码前缀：

```
[系统上下文 · 供你参考，不要复述]
- [学习状态] …
- [长期事实] …
- [会话摘要] …
[最近对话]
用户：…
助手：…
```

  块之间用换行；`kind == 'tail'` 的块不加 `- [标签]` 前缀（原样保留对话形态）。
  空文本的块不出现。

---

## 3. Persona Kernel —— `apps/dsn_study/persona/`

**底座是已经修好的 `harness/personality`（PEV3）** —— 不再重写人格引擎，
本包只负责：dsn_study 侧的**卡片管理**、**信号抽取**、**提示词呈现**、
**API 契约**。

### 3.1 `cards/`

- 目录 `apps/dsn_study/persona/cards/`，**必须进版本控制**（现状 `character_cards/`
  被 `.gitignore` 忽略，"小舟"这张卡只存在于某一台机器上 —— 这是要修的）。
- 卡片文件名 `<card_id>.yaml`，格式沿用 `harness/personality/character_card.py`
  的 `CharacterCard`（不要自造格式）。
- 至少提供 `study_tutor.yaml`（内容沿用现状那张「小舟」卡，自然语言逐字保留）。

### 3.2 `signals.py` —— 规则信号（默认路径，零 LLM）

```python
@dataclass(frozen=True)
class Signal:
    event_type: str      # 必须是 harness.personality.events.EVENT_TYPES 里的枚举
    intensity: str       # 'low' | 'medium' | 'high'
    valence: str         # 'positive' | 'neutral' | 'negative'
    reason: str = ""

def extract_signals(user_msg: str, reply: str = "", *,
                    answer_correct: bool | None = None,
                    answer_wrong: bool | None = None) -> list[Signal]: ...
```

规则（保守，宁可判 neutral 也不要乱判）：

| 条件 | event_type | intensity | valence |
|---|---|---|---|
| `answer_correct is True` | `praise` | medium | positive |
| `answer_wrong is True` | `complaint` | medium | negative |
| 用户文本含「谢谢/厉害/牛/学到了/懂了」 | `thanks` | medium | positive |
| 用户文本含「搞错/不对/错了/没懂/听不懂」 | `complaint` | medium | negative |
| 用户文本含「烦/累/不想学/放弃/压力」 | `venting` | medium | negative |
| 用户文本含「生气/你有病/别管我/滚」 | `conflict` | high | negative |
| 其它 | `neutral` | low | neutral |

- 一次调用**最多返回 1 条**信号（避免一轮灌多条证据）。
- 命中多条时按 `conflict > venting > complaint > thanks > praise` 的优先级取一条。
- 关键词匹配用**子串包含**，大小写与全半角不敏感；不要引入正则依赖。

### 3.3 `engine.py`

```python
class PersonaEngine:
    def __init__(self, pv3: PersonalitySystemV3, *,
                 use_llm_judge: bool = False,
                 trace_sink: Callable[[dict], None] | None = None): ...

    def prompt_block(self, uid: int) -> str:
        """给 system prompt 的人格段落。**任何异常都必须降级成 '' 或
        一段安全文本，绝不能抛出去**（红线 R6）。"""

    def feedback(self, uid: int, user_msg: str, reply: str, *,
                 answer_correct: bool | None = None,
                 answer_wrong: bool | None = None) -> None:
        """回写人格状态。**绝不阻塞调用方**（由调用方放到后台线程）。
        默认走规则信号；use_llm_judge=True 时才走 PEV3 的 LLM 判定。"""

    def status(self, uid: int) -> dict: ...
    def cards(self) -> list[dict]: ...
    def switch(self, uid: int, card_id: str) -> bool: ...
```

- `feedback` 内部：规则信号 → 构造 `harness.personality.events.PerceptionRecord`
  → 调用**新增的** `pv3.apply_event(uid, perception, conversation_history="")`
  （见 §4）→ 由 PEV3 完成动力学 / 证据 / 审计 / 落库。
- `use_llm_judge=True` 时改调 `pv3.analyze_interaction(...)`。
- `status` 返回：`{uid, card_id, affinity, affinity_level, total_interactions,
  mood, traits(deviated dims), evidence_total, last_updated}`。

### 3.4 提示词呈现

- 人格段落**只呈现有意义的东西**：档案正文 + 当前关系阶段 + 偏离基线的特质
  （偏离 < 0.05 的维度不展示）。
- **不要**把 50 维原始向量、情绪向量、亲密度 15 级标签塞进 prompt。
- 段落长度上限 **800 字**（超出截断）。
- 不得出现其它应用的人格身份（现状兜底串写死成「你是 EXA」—— 已修，但本包
  也不能自己引入同类问题）。

---

## 4. harness 侧新增（集成方实现，两个包都依赖它）

`harness/personality/__init__.py` 的 `PersonalitySystemV3` 增加**公开**方法：

```python
def apply_event(self, uid: int, perception: PerceptionRecord,
                conversation_history: str = "") -> MoodUpdateResult | None:
    """把一条**已经确定好的**语义事件推进为状态变化（不含 LLM 判定）。

    与 analyze_interaction 的区别：省掉 judge.classify 这一步 ——
    判定由调用方给（dsn_study 默认用规则信号）。
    后续的动力学 / 证据累积 / 审计 / 落库逻辑完全一致。
    """
```

实现方式：把 `analyze_interaction` 里「judge 分类」之后的所有步骤抽成一个
内部方法 `_apply_perception(...)`，`analyze_interaction` 与 `apply_event` 都调它。

---

## 5. 验收

- 两个包各自有单测：`context/` 的 budget 与 kernel 是纯函数测试；
  `persona/` 的 signals 是表驱动测试。
- 红线 R1~R18、R26、R28、R29 全部保持通过。
- `python -m pytest tests/ -q` 不新增失败。
- 新代码不引入任何第三方依赖。
- 禁止裸 import 顶层包（`from apps.dsn_study.config import ...` 不行，
  必须 `from apps.dsn_study import config`）。
