# 动态记忆召回系统设计

> 版本: v1.0 | 2026-05-16
> 目标: 将记忆系统从"被动压缩"升级为"主动召回"，允许 AI 像人类一样检索和回忆过去的对话细节。

---

## 一、现状分析

### 1.1 当前记忆系统

```
MemoryManager (memory.py)
├── record_dialog_and_summary()   # 每轮对话后异步生成摘要 → 存入 memories 表
└── assemble_context()            # 上下文超过阈值时，远端消息替换为摘要系统消息

memories 表结构:
  memory_id | user_id | chat_id | round_index | summary | created_at
```

**核心缺陷**：
- 摘要一旦生成就失去了与原始消息的关联映射
- 摘要片段不够精细，无法按主题或关键词索引检索
- AI 只能被动看到窗口内的摘要，无法**主动搜索**历史记忆
- 无法还原记忆的**原始对话细节**

### 1.2 预期行为

```
用户: "你还记得我们之前讨论过 Python 类型系统吗？"

AI: "让我回忆一下……"           ← 人类化的自然语言过渡
AI (内部): <recall>{"keywords":["Python","类型系统"],"count":3}</recall>
系统返回: [找到 2 条相关记忆]

AI: "我想起来了。在第5轮我们讨论了类型注解的基本语法，
     第12轮我们深入到了泛型和 Protocol……"

AI (可选细化):
AI: "让我把第5轮的细节调出来……"
AI (内部): <recall>{"detail":[5]}</recall>
系统返回: [第5轮原始对话]
AI: "当时你是这样说的：……，我的回答是：……"
```

---

## 二、设计方案

### 2.1 总体架构

```
┌─────────────────────────────────────────────────────────────┐
│                    MemoryRecallEngine                       │
│                   (memory_recall.py)                        │
│                                                             │
│  search(keywords, count) → List[MemoryHit]                  │
│  get_detail(round_indices) → List[RoundMessages]            │
│  extract_keywords(text) → List[str]                         │
└──────────┬──────────────────────────────────┬───────────────┘
           │                                  │
    ┌──────▼──────┐                   ┌──────▼──────┐
    │ chatdbmgr   │                   │  memory.py  │
    │ (扩展后的    │                   │ (摘要生成时  │
    │  memories表  │                   │  注入关键词) │
    │ + recall接口)│                   │             │
    └─────────────┘                   └─────────────┘
           │
    ┌──────▼──────────────────────────────────────┐
    │          recall_plugin.py                   │
    │  解析 <recall> 标签 → 调用引擎 → 注入结果     │
    │  Hook: POST_PROCESS, priority=38            │
    └─────────────────────────────────────────────┘
```

### 2.2 数据库扩展

#### 2.2.1 扩展 `memories` 表

```sql
-- 新增字段
ALTER TABLE memories ADD COLUMN keywords TEXT DEFAULT '';
-- 格式: "keyword1,keyword2,keyword3" (逗号分隔，小写)

ALTER TABLE memories ADD COLUMN message_start_id INTEGER DEFAULT NULL;
-- 该轮次第一条消息的 message_id

ALTER TABLE memories ADD COLUMN message_end_id INTEGER DEFAULT NULL;
-- 该轮次最后一条消息的 message_id
```

#### 2.2.2 扩展 `messages` 表

```sql
ALTER TABLE messages ADD COLUMN round_index INTEGER DEFAULT NULL;
-- 标记消息属于哪个对话轮次，用于记忆→消息的精确回溯
```

每次 `append_messages()` 时自动填充 `round_index`（由 `MemoryManager` 调用方传入）。

#### 2.2.3 新建 `memory_index` 表（可选优化）

```sql
CREATE TABLE IF NOT EXISTS memory_index (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id INTEGER NOT NULL,
    keyword TEXT NOT NULL,
    FOREIGN KEY (memory_id) REFERENCES memories(memory_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_memory_index_keyword ON memory_index(keyword);
```

