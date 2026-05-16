## DSN-exp

**EXA** — 基于 Flask 的插件化 AI 助手系统，支持语音交互、动态人格、可扩展技能和自动进化。

> **设计理念**：将 AI 助手的核心能力拆分为三个低耦合子系统——插件系统（运行时流水线）、Prompt 生态（动态提示词组装）、技能系统（可热加载的能力包）。每个子系统可独立开发、测试和替换，`app.py` 仅作为胶水层路由请求，不包含业务逻辑。

---

### 系统工作原理

#### 整体架构

```
用户层:  CLI (文字)  |  CLI (实时语音)  |  WebUI (SSE流式)
          ──────────────────┬───────────────────
                          HTTP API
                            │
              ┌─────────────▼─────────────┐
              │    app.py (Flask ~200行)    │  ← 纯胶水层: 路由 · 认证 · 构造上下文
              └────┬──────┬──────┬───────┘
                   │      │      │
        ┌──────────▼──┐ ┌─▼────────▼──┐ ┌▼───────────────┐
        │  usermgr    │ │ chatdbmgr   │ │   config.py    │
        │ OAuth2+JWT  │ │  SQLite     │ │   环境配置      │
        └─────────────┘ └─────────────┘ └────────────────┘

    三大独立子系统 (各自持有自己的状态，通过接口互操作):

    ┌──────────────────────────────────────────────────────────┐
    │                   插件系统 (plugins/)                      │
    │                                                          │
    │   PluginManager → Plugin[priority] → ChatPipeline         │
    │                                                          │
    │   PRE_FILTER → PRE_PROCESS → MODEL_INVOKE                │
    │                              → POST_PROCESS → POST_TTS   │
    └──────────┬───────────────────────────────────┬───────────┘
               │                                   │
    ┌──────────▼──────────┐           ┌────────────▼──────────┐
    │  Prompt 生态 (prompt/)│          │  技能系统 (skills/)    │
    │                      │          │                       │
    │  PromptEngine        │          │  SkillManager         │
    │  ├─ PromptLibrary    │◄─────────│  ├─ SkillRegistry ←──┤
    │  ├─ PersonalitySystem│ 技能提示词 │  │  (动态工具加载)     │
    │  └─ 用户上下文       │          │  ├─ DistillationEngine │
    └──────────────────────┘          │  │  (自动蒸馏)         │
                                      │  └─ SkillLoader       │
                                      └───────────────────────┘

    底层引擎 (被插件调用，不直接暴露给路由):
    models.py · memory.py · tasks.py · vocal_infer.py · ASR_filter.py
```

**关键设计决策**：认证（`usermgr.py`）和持久化（`chatdbmgr.py`）不进入插件系统。它们提供基础服务层，是插件系统的前置依赖而非参与者——所有插件默认运行在已通过认证的、已准备好数据库的用户上下文中。

---

#### 一、插件系统 — 五阶段对话管道

插件系统是对话处理的运行时核心。它不定义 AI 的能力，而是编排一次用户请求从输入到输出的完整生命周期。

```
PluginContext (贯穿整个管道的上下文载体)
    │
    ▼
ChatPipeline.process(ctx)
    │
    ├──① PRE_FILTER (priority=10)
    │     asr_filter_plugin: 用小模型判断语音输入质量
    │     → 若返回 HOLD 则短路，不消耗主模型 token
    │
    ├──② PRE_PROCESS (priority=30)
    │     memory_plugin: 从 SQLite 加载最近 N 轮对话
    │     → 将远端历史替换为已生成的记忆摘要
    │     → 注入当前用户上下文 (姓名/时间/性格/情绪)
    │
    ├─── [PromptEngine 在此处组装完整 system prompt] ───
    │     → 核心身份 + 输出格式 + 安全约束
    │     → 当前性格描述 (大五人格 + 情绪 + 亲密度)
    │     → 能力说明 (<task> / <tool> 标签使用规范)
    │     → 所有已启用技能的提示词
    │     → 用户自定义扩展
    │
    ├──③ MODEL_INVOKE (priority=50)
    │     models_plugin:
    │     → ComplexityAnalyzer 对用户输入打分 (0~1)
    │     → 低复杂度: DeepSeek chat (快/便宜)
    │     → 高复杂度: DeepSeek reasoner (慢/深入)
    │     → 或使用本地 LMStudio (完全离线)
    │     → 输出原始 AI 回复 (含 <tool>/<task>/<text> 标签)
    │
    ├──④ POST_PROCESS
    │     ├── skills_plugin (priority=35): 解析 <tool> 标签
    │     │     → 通过 SkillRegistry 调用 Python 工具
    │     │     → 将执行结果追加到回复
    │     ├── agent_plugin (priority=37): 多步代理循环
    │     │     → 执行 <tool> → 结果喂回 LLM → 继续直到无更多工具
    │     ├── task_plugin (priority=40): 解析 <task> 标签
    │     │     → 创建提醒/推理/动作任务，提交给 TaskManager
    │     ├── memory_plugin (priority=30): 保存本轮对话
    │     │     → 异步触发摘要生成 (ThreadPoolExecutor)
    │     └── distill_plugin (priority=100): 蒸馏触发器
    │           → 检查是否有足够的新对话数据
    │           → 满足条件时触发 DistillationEngine
    │
    └──⑤ POST_TTS (priority=60)
          tts_plugin: 剥离所有标签 → 纯文本 → GPT-SoVITS → base64 音频
```

