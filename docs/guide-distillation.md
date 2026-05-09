# 自动蒸馏系统实现指导

> 来源: architecture.md §七 / §八.5 / §十
> 目标: 从用户对话中自动提取模式，生成可审核的技能草案

---

## 一、设计理念

```
用户对话 ──→ 模式挖掘 ──→ 技能草案 ──→ 人工审核 ──→ 激活技能
                │                          │
                │  ┌───────────────────────┘
                │  │
                ▼  ▼
         不断迭代优化
```

**核心思想:** AI 通过与用户的真实交互"学会"新能力。不是简单的 prompt 模板，而是从对话中提取模式、生成结构化的技能包。

---

## 二、目标文件

```
skills/
├── distill.py          # DistillationEngine 主类 (~350 行)
└── distilled/
    └── _drafts/        # 待审核草案目录
```

---

## 三、蒸馏流程

```
┌─────────────────────────────────────────────────────────────┐
│                   DistillationEngine                         │
│                                                             │
│  ┌───────────────┐                                          │
│  │ 1. 对话收集    │  从 chatdbmgr 获取最近 N 轮对话           │
│  └───────┬───────┘                                          │
│          ▼                                                  │
│  ┌───────────────┐                                          │
│  │ 2. 模式挖掘    │  使用 LLM 分析对话，识别重复模式           │
│  │               │  - 用户经常问什么？                        │
│  │               │  - AI 怎么回答的？                         │
│  │               │  - 有没有固定的处理流程？                   │
│  │               │  - 是否涉及外部工具调用？                   │
│  └───────┬───────┘                                          │
│          ▼                                                  │
│  ┌───────────────┐                                          │
│  │ 3. 模式聚类    │  将相似模式归类，判断是否值得蒸馏           │
│  │               │  - 出现频率 > 阈值                         │
│  │               │  - 有明确的知识/流程可提取                  │
│  │               │  - 不与现有技能重复                        │
│  └───────┬───────┘                                          │
│          ▼                                                  │
│  ┌───────────────┐                                          │
│  │ 4. 草案生成    │  使用 LLM 生成技能结构:                   │
│  │               │  - skill.yaml (元数据)                     │
│  │               │  - prompts/instruction.md (使用说明)       │
│  │               │  - prompts/patterns.md (提取的模式)        │
│  │               │  - prompts/examples.md (真实对话示例)      │
│  │               │  - tools/*.py (可选, 工具代码草案)         │
│  └───────┬───────┘                                          │
│          ▼                                                  │
│  ┌───────────────┐                                          │
│  │ 5. 草案存储    │  保存到 skills/distilled/_drafts/         │
│  │               │  status = "draft"                         │
│  └───────┬───────┘                                          │
│          ▼                                                  │
│  ┌───────────────┐                                          │
│  │ 6. 通知用户    │  通知用户有新技能草案待审核                 │
│  └───────────────┘                                          │
│                                                             │
│  ┌──────────────────────────────────────────────────────────┐│
│  │ 7. 人工审核 (用户操作)                                    ││
│  │    - 查看草案内容                                         ││
│  │    - 编辑修改                                             ││
│  │    - 批准 → status="active" → 自动加载                    ││
│  │    - 拒绝 → 删除草案                                      ││
│  └──────────────────────────────────────────────────────────┘│
│                                                             │
│  ┌──────────────────────────────────────────────────────────┐│
│  │ 8. 技能迭代 (持续优化)                                    ││
│  │    - 已激活技能继续积累相关对话                            ││
│  │    - 定期重新蒸馏，更新提示词和工具代码                    ││
│  │    - 版本递增: v1 → v2 → v3                              ││
│  └──────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

---

## 四、DistillationEngine 实现概要

```python
class DistillationEngine:
    """
    自动蒸馏引擎。
    从用户对话中提取模式，生成技能草案。
    """

    def __init__(self, db, skill_manager, llm_client, draft_dir):
        self.db = db                    # ChatDBManager
        self.skill_manager = skill_manager  # SkillManager
        self.llm = llm_client           # LLM 客户端 (用于分析)
        self.draft_dir = Path(draft_dir)

        # 配置参数
        self.min_conversations = 10      # 最少对话轮数
        self.min_pattern_frequency = 3   # 模式最少出现次数
        self.max_draft_age_days = 7      # 草案过期天数
        self.analysis_window_days = 30   # 分析最近多少天的对话

    async def run(self, user_id=None) -> dict:
        """执行一次完整的蒸馏流程，返回报告"""
        # 1. 收集对话
        # 2. 模式挖掘 (LLM)
        # 3. 草案生成 (LLM)
        # 4. 保存 + 清理
        pass
```

---

## 五、关键方法详解

### 5.1 对话收集 `_collect_conversations()`

```python
def _collect_conversations(self, user_id=None) -> list:
    """从数据库获取最近 analysis_window_days 天的对话"""
    # 调用 self.db.list_chats() + self.db.get_messages()
    # 返回格式: [{chat_id, chat_name, role, content, timestamp}, ...]
    # 采样上限: 200 条
