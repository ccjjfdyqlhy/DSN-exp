# 记忆系统重设计：基于第一性原理

## 0. 问题诊断

当前记忆系统遍布 7 个文件（`memory.py`、`memory_recall.py`、`chatdbmgr.py` 记忆部分、`memory_plugin.py`、`recall_plugin.py`、`memory_compact.py`、`engine.py` 记忆初始化），代码约 600 行，但其功能核心只有三步：

| 操作 | 有效代码 | 冗余部分 |
|---|---|---|
| 每轮对话生成 LLM 摘要 → 存入 SQLite | ~20 行 | `ThreadPoolExecutor(max_workers=2)`、永远为空的 `keywords` 列、从未用于检索的 `message_start_id/end_id` |
| 上下文过长时用摘要代替远端的旧消息 | ~30 行 | 重复的时间跨度计算（两处独立实现） |
| AI 输出 `<recall>` 标签时按关键词搜索记忆 | ~40 行 | 两条独立但功能相同的标签解析路径（`memory.py:process_recall_tags` vs `recall_plugin.py:on_hook`）、被注释/未实现的 `extract_keywords_from_summary`、两个 `MemoryRecallEngine` 实例 |

全身上下尽是**写了但没用上的**东西。重设计的核心原则：**去掉一切不是绝对必要的东西。**

---

## 1. 第一性原理分析

### 1.1 上下文是有限资源

LLM 的注意力窗口有上限（通常 32K–128K tokens）。对话越长，必须丢弃的信息越多。记忆系统的本质问题是：**当上下文枯竭时，丢弃什么、保留什么。**

从这个原理出发，记忆系统的所有操作都围绕一件事：**把无限增长的对话压缩进有限窗口，同时最大化信息保真度。**

### 1.2 记忆只有两种用途

| 用途 | 触发方式 | 频率 | 需要什么 |
|---|---|---|---|
| **被动注入**（上下文压缩） | 每次消息前自动执行 | 极高 | 快速、简短的摘要，不多于 3–5 行 |
| **主动召回**（按需搜索） | AI 判断需要时主动触发 | 低 | 基于关键词/语义的相似匹配 |

两者共享同一份存储，不需要额外的索引表、关键词列或消息链接。

### 1.3 记忆有两种性质

| 性质 | 来源 | 例子 | 存储策略 |
|---|---|---|---|
| **经验性记忆** (experience) | 对话自动生成 | "用户提到他在腾讯工作，负责云数据库" | 参与上下文压缩，会被后续摘要覆盖/汇总 |
| **备忘录** (memo) | 用户显式记录或 AI 判定重要 | "用户儿子名叫小明，5 岁" | 总是可见，不参与压缩，可删除 |

---

## 2. 新设计

### 2.1 数据模型（一张表）

```sql
CREATE TABLE memory (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    chat_id    INTEGER NOT NULL,
    type       TEXT NOT NULL CHECK(type IN ('exp', 'memo')),
    round      INTEGER,           -- NULL for memos
    content    TEXT NOT NULL,      -- summary or memo body
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_memory_lookup ON memory(user_id, chat_id, type, round);
```

这就是全部，不需要 `keywords` 列（永远空白），不需要 `message_start_id/end_id`（检索细节直接按 `round` 反查 `messages` 表），不需要 `memory_index` FTS5 表（对话体量的全文检索用 Python 字符串匹配足够）。

### 2.2 模块架构（一个文件 + 一个表）

```
memory/
  __init__.py    →   from .core import MemorySystem
  core.py        →   class MemorySystem  (约 250 行，全部逻辑)
```

**没有** Manager、Engine、Plugin 的层层包装。插件层 (`Plugin`) 是框架自己的事情，不必在记忆模块里多包一层。

### 2.3 核心 API

```python
class MemorySystem:
    # ---- 自动记忆 ----
    def summarize_turn(
        self, user_id: int, chat_id: int, round_idx: int,
        user_msg: str, assistant_reply: str
    ) -> int | None:
        """用 LLM 将一轮对话压缩为单行摘要并持久化。"""

    def assemble_context(
        self, user_id: int, chat_id: int,
        history: list[dict], max_msgs: int = 56
    ) -> list[dict]:
        """
        被动注入：
        1. 先放所有 memo（作为 system 消息）
        2. 如果 history 超过 max_msgs，用摘要替换远端消息
        """

    # ---- 主动召回 ----
    def search(
        self, user_id: int, chat_id: int,
        keywords: list[str], limit: int = 5
    ) -> list[dict]:
        """对 exp+memo 内容进行分词匹配，返回 top-k。"""

    def get_detail(
        self, user_id: int, chat_id: int,
        rounds: list[int]
    ) -> dict[int, list[dict]]:
        """按轮次还原原始对话消息。"""

    def handle_tags(
        self, user_id: int, chat_id: int, text: str
    ) -> str:
        """
        处理回复中的 <recall> 和 <memo> 标签，返回替换后的文本。
        - <recall>{"k": [...], "n": 5}</recall>  → 搜索注入
        - <memo>text</memo>  → 创建备忘录，移除标签
        """

    # ---- 备忘录 (CRUD) ----
    def add_memo(self, user_id: int, chat_id: int, text: str) -> int: ...
    def get_memos(self, user_id: int, chat_id: int) -> list[dict]: ...
    def update_memo(self, memo_id: int, text: str) -> None: ...
    def delete_memo(self, memo_id: int) -> None: ...
```

我类的方法数：**8 个**。当前系统对象分布：`MemoryManager`(6) + `MemoryRecallEngine`(6) + `MemoryPlugin`(3) + `RecallPlugin`(2) + `MemoryCompactTask`(1) = **18 个**分散在 5 个文件。缩减 2.25x。