**插件注册机制**：

- 所有插件继承 `Plugin` 基类，声明所在 `HookPoint` 和执行 `priority`
- `PluginManager.dispatch(hook, ctx)` 按 priority 升序逐一调用该 HookPoint 的所有已启用插件
- 任何插件可通过抛出 `PipelineHalt` 异常短路后续流程（例如 ASR 过滤器判定无关语音时）
- 用户自定义插件放入 `plugins/custom/`，与内置插件使用完全相同的接口

---

#### 二、Prompt 生态 — 动态人格与提示词组装

Prompt 生态解决的核心问题是：**如何让 AI 的人格可塑、提示词可组合、能力可声明**。

##### 2.1 PromptLibrary — 可组合的提示词库

所有提示词片段以 Markdown 文件形式存储，使用 YAML frontmatter 标注元数据：

```yaml
# prompt/prompts/core/identity.md
---
category: core
tags: [identity, base]
enabled: true
---
You are an AI system named EXA running in DSN-exp on the user's computer.
```

`PromptLibrary` 在启动时扫描所有 `.md` 文件，按 `category` 分组索引。运行时 `PromptEngine` 按固定顺序拼接：
1. **core** — 身份定义、输出格式（TTS 友好：短句、无 markdown、无 emoji）、安全约束
2. **capabilities** — 声明 AI 可通过 `<task>` 和 `<tool>` 标签触发的能力
3. **extensions** — 用户自定义片段（可热重载，无需重启服务）

核心/能力提示词在启动时预渲染；扩展提示词每次请求时动态读取，支持热重载。

##### 2.2 PersonalitySystem — 动态人格模型

人格系统是两层结构：

```
         静态层 (不随交互变化)              动态层 (随每次交互微调)
    ┌─────────────────────────┐    ┌─────────────────────────────┐
    │ 大五人格维度 (0.0 ~ 1.0) │    │ 情绪状态:                    │
    │ · 开放性 Openness       │    │ · energy   (精力)   → 衰减   │
    │ · 尽责性 Conscientiousness│   │ · positivity(积极性)→ 衰减   │
    │ · 外向性 Extraversion   │    │ · patience (耐心)  → 衰减    │
    │ · 宜人性 Agreeableness   │    │ · curiosity(好奇心)→ 衰减   │
    │ · 神经质 Neuroticism    │    │                             │
    └─────────────────────────┘    │ 关系亲密度 intimacy (0~1)     │
                                   │  → 随交互增长，不衰减        │
                                   └─────────────────────────────┘
```

**工作机制**：
- **静态层**：由性格预设 YAML 文件定义（default/tsundere/gentle/custom），运行时可通过 API 切换
- **动态情绪**：每次 `on_interaction()` 调用时，根据 AI 的回复内容微调情绪（例如长回复消耗 energy，被拒绝降低 positivity）
- **衰减回归**：后台定时调用 `decay()`，所有情绪以固定速率向基线值回归（模拟"情绪随时间平复"）
- **亲密度**：仅增长不衰减，模拟人际关系的单向积累特性
- **最终输出**：`PersonalitySystem` 将以上所有维度渲染为一段自然语言描述，注入 system prompt