> 此表将每个 memory 对应的关键词拆分为多行，便于精确匹配。初期可以先放在 `memories.keywords` 字段中用 `LIKE '%keyword%'` 搜索，后续数据量大时再启用此表。

### 2.3 `<recall>` 标签语法

`<recall>` 是一个声明式标签，AI 在回复中插入它来触发记忆操作。支持三种模式：

#### 模式一：关键词检索

```json
<recall>
{
  "keywords": ["keyword1", "keyword2", ...],
  "count": 5,
  "threshold": 0.3
}
</recall>
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `keywords` | `string[]` | 是 | 检索关键词列表 |
| `count` | `int` | 否 | 最多返回条数 (默认 5) |
| `threshold` | `float` | 否 | 最低匹配度阈值 (默认 0.3) |

#### 模式二：请求细节还原

```json
<recall>
{
  "detail": [5, 12, 18]
}
</recall>
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `detail` | `int[]` | 是 | 要还原细节的 round_index 列表 |

#### 模式三：混合模式

```json
<recall>
{
  "keywords": ["topic"],
  "count": 3,
  "detail": true
}
</recall>
```

检索后自动展开所有命中记忆的详细对话内容。

### 2.4 检索算法 (关键词匹配)

由于不引入额外的向量化依赖，采用多级关键词匹配：

```
评分 = keyword_hit_score + recency_bonus
───────────────────────────────────────────

keyword_hit_score:
  - 精确匹配 (summary LIKE '%keyword%'):        +1.0 每命中一个
  - 关键词字段匹配 (keywords LIKE '%keyword%'): +0.8 每命中一个  
  - 同义词/相关词匹配 (可选，通过词表):           +0.5 每命中一个

recency_bonus:
  - 越新的记忆权重越高
  - bonus = 1.0 - (age_in_rounds / total_rounds)
  - 范围: [0, 1.0]

最终排序: 按 (keyword_hit_score * 0.7 + recency_bonus * 0.3) 降序
```

**去重与截断**：
- 同一次检索对同一个 memory_id 只保留最高分
- 结果按分数降序排列，取前 `count` 条
- 分数低于 `threshold` 的不返回

### 2.5 关键词提取策略

在 `MemoryManager._do_summary()` 中，生成摘要后同步提取关键词：

**方式 A — 从摘要文本提取（轻量，无额外 LLM 调用）**：
- 使用 jieba 分词 + TF-IDF 取 Top-K 关键词
- 优点：零延迟，不额外消耗 token
- 缺点：中文分词效果一般，英文支持有限

**方式 B — 让摘要 LLM 同时输出关键词（推荐）**：
- 修改 `LMSummaryModel.summarize_dialog()` 的 prompt，要求返回 `[摘要]\n[关键词: kw1, kw2, kw3]`
- 解析关键词字段
- 优点：关键词质量高，语义准确
- 缺点：略增 token 消耗

**初期采用方式 B**，降级方案为方式 A（当解析失败时）。

### 2.6 召回结果格式

#### 检索成功

```
[记忆检索结果] 找到 3 条相关记忆 (关键词: Python, 类型系统):
────────────────────────────────────────
#5 (2026-05-10) [匹配: Python×1, 类型系统×1, 得分: 1.85]
摘要: 讨论了Python类型注解的基本语法，包括基本类型、Optional和Union的用法。
  关联消息: #42~#47
────────────────────────────────────────
#12 (2026-05-14) [匹配: Python×1, 类型×1, 得分: 1.62]
摘要: 深入讨论了泛型、Protocol和类型变量的高级用法，用户表示想在实际项目中尝试。
  关联消息: #98~#105
────────────────────────────────────────
#18 (2026-05-15) [匹配: Python×1, 得分: 1.20]
摘要: 简短提及了Python 3.12的类型系统新特性。
  关联消息: #150~#153
────────────────────────────────────────

(使用 <recall>{"detail": [5,12,18]}</recall> 可查看完整对话)
```

#### 检索为空

```
[记忆检索结果] 未找到与 "Rust, 所有权" 相关的记忆。
```

