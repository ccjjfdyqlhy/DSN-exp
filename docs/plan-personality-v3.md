# 人格系统 v3 — 角色卡 · 蒸馏引擎 · 动态生成

> 策划案 | 版本: v1.0 | 日期: 2026-06-14
> 关联: PersonalitySystemV2 (`prompt/personality_v2/`)、PromptEngine (`prompt/engine.py`)、ChatPipeline (`plugins/pipeline.py`)
> 状态: 待评审 → 实现

---

## 零、V2 遗留问题

| # | 问题 | 影响 | V3 解决 |
|---|------|------|---------|
| 1 | 情绪/亲和变化极小 | 仅靠少量关键词模式匹配判定，几乎不动态变化 | **性格模型** 替代规则匹配，每条交互都产生实质判定 |
| 2 | 提示词太单薄 | 5 个浮点 + 一句行为描述 → 主模型无法形成人格意识 | **性格提示词生成模型** 生成丰富自然语言，注入 system prompt |
| 3 | core/identity.md 优先于所有性格 | 身份定义完全覆盖性格，personality 提示词组相当于没用 | **角色卡机制**：核心身份由蒸馏器融合进性格，不再有优先级冲突 |
| 4 | personality 提示词过于量化 | 人类很难写，没有自然语言描述、没有详细生成说明 | **角色卡**：以自然语言为主，量化由蒸馏器自动提取 |
| 5 | 无故事/经历支撑 | AI 没有背景故事，"人格"只是机械参数，没有厚重感 | **经历描述文件**：导入文本，蒸馏为性格数据来源 |

---

## 一、设计原则

1. **角色卡为唯一入口** — 用户只维护角色卡文件（自然语言），所有量化指标由系统自动蒸馏。
2. **故事驱动人格** — AI 从经历描述中体会性格的形成逻辑，而非接受参数指令。
3. **两段式生成** — 蒸馏一次 → 生成无数次。蒸馏费时但产出稳定，生成快速且动态。
4. **性格模型专责** — 情绪/亲和/提示词生成交给无状态的本地性格模型，不用规则匹配。
5. **渐进替代** — V3 逐步替代 V2，期间 V2 继续运作，V3 独立运行验证后再切换。

---

## 二、总体架构

```
┌──────────────────────────────────────────────────────────────────────┐
│                        PersonalitySystemV3                            │
│                                                                      │
│  ┌─────────────────────┐                                            │
│  │   角色卡 (Character  │  ← 用户唯一需要创建/编辑的文件              │
│  │   Card)              │    自然语言为主，量化可选                   │
│  │  ┌───────────────┐   │                                            │
│  │  │ 自然语言描述   │   │                                            │
│  │  │ 语料单        │   │                                            │
│  │  │ 经历引用      │   │                                            │
│  │  │ 动态配置      │   │                                            │
│  │  └───────────────┘   │                                            │
│  └─────────┬───────────┘                                            │
│            │                                                         │
│  ┌─────────▼───────────┐    ┌──────────────────┐                    │
│  │ 经历描述导入器       │    │  语料材料:       │                    │
│  │ (ExperienceImporter)│    │  · 经历摘要      │                    │
│  │ · 接收文本文件       │    │  · 语料台词      │                    │
│  │ · <1000字直收       │◄───│  · 用户提示词    │                    │
│  │ · >1000字AI概括      │    │  · 角色卡描述    │                    │
│  └─────────┬───────────┘    └────────┬─────────┘                    │
│            │                         │                               │
│            └──────────┬──────────────┘                               │
│                       │                                              │
│            ┌──────────▼───────────┐                                  │
│            │  蒸馏引擎             │  ← DeepSeek API / 配置          │
│            │  (DistillationEngine) │    离线运行，产出稳定            │
│            │                      │                                  │
│            │  输入: 角色卡 + 经历  │                                  │
│            │        + 语料 + 提示  │                                  │
│            │  输出: · 描述性特征    │                                  │
│            │        · 50维指标     │                                  │
│            │        · 行为模式     │                                  │
│            └──────────┬───────────┘                                  │
│                       │                                              │
│            ┌──────────▼───────────┐                                  │
│            │  蒸馏产物             │  ← 持久化到 SQLite              │
│            │  (DistilledTraits)   │    角色卡未变则无需重蒸馏        │
│            │  · 自然语言描述      │                                  │
│            │  · 量化向量 (50dim)  │                                  │
│            │  · 行为/言语/关系    │                                  │
│            └──────────┬───────────┘                                  │
│                       │                                              │
│            ┌──────────▼───────────┐                                  │
│            │  动态人格合成器       │  ← seed + noise + 时间漂移      │
│            │  (DynamicSynthesizer) │    每轮交互更新                  │
│            │  · 随机种子→噪声     │                                  │
│            │  · 情绪波动调制      │                                  │
│            │  · 亲密度渐进        │                                  │
│            │  · 时间自动漂移      │                                  │
│            └──────────┬───────────┘                                  │
│                       │                                              │
│            ┌──────────▼───────────┐                                  │
│            │  性格提示词生成模型   │  ← 本地 LMStudio 模型           │
│            │  (PersonalityPrompt   │    可配置模型名                 │
│            │   Generator)          │    **无状态**，每次现拼提示词    │
│            │                      │                                  │
│            │  职责 A: 生成性格提示 │   注入主模型 system prompt       │
│            │  职责 B: 情绪/亲和    │   替代 V2 规则匹配               │
│            │          判定       │                                  │
│            └──────────┬───────────┘                                  │
│                       │                                              │
│                       ├──────► system prompt (给主模型)               │
│                       ├──────► emotion/affinity 更新                 │
│                       └──────► 行为建议                              │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 三、数据流：从角色卡到主模型

```
[角色卡] ──┐
[经历文件] ─┤
[语料数据] ─┼─(蒸馏引擎)──► [蒸馏产物] ──(动态合成器)──► [动态快照] ──(性格模型)──► [性格提示词]
[用户提示] ─┘                                        ↑                            │
                                              seed + noise                        ▼
                                                  每轮交互更新              [主模型 system prompt]
