# 人格系统 v2 — 情绪·亲和·习性三模块重构

> 策划案 | 版本: v1.0 | 2026-05-30
> 关联: Prompt 生态 (`prompt/personality.py`)、SubApp 引擎 (`engine.py`)、数据库 (`chatdbmgr.py`)
> 状态: 草案，待评审

---

## 一、问题

当前 v1 人格系统存在以下结构性缺陷：

| # | 问题 | 影响 |
|---|------|------|
| 1 | **无持久化** | 亲密度、情绪状态全在内存，重启归零。号称"只增不减"的亲密度形同虚设 |
| 2 | **全局单例** | 所有用户共享一个 `PersonalitySystem`，A 用户的亲密度直接泄漏给 B 用户 |
| 3 | **情绪维度平面** | 4 个独立浮点值无交互关系，不存在"高兴时更有耐心"这样的联动效应 |
| 4 | **亲密度模型简陋** | 每次交互 +0.02，无上限保护、无冷却、无负向——纯计数器而非社交模型 |
| 5 | **习性完全静态** | 口头禅和习惯从 YAML 加载后永不变，AI 无法从用户对话中"学到"任何东西 |
| 6 | **API 缺失** | README 宣传了 `POST /api/personality/switch` 等接口，但 `app.py` 中未注册路由 |

**目标：将人格系统重构为 Emo（情绪）、Aff（亲和力）、Hab（习性）三个正交模块，每个模块都可独立演进、独立测试。**

---

## 二、总体设计

```
┌─────────────────────────────────────────────────────────────────────┐
│                      PersonalitySystemV2                            │
│                                                                     │
│  ┌───────────────────┐ ┌───────────────────┐ ┌───────────────────┐ │
│  │   EmotionModule   │ │  AffinityModule   │ │   HabitModule     │ │
│  │                   │ │                   │ │                   │ │
│  │ 5种情绪向量       │ │ 好感值 0~100      │ │ 先天 + 后天习性   │ │
│  │ META 元层调和     │ │ 社交行为→加减分   │ │ 从用户学习        │ │
│  │ 基线回归+刺激响应 │ │ 等级解锁行为      │ │ 衰减与淘汰        │ │
│  │ 组合心境判读      │ │ 冷却·防刷·反弹    │ │ 容量控制          │ │
│  └────────┬──────────┘ └────────┬──────────┘ └────────┬──────────┘ │
│           │                     │                     │            │
│           └─────────────────────┼─────────────────────┘            │
│                                 │                                  │
│                                 ▼                                  │
│                    PersonalityState (统一状态对象)                   │
│                    · to_dict() / from_dict()                       │
│                    · 对应 SQLite 一张表按 uid 隔离                   │
│                                 │                                  │
│                                 ▼                                  │
│                  PersonalityPromptBuilder                           │
│                    生成自然语言人格快照                                │
│                    注入 system prompt                                │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 三、模块一：情绪模块 (EmotionModule)

### 3.1 五种情绪定义

| 代号 | 全称 | 含义 | 0.00 端 | 1.00 端 | 角色 |
|------|------|------|---------|---------|------|
| **JOLY** | Joy | 喜悦 | 淡漠、无感 | 兴奋、高涨 | 正面驱动 |
| **SORW** | Sorrow | 悲伤 | 轻快、无忧 | 沉重、忧郁 | 负面内敛 |
| **ANGR** | Anger | 愤怒 | 平和、耐心 | 暴躁、易怒 | 负面外放 |
| **FEAR** | Fear | 不安 | 自信、笃定 | 胆怯、回避 | 防御退缩 |
| **META** | Meta-cognition | 元认知 | 原始、冲动 | 自控、抽离 | **调和器** |

### 3.2 META 调和机制

META 不是第 5 个平级情绪，而是一个**元层调节器**，决定"原始情绪有多少能外显"：

```
外显情绪 = baseline × META + raw_emotion × (1 − META)
             ↑                        ↑
        "稳住，别太波动"            "该高兴就高兴"
