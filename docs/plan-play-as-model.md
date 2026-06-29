# DEBUG_PLAY_AS_MODEL — 调试模式策划案

## 1. 概述

`DEBUG_PLAY_AS_MODEL` 是一种双角色调试模式，让开发者/测试者同时扮演"用户"和"AI模型"两个角色，以便在不依赖真实 LLM API 的情况下，完整测试系统的插件、技能、工具调用、Agent 循环等全部管线流程。

### 核心价值

- **脱离 API 依赖**：不需要 DeepSeek/LMStudio API 密钥即可进行全流程测试
- **精确控制模型输出**：开发者可以输入特定文本或触发特定工具调用，验证下游行为
- **工具调用测试**：通过交互式菜单逐级选择技能和工具，验证工具调用链
- **回归测试**：可复现的测试场景，无需等待 LLM 生成

---

## 2. 架构设计

```
play_as_model.py (CLI 前端)
       │
       │ HTTP (127.0.0.1:DEBUG_PORT)
       ▼
Flask Debug 蓝图 (api/debug.py)
       │
       ▼
DSNEngine.chat_debug()
       │
       ├── 1. build_context (跳过 DB)
       ├── 2. PRE_FILTER
       ├── 3. PRE_PROCESS (记忆/世界/人格完整运行)
       ├── 4. → 返回上下文给前端 ← (代替 MODEL_INVOKE)
       │      前端展示给"模型角色"用户
       ├── 5. ← 用户以模型身份回复 ←
       ├── 6. POST_PROCESS (工具执行)
       ├── 7. Agent Loop (如有工具结果)
       └── 8. POST_TTS
```

### 双角色交替流程

```
[用户角色]  输入消息 "帮我设个提醒"
     │
     ▼
[系统]      处理 PRE_PROCESS → 返回上下文 + 技能列表
     │
     ▼
[模型角色]  用户看到完整上下文，选择技能或直接回复
           例: "好的，我来设一个提醒。"
           或交互式选择 create_reminder 工具
     │
     ▼
[系统]      处理 POST_PROCESS → 执行工具 → Agent Loop → 返回最终结果
     │
     ▼
[用户角色]  继续下一轮对话...
```

---

## 3. 配置项

### config.py 新增

```python
# ==================== 调试模式 ====================
DEBUG_PLAY_AS_MODEL = _env("DEBUG_PLAY_AS_MODEL", "false").lower() == "true"
DEBUG_PLAY_AS_MODEL_PORT = int(_env("DEBUG_PLAY_AS_MODEL_PORT", "5050"))
```

### EngineConfig 新增

```python
debug_play_as_model: bool = Config.DEBUG_PLAY_AS_MODEL
debug_play_as_model_port: int = Config.DEBUG_PLAY_AS_MODEL_PORT
```

---

## 4. 后端实现

### 4.1 Engine 改动 (`engine.py`)

**`build_context` 方法**：当 `DEBUG_PLAY_AS_MODEL` 为 `True` 时，跳过 `ctx.extra["_db"]` 的注入。

**新增 `chat_debug` 方法**：两阶段处理。

```python
async def chat_debug(self, message, user_id=1, chat_id=None, ...) -> dict:
    """调试模式对话，分两阶段返回"""

    # Phase 1: 构建上下文 + PRE_PROCESS
    ctx = self.build_context(..., skip_db=True)
    ctx = await self.pipeline.process_pre_process(ctx)
    # 收集上下文信息供前端展示
    context_info = {
        "system_prompt": ctx.system_prompt,
        "history": ctx.full_history,
        "message": ctx.message,
        "skills": self._get_skills_info(),
    }
    return {"phase": "pre_process", "context": context_info, ...}

async def chat_debug_respond(self, session_id, reply, tool_calls=None) -> dict:
    """Phase 2: 以模型回复继续管线"""
    ctx = self._restore_context(session_id)
    ctx.original_reply = reply
    ctx.reply = _clean_reply(reply)
    # 处理工具调用
    if tool_calls:
        ctx.extra["_native_tool_calls"] = tool_calls
    # 执行 POST_PROCESS + Agent Loop + TTS
    ctx = await self.pipeline.process_post_process(ctx)
    ...
```

### 4.2 Pipeline 新增方法 (`plugins/pipeline.py`)

新增 `process_pre_process` 和 `process_post_process` 两个公开方法，分别执行管线的前半段和后半段：

```python
async def process_pre_process(self, ctx: PluginContext) -> PluginContext:
    """执行管线前半段：PRE_FILTER → PRE_PROCESS"""
    ctx = await self.pm.dispatch(HookPoint.PRE_FILTER, ctx)
    self._assemble_prompt(ctx)
    ctx = await self._dispatch_pre_process(ctx)
    return ctx

async def process_post_process(self, ctx: PluginContext) -> PluginContext:
    """执行管线后半段：POST_PROCESS → Agent Loop → POST_TTS"""
    ctx = await self._dispatch_post_process(ctx)
    if ctx.agent_active and ctx.extra.get("_tag_results"):
        ctx = await self._run_agent_loop(ctx)
    # TTS
    if ctx.tts_enabled and ctx.reply and self._tts_client:
        tts_lines = await self._synthesize_lines(ctx.reply)
        ...
    return ctx
```

### 4.3 Debug API 蓝图 (`api/debug.py`)

新建 Flask 蓝图，注册在独立的端口上：

| 端点 | 方法 | 说明 |
|---|---|---|
| `/debug/chat` | POST | 阶段1: 用户发消息，返回上下文 |
| `/debug/respond` | POST | 阶段2: 模型角色回复，返回最终结果 |
| `/debug/skills` | GET | 获取所有可用技能/工具列表 |
| `/debug/tool_schema/<skill>/<tool>` | GET | 获取指定工具的参数字段定义 |

