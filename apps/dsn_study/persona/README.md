# dsn_study 人格内核（persona/）

**薄层**。人格引擎在 `harness/personality`（PEV3）—— 动力学、证据、审计、
落库、缓存分桶、兜底串都在那边，本包**不重写**人格引擎。

本包只做 dsn_study 侧的四件事：

| 模块 | 职责 |
|---|---|
| `cards/` | 版本化的角色卡（「小舟」），**进 git** |
| `signals.py` | 规则信号抽取（零 LLM 的事件判定） |
| `engine.py` | `PersonaEngine`：提示词呈现 / 状态回写 / API 形状 |
| `__init__.py` | 公共接口 |

契约见 `apps/dsn_study/REBUILD_SPEC.md` §3。

---

## 1. 卡片（`cards/`）

* 目录 `apps/dsn_study/persona/cards/`，文件名 `<card_id>.yaml`，
  格式沿用 `harness/personality/character_card.py` 的 `CharacterCard`
  （不自造格式）。
* `study_tutor.yaml` 是从旧目录 `apps/dsn_study/character_cards/` 搬过来的
  「小舟」卡，**自然语言逐字保留**（`natural_language` 整块未改一字，
  语料也逐条一致）。
* 为什么要搬：旧的 `character_cards/` 被 `.gitignore` 的 `*character_cards*`
  命中 —— 那张卡只存在于某一台机器上，clone 出来的人没有卡可用。
  新目录 `persona/cards/` **不被**这条规则命中（已用
  `git check-ignore` 验证）。
* 旧目录已归档到 `persona/cards/_legacy/`；同目录下的 `backups/` 与
  `*.distilled.json` 是**派生物**（蒸馏产物与备份），由 `.gitignore` 排除，
  不入库。本包的 `cards()` 只扫 `*.yaml`（不递归），不会把它们当成角色卡。

> 接线方注意：PEV3 的 `cards_dir` 要指向本目录，否则 `switch()` 绑不上。

## 2. 规则信号（`signals.py`）

默认路径**零 LLM**：关键词子串匹配（大小写与全半角不敏感，不引入正则依赖），
一次最多返回 **1 条**信号，命中多条时按
`conflict > venting > complaint > thanks > praise` 取一条。

| 条件 | event_type | intensity | valence |
|---|---|---|---|
| `answer_correct is True` | `praise` | medium | positive |
| `answer_wrong is True` | `complaint` | medium | negative |
| 文本含「谢谢/厉害/牛/学到了/懂了」 | `thanks` | medium | positive |
| 文本含「搞错/不对/错了/没懂/听不懂」 | `complaint` | medium | negative |
| 文本含「烦/累/不想学/放弃/压力」 | `venting` | medium | negative |
| 文本含「生气/你有病/别管我/滚」 | `conflict` | high | negative |
| 其它 | `neutral` | low | neutral |

两个设计取舍：

1. **显式答题结果与关键词命中同池竞争**，最终按事件优先级只留一条 ——
   `answer_correct=True` 且用户说「谢谢」时记 `thanks`（用户确实在道谢），
   而不是 `praise`（用户并没有夸角色）。
2. **只看用户文本**，不看助手回复：回复是结果，不是事件。

保守是刻意的：宁可判 `neutral`，也不要把普通陈述句误判成情绪事件。

## 3. `PersonaEngine`

```python
from apps.dsn_study.persona import PersonaEngine

engine = PersonaEngine(pv3, use_llm_judge=False, trace_sink=None)
```

### `prompt_block(uid) -> str`

给 system prompt 的人格段落。**任何异常都必须降级**（返回 `''` 或安全文本），
绝不抛出去 —— 红线 R6：人格故障不能让整轮对话失败。

只呈现**有意义**的东西（上限 800 字）：

* 档案正文（角色卡的自然语言，逐字搬过来）；
* 关系阶段（当前标签，不给等级表、不给亲密度数值）；
* 偏离基线 ≥0.05 的特质（最多 5 条，带中文名，不带维度编号）。

**不**呈现：50 维原始向量、情绪向量、亲密度 15 级标签表，
也**不**出现别的应用的人格身份（跨应用串味会被清掉）。

> 特质取自「稳定特质中心」（蒸馏产物 = 真正演化出来的那份性格），
> 而不是 PEV3 对外暴露的瞬时向量 —— 后者含每小时噪声与情绪调制，
> 拿它当「人格特质」会把噪声当性格。

### `feedback(uid, user_msg, reply, *, answer_correct=None, answer_wrong=None) -> None`

回写人格状态，**绝不抛异常、绝不阻塞调用方**：

* 默认：规则信号 → 构造 `harness.personality.events.PerceptionRecord`
  → 调 `pv3.apply_event(uid, perception, conversation_history="")`
  （**该方法不存在时降级为不做事并记一条日志**，绝不崩）；
* `use_llm_judge=True`：改调 `pv3.analyze_interaction(...)`（会发起 LLM 调用，
  请放到后台线程）。

动力学 / 证据 / 审计 / 落库全由 PEV3 完成，本包不重复实现。

### `status(uid) -> dict`

```python
{"uid", "card_id", "affinity", "affinity_level", "total_interactions",
 "mood", "traits", "evidence_total", "last_updated"}
```

`traits` 是**偏离基线的维度**列表（`tid` / `name` / `value` / `label` /
`deviation`）。

### `cards() -> list[dict]` / `switch(uid, card_id) -> bool`

卡片清单与切换（失败返回 `False`，不抛）。

## 4. 开关

本包**不读** feature gate —— 开关归接线方：

```python
from apps.dsn_study import gating
engine = PersonaEngine(pv3, use_llm_judge=gating.enabled("persona_llm_judge", False))
```

## 5. 单测

```bash
python3 -m pytest tests/test_dsn_study_persona_kernel.py -q -p no:cacheprovider
```
