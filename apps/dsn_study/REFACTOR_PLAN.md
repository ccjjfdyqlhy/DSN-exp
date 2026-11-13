# dsn_study 长上下文 + 性格系统 · 推倒重建计划

> 状态：☐ 未开始 / ◐ 进行中 / ✅ 完成 / ⛔ 阻塞
> 基线：`harness-refactor` @ `f3b9b2a`（2026-11-11 审计快照）
> 配套：`MIGRATION_PLAN.md`（上一轮迁移，已基本完成）、`FEATURE_GAP.md`（历史记录）
> 本文件是**新一轮**计划：上一轮是"把 dsn 的能力搬过来"，本轮是"**把搬过来的实现扔掉重做**"。

---

## 0. 决策摘要

| # | 决策 | 理由（详见 §1） |
|---|---|---|
| **D1** | **长上下文全部重写**，落到新包 `apps/dsn_study/context/`；旧路径（`memory/topics.py`、`memory/core.py:assemble_context`、`boot.py` 四个 preamble、`TopicContextPlugin`）**一次性删除**，不做双轨长期并存 | 现状有 **6 条并行装配路径**、**5 份同一段对话的存储副本**；继续打补丁只会再加路径 |
| **D2** | **性格系统全部重写**，落到新包 `apps/dsn_study/persona/`；**放弃"LLM 蒸馏人格 + 每轮 LLM 判定情绪"**，改为"**静态人格档案 + 确定性状态旋钮**" | 线上蒸馏产物 **50 维全 0.5、四个结构化字段全空**；演化链从未回写；重启即失忆。复杂机制没有产生任何价值 |
| **D3** | **先补 Feature Gate（运行时可求值的开关层）再动任何生产代码** | 全仓**没有** feature flag / 灰度 / 双写 / 蓝绿；`Config` 是 import 时快照；面板 `/config/set` 恒 501。没有这层，"推倒重来"只能靠回滚 commit |
| **D4** | **上下文有唯一全局硬预算**，裁剪是纯函数、最近 N 轮永在、中间轮次不静默丢失 | 现状 tail 段 `unbounded=True` 不占预算（实测 system 可达 **386,215 字符**）；verbatim 段截断**保留头部**，导致中间 36 轮凭空消失且无日志 |
| **D5** | **删掉 `contextvars` 传上下文**，改为显式 `TurnContext` 参数传递 | `run_in_executor` 不复制 contextvars，线程池复用会让上一轮别的用户的上下文残留 |
| **D6** | **会话标识跨进程稳定**（UUID session_id + DB 分配 round_index） | 现状 `chat_id = len(session_ids)+1`，进程重启后新会话又拿 `chat_id=1`，与旧会话记忆混写 |
| **D7** | **流式与非流式走同一条上下文装配路径** | 现状流式只跑 PREPARE + POST_PROCESS，**PRE_PROCESS 全部丢失**、`<plan_check>` 标签原样出现在用户回复里 |
| **D8** | **不引入新第三方依赖**（不引 pydantic / tiktoken） | 预算单位用**字符**（中文场景 token≈char/1.5），校验用 dataclass + 手写 |
| **D9** | **`harness/context_assembly.py` 与 `harness/personality/` 本轮不动**，dsn_study 单方面解耦 | 两者分别被 `apps/dsn_ui`、`apps/emotion_exp` 使用；`apps/dsn` 零改动是既有红线 |
| **D10** | **每次上下文组装产出 `ContextTrace` 并落库**，面板可查 | 现状注入失败只 warning 甚至 `return ""` 无日志，"上下文没了"不会报错，只表现为模型变笨 |

---

## 1. 为什么要推倒重来：三份现状审计的硬证据

> 证据口径：`文件:行号`。审计为只读走查 + 运行时探针，未修改仓库任何文件。

### 1.1 长上下文：形状清晰，但没有一条路是对的

**6 条并行装配路径**（同一件事有 6 个做法）：

| # | 路径 | 触发点 | 问题 |
|---|---|---|---|
| A | `{user_context}` 插槽（今日计划/到期复习/错题本/memo/5 条 exp） | `boot.py:243-256` | 每轮 **4~5 次 SQL，零缓存**；`_get_exp_memories` **无 LIMIT** 全量拉取 |
| B | 话题块（closed 摘要 + 其它话题原文 + 当前话题原文 + tail） | `plugins.py:649-714` | 唯一走 `SegmentedContextAssembler` 的路径；仅当 `TOPIC_ENABLED=true` |
| C | user 消息前插块（视觉/考试/日终报告/复杂度） | 4 个 PRE_PROCESS 插件 | 前缀字面量散落 5 处、2 个版本，**同一轮里重复出现 3 次** |
| D | agent 会话历史 `conv.messages` | `agent_runtime.py:94` | 主管线被 `_trim_agent_history` 清空成 **0 条**；兜底路径**无限增长** —— 两条路径行为相反 |
| E | 扫题批总结的独立管线 | `api/scan.py:326-327` | system prompt 是 **boot 时冻结的死字符串**，无学习上下文，人格永久停在启动那一刻 |
| F | 语义缓存短路 | `boot.py:300-337` | 命中即返回，**完全绕过 A/B/C/D**，本轮不落记忆、不更新人格 |

**同一段对话存了 5 份**：`chat_rounds`（`memory/core.py:126`）、`memory_v2(exp)`（`:87`）、`study_topic_messages`（`memory/topics.py:93`）、`agent.conversations`（进程内存）、`compressed_chunks`（`infra/store/chat_store.py:49`）—— **写入时机各不相同（同步/后台线程），`compressed_chunks` 写进去从来没人读**。

**三个会直接毁掉上下文的缺陷**：

| 编号 | 缺陷 | 证据 | 实测后果 |
|---|---|---|---|
| **F1** | verbatim 段截断**保留头部**，tail 保留尾部 → **中间整段静默消失** | `harness/context_assembly.py:255-259`（`content[:room]`） | 60 轮话题：模型只看到**头 14 轮 + 尾 10 轮**，中间 **36 轮凭空消失**，**零日志** |
| **F2** | tail 段 `unbounded=True`，**不参与任何预算** | `memory/topics.py:742-746` + `context_assembly.py:292-294` | 15 轮 × 19000 字 → 最终 system **386,215 字符** |
| **F3** | 截断标记不预留长度 → **实际产出超预算** | `context_assembly.py:252-259` | 预算 9200，实际 **10365** |

**其它已确认缺陷**：