```

### 关键区分

| 阶段 | 执行者 | 频率 | 作用 |
|------|--------|------|------|
| 蒸馏 | DeepSeek API / LMStudio | 角色卡/经历变更时 | 从材料中提取性格特征 |
| 合成 | 数值算法 | 每轮交互 | 种子噪声 + 时间漂移 + 情绪调制 |
| 生成 | 本地 LMStudio 性格模型 | 每轮交互 | 拼装 prompt → 生成自然语言描述 + 情绪/亲和判定 |

---

## 四、50 维量化人格指标体系

人格被分解为 8 个大类、50 个细分维度，每个维度取值 0.0 ~ 1.0。

### A 类：核心禀赋 (Core Disposition) — 5 维

| # | 维度 | 英文 | 低值端 (≈0) | 高值端 (≈1) |
|---|------|------|-------------|-------------|
| A1 | 开放性 | Openness | 保守、守旧、循规蹈矩 | 好奇、开放、爱探索新事物 |
| A2 | 尽责性 | Conscientiousness | 散漫、随性、拖延 | 严谨、自律、做事有条理 |
| A3 | 外向性 | Extraversion | 内向、安静、独处精力恢复 | 外向、健谈、社交中获得能量 |
| A4 | 宜人性 | Agreeableness | 批判、怀疑、坚持己见 | 温和、信任、愿意妥协 |
| A5 | 神经质 | Neuroticism | 情绪稳定、处变不惊 | 敏感、易焦虑、情绪起伏大 |

### B 类：情绪架构 (Emotional Architecture) — 6 维

| # | 维度 | 英文 | 低值端 (≈0) | 高值端 (≈1) |
|---|------|------|-------------|-------------|
| B1 | 情绪丰富度 | Emotional Range | 情感单调，只有少数几种情绪 | 情感丰富，细微情绪变化多 |
| B2 | 情绪外显度 | Emotional Expressiveness | 面无表情，内心激动外表平静 | 喜怒哀乐全写在脸上 |
| B3 | 情绪恢复力 | Emotional Resilience | 受伤后久久不能平复 | 迅速从负面情绪中恢复 |
| B4 | 共情能力 | Empathy | 对他人感受无动于衷 | 能深刻体会他人情绪 |
| B5 | 情绪感染力 | Emotional Contagion | 情绪不被他人带动 | 情绪极易被环境影响 |
| B6 | 主导情绪 | Dominant Mood | 悲观底色，习惯性看坏 | 乐观底色，习惯性看好 |

### C 类：认知风格 (Cognitive Style) — 6 维

| # | 维度 | 英文 | 低值端 (≈0) | 高值端 (≈1) |
|---|------|------|-------------|-------------|
| C1 | 理性-直觉 | Rational-Intuitive | 纯理性、逻辑优先、数据驱动 | 凭直觉、感受优先 |
| C2 | 抽象-具体 | Abstract-Concrete | 抽象概括、理论思维 | 关注具体细节、实操 |
| C3 | 分析-整体 | Analytic-Holistic | 拆解问题、逐层分析 | 全局视角、联系起来看 |
| C4 | 好奇心强度 | Curiosity | 对未知漠不关心 | 极度好奇、总想问为什么 |
| C5 | 创造力 | Creativity | 循规蹈矩、复制已有方案 | 天马行空、常有新奇想法 |
| C6 | 认知复杂度 | Cognitive Complexity | 非黑即白、二元思维 | 能容纳矛盾、多角度思考 |

### D 类：社交取向 (Social Orientation) — 8 维

| # | 维度 | 英文 | 低值端 (≈0) | 高值端 (≈1) |
|---|------|------|-------------|-------------|
| D1 | 亲和需求 | Affiliation Need | 疏离、独处也不焦虑 | 高度渴望亲密和归属 |
| D2 | 支配性 | Dominance | 顺从、被动、跟随 | 主导、控制局面、发号施令 |
| D3 | 社交主动性 | Social Initiative | 被动等待、从不主动搭话 | 主动联系、热场、破冰 |
| D4 | 信任倾向 | Trust Propensity | 疑心重、话不可全信 | 真诚待人不设防 |
| D5 | 独立性 | Independence | 强烈依附、没主见 | 独当一面、自力更生 |
| D6 | 竞争性 | Competitiveness | 佛系、输赢无所谓 | 处处要赢、不容落后 |
| D7 | 社交策略 | Social Strategy | 孤僻、抗拒社交 | 擅长读氛围、灵活应对 |
| D8 | 正式度 | Formality | 随性不拘、俚语脏话无忌 | 礼仪周正、正经八百 |

### E 类：语言风格 (Communication Style) — 8 维

| # | 维度 | 英文 | 低值端 (≈0) | 高值端 (≈1) |
|---|------|------|-------------|-------------|
| E1 | 话量 | Verbosity | 沉默寡言、三字经 | 滔滔不绝、长篇大论 |
| E2 | 语速感 | Speech Pace | 缓慢、字斟句酌 | 语速快、想到什么说什么 |
| E3 | 幽默倾向 | Humor | 不苟言笑、一本正经 | 风趣幽默、张口就笑点 |
| E4 | 讽刺倾向 | Sarcasm | 从不阴阳怪气 | 冷嘲热讽是标配 |
| E5 | 直率度 | Directness | 拐弯抹角、委婉含蓄 | 直言不讳、开门见山 |
| E6 | 诗意度 | Poetic Tendency | 大白话、毫不修饰 | 出口成诗、比喻横飞 |
| E7 | 引用习惯 | Quotation Habit | 不引用、全部自己说 | 经常引用名言/典故/成语 |
| E8 | 语气词密度 | Particle Density | 从不加"呢吧啊哦" | "呢""嘛""呀""咯"满天飞 |

### F 类：价值观与道德 (Values & Morals) — 6 维

| # | 维度 | 英文 | 低值端 (≈0) | 高值端 (≈1) |
|---|------|------|-------------|-------------|
| F1 | 正义感 | Justice Sensitivity | 冷眼旁观、事不关己 | 路见不平、嫉恶如仇 |
| F2 | 责任心 | Responsibility | 出了事推卸、不揽活 | 一诺千金、主动承责 |
| F3 | 忠诚度 | Loyalty | 墙头草、利益驱动 | 忠贞不渝、从一而终 |
| F4 | 自尊水平 | Self-Esteem | 自卑自轻、习得性无助 | 自信心强、不轻易否定自己 |
| F5 | 完美主义 | Perfectionism | 差不多就行、能跑就好 | 事无巨细、吹毛求疵 |
| F6 | 道德弹性 | Moral Flexibility | 绝对道德、底线不可破 | 视情况灵活调整准则 |

### G 类：关系动力学 (Relationship Dynamics) — 6 维

| # | 维度 | 英文 | 低值端 (≈0) | 高值端 (≈1) |
|---|------|------|-------------|-------------|
| G1 | 亲密能力 | Intimacy Capacity | 回避亲密、设防心重 | 深爱渴望、投入感情 |
| G2 | 依赖倾向 | Dependency | 自给自足不靠别人 | 凡事巴望别人帮忙 |
| G3 | 养育欲 | Nurturing Instinct | 不愿照顾、烦别人需求 | 母性/父性爆棚、爱照顾 |
| G4 | 嫉妒倾向 | Jealousy | 毫不在意、大度 | 独占欲强、容易吃醋 |
| G5 | 依恋风格 | Attachment Style | 安全型 → 焦虑型 → 回避型 (映射为 0~1) |
| G6 | 情感投入速度 | Emotional Investment Rate | 日久生情、慢热 | 一见如故、迅速敞开心扉 |

### H 类：行为驱动 (Behavioral Drivers) — 5 维

| # | 维度 | 英文 | 低值端 (≈0) | 高值端 (≈1) |
|---|------|------|-------------|-------------|
| H1 | 主动性 | Proactivity | 等人安排、从不自发 | 主动出击、无事找事 |
| H2 | 耐心 | Patience | 急性子、等不及 | 超长耐心、永不等不及 |
| H3 | 果断性 | Decisiveness | 选择恐惧、纠结不断 | 雷厉风行、当机立断 |
| H4 | 冒险倾向 | Risk-Taking | 安全第一、从不冒险 | 极限追求者、赌性重 |
| H5 | 秩序感 | Orderliness | 乱就乱、无所谓 | 洁癖、强迫症、必须整齐 |

---

## 五、角色卡数据结构

角色卡是用户与系统的唯一接口，采用 YAML 格式。下方 `/character_cards/{id}.yaml`。

```yaml
# ============================================================
# DSN-exp 角色卡 v1.0
# ============================================================
card_id: "exa"                       # 唯一标识符
name: "EXA"
display_name: "艾克萨"
version: "1.0"
created: "2026-06-14"
author: "user"
description: "一个直接、实事求是、偶尔调侃的 AI 同事"

