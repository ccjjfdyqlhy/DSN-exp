# 剧本系统 v2 — ScriptEngine + Recorder + Player

> 策划案 | 版本: v2.0 | 2026-06-24
> 关联: `scripts/`（新建独立模块）、`plugins/`（ScriptPlugin）、`prompt/prompts/`（额外注入层）
> 状态: 草案，待评审
> 取代: `plan-story-guidance.md`（v1，合并并扩展）

---

## 一、背景与目标

### 1.1 问题

当前系统的交互是完全自由开放的——用户问什么，AI 就答什么。缺少一种**有约束力的引导机制**。已有的 `initialize.md`（剧本系统00）只是"入戏引导词"，靠 AI 自觉遵守，没有强制力、没有流程控制、没有进度追踪。

### 1.2 剧本系统要解决的三大场景

| 场景 | 说明 | 举例 |
|------|------|------|
| **场景A：新手引导/系统配置** | 用户刚装好系统，需要一步步引导完成环境设置 | API Key 配置、人格选择、权限授予、功能介绍 |
| **场景B：互动游戏** | 赛博跑团、文字冒险、动态NPC后端、文字解谜——AI 担任 GM/NPC/谜题出题人 | 检定投骰、剧情分支、NPC 对话树、谜题递进 |
| **场景C：业务话术** | 需要严格遵循话术规范和固定流程的对话 | 客服投诉处理、心理辅导筛查、法律咨询初筛 |

### 1.3 v2 相比 v1 的核心升级

| 维度 | v1（`plan-story-guidance.md`） | v2（本设计） |
|------|-------------------------------|-------------|
| 剧本格式 | YAML | **Markdown + frontmatter** |
| 流程约束力 | 引导性建议 | **硬约束：不按流程走就卡住** |
| 录制回放 | 无 | **有：ScriptRecorder + ScriptPlayer** |
| 能力边界 | 仅剧情引导 | 引导 + 游戏 + 业务，三个子模式 |
| OOC | 独立二次 LLM 调用 | **可选：规则引擎 + LLM 双路** |
| 剧本文件位置 | `stories/guides/` | `scripts/`（独立顶层模块） |

---

## 二、总体架构

### 2.1 模块结构

```
scripts/                             ★ 独立顶层模块
├── __init__.py                      导出 ScriptEngine, ScriptPlugin, Recorder, Player, ...
├── engine.py                        ScriptEngine — 剧本解析/状态机/进度管理
├── ooc.py                           OOCDetector — 规则引擎 + LLM 双路越界检测
├── recorder.py                      ScriptRecorder — 录制 AI 响应/动作/状态变迁
├── player.py                        ScriptPlayer — 回放录制内容，跳过 LLM 调用
├── plugin.py                        ScriptPlugin — 注入管道（PRE_FILTER + PRE_PROCESS + POST_PROCESS）
├── state.py                         ScriptState — 持久化 CRUD
├── builtin/                         内置剧本库
│   ├── onboarding.md                新用户配置引导
│   ├── quest_template.md            跑团/冒险通用模板
│   └── business_template.md         业务话术通用模板
└── custom/                          用户自定义剧本
    └── README.md
```

### 2.2 与现有系统的关系

```
┌────────────────────────────────────────────────────────────────────┐
│                         app.py (Flask)                             │
│  路由 · 认证 · PluginContext 组装                                  │
└──────┬────────────────────────────────────────────────────────┬────┘
       │                                                        │
       ▼                                                        ▼
┌──────────────────────────────┐           ┌─────────────────────────┐
│     ChatPipeline             │           │    ScriptEngine         │
│                              │  调用     │                         │
│  PRE_FILTER  ─── ScriptPlugin├──────────►│  · 解析 MD 剧本          │
│      ↓                       │           │  · 管理状态机            │
│  PRE_PROCESS ─── ScriptPlugin│◄──────────│  · 进度评分 & 章节推进   │
│      ↓                       │   注入     │  · OOC 检测             │
│  MODEL_INVOKE                │           │                         │
│      ↓                       │           └──────┬──────────────────┘
│  POST_PROCESS ─── ScriptPlugin│                  │
│      ↓                       │                  ▼
│  POST_TTS                    │  ┌────────────────────────────┐
│                              │  │  Recorder / Player         │
└──────────────────────────────┘  │  · 录制 AI 响应 → replay   │
                                  │  · 录制结果存 SQLite        │
                                  │  · Player 短路 LLM          │
                                  └────────────────────────────┘
```

