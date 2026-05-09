# 插件系统实现指导

> 来源: architecture.md §四 / §八.6
> 目标: 将当前 app.py 中硬编码的处理逻辑迁移为可插拔的插件管道

---

## 一、设计边界

| 模块 | 归属 | 理由 |
|------|------|------|
| 用户管理 `usermgr.py` | **独立模块** | 认证是基础设施，不进插件 |
| Prompt 生态 `prompt/` | **独立子系统** | AI 人格核心，独立演进 |
| 技能系统 `skills/` | **独立子系统** | 能力扩展核心 |
| 模型调用 | **一个大插件** | DeepSeek / LMStudio / Summary 统一管理 |
| ASR / 记忆 / 任务 / TTS | **各一个插件** | 可选功能，可热插拔 |

---

## 二、目标目录结构

```
plugins/
├── __init__.py
├── base.py              # Plugin 基类 + HookPoint + PluginContext
├── manager.py           # PluginManager — 注册/启用/禁用/钩子调度
├── pipeline.py          # ChatPipeline — 编排管道
├── builtin/
│   ├── __init__.py
│   ├── models_plugin.py      # ★ 统一模型插件
│   ├── asr_filter_plugin.py  # ASR 语音过滤
│   ├── memory_plugin.py      # 记忆注入 + 对话保存
│   ├── task_plugin.py        # 任务解析 + 技能工具调用
│   └── tts_plugin.py         # TTS 语音合成
└── custom/
    └── README.md             # 自定义插件编写指南
```

---

## 三、核心接口

### 3.1 Plugin 基类 (`plugins/base.py`)

```python
from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Optional

class HookPoint(Enum):
    """插件可以挂载的钩子点"""
    PRE_FILTER    = "pre_filter"      # ASR 输入过滤，可短路返回
    PRE_PROCESS   = "pre_process"     # 记忆注入、上下文组装
    MODEL_INVOKE  = "model_invoke"    # 模型调用（建议只有一个插件）
    POST_PROCESS  = "post_process"    # 任务解析、对话保存
    POST_TTS      = "post_tts"        # TTS 合成

@dataclass
class PluginContext:
    """贯穿整个管道的上下文，插件间通过它传递数据"""
    # 输入
    user_id: int = 0
    message: str = ""
    is_asr_input: bool = False
    chat_id: Optional[int] = None
    history: list = field(default_factory=list)
    tts_enabled: bool = True
    model_type: Optional[str] = None

    # 中间产物
    system_prompt: str = ""
    full_history: list = field(default_factory=list)
    reply: str = ""
    original_reply: str = ""   # 保留标签的原始回复
    audio: Optional[bytes] = None
    filtered: bool = False     # PRE_FILTER 短路标记

    # 扩展
    extra: dict = field(default_factory=dict)


class Plugin:
    """插件基类，所有插件继承此类"""

    name: str = ""           # 唯一标识
    description: str = ""
    version: str = "1.0"
    hooks: list[HookPoint] = []  # 该插件监听的钩子
    priority: int = 50       # 同钩子下的执行优先级（越小越先执行）

    def on_load(self):
        """插件加载时调用，用于初始化资源"""
        pass

    def on_unload(self):
        """插件卸载时调用，用于清理资源"""
        pass

    async def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        """
        钩子回调。插件必须实现此方法。
        返回修改后的 ctx（或原样返回）。
        若 ctx.filtered = True，管道将短路。
        """
        return ctx
```

### 3.2 PluginManager (`plugins/manager.py`)

```python
class PluginManager:
    """
    职责:
    - 从 plugins/builtin/ 和 plugins/custom/ 扫描并加载插件
    - 按 HookPoint 索引插件，支持优先级排序
    - 启用/禁用/卸载插件
    - 对外暴露 dispatch(hook, ctx) 方法
    """
    def scan_and_load(self) -> int: ...
    def enable(self, name: str) -> bool: ...
    def disable(self, name: str) -> bool: ...
    def unload(self, name: str) -> bool: ...
    def list_plugins(self) -> list[dict]: ...
    async def dispatch(self, hook: HookPoint, ctx: PluginContext) -> PluginContext: ...
```

### 3.3 ChatPipeline (`plugins/pipeline.py`)

```python
class ChatPipeline:
    """
    编排整个对话流程。
    app.py 只调用 pipeline.process(message, user_id, ...)
    """
    def __init__(self, plugin_manager: PluginManager, prompt_engine, skill_registry=None):
        self.pm = plugin_manager
        self.prompt_engine = prompt_engine
        self.skill_registry = skill_registry

    async def process(self, ctx: PluginContext) -> PluginContext:
        # 1. PRE_FILTER  → ASR 过滤（可短路）
        # 2. PRE_PROCESS → 构建 system_prompt + 记忆注入
        # 3. MODEL_INVOKE → 模型调用
        # 4. POST_PROCESS → 任务解析 + 对话保存
        # 5. POST_TTS    → TTS 合成
        ...
```

---

## 四、管道流程

