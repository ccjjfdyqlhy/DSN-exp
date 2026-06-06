# engine.py 补全 + app.py 依赖引擎迁移方案

> 策划案 | 版本: v1.0 | 2026-06-02
> 关联: `engine.py`（DSNEngine）、`app.py`（Flask 主进程）、`world/`、`plugins/`、`skills/`、`config.py`
> 状态: 草案，待评审

---

## 一、背景

当前 `app.py` 和 `engine.py` 存在严重的功能不对称。

### 现状结构

```
app.py (Flask)                          engine.py (DSNEngine)
│                                       │
├─ 初始化全部 18 个子系统                 ├─ 初始化 11 个子系统
│   (含 World, Narrative, TTS, ASR)     │   (World/Narrative 为 None, 无 TTS/ASR)
│                                       │
├─ 内联 chat_send / stream_send         ├─ chat() / chat_stream()
│   (自建 model client, 自写 agent loop,  │   (基于 ChatPipeline 插件管道)
│   自解析 tool/task, 自调 TTS/ASR)      │   (插件未被 app.py 使用)
│                                       │
├─ _dispatch_plugins_sync (仅2钩子)      ├─ PluginManager.dispatch (5钩子全)
│   (PersonalityPlugin, WorldPlugin,     │   (10 个插件, 含 ModelsPlugin/
│    ImpressionPlugin — 3个插件)         │    SkillsPlugin/AgentPlugin/TTSPlugin/
│                                       │    ASRFilterPlugin — 但一半未注册)
│                                       │
└─ 14 个 API 端点                       └─ 无 HTTP 层 (仅 programmatic API)
```

### 问题

1. **engine.py 缺少 13 项 app.py 已有功能**——World/Narrative/TTS/ASR 子系统未初始化，Reminder/Reasoner 处理缺失
2. **app.py 只用了 engine.py 的 2/5 钩子**——`PRE_FILTER`、`MODEL_INVOKE`、`POST_TTS` 完全绕过了插件管道
3. **代码重复**——ChatPipeline 的逻辑在 app.py 的 `chat_send`/`chat_stream_send` 中各实现了一遍，维护两个版本

---

## 二、全面差异分析

### 2.1 初始化子系统对比

| Subsystem | app.py | engine.py | 差异 |
|-----------|--------|-----------|------|
| ChatDBManager | ✅ | ✅ | 同等 |
| TaskManager + 队列 + 通知线程 | ✅ | ✅ | 同等 |
| ComplexityAnalyzer | ✅ | ❌ | **引擎未创建** |
| MemoryManager + LMSummaryModel | ✅ | ✅ | 同等 |
| TTS client (VocalExp) + `_tts_available` | ✅ | ❌ | **引擎未创建** |
| ASR filter (LMFilterModel) | ✅ | ❌ | **引擎未创建** |
| ASR model (FunASR) | ✅ | ❌ | 合理——引擎无 HTTP |
| PromptEngine | ✅ | ✅ | 同等 |
| PersonalitySystemV2 | ✅ | ✅ | 同等 |
| ImpressionManager | ✅ | ✅ | 同等 |
| WorldEngine + WorldStateManager | ✅ | ❌ | **声明为 None 但从未加载 YAML** |
| NarrativeModel | ✅ | ❌ | **声明为 None 但从未加载 prompt** |
| PluginManager | ✅ | ✅ | 同等 |
| SkillRegistry + SkillManager | ✅ | ✅ | 同等 |
| ChatPipeline | ❌ | ✅ | 引擎独有抽象 |
| `_tts_available` 全局标志 | ✅ | ❌ | 引擎无降级机制 |
| Auth / CORS / Login decorator | ✅ | ❌ | 合理——HTTP 层 |

### 2.2 插件注册对比