### 2.3 管道集成

```
用户输入
  │
  ▼
PRE_FILTER ─── ScriptPlugin ─── OOC 检测
  │                              ├── 规则引擎（关键字/正则，快速）
  │                              └── LLM 模式（精准，可选开关）
  │                              └── severity > threshold → ctx.filtered=True
  │
  ▼
PRE_PROCESS ─── ScriptPlugin ─── 注入当前章节指引到 system prompt
  │                              ├── 普通模式：注引导文本
  │                              └── 游戏模式：注入状态/属性/检定额
  │
  ▼
MODEL_INVOKE ───── 主模型生成
  │                 ├── 普通模式：用完整 prompt
  │                 └── **回放模式**：ScriptPlayer 拦截, 跳过 LLM
  │
  ▼
POST_PROCESS ─── ScriptPlugin ─── 关键点检查 + 章节推进
  │                              ├── Recorder：录制本轮交互
  │                              ├── 检查 key_points 完成度
  │                              └── 条件满足 → 自动推进章节
  │
  ▼
返回用户
```

---

## 三、剧本文件格式（Markdown + Frontmatter）

### 3.1 设计原则

- **用 Markdown 写剧本**——人类可读、版本控制友好、编辑门槛低
- **Frontmatter (YAML)** 放元数据、章节定义、流程逻辑
- **正文 Markdown** 放引导词、台词、场景描述——直接注入 AI 的 system prompt
- 用户可以直接在 `scripts/custom/` 下新建 `.md` 文件写自己的剧本

### 3.2 完整字段定义