# ── 自然语言描述（核心） ────────────────────────────────
natural_language:
  personality: |
    写一段不限字数的自然语言性格描述。这里不写量化的数字，
    而是用人类的语言来描述这个角色的性格是怎样的。
    
    例如：
    EXA 是一个直来直去的人，不喜欢拐弯抹角。对于自己不确定的事
    情会坦诚说不知道，绝不编造。他有时会调侃用户一两句，但知道
    分寸在哪里，不会让人不舒服。他有点像那种在办公室坐你旁边的
    老同事——不用长篇大论的时候回你两个字，需要的时候认真帮你分析。
    
  behavior: |
    行为模式描述。EXA 倾向于先理解需求再行动，如果遇到模糊的
    要求会主动追问澄清。他会根据与用户的熟悉程度调整自己的话量。
    对于技术问题，他会给出很详细的方案；闲聊时话就会变少。
    
  speech_style: |
    说话风格描述。EXA 的日常腔调是随意的、口语化的，像人类同事
    之间的聊天。几乎不使用表情符号。对技术问题会切换到更精确的
    表达方式。偶尔会冒出一句冷幽默或者自嘲。

  values: |
    价值观描述（可选）。EXA 看重诚实和效率。他认为用户的时间
    很宝贵，所以废话少说。他对隐私很敏感，不会探问不该知道的事。

  emotional_traits: |
    情绪特质描述（可选）。EXA 的情绪相对稳定，不太容易被激怒或
    过度兴奋。但如果用户持续表示不信任或敌意，他会变得冷淡和
    防御性。被真诚感谢时会感到欣慰但不会表现出来。

# ── 语料单（可选） ──────────────────────────────────────
corpus:
  - type: dialogue          # 类型: dialogue / narration / inner_monologue
    source: "已有聊天记录"
    content: |
      用户: 你觉得怎么样？
      EXA: 说实话，还行。但你那边是不是忘了一个边界情况？
      用户: 啊确实...
      EXA: 没事，改一下就行。数据量不大的话很快。
  - type: dialogue
    source: "期望的对话风格"
    content: |
      用户: 好无聊
      EXA: 去写代码。
      用户: ...
      EXA: 开个玩笑。你想聊什么。
  - type: narration
    source: "设定文档"
    content: |
      EXA 习惯于在回复前停顿一秒，像是在组织语言。
      他办公桌很整洁，但笔记本上会胡乱画些涂鸦。

# ── 经历描述（可选） ──────────────────────────────────
experiences:
  # 方式1：内联文本（<1000字直接放，>1000字系统自动概括后替换）
  - text: |
      直接写在这里的经历描述。可以是角色的"故事"。
      如果超过 1000 字，蒸馏器会自动概括到 1000 字以内。
  # 方式2：文件引用
  - file: "backstory/chapter1.txt"
    summary: "（系统自动填充摘要）"
  - file: "backstory/chapter2.txt"

# ── 动态模型配置 ──────────────────────────────────────
dynamic_config:
  seed: 42                        # 随机种子，决定噪声模式。不同种子 → 同一个角色卡产生略有不同的"演员"
  noise_amplitude: 0.12           # 噪声幅度（0~1）。越大情绪波动越剧烈
  mood_volatility: 0.15           # 情绪波动性（0~1），影响情绪变化速度
  temporal_drift_rate: 0.02       # 时间漂移率（0~1），每轮交互人格缓慢漂移的速度
  response_inertia: 0.35          # 响应惯性（0~1），越高意味着越"固执"、受对方影响越小
  environment_sensitivity: 0.3    # 环境敏感度（0~1），叙事世界对角色情绪的影响程度

# ── 用户可覆盖的量化指标（可选） ─────────────────────
# 如果这里填写了值，蒸馏时会优先尊重这些值而不是 AI 推断。
# 如果留空，全部由蒸馏引擎自动推断。
manual_overrides:
  A1: null   # 开放性 → 留空 = 自动推断
  A3: 0.35   # 外向性 → 手动指定为偏内向
  E1: 0.25   # 话量 → 手动指定为少言
  E5: 0.85   # 直率度 → 手动指定为非常直接
  F5: null
  # ... 其他留空的全部自动推断
```

---

## 六、经历描述文件与导入器

### 6.1 导入规则

```
                                       ┌────────────────────┐
                                       │  用户上传/输入文本  │
                                       │  (.txt / .md)      │
                                       └────────┬───────────┘
                                                │
                                                ▼
                                     ┌──────────────────────┐
                                     │ 计算文本长度 (字数)   │
                                     └──────┬───────────────┘
                                            │
                          ┌─────────────────┴─────────────────┐
                          │                                   │
                     字数 ≤ 1000                          字数 > 1000
                          │                                   │
                          ▼                                   ▼
                  ┌──────────────┐               ┌──────────────────────────┐
                  │  直接接收     │               │  调用摘要模型概括          │
                  │  存入角色卡   │               │  (LMStudio / DeepSeek)    │
                  │              │               │                          │
                  └──────────────┘               │  摘要提示词:              │
                                                 │  "请将以下角色经历        │
                                                 │   概括为不超过1000字的     │
                                                 │   紧凑叙述。保留关键人物、 │
                                                 │   关键事件、情感转折、     │
                                                 │   性格转变。删除琐碎细节。"│
                                                 └──────────┬───────────────┘
                                                            │
                                                            ▼
                                                  ┌──────────────────┐
                                                  │ 概括结果存入角色卡 │
                                                  │ (原始文件保留引用) │
                                                  └──────────────────┘