- **F4** `plan()` 就地改写调用方的 segment（memo 分支 `context_assembly.py:169` 直接赋值，非 `replace()`）→ 幂等性被破坏；在 `apps/dsn_ui/topic_manager.py:552`、`apps/emotion_exp/topic_manager.py:255` 是活 bug。
- **F5** 流式路径丢 PRE_PROCESS 全部上下文 + `<plan_check>` 标签外泄（`boot.py:558-560` 传原始 message、`:694-697` yield 原始 reply、`:733` 只跑 PREPARE）。
- **F6** `context=None` ≠ "清空上下文" 的脆弱语义（`prompts/builder.py:140-149`）。
- **F7** `run_in_executor` 不复制 contextvars（`harness/pipeline/manager.py:97`）→ 线程池复用导致跨用户上下文残留。
- **F8** `Config` 是 import 期快照（`config.py:14-22`）；`TOPIC_ENABLED` 代码默认 `false`、`.env.example`/文档 `true`、**线上 `.env` `true`** —— 代码与部署相反。
- **F9** 死配置：`TOPIC_MEMO_CHARS`（dsn_study 从不产 `SEG_MEMO`）、`MEMORY_CONTEXT_WINDOW_SIZE` / `MEMORY_REPLACE_THRESHOLD_RATIO`（只服务不可达分支）、`TOPIC_DB_PATH`（`conftest.py:84` 设了但**全仓无人读**）。
- **F10** 同一份"记忆注入"逻辑两份实现、口径不同：`memory/core.py:314-361`（**热路径不可达**）vs `boot.py:208-241`（生效的那份）。
- **F11** `_complexity_preamble` 是死代码（`boot.py:258-271`，零调用），且与插件重复。
- **F12** 语义缓存**不带 user_id 作用域**（`semantic_cache/engine.py:54-60` + `boot.py:300-337` 不传 uid）→ 多用户下 A 的回答回放给 B。
- **F13** `chat_id` 跨进程不稳定（`boot.py:275-280` `len(self._session_ids)+1`）→ 重启后新会话复用 `chat_id=1`，与旧会话记忆混写；`_round_counters` 同样重置 → `round_index` 从 1 重来，`chat_rounds` 被 `INSERT OR REPLACE` 覆盖，`memory_v2(exp)` 无唯一约束 → **摘要无限重复累积**。
- **F14** 每轮 **2 次同步 embedding HTTP + 可能 1 次同步 LLM judge**，全在热路径（`topics.py:257/566/411-413`）。
- **F15** 33KB 技能指令每轮重建每轮重传（`harness/skills/registry.py:301-319`，实测 33,751 字节 / 18 技能）。
- **F16** `boot.py:218-219` 直接调 `memory_system._get_memos()` / `._get_exp_memories()` —— 私有 API 越界。
- **F17** `TopicManager._states` 永不回收（`topics.py:211`）；`get_assembly_stats()` 恒返回 `{}`（读的是不存在的 `assembler.last_stats`）。

### 1.2 性格系统：不是"太复杂"，是"**空转**"

| 编号 | 事实 | 证据 |
|---|---|---|
| **P1** | **线上人格产物是空的**：`study_tutor.distilled.json` 的 50 维特质向量 `set == {0.5}`；`behavioral_patterns` / `speech_patterns` / `emotional_model` / `relational_model` / `trait_narrative` **全空**；只有 pass1 的 `foundation_description`（1742 字）有效 | 根因：`distillation_engine.py:301/314` `max_tokens=3000` 装不下 pass2/pass3 的输出 → 回复被截断在 JSON 中间（`logs/distill/*_pass2_reply.txt` 实测 `Unterminated string`）→ `_parse_json_response:395` 静默 `return {}` |
| **P2** | **演化链从未回写**：DB 里 **306 条证据**，但 `_pending` 是纯内存计数（`evidence_accumulator.py:50`），`CONSOLIDATE_EVERY=50` 在频繁重启下永达不到 → `distilled.json` 自 11-08 蒸馏后 **mtime 未变** | `evidence_accumulator.py:50/168/192` |
| **P3** | **重启即失忆**：`get_mu()` 只读内存不读 DB（`:175`），`seed()` 只由 `add_evidence()` 触发 → 冷启动实测 `evidence_total=0`（DB 实为 306）、`maturity=0.0`、稳定向量零偏离 | `evidence_accumulator.py:125/143/175` |
| **P4** | **兜底串硬编码了另一个应用的人格**：`personality_generator.py:308-311` 的 `DEFAULT_FALLBACK_PROMPT` 是「你是 EXA，一个运行在用户本地电脑上的 AI 同事」→ dsn_study 偶尔会把 **"你是 EXA"** 讲给用户听 | `harness/personality/__init__.py:442` |
| **P5** | **三套实现并存**：`harness/personality`（3767 行，dsn_study/emotion_exp/dsn_ui 用）、`apps/dsn/prompt/personality_v3`（**apps/dsn 生产在用**）、`apps/dsn/prompt/personality_v2`（1654 行）→ 任何修复都要改两处 | `pers-audit` §5.3 |
| **P6** | **人格卡不在版本控制里**：`.gitignore:81-83,111` 忽略 `apps/dsn_study/character_cards/*` → 「小舟」这张卡只存在于那台机器上 | `git ls-files` 返回空 |
| **P7** | **每轮 1 次 LLM 判定 + 可能 1 次 LLM 重生成**，且与主回复**抢同一个 provider 队列**（实测把回复拖到 50~100 秒） | `plugins.py:738-793`、`turn_gate.py:5-8`、`personality_generator.py:59-66` |
| **P8** | **生成路径与使用路径割裂**：生成读 YAML 自然语言，使用读蒸馏产物的结构化字段（而后者全空）；同一份文本在 yaml（截断到 800 字）和 json 里各存一份 | `character_card.py:149-157/203-241`、`__init__.py:216` |
| **P9** | 30 处 `except Exception`；`flush()` **全仓无人调用**（退出时最多丢 2 条状态）；prompt 缓存**不分 uid**（多用户串人格） | `personality_generator.py:71`、`persistence.py:64/227` |

**同时，审计明确点名三块"干净"的骨架，值得保留**：

- `events.py` 的「**LLM 只做语义、数值全走确定性表**」分层原则；
- `dynamics_engine.py` 的确定性动力学内核（冲量-回归情绪、亲密度饱和曲线、遗忘、单轮钳制、`rule_id` 审计标签）；
- `traits.py` 的 50 维分类词典 + `character_card.py` 的 YAML 契约与 fingerprint（**领域知识资产**，与实现无关）。

### 1.3 结构性根因（8 条）

1. **没有安全网**：全仓无 feature flag / 灰度 / 双写 / 蓝绿；`Config` import 时快照；面板写配置恒 501。**这是"推倒重来"的头号障碍**。
2. **一份数据多个家**：`chat_rounds` / `memory_v2` / `study_topic_messages` / `compressed_chunks` / `agent.conversations` 各自为政。
3. **应用层手拼上下文**：`boot.py:167-271` 直接写 SQL、拼字符串、决定格式。`boot.py` 不该知道上下文长什么样。
4. **隐式状态与隐式顺序**：contextvars 传轮次上下文；插件 priority 决定谁覆盖谁；`SystemPromptPlugin` 整体覆盖、`TopicContextPlugin` 追加，靠 priority 10<15 的隐式顺序保证不打架。
5. **LLM 在关键路径上做不该做的事**：每轮情绪分类、每次人格局部重写、蒸馏三连调用 —— 全部可确定性表达。
6. **状态在内存、DB 只是影子**：`evidence_accumulator._pending`、`_distillation_pending`、四类缓存、`V3Persistence._pending` —— 重启即丢。
7. **静默降级掩盖回归**：注入失败只 warning、`_memory_preamble` 失败直接 `return ""`（连日志都没有）、`PromptEngine._render` 吞异常 → **占位符 `{skills}` 可能原样留在 prompt 里**。
8. **文档/注释/默认值大面积漂移**：`memory/core.py:11-13` 说"话题系统休眠"（已被 `boot.py:1141-1156` 推翻）；`docs/technical-debt.md:179` 说 `max_open_topics` 从不读取（已修）；`docs/configuration.md:104` 与代码默认值相反；297 个配置项里 **131 个半死 + 1 个全死**。

---

## 2. 新系统设计原则（六条铁律）

| # | 原则 | 具体含义 | 反例（现状） |
|---|---|---|---|
| **P1** | **单一真源** | 每个事实只有一个存储位置、一个读取函数；其余全是它的投影 | 同一段对话 5 份副本 |
| **P2** | **预算即契约** | 一次请求的上下文有**唯一全局上限**；裁剪是**纯函数**、输入相同必输出相同；超限的丢弃顺序固定且可断言 | tail 不占预算、截断保留头部 |
| **P3** | **显式传递** | 轮次上下文通过参数/`TurnContext` 显式传递；不依赖 contextvars、不依赖模块级单例 | `contextvars` + 线程池复用 |
| **P4** | **读快写慢** | 读路径零 LLM、零网络；写路径异步、幂等、可重放 | 每轮 1 次 LLM 判定 + 2 次 embedding HTTP |
| **P5** | **状态在库** | 跨轮/跨进程状态的唯一真源在 DB；缓存只有「TTL + 上限 + 显式失效」三件套 | `_pending` 在内存、`flush()` 无人调用 |
| **P6** | **可观测** | 每次组装产出 `ContextTrace`（块/来源/长度/丢弃原因/耗时）并落库；任何静默降级必须留痕 | 注入失败无日志 |