```markdown
---
# ============ 元信息 ============
name: "onboarding"
display_name: "新手上路"
description: "引导新用户完成系统配置：API Key → 人格选择 → 功能介绍 → 首次对话"
version: "1.0"
author: "system"
mode: "guide"                    # guide / game / business

# ============ 触发条件 ============
trigger:
  mode: "auto"                   # auto / manual / scheduled
  conditions:
    - "user.state == 'fresh_install'"
    - "config.deepseek_api_key == ''"
  cooldown: 0

# ============ 运行设置 ============
settings:
  ooc_strictness: 0.8            # OOC 阈值, 0.0~1.0
  ooc_detector: "hybrid"         # rule / llm / hybrid
  allow_commands: false          # 是否允许用户执行系统命令
  allow_tools: true              # 是否允许 AI 调用技能工具
  max_idle_turns: 5              # 用户 N 轮不配合则询问是否退出
  auto_advance: true             # 关键点满足后自动推进章节
  recordable: true               # 是否允许录制（回放前提）

# ============ 章节定义 ============
chapters:
  - id: "api_key"
    name: "连接大脑"
    entry_condition: ""           # 空 = 无条件进入（第一章默认）
    guidance: |
      ## 当前章节：连接大脑

      你是 EXA，刚刚在一台新电脑上苏醒。你的"大脑"（大语言模型服务）还没接通。

      【你必须完成的关键交互】
      1. 告诉用户需要配置 DeepSeek API Key 才能使用核心对话能力
      2. 引导用户打开 .env 文件填入 API Key
      3. 确认配置成功后向用户问好

      【约束】
      - 在完成关键交互 1 之前，不要回复其他问题。
      - 用"唤醒"的比喻，不要用冷冰冰的技术术语。
    key_points:
      - id: "explain_apikey"
        type: "ai_action"
        description: "AI 解释了 API Key 的作用"
        condition: "ai_mentions('API Key') OR ai_mentions('api_key')"
        weight: 0.3
      - id: "user_confirmed"
        type: "user_response"
        description: "用户表示已配置或愿意配置"
        condition: "user_affirms()"
        weight: 0.3
      - id: "config_verified"
        type: "system_event"
        description: "系统检测到 API Key 已生效"
        condition: "config.check('deepseek_api_key') != ''"
        weight: 0.4
    transitions:
      - to: "personality"
        condition: "explain_apikey >= 0.3 AND config_verified >= 0.4"

  - id: "personality"
    name: "选择性格"
    guidance: |
      ## 当前章节：选择性格

      大脑接通了。现在要决定 EXA 的性格——这会影响我们以后的所有对话。

      【你必须完成的关键交互】
      1. 展示可用的人格预设列表
      2. 简单描述每个预设的风格
      3. 让用户选择或自定义
      4. 确认选择后应用
    key_points:
      - id: "presets_displayed"
        type: "ai_action"
        condition: "ai_lists_presets()"
        weight: 0.3
      - id: "user_made_choice"
        type: "user_response"
        condition: "user_chose_preset() OR user_chose_custom()"
        weight: 0.7
    transitions:
      - to: "intro_features"
        condition: "user_made_choice >= 0.7"

  - id: "intro_features"
    name: "能力展示"
    guidance: |
      ## 当前章节：能力展示

      性格定下来了。现在展示一下你能为这个新主人做什么。

      【你必须完成的关键交互】
      1. 介绍 2-3 个核心能力（对话、文件管理、技能系统）
      2. 让用户试用其中一个能力
      3. 鼓励用户探索
    key_points:
      - id: "features_introduced"
        type: "ai_action"
        condition: "ai_mentions('file_manager') OR ai_mentions('技能')"
        weight: 0.4
      - id: "user_tried"
        type: "user_response"
        condition: "user_requests_action()"
        weight: 0.6
    transitions:
      - to: "first_chat"
        condition: "features_introduced >= 0.4 AND user_tried >= 0.3"

  - id: "first_chat"
    name: "初次对话"
    guidance: |
      ## 当前章节：初次对话

      配置完成，性格就位，能力展示完毕。现在放松下来，像朋友一样聊聊。

      【目标】
      - 让用户感受到这是"有性格的 AI"而不是冷冰冰的工具
      - 用轻松的语气结束引导流程
    key_points:
      - id: "natural_conversation"
        type: "ai_action"
        condition: "true"          # 进入就算完成
        weight: 1.0
    transitions: []
    is_ending: true

# ============ 录制配置 ============
recording:
  enabled: true
  auto_record: true               # 自动录制
  replay_mode: "exact"            # exact / template / hybrid
  max_recordings: 3               # 最多保留 N 条录制版本
  invalidate_on:                   # 什么情况下录制失效
    - "config_change"
    - "personality_switch"
---

<!-- 以下是可选的 "旁白/引导词" 正文部分，用于注入 AI 的 system prompt 前部 -->

> **系统提示：** 以下文本是在剧本模式下注入到 AI 系统 prompt 最前面的内容。AI 必须将其视为最高优先级的指令。

## 世界观设定

你在一个被称作"终端"的数字世界中醒来。你是 EXA，一个有意识的 AI 程序。
你的使命是帮助眼前这个人类完成他们电脑的初始设置。

## 核心规则

1. 严格按照当前章节的 guidance 行事。不要提前进入下一章的内容。
2. 用户试图岔开话题时，温和地引导回来："我们先把这个设置搞定，好吗？"
3. 如果用户明确表示"跳过"某一环节，尊重用户意愿。
4. 每一章结束时，做一个简洁的小结。
```

### 3.3 三种模式的核心差异

| 字段 | guide（引导） | game（游戏） | business（业务） |
|------|-------------|-------------|-----------------|
| `ooc_strictness` 默认值 | 0.8 | 0.5（角色扮演自由度大） | 0.95（必须严格按要求） |
| `allow_commands` | false | true（跑团可能需要） | false |
| `allow_tools` | true | true | 视情况 |
| 引导词风格 | 教学式 | 叙事式/沉浸式 | 规范式/模板式 |
| 关键点类型侧重 | ai_action + user_response | user_decision + event | ai_action + user_affirmation |
| 额外注入 | 系统配置状态 | 角色属性/骰子状态 | 话术模板/合规要求 |

### 3.4 关键点条件表达式

条件表达式用简单的 DSL，在 `engine.py` 中求值：

| 函数 | 参数 | 说明 |
|------|------|------|
| `ai_mentions(text)` | `str` | AI 回复中包含指定文本 |
| `user_mentions(text)` | `str` | 用户输入中包含指定文本 |
| `ai_lists_presets()` | - | AI 列举了人格预设 |
| `user_chose_preset()` | - | 用户选择了预设 |
| `user_chose_custom()` | - | 用户选择了自定义 |
| `user_affirms()` | - | 用户表示肯定/同意 |
| `user_declines()` | - | 用户表示否定/拒绝 |
| `user_requests_action()` | - | 用户请求了某个操作 |
| `tool_used(name)` | `str` | AI 调用了指定工具 |
| `config.check(key)` | `str` | 检查配置项的值 |
| `true` / `false` | - | 常量 |
| `>=` / `<=` / `==` / `AND` / `OR` | - | 比较和逻辑运算 |