##### 2.3 PromptEngine — 组装引擎

PromptEngine 是三个子系统在 prompt 层面的交汇点：
- 从 `PromptLibrary` 获取结构化提示词
- 从 `PersonalitySystem` 获取当前个性描述
- 从 `SkillRegistry` 获取所有已启用技能的提示词（让 AI 知道有哪些 `<tool>` 可用以及如何使用）

这种设计让"AI 知道自己能做什么"这件事与"AI 怎么执行"完全解耦——技能系统只负责执行，Prompt 生态只负责告知。

---

#### 三、技能系统 — 可热加载的能力扩展

技能系统解决的问题：**如何在不修改核心代码、不重启服务的情况下，为 AI 增加新能力**。

##### 3.1 技能定义与加载

每个技能是一个自包含的目录：

```
skills/builtin/web_search/
├── skill.yaml          # 元数据: 名称/描述/激活关键词/工具声明
├── prompts/
│   ├── instruction.md  # AI 使用说明 (注入 system prompt)
│   └── examples.md     # 使用示例 (few-shot 参考)
└── tools/
    └── search.py       # Python 工具实现
```

**skill.yaml 结构**：
- `name` / `description`：技能标识
- `activation_keywords`：触发关键词（用于 PromptEngine 在上下文相关时选择性注入提示词，减少 token 消耗）
- `tools`：工具声明列表，每个工具指定方法名、参数 schema、副作用标记、危险等级

**加载流程** (`SkillLoader`)：
1. 解析 `skill.yaml` 生成 `Skill` 数据实例
2. 读取 `prompts/` 下所有 `.md` 文件，按 frontmatter 的 `category` 分组
3. 若存在 `tools/`，动态 import Python 模块中的工具类
4. 将 `Skill` 实例注册到 `SkillRegistry`

##### 3.2 SkillRegistry — 运行时工具调度

```
SkillRegistry
├── _tools: Dict[str, Dict[str, Any]]     # skill_name -> {tool_name: tool_instance}
├── _tool_specs: Dict[str, Dict]          # skill_name -> {tool_name: ToolSpec}
├── _skill_prompts: Dict[str, List[str]]  # skill_name -> 提示词文本列表
│
├── register_skill(name, tools, prompts)   # 注册技能
├── unregister_skill(name)                # 卸载技能
├── call_tool(skill, tool, params)        # 执行工具 (阻塞)
├── get_all_skill_prompts()               # 聚合所有提示词 (供 PromptEngine)
└── get_skill_tools(skill)               # 获取某个技能的工具列表
```

**工具调用安全性**：
- 每个工具声明 `safe: true/false`，危险工具（如写文件）需要用户确认
- `file_manager` 技能内置路径白名单检查，禁止访问系统目录
- 工具执行超时机制，防止无限循环

##### 3.3 SkillManager — 生命周期管理

提供运行时的技能热管理：
- `enable_skill(name)` → 调用 `SkillRegistry.register_skill()`
- `disable_skill(name)` → 调用 `SkillRegistry.unregister_skill()`
- `install_skill(path)` → 从外部路径加载新技能
- 状态变更后立即反映在下一轮对话的 system prompt 中

##### 3.4 AgentPlugin — 多步代理循环

当 AI 回复包含 `<tool>` 标签时，`AgentPlugin` 可实现多步推理：

```
用户: "搜索最新的 GPT-5 新闻并总结"
  → AI 回复: <tool name="web_search" method="search">GPT-5 latest news 2026</tool>
  → AgentPlugin 执行搜索，获取结果
  → 结果喂回 AI，AI 生成总结
  → 检查回复中是否还有 <tool> 标签
  → 无更多工具 → 返回最终回复
```

支持配置最大迭代步数防止死循环。

---

#### 四、自动蒸馏 — 从对话中进化

蒸馏系统是 DSN-exp 的"自我进化"机制：从日常对话中挖掘可复用的行为模式，自动生成新的技能草案。

**完整流程** (`DistillationEngine`):