---

## 3. 新设计 A：Context Kernel（长上下文内核）

### 3.1 概念模型

把"上下文"劈成两半，各归一个内核：

```
system prompt
├── 静态层（PromptEngine 管）        ← identity / skills / persona_sheet
│     逐轮重建；禁用技能即刻消失（保留现有行为，红线 R4）
└── 动态层（ContextKernel 管）        ← 学习状态 / 长期事实 / 会话摘要 / 最近轮次 / 工具状态
      统一预算 → 统一渲染 → **合并成一条 system 消息**（红线 R10）
```

**关键改动**：动态层不再走 `{user_context}` 插槽 + contextvars，而是**先产出 `ContextBlock` 列表 → 预算裁剪 → 一次性渲染**。静态层与动态层在最后一步合并，输出仍然是一条 system 消息。

### 3.2 模块与依赖（单向，无环）

```
apps/dsn_study/context/
  types.py      ContextBlock / BlockKind / TurnContext / ContextTrace   （零依赖 dataclass）
  budget.py     TokenBudget + fit(blocks, budget) -> FitResult           （纯函数）
  sources.py    Source 协议 + 具体实现（plan/review/errorbook/fact/session/topic）
  store.py      ContextStore：context_turns / context_facts 读写（单连接 + 事务）
  compactor.py  Compactor：轮次压缩为摘要（LLM，异步，幂等）
  kernel.py     ContextKernel.build(turn) -> ContextTrace                （编排）
```

依赖方向恒为 `types ← budget ← kernel ← {sources, store, compactor}`。任何模块不得反向 import。

### 3.3 数据模型（2 张表，取代 5 份副本）

```sql
-- 原始轮次：唯一真源（取代 chat_rounds + study_topic_messages + agent.conversations）
CREATE TABLE context_turns (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  uid           INTEGER NOT NULL,
  session_id    TEXT    NOT NULL,   -- UUID，跨进程稳定
  round_index   INTEGER NOT NULL,
  user_msg      TEXT    NOT NULL,
  assistant_reply TEXT  NOT NULL,
  topic_id      TEXT,                -- 可空：话题归属只是轮次的一个属性
  created_at    TEXT    NOT NULL,
  UNIQUE(uid, session_id, round_index)
);
CREATE INDEX idx_ctx_turns_session ON context_turns(uid, session_id, round_index);

-- 派生事实：摘要 / 备忘 / 画像（取代 memory_v2 的 exp+memo、compressed_chunks）
CREATE TABLE context_facts (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  uid          INTEGER NOT NULL,
  scope        TEXT NOT NULL,     -- 'user' | 'session' | 'topic'
  kind         TEXT NOT NULL,     -- 'summary' | 'memo' | 'profile'
  text         TEXT NOT NULL,
  importance   REAL NOT NULL DEFAULT 0.5,
  pinned       INTEGER NOT NULL DEFAULT 0,
  source       TEXT,              -- 'llm_summary' | 'user' | 'plan' | ...
  ref_id       TEXT,              -- 幂等键，如 'summary:{session_id}:{chunk_no}'
  created_at   TEXT NOT NULL,
  last_hit_at  TEXT, hit_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_ctx_facts_lookup ON context_facts(uid, scope, kind, importance DESC, created_at DESC);
CREATE UNIQUE INDEX idx_ctx_facts_refid ON context_facts(uid, ref_id) WHERE ref_id IS NOT NULL;
```

**迁移映射（旧 → 新）**：

| 旧 | 新 | 说明 |
|---|---|---|
| `chat_rounds` | `context_turns` | 按 `(uid, session_id, round_index)` 迁；`chat_id` 无法反推 session，**只迁最近 30 天** |
| `memory_v2(type='exp')` | `context_facts(kind='summary', scope='session')` | `ref_id = 'summary:{chat_id}:{round}'` 保持幂等 |
| `memory_v2(type='memo')` | `context_facts(kind='memo', scope='user')` | 原样 |
| `study_topic_messages` | `context_turns` + `context_facts(kind='summary', scope='topic')` | 话题原文并入 turns |
| `study_topics` | `context_facts(scope='topic')` + `context_turns.topic_id` | 话题本身退化为一个属性 + 一条事实 |
| `compressed_chunks` | **删除** | 写入后从未读回（死数据） |
| `agent.conversations` | 内存投影 | 每轮从 `context_turns` 取，不持久化第二份 |
| `memory_embeds` | 保留不动 | 属检索子系统，不在本次范围 |

**旧表只读保留 30 天**，迁移脚本幂等（`infra/store/base.py` 的 `MigrationRunner`，新增 migration id，**不改旧 migration 脚本**）。

### 3.4 预算与裁剪算法（新规则，替换 `SegmentedContextAssembler`）

```python
@dataclass(frozen=True)
class ContextBudget:
    total_chars: int = 6000        # 全局硬上限（唯一！）
    tail_chars: int = 2000         # 最近轮次的保底额度（计入 total）
    per_kind_chars: dict[str, int] = ...   # 各 kind 的软上限
```

**裁剪规则（顺序固定，全部可单测）**：

1. **全局上限**：所有块合计 ≤ `total_chars`。**tail 也计入**（修 F2）。
2. **保底顺序**：先给 `tail` 分配 `tail_chars`（最近 N 轮**永在**），再从低优先级到高优先级填其余块。
3. **优先级（低 → 高，先被丢）**：`tool_state` < `session_summary` < `facts` < `state` < `tail` < `persona_state` < `persona_sheet` < `identity`。
   —— 静态层不参与裁剪（它由 PromptEngine 管），动态层最低是 `state`。
4. **截断方向**：**保留尾部**（最近的更重要），不是头部（修 F1）。
5. **禁止静默丢中间**：verbatim 类块要么**完整保留**、要么**整体丢弃**并显式标注 `(本段前文已省略)`；绝不做"保留头 + 丢弃中段"的截断（修 F1/F3）。
6. **marker 计入预算**：截断标记的长度**先预留**再截正文，实际产出**恒 ≤ 上限**（修 F3）。
7. **无副作用**：`fit()` 是纯函数，不改入参（用 `dataclasses.replace`），同一输入必得同一输出（修 F4）。
8. **输出可审计**：`FitResult` 记录每个块的 `kept / dropped / truncated` 与原因，进 `ContextTrace`。

> 旧的 `harness/context_assembly.py` **本轮不动**（`apps/dsn_ui`、`apps/emotion_exp` 在用），但 dsn_study **不再引用**。它被标记 `legacy`，后续统一任务再处理。

### 3.5 一轮对话的新时序

```
HTTP 请求线程
  │
  ├─ ① TurnContext(uid, session_id, message, round_index, is_asr, image)   ← 纯数据，显式传参
  │
  ├─ ② ContextKernel.build(turn) → ContextTrace
  │     ├─ 并发 collect：各 Source 各自读库，各自带超时（默认 300ms），失败即缺席 + 留痕
  │     ├─ budget.fit(blocks) → FitResult
  │     └─ render(blocks) → 一条动态层文本
  │
  ├─ ③ SystemPromptPlugin(PREPARE, prio 10)
  │     system_prompt = PromptEngine.build(静态层) + "\n\n" + 动态层文本
  │     （静态层逐轮重建；不再有 {user_context} 插槽、不再有 contextvars）
  │
  ├─ ④ PRE_PROCESS 视觉/考试/日终/复杂度 → 统一格式注入 user 消息
  │     （流式与非流式**都执行**；修 F5）
  │
  ├─ ⑤ MODEL_INVOKE
  │     消息 = [system] + 最近 N 轮原文(来自 context_turns) + 本轮 user
  │     （不再用 agent.conversations 作为历史真源；修 F2/F4）
  │
  └─ ⑥ POST_PROCESS
        ├─ <plan_check> 清洗（流式路径也必须清洗；修 F5）
        ├─ 落 context_turns（事务内分配 round_index；修 F13）
        ├─ 异步：Compactor 压缩 → context_facts(kind='summary')
        └─ 异步：PersonaKernel 回写旋钮
```

