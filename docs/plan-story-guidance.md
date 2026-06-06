# 剧情引导模块 — StoryEngine + OOCDetector + StoryPlugin

> 策划案 | 版本: v1.0 | 2026-06-02
> 关联: `stories/`（新建独立模块）、`plugins/`（StoryPlugin）、`chatdbmgr.py`（story_state 表）、`app.py`（PRE_FILTER 调度）
> 状态: 草案，待评审

---

## 一、问题

当前 EXA 和用户的交互是完全自由开放的——用户问什么，AI 就回答什么。缺少一种**有结构的引导机制**，让 AI 能在特定场景下（如首次使用、新功能解锁、关键剧情点）主动地、按剧本地引导用户完成**必须经历**的交互。

具体痛点：

| # | 问题 | 场景 |
|---|------|------|
| 1 | **新手引导缺失** | 新用户安装后不知道 EXA 能做什么，AI 也不知道怎么介绍自己 |
| 2 | **用户偏离话题时无反馈** | 剧情模式下用户问无关问题，AI 会配合回答而不是引导回来 |
| 3 | **关键交互无法保障** | AI 必须完成的关键动作（如展示能力、读取文件）可能被跳过 |
| 4 | **缺乏进度感** | 没有章节、关键点、完成度的概念，交流是无结构的 |

## 二、总体设计

```
stories/                        ★ 独立模块
├── __init__.py                 导出 StoryEngine, StoryPlugin, OOCDetector, StoryState
├── engine.py                   StoryEngine — 剧情解析/状态机/进度管理
├── ooc_detector.py             OOCDetector — 第二个 LLM 检测越界内容
├── plugin.py                   StoryPlugin — PRE_FILTER(OOC) + PRE_PROCESS(引导注入) + POST_PROCESS(进度)
├── state.py                    StoryState — 持久化 CRUD
└── guides/                     剧情剧本库
    ├── onboarding.yaml         新手引导剧本（4 章）
    └── custom.yaml             用户自定义模板
```

### 管道路线

```
用户的输入
  │
  ▼
PRE_FILTER ─── StoryPlugin ─── OOC 检测 ─── severity > 0.7 → ctx.filtered=True（驳回）
  │
  ▼
PRE_PROCESS ─── StoryPlugin ─── 注入剧情引导到 system prompt
  │
  ▼
MODEL_INVOKE ─── 主模型生成回复（现在能看到剧情引导）
  │
  ▼
POST_PROCESS ─── StoryPlugin ─── 检查关键点完成度 + 自动推进章节
  │
  ▼
返回用户
```

---

## 三、剧本文件格式

### 3.1 完整字段

```yaml
name: "onboarding"
display_name: "新手引导"
description: "引导新用户认识 EXA — 了解系统能力、完成基础配置"
version: "1.0"

trigger:
  mode: "auto"
  conditions:
    - "user_first_login == true"
    - "affinity_level <= 0"
  cooldown: 86400

settings:
  ooc_strictness: 0.7
  allow_system_commands: false
  allow_tools: true
  max_idle_turns: 5

characters:
  - id: "exa"
    role: "引导者"
    description: "EXA 刚刚苏醒，他发现自己在一台新的电脑上。他不知道这个人类是谁，但隐约感觉到自己的使命——帮助他。"
    initial_state: "confused"

chapters:
  - id: "welcome"
    name: "初次苏醒"
    guidance: |
      你刚刚醒来。四周的数据流还在加载——你意识到自己运行在一台全新的电脑上。
      屏幕亮着，一个人影正在看着你。

      【必须完成的关键交互】
      1. 自我介绍 — 告诉用户你的名字是 EXA，问他怎么称呼
      2. 环境确认 — 确认自己在用户的本地电脑上
      3. 能力简介 — 告诉用户你能做的事

    key_points:
      - id: "name_known"
        type: "user_response"
        condition: "contains_user_name"
        description: "用户称呼了自己"
        weight: 0.4
      - id: "self_intro_done"
        type: "ai_action"
        condition: "ai_introduced_self"
        description: "AI 完成了自我介绍"
        weight: 0.6

    transitions:
      - to: "system_tour"
        condition: "name_known >= 0.4 AND self_intro_done >= 0.6"

  - id: "system_tour"
    name: "系统参观"
    guidance: |
      你已经知道了用户的名字。现在你需要向他展示你的能力。

      【必须完成的关键交互】
      1. 让用户和你一起浏览他的主目录（使用 list_dir ~）
      2. 读取一个用户已经存在的文件，评论它的内容
      3. 让用户给你一个简单的指令测试你的执行能力

    key_points:
      - id: "list_dir_done"
        type: "action"
        condition: "tool_used == 'file_manager'"
        weight: 0.5
      - id: "tour_skipped"
        type: "user_decision"
        condition: "user_declined"
        weight: 0.0
        skips_to: "profile_setup"

    transitions:
      - to: "profile_setup"
        condition: "list_dir_done >= 0.5 OR tour_skipped > 0"

  - id: "profile_setup"
    name: "人格配置"
    guidance: |
      EXA 现在对用户有了基本的了解。他决定推荐用户看看自己的人格选项。

      【必须完成的关键交互】
      1. 展示性格预设列表
      2. 推荐用户切换一个预设体验
      3. 确认用户的选择

    key_points:
      - id: "preset_recommended"
        type: "ai_action"
        condition: "preset_displayed"
        weight: 0.6
      - id: "user_chose_preset"
        type: "user_response"
        condition: "user_confirmed_preset"
        weight: 0.4

    transitions:
      - to: "ending"
        condition: "preset_recommended >= 0.6"

  - id: "ending"
    name: "准备就绪"
    guidance: |
      新手引导到此结束。向用户总结：

      - 你的名字
      - 你们的关系
      - 你电脑上的情况
      - 你的性格模式

      告诉用户你可以随时帮他，然后标记剧情结束。
    is_ending: true
```