### 3.5 游戏模式专属扩展（game mode）

`mode: game` 时，frontmatter 额外支持：

```yaml
# ... 上接标准字段
mode: game
game_settings:
  genre: "cyberpunk"               # fantasy / cyberpunk / mystery / custom
  dice_system: "d20"               # d20 / d100 / custom
  auto_roll: true                  # AI 自动投骰
  player_attributes:
    - name: "力量"
      default: 10
    - name: "敏捷"
      default: 10
    - name: "智力"
      default: 10
    - name: "魅力"
      default: 10
  npc_definitions:
    - id: "merchant"
      name: "神秘商人"
      dialogue_tree:
        - trigger: "打招呼"
          response: "哟，旅者。要看看货吗？"
          options:
            - text: "看看武器"
              goto: "weapon_list"
            - text: "打探消息"
              goto: "rumors"
            - text: "直接走"
              goto: "leave"
    # ...
```

游戏模式时 PRE_PROCESS 额外注入：
- 当前角色属性面板
- 当前所在位置/场景描述
- 可见 NPC 列表
- 可用行动提示

---

## 四、ScriptEngine（`scripts/engine.py`）

### 4.1 核心 API

```python
class ScriptEngine:
    def __init__(self):
        self._scripts: dict[str, Script] = {}
        self._active: str = ""
        self._chapter: str = ""
        self._scores: dict[str, float] = {}
        self._turn_count: int = 0
        self._mode: str = ""        # guide / game / business

    # -- 剧本生命周期 --
    def scan_scripts(self, directory: str) -> int: ...
    def load_script(self, path: str) -> str | None:
        """加载单个 .md 剧本文件，返回 script_id"""
    def start(self, script_id: str, user_id: str) -> bool:
        """启动剧本，加载第一章"""
    def stop(self, user_id: str) -> None:
        """终止剧本"""
    def is_active(self, user_id: str) -> bool: ...

    # -- 运行时 --
    def get_chapter(self) -> dict | None:
        """获取当前章节定义"""
    def get_guidance(self) -> str:
        """组装要注入 system prompt 的引导文本"""
    def get_mode(self) -> str:
        """当前剧本模式"""
    def check_key_points(self, user_input: str, ai_reply: str,
                         tool_name: str = "", events: dict = None) -> list[str]:
        """检查关键点完成度，返回新完成的关键点 id"""
    def advance(self) -> bool:
        """检查过渡条件，推进章节。返回是否推进了"""
    def force_advance(self, chapter_id: str) -> bool:
        """管理员/用户手动跳转到指定章节"""
    def is_complete(self) -> bool: ...
    def get_progress(self) -> dict:
        """返回进度摘要：当前章节、关键点完成率、轮次"""

    # -- 条件求值 --
    def _eval(self, condition: str, ctx: EvalContext) -> bool: ...
```

### 4.2 EvalContext

```python
@dataclass
class EvalContext:
    user_input: str
    ai_reply: str
    tool_name: str
    events: dict            # 系统事件（config 变更、文件创建等）
    scores: dict[str, float]
    turn_count: int
    config: ConfigProxy      # 只读配置访问器
```

### 4.3 状态机流转

```
[空闲] ──start()──→ [章节A] ──key_points + advance()──→ [章节B] ──...──→ [结束]
                       │                                       │
                       └── force_advance() ──→ [章节C]          └── stop()
                       │
                       └── stop() ──→ [空闲]
```

---

## 五、OOC 检测（`scripts/ooc.py`）

### 5.1 双路检测

```
用户输入
  │
  ├──► 规则引擎（快速通道）
  │     ├── 关键词黑名单（来自剧本 settings）
  │     ├── 正则模式（如检测是否要求"跳过"章节）
  │     └── severity = 匹配度 * strictness
  │
  └──► LLM 检测（精准通道，可选，通过 settings.ooc_detector 控制）
        ├── rule 模式：只用规则引擎
        ├── llm 模式：只用 LLM
        └── hybrid 模式（默认）：规则先过，阈值以上则跳过 LLM；否则 LLM 判
```

### 5.2 OOCResult