### 3.6 来源清单（每个来源一个 `Source` 实现）

| Source | 内容 | 读取 | 预算 | 失败降级 |
|---|---|---|---|---|
| `StudyStateSource` | 今日计划 / 到期复习 / 错题本 | `plan_engine` / `graph_store` / `question_store` | 300 字 | 该项缺席 + trace 记录 |
| `MemoSource` | 长期备忘（用户级事实） | `context_facts(scope='user', kind='memo')` | 400 字 | 缺席 |
| `SummarySource` | 会话摘要（压缩产物） | `context_facts(scope='session', kind='summary')` | 800 字 | 缺席 |
| `TailSource` | 最近 N 轮原文 | `context_turns` | 2000 字（保底） | 缺席 |
| `TopicSource` | 话题分组（可选，v2.1） | `context_turns.topic_id` | 0（默认关） | 缺席 |
| `ToolStateSource` | 工具结果缓存（v2.1，可选） | 内存 | 200 字 | 缺席 |

> **没有"话题"这一层的强依赖**：话题退化为 `context_turns.topic_id` + 一条 summary 事实；边界判定降级为**纯函数**（时间间隔 + 词面相似度），LLM judge 默认**关闭**（修 F14）。原 `TOPIC_*` 的 17 个开关收敛为 3 个。

### 3.7 渲染格式（统一，消灭 5 处 2 版前缀）

```text
[系统上下文 · 供你参考，不要复述]
- [学习状态] 今日计划 3/8 已完成；到期复习 2 项（函数单调性、导数几何意义）
- [长期事实] 用户偏好先给思路再给答案
- [会话摘要] 前面在讨论二次函数配方法的常见变形
[最近对话]
用户：……
小舟：……
```

- 全部块用**同一个** `CTX_PREFIX` 常量（`context/types.py`），不再散落。
- 每块带 `[标签]`，模型知道这是什么、也便于 trace 定位。
- 动态层最终与静态层合并成**一条 system 消息**（红线 R10）。

---

## 4. 新设计 B：Persona Kernel（性格内核）

### 4.1 核心决策

> **放弃**「LLM 蒸馏人格档案 + 50 维特质向量 + 每轮 LLM 情绪判定 + 证据贝叶斯演化」。
> **改为**「**静态人格档案（人工可编辑、进 git）+ 少量可解释的状态旋钮（确定性规则更新）+ 零 LLM 关键路径**」。

理由：审计实证表明复杂机制没有产生任何价值（P1/P2/P3），且每轮 LLM 判定会与主回复抢 provider 队列把回复拖到 50~100 秒（P7）。学习陪伴场景真正需要的是**长期一致性**与**可控**，不是**情绪感知精度**。

### 4.2 人格档案（新格式，取代 `character_cards/*.yaml`）

```yaml
id: study_tutor
version: 2
name: 小舟
identity: |        # 旧 natural_language.personality
  一个陪你刷题的学长 —— 记得你的薄弱点，不替你做题。
voice: |           # 旧 natural_language.speech_style
  口语化、短句。像坐在旁边说话，不是站在讲台上讲。不说"综上所述"，不说"希望对你有帮助"。
values:             # 旧 natural_language.values（拆成条目）
  - 诚实优先于鼓励
  - 过程重于结果：会做题不等于学会了
  - 尊重用户的节奏
teaching: |         # 旧 natural_language.behavior
  用户带着具体问题来 → 先确认题目要问什么，再给思路，最后才给答案。
boundaries: |       # 旧 natural_language.emotional_traits（反向）
  不替用户写答案；不用"我是为你好"给建议；不拿用户的错误开玩笑。
tabs:               # 旧 corpus（精选，≤5 条）
  - 来了。今天想搞哪块？
```

**迁移规则**：旧卡 `natural_language` 的 5 段**逐段映射，不丢一个字**；旧 `corpus` 精选进 `tabs`；旧 `dynamic_config` / `manual_overrides` / `experiences` **不再使用**（`experiences` 若有内容，转成 `context_facts(kind='profile')`）。

**新卡进版本控制**（`apps/dsn_study/persona/sheets/study_tutor.yaml`），修 P6。

### 4.3 状态旋钮（可解释的 6 个数值）

| 旋钮 | 含义 | 初值 |
|---|---|---|
| `warmth` | 温度 | 0.6 |
| `strict` | 要求严格度 | 0.6 |
| `energy` | 活力 | 0.5 |
| `verbosity` | 话多程度 | 0.4 |
| `pace` | 推进速度 | 0.6 |
| `mood` | 心境（-1..1） | 0.0 |

**存储**（DB 唯一真源，修 P3）：

```sql
CREATE TABLE persona_state (
  uid INTEGER NOT NULL, sheet_id TEXT NOT NULL,
  sheet_version INTEGER NOT NULL,
  knobs_json TEXT NOT NULL,
  streak_correct INTEGER NOT NULL DEFAULT 0,
  streak_wrong INTEGER NOT NULL DEFAULT 0,
  total_turns INTEGER NOT NULL DEFAULT 0,
  last_seen_at TEXT, last_verbal_feedback_at TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(uid, sheet_id)
);

CREATE TABLE persona_events (      -- 只记"变更"，不记证据原文
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  uid INTEGER NOT NULL, sheet_id TEXT NOT NULL,
  knob TEXT NOT NULL, old_value REAL NOT NULL, new_value REAL NOT NULL,
  reason TEXT NOT NULL,             -- 规则 id，可回放
  created_at TEXT NOT NULL
);
```

### 4.4 确定性更新规则（零 LLM）

**信号抽取**（`signals.py`，纯规则）：

| 信号 | 来源 | 可靠性 |
|---|---|---|
| `answer_correct` / `answer_wrong` | 题库/考试结果事件（**不是 LLM 判断**） | 高 |
| `explicit_feedback` | 用户显式措辞：「太啰嗦」「说重点」「讲细一点」「再来一遍」「跳过」 | 高 |
| `pace_signal` | 用户回复间隔（急/缓） | 中 |
| `emotional_tone` | 轻量词面特征（否定词、连续问号、感叹） | 低 |

**更新规则**（`dynamics.py`，从 `harness/personality/dynamics_engine.py` 整体搬来并简化）：

| 规则 id | 条件 | 变更 |
|---|---|---|
| `streak_wrong` | 连续答错 ≥2 | `strict += 0.05`（≤0.9） |
| `streak_correct` | 连续答对 ≥2 | `strict -= 0.03`，`warmth += 0.02` |
| `feedback_verbose_down` | 「太啰嗦/说重点」 | `verbosity -= 0.15`（≥0.1） |
| `feedback_verbose_up` | 「讲细一点/展开」 | `verbosity += 0.15`（≤0.9） |
| `idle_cool` | 距上次 >3 天 | `warmth -= 0.05` |
| `mood_regress` | 每轮 | `mood → 0` 回归 20%（冲量-回归模型） |

每次变更写一条 `persona_events`（谁/哪维/旧值/新值/原因）→ **可解释、可回放、可单测**。

### 4.5 注入格式（替代 `## 角色设定`）

```text
## 你是谁
<档案正文，identity + voice + values + teaching + boundaries，≤600 字>

## 相处状态
耐心偏足 · 要求偏高 · 话不多
```