#### 细节还原

```
[记忆细节还原] 第5轮对话 (2026-05-10):
────────────────────────────────────────
User:  昨天你提到 Python 的类型注解，我想详细了解...
Agent: 当然。Python 的类型注解从 3.5 开始引入...
User: 那 Optional 和 Union 有什么区别？
Agent: Optional[X] 本质上是 Union[X, None] 的语法糖...
User: 明白了，那在实际项目中你会推荐用哪个？
Agent: 对于可能为 None 的情况，Optional 更语义化...
────────────────────────────────────────
第12轮对话 (2026-05-14):
────────────────────────────────────────
User:  上次讨论的类型系统，我想深入泛型的部分...
Agent: 好的。Python 的泛型通过 TypeVar 实现...
...
────────────────────────────────────────
```

### 2.7 召回插件 (recall_plugin.py)

#### 在管道中的位置

```
POST_PROCESS 阶段:
  priority 35: SkillsPlugin / AgentPlugin  (执行 <tool> 标签)
  priority 38: RecallPlugin                ← 新增: 执行 <recall> 标签
  priority 40: TaskPlugin                  (执行 <task> 标签)
```

**为什么放在 tools 之后、task 之前？**
- `<recall>` 的结果可能需要被后续 AI 处理（如果 agent 循环开启）
- 记忆检索是纯查询操作，不产生副作用，适合在工具执行后确保上下文中已有工具结果
- 在 task 之前执行，因为 task 可能要基于记忆结果做判断

#### 处理流程

```
RecallPlugin.on_hook(POST_PROCESS, ctx):
  1. 从 ctx.original_reply 中提取所有 <recall> 标签
  2. 若没有 <recall> 标签 → 直接返回 ctx
  3. 对每个 <recall>:
     ├─ 若含 "detail" 字段 → 调用 engine.get_detail(round_indices)
     ├─ 若含 "keywords" 字段 → 调用 engine.search(keywords, count)
     └─ 格式化结果 → 追加到 ctx.reply / ctx.original_reply
  4. 设置 ctx.extra["recall_executed"] = True
  5. 如果 agent 模式开启，结果会由 AgentPlugin 在下一轮喂给 LLM
```

#### Agent 模式集成

当 `ctx.agent_active = True` 时，RecallPlugin 的工作方式：

```
User: "还记得我们讨论过 Python 类型系统吗？"

AI 第1轮: "让我回忆一下……<recall>{"keywords":["Python","类型系统"],"count":3}</recall>"

→ RecallPlugin 执行检索，将结果注入回复
→ AgentPlugin 检测到工具结果，将其作为 system/user 消息喂给 LLM

AI 第2轮: "我想起来了。第5轮讨论了类型注解基础，第12轮深入到泛型……
         让我调出第5轮的细节。<recall>{"detail":[5]}</recall>"

→ RecallPlugin 再次执行，还原第5轮完整对话
→ AgentPlugin 继续循环

AI 第3轮: "[基于完整记忆的回复] 当时你问了 Optional 和 Union 的区别，
         我的回答是……"
```

### 2.8 Prompt 更新

新增 `prompt/prompts/capabilities/memory_recall.md`：

```markdown
---
name: memory_recall
category: capabilities
version: "1.0"
description: 动态记忆召回能力 — <recall> 标签检索历史记忆
tags: [memory, recall, retrieval]
priority: 110
enabled: true
---
## 动态记忆召回能力

你拥有动态记忆召回能力。当用户询问你"是否记得"、"回忆一下"或需要引用过去的讨论时，
使用 `<recall></recall>` 标签检索你的长期记忆。

**检索语法**:
```json
<recall>
{"keywords": ["关键词1", "关键词2"], "count": 5}
</recall>
```

**细节还原语法**:
```json
<recall>
{"detail": [轮次号1, 轮次号2]}
</recall>
```

**行为准则**:
- 主动检索：当用户提及过去讨论的主题时，先检索再回答
- 自然过渡：检索前说"让我回忆一下…"等自然语言
- 诚实披露：未检索到时说"抱歉，我没有找到相关的记忆"
- 选择性展开：如果检索到的摘要足够回答，直接引用；
  如果需要更详细的上下文，再使用 detail 模式还原完整对话
```

