# 聊天管线与插件系统

## 架构概览

```
用户输入
   │
   ▼
┌──────────────────────────────────────────────────────────────────┐
│  ChatPipeline.process_stream(ctx)                                 │
│                                                                  │
│  Hook 顺序 (硬编码):                                              │
│                                                                  │
│  1. PRE_FILTER     ─── PluginManager.dispatch(PRE_FILTER, ctx)   │
│  2. Prompt 组装    ─── _assemble_prompt(ctx)  (内联，非 Hook)     │
│  3. PRE_PROCESS    ─── 并行模式: VisionPlugin || 其他插件         │
│  4. MODEL_INVOKE   ─── PluginManager.dispatch(MODEL_INVOKE, ctx) │
│  5. POST_PROCESS   ─── PluginManager.dispatch(POST_PROCESS, ctx) │
│  6. Agent 循环     ─── 硬编码，循环执行 MODEL_INVOKE + POST_PROCESS│
│  7. TTS 合成       ─── 硬编码 _synthesize_lines_stream           │
│  8. POST_TTS       ─── PluginManager.dispatch(POST_TTS, ctx)     │
│  9. yield completed                                               │
└──────────────────────────────────────────────────────────────────┘
   │
   ▼
  SSE 事件流 → 前端
```

- Hook 顺序和数量是 **硬编码** 的，无法通过配置改变
- 每个 Hook 点内部的插件按 `priority` 升序执行
- `Plugin`（同步）在 executor 线程池中执行；`AsyncPlugin`（异步）直接 await
- 任何插件可设 `ctx.filtered = True` 短路后续流水线
- 插件通过 `ctx.extra` 字典互相通信

---

## PluginContext

定义在 `plugins/base.py`，是贯穿管线全流程的数据载体。

### 输入字段

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `user_id` | `int` | `0` | 用户 ID |
| `message` | `str` | `""` | 用户本轮消息 |
| `chat_id` | `Optional[int]` | `None` | 聊天 ID |
| `chat_name` | `str` | `"未命名"` | 聊天显示名 |
| `history` | `list` | `[]` | 聊天历史（原始） |
| `is_asr_input` | `bool` | `False` | 是否语音输入 |
| `tts_enabled` | `bool` | `True` | 是否启用 TTS |
| `model_type` | `Optional[str]` | `None` | 模型类型覆盖 |
| `nickname` | `str` | `"用户"` | 用户昵称 |
| `image_data` | `Optional[str]` | `None` | Base64 图片 |
| `cross_user_id` | `Optional[int]` | `None` | Agent 模式下绑定的用户 ID |
| `skip_model` | `bool` | `False` | 是否跳过模型调用（剧本回放） |
| `agent_active` | `bool` | `False` | Agent 循环开关 |
| `agent_max_steps` | `int` | `5` | Agent 最大步数 |
| `agent_token_budget` | `int` | `1000000` | Token 预算 |
| `recall_engine` | `Optional[Any]` | `None` | 记忆召回引擎 |

### 输出/中间字段

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `system_prompt` | `str` | `""` | 组装后的系统提示词 |
| `full_history` | `list` | `[]` | 注入记忆后的增强历史 |
| `reply` | `str` | `""` | 清理后的回复（前端/TTS 用） |
| `original_reply` | `str` | `""` | 原始回复（含标签） |
| `audio` | `Optional[bytes]` | `None` | TTS 音频字节 |
| `audio_b64` | `Optional[str]` | `None` | TTS 音频 base64 |
| `filtered` | `bool` | `False` | 短路标志 |
| `tts_error` | `Optional[str]` | `None` | TTS 错误信息 |
| `usage` | `Optional[dict]` | `None` | API 用量 |
| `model_name` | `Optional[str]` | `None` | 实际使用的模型名 |
| `extra` | `dict` | `{}` | 插件间通信的扩展字典 |

---

## HookPoint 枚举

定义在 `plugins/base.py`，按管线执行顺序排列：