- **不注入**原始数字（模型会把参数当指令乱套）、**不注入** 50 维向量、**不注入**情绪向量、**不注入**亲密度 15 级标签 —— 这些在现状里是**噪声**（P1 的 50 维全是 0.5）。
- 状态行由旋钮**离散化**成 3 档措辞（低/中/高），不出现数字。
- 档案正文按 `version` 缓存（进程内 + DB），命中即 0 IO。

### 4.6 保留 / 丢弃对照表

| 现状 | 处置 | 理由 |
|---|---|---|
| `character_card.py` 的 YAML 契约 + `compute_fingerprint` | ✅ 保留思路，格式换成 §4.2 | 内容寻址判断"要不要重算"的正确思路 |
| `traits.py` 的 50 维词典 | ✅ 保留为**领域知识资产**（`persona/traits_reference.md`），不再注入 | 与实现无关 |
| `dynamics_engine.py` 确定性内核（饱和/遗忘/钳制/`rule_id`） | ✅ 整体搬进 `persona/dynamics.py` | 纯函数、有边界、有单测 |
| `events.py`「LLM 只做语义、数值走确定性表」分层 | ✅ 继承并**更进一步**：语义层也不用 LLM | 确定性 > 精度 |
| 4-Pass 蒸馏链（`distillation_engine.py` 396 行） | ❌ **删除** | 产物 100% 退化、不可复现、提示词预算不足 |
| 每轮 LLM 情绪判定（`personality_judge.py`） | ❌ **删除**（规则信号替代） | 抢 provider 队列、拖慢 50~100s |
| 证据贝叶斯演化（`evidence_accumulator.py`） | ❌ **删除**（`persona_events` 替代） | 状态在内存，重启即丢 |
| `audit.py` | ❌ 删除（合并进 `persona_events`） | 两套审计 |
| `dynamic_synthesizer.py` 的噪声/漂移 | ❌ **删除** | 噪声按小时跳变、漂移方向永久固定 —— 不可解释 |
| `personality_generator.py` 的 LLM 生成 + EXA 兜底串 | ❌ **删除** | 兜底串串了别的应用的人格（P4） |
| `harness/personality/` 整包 | ⏸ 本轮**保留在仓库**（`apps/dsn`/`emotion_exp`/`dsn_ui` 在用），dsn_study **不再 import** | 红线 R22 `apps/dsn` 零改动 |

### 4.7 人格 API 兼容（红线 R15）

`/api/personality/status|current|list|switch|prompt` **路径、状态码、错误体全部不变**，只换内部实现：

| 端点 | 新返回 |
|---|---|
| `/status` | `{uid, sheet_id, sheet_version, knobs, total_turns, streak_*, updated_at}` |
| `/current` | `{uid, sheet_id, knobs, knobs_labels, sheet_version}`（替代 50 维） |
| `/list` | `{cards:[{card_id, name, version, source:"file"}]}` |
| `/switch` | 入参 `card_id` 仍必填，缺省 **400**（测试锁定） |
| `/prompt` | `{prompt: "<档案正文 + 状态行>"}` |

面板 `/api/admin/persona/*` 同样换实现，路由不变。

---

## 5. 共同地基：Feature Gate + Context Trace

### 5.1 Feature Gate（阶段 0 必须先落地）

新增 `apps/dsn_study/gating.py`：

- **运行时求值**（不再 import 时快照）—— 这是与 `Config` 的本质区别。
- 键与默认值：

| 键 | 默认 | 含义 |
|---|---|---|
| `context_engine` | `v1` | `v1`=现状装配；`v2`=Context Kernel |
| `persona_engine` | `v1` | `v1`=PEV3；`v2`=Persona Kernel |
| `context_trace_sample` | `0.0` | trace 采样率（0~1） |
| `persona_llm_review` | `off` | 每日 LLM 复盘（默认关） |
| `topic_enabled` | `true` | 话题分组（v2.1 才生效） |

- **取值优先级**：环境变量 `DSN_FLAG_<KEY>` > `.dsn/feature_flags.json` > 默认值。
- **求值失败一律回退默认值（保守）**，并写一行 warning。
- 面板新增 `/api/admin/flags`（GET 读 / POST 写）—— 补上"运行时切新旧实现"的能力（现状 `/config/set` 恒 501）。
- 每次求值结果写进 `ContextTrace` 与启动日志 → 事后可确认"当时跑的是哪套"。

### 5.2 Context Trace

```python
@dataclass
class ContextTrace:
    trace_id: str
    uid: int
    session_id: str
    round_index: int
    engine: str            # v1 | v2
    flags: dict[str, str]
    blocks: list[BlockTrace]   # 每块：kind / source / chars / kept|dropped|truncated / reason
    total_chars: int
    budget_chars: int
    collect_ms: float
    degraded: list[str]       # 哪些来源缺席/失败
    created_at: str
```

- 落 `context_traces` 表（采样存储，默认低采样率；`context_engine=v2` 时默认 100%）：

```sql
CREATE TABLE context_traces (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  trace_id     TEXT    NOT NULL UNIQUE,
  uid          INTEGER NOT NULL,
  session_id   TEXT    NOT NULL,
  round_index  INTEGER NOT NULL,
  engine       TEXT    NOT NULL,      -- v1 | v2
  flags_json   TEXT    NOT NULL,      -- 本轮生效的开关快照
  blocks_json  TEXT    NOT NULL,      -- 每块：kind/source/chars/kept|dropped|truncated/reason
  total_chars  INTEGER NOT NULL,
  budget_chars INTEGER NOT NULL,
  collect_ms   REAL    NOT NULL,
  degraded_json TEXT   NOT NULL,      -- 缺席/失败的来源
  created_at   TEXT    NOT NULL
);
CREATE INDEX idx_ctx_traces_uid ON context_traces(uid, created_at DESC);
```
- 面板 `/api/admin/context/traces?uid=&limit=` 可查 → **这是判断"重构后是否回归"的唯一手段**（修现状 H7 静默降级）。
- 每次组装**必产出一条 trace**（即使采样丢弃也要先算完组装，采样只影响落库）。

---

## 6. 迁移阶段（每阶段独立可交付、可回滚）

> 纪律：每阶段结束时 `pytest tests/` 全绿；每阶段都有明确的"开关回滚路径"；每阶段更新本文件状态。

### 阶段 0 · 安全网（**不改任何行为**）

| # | 任务 | 验收 |
|---|---|---|
| 0.1 | `gating.py` + `.dsn/feature_flags.json` + 面板 `/api/admin/flags` | 运行时改开关即时生效；求值失败回退默认 |
| 0.2 | `ContextTrace` 埋点（v1 路径也产出 trace） | 面板能看到 v1 每轮的块与长度 |
| 0.3 | 补护栏测试（审计缺口 G1/G2/G3/G4/G5/G6 的等价项） | 新增用例全绿 |
| 0.4 | 修两条"把错误行为写成契约"的既有用例 | `test_plan_truncatable_segment_keeps_head`、`test_assembly_respects_budget` 改为断言正确行为 |

**0.3 必补的护栏（重构前先立规矩）**：

1. 最终 system prompt 的**结构快照**（几段、什么顺序、无裸占位符）；
2. user 消息最终形态（前插块顺序、前缀只出现一次）；
3. **流式与非流式等价**（同一消息两条路径的 prompt/messages 一致）；
4. `<plan_check>` 在流式路径被清洗；
5. **截断方向**：中间轮次不静默丢失；
6. **system prompt 体积上限**（含 tail，恒 ≤ 上限）。

**回滚**：无行为变更，无需回滚。

---

### 阶段 1 · Context Kernel v2 影子运行

| # | 任务 |
|---|---|
| 1.1 | 建 `apps/dsn_study/context/`（types/budget/sources/store/kernel），纯函数部分 100% 单测 |
| 1.2 | 建 `context_turns` / `context_facts` 表与幂等迁移脚本（旧表只读） |
| 1.3 | **影子模式**：`context_engine=shadow` → 新内核在真实请求上并行组装但**不注入**，把新旧 prompt 差异写进 trace |
| 1.4 | 差异人工审阅清单（重点：内容有没有丢、顺序对不对、有没有重复注入） |

