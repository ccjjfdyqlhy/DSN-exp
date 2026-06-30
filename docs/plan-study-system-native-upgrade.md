# 学习系统 Native Tool Call 升级策划案

> 版本: v1.0 | 日期: 2026-06-30
> 基于 `toolcall_native_upgrade_plan.md` 中已完成的技能加载器重构和 ToolPlugin 改造，将学习系统（题库/知识图谱/考试模拟）从 XML 标签全面升级为 Native Function Calling。

---

## 目录

1. [现状审计](#1-现状审计)
2. [升级目标](#2-升级目标)
3. [总体架构](#3-总体架构)
4. [知识图谱模块迁移](#4-知识图谱模块迁移)
5. [考试模拟模块迁移](#5-考试模拟模块迁移)
6. [题库模块清理](#6-题库模块清理)
7. [文档录入技能清理](#7-文档录入技能清理)
8. [依赖注入重构](#8-依赖注入重构)
9. [兼容性与降级](#9-兼容性与降级)
10. [实施计划](#10-实施计划)
11. [涉及文件清单](#11-涉及文件清单)

---

## 1. 现状审计

### 1.1 当前架构下学习系统的工具调用方式

```
┌──────────────────────────────────────────────────────────────────┐
│                          LLM 输出                                 │
├──────────────────────────────────────────────────────────────────┤
│  Native 模式 (默认):                                              │
│    模型通过 tools API 参数获取工具定义                              │
│    通过 tool_calls 数组调用工具                                    │
│    当前状态: question_bank 9 工具有注册，knowledge_graph          │
│    和 exam_sim 无注册                                              │
├──────────────────────────────────────────────────────────────────┤
│  XML 降级模式:                                                     │
│    模型通过系统提示词中的 instruction.md 了解工具                    │
│    通过 XML 标签调用工具                                           │
│    当前状态: 三大模块全依赖此模式                                    │
└──────────────────────────────────────────────────────────────────┘
```

### 1.2 审计结果汇总

| 模块 | 是否有 skill.yaml | 工具注册数 | XML 标签残留 | Native 下是否可用 |
|------|:-:|:-:|:-:|:-:|
| **question_bank** | ✅ | 9 工具 | `<qb_query>` `<qb_store>` `<qb_compose>` `<qb_analyze>` | ⚠️ 部分可用（YAML 工具能调，但 Plugin 中 XML 功能不可达） |
| **knowledge_graph** | ❌ 无 | 0 | `<kg_update>` `<kg_recommend>` `<kg_build>` | ❌ 完全不可用 |
| **exam_sim** | ❌ 无 | 0 | 无 XML，但关键字匹配（用户触发型） | ❌ LLM 无法主动调用 |
| **doc_to_questions** | ✅ | 2 工具 | instruction.md 含 `<tool>` 示例 | ✅ 可用但 instruction.md 有误导 |

### 1.3 核心问题

1. **knowledge_graph** — 顶层 Python 包，没有 skill.yaml，Plugin 只解析 XML 标签。Native 模式下 LLM 零知识图谱工具可用。
2. **exam_sim** — 顶层 Python 包，没有 skill.yaml。Plugin 靠用户消息关键词（"开始考试"等）触发，LLM 无法主动创建/管理考试。
3. **question_bank** — YAML skill 存在，但 Plugin 中仍有 4 种 XML 标签解析（`<qb_query>` 等），功能碎片化且 native 模式下变成死代码。
4. **依赖注入** — `engine.py:1402-1419` 通过 `_tool_instances.items()` + `key.startswith()` 字符串匹配手动注入依赖，脆弱且不透明。

---

## 2. 升级目标

| 目标 | 说明 |
|------|------|
| **G1** | 学习系统所有工具通过 YAML skill.yaml 定义，统一由 `SkillRegistry.get_tools_schema()` 生成 API schema |
| **G2** | 消除 Plugin 中的 XML 标签解析，统一走 `ToolPlugin._handle_native_tool_calls()` + `SkillRegistry.call_tool()` |
| **G3** | knowledge_graph + exam_sim 从顶层 Python 包转为 `skills/builtin/` 下的标准技能 |
| **G4** | Plugin 保留用于 PRE_PROCESS/POST_PROCESS 上下文注入，但不再执行工具 |
| **G5** | 依赖注入通过 `skill.yaml` 的 `dependencies` 字段自动完成 |

---

## 3. 总体架构

### 3.1 升级后调用流程

```
Native Mode:
  LLM 收到 tools API 参数（含学习系统全部工具定义）
    ↓
  LLM 返回 tool_calls: [{function: {name: "skill-knowledge_graph-update_state", arguments: {...}}}]
    ↓
  ToolPlugin._handle_native_tool_calls()
    ↓  (命名空间: skill-{skill_name}-{tool_name})
  SkillRegistry.call_tool("knowledge_graph", "update_state", args)
    ↓
  Python 工具方法执行 → 返回结果
    ↓
  Agent Loop: role:"tool" 消息 → 继续对话

XML Fallback:
  LLM 输出 <tool>{"skill":"knowledge_graph","tool":"update_state","params":{...}}</tool>
    ↓
  ToolPlugin._handle_xml_tool_tags()  ← 保留作为降级
```

### 3.2 模块依赖关系

```
┌─────────────────────┐     ┌──────────────────────────────┐
│   skills/builtin/   │     │    plugins/builtin/           │
├─────────────────────┤     ├──────────────────────────────┤
│ question_bank/      │     │ question_bank_plugin.py      │
│   skill.yaml (9t)   │◄────│   PRE: 注入错题统计          │
│   tools/*.py        │     │   POST: 注入扫描结果 (移除XML)│
├─────────────────────┤     ├──────────────────────────────┤
│ knowledge_graph/    │◄────│ knowledge_graph_plugin.py    │
│   skill.yaml (6t)   │     │   PRE: 注入待复习知识点      │
│   tools/*.py        │     │   POST: 消除 (空壳/移除)     │
├─────────────────────┤     ├──────────────────────────────┤
│ exam_sim/           │◄────│ exam_sim_plugin.py           │
│   skill.yaml (4t)   │     │   PRE: 关键字检测 + 超时     │
│   tools/*.py        │     │   POST: 消除                 │
├─────────────────────┤     └──────────────────────────────┘
│ doc_to_questions/   │
│   skill.yaml (2t)   │
│   tools/*.py        │
└─────────────────────┘
```

---

## 4. 知识图谱模块迁移

### 4.1 当前状态

- **位置**: `knowledge_graph/` — 顶层 Python 包，含 `graph_store.py`, `graph_engine.py`, `builder.py`, `matcher.py`, `models.py`
- **插件**: `plugins/builtin/knowledge_graph_plugin.py` — 在 `_pre_process` 注入待复习知识点，`_post_process` 解析 `<kg_update>`, `<kg_recommend>`, `<kg_build>` XML 标签
- **问题**: 无 YAML skill，LLM 在 native 模式下没有任何知识图谱工具可用

### 4.2 迁移方案

#### 步骤 A: 创建 skill.yaml

新建 `skills/builtin/knowledge_graph/skill.yaml`：

```yaml
name: knowledge_graph
display_name: "Knowledge Graph"
description: "知识图谱 - 知识点追踪、薄弱路径分析、间隔复习推荐、图谱构建"
version: "1.0"
author: "system"
source: "builtin"
enabled: true
status: "active"
prompt_category: "skills"
prompt_priority: 72

tools:
  - name: update_knowledge_state
    display_name: "Update Knowledge State"
    description: "更新用户对某个知识点的掌握状态（答对/答错后调用）"
    module: "tools.knowledge_tools"
    class: "KnowledgeGraphTool"
    methods:
      - name: update_knowledge_state
        description: "记录答题结果，更新置信度和下次复习时间"
        parameters:
          kp_code:
            type: string
            description: "知识点代码，如 KP-MATH-001"
            required: true
          correct:
            type: boolean
            description: "是否回答正确"
            required: true
          user_id:
            type: integer
            description: "用户 ID"
            default: 0

  - name: get_due_reviews
    display_name: "Get Due Reviews"
    description: "获取当前到期待复习的知识点列表"
    module: "tools.knowledge_tools"
    class: "KnowledgeGraphTool"
    methods:
      - name: get_due_reviews
        description: "返回需要复习的知识点（按到期时间排序）"
        parameters:
          user_id:
            type: integer
            description: "用户 ID"
            default: 0
          subject:
            type: string
            description: "学科代码（可选）"
          limit:
            type: integer
            description: "返回条数"
            default: 5

  - name: analyze_weakness
    display_name: "Analyze Weakness"
    description: "薄弱路径分析：从薄弱知识点 BFS 回溯到根本原因"
    module: "tools.knowledge_tools"
    class: "KnowledgeGraphTool"
    methods:
      - name: analyze_weakness
        description: "分析薄弱知识点路径"
        parameters:
          kp_code:
            type: string
            description: "知识点代码"
            required: true
          user_id:
            type: integer
            description: "用户 ID"
            default: 0

  - name: recommend_related
    display_name: "Recommend Related Knowledge"
    description: "关联知识点推荐（沿边扩散）"
    module: "tools.knowledge_tools"
    class: "KnowledgeGraphTool"
    methods:
      - name: recommend_related
        description: "推荐与指定知识点相关的其他知识点"
        parameters:
          kp_code:
            type: string
            description: "知识点代码"
            required: true
          depth:
            type: integer
            description: "扩散深度"
            default: 2

  - name: get_mastery_summary
    display_name: "Get Mastery Summary"
    description: "获取学科掌握度概览"
    module: "tools.knowledge_tools"
    class: "KnowledgeGraphTool"
    methods:
      - name: get_mastery_summary
        description: "返回学科的掌握/薄弱/未学统计"
        parameters:
          subject:
            type: string
            description: "学科代码"
            required: true
          user_id:
            type: integer
            description: "用户 ID"
            default: 0

  - name: build_from_syllabus
    display_name: "Build Knowledge Graph"
    description: "从教材/考纲文本构建知识图谱"
    module: "tools.knowledge_tools"
    class: "KnowledgeGraphTool"
    methods:
      - name: build_from_syllabus
        description: "利用 LLM 从文本提取知识点结构并入库"
        parameters:
          subject:
            type: string
            description: "学科代码"
            required: true
          content:
            type: string
            description: "教材或考纲文本"
            required: true
          user_id:
            type: integer
            description: "用户 ID"
            default: 0

activation:
  keywords: ["知识点", "知识图谱", "薄弱", "复习", "掌握", "知识库",
             "knowledge", "review", "mastery", "图谱"]
  auto_activate: false

dependencies:
  - graph_store
  - graph_engine
  - knowledge_matcher
  - models_plugin
  - question_store
tags: [knowledge, graph, study, review, mastery]
```

#### 步骤 B: 创建 tools/knowledge_tools.py

```python
# skills/builtin/knowledge_graph/tools/knowledge_tools.py

class KnowledgeGraphTool:

    def __init__(self, graph_store=None, graph_engine=None,
                 knowledge_matcher=None, models_plugin=None,
                 question_store=None):
        self._store = graph_store
        self._engine = graph_engine
        self._matcher = knowledge_matcher
        self._models = models_plugin
        self._question_store = question_store

    def update_knowledge_state(self, kp_code: str, correct: bool,
                               user_id: int = 0, **kwargs) -> dict:
        if not self._store:
            return {"error": "GraphStore 未初始化"}
        self._store.update_user_state(user_id, kp_code, correct)
        if correct and self._engine:
            self._engine.propagate_mastery(user_id, kp_code)
        state = self._store.get_user_state(user_id, kp_code)
        return {
            "success": True,
            "confidence": state.get("confidence", 0) if state else 0,
            "kp_code": kp_code,
        }

    def get_due_reviews(self, user_id: int = 0, subject: str = None,
                        limit: int = 5, **kwargs) -> dict:
        if not self._engine:
            return {"error": "GraphEngine 未初始化"}
        due = self._engine.recommend_review(user_id, limit=limit)
        if subject:
            due = [d for d in due if d.get("subject") == subject]
        return {
            "success": True,
            "due_count": len(due),
            "items": due,
        }

    def analyze_weakness(self, kp_code: str, user_id: int = 0,
                         **kwargs) -> dict:
        if not self._engine:
            return {"error": "GraphEngine 未初始化"}
        path = self._engine.find_weak_path(user_id, kp_code)
        return {
            "success": True,
            "path": path,
            "path_length": len(path),
            "root_cause": path[0] if path else None,
        }

    def recommend_related(self, kp_code: str, depth: int = 2,
                          **kwargs) -> dict:
        if not self._engine:
            return {"error": "GraphEngine 未初始化"}
        related = self._engine.find_related(kp_code, depth=depth)
        return {
            "success": True,
            "related_count": len(related),
            "items": related,
        }

    def get_mastery_summary(self, subject: str, user_id: int = 0,
                            **kwargs) -> dict:
        if not self._engine:
            return {"error": "GraphEngine 未初始化"}
        summary = self._engine.get_mastery_summary(user_id, subject)
        return {
            "success": True,
            "subject": subject,
            **summary,
        }

    def build_from_syllabus(self, subject: str, content: str,
                            user_id: int = 0, **kwargs) -> dict:
        from knowledge_graph.builder import KnowledgeGraphBuilder
        builder = KnowledgeGraphBuilder(
            graph_store=self._store,
            models_plugin=self._models,
        )
        if len(content) > 8000:
            content = content[:8000]
        result = builder.build_from_syllabus(subject, content)
        return result
```

#### 步骤 C: 清理 Plugin 中的 XML 解析

修改 `plugins/builtin/knowledge_graph_plugin.py`：

```python
class KnowledgeGraphPlugin(Plugin):
    name = "knowledge_graph"
    description = "知识图谱 - 上下文注入（不再执行工具）"
    hooks = [HookPoint.PRE_PROCESS]  # 移除 POST_PROCESS
    priority = 22

    def __init__(self, graph_store=None, graph_engine=None,
                 knowledge_matcher=None, question_store=None):
        self._store = graph_store
        self._engine = graph_engine
        self._matcher = knowledge_matcher
        self._question_store = question_store

    def on_load(self) -> None:
        if self._store is None:
            logger.warning("GraphStore 未注入")

    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        if hook == HookPoint.PRE_PROCESS:
            return self._pre_process(ctx)
        return ctx

    def _pre_process(self, ctx: PluginContext) -> PluginContext:
        # 仅保留上下文注入功能
        if self._engine:
            try:
                due = self._engine.recommend_review(ctx.user_id, limit=3)
                if due:
                    names = [
                        d.get("kp_name", d.get("kp_code", ""))
                        for d in due
                    ]
                    ctx.system_prompt += (
                        f"\n[知识图谱] 今日待复习知识点: {'、'.join(names)}。"
                    )
            except Exception as e:
                logger.warning("复习推荐失败: %s", e)
        return ctx
```

关键变更：
- 移除 `POST_PROCESS` hook
- 移除所有 XML 标签正则解析代码
- 工具执行全部交由 `SkillRegistry.call_tool()` 处理

### 4.3 注入方式升级

在 `engine.py` 中，知识图谱工具的依赖注入通过 `SkillLoader` 的 `deps` 参数自动完成：

```python
# engine.py — 新注入方式
if skill_registry and graph_store:
    try:
        skill = skill_registry.get_skill("knowledge_graph")
        if skill:
            tool_instances = skill_registry.get_tool_instances("knowledge_graph")
            for inst in tool_instances:
                inst._store = graph_store
                inst._engine = graph_engine
                inst._matcher = knowledge_matcher
                inst._models = models_plugin
                inst._question_store = question_store
    except Exception as e:
        logger.warning("knowledge_graph 技能注入失败: %s", e)
```

---

## 5. 考试模拟模块迁移

### 5.1 当前状态

- **位置**: `exam_sim/` — 顶层 Python 包，含 `engine.py`, `scorer.py`, `models.py`, `prompts.py`
- **插件**: `plugins/builtin/exam_sim_plugin.py` — 在 `PRE_FILTER` 检测超时自动提交，`PRE_PROCESS` 检测用户消息关键词
- **问题**: 无 YAML skill，LLM 无法主动创建/管理考试

### 5.2 迁移方案

#### 步骤 A: 创建 skill.yaml

新建 `skills/builtin/exam_sim/skill.yaml`：

```yaml
name: exam_sim
display_name: "Exam Simulator"
description: "考试模拟 - 创建/管理/评分考试会话"
version: "1.0"
author: "system"
source: "builtin"
enabled: true
status: "active"
prompt_category: "skills"
prompt_priority: 68

tools:
  - name: create_exam
    display_name: "Create Exam"
    description: "创建新的考试会话（组卷 + 初始化）"
    module: "tools.exam_tools"
    class: "ExamSimTool"
    methods:
      - name: create_exam
        description: "按配置创建考试，自动组卷"
        parameters:
          subject:
            type: string
            description: "学科代码 (math/physics/chemistry/english/chinese)"
            required: true
          question_count:
            type: integer
            description: "题目数量"
            default: 10
          time_limit_min:
            type: integer
            description: "时间限制（分钟）"
            default: 120
          difficulty:
            type: integer
            description: "难度 1-5"
            default: 3

  - name: start_exam
    display_name: "Start Exam"
    description: "开始考试（将状态从 configuring 转为 in_progress）"
    module: "tools.exam_tools"
    class: "ExamSimTool"
    methods:
      - name: start_exam
        description: "开始考试会话，返回题目列表和倒计时"
        parameters:
          session_id:
            type: string
            description: "考试会话 ID"
            required: true

  - name: submit_answer
    display_name: "Submit Answer"
    description: "提交单题答案"
    module: "tools.exam_tools"
    class: "ExamSimTool"
    methods:
      - name: submit_answer
        description: "提交某道题的答案"
        parameters:
          session_id:
            type: string
            description: "考试会话 ID"
            required: true
          question_index:
            type: integer
            description: "题目序号（从 0 开始）"
            required: true
          answer:
            type: string
            description: "用户答案"
            required: true

  - name: finish_exam
    display_name: "Finish Exam"
    description: "提交整张试卷并判分"
    module: "tools.exam_tools"
    class: "ExamSimTool"
    methods:
      - name: finish_exam
        description: "交卷，执行判分，返回成绩报告"
        parameters:
          session_id:
            type: string
            description: "考试会话 ID"
            required: true

activation:
  keywords: ["考试", "模拟考", "测验", "exam", "test", "quiz",
             "组卷", "判分", "交卷"]
  auto_activate: false

dependencies:
  - exam_engine
  - exam_scorer
  - question_store
tags: [exam, sim, study, test, quiz]
```

#### 步骤 B: 创建 tools/exam_tools.py

```python
# skills/builtin/exam_sim/tools/exam_tools.py


class ExamSimTool:

    def __init__(self, exam_engine=None, exam_scorer=None,
                 question_store=None):
        self._engine = exam_engine
        self._scorer = exam_scorer
        self._store = question_store

    def create_exam(self, subject: str, question_count: int = 10,
                    time_limit_min: int = 120, difficulty: int = 3,
                    user_id: int = 0, **kwargs) -> dict:
        if not self._engine:
            return {"error": "ExamEngine 未初始化"}
        config = {
            "subject": subject,
            "total_count": question_count,
            "time_limit_min": time_limit_min,
            "difficulty": difficulty,
        }
        result = self._engine.create_session(user_id, config)
        return result

    def start_exam(self, session_id: str, **kwargs) -> dict:
        if not self._engine:
            return {"error": "ExamEngine 未初始化"}
        result = self._engine.start_session(session_id)
        if result.get("success"):
            questions = result.get("questions", [])
            return {
                "success": True,
                "session_id": session_id,
                "time_limit_sec": result.get("time_limit_sec", 0),
                "question_count": len(questions),
                "questions": [
                    {
                        "index": i,
                        "content": q.get("content", ""),
                        "type_name": q.get("type_name", ""),
                        "difficulty": q.get("difficulty"),
                    }
                    for i, q in enumerate(questions)
                ],
            }
        return result

    def submit_answer(self, session_id: str, question_index: int,
                      answer: str, **kwargs) -> dict:
        if not self._engine:
            return {"error": "ExamEngine 未初始化"}
        return self._engine.submit_answer(session_id, question_index, answer)

    def finish_exam(self, session_id: str, **kwargs) -> dict:
        if not self._engine:
            return {"error": "ExamEngine 未初始化"}
        result = self._engine.submit_session(session_id)
        if result.get("success"):
            return {
                "success": True,
                "session_id": session_id,
                "score": result.get("score", 0),
                "max_score": result.get("max_score", 0),
                "correct_count": result.get("correct_count", 0),
                "total_count": result.get("total_count", 0),
                "duration_sec": result.get("duration_sec", 0),
                "correct_rate": round(
                    result.get("correct_count", 0) / max(result.get("total_count", 1), 1) * 100, 1
                ),
            }
        return result
```

#### 步骤 C: 精简 Plugin

`plugins/builtin/exam_sim_plugin.py` 保留 `PRE_FILTER` 超时检测和 `PRE_PROCESS` 关键字触发，但工具执行统一走 skill：

```python
class ExamSimPlugin(Plugin):
    name = "exam_sim"
    description = "考试模拟 - 超时检测 + 关键字触发"
    hooks = [HookPoint.PRE_FILTER, HookPoint.PRE_PROCESS]
    priority = 18

    def __init__(self, exam_engine=None, scorer=None):
        self._engine = exam_engine
        self._scorer = scorer

    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        if hook == HookPoint.PRE_FILTER:
            return self._check_timeout(ctx)
        if hook == HookPoint.PRE_PROCESS:
            return self._pre_process(ctx)
        return ctx

    def _check_timeout(self, ctx: PluginContext) -> PluginContext:
        # 保留超时自动提交
        session_id = ctx.extra.get("exam_session_id")
        if not session_id or not self._engine:
            return ctx
        if self._engine.is_timeout(session_id):
            result = self._engine.auto_submit(session_id)
            ctx.extra["exam_auto_submitted"] = result
        return ctx

    def _pre_process(self, ctx: PluginContext) -> PluginContext:
        # 保留关键字检测，但不再直接执行—注入标记由后续 tool call 处理
        message = ctx.message.lower()
        exam_cmds = ["开始考试", "start exam", "提交试卷", "submit exam",
                     "开始作答", "交卷", "查看成绩"]
        if any(cmd in message for cmd in exam_cmds):
            ctx.extra["exam_command"] = True

        # 保留倒计时信息
        session_id = ctx.extra.get("exam_session_id")
        if session_id and self._engine:
            remaining = self._engine.get_remaining_time(session_id)
            ctx.extra["exam_remaining"] = remaining
            ctx.extra["exam_in_progress"] = True
        return ctx
```

---

## 6. 题库模块清理

### 6.1 当前状态

- **skill.yaml**: 已存在 `skills/builtin/question_bank/skill.yaml`，9 个工具定义完整
- **Plugin**: `plugins/builtin/question_bank_plugin.py` 同时存在 XML 标签解析（4 种标签）和扫描结果注入
- **问题**: 功能碎片化 — YAML 工具有 create/search/delete/compose/analyze/stats/recommend，Plugin XML 有 query/store/compose/analyze（部分重叠）

### 6.2 清理方案

#### 步骤 A: 补充 YAML 工具定义

在 `skill.yaml` 中补充缺失的方法：
- 添加 `batch_store` 方法（对应旧 `<qb_store>` 的批量入库能力）
- 确认 `update_question` 方法存在（instruction.md 中提到了但 YAML 中没有）

修改 `skills/builtin/question_bank/skill.yaml`，在 `methods` 下补充新方法定义。

#### 步骤 B: 移除 Plugin 中的 XML 解析

精简 `question_bank_plugin.py`，移除 `_post_process` 中的 XML 标签解析和清理，仅保留上下文注入：

```python
class QuestionBankPlugin(Plugin):
    name = "question_bank"
    description = "题库系统 - 上下文注入"
    hooks = [HookPoint.PRE_PROCESS]  # 移除 POST_PROCESS
    priority = 20

    def __init__(self, question_store=None, models_plugin=None,
                 exam_composer=None, error_analyzer=None,
                 scanner_pipeline=None):
        self._store = question_store
        self._models = models_plugin
        self._composer = exam_composer
        self._analyzer = error_analyzer
        self._scanner = scanner_pipeline

    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        if hook == HookPoint.PRE_PROCESS:
            return self._pre_process(ctx)
        return ctx

    def _pre_process(self, ctx: PluginContext) -> PluginContext:
        if self._store:
            try:
                error_count = self._store.get_total_errors(ctx.user_id)
            except Exception:
                error_count = 0
            if error_count > 0:
                ctx.system_prompt += (
                    f"\n[题库系统] 你有 {error_count} 道错题待复习。"
                )
        return ctx
```

---

## 7. 文档录入技能清理

### 7.1 当前状态

- **skill.yaml**: 已存在 `skills/builtin/doc_to_questions/skill.yaml`，2 个工具定义完整
- **instruction.md**: 仍然展示旧式 `<tool>` XML 调用示例
- **影响**: Native 模式下 instruction.md 被跳过不影响功能，但 XML 降级模式下会误导 LLM

### 7.2 清理方案

更新 `skills/builtin/doc_to_questions/prompts/instruction.md`，移除 `<tool>` XML 示例，改为自然语言描述：

```markdown
# 文档录入题库技能

你可以将已处理的扫描文档或原始文本中的题目批量提取并录入题库系统。

## 使用场景

1. **从扫描文档（.hmd）录入** — 用户扫描试卷后，先用文档技能扫描和处理，再用本技能的 process_hmd 工具提取题目入库
2. **从原始文本录入** — 用户直接粘贴题目文本，调用 process_text 工具提取入库

## 完整流程（扫描 → 录入）

1. 扫描文档 → document.scan 获取图片
2. 图片 → document.process_scan 获得 .hmd 文件路径
3. .hmd → doc_to_questions.process_hmd 提取题目 → 自动入库
4. 或：先用 document.read_hmd 读取内容让用户确认，再调 process_text 录入

## 注意

- 录入后 AI 会自动调用 LLM 从文本中识别每道题的内容、答案、题型、难度等
- 提取结果包含：找到题目数、成功入库数、失败数
```

---

## 8. 依赖注入重构

### 8.1 当前问题

`engine.py:1402-1419` 使用脆弱的方式注入依赖：

```python
for key, instance in skill_registry._tool_instances.items():
    if key.startswith("question_bank.create_question") or ...:
        instance._store = question_store       # 直接操作私有属性
        instance._tm = template_manager        # 工具类构造函数形参不统一
```

问题：
- 直接遍历 `_tool_instances`（私有属性）
- 字符串前缀匹配，易错且不灵活
- 硬编码属性名，与构造函数解耦
- 新增技能时必须手动添加注入代码

### 8.2 新方案

向 `SkillRegistry` 添加标准注入接口：

```python
# skills/registry.py

class SkillRegistry:
    def inject_dependencies(self, skill_name: str, **deps) -> bool:
        """向指定技能的所有工具实例注入依赖"""
        skill = self._active_skills.get(skill_name)
        if not skill:
            logger.warning("技能不存在: %s", skill_name)
            return False

        count = 0
        for tool_spec in skill.tools:
            key = f"{skill_name}.{tool_spec.name}"
            instance = self._tool_instances.get(key)
            if not instance:
                continue
            # 只注入工具实例已有的属性
            for dep_name, dep_value in deps.items():
                if hasattr(instance, dep_name):
                    setattr(instance, dep_name, dep_value)
                    count += 1
                else:
                    logger.debug("工具 %s 无属性 %s，跳过", key, dep_name)
        return count > 0
```

在 `engine.py` 中使用：

```python
# 学习系统技能注入 — 新方式
if skill_registry:
    if question_store and template_manager and models_plugin:
        skill_registry.inject_dependencies("question_bank",
            _store=question_store,
            _tm=template_manager,
            _models=models_plugin,
        )

    if graph_store and graph_engine and knowledge_matcher:
        skill_registry.inject_dependencies("knowledge_graph",
            _store=graph_store,
            _engine=graph_engine,
            _matcher=knowledge_matcher,
            _models=models_plugin,
            _question_store=question_store,
        )

    if exam_engine and exam_scorer:
        skill_registry.inject_dependencies("exam_sim",
            _engine=exam_engine,
            _scorer=exam_scorer,
            _store=question_store,
        )

    if scanner_pipeline:
        skill_registry.inject_dependencies("doc_to_questions",
            _pipeline=scanner_pipeline,
        )
```

---

## 9. 兼容性与降级

### 9.1 双模式支持

| 模式 | 工具定义来源 | 工具调用方式 | 学习系统行为 |
|------|-------------|-------------|-------------|
| **native** | `tools` API 参数（SkillRegistry 生成） | `tool_calls` 数组 | 全部通过 YAML skill 执行 |
| **xml** | `instruction.md` 注入到 system prompt | `<tool>` XML 标签 | instruction.md 描述工具有限，Plugin XML 标签为主 |

### 9.2 迁移过渡策略

1. **Phase 1** — 创建 YAML skill + tools，Plugin 保留 XML 解析作为双路冗余
2. **Phase 2** — 确认 native 模式稳定后，移除 Plugin XML 解析，仅保留上下文注入
3. **Phase 3** — XML 降级模式下，Plugin 中的 XML 标签解析可用 `SkillRegistry.call_tool()` 作为后端

### 9.3 降级模式下 Plugin 复用 SkillRegistry

XML 降级模式下，Plugin 不再直接操作底层引擎，而是委托给 SkillRegistry：

```python
# 降级模式下的知识图谱 Plugin（Phase 3 可选改造）
def _post_process(self, ctx):
    reply = ctx.original_reply
    kg_matches = re.findall(r'<kg_update>(.*?)</kg_update>', reply, re.DOTALL)
    for match in kg_matches:
        params = json.loads(match.strip())
        result = self._skill_registry.call_tool(
            "knowledge_graph", "update_knowledge_state", params
        )
        ctx.extra["kg_update_result"] = result
    # ... 清理标签 ...
```

这样 XML 降级模式和 native 模式共享同一套工具实现。

---

## 10. 实施计划

### Phase 1 — knowledge_graph 迁移 (3-4 天)

- [ ] 创建 `skills/builtin/knowledge_graph/skill.yaml` — 6 个工具定义
- [ ] 创建 `skills/builtin/knowledge_graph/tools/knowledge_tools.py` — 工具实现
- [ ] 创建 `skills/builtin/knowledge_graph/prompts/instruction.md` — 自然语言说明
- [ ] 精简 `plugins/builtin/knowledge_graph_plugin.py` — 移除 XML 标签解析
- [ ] 更新 `engine.py` 注入逻辑 — 使用 `inject_dependencies()`

### Phase 2 — exam_sim 迁移 (2-3 天)

- [ ] 创建 `skills/builtin/exam_sim/skill.yaml` — 4 个工具定义
- [ ] 创建 `skills/builtin/exam_sim/tools/exam_tools.py` — 工具实现
- [ ] 创建 `skills/builtin/exam_sim/prompts/instruction.md`
- [ ] 精简 `plugins/builtin/exam_sim_plugin.py` — 保留超时检测和关键字触发的标记注入
- [ ] 更新 `engine.py` 注入逻辑

### Phase 3 — question_bank 清理 (1-2 天)

- [ ] 在 `skill.yaml` 中补充缺失的 `update` 和 `batch_store` 方法定义
- [ ] 更新 `question_crud.py` 确保 `update` 方法对齐 YAML 参数
- [ ] 精简 `plugins/builtin/question_bank_plugin.py` — 移除 XML 标签解析
- [ ] 更新 `instruction.md` — 移除 `update_question` 不存在工具的引用

### Phase 4 — doc_to_questions 清理 + 全局 (1 天)

- [ ] 更新 `skills/builtin/doc_to_questions/prompts/instruction.md` — 移除 `<tool>` 示例
- [ ] 实现 `SkillRegistry.inject_dependencies()` 方法
- [ ] 重构 `engine.py` 中的注入逻辑
- [ ] 清理 `engine.py` 中旧的 `key.startswith()` 注入代码

### Phase 5 — 验证 (2 天)

- [ ] 验证 native 模式下 knowledge_graph 6 工具有 schema 注册
- [ ] 验证 native 模式下 exam_sim 4 工具有 schema 注册
- [ ] 验证 Agent Loop 多轮 tool call 正常
- [ ] 验证 XML 降级模式仍然可工作
- [ ] 验证依赖注入不破坏现有功能

**总工期预估: 9-12 天**

---

## 11. 涉及文件清单

### 新建文件

| 文件 | 说明 |
|------|------|
| `skills/builtin/knowledge_graph/skill.yaml` | 知识图谱技能定义（6 工具） |
| `skills/builtin/knowledge_graph/__init__.py` | 空包 |
| `skills/builtin/knowledge_graph/tools/__init__.py` | 空包 |
| `skills/builtin/knowledge_graph/tools/knowledge_tools.py` | 知识图谱工具实现 |
| `skills/builtin/knowledge_graph/prompts/instruction.md` | 知识图谱技能提示词 |
| `skills/builtin/exam_sim/skill.yaml` | 考试模拟技能定义（4 工具） |
| `skills/builtin/exam_sim/__init__.py` | 空包 |
| `skills/builtin/exam_sim/tools/__init__.py` | 空包 |
| `skills/builtin/exam_sim/tools/exam_tools.py` | 考试模拟工具实现 |
| `skills/builtin/exam_sim/prompts/instruction.md` | 考试模拟技能提示词 |

### 修改文件

| 文件 | 改动 |
|------|------|
| `skills/builtin/question_bank/skill.yaml` | 补充 `update` 和 `batch_store` 方法 |
| `skills/builtin/question_bank/prompts/instruction.md` | 移除 `update_question` 不存在工具的引用 |
| `skills/builtin/doc_to_questions/prompts/instruction.md` | 移除 `<tool>` XML 示例，改为自然语言 |
| `plugins/builtin/knowledge_graph_plugin.py` | 移除 POST_PROCESS 和 XML 标签解析 |
| `plugins/builtin/exam_sim_plugin.py` | 精简，保留超时 + 关键字标记 |
| `plugins/builtin/question_bank_plugin.py` | 移除 POST_PROCESS 和 XML 标签解析 |
| `skills/registry.py` | 新增 `inject_dependencies()` 方法 |
| `engine.py` | 重构学习系统依赖注入逻辑 |

### 删除文件（二阶段可选）

| 文件 | 说明 |
|------|------|
| `plugins/builtin/knowledge_graph_plugin.py` | 若上下文注入也迁移到其他插件后可删除 |

---

## 附录 A: 工具注册总览

升级后学习系统在 `SkillRegistry` 中注册的工具数：

| 技能 | 工具数 | 工具列表 |
|------|:------:|---------|
| question_bank | 10 | create_question, search_questions, update_question, delete_question, compose_exam, analyze_error, get_error_stats, recommend_questions, suggest_templates, get_subjects |
| knowledge_graph | 6 | update_knowledge_state, get_due_reviews, analyze_weakness, recommend_related, get_mastery_summary, build_from_syllabus |
| exam_sim | 4 | create_exam, start_exam, submit_answer, finish_exam |
| doc_to_questions | 2 | process_hmd, process_text |

合计: **22 个学习系统工具** — 全部通过 `build_function_schema()` 生成 OpenAI function calling schema，在 native 模式下完整可用。

## 附录 B: 原生模式调用示例

```
用户: "我刚刚做了一道关于诱导公式的题，选对了"

系统 (LLM 调用 skill-knowledge_graph-update_knowledge_state):
  → { "kp_code": "KP-MATH-023", "correct": true }

  → 返回: { "success": true, "confidence": 0.65 }

系统 (LLM): "好！诱导公式的掌握度提升到了 0.65。"
```

```
用户: "我想做一套数学模拟卷"

系统 (LLM 调用 skill-exam_sim-create_exam):
  → { "subject": "math", "question_count": 15, "time_limit_min": 30 }

  → 返回: { "success": true, "session_id": "abc-123" }

系统 (LLM 调用 skill-exam_sim-start_exam):
  → { "session_id": "abc-123" }

  → 返回: { "success": true, "questions": [...], "time_limit_sec": 1800 }

系统: "15 道数学题，限时 30 分钟，准备好了吗？"
```