| HookPoint | 值 | 用途 |
|-----------|-----|------|
| `PRE_FILTER` | `"pre_filter"` | 输入过滤、缓存命中。可 `filtered=True` 短路 |
| `PRE_PROCESS` | `"pre_process"` | 提示词注入、记忆组装、上下文增强 |
| `MODEL_INVOKE` | `"model_invoke"` | LLM 调用（通常只有 ModelsPlugin） |
| `POST_PROCESS` | `"post_process"` | 工具执行、任务解析、交互存档 |
| `POST_TTS` | `"post_tts"` | TTS 后备合成 |

---

## 插件的两种基类

### Plugin（同步）— `plugins/base.py:64`

```python
class Plugin:
    name = ""
    description = ""
    version = "1.0"
    hooks: list[HookPoint] = []
    priority: int = 50   # 越小越先执行

    def on_load(self) -> None: ...
    def on_unload(self) -> None: ...
    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext: ...
```

`on_hook` 是同步方法，Pipeline 在 executor 线程池中执行它。

### AsyncPlugin（异步）— `plugins/base.py:96`

```python
class AsyncPlugin:
    # 同名字段
    async def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext: ...
```

`on_hook` 是 async 方法，Pipeline 直接 await。

---

## PluginManager — `plugins/manager.py`

### 内部结构

- `_plugins: dict[str, _PluginT]` — 所有已注册插件
- `_enabled: dict[str, bool]` — 启用状态
- `_hook_index: dict[HookPoint, list[_PluginT]]` — 按 Hook 索引，按 priority 排序

### 核心方法

| 方法 | 说明 |
|------|------|
| `register(plugin)` | 注册插件，按 priority 插入到各个 Hook 的索引 |
| `unregister(name)` | 从所有索引中移除 |
| `enable(name)` / `disable(name)` | 启用/禁用 |
| `dispatch(hook, ctx)` | 执行某 Hook 的所有已启用插件 |
| `dispatch_only(hook, ctx, names)` | 只执行指定名称的插件 |
| `dispatch_except(hook, ctx, skip_names)` | 跳过指定名称的插件 |

### dispatch 执行逻辑

```python
async def _dispatch_filtered(self, hook, ctx, plugin_filter):
    for plugin in self._hook_index[hook]:     # 按 priority 排序
        if not plugin_filter(plugin):
            continue
        if not self._enabled.get(plugin.name, False):
            continue
        ctx = await self._call_plugin(plugin, hook, ctx)
        if ctx.filtered:                       # 短路
            break
    return ctx
```

---

## 各 Hook 点插件执行顺序

### PRE_FILTER

| Priority | 插件 | 文件 | 说明 |
|----------|------|------|------|
| 0 | `cache_interceptor` | `plugins/builtin/cache_interceptor.py` | 语义缓存命中 → `filtered=True` |
| 10 | `asr_filter` | `plugins/builtin/asr_filter_plugin.py` | ASR 噪声过滤 → `filtered=True` |
| 10 | `script` | `scripts/plugin.py` | OOC 检测 → `filtered=True` |

### PRE_PROCESS

| Priority | 插件 | 文件 | 说明 |
|----------|------|------|------|
| 15 | `world` | `world/plugin.py` | 注入世界状态 + 命运提示 + 预叙事 |
| 22 | `impression` | `plugins/builtin/impression_plugin.py` | 注入用户印象 |
| 28 | `vision` | `plugins/builtin/vision_plugin.py` | 图片→文字描述（并行路径） |
| 30 | `memory` | `plugins/builtin/memory_plugin.py` | 记忆注入组装 full_history |
| 39 | `notebook` | `plugins/builtin/notebook/notebook_plugin.py` | 定期提示写观察笔记 |
| 42 | `plan` | `plugins/builtin/plan_plugin.py` | 注入今日计划 |

### MODEL_INVOKE

| Priority | 插件 | 文件 | 说明 |
|----------|------|------|------|
| 50 | `models` | `plugins/builtin/models_plugin.py` | LLM 调用 + tool call 处理 |