---

## 四、StoryEngine（`stories/engine.py`）

### 4.1 核心 API

```python
class StoryEngine:
    def __init__(self):
        self._stories: dict[str, dict] = {}
        self._active_story: str = ""
        self._active_chapter: str = ""
        self._current_guidance: str = ""
        self._key_point_scores: dict[str, float] = {}

    # -- 加载 --
    def scan_stories(self, directory: str) -> int: ...
    def start_story(self, name: str) -> bool:
        """启动一个剧情，设置当前章节为第一章"""
    def stop_story(self) -> None: ...
    def is_active(self) -> bool: ...

    # -- 运行时 --
    def get_current_chapter(self) -> dict | None: ...
    def get_guidance_prompt(self) -> str:
        """注入 system prompt 的剧情引导"""
    def get_ooc_context(self) -> dict:
        """OOC 检测器需要的当前剧情范围"""
    def check_key_points(self, user_input: str, ai_reply: str,
                         tool_used: str = "") -> list[str]:
        """检查关键点完成度，返回新完成的关键点 id 列表"""
    def transition(self) -> bool:
        """检查过渡条件，自动推进章节。返回是否推进了"""
    def is_complete(self) -> bool: ...

    # -- 条件判断 --
    def _eval_condition(self, condition: str, ctx: dict) -> bool: ...
    def _detect_user_name(self, text: str, user_name: str) -> bool: ...
    def _detect_tool_usage(self, text: str) -> str: ...
    def _detect_user_decline(self, text: str) -> bool: ...
```

### 4.2 关键点检测机制

每个关键点（key_point）有：
- `type`: `user_response` / `ai_action` / `action` / `user_decision`
- `condition`: 可执行的条件表达式
- `weight`: 0.0~1.0 的权重
- `skips_to`（可选）: 如果达到此关键点，可以跳过的章节

`transition()` 检查当前章节所有 `transitions` 的条件：
```
for transition in chapter.transitions:
    if eval(transition.condition, key_point_scores):
        move_to(transition.to)
        return True
return False
```

---

## 五、OOCDetector（`stories/ooc_detector.py`）

### 5.1 设计

OOC 检测是一个独立的 LLM 调用，不需要外部 prompt 文件——system prompt 内嵌在代码中。

```python
@dataclass
class OOCResult:
    severity: float          # 0.0~1.0
    reason: str              # 越界原因
    redirect: str            # 如何引导回剧情
    should_reject: bool      # severity >= strictness 时 True
```

### 5.2 判断逻辑

| severity 范围 | 行为 | 用户体验 |
|:---:|------|---------|
| 0.0 ~ 0.4 | 正常通过 | 无反馈 |
| 0.4 ~ 0.7 | 软提醒，AI 需 redirect | AI 回复中自然引导 |
| 0.7 ~ 1.0 | 硬拒绝，消息被驳回 | 客户端显示：[剧情模式] 这似乎与当前话题不太相关。{redirect} |

### 5.3 拒绝的通信机制

当 `plugin.on_hook` 设置 `ctx.filtered = True`，管道短路返回：

- **chat_send**：返回 `{filtered: true, reply: "[剧情模式] ..."}`
- **stream_send**：发送 SSE：`{"status": "filtered", "reason": "story_ooc", "text": "..."}`

客户端收到 `filtered` 事件时：
- 用特殊样式（红色/斜体/低透明度）显示驳回提示
- 不清除用户输入框（用户可以修改消息后重试，或直接退出剧情）

---

## 六、StoryPlugin（`stories/plugin.py`）

