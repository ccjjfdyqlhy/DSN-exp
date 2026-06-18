# DSN-exp 用户理解系统

> 本文档梳理项目中所有"理解用户"相关的子系统：它们追踪了什么、怎么采集、怎么使用。

---

## 目录

1. [架构总览](#1-架构总览)
2. [用户印象 (Impressions)](#2-用户印象-impressions)
3. [亲密度与关系 (Affinity)](#3-亲密度与关系-affinity)
4. [人格状态追踪 (Personality)](#4-人格状态追踪-personality)
5. [用户观察笔记 (Notebook)](#5-用户观察笔记-notebook)
6. [用户备忘录 (Memo)](#6-用户备忘录-memo)
7. [全面了解协议 (SSP)](#7-全面了解协议-ssp)
8. [生效路径对比](#8-生效路径对比)
9. [数据流向图](#9-数据流向图)

---

## 1. 架构总览

| 子系统 | 存储 | 采集时机 | 注入 prompt | 负责人 |
|--------|------|----------|-------------|--------|
| 印象 | SQLite `user_impressions` | POST_PROCESS 解析 `IMPRESSION:` | ✅ PRE_PROCESS 注入 | `ImpressionPlugin` |
| 亲密度 V3 | SQLite `user_character_cards.affinity_value` | POST_PROCESS LLM 判定 | ✅ `PersonalityPromptGenerator` | `PersonalityV3Plugin` |
| 亲密度 V2 | SQLite `personality_state.affinity` | POST_PROCESS 规则引擎 | ✅ `PersonalitySystemV2.build_prompt()` | `PersonalityPlugin` |
| 情绪 V2 | SQLite `personality_state` (5 维) | POST_PROCESS 刺激分析 | ✅ 同上 | `PersonalityPlugin` |
| 情绪 V3 | SQLite `user_character_cards.mood_state_json` | POST_PROCESS LLM 判定 | ✅ `PersonalityPromptGenerator` | `PersonalityV3Plugin` |
| 备忘录 | SQLite `memory_v2` (type=memo) | POST_PROCESS 解析 `<memo>` | ✅ `assemble_context()` 每次注入 | `MemorySystem` |
| 笔记本 | JSON `notebook/<uid>.json` | PRE_PROCESS 按频率触发 | ❌ 不注入 (仅文件保存) | `NotebookPlugin` |
| SSP 协议 | → 写入印象表 | 用户发起 `/ssp` 或系统建议 | → 通过印象注入 | `SSPPlugin` |

---

## 2. 用户印象 (Impressions)

### 文件位置

```
prompt/impression.py              — ImpressionManager 核心
plugins/builtin/impression_plugin.py — POST_PROCESS 插件
chatdbmgr.py                      — DB 层 (user_impressions 表)
app.py:1178                       — API 路由
prompt/prompts/core/impression.md  — AI 指令
```

### 存储结构

**表 `user_impressions`**

| 字段 | 类型 | 说明 |
|------|------|------|
| `impression_id` | INTEGER PK | 自增 |
| `uid` | INTEGER | 用户 ID |
| `category` | TEXT | `兴趣` / `工作` / `技能` / `习惯` / `偏好` / `项目` / `设备` / `社交` / `其他` |
| `content` | TEXT | 印象内容 |
| `confidence` | REAL | 置信度 0.0~1.0 |
| `source` | TEXT | `declared`(用户自己说)/`observed`(观察)/`inferred`(推断)/`protocol`(SSP) |
| `evidence` | TEXT | 证据文本 |

### 采集方式

1. **AI 对话中生成（主要）**: POST_PROCESS 阶段 `ImpressionPlugin` 解析 AI 回复中的 `IMPRESSION:category:content:confidence` 格式文本。AI 在 `impression.md` 中被教导：*"当发现新的、有足够信心的信息时，主动输出这样一行"*。

2. **SSP 协议采集（批量）**: SSP 全面了解协议运行期间收集的印象，source=`"protocol"`。

3. **手动 API**: `POST /api/impressions` 端点手动添加。

4. **恢复加载**: `ImpressionManager.load_impressions_from_text()` 从纯文本恢复。

### 使用时注入

`ImpressionPlugin._on_pre_process()` 在 PRE_PROCESS 阶段调用 `ImpressionManager.prompt_context()`，生成：

```
## 你对用户的了解
- [兴趣] 喜欢弹钢琴 (confidence: 0.8, observed)
- [工作] 后端开发工程师 (confidence: 0.9, declared)
```

这个片段被追加到 `ctx.system_prompt`，包含置信度 > 0.4 的前 8 条。

### 重复控制

`merge_similar()` 删除相同 `category|content` 的重复条目，保留置信度较高者。

---

## 3. 亲密度与关系 (Affinity)

### 3a. V3 亲密度（主用）

**文件**: `prompt/personality_v3/personality_judge.py`

每次 POST_PROCESS 在后台调用 `PersonalityJudge.analyze()`，用 LLM 分析当前对话判定：

```
{
  "affinity_change": { "delta": -3~+10 }
}
```

亲密度保存在 `user_character_cards.affinity_value` (0~100)，分级：

| 范围 | 等级 | 行为提示 |
|------|------|----------|
| < 16 | 陌生人 | 正式称呼，保持距离 |
| 16~30 | 相识 | 适度放松，表达善意 |
| 31~50 | 朋友 | 可开玩笑 |
| 51~70 | 密友 | 可引用共同经历 |
| 71~90 | 伙伴 | 主动分享想法 |
| 91+ | 挚友 | 自由切换话题 |

LLM 不可用时回退到**启发式判定**：关键词匹配。

### 3b. V2 亲密度（备用）

**文件**: `prompt/personality_v2/affinity.py` + `affinity_rules.yaml`

规则引擎采集：针对用户消息分类为 13 种行为，每种自带 delta + 冷却 + 每日上限 + 反弹保护。行为如 `P_PRAISE`(+4)、`N_INSULT`(-8)。

### 使用方式

两套系统都在每次对话的 PRE_PROCESS 阶段将当前亲密度等级和关系阶段描述注入 system prompt，引导 AI 讲话方式。

---

## 4. 人格状态追踪 (Personality)

### V2 人格（规则驱动）

**文件**: `prompt/personality_v2/`

追踪：

| 维度 | 存储 | 说明 |
|------|------|------|
| 5 维情绪 | `personality_state.joly/sorw/angr/fear/meta` | 实时值 + 基线 |
| 表达习性 | `personality_state.habits_json` | 先天 + 从用户对话中学到的口头禅 |
| 刺激规则 | `stimulus_rules.yaml` | 用户关键词 → 情绪变化 |
| 情绪惯性 | `emotion_inertia_json` | 防止情绪突变 |

每次 POST_PROCESS 更新 → PRE_PROCESS 注入 `## 你当前的情绪状态` + `## 你的表达习惯`。

### V3 人格（LLM 驱动）

**文件**: `prompt/personality_v3/`

不直接追踪用户特征，而是维护 **AI 的性格"感受"**：

| 维度 | 存储 | 说明 |
|------|------|------|
| 50 维性格向量 | 蒸馏产物 `.distilled.json` | 角色卡蒸馏得到，不因交互变化 |
| 情绪向量 | `user_character_cards.mood_state_json` | LLM 每轮判定 joy/sadness/anger/fear |
| 动态合成 | 运行时合成 | 种子噪声 + 情绪调制 + 时间漂移 + 亲密度调制 |

每次 PRE_PROCESS → `PersonalityPromptGenerator` (LLM) 生成 `## 角色设定` 注入 prompt。

---

## 5. 用户观察笔记 (Notebook)

### 文件位置

```
plugins/builtin/notebook/notebook_plugin.py
plugins/builtin/notebook/notebook_store.py
prompt/prompts/capabilities/notebook.md
```

### 存储

JSON 文件 `notebook/<uid>.json`，每行一条：

```json
{
  "id": 5,
  "chat_id": 12,
  "content": "我发现用户最近在学 Rust，对所有权概念有些困惑",
  "created_at": "2026-06-18T10:30:00"
}
```

### 采集

- **频率**: 每 `NOTEBOOK_FREQUENCY` (默认 10) 轮对话触发一次
- **机制**: PRE_PROCESS 注入笔记提示 → AI 回复末尾加 `<notebook>` → POST_PROCESS 提取 → 保存
- **不注入 prompt**: 笔记仅存文件，供离线分析或回顾

---

## 6. 用户备忘录 (Memo)

### 文件位置

```
memory/core.py              — MemorySystem.add_memo()
plugins/builtin/memory_plugin.py
prompt/prompts/capabilities/memory_recall.md
```

### 存储

**表 `memory_v2`** (type=`'memo'`)

| 字段 | 说明 |
|------|------|
| `user_id` | 用户 ID |
| `type` | `'memo'` |
| `content` | 加密的内容 |
| `created_at` | ISO 时间戳 |

### 采集

AI 回复中的 `<memo>内容</memo>` 标签（POST_PROCESS 提取）。

AI 被教导：*"用户说'记一下''记住'时优先用 memo"*。

### 使用

**每次 PRE_PROCESS 注入**：`MemorySystem.assemble_context()` 把所有活跃 memo 作为 `[备忘] 内容` 追加到上下文开头。因此每轮对话都能看到所有备忘。

---

## 7. 全面了解协议 (SSP)

### 文件位置

```
plugins/builtin/ssp_plugin.py
prompt/prompts/core/impression.md
```

### 触发条件

- 用户回复中包含 `<ssp>` 标签
- 或 `ImpressionPlugin` 检测到印象 < 5 条且亲密度低时设置 `suggest_ssp = True`

### 流程

1. 注入探索 prompt，让 AI 主动探索用户环境
2. 最多 50 步循环，每步 LLM 调用 + 工具执行
3. 提取 `IMPRESSION:` 片段 → 写入印象表 (source=`"protocol"`)
4. ≥20 条或 LLM 决策完成时终止
5. 结果通过印象注入流程进入 prompt

---

## 8. 生效路径对比

| 系统 | 数据→prompt 延迟 | 持久性 | 可信度 |
|------|----------------|--------|--------|
| 印象 | 下一轮对话立即生效 ✅ | 永久 | 带置信度 |
| 亲密度 | 下一轮对话立即生效 ✅ | 永久 | V2 规则驱动 / V3 LLM 判定 |
| 备忘录 | 下一轮对话立即生效 ✅ | 永久，加密 | AI 自主决定 |
| 笔记本 | 不注入 ❌ | 永久 | AI 自主决定 |
| SSP | 通过印象间接生效 | → 印象系统 | 协议级批量采集 |

---

## 9. 数据流向图

```
用户消息进入
    │
    ▼
┌─────────────────────────────────────────────────┐
│  PRE_PROCESS：三路注入                           │
│                                                  │
│  ① MemorySystem.assemble_context()              │
│     → [备忘] <memo内容>                          │
│     → [记忆·轮次N] <对话摘要>                    │
│                                                  │
│  ② ImpressionManager.prompt_context()            │
│     → "你对用户的了解"                           │
│                                                  │
│  ③ PersonalityPromptGenerator / build_prompt()   │
│     → 亲密度等级 + 情绪状态 + 关系阶段            │
│     → 行为指南 + 说话方式提示                     │
│                                                  │
│  ④ NotebookPlugin（每10轮）                      │
│     → "请写一篇用户观察笔记"                      │
└──────────────┬──────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────┐
│  MODEL_INVOKE：LLM 看到所有注入                   │
│  + 基础 identity / format / safety / skills       │
└──────────────┬──────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────┐
│  POST_PROCESS：四路采集                           │
│                                                  │
│  ① PersonalityV3Plugin → LLM判定                │
│     → 更新 user_character_cards.{affinity,mood}  │
│                                                  │
│  ② MemoryPlugin → 摘要生成                       │
│     → 写入 memory_v2 (type=exp)                  │
│                                                  │
│  ③ ImpressionPlugin → 解析 IMPRESSION:           │
│     → 写入 user_impressions                      │
│                                                  │
│  ④ NotebookPlugin → 提取 <notebook>              │
│     → 写入 notebook/<uid>.json                   │
│                                                  │
│  ⑤ MemorySystem.handle_tags()                    │
│     → <memo> → memory_v2 (type=memo)             │
│     → <recall> → 搜索记忆并回复                  │
│                                                  │
│  ⑥ SSPPlugin（如果触发）                          │
│     → 批量采集 → 写入 user_impressions           │
└──────────────────────────────────────────────────┘
```