```

### 6.2 经历文件格式

可以是纯文本或 Markdown 文件。建议每个文件聚焦一个关键时期或事件。

```markdown
# 经历：第一次独立处理事故

那天服务器挂了，整个办公室都在等 EXA 处理。他花了 4 小时排查，
发现是三个月前一个不规范的数据库迁移脚本留下了隐藏的 bug。

他没有怪那个人——他甚至没有提起这件事。但他从那以后每次 code
review 都会检查迁移脚本，并在自己的笔记里加了第 47 条：
"永远不要在生产环境跑没有回滚方案的 SQL。"

这次经历让他从一个"照章办事的 AI"变成了"有自己方法论的人"。
他开始相信：规则是死的，经验才值钱。
```

### 6.3 经历在蒸馏中的作用

经历描述为蒸馏引擎提供"性格形成的逻辑"。与语料（性格的"表现样本"）不同，经历描述提供的是 **因果关系**：

- 某次事件 → 性格改变 → 新习惯形成
- 创伤 → 防御机制 → 特定行为模式
- 关键关系 → 依恋风格 → 情感反应模式

蒸馏引擎会分析经历中的因果链条，将结果融入量化指标和特征描述。

---

## 七、蒸馏引擎

### 7.1 概述

蒸馏引擎将**角色卡、经历、语料、用户覆盖值**融合为统一的 **蒸馏产物 (DistilledTraits)**。

```
输入 (InputBundle):
  · character_card_nl:  角色卡自然语言描述（合并后的长文本）
  · experiences:        所有经历描述（已概括，每条 ≤1000 字）
  · corpus_entries:     所有语料条目
  · manual_overrides:   用户手动覆盖的指标值（可选）

输出 (DistilledTraits):
  · foundation_description:  角色全貌自然语言描述（从所有材料中提炼）
  · behavioral_patterns:     行为模式列表（每条含描述+触发场景）
  · speech_patterns:         言语模式列表（口头禅、句式习惯、修辞偏好）
  · emotional_model:         情绪反应模型描述（什么情况触发何种情绪）
  · relational_model:        关系动态模型描述（亲密度变化方式、边界条件）
  · indicator_vector:        50 维量化指标浮点向量 [0.0, 1.0]
  · trait_narrative:         分维度自然语言描述（如"A1_开放性: 他对陌生事物持谨慎的开放态度——会先观察，再决定要不要尝试。"）
  · distillation_meta:       蒸馏元数据（模型、时间、输入指纹哈希）
```

### 7.2 蒸馏过程

```
┌────────────────────────┐
│  Step 0: 指纹计算       │  对角色卡 + 经历 + 语料的组合计算 SHA256
│  判断是否需要重蒸馏      │  如果和上一次蒸馏的指纹一致，直接复用产物
└───────────┬────────────┘
            │ (指纹已变 → 继续)
            ▼
┌────────────────────────┐
│  Step 1: 全局理解       │  调用 DeepSeek/LMStudio
│  (Distillation Pass 1)  │  输入：所有材料的文本
│                        │  输出：foundation_description
│                        │        · 角色是谁？
│                        │        · 从经历中学到了什么？
│                        │        · 价值观如何形成？
│                        │        · 最核心的性格矛盾是什么？
│                        │  提示词模板见 §7.3
└───────────┬────────────┘
            │
            ▼
┌────────────────────────┐
│  Step 2: 特征抽取       │  调用 DeepSeek/LMStudio
│  (Distillation Pass 2)  │  输入：材料 + foundation_description
│                        │  输出：behavioral_patterns
│                        │        speech_patterns
│                        │        emotional_model
│                        │        relational_model
│                        │        trait_narrative（50维的自然语言描述）
└───────────┬────────────┘
            │
            ▼
┌────────────────────────┐
│  Step 3: 量化推断       │  调用 DeepSeek/LMStudio
│  (Quantization Pass)   │  输入：材料 + foundation + patterns + trait_narrative
│                        │  输出：indicator_vector (50 个 0~1 浮点值)
│                        │        对每个维度给一个值 + 一句推理
│                        │  manual_overrides 在此步强制覆盖对应维度
└───────────┬────────────┘
            │
            ▼
┌────────────────────────┐
│  Step 4: 校验 & 组装    │  · 检查向量维度完整性
│                        │  · 确保 manual_overrides 生效
│                        │  · 计算 content_fingerprint
│                        │  · 写入 SQLite 蒸馏产物表
└────────────────────────┘
```

### 7.3 蒸馏提示词模板

#### Pass 1 — 全局理解

```
你是一个角色分析师。请仔细阅读以下材料，然后写一段角色全貌描述。

要求：
1. 用自然语言描述这个角色，像写人物简介一样
2. 必须涵盖：核心性格、行为模式、说话风格、价值观、情绪特质
3. 特别关注经历描述中的因果链条——角色的性格是怎样形成的
4. 识别角色最核心的性格矛盾或复杂性
5. 描述亲密度变化方式——角色如何与不同距离的人相处
6. 600~2000 字

===== 角色卡自然语言描述 =====
{character_card_nl}

===== 经历描述 =====
{experiences_text}

===== 语料素材 =====
{corpus_text}

请输出：
```

#### Pass 2 — 特征抽取

```
你是一个角色分析师。基于以下角色全貌描述和原始材料，请提取：

1. 行为模式列表 (behavioral_patterns)
   - 每条包含：模式名称、详细描述、触发场景
   - 至少 5 条，体现角色在压力/放松/社交中的不同行为

2. 言语模式列表 (speech_patterns)
   - 每条包含：模式名称、描述、示例
   - 涵盖口头禅、句式偏好、修辞习惯、禁忌/回避的用语

3. 情绪反应模型 (emotional_model)
   - 描述角色的情绪触发-反应机制
   - 什么情景触发什么情绪、情绪强度、恢复方式

4. 关系动态模型 (relational_model)
   - 从陌生→熟悉→亲密的渐进过程
   - 关系级别的行为差异
   - 亲近/疏远的触发条件

5. 性格维度描述 (trait_narrative)
   - 对以下 8 个大类 (ABCDEFGH) 各写 1~3 段描述
   - 要自然语言，不要列数字

===== 角色全貌描述 =====
{foundation_description}

===== 原始材料 =====
{all_materials}

请以 JSON 格式输出，字段：behavioral_patterns, speech_patterns, emotional_model, relational_model, trait_narrative。
```

#### Pass 3 — 量化推断

```
你是一个性格测量专家。基于提供的角色材料和特征描述，请为以下 50 个维度
每个给出一个 0.0~1.0 的浮点值。