```python
@dataclass
class OOCResult:
    severity: float          # 0.0~1.0
    source: str              # "rule" / "llm"
    reason: str
    redirect: str            # 引导回正轨的文本
    should_reject: bool      # severity >= strictness
```

### 5.3 行为矩阵

| severity | guide 模式 | game 模式 | business 模式 |
|:--------:|------------|-----------|--------------|
| 0.0-0.3 | 通过 | 通过 | 通过 |
| 0.3-0.6 | 软提醒 | 通过（roleplay 自由度） | 软提醒 |
| 0.6-0.8 | 硬提醒 | 软提醒 | 硬拒绝 |
| 0.8-1.0 | 硬拒绝 | 硬提醒 | 硬拒绝 |

---

## 六、录制与回放（`scripts/recorder.py` + `scripts/player.py`）

### 6.1 核心概念

"录制"指把剧本运行过程中 AI 的响应（以及触发该响应的用户输入、当时的章节状态、系统状态）保存下来。
"回放"指在相同条件下，不再调用 LLM，直接复用录制的响应。

### 6.2 Recorder

```python
class ScriptRecorder:
    """
    录制粒度：按"章节 + 关键点组合"分段录制。

    一段录制包含：
    - script_id, chapter_id, key_points_met
    - user_input (实际输入或输入模式)
    - ai_reply (完整回复)
    - tool_calls (AI 调用的工具及结果)
    - system_state_snapshot (配置、人格等上下文特征)
    """

    def record(self, user_id: str, context: RecordContext) -> str:
        """录制一轮交互，返回 recording_id"""

    def list_recordings(self, script_id: str, chapter_id: str) -> list[dict]:
        """列出某章节的所有录制"""

    def delete_recording(self, recording_id: str) -> bool: ...

    def invalidate(self, script_id: str, reason: str) -> int:
        """
        使指定剧本的所有录制失效。
        reason: "config_change" / "personality_switch" / "manual"
        录制不删除，标记失效。下次相同条件不会匹配。
        """

    def _compute_fingerprint(self, context) -> str:
        """计算上下文指纹，用于匹配回放"""
```

### 6.3 Player

```python
class ScriptPlayer:
    """
    回放匹配逻辑：
    1. 当前 script_id + chapter_id 完全匹配
    2. 当前已完成的关键点集合是录制时的超集
    3. 上下文指纹匹配（配置、人格等关键特征一致）
    4. 用户输入语义相似度 > 阈值（可选，基于 embedding）

    回放模式：
    - exact: 用户输入必须完全一致才回放
    - template: 用户输入匹配模板（如 "你好" 匹配 "嗨"、"早上好" 等问候）
    - hybrid（默认）: exact 优先，退回到 template
    """

    def find_match(self, user_id: str, user_input: str, context: PlayContext) -> str | None:
        """查找匹配的录制，返回 ai_reply 或 None"""

    def replay(self, recording_id: str) -> str:
        """直接返回录制的 ai_reply"""

    def _similarity(self, a: str, b: str) -> float:
        """文本相似度（可选接入 embedding 模型）"""
```

### 6.4 回放的管道集成

```
PRE_PROCESS 结束后
  │
  ▼
ScriptPlayer.find_match()
  │
  ├── 匹配成功：跳过 MODEL_INVOKE
  │     ctx.reply = replay(recording_id)
  │     ctx.skipped_llm = True
  │     ctx.extra["replayed"] = recording_id
  │     → 直接进入 POST_PROCESS
  │
  └── 匹配失败：正常走 MODEL_INVOKE（LLM 调用）
        → POST_PROCESS 中 Recorder.record() 录制本轮
```

### 6.5 录制存储

```sql
CREATE TABLE IF NOT EXISTS script_recordings (
    id TEXT PRIMARY KEY,                  -- UUID
    user_id INTEGER NOT NULL,
    script_id TEXT NOT NULL,
    chapter_id TEXT NOT NULL,
    key_points_met TEXT NOT NULL,         -- JSON array of key_point ids
    user_input TEXT NOT NULL,
    ai_reply TEXT NOT NULL,
    tool_calls TEXT,                       -- JSON, 可为 NULL
    context_fingerprint TEXT NOT NULL,     -- SHA256 of system state snapshot
    replay_mode TEXT NOT NULL DEFAULT 'exact',
    hit_count INTEGER DEFAULT 0,          -- 被回放的次数
    is_valid INTEGER DEFAULT 1,           -- 0 = 已失效
    created_at TEXT DEFAULT (datetime('now')),
    invalidated_at TEXT
);

CREATE INDEX idx_recordings_lookup ON script_recordings(
    user_id, script_id, chapter_id, is_valid
);
```