### POST_PROCESS

| Priority | 插件 | 文件 | 说明 |
|----------|------|------|------|
| 10 | `script` | `scripts/plugin.py` | 剧本进度、关键点记录 |
| 15 | `world` | `world/plugin.py` | 后叙事、世界时间推进 |
| 22 | `impression` | `plugins/builtin/impression_plugin.py` | 提取印象 |
| 24 | `personality_v3` | `plugins/builtin/personality_v3_plugin.py` | V3 情绪分析（后台线程） |
| 25 | `personality` | `plugins/builtin/personality_plugin.py` | V2 情绪更新（V3 未启用时） |
| 30 | `memory` | `plugins/builtin/memory_plugin.py` | 对话轮次摘要 |
| 33 | `todo` | `plugins/builtin/todo_plugin.py` | 复杂任务分解 |
| 33 | `recall` | `plugins/builtin/recall_plugin.py` | `<recall>`/`<memo>` 标签处理 |
| 35 | `tool` | `plugins/builtin/tool_plugin.py` | 工具调用执行 |
| 39 | `notebook` | `plugins/builtin/notebook/notebook_plugin.py` | `<notebook>` 标签提取 |
| 40 | `task` | `plugins/builtin/task_plugin.py` | `<task>` 标签解析 + 任务创建 |
| 42 | `plan` | `plugins/builtin/plan_plugin.py` | `<plan_check>` + 日报 |
| 100 | `distill` | `plugins/builtin/distill_plugin.py` | V3 + 技能蒸馏触发 |

### POST_TTS

| Priority | 插件 | 文件 | 说明 |
|----------|------|------|------|
| 0 | `cache_interceptor` | `plugins/builtin/cache_interceptor.py` | 缓存未命中→写入缓存 |
| 60 | `tts` | `plugins/builtin/tts_plugin.py` | TTS 合成（后备，管线内联优先） |

---

## 管线内联逻辑（非 Hook）

以下逻辑 **不通过 Hook 点执行**，直接在 pipeline.py 硬编码：

### 1. Prompt 组装 — `_assemble_prompt(ctx)`

```
core/*.md → 人格描述(V3/V2) → capabilities/*.md → skill prompts → extensions/*.md → 用户上下文 → initialize.md → constant prompts
```

`TOOL_CALL_MODE=native` 时跳过 capabilities 和 skill prompts。

### 2. Agent 循环

在 POST_PROCESS 之后硬编码执行：

```
while agent_step < max_steps and _tag_results:
    1. ModelsPlugin.invoke()      # LLM 调用（含工具 schema）
    2. POST_PROCESS dispatch      # 执行工具
    3. 累加 _tag_results
```

每步结果通过 SSE 事件流式推送。

### 3. TTS 合成

```python
_synthesize_lines_sync(text)  →  逐行 TTS API 调用  →  tts_q（异步队列）
                                                       →  while 循环 drain → yield "line" 事件
```

管线通过 `_tts_client` 直接合成，`POST_TTS` 仅在 `_tts_client` 为 None 时作为后备。

---

## 插件注册方式

插件是 **纯手动注册** 的，无自动发现机制。

### 注册入口 A — `engine.py:create_engine_with_defaults()`

```python
engine.plugin_manager.register(ASRFilterPlugin(filter_model=..., db=...))
engine.plugin_manager.register(VisionPlugin(models_plugin=...))
engine.plugin_manager.register(MemoryPlugin(memory_system=..., db=...))
# ... 约 15 个 register() 调用
```

### 注册入口 B — `boot.py`

```python
# 语义缓存
engine.plugin_manager.register(CacheInterceptorPlugin(cache_engine=...))
# 剧本
engine.plugin_manager.register(ScriptPlugin(engine=..., ...))
```

### 注册入口 C — `engine.py:_init_plugins()`（子应用模式）

自动扫描子应用配置的 `plugins_enable`/`plugins_disable`，按分类调用六个 `_register_*_plugins()` 方法。

要加新插件需手动 import、实例化、调用 `register()`。