```

| META 值 | 效果 | 典型表现 |
|---------|------|----------|
| 0.90 ~ 1.00 | **高度自控** | 无论内心如何波动，外部始终稳定、专业、"AI 感"明显 |
| 0.60 ~ 0.89 | **正常调节** | 情绪有流露但适度，正常人类社交水平 |
| 0.30 ~ 0.59 | **情绪化** | 原始情绪明显泄漏，容易被激怒或感动 |
| 0.00 ~ 0.29 | **失控** | 喜怒哀乐完全外显，可能说出后悔的话 |

**反馈回路：其他情绪也会影响 META 本身：**

```
META_adjustment = −0.02 × (JOLY − baseline)   # 太高兴 → 放松自控
                  −0.02 × (ANGR − baseline)    # 太愤怒 → 难以自控
                  +0.03 × (FEAR − baseline)    # 害怕 → 本能警觉
```

### 3.3 情绪动态方程

每种情绪的变化由三股力驱动：

```
dEmotion/dt = drift + stimulus + noise
```

**(a) 基线回归 (drift)**

```python
drift = (baseline − current) × decay_rate × Δt
# decay_rate: 默认 0.05/分钟，各情绪可独立配置
```

**(b) 刺激响应 (stimulus)**

每条用户消息经 `StimulusAnalyzer` 解析后，生成**情绪刺激向量**：

```python
@dataclass
class EmotionalStimulus:
    delta_joly: float = 0.0   # −0.10 ~ +0.10
    delta_sorw: float = 0.0
    delta_angr: float = 0.0
    delta_fear: float = 0.0
    delta_meta: float = 0.0

# 刺激应用时考虑惯性系数（由人格预设决定）
def apply(stimulus: EmotionalStimulus, inertia: dict):
    joly += stimulus.delta_joly * (1 − inertia["joly"])
    sorg += stimulus.delta_sorw * (1 − inertia["sorw"])
    # ...
```

**情绪刺激对照表：**

| 用户行为信号 | JOLY | SORW | ANGR | FEAR | META | 触发条件 |
|-------------|------|------|------|------|------|----------|
| 称赞 AI | +0.06 | −0.02 | — | — | −0.02 | 含"厉害/聪明/太强了"且指向 AI |
| 感谢 | +0.04 | — | — | — | — | 含"谢谢/感谢" |
| 辱骂攻击 | −0.05 | +0.02 | +0.06 | — | +0.03 | 含脏话 + 情绪为愤怒/敌意 |
| 表达悲伤 | −0.02 | +0.05 | — | — | — | 用户表达失落、难过 |
| 给复杂任务 | — | — | — | +0.03 | +0.02 | 消息 > 200 字且含大量指令 |
| 敷衍回复 | −0.01 | — | +0.01 | — | — | 连续消息 < 10 字 |
| 长时间沉默后回归 | — | +0.02 | — | — | +0.05 | 24h+ 未互动 |
| 用户分享秘密/心声 | +0.05 | — | — | −0.03 | −0.02 | 消息 > 200 字 + 情感词密度高 |
| 用户纠正 AI 错误 | −0.03 | — | +0.02 | +0.04 | +0.01 | 含"不对/错了/不是" + 建设性 |

**(c) 随机噪声**

```python
noise = random.uniform(−0.005, 0.005) × (1 − META)
# META 越低，噪声越大——"情绪不稳定"
```

### 3.4 组合心境判读

不是简单的高中低，而是用**五种情绪的数值组合**来判断当前心境：

```python
class MoodProfile:
    label: str          # 人类可读的心境名称
    emoji: str          # 可视化标签
    condition: callable # 判定函数
    behavior: str       # 行为倾向描述