```
用户消息
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│ PRE_FILTER                                              │
│ ┌─────────────────┐                                     │
│ │ asr_filter_plugin│  ASR 语音输入过滤                   │
│ └─────────────────┘                                     │
│ → 被过滤则短路返回 (ctx.filtered = True)                  │
└──────────────────────┬──────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────┐
│ PRE_PROCESS                                             │
│ ┌─────────────────┐                                     │
│ │ memory_plugin   │  加载历史消息，注入记忆摘要           │
│ └─────────────────┘                                     │
│ ┌─────────────────┐                                     │
│ │ PromptEngine    │  (通过 pipeline，非插件)              │
│ │ build_system    │  组装 system prompt                  │
│ │ _prompt()       │                                     │
│ └─────────────────┘                                     │
└──────────────────────┬──────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────┐
│ MODEL_INVOKE (models_plugin 独占)                       │
│                                                         │
│  复杂度分析 → 选择模型 → 调用 LLM → 获取回复             │
└──────────────────────┬──────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────┐
│ POST_PROCESS                                            │
│ ┌─────────────────┐  ┌─────────────────┐                │
│ │ task_plugin     │  │ memory_plugin   │                │
│ │ 解析<task>标签  │  │ 保存对话+摘要   │                │
│ │ 执行技能工具调用 │  │                 │                │
│ └─────────────────┘  └─────────────────┘                │
└──────────────────────┬──────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────┐
│ POST_TTS (tts_plugin)                                   │
│ 提取 TTS 文本 → 调用 TTS 服务 → 返回音频                 │
└──────────────────────┬──────────────────────────────────┘
                       ▼
                   返回结果
```

---

## 五、内置插件详述

### 5.1 models_plugin（MODEL_INVOKE, priority=50）

```
职责:
- 持有 DeepSeekChat / LMStudioChat / LMSummaryModel 实例
- 内部维护 ComplexityAnalyzer
- 复杂度分析后自动选择模型 (fast/deep/reasoner)
- 支持流式调用
- 将 AI 回复写入 ctx.reply 和 ctx.original_reply
```

**需要从 app.py 迁移的代码:**
- `create_chat_client()` 工厂函数
- `ComplexityAnalyzer` 引用
- `chat.send_message()` 调用逻辑
- `handle_complex_question()` 逻辑

### 5.2 asr_filter_plugin（PRE_FILTER, priority=10）

```
职责:
- 仅当 ctx.is_asr_input 时生效
- 调用 LMFilterModel.filter_input(message)
- 若返回 "HOLD"：设置 ctx.filtered = True，生成记忆，短路管道
- 若返回 "FORWARD"：放行
```

**需要从 app.py 迁移的代码:**
- `filter_model.filter_input()` 调用逻辑（约 15 行）
- ASR 输入的记忆生成逻辑

### 5.3 memory_plugin（PRE_PROCESS + POST_PROCESS, priority=30）

```
职责:
- PRE_PROCESS: 调用 memory_manager.assemble_context() 组装历史+记忆
- POST_PROCESS: 调用 memory_manager.record_dialog_and_summary() 保存+摘要
```

**需要从 app.py 迁移的代码:**
- `memory_manager.assemble_context()` 调用
- `memory_manager.record_dialog_and_summary()` 调用

### 5.4 task_plugin（POST_PROCESS, priority=40）

```
职责:
- 解析 ctx.original_reply 中的 <task> 和 <tool> 标签
- <task> 标签 → 调用 task_manager 创建提醒/推理/动作任务
- <tool> 标签 → 调用 skill_registry 执行技能工具
- 将工具执行结果追加到 ctx.reply
```

**需要从 app.py 迁移的代码:**
- `parse_task_instructions()` 函数
- 任务创建逻辑（reminder / reasoner / action）

### 5.5 tts_plugin（POST_TTS, priority=60）

```
职责:
- 从 ctx.original_reply 提取纯文本供 TTS
- 调用 tts_client.tts() 合成语音
- 将音频写入 ctx.audio
```

**需要从 app.py 迁移的代码:**
- TTS 文本提取（移除标签）
- `tts_client.tts()` 调用及错误处理

---

## 六、插件管理 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/plugins/list` | 列出所有插件及其状态 |
| POST | `/api/plugins/<name>/enable` | 启用指定插件 |
| POST | `/api/plugins/<name>/disable` | 禁用指定插件 |

---

## 七、实现步骤

1. **先建框架，不动现有代码**
   - 创建 `plugins/base.py`（Plugin, HookPoint, PluginContext 三个类）
   - 创建 `plugins/manager.py`（PluginManager，含扫描/注册/调度）
   - 创建 `plugins/pipeline.py`（ChatPipeline，编排 HookPoint 调用）

2. **逐个迁移现有功能为插件**
   - 从最简单的开始：`tts_plugin.py`（约 30 行）
   - 然后是 `asr_filter_plugin.py`（约 30 行）
   - `memory_plugin.py`（约 40 行）
   - `task_plugin.py`（约 80 行）
   - `models_plugin.py`（最复杂，约 150 行）

3. **app.py 换用 ChatPipeline**
   - 在 `chat_send()` 和 `chat_stream_send()` 中构造 `PluginContext`
   - 调用 `pipeline.process(ctx)`
   - 从 ctx 读取结果构造 HTTP 响应

4. **验证**
   - 原有功能不受影响
   - 可通过 API 启用/禁用插件