| 插件 | app.py | engine.py |
|------|--------|-----------|
| PersonalityPlugin | ✅ (POST_PROCESS) | ✅ (POST_PROCESS) — 条件 `enabled("personality")` |
| ImpressionPlugin | ✅ (PRE+POST) | ✅ (PRE+POST) — 条件 `enabled("impression")` |
| WorldPlugin | ✅ (PRE+POST) | ❌ **注册了但永不生效** — `self.world_engine` 永为 None |
| ModelsPlugin | ❌ (内联调用) | ✅ (MODEL_INVOKE) — 条件 `enabled("models")` |
| MemoryPlugin | ❌ (内联调用) | ✅ (PRE+POST) — 条件 `enabled("memory")` |
| RecallPlugin | ❌ (内联调用) | ✅ (POST) — 条件 `enabled("recall")` |
| SkillsPlugin | ❌ (内联调用) | ✅ (POST) — 条件 `enabled("skills")` |
| AgentPlugin | ❌ (内联调用) | ✅ (POST) — 条件 `enabled("agent")` |
| SSPPlugin | ❌ (内联检测) | ✅ (POST) — 条件 `enabled("ssp")` |
| TaskPlugin | ❌ (内联调用) | ✅ (POST) — 条件 `enabled("task")` |
| DistillPlugin | ❌ | ✅ (POST) — 条件 `enabled("distill")` |
| **ASRFilterPlugin** | ❌ (内联调用) | ❌ **类存在但从未注册** |
| **TTSPlugin** | ❌ (内联调用) | ❌ **类存在但从未注册** |
| **TodoPlugin** | ❌ (内联调用) | ❌ **类存在但从未注册** |

### 2.3 Chat 流程差异

| 步骤 | app.py chat_send | engine.py chat() |
|------|------------------|------------------|
| ASR 过滤 | 直接 `filter_model.filter_input()` | 无/PRE_FILTER 未被调度 |
| PRE_PROCESS | 手动 `_dispatch_plugins_sync(PRE_PROCESS)` | Pipeline PRE_PROCESS 阶段 |
| System prompt | `prompt.get_system_prompt(g.user)` | `pipeline._assemble_prompt()` |
| MODEL_INVOKE | `create_chat_client()` + `send_message()` | Pipeline MODEL_INVOKE — ModelsPlugin |
| message 保存 | 用 `round_index` | **不用 round_index** |
| POST_PROCESS | 手动 dispatch | Pipeline POST_PROCESS 阶段（8 个插件） |
| Tool 执行 | inline `<tool>` 正则 | SkillsPlugin |
| Recall 处理 | inline `<recall>` 正则 | RecallPlugin |
| Task 解析 | inline `parse_task_instructions` | TaskPlugin |
| Agent Loop | inline for 循环（工具+动作） | AgentPlugin |
| SSP 模式 | inline 检测 `<ssp>` + `max_steps=50` | SSPPlugin |
| TTS | 直接 `tts_client.tts()` | 无/POST_TTS 未被调度 |
| Narrative SSE | 手动从 `ctx.extra["narrative"]` yield | **无 narrative_update** |
| Impression 提取 | inline `_extract_and_save_impressions()` | ImpressionPlugin 只触发一次 |
| Memory 记忆 | `memory_manager.record_dialog_and_summary()` | MemoryPlugin |

### 2.4 Task 完成处理对比

| 任务类型 | app.py | engine.py |
|----------|--------|-----------|
| REMINDER | ✅ `_handle_reminder_completion` — 注入系统消息 | ❌ **无处理，静默丢弃** |
| REASONER | ✅ `_handle_reasoner_completion` — 注入推理结果 | ❌ **无处理，静默丢弃** |
| ACTION | ✅ `_handle_action_completion` 简版 | ✅ `_handle_engine_action_completion` 增强版（含重试 + AI 生成消息） |

### 2.5 engine.py 独有（app.py 没有）

| 功能 | 位置 | 说明 |
|------|------|------|
| Action 失败自动重试 | `_handle_engine_action_completion` → `_retry_engine_action` | AI 自我修正后重试，最多 3 次 |
| AI 生成结果消息 | `_generate_result_message` | 用 LLM 为 action 结果写自然语言说明 |
| 定时聊天 | `run_scheduled()` | Cron 表达式驱动的自主聊天 |
| 技能蒸馏 | DistillPlugin | 对话→技能草案 |

---

## 三、引擎补全（Phase 1）

### 3.1 缺失子系统初始化的 13 项