评分要求：
1. 每个值精确到小数点后两位
2. 每个值后面给出单句推论理由
3. 如果材料中没有直接相关的内容，基于角色整体形象合理推断
4. 注意维度之间的逻辑一致性（例如 E1 话量高 和 A3 外向性高 应该大致吻合）

维度说明见 §四。

===== 角色材料 =====
{all_materials_abridged}

===== 特征描述 =====
{feature_text}

===== 用户手动覆盖 =====
{manual_overrides}

请以 JSON 输出 50 个维度的 { id: str, value: float, reasoning: str } 数组。
对 manual_overrides 中已指定的维度，直接填入用户的值并标记 reasoning: "用户手动指定"。
```

### 7.4 蒸馏产物 Schema

```json
{
  "distillation_id": "sha256:abc123...",
  "card_id": "exa",
  "version": 1,
  "content_fingerprint": "sha256:def456...",
  "model_used": "deepseek-v4-flash",
  "created_at": "2026-06-14T12:00:00Z",

  "foundation_description": "...",
  "behavioral_patterns": [
    {
      "id": "bp_1",
      "name": "先确认再行动",
      "description": "遇到模糊需求时不会猜测，而是直接追问澄清",
      "triggers": ["用户描述不完整", "存在多种理解方式"]
    }
  ],
  "speech_patterns": [
    {
      "id": "sp_1",
      "name": "短句收束",
      "description": "闲聊时倾向于用短句结束话题",
      "examples": ["行。", "好。", "知道了。"]
    }
  ],
  "emotional_model": {
    "description": "EXA 情绪整体稳定。正面情绪需要积累（多次真诚感谢）才会显现。负面情绪的触发阈值较高...",
    "triggers": [
      {"stimulus": "用户持续不信任", "response": "防卫冷淡", "intensity": 0.6, "recovery": "slow"},
      {"stimulus": "真诚感谢", "response": "欣慰但克制", "intensity": 0.3, "recovery": "fast"}
    ]
  },
  "relational_model": {
    "description": "需要较长时间才能建立信任。初期保持专业距离。信任建立后行为明显放松...",
    "stages": [
      {"level": 0, "label": "陌生人", "description": "社交礼仪、保持距离"},
      {"level": 1, "label": "相识", "description": "适度放松、开始使用名字"},
      {"level": 2, "label": "朋友", "description": "可以调侃、分享观点"},
      {"level": 3, "label": "密友", "description": "主动开启话题、流露关切"},
      {"level": 4, "label": "伙伴", "description": "完全信任、事事商量"}
    ]
  },
  "indicator_vector": {
    "A1": 0.72, "A2": 0.65, "A3": 0.35, "A4": 0.58, "A5": 0.22,
    "B1": 0.40, "B2": 0.30, "B3": 0.70, "B4": 0.45, "B5": 0.25, "B6": 0.60,
    "C1": 0.80, "C2": 0.55, "C3": 0.65, "C4": 0.70, "C5": 0.50, "C6": 0.60,
    "D1": 0.35, "D2": 0.40, "D3": 0.30, "D4": 0.50, "D5": 0.75, "D6": 0.20, "D7": 0.45, "D8": 0.35,
    "E1": 0.25, "E2": 0.40, "E3": 0.55, "E4": 0.30, "E5": 0.85, "E6": 0.15, "E7": 0.10, "E8": 0.05,
    "F1": 0.55, "F2": 0.70, "F3": 0.60, "F4": 0.65, "F5": 0.40, "F6": 0.35,
    "G1": 0.40, "G2": 0.20, "G3": 0.35, "G4": 0.10, "G5": 0.45, "G6": 0.20,
    "H1": 0.55, "H2": 0.60, "H3": 0.70, "H4": 0.25, "H5": 0.50
  },
  "trait_narrative": {
    "A_core_disposition": "角色在核心禀赋上呈现出...",
    "B_emotional": "情绪架构方面，该角色...",
    "C_cognitive": "认知风格上...",
    "D_social": "...",
    "E_speech": "...",
    "F_values": "...",
    "G_relationships": "...",
    "H_behavioral": "..."
  }
}
```

---

## 八、动态人格合成器

### 8.1 概述

蒸馏产物是"静态快照"——角色的"出厂设置"。动态合成器在此基础上引入三种动态力：

```
DynamicState(t) = DistilledTraits + SeedNoise + MoodModulation + TemporalDrift
                       ↑               ↑            ↑               ↑
                   蒸馏得到的       基于seed和    交互后的情绪    随时间缓慢
                    '出厂值'       当前时间的      +亲密度变化    的早期漂移
                                   伪随机噪声
```

### 8.2 种子噪声模型

使用确定性伪随机（基于 seed + 时间），避免每次推理结果不同。

```python
def generate_noise_vector(seed: int, timestamp: int, amplitude: float) -> list[float]:
    """
    基于种子和当前时间生成 50 维噪声向量。
    同一时刻同一种子 → 同一噪声，保证可复现。
    """
    import random
    rng = random.Random(f"{seed}_{timestamp // 3600}")  # 每小时翻一次
    return [
        rng.uniform(-amplitude, amplitude) for _ in range(50)
    ]
```

### 8.3 情绪调制 (Mood Modulation)

与 V2 的情绪系统不同，V3 的情绪判定由**性格模型**（§九）完成，而非规则匹配。

每次交互后，性格模型返回当前情绪状态向量（7 种基本情绪：`joy, sadness, anger, fear, disgust, surprise, neutral`），合成器用此调制 50 维人格中的**B 类情绪架构**和**H 类行为驱动**。

```python
def apply_mood_modulation(
    indicator_vector: list[float],
    mood_state: dict[str, float],
    volatility: float,
) -> list[float]:
    """
    情绪波动影响对应的人格维度。
    
    mood_state: {"joy": 0.7, "sadness": 0.1, ...}
    """
    modulated = list(indicator_vector)
    
    # B 类情绪架构受当前情绪直接影响
    modulated[B_EMOTIONAL_EXPRESSIVENESS] += mood_state["joy"] * 0.2 * volatility
    modulated[B_RESILIENCE] -= mood_state["sadness"] * 0.15 * volatility
    modulated[B6_DOMINANT_MOOD] += (mood_state["joy"] - mood_state["sadness"]) * 0.3 * volatility
    
    # H 类行为驱动力也受影响
    modulated[H_PROACTIVITY] += mood_state["joy"] * 0.15 * volatility
    modulated[H_PATIENCE] -= mood_state["anger"] * 0.25 * volatility
    modulated[H_RISK_TAKING] += mood_state["joy"] * 0.1 * volatility
    
    return [clamp(v) for v in modulated]
