# Tool Call 升级策划案 — DeepSeek 原生模式

> 版本: v2.0 | 日期: 2026-06-29

---

## 目录

1. [现状分析](#1-现状分析)
2. [统一适配策略](#2-统一适配策略)
3. [新方案概述](#3-方案概述)
4. [对比分析](#4-对比分析)
5. [需要重构的模块](#5-需要重构的模块)
6. [详细设计](#6-详细设计)
7. [兼容性与降级策略](#7-兼容性与降级策略)
8. [实施计划](#8-实施计划)

---

## 1. 现状分析

### 1.1 当前架构

```
系统提示词 (注入 skill instruction.md + 各种 capability 说明)
    ↓
LLM 生成文本回复，内含多种 XML 标签
    ↓
POST_PROCESS 各插件按优先级依次解析标签并执行
    ↓
Agent Loop: 工具结果 → 喂回 LLM → 继续生成
```

### 1.2 所有动作形式清单

当前 AI 可以通过 **14 种标签/格式** 执行动作：

| # | 标签/格式 | 解析插件 | 优先级 | 内容格式 | 执行的动作 |
|---|----------|---------|--------|---------|-----------|
| 1 | `<tool>` | ToolPlugin | 35 | JSON | 调用 SkillRegistry 执行技能工具 |
| 2 | `<task type="reminder">` | TaskPlugin | 40 | JSON | 创建提醒任务 |
| 3 | `<task type="habit">` | TaskPlugin | 40 | JSON | 创建习惯任务 |
| 4 | `<task type="countdown">` | TaskPlugin | 40 | JSON | 创建倒计时任务 |
| 5 | `<task type="daily_plan">` | TaskPlugin | 40 | JSON | 创建每日计划 |
| 6 | `<task type="periodic">` | TaskPlugin | 40 | JSON | 创建周期任务 |
| 7 | `<task type="reasoner">` | TaskPlugin | 40 | JSON | 创建推理任务 |
| 8 | `<task type="action">` + ````action` | TaskPlugin | 40 | JSON+代码 | 执行 shell/python/文件操作 |
| 9 | `<recall>` | RecallPlugin | 33 | JSON | 检索历史记忆 |
| 10 | `<memo>` | RecallPlugin | 33 | 纯文本 | 保存事实备忘录 |
| 11 | `<notebook>` | NotebookPlugin | 39 | 纯文本 | 保存用户观察笔记 |
| 12 | `<plan_check>` | PlanPlugin | 72 | JSON | 标记计划任务完成/跳过 |
| 13 | `<help>` | HelpPlugin | 5 | 纯文本 | 检索提示词指导 |
| 14 | `<confirm>` | ConfirmPlugin | 32 | 自闭合 | 触发用户确认协议 |
| 15 | `<ssp>` | SSPPlugin | 50 | 自闭合 | 启动自维持管线 |
| 16 | `<text>` | ModelsPlugin | - | 纯文本 | 包裹代码/特殊格式（TTS 跳过） |
| 17 | `<continue />` | ModelsPlugin | - | 自闭合 | 继续标记（无实际动作） |
| 18 | `IMPRESSION:类别:内容:置信度` | ImpressionPlugin | 22 | 纯文本 | 记录用户印象 |
| 19 | `SSP_DONE`/`SSP_COMPLETE` | SSPPlugin | - | 纯文本 | 终止 SSP 循环 |

### 1.3 现有问题

| 问题 | 影响 |
|------|------|
| LLM 可能输出格式错误的 JSON | 解析失败，工具不执行 |
| 标签格式不稳定（换行、空格、引号差异） | 正则匹配失败 |
| 多工具并行调用困难 | 需输出多个 `<tool>` 标签 |
| 每个技能需写大量提示词指导 LLM | token 浪费（每个 skill ~200-500 tokens） |
| 无法利用模型的结构化输出能力 | 依赖 LLM 的"格式遵循"能力 |
| 14 种标签格式不统一 | 维护成本高，LLM 容易混淆 |

---

## 2. 统一适配策略

### 2.1 分类与映射决策

将 14 种标签按性质分为 4 类，决定映射策略：

| 分类 | 标签 | 映射策略 | 理由 |
|------|------|----------|------|
| **A. 工具调用** | `<tool>` | ✅ 映射为原生 function call | 本身就是工具调用 |
| **B. 任务调度** | `<task>` (7种子类型) | ✅ 映射为原生 function call | 结构化参数，适合 function call |
| **C. 系统操作** | `<recall>` `<memo>` `<notebook>` `<plan_check>` `<help>` | ✅ 映射为原生 function call | 结构化参数，可统一 |
| **D. 信号/格式** | `<confirm>` `<ssp>` `<text>` `<continue/>` `IMPRESSION` `SSP_DONE` | ✅ 映射为无参数 function call | 信号类用空参数 function 表示触发 |

### 2.2 统一 Function 定义

将所有标签统一为 **16 个 function**：

```python
UNIFIED_TOOLS = [
    # === A. 技能工具 (动态生成，来自 skill.yaml) ===
    # {"type": "function", "function": {"name": "skill.web_search.search", ...}}
    # {"type": "function", "function": {"name": "skill.plan.create_goal", ...}}
    # ... (从 SkillRegistry 动态生成)

    # === B. 任务调度 (7个 function) ===
    {
        "type": "function",
        "function": {
            "name": "task.create_reminder",
            "description": "创建定时提醒任务",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "提醒内容"},
                    "time": {"type": "string", "description": "提醒时间 (ISO8601)"},
                },
                "required": ["text", "time"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "task.create_habit",
            "description": "创建周期性习惯任务",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "习惯内容"},
                    "time": {"type": "string", "description": "首次触发时间 (ISO8601)"},
                    "interval": {"type": "string", "description": "重复间隔 (如 30m, 1h, 1d)"},
                },
                "required": ["text", "time", "interval"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "task.create_countdown",
            "description": "创建倒计时任务",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "倒计时结束提示"},
                    "target": {"type": "string", "description": "目标时间 (ISO8601)"},
                },
                "required": ["text", "target"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "task.create_daily_plan",
            "description": "创建每日计划任务",
            "parameters": {
                "type": "object",
                "properties": {
                    "trigger_time": {"type": "string", "description": "每日触发时间 (HH:MM)"},
                },
                "required": ["trigger_time"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "task.create_periodic",
            "description": "创建 cron 周期任务",
            "parameters": {
                "type": "object",
                "properties": {
                    "cron": {"type": "string", "description": "cron 表达式"},
                    "text": {"type": "string", "description": "任务内容"},
                },
                "required": ["cron", "text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "task.create_reasoner",
            "description": "创建异步推理任务，系统会自动执行并返回结果",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "需要推理的问题"},
                    "context": {"type": "string", "description": "上下文信息"},
                },
                "required": ["question"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "task.execute_action",
            "description": "执行代码操作 (shell/python/文件操作)",
            "parameters": {
                "type": "object",
                "properties": {
                    "action_type": {
                        "type": "string",
                        "enum": ["shell", "python", "write_file", "edit_file"],
                        "description": "操作类型"
                    },
                    "content": {"type": "string", "description": "代码/命令内容"},
                    "file_path": {"type": "string", "description": "文件路径 (write_file/edit_file)"},
                    "overwrite": {"type": "boolean", "description": "是否覆盖 (write_file)", "default": False},
                    "pattern": {"type": "string", "description": "匹配模式 (edit_file)"},
                    "replacement": {"type": "string", "description": "替换内容 (edit_file)"},
                },
                "required": ["action_type", "content"]
            }
        }
    },

    # === C. 系统操作 (5个 function) ===
    {
        "type": "function",
        "function": {
            "name": "memory.recall",
            "description": "检索历史记忆，支持关键词搜索和细节还原",
            "parameters": {
                "type": "object",
                "properties": {
                    "keywords": {"type": "array", "items": {"type": "string"}, "description": "搜索关键词列表"},
                    "count": {"type": "integer", "description": "返回条数", "default": 3},
                    "detail": {"type": "boolean", "description": "是否还原细节", "default": False},
                },
                "required": ["keywords"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "memory.save_memo",
            "description": "保存事实备忘录，用于记住用户的长期信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "备忘录内容"},
                },
                "required": ["content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "notebook.save_observation",
            "description": "保存用户观察笔记，记录对用户的观察",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "观察笔记内容"},
                },
                "required": ["content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "plan.mark_task",
            "description": "标记计划任务完成或跳过",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "任务 ID"},
                    "action": {"type": "string", "enum": ["done", "skip"], "description": "操作"},
                },
                "required": ["task_id", "action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "system.search_prompts",
            "description": "检索提示词库，获取操作指导",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索查询"},
                },
                "required": ["query"]
            }
        }
    },

    # === D. 信号/格式 (6个无参数 function) ===
    {
        "type": "function",
        "function": {
            "name": "signal.confirm",
            "description": "向用户请求确认，等待用户选择继续或取消",
            "parameters": {
                "type": "object",
                "properties": {},
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "signal.start_ssp",
            "description": "启动自维持管线，自主循环收集用户信息",
            "parameters": {
                "type": "object",
                "properties": {},
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "signal.stop_ssp",
            "description": "停止自维持管线循环",
            "parameters": {
                "type": "object",
                "properties": {},
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "signal.record_impression",
            "description": "记录用户印象，用于个性化交互",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "印象类别 (如: 兴趣, 习惯, 技能)"},
                    "content": {"type": "string", "description": "印象内容"},
                    "confidence": {"type": "integer", "description": "置信度 (0-100)", "default": 80},
                },
                "required": ["category", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "signal.mark_text",
            "description": "标记文本为代码/特殊格式，TTS 合成时跳过",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "需要标记的文本内容"},
                },
                "required": ["content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "signal.continue_generation",
            "description": "表示回复未完成，需要继续生成",
            "parameters": {
                "type": "object",
                "properties": {},
            }
        }
    },
]
```

### 2.3 映射对照表

所有标签统一映射为 function call：

| 原标签 | 原格式 | 新 function name | 新参数格式 |
|--------|--------|-----------------|-----------|
| `<tool>` | JSON | `skill.{skill_name}.{tool_name}` | 结构化参数 |
| `<task type="reminder">` | JSON | `task.create_reminder` | `{"text":"...", "time":"..."}` |
| `<task type="habit">` | JSON | `task.create_habit` | `{"text":"...", "time":"...", "interval":"..."}` |
| `<task type="countdown">` | JSON | `task.create_countdown` | `{"text":"...", "target":"..."}` |
| `<task type="daily_plan">` | JSON | `task.create_daily_plan` | `{"trigger_time":"07:30"}` |
| `<task type="periodic">` | JSON | `task.create_periodic` | `{"cron":"0 9 * * *", "text":"..."}` |
| `<task type="reasoner">` | JSON | `task.create_reasoner` | `{"question":"...", "context":"..."}` |
| `<task type="action">` + ````action` | JSON+代码 | `task.execute_action` | `{"action_type":"shell", "content":"..."}` |
| `<recall>` | JSON | `memory.recall` | `{"keywords":["..."], "count":3}` |
| `<memo>` | 纯文本 | `memory.save_memo` | `{"content":"..."}` |
| `<notebook>` | 纯文本 | `notebook.save_observation` | `{"content":"..."}` |
| `<plan_check>` | JSON | `plan.mark_task` | `{"task_id":"...", "action":"done"}` |
| `<help>` | 纯文本 | `system.search_prompts` | `{"query":"..."}` |
| `<confirm>` | 自闭合 | `signal.confirm` | `{}` (无参数) |
| `<ssp>` | 自闭合 | `signal.start_ssp` | `{}` (无参数) |
| `SSP_DONE`/`SSP_COMPLETE` | 文本 | `signal.stop_ssp` | `{}` (无参数) |
| `IMPRESSION:类别:内容:置信度` | 文本 | `signal.record_impression` | `{"category":"...", "content":"...", "confidence":80}` |
| `<text>内容</text>` | XML | `signal.mark_text` | `{"content":"..."}` |
| `<continue />` | 自闭合 | `signal.continue_generation` | `{}` (无参数) |

---

## 3. 新方案概述

### 3.1 DeepSeek 原生 Tool Call 模式

```python
from openai import OpenAI

client = OpenAI(api_key="...", base_url="https://api.deepseek.com")

# 所有可用工具（技能工具 + 系统操作）
tools = UNIFIED_TOOLS + skill_registry.get_tools_schema()

response = client.chat.completions.create(
    model="deepseek-v4-pro",
    messages=messages,
    tools=tools,
    tool_choice="auto",
)

message = response.choices[0].message
if message.tool_calls:
    for tc in message.tool_calls:
        func_name = tc.function.name        # "task.create_reminder"
        func_args = json.loads(tc.function.arguments)
        # 分发到对应的处理器
```

### 3.2 统一分发器

```python
# 新增: tools/dispatcher.py

class ToolDispatcher:
    """统一的工具分发器，处理所有原生 tool_calls"""
    
    def __init__(self, skill_registry, task_manager, memory_system,
                 notebook_store, plan_engine, prompt_cache,
                 impression_manager, confirm_callback=None,
                 ssp_callback=None):
        self._handlers = {
            "skill.*": self._handle_skill,
            "task.*": self._handle_task,
            "memory.*": self._handle_memory,
            "notebook.*": self._handle_notebook,
            "plan.*": self._handle_plan,
            "system.*": self._handle_system,
            "signal.*": self._handle_signal,
        }
        self._skill_registry = skill_registry
        self._task_manager = task_manager
        self._memory_system = memory_system
        self._notebook_store = notebook_store
        self._plan_engine = plan_engine
        self._prompt_cache = prompt_cache
        self._impression_manager = impression_manager
        self._confirm_callback = confirm_callback
        self._ssp_callback = ssp_callback
    
    def dispatch(self, tool_call: dict, ctx=None) -> dict:
        func_name = tool_call["function"]["name"]
        func_args = json.loads(tool_call["function"]["arguments"])
        tool_call_id = tool_call["id"]
        
        # 命名空间分发
        namespace = func_name.split(".")[0]
        handler = self._handlers.get(f"{namespace}.*")
        
        try:
            result = handler(func_name, func_args, ctx)
            return {"tool_call_id": tool_call_id, "success": True, "data": result}
        except Exception as e:
            return {"tool_call_id": tool_call_id, "success": False, "error": str(e)}
    
    def _handle_skill(self, name, args, ctx):
        _, skill_name, tool_name = name.split(".", 2)
        return self._skill_registry.call_tool(skill_name, tool_name, args)
    
    def _handle_task(self, name, args, ctx):
        task_type = name.split(".")[-1]
        type_map = {
            "create_reminder": TaskType.REMINDER,
            "create_habit": TaskType.HABIT,
            "create_countdown": TaskType.COUNTDOWN,
            "create_daily_plan": TaskType.DAILY_PLAN,
            "create_periodic": TaskType.PERIODIC,
            "create_reasoner": TaskType.REASONER,
            "execute_action": TaskType.ACTION,
        }
        task_type_enum = type_map[task_type]
        return self._task_manager.create_task(task_type_enum, args)
    
    def _handle_memory(self, name, args, ctx):
        action = name.split(".")[-1]
        if action == "recall":
            return self._memory_system.recall(args["keywords"], args.get("count", 3))
        elif action == "save_memo":
            uid = ctx.user_id if ctx else 0
            return self._memory_system.add_memo(uid, args["content"])
    
    def _handle_notebook(self, name, args, ctx):
        uid = ctx.user_id if ctx else 0
        chat_id = ctx.chat_id if ctx else 0
        return self._notebook_store.add_note(uid, args["content"], chat_id)
    
    def _handle_plan(self, name, args, ctx):
        action = args["action"]
        task_id = args["task_id"]
        if action == "done":
            return self._plan_engine.check_off(task_id)
        elif action == "skip":
            return self._plan_engine.skip_task(task_id)
    
    def _handle_system(self, name, args, ctx):
        action = name.split(".")[-1]
        if action == "search_prompts":
            uid = ctx.user_id if ctx else 0
            chat_id = ctx.chat_id if ctx else 0
            return self._prompt_cache.search(uid, chat_id, args["query"])
    
    def _handle_signal(self, name, args, ctx):
        signal_type = name.split(".")[-1]
        
        if signal_type == "confirm":
            if ctx:
                ctx.extra["confirm_requested"] = True
            return {"action": "confirm_requested"}
        
        elif signal_type == "start_ssp":
            if self._ssp_callback:
                self._ssp_callback("start", ctx)
            return {"action": "ssp_started"}
        
        elif signal_type == "stop_ssp":
            if self._ssp_callback:
                self._ssp_callback("stop", ctx)
            return {"action": "ssp_stopped"}
        
        elif signal_type == "record_impression":
            uid = ctx.user_id if ctx else 0
            self._impression_manager.add(
                uid,
                args["category"],
                args["content"],
                args.get("confidence", 80),
                source="llm"
            )
            return {"action": "impression_recorded"}
        
        elif signal_type == "mark_text":
            return {"action": "text_marked", "content": args.get("content", "")}
        
        elif signal_type == "continue_generation":
            if ctx:
                ctx.extra["continue_generation"] = True
            return {"action": "continue"}
        
        return {"action": "unknown_signal"}
```

### 3.3 核心变化

| 维度 | 当前方案 | 原生模式 |
|------|----------|----------|
| 工具定义 | 14 种标签 + 提示词描述 | 10 个 function + JSON Schema |
| 工具调用 | LLM 输出 XML 标签文本 | API 返回结构化 `tool_calls` |
| 执行结果 | 注入为用户消息 `[执行结果]` | 专用 `role: "tool"` 消息 |
| 多工具调用 | 需输出多个标签，依赖 Agent Loop | 单次响应返回多个 `tool_calls` |
| 格式可靠性 | 依赖 LLM 遵循提示词 | 模型原生支持，结构化输出 |
| 分发方式 | 9 个插件各自正则解析 | 1 个统一 Dispatcher 分发 |

---

## 4. 对比分析

### 4.1 优点

| 优点 | 说明 |
|------|------|
| **格式可靠** | 模型原生输出结构化 tool_calls，无需正则解析 |
| **token 节省** | 不需要 14 种标签的提示词说明，预计节省 2000-3000 tokens/对话 |
| **并行调用** | 单次响应可返回多个 tool_calls，无需多轮 Agent Loop |
| **类型安全** | JSON Schema 定义参数类型，模型输出更准确 |
| **调试友好** | tool_calls 结构化，易于日志记录和追踪 |
| **统一架构** | 10 个 function 替代 14 种标签，维护成本降低 |
| **行业标准** | OpenAI 兼容格式，生态成熟 |

### 4.2 需要解决的问题

| 问题 | 说明 |
|------|------|
| **LMStudio 兼容** | 本地模型可能不支持原生 tool call |
| **迁移成本** | 现有 skill 需要添加 JSON Schema 定义 |
| **Agent Loop 改造** | 需适配新的 tool role 消息格式 |
| **混合模式** | 过渡期需同时支持新旧两种方式 |

---

## 5. 需要重构的模块

### 5.1 最高优先级（技能加载器重构）

| 模块 | 改动 | 复杂度 |
|------|------|--------|
| `skills/loader.py` | 新增 `build_function_schema()` 方法，处理三种 methods 格式（字符串列表/完整对象/空参数） | 高 |
| `skills/loader.py` | 新增 `_extract_parameters()` 方法，统一参数提取逻辑 | 中 |
| `skills/loader.py` | 新增 `_param_def_to_schema()` 方法，类型映射转换 | 低 |
| `skills/registry.py` | 新增 `get_tools_schema()` 方法，调用 loader 生成 schema | 中 |

### 5.2 高优先级（核心改造）

| 模块 | 改动 | 复杂度 |
|------|------|--------|
| `models/clients.py` | DeepSeekChat/LMStudioChat 添加 `tools` 参数支持 | 中 |
| `tools/dispatcher.py` | **新建** 统一 ToolDispatcher 分发器 | 高 |
| `plugins/builtin/models_plugin.py` | 传递 tools schema，处理 tool_calls 响应 | 高 |
| `plugins/pipeline.py` | Agent Loop 适配新的 tool role 消息格式 | 高 |

### 5.3 中优先级（执行层改造）

| 模块 | 改动 | 复杂度 |
|------|------|--------|
| `plugins/builtin/tool_plugin.py` | 原生模式下委托给 ToolDispatcher | 中 |
| `plugins/builtin/task_plugin.py` | 原生模式下委托给 ToolDispatcher | 中 |
| `plugins/builtin/recall_plugin.py` | 原生模式下委托给 ToolDispatcher | 中 |
| `plugins/builtin/notebook/notebook_plugin.py` | 原生模式下委托给 ToolDispatcher | 低 |
| `plugins/builtin/plan_plugin.py` | 原生模式下委托给 ToolDispatcher | 低 |
| `plugins/builtin/help_plugin.py` | 原生模式下委托给 ToolDispatcher | 低 |

### 5.3 低优先级（提示词调整）

| 模块 | 改动 | 复杂度 |
|------|------|--------|
| `prompt/engine.py` | 原生模式下不再注入 skill instruction.md | 低 |
| `skills/*/prompts/instruction.md` | 可保留用于降级模式 | 低 |
| `prompt/prompts/capabilities/task_handling.md` | 更新工具调用语法说明 | 低 |
| `config.py` | 新增 `TOOL_CALL_MODE` 配置 | 低 |

---

## 6. 详细设计

### 6.1 技能加载器重构

#### 6.1.1 现状分析

当前 `skills/loader.py` 的 `_parse_tools()` 方法仅将 skill.yaml 中的 tools 定义解析为 `ToolSpec` 数据类，不做任何格式转换。但 skill.yaml 中存在 **三种不同的 methods 定义格式**：

| 格式 | 示例 | 使用技能 |
|------|------|---------|
| **A. 字符串列表** | `methods: [search_song, get_song_url]` | personality_materials, ncm_music |
| **B. 完整对象列表** | `methods: [{name: clone, parameters: {...}}]` | github, plan, web_search 等 7 个 |
| **C. 空参数** | `methods: [{name: get_title, parameters: []}]` | browser_use, skillmgr, document |

#### 6.1.2 重构目标

在 `SkillLoader` 中新增 `build_function_schema()` 方法，将三种格式统一转换为 OpenAI function calling JSON Schema：

```python
# skills/loader.py 重构

class SkillLoader:
    
    def build_function_schema(self, skill_name: str, tool_spec: ToolSpec) -> dict:
        """
        将 ToolSpec 转换为 OpenAI function calling 格式
        
        输入: ToolSpec(name="search", description="执行搜索", methods=[...])
        输出: {"type": "function", "function": {"name": "skill.web_search.search", ...}}
        """
        func_name = f"skill.{skill_name}.{tool_spec.name}"
        
        # 从 methods 中提取参数定义
        parameters = self._extract_parameters(tool_spec)
        
        return {
            "type": "function",
            "function": {
                "name": func_name,
                "description": tool_spec.description,
                "parameters": parameters,
            }
        }
    
    def _extract_parameters(self, tool_spec: ToolSpec) -> dict:
        """
        从 ToolSpec.methods 提取参数，处理三种格式
        """
        properties = {}
        required = []
        
        for method in tool_spec.methods:
            # 格式 A: 字符串 → 无参数
            if isinstance(method, str):
                continue
            
            # 格式 B/C: 对象
            if isinstance(method, dict):
                params = method.get("parameters", {})
                
                # 格式 C: 空列表 [] 或空对象 {}
                if not params:
                    continue
                
                # 格式 B: 完整对象
                if isinstance(params, dict):
                    for param_name, param_def in params.items():
                        if not isinstance(param_def, dict):
                            continue
                        schema = self._param_def_to_schema(param_def)
                        properties[param_name] = schema
                        if param_def.get("required"):
                            required.append(param_name)
        
        return {
            "type": "object",
            "properties": properties,
            "required": required,
        }
    
    def _param_def_to_schema(self, param_def: dict) -> dict:
        """
        将单个参数定义转换为 JSON Schema 格式
        
        输入: {"type": "string", "description": "搜索关键词", "required": true}
        输出: {"type": "string", "description": "搜索关键词"}
        """
        # 类型映射: skill.yaml 类型 → JSON Schema 类型
        TYPE_MAP = {
            "string": "string",
            "integer": "integer",
            "int": "integer",
            "boolean": "boolean",
            "bool": "boolean",
            "array": "array",
            "list": "array",
            "number": "number",
            "float": "number",
        }
        
        raw_type = param_def.get("type", "string")
        schema_type = TYPE_MAP.get(raw_type, "string")
        
        schema = {"type": schema_type}
        
        # 描述
        if "description" in param_def:
            schema["description"] = param_def["description"]
        
        # 默认值
        if "default" in param_def:
            schema["default"] = param_def["default"]
        
        # 数组类型需要 items 定义
        if schema_type == "array":
            schema["items"] = {"type": "string"}  # 默认字符串数组
        
        return schema
```

#### 6.1.3 转换示例

**示例 1: 格式 A (字符串列表)**
```yaml
# 输入: personality_materials skill.yaml
tools:
  - name: import_experience
    description: "导入经历素材"
    methods:
      - import_experience    # 字符串，无参数

# 输出: OpenAI function calling schema
{
    "type": "function",
    "function": {
        "name": "skill.personality_materials.import_experience",
        "description": "导入经历素材",
        "parameters": {"type": "object", "properties": {}, "required": []}
    }
}
```

**示例 2: 格式 B (完整对象)**
```yaml
# 输入: web_search skill.yaml
tools:
  - name: search
    description: "执行网页搜索"
    methods:
      - name: search
        parameters:
          query:
            type: string
            description: "搜索关键词"
            required: true
          max_results:
            type: integer
            description: "最大结果数"
            default: 5

# 输出:
{
    "type": "function",
    "function": {
        "name": "skill.web_search.search",
        "description": "执行网页搜索",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "max_results": {"type": "integer", "description": "最大结果数", "default": 5}
            },
            "required": ["query"]
        }
    }
}
```

**示例 3: 格式 C (空参数)**
```yaml
# 输入: browser_use skill.yaml
tools:
  - name: get_title
    description: "获取页面标题"
    methods:
      - name: get_title
        description: "返回页面 title"
        parameters: []    # 空列表

# 输出:
{
    "type": "function",
    "function": {
        "name": "skill.browser_use.get_title",
        "description": "获取页面标题",
        "parameters": {"type": "object", "properties": {}, "required": []}
    }
}
```

#### 6.1.4 SkillRegistry 集成

```python
# skills/registry.py 修改

class SkillRegistry:
    def __init__(self):
        self._tool_instances: dict[str, Any] = {}
        self._tool_specs: dict[str, dict] = {}
        self._skill_prompts: dict[str, str] = {}
        self._active_skills: dict[str, "Skill"] = {}
        self._loader = SkillLoader()  # 新增
    
    def get_tools_schema(self) -> list[dict]:
        """生成所有已注册技能工具的 OpenAI function calling schema"""
        tools = []
        for key, spec in self._tool_specs.items():
            skill_name = key.split(".")[0]
            tool_name = key.split(".", 1)[1]
            
            # 从 _active_skills 获取原始 ToolSpec
            skill = self._active_skills.get(skill_name)
            if not skill:
                continue
            
            # 找到对应的 ToolSpec
            tool_spec = None
            for ts in skill.tools:
                if ts.name == tool_name:
                    tool_spec = ts
                    break
            
            if tool_spec:
                schema = self._loader.build_function_schema(skill_name, tool_spec)
                tools.append(schema)
        
        return tools
```

### 6.2 工具 Schema 生成 (简化版)

```python
# skills/registry.py 新增方法

def get_tools_schema(self) -> list[dict]:
    """生成技能工具的 OpenAI function calling 格式 schema"""
    tools = []
    for key, spec in self._tool_specs.items():
        function_def = {
            "type": "function",
            "function": {
                "name": f"skill.{key}",  # "skill.web_search.search"
                "description": spec.get("description", ""),
                "parameters": self._build_parameters_schema(spec),
            }
        }
        tools.append(function_def)
    return tools

def _build_parameters_schema(self, spec: dict) -> dict:
    properties = {}
    required = []
    
    for method in spec.get("methods", []):
        for param_name, param_def in method.get("parameters", {}).items():
            schema = {"type": param_def.get("type", "string")}
            if "description" in param_def:
                schema["description"] = param_def["description"]
            if "default" in param_def:
                schema["default"] = param_def["default"]
            properties[param_name] = schema
            if param_def.get("required"):
                required.append(param_name)
    
    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }
```

### 6.2 客户端改造

```python
# models/clients.py — DeepSeekChat 改造

class DeepSeekChat:
    def send_message(self, message: str, tools: list[dict] = None,
                     tool_choice: str = "auto") -> str:
        self.messages.append({"role": "user", "content": message})
        return self._call_and_append(tools=tools, tool_choice=tool_choice)
    
    def _call_and_append(self, tools=None, tool_choice="auto") -> str:
        payload = {
            "model": self.model,
            "messages": self.messages,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice
        
        response = self._post(payload)
        message = response["choices"][0]["message"]
        
        self._last_message = message
        self.messages.append(message)
        
        return message.get("content", "")
    
    @property
    def last_tool_calls(self) -> list[dict] | None:
        msg = getattr(self, '_last_message', None)
        if msg and msg.get('tool_calls'):
            return msg['tool_calls']
        return None
```

### 6.3 ModelsPlugin 改造

```python
# plugins/builtin/models_plugin.py

class ModelsPlugin(Plugin):
    def on_hook(self, hook, ctx):
        # ... 现有逻辑 ...
        
        # 原生模式：传递所有 tools schema
        tools_schema = None
        if ctx.extra.get("tool_call_mode") == "native":
            tools_schema = self._build_unified_tools(ctx)
        
        chat = self._create_chat(effective_type)
        chat.messages = full_messages.copy()
        reply = chat.send_message(timestamped, tools=tools_schema)
        
        # 保存 tool_calls 供后续处理
        ctx.extra["_native_tool_calls"] = chat.last_tool_calls
        ctx.original_reply = reply
        ctx.reply = self._clean_reply(reply)
        
        return ctx
    
    def _build_unified_tools(self, ctx) -> list[dict]:
        """构建统一的 tools schema"""
        tools = list(UNIFIED_TOOLS)  # 系统工具
        
        # 追加技能工具
        if self._skill_registry:
            tools.extend(self._skill_registry.get_tools_schema())
        
        return tools
```

### 6.4 ToolPlugin 改造

```python
# plugins/builtin/tool_plugin.py

class ToolPlugin(Plugin):
    def on_hook(self, hook, ctx):
        if hook != HookPoint.POST_PROCESS:
            return ctx
        
        # 原生模式：委托给 ToolDispatcher
        native_calls = ctx.extra.pop("_native_tool_calls", [])
        if native_calls:
            return self._handle_native_tool_calls(native_calls, ctx)
        
        # 降级模式：处理 XML 标签（现有逻辑）
        return self._handle_xml_tool_tags(ctx)
    
    def _handle_native_tool_calls(self, tool_calls: list, ctx):
        from tools.dispatcher import ToolDispatcher
        
        dispatcher = ctx.extra.get("_tool_dispatcher")
        if not dispatcher:
            logger.warning("ToolDispatcher 未注入")
            return ctx
        
        results = []
        for tc in tool_calls:
            result = dispatcher.dispatch(tc)
            results.append(result)
        
        ctx.extra["_native_tool_results"] = results
        ctx.extra.setdefault("_tag_results", []).extend(results)
        return ctx
```

### 6.5 Agent Loop 改造

```python
# plugins/pipeline.py — _run_agent_loop 改造

async def _run_agent_loop(self, ctx):
    for step in range(max_steps):
        # 原生模式：构造 tool role 消息
        tool_results = ctx.extra.pop("_native_tool_results", [])
        if tool_results:
            for tr in tool_results:
                ctx.full_history.append({
                    "role": "tool",
                    "tool_call_id": tr["tool_call_id"],
                    "content": json.dumps(
                        tr.get("data", tr.get("error", "")),
                        ensure_ascii=False, default=str
                    ),
                })
            
            # 继续对话，让模型根据工具结果生成回复
            models_plugin = self.pm.get_plugin("models")
            new_reply = await loop.run_in_executor(
                None, lambda: models_plugin.invoke(ctx.full_history, ctx)
            )
            ctx.original_reply = new_reply
            ctx.reply = new_reply
            continue
        
        # 降级模式：XML 标签处理（现有逻辑）
        results = ctx.extra.pop("_tag_results", [])
        if not results:
            break
        # ... 现有逻辑 ...
```

### 6.6 配置设计

```python
# config.py

class Config:
    # 工具调用模式: "native" (DeepSeek原生) | "xml" (XML标签) | "auto" (自动降级)
    TOOL_CALL_MODE = _env("TOOL_CALL_MODE", "auto")
    
    # 原生模式下的模型（需支持 tool call）
    TOOL_CALL_MODEL = _env("TOOL_CALL_MODEL", "deepseek-v4-pro")
```

### 6.7 Skill YAML 扩展

```yaml
# skills/builtin/web_search/skill.yaml

tools:
  - name: search
    display_name: "搜索"
    description: "执行网页搜索获取信息"
    module: "tools.search"
    class: "WebSearchTool"
    # 可选：显式定义 JSON Schema（如不定义则自动从 parameters 生成）
    # schema: { ... }
    methods:
      - name: search
        description: "执行网页搜索"
        parameters:
          query:
            type: string
            description: "搜索关键词"
            required: true
          max_results:
            type: integer
            description: "最大结果数"
            default: 5
```

---

## 7. 兼容性与降级策略

### 7.1 三种模式

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| `native` | DeepSeek 原生 tool call | DeepSeek API + 支持 tool call 的模型 |
| `xml` | XML 标签（现有方案） | LMStudio 本地模型、不支持 tool call 的模型 |
| `auto` | 自动检测并降级 | 默认模式 |

### 7.2 降级逻辑

```python
def _resolve_tool_call_mode(self, ctx) -> str:
    mode = Config.TOOL_CALL_MODE
    if mode == "auto":
        if ctx.model_type == "deepseek" and self._supports_tool_calls(ctx):
            return "native"
        return "xml"
    return mode
```

### 7.3 降级时的行为

| 模式 | 技能工具 | 任务调度 | 记忆操作 | 信号/格式 |
|------|----------|----------|----------|----------|
| native | `skill.*` function call | `task.*` function call | `memory.*` function call | `signal.*` function call |
| xml | `<tool>` XML 标签 | `<task>` XML 标签 | `<recall>`/`<memo>` XML 标签 | `<confirm>`/`<ssp>`/`<text>` XML 标签 |

### 7.4 迁移策略

1. **Phase 1**: 保留所有 XML 标签提示词，新增 native 模式 + ToolDispatcher
2. **Phase 2**: native 模式下不再注入 skill instruction.md，节省 token
3. **Phase 3**: 验证稳定后，XML 模式作为 fallback 保留

---

## 8. 实施计划

### Phase 1 — 技能加载器重构 (5-6 天)

- [ ] `skills/loader.py`: 新增 `build_function_schema()` 方法，处理三种 methods 格式
- [ ] `skills/loader.py`: 新增 `_extract_parameters()` 方法，统一参数提取逻辑
- [ ] `skills/loader.py`: 新增 `_param_def_to_schema()` 方法，类型映射转换
- [ ] `skills/registry.py`: 新增 `get_tools_schema()` 方法，调用 loader 生成 schema
- [ ] `config.py`: 新增 `TOOL_CALL_MODE` / `TOOL_CALL_MODEL`
- [ ] 单元测试：验证 9 个技能的 schema 生成正确性

### Phase 2 — 基础架构 (4-5 天)

- [ ] `tools/dispatcher.py`: **新建** 统一 ToolDispatcher
- [ ] `models/clients.py`: DeepSeekChat 添加 `tools` 参数 + `last_tool_calls` 属性

### Phase 3 — 核心改造 (4-5 天)

- [ ] `plugins/builtin/models_plugin.py`: 传递 tools，保存 tool_calls
- [ ] `plugins/builtin/tool_plugin.py`: 原生模式委托给 ToolDispatcher
- [ ] `plugins/pipeline.py`: Agent Loop 适配 tool role 消息

### Phase 4 — 适配层 (3-4 天)

- [ ] `plugins/builtin/task_plugin.py`: 原生模式委托给 ToolDispatcher
- [ ] `plugins/builtin/recall_plugin.py`: 原生模式委托给 ToolDispatcher
- [ ] `plugins/builtin/notebook/notebook_plugin.py`: 原生模式委托
- [ ] `plugins/builtin/plan_plugin.py`: 原生模式委托
- [ ] `plugins/builtin/help_plugin.py`: 原生模式委托
- [ ] `plugins/builtin/confirm_plugin.py`: 原生模式委托给 ToolDispatcher (signal.confirm)
- [ ] `plugins/builtin/ssp_plugin.py`: 原生模式委托给 ToolDispatcher (signal.start_ssp/stop_ssp)
- [ ] `plugins/builtin/impression_plugin.py`: 原生模式委托给 ToolDispatcher (signal.record_impression)

### Phase 5 — 提示词与 Skill (2-3 天)

- [ ] `prompt/engine.py`: native 模式下跳过 skill instruction.md 注入
- [ ] `prompt/prompts/capabilities/*.md`: 更新说明文档

### Phase 6 — 测试与优化 (2-3 天)

- [ ] 单元测试：tool_calls 解析、降级逻辑
- [ ] 集成测试：完整对话流程验证
- [ ] 性能测试：对比 token 消耗、响应延迟

**总工期预估: 20-26 天**

---

## 附录 A: 涉及文件清单

```
skills/loader.py                    ← 核心重构: build_function_schema() 处理三种格式
skills/registry.py                  ← 新增 get_tools_schema() 调用 loader
config.py                           ← 新增配置
tools/dispatcher.py                 ← 新建: 统一 ToolDispatcher
models/clients.py                   ← 客户端改造
plugins/builtin/models_plugin.py    ← tools 传递
plugins/builtin/tool_plugin.py      ← 委托给 Dispatcher
plugins/builtin/task_plugin.py      ← 委托给 Dispatcher
plugins/builtin/recall_plugin.py    ← 委托给 Dispatcher
plugins/builtin/notebook/notebook_plugin.py ← 委托给 Dispatcher
plugins/builtin/plan_plugin.py      ← 委托给 Dispatcher
plugins/builtin/help_plugin.py      ← 委托给 Dispatcher
plugins/builtin/confirm_plugin.py   ← 委托给 Dispatcher (signal.confirm)
plugins/builtin/ssp_plugin.py       ← 委托给 Dispatcher (signal.start_ssp/stop_ssp)
plugins/builtin/impression_plugin.py ← 委托给 Dispatcher (signal.record_impression)
plugins/pipeline.py                 ← Agent Loop 改造
prompt/engine.py                    ← 提示词条件注入
prompt/prompts/capabilities/*.md    ← 文档更新
```

## 附录 B: Token 节省估算

| 项目 | 当前方案 | 原生模式 | 节省 |
|------|----------|----------|------|
| skill instruction.md | ~300 tokens/skill × 10 skills = 3000 | 0 (Schema 在 API 中) | 3000 |
| task_handling.md | ~500 tokens | ~100 tokens (简要说明) | 400 |
| memory_recall.md | ~200 tokens | ~50 tokens | 150 |
| 其他 capability.md | ~500 tokens | ~100 tokens | 400 |
| **总计** | **~4200 tokens** | **~250 tokens** | **~3950 tokens** |