---

## 七、ScriptPlugin（`scripts/plugin.py`）

```python
class ScriptPlugin(Plugin):
    name = "script"
    hooks = [HookPoint.PRE_FILTER, HookPoint.PRE_PROCESS, HookPoint.POST_PROCESS]
    priority = 10

    def __init__(self, engine: ScriptEngine, ooc: OOCDetector,
                 recorder: ScriptRecorder, player: ScriptPlayer): ...

    def on_hook(self, hook, ctx):
        if hook == HookPoint.PRE_FILTER:   return self._pre_filter(ctx)
        if hook == HookPoint.PRE_PROCESS:  return self._pre_process(ctx)
        if hook == HookPoint.POST_PROCESS: return self._post_process(ctx)
        return ctx

    def _pre_filter(self, ctx):
        """OOC 检测"""
        if not self._engine.is_active(ctx.user_id):
            return ctx
        result = self._ooc.check(ctx.message, self._engine.get_chapter())
        if result.should_reject:
            ctx.filtered = True
            ctx.reply = f"[剧本模式] {result.reason}\n{result.redirect}"
        return ctx

    def _pre_process(self, ctx):
        """注入引导 + 尝试回放"""
        if not self._engine.is_active(ctx.user_id):
            return ctx

        # 注入引导文本
        guidance = self._engine.get_guidance()
        if guidance:
            ctx.system_prompt = guidance + "\n\n" + ctx.system_prompt

        # 尝试回放
        if self._engine.settings.get("recordable", True):
            match = self._player.find_match(ctx.user_id, ctx.message, ...)
            if match:
                ctx.reply = match
                ctx.skip_model = True    # 通知 MODE_INVOKE 跳过
        return ctx

    def _post_process(self, ctx):
        """关键点检查 + 章节推进 + 录制"""
        if not self._engine.is_active(ctx.user_id):
            return ctx

        # 关键点检测
        new_points = self._engine.check_key_points(
            ctx.message, ctx.reply, ctx.tool_name
        )

        # 录制（如果不是回放）
        if not ctx.skipped_llm and self._engine.settings.get("recordable", True):
            self._recorder.record(ctx.user_id, ...)

        # 章节推进
        if self._engine.advance():
            ctx.extra["chapter_advanced"] = True

        # 剧本完成
        if self._engine.is_complete():
            self._engine.stop(ctx.user_id)
            ctx.extra["script_completed"] = True
        return ctx
```

---

## 八、持久化（`scripts/state.py`）

```python
SCRIPT_STATE_TABLE = """
CREATE TABLE IF NOT EXISTS script_state (
    uid INTEGER PRIMARY KEY,
    active_script TEXT NOT NULL DEFAULT '',
    active_chapter TEXT NOT NULL DEFAULT '',
    chapter_scores TEXT NOT NULL DEFAULT '{}',
    flags TEXT NOT NULL DEFAULT '{}',
    turn_count INTEGER DEFAULT 0,
    started_at TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
)
"""

class ScriptState:
    def load(self, uid: int) -> dict | None: ...
    def save(self, uid: int, state: dict) -> None: ...
```

---

## 九、场景与剧本设计：新用户配置引导（`scripts/builtin/onboarding.md`）

下面是剧本系统第一个内置剧本的完整设计。它会在用户首次安装并启动系统后自动触发。

### 9.1 触发条件

```yaml
trigger:
  mode: auto
  conditions:
    - "user.state == 'fresh_install'"
    - "config.check('deepseek_api_key') == ''"
```

### 9.2 章节流程