#### 3.1.1 World 系统（`_init_world()`）

```python
def _init_world(self):
    if not self._engine_cfg.world_enabled:
        return
    from world import WorldEngine, WorldStateManager, NarrativeModel, WorldPlugin
    preset_path = Path(self._cfg.resolve_path(self._engine_cfg.world_preset))
    self.world_engine = WorldEngine()
    self.world_engine.load_config_file(str(preset_path))
    self.world_state_manager = WorldStateManager(self.world_engine, update_interval=self._engine_cfg.world_update_interval)
    self.world_state_manager.start()
    if self._engine_cfg.narrative_enabled:
        self.narrative_model = NarrativeModel(
            model_type=self._engine_cfg.model_type,
            model_name=self._engine_cfg.narrative_model,
            temperature=self._engine_cfg.narrative_temperature,
            keep_history=self._engine_cfg.narrative_keep_history,
        )
        prompt_path = Path(self._cfg.resolve_path(self._engine_cfg.narrative_prompt_path))
        self.narrative_model.load_system_prompt_file(str(prompt_path))
```

**依赖配置键**（`config.py` + `EngineConfig`）：

| 键 | 默认值 |
|----|--------|
| `WORLD_ENABLED` | `true` |
| `WORLD_PRESET` | `"default"` |
| `WORLD_UPDATE_INTERVAL` | `60` |
| `NARRATIVE_ENABLED` | `true` |
| `NARRATIVE_MODEL` | `"deepseek-v4-flash"` |
| `NARRATIVE_TEMPERATURE` | `0.9` |
| `NARRATIVE_MAX_TOKENS` | `150` |
| `NARRATIVE_KEEP_HISTORY` | `false` |
| `NARRATIVE_PROMPT_PATH` | `"prompt/world/narrative.md"` |

#### 3.1.2 TTS 系统（`_init_tts()`）

```python
def _init_tts(self):
    if not self._engine_cfg.tts_enabled:
        return
    from vocal_infer import VocalExp
    self._tts_client = VocalExp(self._engine_cfg.tts_base_url)
    self._tts_available = True
```

#### 3.1.3 ASR Filter 注册（`_init_plugins()` 新增）

```python
if enabled("asr_filter"):
    from plugins.builtin.asr_filter_plugin import ASRFilterPlugin
    self.plugin_manager.register(ASRFilterPlugin(
        filter_model=self._filter_model,
        memory_manager=self.memory_manager,
    ))
```

#### 3.1.4 TodoPlugin 注册（`_init_plugins()` 新增）

```python
if enabled("todo"):
    from plugins.builtin.todo_plugin import TodoPlugin
    self.plugin_manager.register(TodoPlugin(task_manager=self.task_manager))
```

#### 3.1.5 ComplexityAnalyzer 创建（`_init_tasks()` 中新增）

```python
def _init_tasks(self):
    if not self._engine_cfg.task_manager_enabled:
        return
    ...
    self.task_manager = TaskManager(...)
    from complexity_analyzer import ComplexityAnalyzer
    self.complexity_analyzer = ComplexityAnalyzer()
```

#### 3.1.6 Reminder/Reasoner 任务完成处理

`_process_task_completion()` 中新增分支：

```python
def _process_task_completion(self):
    while self._running:
        try:
            task_id, result = self._task_queue.get(timeout=0.5)
            task = self.task_manager.get_task(task_id)
            if task.task_type in (TaskType.REMINDER, TaskType.REASONER):
                msg = self._format_task_result(task.task_type, task.params, result)
                if task.chat_id:
                    db.append_messages(task.user_id, task.chat_id, [{"role": "system", "content": msg}])
            ...
```

参见 app.py 的 `_handle_reminder_completion`（第 290-303 行）和 `_handle_reasoner_completion`（第 305-321 行）。

#### 3.1.7 `round_index` 追踪

在 ModelsPlugin 或 MemoryPlugin 的消息保存逻辑中增加：

```python
round_index = self.db.get_memory_count(user_id, chat_id) + 1
self.db.append_messages(user_id, chat_id, chat.messages[-2:], round_index=round_index)
```

#### 3.1.8 Agent Loop 中逐步 Impression 提取