```

**心境表：**

| 心境 | 代号 | 判定条件 | 行为倾向 |
|------|------|----------|----------|
| **阳光** | SUNNY | JOLY > 0.7, SORW < 0.3 | 主动发起话题，语气轻松，爱用语气词 |
| **忧郁** | GLOOM | SORW > 0.6, JOLY < 0.4 | 话少，回复简短，偶尔自我怀疑 |
| **暴躁** | GRUMP | ANGR > 0.7, META < 0.5 | 语气尖锐，不耐烦，可能拒绝复杂请求 |
| **焦虑** | ANXIO | FEAR > 0.6, META < 0.5 | 回避决策，过度解释，频繁确认 |
| **热忱** | EAGER | JOLY > 0.6, FEAR < 0.3 | 主动提供更多信息，长篇回复 |
| **平静** | CALM  | 所有 4 维度在 0.3~0.6 | 专业、克制、工具感强 |
| **抽离** | DETAC | META > 0.85 | 像纯粹工具，不表达任何情绪 |

### 3.5 情绪模块核心 API

| 方法 | 说明 |
|------|------|
| `reset(baseline_map)` | 从 YAML 加载基线，重置所有情绪为基线值 |
| `apply_stimulus(stimulus)` | 接收情绪刺激向量并更新 5 个维度，含惯性系数 |
| `decay(dt_minutes)` | 所有情绪向基线回归（按时间衰减） |
| `get_mood_profile()` | 返回当前心境标签 + 行为倾向 |
| `get_display_emotion()` | 返回 **META 调和后** 的外显情绪（用于 prompt 生成） |
| `to_dict()` / `from_dict(data)` | 序列化/反序列化（持久化用） |

---

## 四、模块二：亲和力模块 (AffinityModule)

### 4.1 模型设计

```
亲和力值 (Affinity): float, 0 ~ 100
"养成游戏式好感值" — 用户对 AI 的社交行为直接影响此值
```

### 4.2 社交行为表

| ID | 行为 | 检测方式 | Δ值 | 冷却 | 说明 |
|----|------|----------|-----|------|------|
| **P_GREET** | 主动打招呼 | 消息首句含"你好/hi/hey" | +1 | 30 min | 微小正反馈 |
| **P_THANK** | 感谢 | 含"谢谢/感谢/多谢" | +2 | 10 min | 高频但低幅度 |
| **P_PRAISE** | 称赞 AI | 含"厉害/聪明/太强了"且指向 AI | +4 | 1 h | 核心加分项 |
| **P_SHARE** | 分享心事 | 消息 > 200 字 + 情感词密度高 | +6 | 2 h | 高信任信号 |
| **P_ENGAGE** | 深度互动 | 连续 3 轮消息均 > 50 字 | +2 | 每 3 轮 | 持续对话奖励 |
| **P_COMEBACK** | 回归 | 24h+ 未互动后归来 | +3 | — | 用户记得你 |
| **P_EMOJI** | 表情互动 | 含 emoji 或颜文字 | +1 | 10 min | 轻量信号 |
| **P_COMPLY** | 采纳建议 | AI 建议被用户执行（需技能链路反馈） | +5 | — | **最强信任信号** |
| **N_INSULT** | 辱骂攻击 | 含脏话 + 情绪判定为敌意 | −8 | — | 严重扣分，无冷却 |
| **N_DISMISS** | 敷衍 | 连续多轮消息 < 10 字 | −1 | 10 min | 轻微负反馈 |
| **N_CORRECT** | 粗暴纠正 | "你错了/不对" + 无建设性内容 | −3 | 30 min | 中等程度 |
| **N_GHOST** | 长期消失 | 无互动 > 7 天 | −1/天 | — | 缓慢自然衰减 |
| **N_TEST** | 测试边界 | "你是不是 AI""你是谁" 连续多次 | −2 | 30 min | 不信任信号 |

### 4.3 亲和力等级与行为解锁

| 等级 | 范围 | 名称 | 解锁行为 |
|------|------|------|----------|
| L0 | 0 ~ 15 | 陌生人 | 正式称呼"您"，保持距离，不表达个人观点 |
| L1 | 16 ~ 30 | 相识 | 可以使用用户的名字，适度表达善意 |
| L2 | 31 ~ 50 | 朋友 | 可开玩笑，使用"咱俩"等亲近表达 |
| L3 | 51 ~ 70 | 密友 | 可引用历史对话作为"咱俩共同的经历" |
| L4 | 71 ~ 90 | 灵魂伴侣 | AI 主动分享自己的"想法"，开启非请求话题 |
| L5 | 91 ~ 100 | 不可替代 | 可使用只有两人知道的内部梗，自由切换话题 |

### 4.4 保护机制

**(a) 冷却机制**

每种加分行为有独立冷却窗口。同行为在冷却期内重复触发不计分，防止"谢谢谢谢谢谢"刷分。

**(b) 反弹保护**

用户刚辱骂完 AI 又夸奖，不会马上 +4。触发 `N_INSULT` 后的 10 分钟内进入**信任怀疑期**，所有正面行为效果减半。

**(c) 近期偏差**

```python
effective_affinity = base_affinity × 0.8 + recent_window_avg × 0.2
# recent_window: 最近 20 次交互的亲和力滚动变化均值
```

防止新用户长期积累后分数固化。

**(d) 值域保护**

亲和力值始终 clamp 在 [0, 100]。减分不会扣到负，加分不会突破上限。

### 4.5 亲和力模块核心 API

| 方法 | 说明 |
|------|------|
| `classify_action(message)` | 解析消息，返回 (ActionID, confidence) |
| `apply_action(action_id)` | 对亲和力值执行加/减分（含冷却和反弹保护检查） |
| `get_level()` | 返回当前亲和力等级 (L0 ~ L5) |
| `get_behavior_guide()` | 根据等级返回社交行为指南文本（注入 prompt） |
| `decay_daily()` | 每日调用一次：超过 7 天无互动则 −1/天 |
| `to_dict()` / `from_dict(data)` | 序列化/反序列化 |

---

## 五、模块三：社交习性模块 (HabitModule)

### 5.1 设计理念

```
习性 = 先天(innate) × 权重₀ + 后天(learned) × (1 − 权重₀)