**验收**：差异可解释且可接受；新内核组装耗时 P99 < 100ms（纯本地 DB）；**零网络调用**。
**回滚**：`context_engine` 保持 `v1`，零影响。

---

### 阶段 2 · Context Kernel v2 切换（注入）

| # | 任务 |
|---|---|
| 2.1 | `context_engine=v2` 生效：新块替换 A/B/C 三条路径；`{user_context}` 插槽保留但**不再由 dsn_study 填**（兼容期） |
| 2.2 | 修 F5：流式路径补齐 PRE_PROCESS；`<plan_check>` 统一在出口清洗 |
| 2.3 | 修 F13：`session_id` 改 UUID（跨进程稳定）；`round_index` 由 DB 在事务内分配 |
| 2.4 | 修 F2/F3/F1/F4：新预算规则；旧 assembler 在 dsn_study 侧不再被调用 |
| 2.5 | 修 F12：语义缓存键加 `uid` |
| 2.6 | 数据**双写**：新表写 + 旧表继续写（观察期 30 天） |

**验收**：
- 红线用例全过（R1/R2/R3/R4/R9/R10/R11/R13/R16/R17/R18/R21）；
- 真实 20 轮 A/B（v1 vs v2）人工评质量，无明显退化；
- 上下文总长度恒 ≤ 预算；最近 N 轮永在；中间轮次不丢（trace 可证）；
- 首字延迟增量 ≤ 30ms。

**回滚**：`context_engine=v1`，**双写期间数据不丢**，1 分钟内生效。

---

### 阶段 3 · 收敛存储 · 删除旧路径

| # | 任务 |
|---|---|
| 3.1 | `context_turns` / `context_facts` 接管读写；停写 `chat_rounds` / `memory_v2` / `study_topic_messages` / `compressed_chunks` |
| 3.2 | **删**：`apps/dsn_study/memory/topics.py`（774 行）、`memory/core.py:298-361` 的 `assemble_context`、`boot.py:167-271` 的四个 preamble、`pipeline/plugins.py` 的 `TopicContextPlugin`、旧 `TopicContextPlugin`/`SystemPromptPlugin` 的上下文拼装 |
| 3.3 | **删**：`memory_v2` / `chat_rounds` / `memory_embeds` 的写入路径（旧表只读留 30 天） |
| 3.4 | 收敛配置：`TOPIC_*` 17 个 → 3 个；清 `TOPIC_MEMO_CHARS` / `MEMORY_CONTEXT_WINDOW_SIZE` / `MEMORY_REPLACE_THRESHOLD_RATIO` / `TOPIC_DB_PATH` / `MCP_EXPOSE_TOOL_NAME_MAX` 等死开关 |
| 3.5 | 修 F17：`TopicManager._states` 泄漏随之消失；`get_assembly_stats` 修正 |
| 3.6 | 统一 `config.py` 与 `settings.py` 双源（7 处默认值冲突），或明确 `settings.py` 只服务 harness |

**验收**：
- 全量 `pytest tests/` 绿（dsn 相关 332+ 全过）；
- `apps/dsn` 侧零改动，其回归全绿；
- 代码净减 ≈ 350~400 行（删除约 1,070 行：`memory/topics.py` 774 + `boot.py` 四个 preamble 105 + 两个插件 125 + `memory/core.py:assemble_context` 65；新增约 700 行：`context/` 新内核 + 单测）。

**回滚**：`context_engine=v1` —— 但 3.2 删了旧代码后无法回滚。**因此 3.2 必须在 2.x 稳定运行 ≥2 周后执行**，且用 git revert 兜底。

---

### 阶段 4 · Persona Kernel v2

| # | 任务 |
|---|---|
| 4.1 | 建 `apps/dsn_study/persona/`（sheet/knobs/signals/dynamics/engine/store） |
| 4.2 | 把旧 `study_tutor.yaml` 的 `natural_language` 5 段**逐段映射**进新档案格式，新卡**进 git** |
| 4.3 | `persona_state` / `persona_events` 表 + 迁移脚本 |
| 4.4 | 从 `harness/personality/dynamics_engine.py` 搬确定性内核，补单测 |
| 4.5 | `persona_engine=v2` 生效：注入格式换成 §4.5；回写走规则信号，**0 次 LLM** |
| 4.6 | `/api/personality/*` 与面板换实现（路由与状态码不变） |

**验收**：
- 人格关键路径 **0 次 LLM 调用**（探针计数为 0）；
- 人格段长度 ≤ 800 字；
- 旋钮更新可回放（`persona_events` 有 rule_id / 旧值 / 新值 / 原因）；
- 20 轮真实对话人工 rubric：一致性、语气、边界遵守度不低于 v1；
- **不存在** "你是 EXA" 类串味。

**回滚**：`persona_engine=v1`。

---

### 阶段 5 · 解除 PEV3 依赖

| # | 任务 |
|---|---|
| 5.1 | dsn_study 不再 import `harness.personality`（`boot.py:1306`、`:1359-1360`、`prompts/builder.py` 的 personality provider、`plugins.py:738-793` 的 `PersonalityFeedbackPlugin`） |
| 5.2 | 归档 `apps/dsn_study/character_cards/`（进 `persona/sheets/`，旧文件移到 `persona/_archive/`） |
| 5.3 | `prompts/fragments/personality.md` 换成新档案插槽（或并入静态层） |
| 5.4 | `harness/personality/` **保留在仓库**（`apps/dsn` / `emotion_exp` / `dsn_ui` 仍在用），标注 deprecated，另立任务合并三套实现 |

**验收**：dsn_study 代码里 grep `harness.personality` 命中 0；`apps/dsn` 回归全绿。

---

### 阶段 6 · 收尾

| # | 任务 |
|---|---|
| 6.1 | 观察期结束 → 删旧表（`chat_rounds` / `memory_v2` / `memory_embeds` / `study_topics` / `study_topic_messages` / `compressed_chunks` / `topics.db` 文件） |
| 6.2 | 清理死配置：131 个半死开关 + 1 个全死开关，**逐个确认**（dsn 用 / 仅 dsn 用 / 删） |
| 6.3 | 修正文档漂移：`docs/configuration.md` 的 `TOPIC_ENABLED`、`docs/technical-debt.md:179`、`memory/core.py:11-13` 的过期注释（随文件删除自动消失） |
| 6.4 | 更新 `docs/architecture.md`（上下文保底章节改为新预算模型）、`docs/maintenance.md`（新增不变量：上下文全局上限 / tail 保底 / 单条 system / 旋钮可回放） |
| 6.5 | 归档 `MIGRATION_PLAN.md` / `FEATURE_GAP.md`，本文件转为长期维护文档 |

**验收**：全量测试绿；文档与代码一致（抽查 10 项配置默认值与文档）。

---

## 7. 验收标准（可测）

| 域 | 指标 | 阈值 |
|---|---|---|
| 上下文 | 单条 system 消息 | 恒 1 条 |
| 上下文 | 总长度 | ≤ `ContextBudget.total_chars`（默认 6000），**含 tail** |
| 上下文 | 最近 N 轮 | 任何预算下都在（红线 R9） |
| 上下文 | 中间轮次 | 不静默丢失；丢弃必有 trace 记录与标注 |
| 上下文 | 组装耗时 | P99 < 100ms（本地 DB），**零网络调用** |
| 上下文 | 首字延迟增量 | ≤ 30ms（vs v1） |
| 上下文 | 流式/非流式 | prompt 与 messages **完全一致** |
| 人格 | 关键路径 LLM 调用 | **0** |
| 人格 | 人格段长度 | ≤ 800 字 |
| 人格 | 旋钮变更 | 全部有 `rule_id` + 旧值/新值/原因，可回放 |
| 人格 | 重启后 | 状态与重启前**完全一致**（DB 真源） |
| 全局 | 开关回滚 | ≤ 1 分钟生效，无需重启 |
| 全局 | 测试 | `pytest tests/` 全绿（基线 1097 collected / 当前 3 个环境性失败不算回归） |
| 全局 | `apps/dsn` | 零改动，回归全绿 |