```
┌──────────────┐    ┌───────────────┐    ┌────────────────┐    ┌──────────┐
│ 1. 数据收集   │───▶│ 2. 模式挖掘    │───▶│ 3. 草案生成     │───▶│ 4. 审核   │
│              │    │               │    │                │    │          │
│ 从 SQLite    │    │ 用 LLM 分析   │    │ 用 LLM 生成   │    │ 人工      │
│ 获取近期对话  │    │ 发现重复性    │    │ skill.yaml +  │    │ approve/  │
│ (可配置阈值)  │    │ 用户需求模式  │    │ prompts +      │    │ reject    │
│              │    │               │    │ 工具代码草案   │    │          │
└──────────────┘    └───────────────┘    └────────────────┘    └────┬─────┘
                                                                    │
                                                              ┌─────▼─────┐
                                                              │ 5. 激活    │
                                                              │           │
                                                              │ 移至       │
                                                              │ distilled/ │
                                                              │ 自动加载   │
                                                              └───────────┘
```

**触发条件**：
- 定时任务（可配置周期）
- API 手动触发
- 对话中用户表达特定需求后自动触发（distill_plugin 检测条件）
- 新对话数超过阈值时触发

**安全机制**：
- 草案生成后必须经过人工审核才能生效（存储在 `_drafts/` 目录）
- 蒸馏仅分析已脱敏的对话摘要，不直接暴露原始对话给蒸馏 LLM
- 生成的工具代码需要安全审查标记

---

#### 五、任务系统 — 异步后台执行

`TaskManager` ( `tasks.py` ) 是一个完整的任务调度引擎，支持四种任务类型：

| 类型 | 触发方式 | 功能 |
|------|---------|------|
| **REMINDER** | ISO 8601 时间表达式 | 到时间后 AI 生成自然语言提醒，注入到指定聊天 |
| **REASONER** | 立即执行 | 将问题提交给 DeepSeek-Reasoner 深度推理，结果回注到当前聊天 |
| **ANALYSIS** | 立即执行 | 对指定内容进行分析（用户不在线时也可执行） |
| **ACTION** | 立即执行 | 执行 shell 命令、Python 代码片段、文件读写操作 |

**调度机制**：
- 使用 `schedule` 库实现定时任务轮询
- 所有任务持久化到 SQLite，重启不丢失
- 支持任务状态追踪（pending/running/completed/failed）
- 任务完成后生成系统消息注入聊天历史

**AI 如何创建任务**：通过回复中的 `<task>` 标签声明式创建：

```json
<task type="reminder">
{"time": "2026-05-17T09:00:00", "message": "提醒用户参加会议"}
</task>
```

---

#### 六、记忆系统 — 滑动窗口 + 摘要压缩

`MemoryManager` ( `memory.py` ) 解决 LLM 上下文窗口有限的问题：

```
完整历史:  [msg1] [msg2] [msg3] [msg4] [msg5] [msg6] [msg7] [msg8] ... [msg100]

上下文窗口有限 (如 8 轮)
              ┌────────────── 滑动窗口 ──────────────┐
              │                                       │
  [summary]   [msg93] [msg94] [msg95] [msg96] ... [msg100]
      ▲                                               ▲
      │                                               │
   远端消息被压缩为摘要                              最近消息保留原文
```

**摘要生成**：
- 每轮对话结束后，`MemoryPlugin` 异步触发摘要生成
- 使用专门的 `LMSummaryModel`（可配置为轻量模型以减少开销）
- 摘要以系统角色消息形式存储，在上下文组装时优先于原文注入
- 摘要可级联（多次摘要再聚合为更高层摘要），类似分层记忆

---

#### 七、语音子系统 — ASR + 过滤 + TTS

**语音输入流程**：

```
麦克风 (PvRecorder) → FunASR (Paraformer) → 文本 → LMFilterModel
                                                      │
                                          ┌───────────┴───────────┐
                                          │ 判断是否需要转发给 AI  │
                                          └───────────┬───────────┘
                                            FORWARD    │    HOLD
                                          进入对话管道  │  丢弃
```

`ASR_filter.py` 使用本地小模型（默认 llama-3.2-1b-instruct）做第一道过滤，避免环境噪音/无关对话被送入主模型，减少 token 浪费。

**语音输出流程**：

```
AI 回复文本 → TTSPlugin 剥离标签 → GPT-SoVITS (参考音频克隆) → WAV → base64
```

TTS 合成支持流式和非流式两种模式。

---

#### 八、客户端

三种客户端共用同一套后端 API：