### 2.9 人类化行为模拟

AI 在使用召回功能时的自然语言行为指南：

| 阶段 | AI 行为 | 说明 |
|------|---------|------|
| **意图** | "让我回忆一下……" | 发起检索前的自然过渡 |
| **检索中** | `<recall>` 标签嵌入回复 | 系统在 POST_PROCESS 处理 |
| **命中** | "我想起来了，在第X轮我们讨论过……" | 提取记忆摘要的关键信息 |
| **命中但模糊** | "我记得好像讨论过……让我查一下细节" | 触发 detail 模式 |
| **未命中** | "抱歉，我没有找到关于……的记忆" | 诚实告知 |
| **细节展开** | "当时的对话是这样的：……" | 还原原始对话 |

---

## 三、实现计划

### Phase 1: 数据库扩展 (chatdbmgr.py)

- [ ] `memories` 表新增 `keywords`, `message_start_id`, `message_end_id` 列
- [ ] `messages` 表新增 `round_index` 列
- [ ] 新增搜索接口 `search_memories(user_id, chat_id, keywords, count)`
- [ ] 新增消息查询接口 `get_messages_by_rounds(user_id, chat_id, round_indices)`
- [ ] 数据库迁移自动化（检查列是否存在，不存在则 ALTER）

### Phase 2: 检索引擎 (memory_recall.py)

- [ ] 创建 `MemoryRecallEngine` 类
- [ ] 实现 `search(keywords, count, threshold)` — 多级关键词匹配 + 评分排序
- [ ] 实现 `get_detail(round_indices)` — 按轮次还原原始对话
- [ ] 实现 `extract_keywords(text)` — 从摘要文本提取关键词
- [ ] 实现结果格式化 `_format_search_results()`, `_format_detail_results()`

### Phase 3: 摘要生成增强 (memory.py)

- [ ] 修改 `_do_summary()` 方法，生成摘要后同步提取关键词
- [ ] 修改 `save_memory()` 调用，传入 `keywords` 和 `message_id` 范围
- [ ] 修改 `record_dialog_and_summary()` 以记录消息 ID 范围

### Phase 4: 召回插件 (recall_plugin.py)

- [ ] 创建 `RecallPlugin` (Plugin, POST_PROCESS, priority=38)
- [ ] 实现 `<recall>` 标签解析
- [ ] 实现检索调用 + 结果注入
- [ ] 实现细节还原调用 + 结果注入
- [ ] 确保与 AgentPlugin 协同工作

### Phase 5: Prompt 更新

- [ ] 创建 `prompt/prompts/capabilities/memory_recall.md`
- [ ] 更新 `PromptEngine` 或 prompt 库以自动加载新能力描述

### Phase 6: 测试

- [ ] 单元测试：数据库搜索/查询接口
- [ ] 单元测试：MemoryRecallEngine 检索评分
- [ ] 单元测试：RecallPlugin 标签解析与结果格式化
- [ ] 集成测试：端到端记忆召回流程

---

## 四、风险与注意事项

1. **关键词提取质量**：LLM 提取的关键词可能不稳定，需要在下游做降级处理（提取失败时不阻塞流程）
2. **性能**：`LIKE '%keyword%'` 在大量记忆时可能变慢。如果 `memories` 表超过 10000 条，需要启用 `memory_index` 表 + FTS5 全文索引
3. **Agent 循环深度**：如果 AI 在 agent 模式下频繁使用 recall，可能增加对话轮次。需要合理的 `agent_max_steps` 配置（建议 ≥ 8）
4. **向后兼容**：数据库迁移需要处理旧数据（`keywords` 为空时仅匹配 `summary` 文本）
5. **隐私**：细节还原会暴露原始对话内容。仅在用户主动要求或 agent 自动展开时触发，不主动泄露