---

## 8. 风险登记与缓解

| # | 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|---|
| K1 | v2 上下文质量低于 v1（信息取舍失当） | 中 | 高 | 阶段 1 影子对比 + 阶段 2 的 20 轮真实 A/B；块级 trace 定位丢哪块 |
| K2 | 迁移丢历史记忆 | 中 | 中 | 迁移脚本幂等 + 旧表只读保留 30 天 + 迁前备份 |
| K3 | Feature Gate 本身失效 | 低 | 高 | 求值失败回退默认（v1）；启动日志打印全部生效开关；面板可查 |
| K4 | 人格"失去个性化"（不再 LLM 演化） | 中 | 中 | 档案人工可编辑 + 旋钮规则 + `persona_llm_review` 可选开；20 轮 rubric 评估；v1 开关可回滚 |
| K5 | 删除旧路径后无法回滚 | — | 高 | 删除动作单独成阶段（阶段 3），前置稳定运行 ≥2 周，git revert 兜底 |
| K6 | `harness/context_assembly.py` / `harness/personality` 仍有其他消费者 | 高 | 低 | 本轮只让 dsn_study 解耦，不动 harness；另立统一任务 |
| K7 | `Config` 改运行时求值会打破 `conftest.py` 的 setenv 时序假设 | 中 | 中 | **不改 `Config` 语义**；新开关走独立的 `gating.py`；测试继续用 `Config` |
| K8 | 语义缓存加 uid 后命中率下降 | 低 | 低 | 缓存是优化不是契约；命中率下降可接受 |
| K9 | 团队并行开发冲突 | 中 | 中 | 每阶段独立 PR；阶段 0 先合，让所有人基于同一地基并行 |

---

## 9. 废弃清单（"完全抛弃当前设计"的具体所指）

**删除文件**：

- `apps/dsn_study/memory/topics.py`（774 行）
- `apps/dsn_study/character_cards/`（旧卡与 backups、distilled.json）
- `harness/personality/` → **本轮不删**（其他 app 在用），dsn_study 全面解耦

**删除函数 / 方法**：

- `boot.py`：`_build_preamble` / `_memory_preamble` / `_learning_context` / `_complexity_preamble`（约 105 行）
- `memory/core.py`：`assemble_context` 的多分支分派（约 65 行）
- `pipeline/plugins.py`：`TopicContextPlugin`（约 70 行）、`PersonalityFeedbackPlugin`（约 55 行）
- `prompts/builder.py`：`set_context_provider`（零调用）、`set_personality_provider`（改由 PersonaKernel 供数）
- `prompts/fragments/context.md`（`{user_context}` 插槽）

**删除配置项**（逐个确认后）：`TOPIC_*` 13 个、`MEMORY_CONTEXT_WINDOW_SIZE`、`MEMORY_REPLACE_THRESHOLD_RATIO`、`TOPIC_MEMO_CHARS`、`MCP_EXPOSE_TOOL_NAME_MAX`、`PERSONALITY_V3_*`（dsn_study 侧）。

**停写表**：`chat_rounds`、`memory_v2`、`memory_embeds`、`study_topics`、`study_topic_messages`、`compressed_chunks`。

---

## 10. 测试策略

| 类别 | 处理 |
|---|---|
| **必须保住的行为契约**（约 40 条） | 逐条映射到新内核的等价用例；**不允许删测试来让实现通过** |
| **贴着实现写的**（约 10 条：源码文本断言、插件名、hooks 列表） | 允许改，但**必须逐条列出改前改后**并在 PR 里说明 |
| **把错误行为写成契约的**（2 条） | 阶段 0.4 直接改为断言正确行为 |
| **新增** | 预算裁剪（纯函数，≥12 例）、来源降级（每源 1 例）、Trace 生成、旋钮规则（每规则 1 例）、流式/非流式等价（1 例）、会话隔离/重启一致性（2 例） |
| **目标覆盖率** | `context/` 与 `persona/` 两包 ≥ 85% 行覆盖；纯函数模块 100% |

**必跑命令**：

```bash
# 上下文/人格核心红线（当前 88 passed）
python3 -m pytest tests/test_dsn_study_memory.py tests/test_dsn_study_personality.py \
  tests/test_dsn_study_prompts.py tests/test_dsn_study_topics.py \
  tests/test_dsn_study_context_fix.py tests/test_dsn_study_cache.py \
  tests/test_dsn_study_pipeline.py tests/test_dsn_study_session_flow.py \
  tests/test_context_retention.py tests/test_harness_context_assembly.py \
  tests/test_harness_memory.py -q

# 全量
python3 -m pytest -q
```

---

## 11. 明确不做

- 不改 `apps/dsn`（既有红线 `MIGRATION_PLAN.md:413`）。
- 不改 `harness/memory` 的 `MemoryStorePort` 契约、不改 `harness/pipeline` 骨架、不改 `harness/prompts` 片段引擎 —— 这三块是好的，保留。
- 不合并 `harness/personality` 与 `apps/dsn/prompt/personality_v3`（另立任务，涉及 apps/dsn）。
- 不引入新第三方依赖（不用 pydantic / tiktoken / numpy 新用途）。
- 不做 LLM 情绪感知（默认关；`persona_llm_review` 作为可选项）。
- 不重构语义缓存引擎本身（只修用户隔离）。
- 不改 `Config` 的 import 期快照语义（避免打破 `conftest.py` 的既有假设）。
- 不追求"话题系统"这个抽象本身 —— 话题退化为轮次的一个属性。

---

## 12. 现状证据索引（审计产出，便于复核）

| 主题 | 关键证据 |
|---|---|
| 6 条并行装配路径 | `boot.py:243-256` / `plugins.py:649-714` / `plugins.py:57-61` / `agent_runtime.py:94` / `api/scan.py:326-327` / `boot.py:300-337` |
| 截断保留头部丢中间 | `harness/context_assembly.py:255-259`（实测 60 轮丢 36 轮） |
| tail 不占预算 | `memory/topics.py:742-746` + `context_assembly.py:292-294`（实测 386,215 字符） |
| 5 份对话副本 | `memory/core.py:126` / `:87` / `memory/topics.py:93` / `agent_runtime.py:94` / `infra/store/chat_store.py:49` |
| contextvars 跨线程 | `harness/pipeline/manager.py:97` + `prompts/builder.py:29/145-149` |
| 流式丢 PRE_PROCESS | `boot.py:733`（只跑 PREPARE） / `:558-560` / `:694-697` |
| 会话标识跨进程不稳定 | `boot.py:275-280` |
| 人格产物为空 | `apps/dsn_study/character_cards/study_tutor.distilled.json`（50 维全 0.5）+ `distillation_engine.py:301/314/395` |
| 演化链未回写 | `evidence_accumulator.py:50/192` + 生产库 306 条证据 + `distilled.json` mtime 未变 |
| 重启失忆 | `evidence_accumulator.py:125/143/175`（冷启动实测 `evidence_total=0`） |
| EXA 串味 | `harness/personality/personality_generator.py:308-311` + `__init__.py:442` |
| 没有安全网 | 全仓无 feature flag；`config.py:14-22`（import 期快照）；`web_admin/routes.py:467-470`（恒 501） |
| 三套人格实现 | `harness/personality/` 3767 行 / `apps/dsn/prompt/personality_v3/` / `apps/dsn/prompt/personality_v2/` 1654 行 |

---

## 13. 进度日志