- **`cli.py`** — 终端文字聊天。OAuth 登录获取 JWT，使用 pygame 播放 TTS 音频
- **`cli_interact.py`** — 实时语音交互。PvRecorder 持续拾音，支持按键说话（push-to-talk）和自动检测（VAD）两种模式
- **`webui.py`** — Web 界面。SSE 流式响应实时显示生成过程，支持 Markdown/MathJax 渲染、浏览器录音和 TTS 播放

---

### API 端点

**聊天 API**

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chat/send` | 发送消息，返回 AI 回复 + TTS 音频 (base64) |
| POST | `/api/chat/stream_send` | SSE 流式发送，推送各阶段状态与生成文本 |
| GET | `/api/chat/list` | 列出当前用户的所有聊天会话 |
| GET | `/api/chat/<chat_id>` | 获取指定聊天的完整消息历史 |
| POST | `/api/asr/recognize` | 服务端语音识别 (FunASR) |

**认证 API**

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/auth/start` | 返回 OAuth2 授权 URL，客户端跳转 |
| GET | `/api/auth/callback` | OAuth 回调，用授权码换取 JWT token |

**管理 API** (部分实现)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/personality/switch` | 切换性格预设 |
| GET | `/api/personality/status` | 查看当前性格/情绪/亲密度状态 |
| POST | `/api/skills/enable` | 启用指定技能 |
| POST | `/api/skills/disable` | 禁用指定技能 |
| POST | `/api/distill/trigger` | 手动触发蒸馏 |
| POST | `/api/distill/approve` | 审核通过蒸馏草案 |
| POST | `/api/distill/reject` | 驳回蒸馏草案 |

---

### 目录结构

```
DSN-exp/
├── app.py                       # Flask 入口，API 路由与认证中间件
├── config.py                    # 配置管理（从 .env 加载）
├── usermgr.py                   # 用户认证：OAuth2 + JWT
├── chatdbmgr.py                 # SQLite 持久化（用户/聊天/消息/记忆/任务）

├── models.py                    # LLM 客户端：DeepSeekChat / LMStudioChat / LMSummaryModel
├── memory.py                    # 记忆引擎：滑动窗口 + 摘要压缩
├── tasks.py                     # 任务引擎：提醒/推理/动作调度
├── vocal_infer.py               # TTS 客户端：GPT-SoVITS 语音合成
├── ASR_filter.py                # ASR 过滤器：小模型语音质量判断

├── plugins/                     # ★ 插件系统
│   ├── base.py                  # Plugin/AsyncPlugin 基类 · HookPoint 枚举 · PluginContext
│   ├── manager.py               # PluginManager：注册 · 优先级排序 · 调度
│   ├── pipeline.py              # ChatPipeline：五阶段管道编排
│   ├── builtin/                 # 内置插件
│   │   ├── models_plugin.py     # 统一模型调用 (Hook: MODEL_INVOKE)
│   │   ├── asr_filter_plugin.py # ASR 过滤 (Hook: PRE_FILTER)
│   │   ├── memory_plugin.py     # 记忆注入与保存 (Hook: PRE_PROCESS + POST_PROCESS)
│   │   ├── skills_plugin.py     # 技能工具执行 (Hook: POST_PROCESS)
│   │   ├── agent_plugin.py      # 多步代理循环 (Hook: POST_PROCESS)
│   │   ├── task_plugin.py       # 任务解析调度 (Hook: POST_PROCESS)
│   │   ├── tts_plugin.py        # TTS 合成 (Hook: POST_TTS)
│   │   ├── distill_plugin.py    # 蒸馏触发 (Hook: POST_PROCESS)
│   │   ├── todo_plugin.py       # Todo 计划创建
│   │   └── todo_store.py        # Todo 状态存储 (内存 + pub/sub)
│   └── custom/                  # 用户自定义插件

├── prompt/                      # ★ Prompt 生态
│   ├── engine.py                # PromptEngine：最终 system prompt 组装
│   ├── library.py               # PromptLibrary：MD 提示词库 (YAML frontmatter)
│   ├── personality.py           # PersonalitySystem：大五人格 + 情绪 + 亲密度
│   └── prompts/
│       ├── core/                # identity.md · format.md · safety.md
│       ├── capabilities/        # task_handling · code_execution · reminder · reasoner
│       ├── personality/         # default.yaml · tsundere.yaml · gentle.yaml · custom.yaml
│       └── extensions/          # 用户自定义扩展提示词

