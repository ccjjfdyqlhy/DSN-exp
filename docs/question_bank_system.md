# DSN-exp 题库系统使用文档

> 版本: Phase 2 | 独立 SQLite，不加密，可移植 | 答题卡批改 → `problem_utils`

---

## 目录

1. [系统架构](#1-系统架构)
2. [快速开始](#2-快速开始)
3. [数据模型](#3-数据模型)
4. [核心模块](#4-核心模块)
5. [科目模板](#5-科目模板)
6. [题目管理](#6-题目管理)
7. [组卷 (Compose)](#7-组卷-compose)
8. [考试模拟 (Exam Sim)](#8-考试模拟-exam-sim)
9. [错题分析与复习](#9-错题分析与复习)
10. [多通道录入](#10-多通道录入)
11. [答题卡批改 (problem_utils 接口)](#11-答题卡批改-problem_utils-接口)
12. [调试工具](#12-调试工具)
13. [与 problem_utils 的对接设计](#13-与-problem_utils-的对接设计)

---

## 1. 系统架构

```
┌─────────────────────────────────────────────────────┐
│                    DSN Engine                        │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────┐  │
│  │ QuestionBank │  │ SubjectTmpl  │  │ GraphStore │  │
│  │    Store     │  │    Manager   │  │            │  │
│  └──────┬───────┘  └──────┬───────┘  └───────────┘  │
│         │                 │                          │
│  ┌──────┴─────────────────┴──────────────────────┐  │
│  │          question_bank / 独立 SQLite            │  │
│  │          .dsn/question_bank.db                 │  │
│  └───────────────────────────────────────────────┘  │
│                                                      │
│  ┌──────────────┐  ┌─────────────┐  ┌───────────┐  │
│  │ ScannerPipeline│  │ErrorAnalyzer│  │ExamComposer│  │
│  └──────┬───────┘  └──────┬──────┘  └─────┬─────┘  │
│         │                 │               │          │
│  ┌──────┴─────────────────┴───────────────┴──────┐  │
│  │  Skills (AI 调用的工具层)                       │  │
│  │  question_crud / compose_exam / error_analysis │  │
│  │  template_tools / exam_review / batch_import   │  │
│  │  doc_to_questions / quest_from_image           │  │
│  │  quick_question                                │  │
│  └───────────────────────────────────────────────┘  │
│                                                      │
│  ┌───────────────────────────────────────────────┐  │
│  │  ExamSim (考试模拟系统)                         │  │
│  │  ExamEngine / ExamScorer / AnswerSheetMatcher  │  │
│  └───────────────────────────────────────────────┘  │
│                                                      │
│  ┌───────────────────────────────────────────────┐  │
│  │  problem_utils (答题卡扫描前端)                 │  │
│  │  OpenCV 检测 → 透视矫正 → 图像保存             │  │
│  │  → AI 阅卷 → AnswerSheetMatcher → 判分          │  │
│  └───────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

### 分层说明

| 层 | 位置 | 职责 |
|----|------|------|
| **DB** | `db/question_bank.py` | SQLite 独立数据库，DDL 定义，线程安全连接，数据迁移 |
| **Store** | `question_bank/store.py` | CRUD 操作：题目、试卷、错题、考试结果 |
| **Model** | `question_bank/models.py` | 数据类：Question, Subject, ErrorLog, ExamPaper, ExamResult 等 |
| **Composer** | `question_bank/composer.py` | 组卷引擎：按难度/知识点/题型分布选题目 |
| **Scanner** | `question_bank/scanner_pipeline.py` | LLM 驱动的扫描录入管线（图片→文本→入库） |
| **Analyzer** | `question_bank/error_analyzer.py` | 错题分析：LLM 判断错误类型 + 薄弱知识点抽取 |
| **Templates** | `question_bank/template_manager.py` | 科目模板管理：加载/创建/导入/导出/应用 |
| **ExamSim** | `exam_sim/` | 考试模拟引擎、判分器、答题卡匹配器 |
| **Skills** | `skills/builtin/question_bank/` | AI 工具接口层：CRUD、组卷、分析、模板 |

---

## 2. 快速开始

### 2.1 初始化

系统首次启动时自动初始化题库 DB：

```python
# db/question_bank.py → QuestionBankDBManager.__init__()
# 自动创建 .dsn/question_bank.db + 所有表 + 预置题型
```

引擎启动时注入依赖：

```python
# engine.py L1506-L1527
from question_bank.store import QuestionStore
from question_bank.template_manager import SubjectTemplateManager
from question_bank.composer import ExamComposer
from question_bank.error_analyzer import ErrorAnalyzer
from question_bank.scanner_pipeline import ScannerPipeline

question_store = QuestionStore(db)
template_manager = SubjectTemplateManager(db)
exam_composer = ExamComposer(question_store)
error_analyzer = ErrorAnalyzer(question_store, models_plugin)
scanner_pipeline = ScannerPipeline(question_store, models_plugin)
```

### 2.2 应用科目模板

```bash
# 内置模板 (YAML):
#   skills/builtin/question_bank/templates/
#     3_subjects.yaml  → 理科3科 (数学/物理/化学)
#     6_subjects.yaml  → 高考6科 (语数英+物化生)
#     9_subjects.yaml  → 全科9科 (语数英+物化生+政史地)

# 通过 AI 工具应用：
TemplateTools.apply("理科3科")
# 或直接代码调用：
template_manager.apply_template("6_subjects")
```

### 2.3 添加入门题目

```python
# 代码级
store.create_question({
    "subject_id": 1,
    "type_id": 1,
    "content": "1+1=?",
    "answer": "2",
    "difficulty": 1,
})

# AI 工具级 (Skill)
QuickQuestionTool.add_question(subject="math", content="...", answer="...")
```

### 2.4 验证

```bash
python tests/debug_question_bank.py subjects
python tests/debug_question_bank.py count
python tests/debug_question_bank.py list
```

---

## 3. 数据模型

### 3.1 数据库表 (12 张)

| 表名 | 主键 | 说明 |
|------|------|------|
| `subjects` | subject_id | 科目定义 |
| `question_types` | type_id | 题型定义（含判分模式） |
| `questions` | question_id | 题目主体 |
| `question_type_refs` | — | (保留) |
| `knowledge_point_refs` | id | 题目标签→知识点关联 |
| `error_logs` | log_id | 错题记录（user_id 为整数，不引用 users 表） |
| `exam_papers` | paper_id | 组卷生成的试卷 |
| `exam_results` | result_id | 考试结果（含逐题得分详情） |
| `exam_sessions` | session_id (UUID) | 考试会话（进行中状态+答案+计时） |
| `subject_templates` | template_id | YAML 模板的 JSON 存储 |
| `knowledge_nodes` | kp_code | 知识图谱节点 |
| `knowledge_edges` | id | 知识图谱边 |
| `user_knowledge_state` | id | 用户知识点掌握状态（Spaced Repetition） |

### 3.2 Question 字段

```python
@dataclass
class Question:
    question_id: int       # 自增 PK
    subject_id: int        # → subjects.subject_id
    type_id: int           # → question_types.type_id
    source: str            # manual / scan / import / image_snap / batch
    difficulty: int        # 1-5
    content: str           # 题目正文（支持 Markdown）
    options: str           # JSON 数组 (选择题用)
    answer: str            # 答案 (JSON 序列化)
    explanation: str       # 解析
    tags: str              # JSON 标签数组
    knowledge_points: str  # JSON 知识点数组
    metadata: str          # JSON 元信息
    version: int           # 乐观锁版本号
```

### 3.3 题型与判分模式

| 题型 | 子类型 | 判分模式 | 匹配逻辑 |
|------|--------|---------|----------|
| 选择题 | 单选/多选 | `exact` | 字符串精确匹配 |
| 判断题 | 判断 | `exact` | 字符串精确匹配 |
| 填空题 | 填空 | `keyword` | 关键词命中率 ≥80% |
| 解答题 | 计算/证明/简答 | `llm` | LLM 评分 0.0-1.0 |
| 作文题 | 作文 | `llm` | LLM 评分 |
| 阅读理解 | 阅读 | `llm` | LLM 评分 |

---

## 4. 核心模块

### 4.1 QuestionStore (`question_bank/store.py`)

**依赖**: `QuestionBankDBManager` (SQLite 连接)

**核心方法**:

| 方法 | 作用 |
|------|------|
| `create_question(data)` | 创建题目 → 返回 question_id |
| `get_question(id)` | 按 ID 获取单题 |
| `update_question(id, data)` | 更新（增量字段，自动 JSON 序列化） |
| `delete_question(id)` | 级联删除（清 kp_refs + error_logs） |
| `search_questions(subject, type_id, difficulty, tags, kps, limit, offset)` | 多条件搜索 |
| `get_questions_by_ids(ids)` | 批量获取（保持传入顺序） |
| `count_questions(subject)` | 统计数量 |
| `add_error_log(...)` | 添加错题（已存在未掌握→累加 attempt_count） |
| `get_error_logs(user_id, subject, mastered)` | 查询错题记录 |
| `mark_mastered(log_id)` | 标记掌握 |
| `create_exam_paper(...)` | 创建试卷 |
| `get_exam_paper(paper_id)` | 获取试卷 |
| `save_exam_result(...)` | 保存考试结果 |
| `get_exam_results(user_id, limit)` | 查询考试历史 |

### 4.2 SubjectTemplateManager (`question_bank/template_manager.py`)

**职责**: 科目模板的完整生命周期管理

| 方法 | 说明 |
|------|------|
| `list_templates()` | 列出所有模板 (名称+简介) |
| `get_template(name)` | 获取模板详情 (解析 YAML/JSON) |
| `apply_template(name)` | 应用模板（清空 subjects + question_types，按模板重建） |
| `import_template(path)` | 从 YAML 文件导入自定义模板 |
| `export_template(name, path)` | 导出模板为 YAML |
| `create_template(name, subjects)` | 创建自定义模板（入库+写入 custom/ 目录） |
| `delete_template(name)` | 删除模板（内置模板不可删） |
| `init_builtin_templates()` | 初始化 3 个内置模板到 DB |
| `get_active_subjects()` | 获取所有活跃科目 |
| `get_subject_by_code(code)` | 按 code 查科目 |
| `get_question_types()` | 获取所有题型 |
| `get_type_id(name, subtype)` | 获取题型 ID |
| `has_subjects()` | 是否有科目数据 |

### 4.3 ScannerPipeline (`question_bank/scanner_pipeline.py`)

**依赖**: `QuestionStore` + `ModelsPlugin` (LLM)

**流程**:

```
输入图像/文本
  → ModelsPlugin.describe_image (视觉识别)
  → LLM 提取：content/answer/type_name/options/difficulty/tags
  → JSON 解析
  → 逐条 create_question (自动匹配 subject_id + type_id)
  → 返回统计
```

**方法**:

| 方法 | 说明 |
|------|------|
| `process_scan(image_path, user_id, subject_code)` | 扫描图片→LLM 识别→入库 |
| `process_text(text, user_id, subject_code)` | 文本→LLM 提取→入库 |

### 4.4 ErrorAnalyzer (`question_bank/error_analyzer.py`)

| 方法 | 说明 |
|------|------|
| `analyze_error(user_id, question_id, user_answer)` | LLM 分析错误类型 + 原因 |
| `get_weak_points(user_id, subject)` | 按错题统计薄弱知识点 |
| `recommend_questions(user_id, kp_code, count)` | 基于薄弱知识点推荐题目 |

**LLM 判断的错误类型**: `粗心` / `知识点不清` / `审题错误` / `计算错误` / `概念混淆`

### 4.5 ExamComposer (`question_bank/composer.py`)

| 方法 | 说明 |
|------|------|
| `compose(params)` | 按参数组卷（难度分布+知识点过滤） |
| `compose_by_diff(subject, difficulty, count)` | 按单一难度组卷 |
| `compose_adaptive(user_id, subject, count)` | 自适应组卷（基于错题知识点） |

**ComposeParams**:

```python
ComposeParams(
    subject="math",
    knowledge_points=["一元二次方程"],  # 可选过滤
    difficulty_dist={1:0.1, 2:0.2, 3:0.4, 4:0.2, 5:0.1},  # 难度分布（默认）
    type_dist={"选择题":0.4, "填空题":0.2, "解答题":0.4},   # 题型分布（默认）
    count=10,
    exclude_recent=5,   # 排除最近 N 次考过的题
)
```

---

## 5. 科目模板

### 5.1 内置模板

**3_subjects.yaml** (理科3科):
```yaml
subjects:
  - code: math       / name: 数学     / icon: 📐 / 150分 / 120min
  - code: physics    / name: 物理     / icon: ⚡ / 100分 / 90min
  - code: chemistry  / name: 化学     / icon: 🧪 / 100分 / 90min
```

**6_subjects.yaml** (高考6科): 语数英+物化生

**9_subjects.yaml** (全科9科): 语数英+物化生+政史地

### 5.2 自定义模板

```yaml
# my_custom.yaml
name: "考研数学"
description: "考研数学模板"
subjects:
  - code: "advanced_math"
    name: "高等数学"
    icon: "∫"
    typical_score: 150
    exam_duration: 180
question_types:
  - name: "选择题"
    subtypes: ["单选"]
    scoring_mode: "exact"
  - name: "解答题"
    subtypes: ["计算", "证明"]
    scoring_mode: "llm"
```

导入: `TemplateTools.import_template("/path/to/my_custom.yaml")`

应用: `TemplateTools.apply("考研数学")`

---

## 6. 题目管理

### 6.1 通过 Skills (AI 工具)

所有 Skill 工具均通过 `<tool>` XML 标签由 AI 调用。

#### QuestionCRUDTool

```json
// 创建
{"skill":"question_bank","tool":"create_question",
 "subject":"math", "content":"...", "answer":"...",
 "difficulty":3, "type_name":"选择题", "options":["A. xxx", "B. xxx"]}

// 搜索
{"skill":"question_bank","tool":"search_questions",
 "subject":"math", "difficulty":3, "limit":20}

// 获取
{"skill":"question_bank","tool":"get","question_id":42}

// 更新
{"skill":"question_bank","tool":"update","question_id":42,
 "difficulty":4, "content":"更新后内容"}

// 删除
{"skill":"question_bank","tool":"delete","question_id":42}
```

#### QuickQuestionTool (快捷录入)

```json
{"skill":"quick_question","tool":"add_question",
 "subject":"physics", "content":"...", "answer":"...",
 "type_name":"填空题", "difficulty":2}
```

#### BatchImportTool (批量导入)

```json
{"skill":"batch_import","tool":"import_questions",
 "subject":"math",
 "questions":[
   {"content":"...", "answer":"A", "type_name":"选择题"},
   {"content":"...", "answer":"42", "type_name":"填空题"}
 ],
 "mode":"commit"}   // 或 "dry_run" 预览
```

### 6.2 通过代码

```python
# 创建
qid = store.create_question({
    "subject_id": 1,
    "type_id": 1,
    "source": "manual",
    "difficulty": 3,
    "content": "设 f(x)=x²，求 f'(2)",
    "answer": "4",
    "options": ["A. 2", "B. 4", "C. 6", "D. 8"],
    "tags": ["导数", "基础"],
    "knowledge_points": ["derivative.power_rule"],
})

# 查询  
q = store.get_question(qid)
# 返回值自动反序列化 JSON 字段:
# q["options"] → list, q["answer"] → list|str, q["tags"] → list

# 搜索
results = store.search_questions(
    subject="math",
    difficulty=3,
    tags=["导数"],
    knowledge_points=["derivative.power_rule"],
    limit=20, offset=0,
)
```

### 6.3 通过调试 CLI

```bash
python tests/debug_question_bank.py subjects
python tests/debug_question_bank.py types
python tests/debug_question_bank.py count
python tests/debug_question_bank.py list --subject math --limit 10
python tests/debug_question_bank.py get 42
python tests/debug_question_bank.py search "导数"
python tests/debug_question_bank.py errors
python tests/debug_question_bank.py exams
```

---

## 7. 组卷 (Compose)

### 7.1 基本组卷

```json
{"skill":"question_bank","tool":"compose_exam",
 "subject":"math", "count":10, "difficulty":3}
```

### 7.2 按知识点组卷

```json
{"skill":"question_bank","tool":"compose_exam",
 "subject":"physics",
 "count":15,
 "knowledge_points":["牛顿第二定律", "匀变速直线运动"]}
```

### 7.3 自适应组卷（基于弱点）

```json
{"skill":"question_bank","tool":"adaptive_compose",
 "user_id":1, "subject":"chemistry", "count":10}
```

**逻辑**: 查用户错题 → 提取高频错误知识点 → 作为过滤条件组卷

### 7.4 保存为试卷

```python
paper_id = store.create_exam_paper(
    user_id=1,
    title="月考-数学-2024-03",
    subject_id=1,
    question_ids=[1, 2, 3, 5, 8, 13],
    difficulty=3,
    total_score=100,
    time_limit_min=120,
)
```

---

## 8. 考试模拟 (Exam Sim)

### 8.1 架构

```
ExamEngine
  ├── create_session(config)     → 创建考试会话
  ├── start_session(session_id)  → 开始（自动组卷/载入题目）
  ├── submit_answer(sid, idx, answer) → 逐题提交
  ├── submit_session(sid)        → 交卷判分
  ├── auto_submit(sid)           → 超时自动提交
  ├── get_session(sid)           → 获取会话状态
  ├── get_remaining_time(sid)    → 剩余时间
  └── get_user_sessions(uid)     → 用户考试历史

ExamScorer
  ├── score_question(q, answer)  → 单题判分
  ├── score_session(session, questions) → 整卷判分
  └── score_answer_sheet(matched_answers, user_id) → 答题卡格式判分

AnswerSheetMatcher
  ├── match(extracted_questions, subject)  → 文本→题库匹配
  └── from_session(session)               → 会话→答题卡格式
```

### 8.2 考试流程

```
1. create_session(user_id, config)
   → session_id (UUID)

2. start_session(session_id)
   → questions[] + time_limit_sec

3. submit_answer(session_id, question_index, answer)
   → 逐题保存到 answers JSON

4. submit_session(session_id)
   → ExamScorer 逐题判分
   → ErrorAnalyzer 自动分析错题
   → save_exam_result 保存结果
   → 返回 score + details + error_analyses

5. (可选) auto_submit(session_id)
   → 超时场景，自动交卷
```

### 8.3 ExamConfig 参数

```python
ExamConfig(
    subject="math",
    paper_id=None,            # 指定试卷 ID（可填）
    question_ids=[],          # 指定题目列表（可填）
    time_limit_min=120,
    total_score=100,
    difficulty=3,
    title="月考-数学",
    shuffle=True,
    show_result_immediately=False,
)
```

### 8.4 判分细节

- **选择题/判断题**: `_score_exact` → 精确匹配
- **填空题**: `_score_keyword` → 关键词命中率 ≥80% 判对
- **解答题/作文/阅读**: `_score_llm` → LLM 给出 0.0-1.0 评分

---

## 9. 错题分析与复习

### 9.1 错题记录

```json
// AI 触发记录
{"skill":"question_bank","tool":"analyze_error",
 "question_id":42, "user_answer":"A", "user_id":1}
```

判分时自动记录（ExamScorer.score_answer_sheet 内置逻辑）：
- 答案错误 → 调用 ErrorAnalyzer → `store.add_error_log()`
- 若已存在未掌握的记录 → 累加 attempt_count

### 9.2 复习工具 (ExamReviewTool)

```json
// 考试历史
{"skill":"exam_review","tool":"get_exam_history", "user_id":1, "subject":"math"}

// 考试详情
{"skill":"exam_review","tool":"get_exam_detail", "session_id":"xxx-yyy"}

// 错题汇总
{"skill":"exam_review","tool":"get_error_summary", "user_id":1, "subject":"math"}

// 错题列表
{"skill":"exam_review","tool":"get_wrong_questions", "user_id":1, "subject":"math"}

// 标记掌握
{"skill":"exam_review","tool":"mark_mastered", "log_id":5}

// 薄弱点趋势
{"skill":"exam_review","tool":"get_weakness_trend", "user_id":1, "subject":"math", "days":30}
```

### 9.3 可视化: 薄弱知识点分布

```python
weak_points = error_analyzer.get_weak_points(user_id=1, subject="math")
# 返回: [{"code": "derivative.chain_rule", "error_count": 5}, ...]
```

---

## 10. 多通道录入

### 10.1 文档扫描 → HMD 文件 (doc_to_questions)

```json
{"skill":"doc_to_questions","tool":"process_hmd",
 "hmd_path":"/path/to/doc.hmd",
 "subject_code":"math", "user_id":1}
```

**流程**: 读 .hmd → 提取 mdA/mdB → ScannerPipeline.process_text → LLM 提取 → 入库

### 10.2 图片快照 (quest_from_image)

```json
// 预览（不写入）
{"skill":"quest_from_image","tool":"snap_question",
 "file_path":"/path/to/question.jpg",
 "subject":"physics", "preview_only":true}

// 提交（识别+入库）
{"skill":"quest_from_image","tool":"snap_question",
 "file_path":"/path/to/question.jpg",
 "subject":"physics", "preview_only":false}

// 批量
{"skill":"quest_from_image","tool":"snap_batch",
 "file_paths":["img1.jpg","img2.jpg"],
 "subject":"chemistry"}
```

**使用的视觉模型**:
- `Config.VISION_API_KEY` 有值 → `VisionModel`
- 否则 → `LMStudioChat.describe_image`

### 10.3 文本粘贴 (ScannerPipeline 直接)

```python
result = scanner_pipeline.process_text(
    text="1. 计算 2+3×4\n答案: 14\n2. 什么是牛顿第一定律？\n答案: 惯性定律",
    user_id=1,
    subject_code="math",
)
# → {"questions_found": 2, "questions_added": 2, "errors": []}
```

---

## 11. 答题卡批改 (problem_utils 接口)

### 11.1 problem_utils 项目概览

**位置**: `problem_utils/` (同级目录)

**用途**: 浏览器端摄像头实时文档扫描，输出裁剪后的试卷图像。

**核心功能** (纯 OpenCV，无 DSN 依赖):
1. 浏览器摄像头 → 逐帧 POST `/analyze` → OpenCV 检测文档四边形
2. 检测稳定 8 帧 + 清晰度 > 80 → POST `/capture` → 透视矫正 → 保存 `img/` 目录
3. 返回矫正后的图片路径

**技术栈**: Flask + OpenCV + 摄像头前端

### 11.2 对接流程

```
用户拍照 → problem_utils (OpenCV检测+透视矫正)
                    ↓
           矫正后的试卷图像 (img/*.jpg)
                    ↓
      DSN-exp QuestFromImageTool.snap_question()
                    ↓
           LLM 识别题目 + 学生答案
                    ↓
       AnswerSheetMatcher.match()  →  题库匹配
                    ↓
        ExamScorer.score_answer_sheet()  →  判分
                    ↓
       ErrorAnalyzer 错题分析 + error_logs
                    ↓
           ExamReviewTool 查询结果
```

### 11.3 代码级对接示例

```python
# Step 1: 从 problem_utils 获取矫正图片
captured_img = "problem_utils/img/document_20240301_120000_123456.jpg"

# Step 2: QuestFromImageTool 识别题目+答案
from skills.builtin.quest_from_image.tools.quest_from_image import QuestFromImageTool
qfi = QuestFromImageTool()
# 注入 store + tm (由 engine 在初始化时完成)
qfi._store = question_store
qfi._tm = template_manager

result = qfi.snap_question(
    file_path=captured_img,
    subject="math",
    preview_only=False,   # True 只预览不写入
)
# result: {success, questions_found, added_count, added_ids, ...}
```

---

## 12. 调试工具

### 12.1 debug_question_bank.py

```bash
# 交互模式（推荐）
python tests/debug_question_bank.py

# 命令行模式
python tests/debug_question_bank.py subjects     # 科目列表
python tests/debug_question_bank.py types        # 题型列表
python tests/debug_question_bank.py count        # 各科统计
python tests/debug_question_bank.py list         # 列出题目
python tests/debug_question_bank.py get 42       # 查看第42题
python tests/debug_question_bank.py search "导数" # 搜索
python tests/debug_question_bank.py errors       # 错题记录
python tests/debug_question_bank.py exams        # 试卷列表
```

### 12.2 直接查询 SQLite

```bash
sqlite3 .dsn/question_bank.db
.tables
SELECT count(*) FROM questions;
SELECT q.question_id, q.content, s.name FROM questions q
  JOIN subjects s ON q.subject_id = s.subject_id
  LIMIT 5;
```

---

## 13. 与 problem_utils 的对接设计

### 13.1 当前状态

| 组件 | DSN-exp 题库系统 | problem_utils |
|------|------------------|---------------|
| 题目存储 | ✅ 完整 CRUD + SQLite | ❌ 无 |
| 组卷 | ✅ ComposeParams + adaptive | ❌ 无 |
| 判分 | ✅ ExamScorer (exact/keyword/LLM) | ❌ 无 |
| 错题分析 | ✅ ErrorAnalyzer + LLM | ❌ 无 |
| 摄像头扫描 | ❌ 无 | ✅ OpenCV 文档检测+矫正 |
| 图片识题 | ✅ QuestFromImageTool | ❌ 无（需由 LLM 完成） |
| 答题卡匹配 | ✅ AnswerSheetMatcher | ❌ 无 |
| 考试模拟 | ✅ ExamEngine 全流程 | ❌ 无 |

### 13.2 推荐对接方案

```
problem_utils (摄像头 → 矫正图像)
        ↓ HTTP POST /capture (返回 filename)
        ↓
    DSN-exp 侧接收:
        ↓
    QuestFromImageTool.snap_question(file_path, subject, preview_only=False)
        ↓ 同时提取：题目内容 + 学生手写答案
        ↓
    AnswerSheetMatcher.match(extracted_questions, subject)
        ↓ 匹配题库中的题目
        ↓
    ExamScorer.score_answer_sheet(matched_answers, user_id)
        ↓ 自动判分 + 错题分析
        ↓
    ExamReviewTool 呈现结果
```

### 13.3 关键数据流

```
problem_utils 输出:
  → filename: "document_20240301_120000_123456.jpg"
  → img_path: "problem_utils/img/..."

DSN-exp 输入 (AnswerSheetMatcher.match 所需):
  extracted_questions = [
    {
      "question_index": 0,
      "question_text": "1+1=?",
      "student_answer": "2"
    },
    {
      "question_index": 1,
      "question_text": "牛顿第一定律的内容是？",
      "student_answer": "惯性定律"
    }
  ]

DSN-exp 输出:
  → score, correct_count, total_count
  → details[] (逐题得分)
  → error_analyses[] (错题分析)
  → error_logs 自动记录
```

### 13.4 集成检查清单

- [ ] problem_utils 保存的图片路径可被 DSN-exp 访问
- [ ] QuestFromImageTool 注入 store + tm (engine 初始化)
- [ ] AnswerSheetMatcher 注入 store
- [ ] ExamScorer 注入 store + models_plugin
- [ ] ErrorAnalyzer 注入 store + models_plugin
- [ ] 配置 `VISION_API_KEY` 或 LMStudio 视觉模型可用

---

## 附录

### A. 数据库路径

```
默认: DSN-exp/.dsn/question_bank.db
可配置: QuestionBankDBManager(db_path="自定义路径")
```

### B. 预置题型 ID

| type_id | name | subtype | scoring_mode |
|---------|------|---------|--------------|
| 1 | 选择题 | 单选 | exact |
| 2 | 选择题 | 多选 | exact |
| 3 | 填空题 | 填空 | keyword |
| 4 | 解答题 | 计算 | llm |
| 5 | 解答题 | 证明 | llm |
| 6 | 解答题 | 简答 | llm |
| 7 | 判断题 | 判断 | exact |
| 8 | 作文题 | 作文 | llm |
| 9 | 阅读理解 | 阅读 | llm |

### C. 配置文件位置

| 文件 | 路径 |
|------|------|
| 内置模板 (3科) | `skills/builtin/question_bank/templates/3_subjects.yaml` |
| 内置模板 (6科) | `skills/builtin/question_bank/templates/6_subjects.yaml` |
| 内置模板 (9科) | `skills/builtin/question_bank/templates/9_subjects.yaml` |
| 自定义模板 | `skills/builtin/question_bank/templates/custom/*.yaml` |
| 调试工具 | `tests/debug_question_bank.py` |

### D. 关键类间依赖图

```
QuestionBankDBManager (SQLite)
       ↓
  QuestionStore ←── ExamComposer
       ↑              ↑
       │              │
  ScannerPipeline─── ExamScorer
       │              ↑
       │              │
  ErrorAnalyzer ←── AnswerSheetMatcher
       │
       ↓
  ModelsPlugin (LLM, 外部依赖)
```