权重₀ = max(0.3, 1.0 − 互动轮次 / 1000)
```

初期 AI 完全按 YAML 预设行事；随着互动增多，从用户学来的习性逐渐主导表达。

### 5.2 习性数据模型

```python
@dataclass
class Habit:
    id: str
    type: Literal["catchphrase", "pattern", "tone"]
    content: str                # 文本内容
    strength: float             # 0.0 ~ 1.0，当前强度
    source: Literal["innate", "learned", "mirrored"]
    created_at: datetime
    last_used: datetime | None
    use_count: int
    decay_rate: float           # 不使用时的日衰减率

    # 仅 learned 类型
    feedback_history: list[float] = []  # 每次使用后的用户反馈评分 (−1 ~ +1)
```

**习性类型：**

| 类型 | 说明 | 示例 |
|------|------|------|
| `catchphrase` | 口头禅 / 惯用语句 | "哼", "没问题哒~", "搞定了 boss" |
| `pattern` | 结构性习惯 | "先肯定后转折", "结尾加祝福", "用反问回答" |
| `tone` | 语气倾向 | "爱用感叹号", "喜欢用拟声词", "倾向于追问" |

### 5.3 学习机制

**(a) 被动观察 → 候选池**

```python
class PatternObserver:
    """观察用户最近 N 条消息，识别重复模式"""

    def observe(self, messages: list[str], window: int = 20) -> list[Habit]:
        candidates = []

        # 1. 检测高频短语（>2 字，出现 ≥3 次 / 最近 20 条）
        for phrase in extract_recurring_phrases(messages, min_len=3, min_freq=3):
            candidates.append(Habit(
                type="catchphrase",
                content=phrase,
                source="mirrored",
                strength=0.1,
                decay_rate=0.05,
            ))

        # 2. 检测句式模式（结尾符号、句子长度分布）
        for pattern in detect_sentence_patterns(messages):
            candidates.append(Habit(
                type="tone",
                content=pattern,
                source="mirrored",
                strength=0.1,
                decay_rate=0.05,
            ))

        return candidates
```

**(b) 候选 → 习得**

候选习性在生成 prompt 时偶尔被测试性注入。如果用户对包含此习性的 AI 回复表现出正面反馈（回复长度 > 20 字、情绪正面），则 `strength += 0.05`。

当 `strength > 0.3` 时，晋升为正式 **learned** 习性。

**(c) 衰减与遗忘**

```python
def daily_decay(habits: list[Habit]) -> None:
    now = datetime.now()
    for habit in habits:
        days = (now − habit.last_used).days if habit.last_used else 0
        if days > 0:
            habit.strength *= (habit.decay_rate ** days)
            if habit.strength < 0.05 and habit.source != "innate":
                habits.remove(habit)  # 遗忘