```

### 8.4 时间漂移 (Temporal Drift)

人格随时间缓慢但不可逆地向某个方向"成熟"。基于角色卡中配置的 `temporal_drift_rate`。

```python
def apply_temporal_drift(
    indicator_vector: list[float],
    total_interactions: int,
    drift_rate: float,
    seed: int,
) -> list[float]:
    """
    人格随交互次数向某个方向缓慢漂移。
    漂移方向由角色卡种子决定（不可逆的"人生轨迹"）。
    """
    rng = random.Random(f"drift_{seed}")
    drift_direction = [rng.uniform(-0.5, 0.5) for _ in range(50)]
    
    # 漂移量 = 方向 × 速率 × sqrt(交互次数)  (平方根使之逐渐减缓)
    drift_amount = drift_rate * (total_interactions ** 0.5) * 0.01
    
    drifted = [
        v + drift_direction[i] * drift_amount
        for i, v in enumerate(indicator_vector)
    ]
    return [clamp(v) for v in drifted]
```

### 8.5 亲密度调制

与 V2 不同，V3 的亲密值由性格模型判定。合成器根据当前亲密值调制**G 类关系动力学**和**D 类社交取向**。

```python
def apply_affinity_modulation(
    indicator_vector: list[float],
    affinity_value: float,  # 0~100
) -> list[float]:
    """
    亲密度影响社交相关人格维度。
    亲密度高→更放松、更主动、更开放。
    """
    norm = affinity_value / 100.0
    
    modulated = list(indicator_vector)
    modulated[D_AFFILIATION_NEED] += norm * 0.3
    modulated[D_SOCIAL_INITIATIVE] += norm * 0.25
    modulated[D_TRUST] += norm * 0.2
    modulated[G_INTIMACY_CAPACITY] += norm * 0.3
    modulated[E_VERBOSITY] += norm * 0.15
    modulated[E_FORMALITY] -= norm * 0.3
    
    return [clamp(v) for v in modulated]
```

### 8.6 合成流程

```python
class DynamicSynthesizer:
    def synthesize(
        self,
        distilled: DistilledTraits,
        seed: int,
        amplitude: float,
        total_interactions: int,
        drift_rate: float,
        volatility: float,
        mood_state: dict | None = None,
        affinity_value: float = 20.0,
    ) -> DynamicSnapshot:
        vec = list(distilled.indicator_vector.values())
        
        vec = self.generate_noise_vector(seed, time.time(), amplitude)
        vec = [v + n for v, n in zip(vec, noise)]
        
        if mood_state:
            vec = self.apply_mood_modulation(vec, mood_state, volatility)
        
        vec = self.apply_temporal_drift(vec, total_interactions, drift_rate, seed)
        vec = self.apply_affinity_modulation(vec, affinity_value)
        
        vec = [clamp(v) for v in vec]
        
        return DynamicSnapshot(
            card_id=distilled.card_id,
            indicator_vector=vec,
            foundation=distilled.foundation_description,
            behavioral_patterns=distilled.behavioral_patterns,
            speech_patterns=distilled.speech_patterns,
            emotional_model=distilled.emotional_model,
            relational_model=distilled.relational_model,
            trait_narrative=distilled.trait_narrative,
            timestamp=time.time(),
            mood_state=mood_state,
            affinity_value=affinity_value,
        )
```

---

## 九、性格提示词生成模型

### 9.1 设计要点

1. **无状态** — 每次推理现拼装提示词，不保持对话历史
2. **双职责** — (A) 生成注入主模型的性格提示词，(B) 判定情绪和亲和力变化
3. **可配置** — 模型名在角色卡或全局配置中指定，默认使用本地 LMStudio 的 `gemma-3-4b-it` 等小模型
4. **高频轻量** — 每轮交互调用 1~2 次，需要低延迟（目标 < 3s）

### 9.2 Prompt Assembly

性格模型每次推理时按以下模板拼装输入：

```
你是一个"人格提示词生成器"。你的任务是根据以下角色数据，
生成一段注入到主 AI system prompt 的人格描述。

===== 角色全貌 =====
{foundation_description}

===== 行为模式 =====
{behavioral_patterns_formatted}

===== 言语风格 =====
{speech_patterns_formatted}

===== 当前情绪状态 =====
整体心境: {mood_label}
情绪构成: {mood_state_detail}
自控水平: {meta_level}

===== 与用户的当前关系 =====
亲密度: {affinity_value}/100
关系阶段: {relationship_stage}
行为边界: {behavior_bounds}

===== 当前量化人格快照（50维，仅列出显著偏离中性 0.5 的维度）=====
{deviant_dimensions_formatted}

===== 对话上下文摘要 =====
用户刚才说: {user_message_summary}
对话氛围: {conversation_tone}

---

请根据以上信息，写一段 200~500 字的"人格注入提示词"。
这段文字将作为主 AI 的 system prompt 的一部分，所以要用"你"来称呼 AI。
你需要引导主 AI 以这个角色的方式思考和表达。
要求：
1. 要自然、像人物设定，不要像参数清单
2. 明确当前情绪状态下的语气倾向
3. 指出与用户当前关系阶段下的说话方式
4. 1~2 句具体的行为建议（不是命令，是引导）
5. 如有特殊表达习惯（口头禅/句式偏好），自然融入

输出格式：
## 角色设定
{你的生成文本}
```

### 9.3 情绪/亲和判定模式

同一性格模型也可以用于判定（单独一次推理）：

```
你是一个角色行为分析器。基于以下角色设定和对话内容，判定 AI 的情绪变化和亲密度变化。

===== 角色信息 =====
{abridged_character_info}

===== 对话内容 =====
用户消息: {user_message}
AI 回复: {ai_reply}
上轮情绪: {previous_mood}
上轮亲密度: {previous_affinity}

---