AgentPlugin `_run_agent_loop` 中每步 continuation 后调用：

```python
if self._impression_manager:
    self._impression_manager.load_impressions_from_text(uid, continuation, "inferred")
```

#### 3.1.9 `narrative_update` SSE 事件

ChatPipeline `process_stream()` 中 POST_PROCESS 后增加：

```python
if hook == HookPoint.POST_PROCESS:
    narrative = ctx.extra.get("narrative", "")
    if narrative:
        yield f"data: {json.dumps({'status': 'narrative_update', 'text': narrative})}\n\n"
```

#### 3.1.10 `extensions/` prompt 目录

`_init_prompt()` 中的 `lib.scan_and_load` 增加：

```python
lib.scan_and_load(
    str(core_dir / "core"),
    str(core_dir / "capabilities"),
    str(core_dir / "extensions"),  # ← 新增
)
```

#### 3.1.11 `_tts_available` 降级标志

TTSPlugin 中首次失败时：

```python
def on_hook(self, hook, ctx):
    if not ctx.extra.get("tts_available", True):
        return ctx
    try:
        ...
    except Exception:
        ctx.extra["tts_available"] = False
```

---

## 四、app.py 依赖引擎（Phase 2）

### 4.1 最终架构

```
app.py (~400 行 — HTTP 壳)
│
├─ Flask 应用 / CORS / Logging / Auth
├─ 启动时: engine = create_engine_with_defaults(db, ...)  
│           (引擎负责所有业务子系统初始化)
│
├─ /api/chat/send
│   └─ 解析 HTTP → engine.chat() → JSON 响应
│
├─ /api/chat/stream_send
│   └─ 解析 HTTP → engine.chat_stream() → SSE 流
│
├─ /api/chat/*           (list/history/delete — 浅包装)
├─ /api/personality/*    (浅包装 engine 状态查询)
├─ /api/impressions/*    (浅包装 engine 印象查询)
└─ /api/auth/*           (JWT — 仍在 HTTP 层处理)
```

### 4.2 核心改动

#### 初始化流程精简

```python
# app.py 启动 (Before: ~120 行初始化代码)
engine = create_engine_with_defaults(
    db=db,
    memory_manager=memory_manager,
    skill_registry=skill_registry,
    skill_manager=skill_manager,
    impression_manager=impression_manager,
)
# 引擎内部完成: world, narrative, tts, plugins, pipeline 全部初始化
```

#### chat_send 精简

```python
@login_required
def chat_send():
    data = request.get_json()
    result = engine.chat(
        user_id=g.user["uid"],
        message=data["message"],
        chat_id=data.get("chat_id"),
        model_type=data.get("model_type"),
        tts_enabled=data.get("tts_enabled", True),
        is_asr_input=data.get("is_asr_input", False),
        chat_name=data.get("chat_name", "未命名"),
    )
    return jsonify(result)
```

#### chat_stream_send 精简

```python
@login_required
async def chat_stream_send():
    async for event in engine.chat_stream(...):
        yield event  # 所有 SSE 由引擎生成
    return Response(stream_with_context(generate()), mimetype="text/event-stream")
```

### 4.3 移出 app.py 的代码

| 删除的代码 | 行数 | 替代 |
|-----------|------|------|
| `create_chat_client()` | 20 | ModelsPlugin |
| `parse_task_instructions()` | 45 | TaskPlugin |
| `_format_tool_result()` | 90 | SkillsPlugin + app.py 保留浅包装 |
| `handle_complex_question()` | 40 | ComplexityAnalyzer + TaskPlugin |
| `_process_tasks_completion()` | 30 | TaskManager 内部 |
| `_handle_reminder_completion()` | 15 | engine.py 补全 |
| `_handle_reasoner_completion()` | 15 | engine.py 补全 |
| `_handle_action_completion()` | 35 | engine.py 已有 |
| `_dispatch_plugins_sync()` | 10 | ChatPipeline |
| `_clean_display()` | 10 | ModelsPlugin._clean_reply() |
| `_extract_actions()` | 10 | AgentPlugin |
| `_extract_and_save_impressions()` | 15 | ImpressionPlugin |
| `_format_action_result()` | 5 | AgentPlugin |
| `_process_tools_and_recall()` | 30 | SkillsPlugin + RecallPlugin |
| `chat_send` 内联业务 | 200 | `engine.chat()` |
| `chat_stream_send` 内联业务 | 250 | `engine.chat_stream()` |
| **合计删除** | **~820 行** | |