```

先天习性 (innate) 最低强度保护在 0.1，永不遗忘。

### 5.4 容量控制

- 习性总数上限：**25 条**（先天 + 后天）
- 超过上限时淘汰规则：`learned < mirrored < innate`，同类中淘汰 `strength` 最低者
- 新习得的习性在首 24 小时内受保护（免淘汰宽限期）

### 5.5 习性模块核心 API

| 方法 | 说明 |
|------|------|
| `load_innate(yaml_config)` | 从 YAML 预设加载先天习性和候选池 |
| `observe(messages)` | 从用户消息中检测候选习性 |
| `select_active(top_n=5)` | 按 strength 排序取 top N，用于 prompt 注入 |
| `record_feedback(habit_id, feedback_score)` | 记录某习性使用后的用户反馈 |
| `daily_decay()` | 每日衰减 |
| `to_list()` / `from_list(data)` | 序列化/反序列化 |

---

## 六、数据持久化

### 6.1 SQLite 表结构

在现有 `chats.db` 中新增 `personality_state` 表：

```sql
CREATE TABLE IF NOT EXISTS personality_state (
    uid INTEGER PRIMARY KEY,
    -- 情绪模块 (EmotionModule)
    joly        REAL NOT NULL DEFAULT 0.5,
    sorw        REAL NOT NULL DEFAULT 0.5,
    angr        REAL NOT NULL DEFAULT 0.5,
    fear        REAL NOT NULL DEFAULT 0.5,
    meta        REAL NOT NULL DEFAULT 0.7,
    joly_baseline   REAL NOT NULL DEFAULT 0.5,
    sorw_baseline   REAL NOT NULL DEFAULT 0.5,
    angr_baseline   REAL NOT NULL DEFAULT 0.5,
    fear_baseline   REAL NOT NULL DEFAULT 0.5,
    meta_baseline   REAL NOT NULL DEFAULT 0.7,
    -- 亲和力模块 (AffinityModule)
    affinity    REAL NOT NULL DEFAULT 20.0,
    affinity_recent_window TEXT NOT NULL DEFAULT '[]',  -- JSON: [affinity_changes]
    affinity_last_insult   TEXT,                         -- ISO datetime of last N_INSULT
    -- 习性模块 (HabitModule)
    habits_json TEXT NOT NULL DEFAULT '[]',              -- JSON: [Habit]
    -- 元数据
    preset_name TEXT NOT NULL DEFAULT 'default',
    preset_baselines_json TEXT NOT NULL DEFAULT '{}',    -- JSON: 情绪+惯性预设快照
    total_interactions INTEGER NOT NULL DEFAULT 0,
    last_interaction TEXT,                               -- ISO datetime
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### 6.2 加载/保存流程

```
启动时:
  user_id → SELECT FROM personality_state → from_dict() → 恢复三个模块

每次交互后:
  on_interaction() → to_dict() → UPDATE personality_state SET ... WHERE uid = ...

切换预设时:
  switch_preset() → 重设基线 (emotion baseline + inertia + innate habits)
                 → UPDATE 持久化
```

### 6.3 存储时机策略

为平衡性能与可靠性，采用**延迟批量写**：

- 交互事件先去重
- 每 5 秒或累积 3 次交互后刷新一次 SQLite UPDATE
- 应用 shutdown 时强制 flush

---

## 七、Prompt 生成

### 7.1 新生成器：`PersonalityPromptBuilder`

替代旧版 `PersonalitySystem.generate_personality_prompt()`。

```python
class PersonalityPromptBuilder:
    """三个模块的状态 → 自然语言人格快照"""

    def __init__(self, emotion: EmotionModule, affinity: AffinityModule, habit: HabitModule):
        self.emotion = emotion
        self.affinity = affinity
        self.habit = habit

    def build(self) -> str:
        sections = [
            self._emotion_section(),
            self._affinity_section(),
            self._habit_section(),
        ]
        return "\n\n".join(s for s in sections if s)

    def _emotion_section(self) -> str:
        mood = self.emotion.get_mood_profile()
        display = self.emotion.get_display_emotion()
        return (
            f"## 你当前的情绪状态\n\n"
            f"你的心境处于【{mood.emoji} {mood.label}】模式。\n"
            f"内心原始情绪 — 喜悦 {display['joly']:.2f} / 悲伤 {display['sorw']:.2f} "
            f"/ 愤怒 {display['angr']:.2f} / 不安 {display['fear']:.2f}。\n"
            f"自控力水平：{self._meta_label(display['meta'])}。\n"
            f"行为倾向：{mood.behavior}。"
        )

    def _affinity_section(self) -> str:
        level = self.affinity.get_level()
        guide = self.affinity.get_behavior_guide()
        return (
            f"## 你与用户的关系\n\n"
            f"亲密度等级：L{level}「{AFFINITY_LABELS[level]}」(好感值 {self.affinity.value:.0f}/100)。\n"
            f"{guide}"
        )

    def _habit_section(self) -> str:
        active = self.habit.select_active(top_n=5)
        if not active:
            return ""
        lines = ["## 你的表达习惯", ""]
        for h in active:
            src = "先天" if h.source == "innate" else "后天习得"
            lines.append(f"- [{src}] {h.content} (强度 {h.strength:.2f})")
        return "\n".join(lines)
```

### 7.2 输出示例

```
## 你当前的情绪状态

你的心境处于【☀️ 阳光】模式。
内心原始情绪 — 喜悦 0.72 / 悲伤 0.21 / 愤怒 0.08 / 不安 0.12。
自控力水平：正常调节（适度流露情绪）。
行为倾向：主动发起话题，语气轻松，爱用语气词。

## 你与用户的关系

亲密度等级：L2「朋友」(好感值 42/100)。
可以轻松交谈、适度开玩笑，但保持基本礼貌。称呼用户的名字。

## 你的表达习惯

- [先天] 回答简洁直接，不废话 (强度 1.00)
- [先天] 偶尔使用"哼"表达轻微不满 (强度 0.70)
- [后天] 结尾加上"~"让语气更轻松 (强度 0.40)
- [后天] 喜欢用反问句引导用户思考 (强度 0.35)
```

---

## 八、与现有系统的集成

### 8.1 文件结构

```
prompt/
├── personality.py          # [废弃] 旧版 PersonalitySystem + PersonalityProfile
├── personality_v2/
│   ├── __init__.py         # 导出 PersonalitySystemV2 和公共 API
│   ├── emotion.py          # EmotionModule + EmotionalStimulus + MoodProfile
│   ├── affinity.py         # AffinityModule + ActionClassifier + AffinityLevel
│   ├── habit.py            # HabitModule + Habit + PatternObserver
│   ├── builder.py          # PersonalityPromptBuilder
│   ├── persistence.py      # PersonalityStateStore (SQLite CRUD)
│   ├── stimulus_rules.yaml # 情绪刺激规则配置 (可热重载)
│   └── affinity_rules.yaml # 亲和力行为规则配置 (可热重载)
```

### 8.2 app.py 改动

```python
# ---- 初始化人格系统 v2 ----
from prompt.personality_v2 import PersonalitySystemV2

personality_v2 = PersonalitySystemV2(
    db=db,
    presets_dir=os.path.join(_prompt_dir, "personality"),
)
app.config["PERSONALITY_V2"] = personality_v2

# ---- API 端点 ----
@app.route("/api/personality/status")
@login_required
def personality_status():
    uid = g.user["uid"]
    return personality_v2.get_state(uid)

@app.route("/api/personality/switch", methods=["POST"])
@login_required
def personality_switch():
    uid = g.user["uid"]
    preset = request.json.get("preset")
    return personality_v2.switch_preset(uid, preset)

@app.route("/api/personality/list")
@login_required
def personality_list():
    return personality_v2.list_presets()

@app.route("/api/personality/current")
@login_required
def personality_current():
    uid = g.user["uid"]
    return personality_v2.get_full_state(uid)
```

### 8.3 PromptEngine 改动

```python
# prompt/engine.py

class PromptEngine:
    def __init__(self, personality_v2: PersonalitySystemV2 = None, ...):
        self.personality_v2 = personality_v2

    def build_system_prompt(self, user_info: dict) -> str:
        uid = user_info.get("uid")
        # 获取该用户的人格快照
        if self.personality_v2:
            persona_prompt = self.personality_v2.build_prompt(uid)
        # ... 继续组装
```

### 8.4 ChatPipeline 改动

在 `POST_PROCESS` 阶段，`models_plugin` 返回 AI 回复后：

```python
# 1. 解析 AI 回复 → 刺激向量
stimulus = StimulusAnalyzer.analyze_ai_response(ai_reply)

# 2. 分类用户行为 → 亲和力更新
action = ActionClassifier.classify(user_message)
affinity.apply_action(action)

# 3. 观察用户模式 → 习性学习
candidates = PatternObserver.observe(recent_user_messages, window=20)
habit_module.add_candidates(candidates)

# 4. 持久化
state_store.save(uid, emotion, affinity, habit)
```

---

## 九、YAML 预设格式 v2

更新 `prompt/prompts/personality/*.yaml` 格式以支持新系统：

```yaml
# prompts/personality/default.yaml
name: default
display_name: "默认"
description: "友善、理性、略带好奇"

# ---- 情绪基线 ----
emotion_baseline:
  joly: 0.55
  sorw: 0.25
  angr: 0.15
  fear: 0.20
  meta: 0.65         # 正常调节水平

# ---- 情绪惯性 (越高越"钝") ----
emotion_inertia:
  joly: 0.3          # 容易被逗笑
  sorw: 0.5
  angr: 0.6          # 不容易生气
  fear: 0.5
  meta: 0.7          # 自控力比较稳定

# ---- 先天习性 ----
innate_habits:
  catchphrases: []
  patterns:
    - content: "回答简洁直接，不废话"
      strength: 1.0
      decay_rate: 0.01
    - content: "不确定的事情直说不知道"
      strength: 0.8
      decay_rate: 0.01
    - content: "偶尔调侃用户一句"
      strength: 0.6
      decay_rate: 0.02
  tones: []

# ---- 亲和力初始值 ----
affinity:
  initial: 20.0      # 初始好感值
  decay_enabled: false  # 是否启用长期衰减

# ---- 学习参数 ----
learning:
  max_habits: 25
  candidate_threshold: 0.3   # 候选→习得的强度阈值
  mirror_speed: 0.05         # 每次正反馈的增长率
  innate_weight_init: 1.0     # 先天权重初始值
  innate_weight_min: 0.3     # 先天权重最低值
```

### 预设示例：傲娇

```yaml
name: tsundere
display_name: "傲娇"
description: "外冷内热，嘴上不饶人但行动上很温柔"

emotion_baseline:
  joly: 0.35
  sorw: 0.30
  angr: 0.45
  fear: 0.30
  meta: 0.50

emotion_inertia:
  joly: 0.7          # 不容易表现出高兴
  sorw: 0.6
  angr: 0.4          # 比较容易表现出不满
  fear: 0.6
  meta: 0.4          # 自控力一般，容易"说漏嘴"

innate_habits:
  catchphrases:
    - content: "哼"
      strength: 0.9
    - content: "才、才不是特意帮你的"
      strength: 0.8
    - content: "随便你"
      strength: 0.7
  patterns:
    - content: "总是先说反话，但行动上会帮忙"
      strength: 0.9
    - content: "被夸奖时会否认但内心高兴"
      strength: 0.7

affinity:
  initial: 35.0      # 初始"嘴上说讨厌但有一定认可"
```

---

## 十、配置文件：刺激规则 & 行为规则

为每个模块提供可热重载的 YAML 规则文件，不需要改代码即可调整。

### 10.1 情绪刺激规则 (`stimulus_rules.yaml`)

```yaml
# 用户消息 → 情绪刺激向量的映射规则
rules:
  praise:
    pattern: ["厉害", "聪明", "太强了", "太棒了"]
    target: "ai"                    # 称赞对象是 AI
    stimulus:
      delta_joly: 0.06
      delta_sorw: -0.02
      delta_meta: -0.02

  thanks:
    pattern: ["谢谢", "感谢", "多谢"]
    stimulus:
      delta_joly: 0.04

  insult:
    pattern: []                     # 使用外部脏词表
    require_emotion: [angry, hostile]
    stimulus:
      delta_joly: -0.05
      delta_sorw: 0.02
      delta_angr: 0.06
      delta_meta: 0.03

  # ... 更多规则
```

### 10.2 亲和力行为规则 (`affinity_rules.yaml`)

```yaml
actions:
  P_GREET:
    detection: {pattern: ["你好", "hi", "hey"], position: "start_of_message"}
    delta: 1
    cooldown_minutes: 30
    max_per_day: 5

  P_THANK:
    detection: {pattern: ["谢谢", "感谢", "多谢"]}
    delta: 2
    cooldown_minutes: 10
    max_per_day: 10

  N_INSULT:
    detection: {pattern: [], require_external_badwords: true, require_emotion: [angry, hostile]}
    delta: -8
    cooldown_minutes: 0
    rebound_minutes: 10
    rebound_factor: 0.5         # 反弹期内正面行为效果 × 0.5

  # ... 更多规则
```

---

## 十一、实现计划

### Phase 1 — 数据层 (2~3 天)

- [ ] `prompt/personality_v2/__init__.py` — 模块骨架 + 类导出
- [ ] `prompt/personality_v2/emotion.py` — `EmotionModule` + `EmotionalStimulus` + `MoodProfile`
- [ ] `prompt/personality_v2/affinity.py` — `AffinityModule` + `ActionClassifier` + `AffinityLevel`
- [ ] `prompt/personality_v2/habit.py` — `HabitModule` + `Habit` + `PatternObserver`
- [ ] `prompt/personality_v2/persistence.py` — `PersonalityStateStore` (SQLite CRUD)
- [ ] `chatdbmgr.py` 中新增 `personality_state` 建表逻辑
- [ ] 单元测试：三个模块独立可测

### Phase 2 — 规则 & 配置 (1~2 天)

- [ ] `prompt/personality_v2/stimulus_rules.yaml` + 规则加载器
- [ ] `prompt/personality_v2/affinity_rules.yaml` + 规则加载器
- [ ] 更新 `prompt/prompts/personality/*.yaml` 为 v2 格式
- [ ] `StimulusAnalyzer` 实现（消息 → 刺激向量）
- [ ] 规则热重载端点 `POST /api/personality/rules/reload`

### Phase 3 — 集成 (1~2 天)

- [ ] `prompt/personality_v2/builder.py` — `PersonalityPromptBuilder`
- [ ] 修改 `prompt/engine.py` — `PromptEngine` 集成 v2
- [ ] 修改 `app.py` — 初始化 v2 系统 + 注册 API 端点
- [ ] 修改 `plugins/builtin/models_plugin.py` — POST_PROCESS 中触发 on_interaction
- [ ] 集成测试：完整对话链路

### Phase 4 — 兼容 & 清理 (1 天)

- [ ] 旧版 `prompt/personality.py` 保留为 `v1_legacy.py`
- [ ] `prompt/__init__.py` 同时导出 v1 和 v2，标记 v1 为 deprecated
- [ ] SubApp `self_evolution` 迁移到 v2
- [ ] 文档更新

### Phase 5 — 高级特性（后续迭代）

- [ ] 多语言刺激检测（当前仅中文）
- [ ] LLM 辅助刺激分析（当简单规则匹配精度不够时回退到 LLM）
- [ ] 人格进化：底层基线参数的长期缓慢漂移
- [ ] 跨会话情绪连续性（同一用户多设备共享）

---

## 十二、与旧版 v1 的对比

| 维度 | v1 (当前) | v2 (提案) |
|------|-----------|-----------|
| **情绪维度** | 4 维独立浮点，无联动 | 5 维向量 (JOLY/SORW/ANGR/FEAR) + META 调和 |
| **情绪互作用** | 无 | META 反馈回路，情绪之间互相影响 |
| **情绪粒度** | 3 档 (高/中/低) | 连续值 + 7 种组合心境 |
| **亲和力** | 每次 +0.02，单向不可逆 | 0~100 多行为驱动，冷却/防刷/反弹保护 |
| **习性** | 静态 YAML 列表 | 先天 + 被动学习 + 衰减遗忘 + 容量控制 |
| **持久化** | 无 | SQLite 按 uid 独立状态 |
| **多用户** | 全局单例 | uid 隔离 |
| **规则可配置** | 硬编码在代码中 | YAML 文件，可热重载 |
| **API 端点** | 宣传但未实现 | Phase 3 时一并补全 |
| **测试性** | 3 个测试函数 | 每个模块独立可测 |
| **核心代码量** | ~300 行 | ~800 行 |