├── skills/                      # ★ 技能系统
│   ├── loader.py                # SkillLoader：从目录加载技能 (skill.yaml + prompts + tools)
│   ├── registry.py              # SkillRegistry：动态加载 · 工具调用 · 提示词聚合
│   ├── manager.py               # SkillManager：生命周期管理 (启用/禁用/安装)
│   ├── distill.py               # DistillationEngine：对话挖掘 → 草案生成 → 审核
│   ├── builtin/
│   │   ├── web_search/          # DuckDuckGo 搜索 (无需 API key)
│   │   └── file_manager/        # 文件读写/目录列表 (路径安全)
│   ├── distilled/
│   │   └── _drafts/             # 待审核技能草案
│   └── custom/                  # 用户自建技能

├── cli/                         # 客户端
│   ├── cli.py                   # 终端文字聊天
│   ├── cli_interact.py          # 实时语音交互
│   └── webui.py                 # Web 界面 (SSE · Markdown · 录音)

├── docs/                        # 设计文档
│   ├── architecture.md          # 完整系统架构
│   ├── guide-plugin-system.md   # 插件系统实现指导
│   ├── guide-prompt-ecosystem.md# Prompt 生态实现指导
│   ├── guide-skill-system.md    # 技能系统实现指导
│   ├── guide-distillation.md    # 自动蒸馏实现指导
│   └── guide-integration.md     # 系统集成与迁移路线图

└── tests/                       # 测试套件
    ├── test_plugin_loader.py    # 插件系统测试
    ├── test_prompt_ecosystem.py # Prompt 生态测试
    ├── test_skills_system.py    # 技能系统测试
    └── test_*.py                # 其他集成/单元测试
```

---

### 子系统交互关系

```
                    ┌──────────────┐
                    │   app.py     │
                    │  (胶水层)    │
                    └──┬───┬───┬──┘
                       │   │   │
         构造上下文     │   │   │ 调用
         并调用管道     │   │   │ PromptEngine
                       │   │   │
    ┌──────────────────▼───▼───▼──────────────────┐
    │              ChatPipeline                    │
    │                                              │
    │  PRE_PROCESS → [PromptEngine] → MODEL_INVOKE │
    │       │              ▲              │        │
    │       │              │              │        │
    │       │    ┌─────────┴─────────┐    │        │
    │       │    │   PromptEngine    │    │        │
    │       │    │                   │    │        │
    │       │    │ PromptLibrary     │    │        │
    │       │    │ PersonalitySystem │    │        │
    │       │    │ SkillRegistry ────┼────┼────────┤
    │       │    └───────────────────┘    │        │
    │       │                             │        │
    │       │  POST_PROCESS               │        │
    │       │    │                        │        │
    │       │    ├── skills_plugin ───────┼──► SkillRegistry.call_tool()
    │       │    ├── task_plugin ─────────┼──► TaskManager.create_task()
    │       │    ├── memory_plugin ───────┼──► chatdbmgr.save_message()
    │       │    └── distill_plugin ──────┼──► DistillationEngine.run()
    │       │                             │        │
    │       │  POST_TTS                   │        │
    │       │    └── tts_plugin ──────────┼──► VocalExp.synthesize()
    └──────────────────────────────────────┘
```

**关键交互说明**：

- **PromptEngine ↔ SkillRegistry**（系统级）：PromptEngine 在构建 system prompt 时查询 SkillRegistry 获取所有已启用技能的提示词，使 AI 知晓可用工具。这是两个独立子系统之间唯一的直接依赖。
- **SkillsPlugin ↔ SkillRegistry**（运行时）：AI 回复中的 `<tool>` 标签被解析后，SkillsPlugin 通过 SkillRegistry 查找并执行对应的 Python 工具。
- **TaskPlugin ↔ TaskManager**（运行时）：AI 回复中的 `<task>` 标签被解析后，TaskPlugin 调用 TaskManager 创建异步任务。
- **DistillPlugin ↔ DistillationEngine**（后台）：在每次对话后检查数据积累条件，触发蒸馏流程；蒸馏结果通过 SkillManager 写入技能系统。