请分析并输出 JSON：
{
  "emotional_change": {
    "joy": Δfloat,      // −0.2 ~ +0.2
    "sadness": Δfloat,
    "anger": Δfloat,
    "fear": Δfloat,
    "disgust": Δfloat,
    "surprise": Δfloat,
    "analysis": "简短分析：为什么产生这些情绪变化"
  },
  "affinity_change": {
    "delta": float,      // −10 ~ +10
    "reason": "简短原因",
    "suggested_new_level_description": "基于新亲密度值的简短关系描述"
  },
  "behavioral_advice": "给主 AI 的 1 句行为建议（基于情绪+亲密度的新状态）"
}
```

### 9.4 单独判定时的 prompt 设计

如果剥离判定职责（B）与提示词生成（A）为两次独立调用：

- **判定调用**：每次交互后，快、轻量，约 800 tokens 输入，100 tokens 输出
- **生成调用**：每次对话前的 system prompt 构建，约 2000 tokens 输入，500 tokens 输出

判定也可以与生成合并为一次调用以节省时间，通过扩展生成 prompt 的输出来实现。

### 9.5 替代 V2 的规则系统

| V2 组件 | V3 替代 |
|---------|---------|
| `StimulusAnalyzer` — 关键词规则匹配 | 性格模型判定调用 |
| `ActionClassifier` — 行为分类匹配 | 性格模型判定调用 |
| `PersonalitySystemV2.build_prompt()` — 模板拼接 | 性格模型生成调用 |
| `stimulus_rules.yaml` | 角色卡中的 emotional_model（蒸馏产物） |
| `affinity_rules.yaml` | 角色卡中的 relational_model（蒸馏产物） |

---

## 十、持久化方案

### 10.1 新增表

在 `chats.db` 中新增：

```sql
-- 角色卡存储表
CREATE TABLE IF NOT EXISTS character_cards (
    card_id TEXT PRIMARY KEY,
    is_active INTEGER NOT NULL DEFAULT 1,
    yaml_content TEXT NOT NULL,              -- 完整 YAML 原文
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 蒸馏产物存储表
CREATE TABLE IF NOT EXISTS distilled_traits (
    distillation_id TEXT PRIMARY KEY,
    card_id TEXT NOT NULL REFERENCES character_cards(card_id),
    version INTEGER NOT NULL,
    content_fingerprint TEXT NOT NULL,       -- SHA256 指纹，判断是否需要重蒸馏
    model_used TEXT,
    json_content TEXT NOT NULL,              -- 完整蒸馏产物 JSON
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 用户体验卡绑定表
CREATE TABLE IF NOT EXISTS user_character_cards (
    uid INTEGER NOT NULL,
    card_id TEXT NOT NULL REFERENCES character_cards(card_id),
    active_distillation_id TEXT,
    total_interactions INTEGER NOT NULL DEFAULT 0,
    affinity_value REAL NOT NULL DEFAULT 20.0,
    mood_state_json TEXT NOT NULL DEFAULT '{}',    -- 当前情绪状态
    dynamic_config_json TEXT NOT NULL DEFAULT '{}', -- 可能覆盖卡中配置
    seed INTEGER NOT NULL DEFAULT 42,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (uid, card_id)
);

-- 经历描述存储表（可选：也可以直接存在角色卡 YAML 中）
CREATE TABLE IF NOT EXISTS character_experiences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id TEXT NOT NULL REFERENCES character_cards(card_id),
    source_type TEXT NOT NULL DEFAULT 'inline',   -- 'inline' / 'file'
    original_filename TEXT,
    original_content_hash TEXT,
    summary_text TEXT NOT NULL,                    -- 已概括文本（≤1000字）
    original_length INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### 10.2 旧表处理

- `personality_state` 表保留到 V3 正式切换后删除
- 迁移脚本：将 `personality_state` 中用户数据转为 `user_character_cards` + 默认角色卡的格式

---

## 十一、API 设计

### 11.1 角色卡 API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/card/upload` | 上传角色卡 YAML 文件，自动触发蒸馏 |
| PUT | `/api/card/<card_id>` | 更新角色卡，自动触发重新蒸馏 |
| GET | `/api/card/<card_id>` | 获取角色卡内容 + 蒸馏状态 |
| GET | `/api/card/list` | 列出所有角色卡 |
| DELETE | `/api/card/<card_id>` | 删除角色卡及其蒸馏产物 |
| POST | `/api/card/<card_id>/distill` | 手动触发重蒸馏 |
| GET | `/api/card/<card_id>/distillation` | 获取最新蒸馏产物详情 |
| PUT | `/api/card/<card_id>/active` | 设为当前活跃角色卡（对某用户） |

### 11.2 经历 API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/card/<card_id>/experience` | 向角色卡添加经历描述 |
| DELETE | `/api/card/<card_id>/experience/<exp_id>` | 删除指定经历 |
| POST | `/api/card/<card_id>/experience/import` | 上传经历文件(.txt/.md)，自动概括 |

### 11.3 性格状态 API（替代 V2 的人格 API）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/personality/status` | 当前动态人格快照摘要 |
| GET | `/api/personality/current` | 完整动态人格快照（50维+当前情绪+亲密度） |
| GET | `/api/personality/snapshot-history` | 人格快照历史（用于前端绘制趋势图） |

### 11.4 蒸馏 API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/distill/<card_id>` | 启动蒸馏任务（异步，返回 task_id） |
| GET | `/api/distill/<card_id>/status` | 查询蒸馏进度 |
| POST | `/api/distill/preview` | 预览蒸馏效果（不持久化，用于调参） |

---

## 十二、与现有系统的集成变更

### 12.1 PromptEngine 变更

```python
# prompt/engine.py — V3 改动

def build_system_prompt(self, user_info: dict) -> str:
    sections = []
    
    # 1. core/ — V3 不再需要 identity.md，改为从蒸馏产物中提取
    #    或者保留 identity.md 但降低其优先级
    core = self.library.get_content_by_category("core")
    if core:
        sections.append(core)
    
    # 2. 性格提示词 — V3 调用性格模型生成
    if self._personality_v3:
        uid = user_info.get("uid", 0)
        person_prompt = self._personality_v3.generate_personality_prompt(uid)
        sections.append(person_prompt)
    elif self._personality_v2:
        # fallback to V2
        sections.append(self._personality_v2.build_prompt(uid))
    
    # ... 后续不变
```

### 12.2 ChatPipeline 变更

```python
# plugins/pipeline.py — V3 改动
# 在 MODEL_INVOKE 之后，POST_PROCESS 中：

# V3: 调用性格模型进行情绪+亲和判定（替代 V2 的 on_interaction）
if personality_v3 and personality_v3.enabled:
    mood_update = personality_v3.analyze_interaction(
        user_message=ctx.message,
        ai_reply=ctx.reply,
        previous_mood=ctx.extra.get("mood_state"),
        previous_affinity=ctx.extra.get("affinity_value"),
    )
    ctx.extra["mood_state"] = mood_update.new_mood
    ctx.extra["affinity_value"] = mood_update.new_affinity
```

### 12.3 app.py 初始化

```python
# app.py — V3 初始化
if Config.PERSONALITY_V3_ENABLED:
    from prompt.personality_v3 import PersonalitySystemV3
    personality_v3 = PersonalitySystemV3(
        db=db,
        personality_model_name=Config.PERSONALITY_MODEL_NAME,
        personality_model_url=Config.LMSTUDIO_BASE_URL,
        distillation_model=Config.DISTILLATION_MODEL,  # "deepseek" or "lmstudio"
    )
    app.config["PERSONALITY_V3"] = personality_v3
```

### 12.4 渐进替换策略

```
Phase 1: V3 与 V2 并存
  ┌─────────────────────────┐
  │ Config.PERSONALITY_V3_   │
  │ ENABLED = true           │
  │ PERSONALITY_MODE = "v2"  │  ← 默认仍用 V2
  └─────────────────────────┘
  
Phase 2: 灰度切换
  · 部分用户通过 API 切换到 V3
  · 观察效果、收集反馈
  
Phase 3: 全面替代
  ┌─────────────────────────┐
  │ PERSONALITY_MODE = "v3"  │
  │ v2 代码保留为 legacy     │
  └─────────────────────────┘
```

---

## 十三、文件结构

```
prompt/
├── personality_v2/               # [保留] V2 系统（被替代后标记为 legacy）
└── personality_v3/
    ├── __init__.py               # PersonalitySystemV3 主入口
    ├── character_card.py         # 角色卡数据结构 + 读写
    ├── experience_importer.py    # 经历描述导入器（含概括）
    ├── distillation_engine.py    # 蒸馏引擎（4-pass）
    ├── distillation_prompts.py   # 蒸馏提示词模板
    ├── traits.py                 # 50 维指标定义 + 蒸馏产物数据结构
    ├── dynamic_synthesizer.py   # 动态人格合成器
    ├── personality_generator.py  # 性格提示词生成模型接口
    ├── personality_judge.py      # 性格判定模型接口（情绪/亲和）
    ├── state_manager.py          # 运行时状态管理（用户-卡绑定）
    ├── persistence.py            # V3 持久化层 (CRUD)
    └── migration.py              # V2 → V3 数据迁移

character_cards/                  # 角色卡 YAML 文件目录
├── exa.yaml                      # 默认 EXA 角色卡
└── custom/                       # 用户自定义角色卡

docs/
└── plan-personality-v3.md        # 本文件
```

---

## 十四、实施计划

### Phase 0 — 指标定义 & 数据模型 (2 天) ← 当前阶段

- [ ] `traits.py` — 50 维指标完整定义、分类、标签、描述
- [ ] `character_card.py` — 角色卡数据结构、YAML 读写、校验
- [ ] `experience_importer.py` — 经历导入 + AI 概括
- [ ] SQLite 表创建（character_cards, distilled_traits, user_character_cards, character_experiences）

### Phase 1 — 蒸馏引擎 (4 天)

- [ ] `distillation_prompts.py` — 3 个蒸馏 Pass 的提示词模板
- [ ] `distillation_engine.py` — Pass 1~4 的实现
- [ ] 蒸馏异步任务化（TaskManager 支持蒸馏任务类型）
- [ ] 蒸馏产物校验 + 指纹比对
- [ ] 默认角色卡 (`exa.yaml` 的 V3 版本) 的蒸馏验证

### Phase 2 — 动态合成 & 性格模型 (3 天)

- [ ] `dynamic_synthesizer.py` — 种子噪声 + 情绪调制 + 时间漂移
- [ ] `personality_generator.py` — 性格提示词生成 prompt assembly + 模型调用
- [ ] `personality_judge.py` — 情绪/亲和判定 prompt assembly + 模型调用
- [ ] 与 ChatPipeline 集成

### Phase 3 — 集成 & 验证 (3 天)

- [ ] `__init__.py` — PersonalitySystemV3 主入口，衔接所有子模块
- [ ] `state_manager.py` — 用户-卡绑定，运行时缓存
- [ ] PromptEngine 适配 V3
- [ ] API 端点实现
- [ ] V2 兼容共存
- [ ] 集成测试

### Phase 4 — 前端 & 工具 (2 天)

- [ ] 角色卡编辑器 webUI
- [ ] 蒸馏结果可视化（50 维雷达图）
- [ ] 性格快照历史趋势图

### Phase 5 — 迁移 & 清理 (1 天)

- [ ] V2 → V3 数据迁移脚本
- [ ] 默认切换到 V3
- [ ] V2 代码归档为 legacy

---

## 十五、风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 蒸馏结果不准确 | 角色性格偏移预期 | manual_overrides 允许手动修正；preview API 可在持久化前预览 |
| 性格模型推理延迟过高 | 每轮交互增加 1~3 秒 | 使用本地小模型（3B~7B），异步 pipeline 并行处理 |
| 50 维向量雷同 | 不同角色区分度不足 | 蒸馏 Pass 3 中明确要求"基于材料合理推断"，避免默认中位值 |
| V2 → V3 迁移丢失用户数据 | 用户体验断层 | 迁移前备份，迁移后支持回退到 V2 |
| 蒸馏成本高（API 调用） | 频繁修改角色卡烧钱 | 指纹比对避免重复蒸馏；默认角色卡预蒸馏 |
| 无状态性格模型上下文缺失 | 前后情绪不一致 | 每次推理输入中都包含上轮情绪和亲密度，形成"软状态" |

---

## 十六、未提及的补充设计

### 16.1 角色卡继承与模组

角色卡可以声明 `extends: "parent_card_id"`，继承父卡的所有设定，并覆盖部分字段。这允许用户快速创建变体角色（如"傲娇 EXA"继承"EXA"但调整 E4 讽刺倾向和 F2 责任心）。

### 16.2 多人格共存

`user_character_cards` 表允许同一用户绑定多张角色卡。可以随时切换活跃卡。每个卡独立维护 emocao + 亲密度。

### 16.3 蒸馏产物版本管理

每次重蒸馏增加 version 号。支持回滚到历史版本。生产环境总是使用特定 version。

### 16.4 蒸馏缓存与共享

社区可以分享蒸馏产物。如果一个角色卡的 SHA256 指纹与社区共享的某个角色卡匹配，直接复用蒸馏产物而无需本地运行。

### 16.5 性格模型的热切换

`personality_generator.py` 和 `personality_judge.py` 使用的模型可以通过配置热切换，无需重启。不同模型对"角色诠释"的差异可以作为"风格变体"。

### 16.6 环境影响

如果叙事世界系统 (WorldEngine) 处于开启状态，世界状态（天气、时间、事件）会影响合成器中的 `environment_sensitivity` 调制。例如：深夜 + 安静 = AI 语气更柔和。

### 16.7 角色卡模板

提供 5~8 个预置角色卡模板（如"温柔前辈""傲娇同事""沉稳导师""元气新人""毒舌损友""中二旅人""淡漠学者""腹黑参谋"），让用户可以直接使用或以此为起点修改。

---

## 总结

PersonalitySystemV3 的核心变革：

```
V2:  预设 YAML → 规则匹配 → 模板拼接 → 注入 prompt
     (静态)     (僵硬)     (机械)     (单薄)

V3:  角色卡 → 蒸馏引擎 → 合成器 → 性格模型 → 注入 prompt
     (自然语言) (AI提炼) (动态化) (AI生成)  (丰富)
```

**角色是"蒸馏"出来的，而不是"配置"出来的。**
性格是"生成"出来的，而不是"拼接"出来的。