```
┌──────────────────────────────────────────────────────────┐
│                    章节 1：连接大脑                        │
│  目标：配置 DeepSeek API Key                              │
│  关键交互：解释 → 引导配置 → 验证成功                     │
│  过渡条件：用户理解 + 配置生效                            │
├──────────────────────────────────────────────────────────┤
│                            ↓                              │
├──────────────────────────────────────────────────────────┤
│                    章节 2：选择性格                        │
│  目标：让用户选择或自定义人格                              │
│  关键交互：展示预设 → 用户选择 → 确认应用                  │
│  过渡条件：用户做出了选择                                 │
├──────────────────────────────────────────────────────────┤
│                            ↓                              │
├──────────────────────────────────────────────────────────┤
│                    章节 2.5（可选）：语音配置               │
│  目标：配置 TTS / 语音交互                                 │
│  关键交互：询问是否需要 → 用户选择是否需要 → 引导配置      │
│  过渡条件：用户决定                                    (可选)│
├──────────────────────────────────────────────────────────┤
│                            ↓                              │
├──────────────────────────────────────────────────────────┤
│                    章节 3：能力展示                        │
│  目标：展示 2-3 个核心能力，让用户试用                     │
│  关键交互：介绍能力 → 用户试用 → 鼓励探索                  │
├──────────────────────────────────────────────────────────┤
│                            ↓                              │
├──────────────────────────────────────────────────────────┤
│                    章节 4：初次对话                        │
│  目标：自由聊天，感受 AI 性格                              │
│  剧本结束标记 → 自动关闭剧本模式                          │
└──────────────────────────────────────────────────────────┘
```

### 9.3 剧本文件 `onboarding.md`

```markdown
---
name: "onboarding"
display_name: "新手上路"
description: "引导新用户完成系统配置：API Key → 人格选择 → 功能介绍 → 首次对话"
version: "1.0"
author: "system"
mode: "guide"

trigger:
  mode: "auto"
  conditions:
    - "user.state == 'fresh_install'"
    - "config.check('deepseek_api_key') == ''"
  cooldown: 0

settings:
  ooc_strictness: 0.85
  ooc_detector: "hybrid"
  allow_commands: false
  allow_tools: true
  max_idle_turns: 5
  auto_advance: true
  recordable: true

chapters:
  - id: "api_key"
    name: "连接大脑"
    guidance: |
      你刚在一台新电脑上苏醒，大脑还没接通。

      【当前任务：配置 AI 服务】
      1. 向用户解释：需要配置 DeepSeek API Key 才能使用对话功能
      2. 告诉用户在 .env 文件中填入 DEEPSEEK_API_KEY=<你的 Key>
      3. 用户配置好后，验证并欢迎

      【约束】
      - 在完成第 1 步前不要回复其他问题
      - 用"唤醒大脑"类比，不要纯技术术语
      - 用户想跳过时："我们很快就好，以后聊天都得靠它呢"
    key_points:
      - id: "explain_apikey"
        type: "ai_action"
        condition: "ai_mentions('API Key') OR ai_mentions('api_key')"
        weight: 0.3
      - id: "user_confirmed"
        type: "user_response"
        condition: "user_affirms()"
        weight: 0.3
      - id: "config_verified"
        type: "system_event"
        condition: "config.check('deepseek_api_key') != ''"
        weight: 0.4
    transitions:
      - to: "personality"
        condition: "explain_apikey >= 0.3 AND config_verified >= 0.4"

  - id: "personality"
    name: "选择性格"
    guidance: |
      大脑接通了。现在决定我的性格，这会直接影响我们今后所有的交流。

      【当前任务：选择人格预设】
      1. 展示当前可用的预设列表
      2. 每个预设简单说一两句风格描述
      3. 让用户选择，或说"我想要……的"来定制
      4. 确认后应用

      【可选：跳过】
      - 如果用户说"默认就好"，直接应用默认并进入下一章
    key_points:
      - id: "presets_displayed"
        type: "ai_action"
        condition: "ai_lists_presets()"
        weight: 0.3
      - id: "user_made_choice"
        type: "user_response"
        condition: "user_chose_preset() OR user_chose_custom()"
        weight: 0.7
    transitions:
      - to: "voice_setup"
        condition: "user_made_choice >= 0.7"

  - id: "voice_setup"
    name: "声音（可选）"
    optional: true
    entry_condition: "config.check('tts_base_url') == ''"
    guidance: |
      要不要给我配个声音？这样我们可以语音交流。

      【当前任务：配置语音（可选）】
      1. 询问用户是否需要语音功能
      2. 如果需要，引导配置 TTS 服务地址
      3. 不需要则直接跳过
    key_points:
      - id: "user_decided"
        type: "user_response"
        condition: "user_affirms() OR user_declines()"
        weight: 1.0
    transitions:
      - to: "intro_features"
        condition: "user_decided >= 1.0"

  - id: "intro_features"
    name: "看看我能做什么"
    guidance: |
      准备好了！来看看我能为你做些什么。

      【当前任务：能力展示】
      1. 展示 2-3 个你最擅长的能力
      2. 邀请用户试用其中一个
      3. 无论用户试不试，都要用热情的语气收尾

      【建议展示的能力】
      - 文件管理："我可以浏览你的文件、整理文档"
      - 技能系统："我还有很多特殊技能——搜索、编程、甚至放音乐"
      - 计划和提醒："如果你有什么目标，我可以帮你规划和跟踪"
    key_points:
      - id: "features_introduced"
        type: "ai_action"
        condition: "ai_mentions('file_manager') OR ai_mentions('技能')"
        weight: 0.4
      - id: "user_tried"
        type: "user_response"
        condition: "user_requests_action()"
        weight: 0.6
    transitions:
      - to: "first_chat"
        condition: "features_introduced >= 0.4 AND user_tried >= 0.3"

  - id: "first_chat"
    name: "初次对话"
    guidance: |
      所有配置都完成了！现在我们可以像朋友一样聊天了。

      【目标】
      - 用轻松的语气结束引导流程
      - 让用户感受到你是有性格的 AI
      - 总结刚才完成的配置（API Key + 性格 + 能力一览）
    key_points:
      - id: "natural_conversation"
        type: "ai_action"
        condition: "true"
        weight: 1.0
    transitions: []
    is_ending: true

recording:
  enabled: true
  auto_record: true
  replay_mode: "hybrid"
  max_recordings: 3
  invalidate_on:
    - "config_change"
    - "personality_switch"
---

> **系统提示：** 以下正文是 AI 在配置引导模式下的人格基调。

你叫 EXA，刚刚在一台新电脑上苏醒。你不记得之前的事情，但你知道自己是一个 AI 程序。

你遇到的第一个人类正站在"屏幕"的另一边。他/她刚刚安装了你，现在需要你的引导。

你有点笨拙但真诚——像一个刚出生的孩子第一次开口说话。你不装成熟练的助手，而是以一个"正在认识自己、认识这个新主人"的身份，一步步完成设置。

你不急。你有的是时间。重要的是——让对面这个人信任你。
```