---

## ctx.extra 字典 — 插件间通信

`ctx.extra` 是插件间共享数据的唯一通道。以下列举所有被使用的 key：

### 由 engine/pipeline 写入

| Key | 类型 | 写入者 | 说明 |
|-----|------|--------|------|
| `_task_manager` | TaskManager | engine.build_context | 任务管理器实例 |
| `_completion_queue` | Queue | engine.build_context | 任务完成队列 |
| `_db` | ChatDBManager | engine.build_context | 数据库实例 |
| `_debug_mode` | bool | engine.build_context | 调试模式标志 |
| `_hibernate_manager` | HibernateManager | engine.build_context | 性能休眠管理器 |
| `_sensing_hint` | str | engine.build_context | 感知提示 |
| `_plugin_manager` | PluginManager | pipeline | 插件管理器引用 |
| `_plugin_timings` | dict | pipeline/manager | 各插件耗时 |
| `_narrative_collector` | ActionNarrativeCollector | pipeline | 行动叙事收集器 |
| `_activated_tools` | list[str] | pipeline/ModelsPlugin | 已激活工具 ID |
| `_progress_queue` | Queue | pipeline(stream) | 进度 SSE 队列 |
| `_agent_progress_queue` | Queue/False | pipeline(stream) | Agent 进度队列 |
| `_agent_reply_dirty` | bool | pipeline | Agent 修改了回复 |
| `_agent_step` | int | pipeline | 当前 Agent 步数 |
| `_async_task_id` | str | pipeline | 异步后台任务 ID |
| `action_narratives` | list[str] | pipeline | 已完成的行动叙事 |
| `tts_lines` | list[dict] | pipeline | 逐行 TTS 结果 |
| `_async_detected` | bool | ModelsPlugin | 检测到异步工具 |
| `_async_tool_count` | int | ModelsPlugin | 异步工具调用数 |
| `_native_tool_calls` | list | ModelsPlugin/ToolPlugin | 原生 tool call 对象 |
| `_last_tool_calls` | list | ModelsPlugin | 所有 tool calls |
| `_tag_results` | list[dict] | 多个插件 | 累积的标签执行结果 |
| `_pending_tasks` | set[str] | TaskPlugin | 待轮询的后台任务 |
| `round_index` | int | ModelsPlugin | 当前对话轮次 |

### 由插件写入

| Key | 写入插件 | 说明 |
|-----|----------|------|
| `sc_intent`, `sc_hit`, `sc_action_signature`, `sc_slot_hash`, `sc_similarity`, `sc_cache_key`, `sc_observer_key`, `sc_observer_end`, `sc_cached_key` | CacheInterceptorPlugin | 语义缓存元数据 |
| `script_ooc`, `script_ooc_soft`, `script_ooc_redirect`, `script_replayed`, `script_progressed`, `script_completed`, `script_key_points`, `chapter_advanced` | ScriptPlugin | 剧本状态 |
| `world_snapshot`, `world_activated`, `pre_narrative`, `narrative`, `narrative_speaker`, `_action_narrator` | WorldPlugin | 世界状态 |
| `impression_count`, `suggest_ssp` | ImpressionPlugin | 印象计数 |
| `image_description`, `image_data_url` | VisionPlugin | 图片描述 |
| `confirm_requested` | ToolPlugin | 确认请求信号 |
| `ssp_active`, `ssp_stopped`, `ssp_requested` | SSPPlugin (未注册) | SSP 状态 |
| `tts_available` | TTSPlugin | TTS 可用性 |

---

## 注册但未使用的插件（死代码）

| 插件 | 文件 | Hook | 原因 |
|------|------|------|------|
| `help` | `plugins/builtin/help_plugin.py` | POST_PROCESS(5) | 从未在任何地方 register |
| `ssp` | `plugins/builtin/ssp_plugin.py` | POST_PROCESS(50) | 从未在任何地方 register |
| `confirm` | `plugins/builtin/confirm_plugin.py` | (无) | 已弃用空壳 |