```

### 5.2 模式挖掘 `_mine_patterns()`

**使用 LLM 进行对话分析。** 核心是构建合适的分析 prompt：

```
你是对话分析专家。分析以下 AI 助手与用户的对话，识别可蒸馏的模式：

模式类型:
1. 知识型: 用户反复询问某类知识
2. 工作流型: 用户经常要求执行固定的多步骤流程
3. 工具使用型: AI 经常需要调用外部工具
4. 偏好型: 用户对某类回答有明确的偏好

输出 JSON 数组:
[{
  "name": "模式名(snake_case)",
  "display_name": "中文名",
  "description": "描述",
  "category": "knowledge|workflow|tool_usage|preference",
  "occurrence_count": 出现次数,
  "example_exchanges": [{user: ..., assistant: ...}, ...],
  "key_insights": ["知识点1", "知识点2"],
  "suggested_tools": [...]
}]
```

**LLM 调用方式：**

```python
messages = [{"role": "system", "content": analysis_prompt}]
# 注意: 这里用 messages 作为 system prompt 内容
# LLM 直接返回 JSON（非对话模式）
response = self.llm.send_message(messages)
# 用 re.search(r'\[.*\]', response) 提取 JSON
```

### 5.3 草案生成 `_generate_draft()`

**根据挖掘出的模式，再次调用 LLM 生成完整的技能文件：**

```
你是技能设计师。根据以下模式，生成完整技能草案。

输出 JSON:
{
  "skill.yaml": "...",
  "prompts/instruction.md": "...",
  "prompts/patterns.md": "...",
  "prompts/examples.md": "...",
  "tools/main.py": "..." (或 null)
}
```

### 5.4 草案保存 `_save_draft()`

```python
def _save_draft(self, draft: dict) -> Path:
    """
    将草案写入 skills/distilled/_drafts/<skill_name>/
    包含: skill.yaml, prompts/, tools/
    """
    # 从 skill.yaml 内容中提取 name
    # 创建 drafts/<name>/ 目录
    # 逐个写入各文件
```

---

## 六、草案管理

| 方法 | 说明 |
|------|------|
| `list_drafts()` | 列出所有待审核草案 |
| `approve_draft(name)` | 批准 → 移动至 distilled/ → 激活 |
| `reject_draft(name)` | 拒绝 → 删除草案目录 |
| `iterate_skill(name)` | 对已激活技能重新蒸馏迭代 |
| `_cleanup_old_drafts()` | 清理超过 max_draft_age_days 的过期草案 |

---

## 七、蒸馏触发方式

```python
# 方式 1: 定时自动蒸馏 (推荐)
# 在 config 中配置:
DISTILLATION_AUTO_ENABLED = True
DISTILLATION_INTERVAL_HOURS = 24

# 方式 2: API 手动触发
# POST /api/skills/distill

# 方式 3: 对话中触发
# 当用户说 "帮我总结一下你最近学到了什么"
# task_plugin 识别为蒸馏请求
```

定时任务实现建议：
```python
# 使用 schedule 库（项目中已有 tasks.py 使用）
import schedule
schedule.every(24).hours.do(distillation_engine.run)
```

---

## 八、蒸馏 API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/skills/distill` | 手动触发蒸馏 |
| GET | `/api/skills/distill/drafts` | 列出待审核草案 |
| GET | `/api/skills/distill/drafts/<name>` | 草案详情 |
| POST | `/api/skills/distill/drafts/<name>/approve` | 批准草案 |
| POST | `/api/skills/distill/drafts/<name>/reject` | 拒绝草案 |
| GET | `/api/skills/distill/history` | 蒸馏历史记录 |

---

## 九、蒸馏生成的技能示例

假设用户经常让 AI 帮忙审查代码：

```
skills/distilled/_drafts/code_review/
├── skill.yaml              # name: code_review, status: draft
├── prompts/
│   ├── instruction.md      # 审查流程: 理解意图→整体浏览→逐层审查→总结建议
│   ├── patterns.md         # 提取的用户偏好: 简洁、关注安全、Python 为主
│   └── examples.md         # 历史对话中的典型审查示例
└── (无 tools/ — 纯提示词技能)
```

---

## 十、实现步骤

1. **实现 DistillationEngine 核心**
   - 对话收集 (从 chatdbmgr)
   - 模式挖掘 prompt 工程
   - 草案生成 prompt 工程
   - 文件保存

2. **实现审核流程**
   - list / approve / reject
   - approve 时自动调用 SkillManager.install()

3. **添加定时蒸馏**
   - 在 app.py 启动时注册 schedule 任务
   - 或使用 threading.Timer

4. **添加 API 端点**
   - 蒸馏触发
   - 草案管理

5. **实现技能迭代**
   - 已激活技能积累新对话
   - 定期重新蒸馏更新

---

## 十一、依赖关系

```
DistillationEngine
    ├── 依赖 chatdbmgr    (对话数据来源)
    ├── 依赖 SkillManager (草案批准后加载技能)
    ├── 依赖 LLM 客户端   (模式挖掘 + 草案生成, 使用 DeepSeek)
    └── 被 task_plugin 调用 (对话中触发蒸馏)
```