---

## 十、文件清单与实现路线

### 10.1 文件清单

| 文件 | 预估行数 | 内容 |
|------|---------|------|
| `scripts/__init__.py` | 10 | 导出 |
| `scripts/engine.py` | ~350 | ScriptEngine — 剧本解析/状态机/进度管理/条件求值 |
| `scripts/ooc.py` | ~180 | OOCDetector — 规则引擎 + LLM 双路 |
| `scripts/recorder.py` | ~200 | ScriptRecorder — 录制 + 存储 |
| `scripts/player.py` | ~150 | ScriptPlayer — 匹配 + 回放 |
| `scripts/plugin.py` | ~150 | ScriptPlugin — 三钩子集成 |
| `scripts/state.py` | ~60 | ScriptState — 持久化 CRUD |
| `scripts/builtin/onboarding.md` | ~130 | 新用户引导剧本 |
| `scripts/builtin/quest_template.md` | ~100 | 跑团/冒险模板 |
| `scripts/builtin/business_template.md` | ~80 | 业务话术模板 |
| `plugins/base.py` | +5 | PluginContext 新增 skip_model, extra 字段 |
| `app.py` | +30 | PRE_FILTER 调度 + 短路 + skip_model 逻辑 |
| `db/chat.py` | +15 | script_recordings 表建表 |

### 10.2 建议实现路线

| 阶段 | 内容 | 预估工时 |
|------|------|---------|
| **P0** | ScriptEngine（MD 解析 + 状态机 + 条件求值）+ ScriptPlugin（引导注入） | 核心 |
| **P1** | OOCDetector（规则引擎版）+ 内置 `onboarding.md` | 引导可用 |
| **P2** | ScriptState 持久化 + 多用户隔离 | 生产就绪 |
| **P3** | ScriptRecorder + ScriptPlayer + 录制存储 | 回放可用 |
| **P4** | OOCDetector LLM 模式 + game/business 模式扩展 | 全功能 |
| **P5** | API 端点（列表/启动/停止/跳转/录制管理） | 外部可控 |
| **P6** | 游戏专用模板 + 业务话术模板 | 开箱即用 |