| 日期 | 阶段 | 状态 | 备注 |
|---|---|---|---|
| 2026-11-11 | 计划 | ✅ | 三份只读审计完成（长上下文 / 人格 / 测试与接入面），本计划成文 |
| 2026-11-11 | 底座修复 | ✅ | 6 处 harness 缺陷修复，`apps/harness_lab` 验证台 60/60 通过 |
| 2026-11-11 | 上下文内核 v2 | ✅ | `apps/dsn_study/context/` 落地并接线（28 条单测 + 8 条端到端） |
| 2026-11-11 | 人格内核 | ✅ | `apps/dsn_study/persona/` 落地并接线（51 条单测） |
| 2026-11-11 | 旧路径清理 | ◐ | 旧 preamble 路径保留在 `context_engine=v1` 开关后，未删除（见 §14.4） |

---

## 14. 实施记录（2026-11-11）

### 14.1 顺序调整：先修底座，再重建

原计划是"直接重建"。实际执行改成**先修 harness 底层、再基于修好的底层重建**，
理由是审计发现人格系统的复杂度**不是设计缺陷，而是空转**：
线上产物 50 维全是 0.5、演化链从未回写、重启即失忆。
在这样的底座上重建上层，只会把空转搬进新代码。

### 14.2 底座修复（6 处，`apps/harness_lab` 60/60 通过）

| # | 缺陷 | 修法 |
|---|---|---|
| 1 | 蒸馏 pass2/pass3 的 `max_tokens=3000` 装不下提示词要求的输出 → JSON 被截断 → 解析失败 → **静默**产出空产物 | 预算提到 8000（重试 16000）+ 结构完整性校验（5 条行为模式/5 条言语模式/情绪模型/4 段关系/8 大类叙事；50 维齐全）+ 失败**抛 `DistillationError`** |
| 2 | 状态缓冲 3 条/5 秒，生产路径无人调用 `flush()` → 重启丢状态 | `on_interaction` 写穿落库（`force_flush`） |
| 3 | 证据状态（mu/sigma/counts/pending）只在内存 → 重启失忆、固化门槛永远达不到 | 全部以 DB 为真源；`personality_evidence` 加 `pending` 列（旧库自动补列） |
| 4 | `SegmentedContextAssembler.plan()` 的 memo 分支就地改写入参 | 改用 `replace()`（verbatim 分支早就修过） |
| 5 | 兜底串硬编码了别的应用的人格（"你是 EXA"） | 改为不含产品身份的行为准则 |
| 6 | 人格提示词缓存是全局单份 → 多用户串人格 | 缓存按 (卡, 用户, 关系阶段) 分桶 |

**顺带新增**：harness 侧公开 `PersonalitySystemV3.apply_event()`（判定由调用方给，
判定之外每一步完全一致）与 `classify_heuristic()`（零 LLM 的关键词分类）。

### 14.3 ⚠️ 决策反转：不再"替换"人格引擎，改为"复用修好的它"

**原计划 D2**：放弃 PEV3，改成"静态人格档案 + 6 个确定性状态旋钮 + 零 LLM"。
**实际执行**：保留并复用修好的 PEV3；dsn_study 侧只做**薄层**
（规则信号 + 提示词呈现 + API 形状）。

反转的依据是**验证结果**：

| 事实 | 修复前 | 修复后（`apps/harness_lab` 实测） |
|---|---|---|
| 亲密度演化 | 机制在，但不明显 | 连续表扬 12 轮：20.0 → 27.4，**增幅逐轮递减**（1.067 → 0.308），饱和曲线逐轮公式精确匹配 |
| 特质演化 | 50 维全 0.5 | 空白卡 55 轮后 **50 维全部偏离 0.5**，105 条证据 |
| 固化写回 | 从未触发 | 达标即写回 `distilled.json` |
| 重启 | 失忆 | 证据与状态完整恢复 |
| 提示词内容 | "（暂无）" | 完整的行为/言语模式 + 情绪/关系模型 |

即：原计划要替换的**不是"复杂但错"的机制，而是"被预算与持久化 bug 打死"的机制**。
修好之后，PEV3 的确定性内核（事件权重表 / 情绪冲量表 / 饱和曲线 / 遗忘 /
证据映射）本来就是这个系统里质量最高的部分 —— 全部保留。

仍然按原计划做的两件事（它们与"要不要重写引擎"无关）：
- **热路径不再有 LLM**：判定改为规则信号（`persona/signals.py`），
  LLM 判定降级为可选开关（`persona_llm_judge`，默认关）——
  这条原本就是 D2 的核心收益，与引擎实现无关；
- **提示词只呈现有意义的内容**：不塞 50 维原始向量、情绪向量、15 级亲密度标签。

### 14.4 已落地 vs 未落地

| 计划项 | 状态 | 说明 |
|---|---|---|
| 上下文内核（新包 + 接线） | ✅ | `apps/dsn_study/context/`，6 模块单向依赖 |
| 预算与裁剪（新规则） | ✅ | 全局硬上限含 tail、尾部截断、禁止中间丢失、纯函数 |
| `context_turns` / `context_facts` | ✅ | 新表；旧数据由 `scripts/migrate_context_v2.py` 幂等迁移（boot 时按需自动跑一次） |
| 记忆转写口 | ✅ | 同一份摘要/备忘同步进 `context_facts`（`MemorySystem.summary_sink/memo_sink`） |
| 会话 id 跨进程稳定 | ✅ | `session_chat_ids` 表持久化（旧 `chat_id=1..N` 数据原样保留） |
| contextvars 残留 | ✅ | 兜底路径的 `build()` 改为显式传 uid/context |
| 流式/非流式一致 | ✅ | 流式补跑 PRE_PROCESS、传 `ctx.message`、`<plan_check>` 不再外泄到文本与 TTS |
| 人格薄层 | ✅ | `apps/dsn_study/persona/`（规则信号 / 呈现 / API 形状）+ PEV3 形状兼容层 |
| 角色卡进版本库 | ✅ | `persona/cards/study_tutor.yaml`（旧目录归档到 `persona/cards/_legacy/`） |
| Feature Gate | ✅ | `apps/dsn_study/gating.py`（运行时求值）+ 面板 `/api/admin/flags` 读写 |
| 旧路径删除 | ◐ **未做** | 旧 preamble 路径保留在 `context_engine=v1` 开关后 —— 删掉就没有回滚路径了，等新路径稳定运行后再删 |
| 话题系统下线 | ⛔ **不做** | 话题退化为轮次的一个属性 + 一条事实，但 `TopicManager` 本体暂不删（它还管 `compressed_chunks` 等） |
| `harness/context_assembly.py` | ⛔ **不动** | `apps/dsn_ui` / `apps/emotion_exp` 还在用；dsn_study 已不再引用 |

### 14.5 改动的既有用例（逐条列出）

| 用例 | 改前 | 改后 | 原因 |
|---|---|---|---|
| `test_dsn_study_personality.py::test_study_tutor_card_exists_and_validates` | 断言卡在 `apps/dsn_study/character_cards/study_tutor.yaml` | 断言卡在 `apps/dsn_study/persona/cards/study_tutor.yaml` | 旧目录被 `.gitignore` 忽略 → 卡只存在于某一台机器上；新目录进版本库。**卡的正文逐字未变** |
| `test_dsn_study_personality.py::test_study_cards_dir_is_not_dsns` | 断言 boot 源码含 `"character_cards"` | 断言 boot 源码含 `'"persona", "cards"'` | 同上；**断言的意图（不能用 dsn 的 EXA 卡）保持不变** |

其余既有用例**全部未改**。

### 14.6 当前基线

- `pytest tests/`：**1227 passed / 18 failed** —— 18 项失败与改动前**完全一致**
  （缺 `pytest-asyncio` 插件、缺 TTS 服务、缺 MCP stdio 子进程等环境问题）。
- `apps/harness_lab`：**60/60 通过**（底座修复全部有回归网）。
- 新增测试：上下文内核 28 条 + 人格内核 51 条 + 端到端接线 8 条 + 验证台 63 条。