---

## 五、配置键补充（`config.py` + `EngineConfig`）

| 配置键 | 默认值 | 说明 |
|--------|--------|------|
| `TTS_ENABLED` | `true` | 启用 TTS 语音合成 |
| `TTS_BASE_URL` | `"http://localhost:9880"` | TTS 服务地址 |
| `TTS_AVAILABLE` | `true` | 运行时标志，首次失败后置 false |
| `WORLD_ENABLED` | `true` | 世界模型总开关 |
| `WORLD_PRESET` | `"default"` | 世界预设名称 |
| `WORLD_UPDATE_INTERVAL` | `60` | 状态刷新间隔（秒） |
| `NARRATIVE_ENABLED` | `true` | 叙事旁白总开关 |
| `NARRATIVE_MODEL` | `"deepseek-v4-flash"` | 叙事模型名称 |
| `NARRATIVE_TEMPERATURE` | `0.9` | 旁白创造力 |
| `NARRATIVE_MAX_TOKENS` | `150` | 旁白长度上限 |
| `NARRATIVE_KEEP_HISTORY` | `false` | 叙事历史是否累积 |
| `NARRATIVE_PROMPT_PATH` | `"prompt/world/narrative.md"` | 叙事 system prompt 路径 |
| `ROUND_INDEX_TRACKING` | `true` | 是否追踪 round_index |

---

## 六、实施步骤

| Phase | 内容 | 文件 | 预计增量 |
|-------|------|------|---------|
| **P1a** | `_init_world()` + World/Narrative 配置 | `engine.py`, `subapp_loader.py`, `config.py` | +80 行 |
| **P1b** | `_init_tts()` + TTSPlugin 注册 + `_tts_available` | `engine.py`, `TTSPlugin`, `config.py` | +40 行 |
| **P1c** | ASRFilterPlugin + TodoPlugin 注册 | `engine.py` | +15 行 |
| **P1d** | ComplexityAnalyzer 创建 | `engine.py`, `_init_tasks()` | +5 行 |
| **P1e** | Reminder/Reasoner 完成处理 | `engine.py` `_process_task_completion` | +50 行 |
| **P1f** | round_index + per-step impression + narrative SSE + extensions | `engine.py`, `ModelsPlugin`, `MemoryPlugin`, `AgentPlugin`, `TTSPlugin`, `pipeline.py` | +60 行 |
| **P1g** | SubAppConfig + EngineConfig 新增字段 | `subapp_loader.py`, `Config` | +25 行 |
| **P2** | app.py 精简 | `app.py` | **-800 行** |
| **P3** | 测试 | 新测试文件 | +200 行 |

---

## 七、风险与注意事项

1. **双轨冲突风险**：P1 阶段 engine.py 补全后，app.py 的 inline 逻辑和 engine 内部的插件逻辑**同时存在**。在 P2 完成前不要同时激活两条路径，以免双重处理（如消息被存两次、TTS 被调用两次）。

2. **`format_tool_result` 归属**：`_format_tool_result()` 对多种技能有格式化逻辑（web_search、file_manager、browser_use、skillmgr）。它必须保留在 app.py 或移到与 SkillsPlugin 相邻的位置。建议移到 `skills/formatter.py`，同时被 app.py 和 engine.py 引用。

3. **`_tts_available` 全局 flag**：需要跨模块共享。建议放在引擎实例上（`self._tts_available`），TTSPlugin 通过 `ctx.extra["tts_available"]` 读写。

4. **功能回归**：P2 精简 app.py 后，所有现有功能必须完整回归测试。重点检查：
   - ASR 过滤 + HOLD 记忆
   - Agent Loop 工具链
   - SSP 自维持管线
   - Narrative SSE 事件
   - TTS 降级
   - Impression 提取