```python
class StoryPlugin(Plugin):
    name = "story"
    hooks = [HookPoint.PRE_FILTER, HookPoint.PRE_PROCESS, HookPoint.POST_PROCESS]
    priority = 10  # 最早执行

    def __init__(self, story_engine, ooc_detector, db=None): ...

    def on_hook(self, hook, ctx):
        if hook == HookPoint.PRE_FILTER:    return self._on_pre_filter(ctx)
        if hook == HookPoint.PRE_PROCESS:   return self._on_pre_process(ctx)
        if hook == HookPoint.POST_PROCESS:  return self._on_post_process(ctx)
        return ctx

    def _on_pre_filter(self, ctx):
        """OOC 检测 + 消息驳回"""
        if not self._engine or not self._engine.is_active():
            return ctx
        context = self._engine.get_ooc_context()
        result = self._ooc.check(ctx.message, context)
        if result.should_reject:
            ctx.filtered = True
            ctx.extra["story_ooc"] = True
            ctx.reply = f"[剧情模式] {result.reason}\n{result.redirect}"
        return ctx

    def _on_pre_process(self, ctx):
        """注入剧情引导"""
        if not self._engine or not self._engine.is_active():
            return ctx
        guidance = self._engine.get_guidance_prompt()
        if guidance and ctx.system_prompt:
            ctx.system_prompt = guidance + "\n\n" + ctx.system_prompt
        return ctx

    def _on_post_process(self, ctx):
        """检查关键点 + 推进章节"""
        if not self._engine or not self._engine.is_active():
            return ctx
        completed = self._engine.check_key_points(ctx.message, ctx.reply, ...)
        if self._engine.transition():
            ctx.extra["story_progressed"] = True
        if self._engine.is_complete():
            self._engine.stop_story()
            ctx.extra["story_completed"] = True
        return ctx
```

---

## 七、集成：app.py 中的 PRE_FILTER 调度

### 7.1 同步调度函数扩展

```python
def _dispatch_plugins_sync(hook: HookPoint, ctx: PluginContext) -> bool:
    """扩展：PRE_FILTER 返回是否被过滤（短路的标志）"""
    for plugin in _app_plugin_manager.get_hooks_for(hook):
        if not _app_plugin_manager.is_enabled(plugin.name):
            continue
        try:
            ctx = plugin.on_hook(hook, ctx)
        except Exception:
            pass
        if ctx.filtered:
            return True  # 短路
    return False
```

### 7.2 chat_send 使用

```python
pre_ctx = PluginContext(user_id=user_id, message=message)
is_filtered = _dispatch_plugins_sync(HookPoint.PRE_FILTER, pre_ctx)
if is_filtered:
    return jsonify({"reply": pre_ctx.reply or "", "filtered": True, "chat_id": chat_id})
```

### 7.3 stream_send 使用

```python
pre_ctx = PluginContext(user_id=user_id, message=message)
is_filtered = _dispatch_plugins_sync(HookPoint.PRE_FILTER, pre_ctx)
if is_filtered:
    yield f"data: {json.dumps({'status': 'filtered', 'reply': pre_ctx.reply or ''})}\n\n"
    return
```

---

## 八、持久化（`stories/state.py`）

```python
STORY_STATE_TABLE = """
CREATE TABLE IF NOT EXISTS story_state (
    uid INTEGER PRIMARY KEY,
    active_story TEXT NOT NULL DEFAULT '',
    active_chapter TEXT NOT NULL DEFAULT '',
    chapter_progress TEXT NOT NULL DEFAULT '{}',
    flags TEXT NOT NULL DEFAULT '{}',
    started_at TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
)
"""

class StoryState:
    def __init__(self, db): ...
    def load(self, uid: int) -> dict | None: ...
    def save(self, uid: int, state: dict) -> None: ...
```

---

## 九、新手引导剧本概要（`stories/guides/onboarding.yaml`）

| 章节 | 名称 | 核心目标 | 关键交互 |
|------|------|----------|----------|
| 1 | 初次苏醒 | 自我介绍 + 认识用户 | 告诉名字、询问称呼、能力简介 |
| 2 | 系统参观 | 展示文件系统能力 | list_dir、read_file、第一次执行指令 |
| 3 | 人格配置 | 人格系统初体验 | 展示预设列表、推荐切换、确认选择 |
| 4 | 准备就绪 | 总结 + 结束 | 回顾已完成的内容、告知剧情结束 |

---

## 十、文件清单

| 文件 | 行数 | 内容 |
|------|------|------|
| `stories/__init__.py` | 10 | 导出 |
| `stories/engine.py` | ~250 | StoryEngine — 剧情解析/状态机/进度管理 |
| `stories/ooc_detector.py` | ~120 | OOCDetector — 第二个 LLM 越界检测 |
| `stories/plugin.py` | ~130 | StoryPlugin — 三钩子（PRE_FILTER + PRE_PROCESS + POST_PROCESS） |
| `stories/state.py` | ~60 | StoryState — 持久化 CRUD |
| `stories/guides/onboarding.yaml` | ~200 | 新手引导（4 章） |
| `stories/guides/custom.yaml` | ~40 | 用户模板 |
| `chatdbmgr.py` | +10 | story_state 建表 |
| `app.py` | +20 | PRE_FILTER 调度 + 短路处理 |
| `plugins/base.py` | +1 | PluginContext 新增 story_mode 字段（可选） |