---

## 3. 关键机制

### 3.1 上下文压缩（被动回忆）

```
输入: [msg1, msg2, msg3, ..., msg100]   (100 条消息)
                    ↓
超过阈值 (56 条) → 触发压缩
                    ↓
保留最近 56 条消息 (msg45–msg100)
替换远端 44 条 (msg1–msg44) 为对应轮次的摘要
并在最前面插入所有备忘录
                    ↓
输出: [memo1, memo2, ..., sys:"[记忆 · 轮1] ...", sys:"[记忆 · 轮2] ...", ..., msg45, msg46, ..., msg100]
```

关键参数：
- `window_size`: 保留多少条消息（默认 56）
- `always_include_memos`: 备忘录永远排在最前

省略了"几天前"这种装饰性标签——信息密度不够的格式交给 prompt 设计，不要硬编码在逻辑里。

### 3.2 主动召回（搜索）

```
搜索过程:
  输入: keywords=["python", "async"]
  ↓
  从 DB 读取此 chat 的所有 exp 和 memo content
  ↓
  对每条 content 做 _tokenize(content) → set of tokens
  ↓
  score = |query_tokens ∩ content_tokens| / |query_tokens| × 0.7
        + (1 - round / max_round) × 0.3
  ↓
  过滤 score >= 0.3，按 score 降序，取 top-k
```

分词策略：中文逐字 + 英文按词（沿用现有 `_tokenize`，逻辑正确且简洁）。

### 3.3 备忘录

这是新增功能。有两种创建方式：

**方式 A — 用户命令：** 通过 `/memo add 小明今年5岁` 直接写入。

**方式 B — AI 识别：** AI 在回复中可插入 `<memo>content</memo>` 标签，被 `handle_tags()` 解析后存入并去除标签。

备忘录在 `assemble_context()` 中的行为：
- **永远排在** history 最前面，以 `system` 角色出现
- 格式：`[备忘] content`
- 可独立增删改查

示例交互：
```
用户: 对了，我的项目截止日是下周五
AI:   好的，我记下了。<memo>用户项目截止日是下周五</memo>
      (这条 memo 被保存，标签被去除，用户看到干净回复)
```

---

## 4. 与现有系统的差异对比

| 维度 | 旧设计 | 新设计 |
|---|---|---|
| 文件数 | 7 | 1 (`core.py`) |
| 类数 | 5 | 1 (`MemorySystem`) |
| 方法数 | ~18 (分散) | 8 (集中) |
| 数据表 | 1 表 + 6 列 | 1 表 + 6 列（重命名的更清晰列名） |
| keywords 列 | 有，但永远为空 | 删除 |
| message_start_id/end_id | 有但从未用于检索 | 删除（细节检索直接用 round） |
| ThreadPoolExecutor | max_workers=2，仅用于一个任务 | `threading.Thread(daemon=True)` |
| 重复 `<recall>` 解析 | 两处独立实现 | 一处：`handle_tags()` |
| 维护任务 | memory_compact.py（有 bug） | 不需要（内容本身就短） |
| 备忘录 | 无 | CRUD + 自动注入 |
| 加密 | AES-256-GCM（侵入业务逻辑） | 可选，通过 `content_cipher(value) → encrypted` hook 注入 |

---

## 5. 实现路径

### Phase 0 — 准备（1h）

1. 创建 `memory/core.py`，实现 `MemorySystem` 类
2. 写完整的单元测试（`tests/test_memory.py`），覆盖所有 8 个方法
3. 在 `memory/__init__.py` 中导出 `MemorySystem`

### Phase 1 — 迁移（2h）

1. 写数据迁移脚本：`exp` 迁移、旧表重命名、清理无效列
2. 将 `engine.py` 中的 `MemoryManager` 引用替换为 `MemorySystem`
3. 将 `memory_plugin.py` 中的调用适配到新 API
4. 将 `recall_plugin.py` 中的调用适配到 `handle_tags()`
5. 确认 AgentPlugin 的 recall 循环仍然正常工作

### Phase 2 — 备忘录（1h）

1. 实现 `add_memo` / `get_memos` / `update_memo` / `delete_memo`
2. 在 `assemble_context()` 中注入 memo
3. 在 `handle_tags()` 中实现 `<memo>` 标签解析
4. 添加 `/memo` 命令（todo_api.py 或新端点？等待确认）

### Phase 3 — 清理（0.5h）

1. 删除 `memory.py`、`memory_recall.py`、`maintenance/tasks/memory_compact.py`
2. 删除 `chatdbmgr.py` 中旧的记忆方法
3. 清理 `config.py` 中不再使用的配置项
4. 清理测试文件中的死引用

---

## 6. 讨论要点

1. **LLM 摘要的 prompt 设计**：新系统复用现有的 `LMSummaryModel`，但 prompt 应增加对"关键信息"的强调，而非"不超过50字"的机械限制。允许 AI 自行判断哪些对话值得记住，哪些是冗余社交语。

2. **备忘录的存储上限**：不设硬限制，但 prompt 中应引导 AI 控制 memo 数量（"只在信息具有长期价值时创建备忘"）。

3. **加密**：当前 AES-GCM 加密侵入在业务逻辑中（`_cipher.encrypt(user_id, ...)` 散落各处）。新设计建议将加密与解密收口为一个可插拔的 hook：`MemorySystem(encrypt_fn=..., decrypt_fn=...)`，默认无加密。

4. **搜索阈值**：`threshold=0.3` 和 `score = token_overlap * 0.7 + recency * 0.3` 这个公式从经验得出，暂不改变。如果未来需要语义搜索，可以通过 `search_fn` 回调注入，不改核心结构。