会话管理：使用 `uuid` 作为 `session_id`，上下文存储在内存字典中（自动过期，最多 64 个会话）。

### 4.4 主服务启动 (`main.py`)

当 `DEBUG_PLAY_AS_MODEL=True` 时，额外启动一个 Werkzeug 服务器：

```python
if Config.DEBUG_PLAY_AS_MODEL:
    debug_host = "127.0.0.1"
    debug_port = Config.DEBUG_PLAY_AS_MODEL_PORT
    debug_app = create_debug_app(engine)
    debug_server = make_server(debug_host, debug_port, debug_app, threaded=True)
    threading.Thread(target=debug_server.serve_forever, daemon=True).start()
```

---

## 5. CLI 前端 (`play_as_model.py`)

### 5.1 界面设计

```
╔══════════════════════════════════════════════════╗
║           DEBUG PLAY-AS-MODEL MODE              ║
║   http://127.0.0.1:5050                         ║
╚══════════════════════════════════════════════════╝

── [用户] ──────────────────────────────────────────
你好，帮我设一个1分钟后的提醒

── [系统] 上下文预览 ──────────────────────────────
系统提示词：[已生成，共 2458 字符]
对话历史：2 条
可用技能：system(8), builtin(12), custom(3)

── [你 = 模型] 请以 AI 身份回复 ──────────────────
可用指令: /skills 浏览技能 /tool <name> 使用工具 /skip 跳过
> 好的，我来帮你设一个提醒。
> /tool create_reminder
  ┌─ text: "1分钟测试提醒"
  ┌─ time: "2026-06-29T20:44:00"
> 已设置完成，1分钟后会提醒你。
> /done

── [系统] 工具执行结果 ──────────────────────────
✓ create_reminder → {"task_id": "..."}

── [用户] ──────────────────────────────────────────
>
```

### 5.2 命令系统

| 命令 | 说明 |
|---|---|
| `/help` | 显示帮助 |
| `/skills` | 列出所有可用技能和工具 |
| `/tool <name>` | 进入工具选择模式，引导输入参数 |
| `/skip` | 跳过当前模型角色，切换回用户角色 |
| `/done` | 结束模型回复，提交给管线处理 |
| `/context` | 显示当前完整上下文（system prompt + 历史） |
| `/clear` | 清屏 |
| `/exit` | 退出调试模式 |

### 5.3 工具选择交互

当用户输入 `/tool <name>` 时，进入交互式参数填写：

```
> /tool create_reminder
  工具: create_reminder (创建提醒)
  参数:
    text (string, 必填): 1分钟后提醒我测试
    time (string, 必填): 2026-06-29T20:44:00
  确认使用此工具? [Y/n] Y
  已添加到当前回复
```

可以在一次回复中使用多个工具，最后用 `/done` 提交。

### 5.4 技术实现

```python
class PlayAsModelCLI:
    def __init__(self, base_url):
        self.session_id = str(uuid4())
        self.role = "user"  # "user" | "model"
        self.current_reply = ""
        self.current_tool_calls = []

    def run(self):
        while True:
            if self.role == "user":
                text = input("── [用户] ──\n> ")
                if text.startswith("/"):
                    self._handle_user_command(text)
                else:
                    self._send_user_message(text)
                    self.role = "model"
            elif self.role == "model":
                text = input("── [你 = 模型] ──\n> ")
                if text.startswith("/"):
                    self._handle_model_command(text)
                else:
                    self.current_reply += text + "\n"

    def _handle_model_command(self, cmd):
        if cmd == "/skip":
            self._submit_reply()
            self.role = "user"
        elif cmd.startswith("/tool"):
            self._interactive_tool_select(cmd)
        elif cmd == "/done":
            self._submit_reply()
            self.role = "user"
        elif cmd == "/context":
            self._show_context()
```

---

## 6. DB 跳过机制

当 `DEBUG_PLAY_AS_MODEL=True` 时，所有数据库写入被跳过：

1. `engine.build_context()` 不注入 `_db` 到 `ctx.extra`
2. `models_plugin.py` 中 `if self._db is not None and ctx.chat_id:` 条件不满足，跳过 `append_messages`
3. `ChatPipeline._run_async_background` 中的 store 操作静默跳过
4. `MemoryPlugin._on_post_process` 中的 `summarize_turn` 跳过（因为 `_db` 为 `None`）

---

## 7. 安全与边界

### 网络隔离
- Debug 服务仅绑定 `127.0.0.1`，不对外暴露
- 端口默认 `5050`，与主服务端口 `5000` 不同
- 无需认证，仅限本地开发调试

### 并发限制
- Debug 模式与正常模式互斥 — 不能同时运行
- 单次只能有一个活跃会话

### 状态清理
- 会话超过 64 个时自动淘汰最旧的
- 会话超过 30 分钟无活动自动过期

---

## 8. 文件改动清单

| 文件 | 改动 |
|---|---|
| `config.py` | 新增 `DEBUG_PLAY_AS_MODEL`、`DEBUG_PLAY_AS_MODEL_PORT` |
| `engine.py` | `EngineConfig` 新增对应字段，`build_context` 跳过 DB，新增 `chat_debug`、`chat_debug_respond` |
| `plugins/pipeline.py` | 新增 `process_pre_process`、`process_post_process` 方法 |
| `api/debug.py` | **新文件** — Debug Flask 蓝图 |
| `main.py` | Debug 模式启动独立服务器 |
| `play_as_model.py` | **新文件** — CLI 交互前端 |
