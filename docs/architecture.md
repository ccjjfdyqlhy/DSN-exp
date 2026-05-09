# DSN-exp 完整系统架构

> 版本: v4.0 | 2026-05-03
> 核心理念: 插件化运行时 + 可塑性格 + 自进化技能

---

## 一、系统全景

```
┌─────────────────────────────────────────────────────────────────────┐
│                           用户层                                    │
│  ┌──────────┐  ┌──────────────┐  ┌──────────────┐                 │
│  │  cli.py  │  │ cli_interact │  │   webui.py   │                 │
│  │  文字CLI │  │  实时语音交互  │  │   Web 界面   │                 │
│  └────┬─────┘  └──────┬───────┘  └──────┬───────┘                 │
│       └────────────────┼─────────────────┘                         │
│                        │ HTTP API                                   │
├────────────────────────┼───────────────────────────────────────────┤
│                        ▼                                            │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                      app.py (Flask)                         │   │
│  │  路由注册 · 认证中间件 · API 端点 · 生命周期管理              │   │
│  │  (~200 行，只做胶水，不含业务逻辑)                            │   │
│  └─────────────────────────────────────────────────────────────┘   │
│       │              │              │              │                │
│       ▼              ▼              ▼              ▼                │
│  ┌─────────┐  ┌───────────┐  ┌──────────┐  ┌──────────────┐      │
│  │ usermgr │  │chatdbmgr  │  │  config  │  │   ASR 服务    │      │
│  │(OAuth2) │  │ (SQLite)  │  │ (分组配置)│  │ (FunASR)     │      │
│  └─────────┘  └───────────┘  └──────────┘  └──────────────┘      │
│                                                                     │
│  ════════════════════ 三大独立子系统 ════════════════════          │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────┐     │
│  │                  插件系统 (plugins/)                       │     │
│  │                                                           │     │
│  │  ChatPipeline 编排管道:                                    │     │
│  │  ┌──────────┐ ┌───────────┐ ┌────────────┐ ┌───────────┐ │     │
│  │  │PRE_FILTER│→│PRE_PROCESS│→│MODEL_INVOKE│→│POST_PROCESS│ │     │
│  │  │(ASR过滤) │ │(记忆注入)  │ │(模型调用)   │ │(任务解析)  │ │     │
│  │  └──────────┘ └───────────┘ └────────────┘ └─────┬─────┘ │     │
│  │                                                  │       │     │
│  │                                              ┌───▼─────┐ │     │
│  │                                              │POST_TTS │ │     │
│  │                                              │(语音合成)│ │     │
│  │                                              └─────────┘ │     │
│  │                                                           │     │
│  │  内置插件: models · asr_filter · memory · task · tts     │     │
│  │  自定义插件: plugins/custom/*.py                          │     │
│  └───────────────────────────────────────────────────────────┘     │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────┐     │
│  │              Prompt 生态 (prompt/)                         │     │
│  │                                                           │     │
│  │  PromptEngine ─── 组装最终 system prompt                   │     │
│  │       │                                                   │     │
│  │       ├── PromptLibrary ─── MD 文件提示词库                │     │
│  │       │     ├── core/        (身份·格式·安全)              │     │
│  │       │     ├── capabilities/(任务·代码·推理)              │     │
│  │       │     └── extensions/  (用户自建)                    │     │
│  │       │                                                   │     │
│  │       ├── PersonalitySystem ─── 性格系统                   │     │
│  │       │     ├── 大五人格维度                               │     │
│  │       │     ├── 情绪状态 (动态波动)                        │     │
│  │       │     ├── 关系亲密度 (随交互增长)                    │     │
│  │       │     └── 性格预设 (YAML, 可切换)                   │     │
│  │       │                                                   │     │
│  │       └── SkillRegistry ─── 技能注册表                     │     │
│  │             (将已加载技能的提示词注入 system prompt)        │     │
│  └───────────────────────────────────────────────────────────┘     │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────┐     │
│  │              技能系统 (skills/)                            │     │
│  │                                                           │     │
│  │  SkillManager ─── 技能生命周期管理                         │     │
│  │       │                                                   │     │
│  │       ├── 加载/卸载/切换技能                               │     │
│  │       ├── 技能工具注册 (Python 代码)                       │     │
│  │       └── 技能提示词注入 (MD 文件)                         │     │
│  │                                                           │     │
│  │  DistillationEngine ─── 自动蒸馏系统                       │     │
│  │       │                                                   │     │
│  │       ├── 对话模式挖掘                                     │     │
│  │       ├── 技能草案生成 (MD + 工具代码)                     │     │
│  │       ├── 人工审核 → 激活                                  │     │
│  │       └── 技能迭代优化                                     │     │
│  └───────────────────────────────────────────────────────────┘     │
│                                                                     │
│  ════════════════════ 底层模块 (保留) ════════════════════        │
│                                                                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐  │
│  │ models.py│ │ memory.py│ │ tasks.py │ │vocal_infer│ │ASR_filter│  │
│  │(LLM客户端)│ │(记忆引擎)│ │(任务引擎)│ │(TTS客户端)│ │(过滤引擎)│  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └─────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 二、目录结构

```
DSN-exp/
├── app.py                          # Flask 入口 (~200 行)
├── config.py                       # 分组配置
├── usermgr.py                      # 用户认证 (独立，不进插件)
├── chatdbmgr.py                    # 数据库管理 (独立)
│
├── models.py                       # 底层 LLM 客户端 (被 models_plugin 调用)
├── memory.py                       # 底层记忆引擎 (被 memory_plugin 调用)
├── tasks.py                        # 底层任务引擎 (被 task_plugin 调用)
├── vocal_infer.py                  # 底层 TTS 客户端 (被 tts_plugin 调用)
├── ASR_filter.py                   # 底层过滤引擎 (被 asr_filter_plugin 调用)
│
├── prompt/                         # ★ Prompt 生态 (独立子系统)
│   ├── __init__.py
│   ├── engine.py                   # PromptEngine — 组装最终 system prompt
│   ├── personality.py              # PersonalitySystem — 性格系统
│   ├── library.py                  # PromptLibrary — MD 文件提示词库
│   └── prompts/                    # 提示词文件目录
│       ├── core/
│       │   ├── identity.md         # 基础身份
│       │   ├── format.md           # 输出格式 (TTS 友好)
│       │   └── safety.md           # 安全约束
│       ├── capabilities/
│       │   ├── task_handling.md    # 任务处理能力
│       │   ├── code_execution.md   # 代码执行能力
│       │   ├── reminder.md         # 提醒能力
│       │   └── reasoner.md         # 推理能力
│       ├── personality/
│       │   ├── default.yaml        # 默认性格
│       │   ├── tsundere.yaml       # 傲娇
│       │   ├── gentle.yaml         # 温柔
│       │   └── custom.yaml         # 用户自定义模板
│       └── extensions/             # 用户自建提示词
│           └── README.md           # 编写指南
│
├── skills/                         # ★ 技能系统
│   ├── __init__.py
│   ├── manager.py                  # SkillManager — 技能生命周期
│   ├── registry.py                 # SkillRegistry — 技能注册与工具管理
│   ├── distill.py                  # DistillationEngine — 自动蒸馏
│   ├── loader.py                   # SkillLoader — 技能加载器
│   │
│   ├── builtin/                    # 内置技能
│   │   ├── file_manager/
│   │   │   ├── skill.yaml
│   │   │   └── prompts/
│   │   │       ├── instruction.md
│   │   │       └── examples.md
│   │   └── web_search/
│   │       ├── skill.yaml
│   │       ├── prompts/
│   │       │   ├── instruction.md
│   │       │   └── examples.md
│   │       └── tools/
│   │           └── search.py
│   │
│   ├── distilled/                  # 蒸馏生成的技能 (需审核)
│   │   └── _drafts/                # 待审核草案
│   │       └── ...
│   │
│   └── custom/                     # 用户自建技能
│       └── README.md               # 技能编写指南
│
├── plugins/                        # ★ 插件系统
│   ├── __init__.py
│   ├── base.py                     # Plugin 基类 + HookPoint + PluginContext
│   ├── manager.py                  # PluginManager
│   ├── pipeline.py                 # ChatPipeline
│   ├── builtin/
│   │   ├── __init__.py
│   │   ├── models_plugin.py        # ★ 统一模型插件
│   │   ├── asr_filter_plugin.py
│   │   ├── memory_plugin.py
│   │   ├── task_plugin.py
│   │   └── tts_plugin.py
│   └── custom/                     # 用户自定义插件
│       └── README.md
│
├── cli/                            # 客户端
│   ├── cli.py
│   ├── cli_interact.py
│   └── webui.py
│
└── docs/                           # 文档
    └── architecture.md
```

---

## 三、三大子系统关系

```
                    ┌──────────────┐
                    │   app.py     │
                    │  (路由·胶水)  │
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────────┐
        │ 插件系统  │ │Prompt生态 │ │   技能系统    │
        │(运行时)  │ │(人格+提示)│ │(能力+蒸馏)   │
        └────┬─────┘ └────┬─────┘ └──────┬───────┘
             │            │              │
             │     ┌──────┴──────┐       │
             │     │PromptEngine │◄──────┘
             │     │ 组装prompt  │  技能的MD提示词
             │     └──────┬──────┘  通过SkillRegistry
             │            │         注入PromptEngine
             │            ▼
             │     最终 system prompt
             │            │
             ▼            ▼
        ┌────────────────────────┐
        │    ChatPipeline        │
        │  PRE_FILTER            │
        │  → PRE_PROCESS         │  ← 注入 system prompt
        │  → MODEL_INVOKE        │  ← 模型调用
        │  → POST_PROCESS        │  ← 任务解析 (含技能工具调用)
        │  → POST_TTS            │
        └────────────────────────┘
```

**关键交互点：**

| 交互 | 方向 | 说明 |
|------|------|------|
| PromptEngine → SkillRegistry | 查询 | 获取已加载技能的提示词，注入 system prompt |
| SkillManager → SkillRegistry | 注册/注销 | 加载技能时注册其工具和提示词 |
| DistillationEngine → SkillManager | 创建草案 | 蒸馏完成后创建待审核技能 |
| ChatPipeline → PromptEngine | 调用 | 每次对话前构建 system prompt |
| task_plugin → SkillRegistry | 查询 | 解析 AI 回复中的技能工具调用 |

---

## 四、插件系统

### 4.1 设计边界

| 模块 | 归属 | 理由 |
|------|------|------|
| 用户管理 `usermgr.py` | **独立模块** | 认证是基础设施 |
| Prompt 生态 `prompt/` | **独立子系统** | AI 人格核心，独立演进 |
| 技能系统 `skills/` | **独立子系统** | 能力扩展核心，与 Prompt 生态深度耦合 |
| 模型调用 | **一个大插件** | DeepSeek / LMStudio / Summary 统一管理 |
| ASR / 记忆 / 任务 / TTS | **各一个插件** | 可选功能，可热插拔 |

### 4.2 管道流程

```
用户消息
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│ PRE_FILTER                                              │
│ ┌─────────────────┐                                     │
│ │ asr_filter_plugin│  ASR 语音输入过滤                   │
│ └─────────────────┘                                     │
│ → 被过滤则短路返回                                       │
└──────────────────────┬──────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────┐
│ PRE_PROCESS                                            │
│ ┌─────────────────┐                                     │
│ │ memory_plugin   │  加载历史消息，注入记忆摘要           │
│ └─────────────────┘                                     │
└──────────────────────┬──────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────┐
│ PromptEngine.build_system_prompt(user_info)             │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐ │
│  │ core/    │→│性格描述   │→│capabilities│→│已加载技能 │ │
│  │ 提示词   │  │(动态生成) │  │ 提示词    │  │ 提示词   │ │
│  └──────────┘  └──────────┘  └──────────┘  └─────────┘ │
│       + extensions/ 提示词 + 用户上下文                   │
└──────────────────────┬──────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────┐
│ MODEL_INVOKE (models_plugin 独占)                       │
│                                                         │
│  复杂度分析 → 选择模型 → 调用 LLM → 获取回复             │
└──────────────────────┬──────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────┐
│ POST_PROCESS                                           │
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

### 4.3 统一模型插件 (models_plugin)

```python
# plugins/builtin/models_plugin.py

class ModelsPlugin(Plugin):
    """
    统一管理所有 LLM 后端。

    职责:
    - DeepSeek Chat / Reasoner 客户端
    - LMStudio Chat 客户端
    - LMStudio Summary 客户端 (记忆摘要)
    - ComplexityAnalyzer 复杂度分析
    - 自动模型选择
    - 流式调用支持
    """

    name = "models"
    hooks = [MODEL_INVOKE]
    priority = 50

    # 内部持有:
    #   _deepseek: DeepSeekChat
    #   _lmstudio: LMStudioChat
    #   _summary: LMSummaryModel
    #   _complexity: ComplexityAnalyzer
```

### 4.4 内置插件一览

| 插件 | 钩子 | 职责 |
|------|------|------|
| `models_plugin` | MODEL_INVOKE | 统一模型管理、复杂度分析、模型选择 |
| `asr_filter_plugin` | PRE_FILTER | ASR 语音输入过滤 |
| `memory_plugin` | PRE_PROCESS, POST_PROCESS | 记忆注入、对话保存、摘要生成 |
| `task_plugin` | POST_PROCESS | 任务解析、技能工具调用分发 |
| `tts_plugin` | POST_TTS | TTS 语音合成 |

---

## 五、Prompt 生态

### 5.1 三层架构

```
┌─────────────────────────────────────────────────────────┐
│                    PromptEngine                          │
│              (组装最终 system prompt)                     │
│                                                         │
│  输入: user_info + 当前状态                               │
│  输出: 完整 system prompt 字符串                          │
└───────────┬────────────────────────────┬────────────────┘
            │                            │
            ▼                            ▼
┌───────────────────────┐    ┌───────────────────────────┐
│   PromptLibrary       │    │   PersonalitySystem       │
│   (MD 文件提示词库)    │    │   (性格系统)               │
│                       │    │                           │
│  · core/              │    │  · 大五人格维度            │
│  · capabilities/      │    │  · 情绪状态 (动态)         │
│  · extensions/        │    │  · 关系亲密度              │
│  · 动态加载/卸载       │    │  · 性格预设 (YAML)        │
│  · 热重载              │    │  · 自然语言描述生成        │
└───────────────────────┘    └───────────────────────────┘
            │                            │
            └────────────┬───────────────┘
                         │
                         ▼
              ┌──────────────────┐
              │  SkillRegistry   │
              │  (技能提示词注入) │
              │                  │
              │  已加载技能的     │
              │  MD 提示词内容    │
              └──────────────────┘
```

### 5.2 PromptLibrary — MD 文件提示词库

**文件格式:**

```markdown
---
name: task_handling
category: capabilities
version: 1.0
description: 任务处理能力定义
tags: [task, action, reminder]
priority: 50
enabled: true
---

## 任务处理能力

你可以通过 <task></task> 标签发送任务指令...
```

**核心能力:**

| 操作 | 方法 | 说明 |
|------|------|------|
| 扫描加载 | `scan_and_load()` | 启动时加载所有 MD 文件 |
| 动态加载 | `load_file(path)` | 运行时加载单个文件 |
| 卸载 | `unload(prompt_id)` | 移除指定提示词 |
| 热重载 | `reload(prompt_id)` | 从磁盘重新读取 |
| 启用/禁用 | `toggle(prompt_id, bool)` | 不删除，只是不参与组装 |
| 上传 | API `POST /api/prompts/upload` | 通过 API 上传新 MD |

### 5.3 PersonalitySystem — 性格系统

**模型:**

```
┌─────────────────────────────────────────┐
│           PersonalityProfile            │
│                                         │
│  ┌─────────────────────────────────┐    │
│  │ 大五人格 (底层维度, 静态)        │    │
│  │ O: 开放性  C: 尽责性             │    │
│  │ E: 外向性  A: 宜人性             │    │
│  │ N: 神经质                        │    │
│  └─────────────────────────────────┘    │
│                                         │
│  ┌─────────────────────────────────┐    │
│  │ 情绪状态 (短期波动, 动态)        │    │
│  │ energy     精力水平              │    │
│  │ positivity 积极程度              │    │
│  │ patience   耐心程度              │    │
│  │ curiosity  好奇心                │    │
│  │         ↕ 向基线自然回归         │    │
│  └─────────────────────────────────┘    │
│                                         │
│  ┌─────────────────────────────────┐    │
│  │ 语言风格                         │    │
│  │ formality  正式度                │    │
│  │ verbosity  详细度                │    │
│  │ humor      幽默度                │    │
│  │ sarcasm    讽刺度                │    │
│  └─────────────────────────────────┘    │
│                                         │
│  ┌─────────────────────────────────┐    │
│  │ 关系动态                         │    │
│  │ intimacy: 0.0 ──────────→ 1.0   │    │
│  │ (随交互次数增长, 有上限)          │    │
│  └─────────────────────────────────┘    │
│                                         │
│  口头禅 · 习惯 · 话题态度               │
└─────────────────────────────────────────┘
```

**性格预设示例:**

```yaml
# prompts/personality/default.yaml
name: default
display_name: "默认"
description: "友善、理性、略带好奇"

traits:
  openness: 0.7
  conscientiousness: 0.6
  extraversion: 0.5
  agreeableness: 0.7
  neuroticism: 0.3

emotion_baseline:
  energy: 0.6
  positivity: 0.7
  patience: 0.7
  curiosity: 0.8

speech_style:
  formality: 0.3
  verbosity: 0.4
  humor: 0.4
  sarcasm: 0.1

catchphrases: []
habits:
  - "回答前会先确认理解了问题"
  - "遇到不确定的事情会坦诚说明"

relationship:
  initial_distance: 0.5
  warming_rate: 0.02
  max_intimacy: 0.9
```

**输出不是字段拼接，而是自然语言描述:**

```
## 你的性格

你的性格特点：开放性偏高（开放好奇），宜人性偏高（温和友善）。
你现在的状态：精力充沛，心情不错，充满好奇。请根据这个状态调整你的语气和表达方式。
你的说话风格：说话随意自然，像朋友聊天；回答简洁，不啰嗦。
你和用户有过一些交流，逐渐熟悉中。
```

### 5.4 PromptEngine — 组装引擎

```python
class PromptEngine:
    def build_system_prompt(self, user_info) -> str:
        sections = []

        # 1. core/ — 身份·格式·安全
        sections.append(library.get_content_by_category("core"))

        # 2. 性格描述 (动态生成)
        sections.append(personality.generate_personality_prompt())

        # 3. capabilities/ — 能力定义
        sections.append(library.get_content_by_category("capabilities"))

        # 4. 已加载技能的提示词 (从 SkillRegistry 获取)
        sections.append(skill_registry.get_all_skill_prompts())

        # 5. extensions/ — 用户扩展
        sections.append(library.get_content_by_category("extensions"))

        # 6. 用户上下文
        sections.append(f"当前用户：{nickname}\n当前时间：{now}")

        return "\n\n".join(sections)
```

---

## 六、技能系统 (核心新增)

### 6.1 什么是技能

**技能 = 一组 MD 提示词 + 可选的 Python 工具代码，打包成一个可加载/卸载的能力单元。**

```
skills/builtin/web_search/
├── skill.yaml              # 技能元数据
├── prompts/                # 提示词文件 (会被注入 system prompt)
│   ├── instruction.md      # 使用说明
│   └── examples.md         # 使用示例
└── tools/                  # 工具代码 (可选, AI 可调用)
    └── search.py           # 搜索工具实现
```

**技能与插件的区别:**

| 维度 | 插件 (Plugin) | 技能 (Skill) |
|------|--------------|-------------|
| 本质 | 运行时代码钩子 | 提示词 + 工具的能力包 |
| 影响范围 | 拦截/修改管道流程 | 扩展 AI 的知识和能力 |
| 触发方式 | 自动 (钩子) | AI 主动选择使用 |
| 用户感知 | 透明 | AI 会说"我用XX技能帮你..." |
| 典型用途 | ASR过滤、TTS合成 | 网页搜索、代码审查、翻译 |
| 可蒸馏 | 否 | **是** |

### 6.2 技能元数据 (skill.yaml)

```yaml
# skills/builtin/web_search/skill.yaml
name: web_search
display_name: "网页搜索"
description: "搜索互联网获取最新信息"
version: "1.0"
author: "system"              # system / distilled / user
source: "builtin"             # builtin / distilled / custom
enabled: true
status: "active"              # active / draft / archived

# 提示词加载行为
prompt_category: "skills"     # 注入到 PromptEngine 的哪个位置
prompt_priority: 60           # 在 system prompt 中的排序

# 工具注册 (可选)
tools:
  - name: search
    display_name: "搜索"
    description: "搜索互联网获取信息"
    module: "tools.search"
    class: "WebSearchTool"
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

# 激活条件 (可选, 用于自动激活建议)
activation:
  keywords: ["搜索", "查找", "最新", "新闻", "搜一下"]
  auto_activate: false        # true = 始终激活, false = AI 自主判断

# 依赖 (可选)
dependencies: []              # 依赖的其他技能名

# 标签
tags: [search, web, information]
```

### 6.3 技能提示词示例

```markdown
<!-- skills/builtin/web_search/prompts/instruction.md -->
---
name: web_search_instruction
category: skills
priority: 60
---

## 网页搜索技能

你具备网页搜索能力。当用户需要查找最新信息、新闻、资料时，你可以使用搜索工具。

### 使用方式

通过 <tool> 标签调用搜索工具：

<tool>
{
  "skill": "web_search",
  "tool": "search",
  "params": {
    "query": "搜索内容",
    "max_results": 5
  }
}
</tool>

### 使用原则

1. 当用户明确要求搜索时，直接使用
2. 当你需要最新信息来回答问题时，主动使用
3. 搜索后整合结果，用自己的话总结给用户
4. 如果搜索结果不够好，可以换关键词再搜一次
```

```markdown
<!-- skills/builtin/web_search/prompts/examples.md -->
---
name: web_search_examples
category: skills
priority: 61
---

### 搜索示例

用户: 帮我查一下今天的天气
<tool>
{
  "skill": "web_search",
  "tool": "search",
  "params": {"query": "今天天气", "max_results": 3}
}
</tool>

用户: 最近有什么科技新闻
<tool>
{
  "skill": "web_search",
  "tool": "search",
  "params": {"query": "最新科技新闻 2026", "max_results": 5}
}
</tool>
```

### 6.4 技能工具代码示例

```python
# skills/builtin/web_search/tools/search.py

import requests
import logging
from typing import Dict, Any, List

logger = logging.getLogger("skill.web_search")


class WebSearchTool:
    """网页搜索工具 — 技能工具的参考实现"""

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.api_url = self.config.get("api_url", "https://api.example.com/search")
        self.api_key = self.config.get("api_key", "")
        self.timeout = self.config.get("timeout", 30)

    def search(self, query: str, max_results: int = 5) -> Dict[str, Any]:
        """
        执行网页搜索。

        :param query: 搜索关键词
        :param max_results: 最大结果数
        :return: 搜索结果字典
        """
        try:
            resp = requests.get(
                self.api_url,
                params={"q": query, "count": max_results},
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()

            results = []
            for item in data.get("results", [])[:max_results]:
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("snippet", ""),
                })

            return {
                "success": True,
                "query": query,
                "results": results,
                "count": len(results),
            }

        except Exception as e:
            logger.error("搜索失败: %s", e)
            return {
                "success": False,
                "error": str(e),
                "query": query,
                "results": [],
            }
```

### 6.5 SkillManager — 技能生命周期管理

```python
# skills/manager.py

import logging
from pathlib import Path
from typing import Dict, List, Optional, Any

from .registry import SkillRegistry
from .loader import SkillLoader


class SkillManager:
    """
    技能生命周期管理器。

    职责:
    - 扫描并加载技能
    - 启用/禁用/卸载技能
    - 查询技能列表和状态
    - 与 SkillRegistry 交互 (注册/注销工具和提示词)
    """

    def __init__(self, skill_dirs: List[str], registry: SkillRegistry):
        self.skill_dirs = [Path(d) for d in skill_dirs]
        self.registry = registry
        self.loader = SkillLoader()
        self._skills: Dict[str, 'Skill'] = {}
        self.logger = logging.getLogger("SkillManager")

    def scan_and_load(self) -> int:
        """扫描所有技能目录并加载"""
        count = 0
        for skill_dir in self.skill_dirs:
            if not skill_dir.exists():
                continue
            for sub_dir in skill_dir.iterdir():
                if not sub_dir.is_dir() or sub_dir.name.startswith("_"):
                    continue
                skill_yaml = sub_dir / "skill.yaml"
                if skill_yaml.exists():
                    try:
                        skill = self.loader.load(sub_dir)
                        if skill and skill.enabled:
                            self._skills[skill.name] = skill
                            self.registry.register_skill(skill)
                            count += 1
                    except Exception as e:
                        self.logger.error("加载技能失败 %s: %s", sub_dir, e)
        self.logger.info("加载了 %d 个技能", count)
        return count

    def enable(self, name: str) -> bool:
        """启用技能"""
        skill = self._skills.get(name)
        if not skill:
            return False
        skill.enabled = True
        self.registry.register_skill(skill)
        self.logger.info("启用技能: %s", name)
        return True

    def disable(self, name: str) -> bool:
        """禁用技能 (不卸载，只是不注入 prompt 和不注册工具)"""
        skill = self._skills.get(name)
        if not skill:
            return False
        skill.enabled = False
        self.registry.unregister_skill(name)
        self.logger.info("禁用技能: %s", name)
        return True

    def unload(self, name: str) -> bool:
        """完全卸载技能"""
        skill = self._skills.pop(name, None)
        if not skill:
            return False
        self.registry.unregister_skill(name)
        self.logger.info("卸载技能: %s", name)
        return True

    def install(self, skill_dir: str) -> bool:
        """安装新技能 (从目录)"""
        try:
            skill = self.loader.load(skill_dir)
            if skill:
                self._skills[skill.name] = skill
                if skill.enabled:
                    self.registry.register_skill(skill)
                return True
        except Exception as e:
            self.logger.error("安装技能失败: %s", e)
        return False

    def list_skills(self, status: str = None) -> List[Dict]:
        """列出技能"""
        result = []
        for skill in self._skills.values():
            if status and skill.status != status:
                continue
            result.append({
                "name": skill.name,
                "display_name": skill.display_name,
                "description": skill.description,
                "version": skill.version,
                "author": skill.author,
                "source": skill.source,
                "enabled": skill.enabled,
                "status": skill.status,
                "tags": skill.tags,
                "has_tools": bool(skill.tools),
                "prompt_count": len(skill.prompts),
            })
        return result

    def get_skill(self, name: str) -> Optional['Skill']:
        return self._skills.get(name)
```

### 6.6 SkillRegistry — 技能注册表

```python
# skills/registry.py

import importlib.util
import logging
from typing import Dict, List, Optional, Any


class SkillRegistry:
    """
    技能注册表。

    职责:
    - 管理已注册技能的工具实例
    - 提供工具调用接口 (供 task_plugin 调用)
    - 聚合所有已启用技能的提示词内容 (供 PromptEngine 使用)
    """

    def __init__(self):
        self._tool_instances: Dict[str, Any] = {}      # "skill_name.tool_name" → instance
        self._tool_specs: Dict[str, Dict] = {}          # "skill_name.tool_name" → spec
        self._skill_prompts: Dict[str, str] = {}        # "skill_name" → 聚合提示词
        self._active_skills: Dict[str, 'Skill'] = {}
        self.logger = logging.getLogger("SkillRegistry")

    def register_skill(self, skill: 'Skill') -> None:
        """注册技能: 加载工具 + 聚合提示词"""
        self._active_skills[skill.name] = skill

        # 注册工具
        if skill.tools:
            for tool_spec in skill.tools:
                try:
                    instance = self._load_tool(tool_spec, skill.skill_dir)
                    if instance:
                        key = f"{skill.name}.{tool_spec['name']}"
                        self._tool_instances[key] = instance
                        self._tool_specs[key] = tool_spec
                        self.logger.info("注册技能工具: %s", key)
                except Exception as e:
                    self.logger.error("加载工具失败 %s.%s: %s",
                                      skill.name, tool_spec['name'], e)

        # 聚合提示词
        prompts_content = []
        for prompt in skill.prompts:
            if prompt.content.strip():
                prompts_content.append(prompt.content)
        if prompts_content:
            self._skill_prompts[skill.name] = "\n\n".join(prompts_content)

    def unregister_skill(self, name: str) -> None:
        """注销技能"""
        self._active_skills.pop(name, None)
        self._skill_prompts.pop(name, None)

        # 移除该技能的所有工具
        keys_to_remove = [k for k in self._tool_instances if k.startswith(f"{name}.")]
        for key in keys_to_remove:
            self._tool_instances.pop(key, None)
            self._tool_specs.pop(key, None)

    def call_tool(self, skill_name: str, tool_name: str,
                  params: Dict[str, Any]) -> Any:
        """
        调用技能工具。

        :param skill_name: 技能名
        :param tool_name: 工具名
        :param params: 调用参数
        :return: 工具返回值
        """
        key = f"{skill_name}.{tool_name}"
        instance = self._tool_instances.get(key)
        if not instance:
            raise ValueError(f"工具不存在: {key}")

        method = getattr(instance, tool_name, None)
        if not method or not callable(method):
            raise ValueError(f"工具方法不存在: {key}.{tool_name}")

        return method(**params)

    def get_tool_spec(self, skill_name: str, tool_name: str) -> Optional[Dict]:
        """获取工具规格"""
        return self._tool_specs.get(f"{skill_name}.{tool_name}")

    def get_all_tool_specs(self) -> List[Dict]:
        """获取所有已注册工具的规格 (用于生成工具列表注入 prompt)"""
        return [
            {**spec, "skill": key.split(".")[0], "full_name": key}
            for key, spec in self._tool_specs.items()
        ]

    def get_all_skill_prompts(self) -> str:
        """获取所有已启用技能的提示词 (供 PromptEngine 注入)"""
        contents = []
        for name, content in self._skill_prompts.items():
            if content.strip():
                contents.append(content)
        return "\n\n".join(contents) if contents else ""

    def has_skill(self, name: str) -> bool:
        return name in self._active_skills

    def list_active_tools(self) -> List[str]:
        return list(self._tool_instances.keys())

    def _load_tool(self, tool_spec: Dict, skill_dir) -> Any:
        """动态加载工具 Python 模块"""
        module_path = tool_spec.get("module", "")
        class_name = tool_spec.get("class", "")

        if not module_path or not class_name:
            return None

        # 解析模块路径: "tools.search" → skill_dir/tools/search.py
        parts = module_path.split(".")
        file_name = parts[-1] + ".py"
        file_path = Path(skill_dir) / "/".join(parts[:-1]) / file_name

        if not file_path.exists():
            self.logger.warning("工具文件不存在: %s", file_path)
            return None

        spec = importlib.util.spec_from_file_location(
            f"skill_tools.{module_path.replace('.', '_')}", file_path
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        cls = getattr(mod, class_name, None)
        if not cls:
            return None

        return cls()
```

### 6.7 SkillLoader — 技能加载器

```python
# skills/loader.py

import yaml
import re
import logging
from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass, field


@dataclass
class ToolSpec:
    """工具规格"""
    name: str
    display_name: str = ""
    description: str = ""
    module: str = ""
    class_name: str = ""
    methods: List[Dict] = field(default_factory=list)


@dataclass
class PromptFile:
    """提示词文件"""
    name: str
    category: str = "skills"
    priority: int = 60
    content: str = ""
    source_file: str = ""


@dataclass
class Skill:
    """技能定义"""
    name: str
    display_name: str = ""
    description: str = ""
    version: str = "1.0"
    author: str = "system"
    source: str = "builtin"
    enabled: bool = True
    status: str = "active"          # active / draft / archived

    prompt_category: str = "skills"
    prompt_priority: int = 60

    tools: List[ToolSpec] = field(default_factory=list)
    prompts: List[PromptFile] = field(default_factory=list)

    activation: Dict = field(default_factory=dict)
    dependencies: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)

    skill_dir: str = ""             # 技能目录路径


class SkillLoader:
    """技能加载器 — 从目录加载技能定义"""

    def load(self, skill_dir: str) -> Optional[Skill]:
        """从目录加载技能"""
        path = Path(skill_dir)
        yaml_file = path / "skill.yaml"

        if not yaml_file.exists():
            raise FileNotFoundError(f"skill.yaml not found in {skill_dir}")

        with open(yaml_file, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        if not data or 'name' not in data:
            raise ValueError("Invalid skill.yaml: missing 'name'")

        # 加载提示词文件
        prompts = self._load_prompts(path / "prompts")

        # 解析工具规格
        tools = self._parse_tools(data.get("tools", []))

        return Skill(
            name=data['name'],
            display_name=data.get('display_name', data['name']),
            description=data.get('description', ''),
            version=data.get('version', '1.0'),
            author=data.get('author', 'system'),
            source=data.get('source', 'builtin'),
            enabled=data.get('enabled', True),
            status=data.get('status', 'active'),
            prompt_category=data.get('prompt_category', 'skills'),
            prompt_priority=data.get('prompt_priority', 60),
            tools=tools,
            prompts=prompts,
            activation=data.get('activation', {}),
            dependencies=data.get('dependencies', []),
            tags=data.get('tags', []),
            skill_dir=str(path),
        )

    def _load_prompts(self, prompts_dir: Path) -> List[PromptFile]:
        """加载技能目录下的 prompts/ 子目录"""
        prompts = []
        if not prompts_dir.exists():
            return prompts

        for md_file in sorted(prompts_dir.glob("*.md")):
            try:
                text = md_file.read_text(encoding='utf-8')
                match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
                if match:
                    meta = yaml.safe_load(match.group(1)) or {}
                    content = match.group(2).strip()
                else:
                    meta = {}
                    content = text.strip()

                prompts.append(PromptFile(
                    name=meta.get('name', md_file.stem),
                    category=meta.get('category', 'skills'),
                    priority=meta.get('priority', 60),
                    content=content,
                    source_file=str(md_file),
                ))
            except Exception as e:
                logging.getLogger("SkillLoader").error(
                    "加载提示词失败 %s: %s", md_file, e
                )
        return prompts

    def _parse_tools(self, tools_data: list) -> List[ToolSpec]:
        """解析 skill.yaml 中的 tools 定义"""
        specs = []
        for t in tools_data:
            specs.append(ToolSpec(
                name=t.get('name', ''),
                display_name=t.get('display_name', ''),
                description=t.get('description', ''),
                module=t.get('module', ''),
                class_name=t.get('class', ''),
                methods=t.get('methods', []),
            ))
        return specs
```

---

## 七、自动蒸馏系统 (核心新增)

### 7.1 设计理念

```
用户对话 ──→ 模式挖掘 ──→ 技能草案 ──→ 人工审核 ──→ 激活技能
                │                          │
                │  ┌───────────────────────┘
                │  │
                ▼  ▼
         不断迭代优化
```

**核心思想:** AI 通过与用户的真实交互"学会"新能力。不是简单的 prompt 模板，而是从对话中提取模式、生成结构化的技能包（提示词 + 可选工具代码）。

### 7.2 蒸馏流程

```
┌─────────────────────────────────────────────────────────────┐
│                   DistillationEngine                         │
│                                                             │
│  ┌───────────────┐                                          │
│  │ 1. 对话收集    │  从 chatdbmgr 获取最近 N 轮对话           │
│  └───────┬───────┘                                          │
│          ▼                                                  │
│  ┌───────────────┐                                          │
│  │ 2. 模式挖掘    │  使用 LLM 分析对话，识别重复模式           │
│  │               │  - 用户经常问什么？                        │
│  │               │  - AI 怎么回答的？                         │
│  │               │  - 有没有固定的处理流程？                   │
│  │               │  - 是否涉及外部工具调用？                   │
│  └───────┬───────┘                                          │
│          ▼                                                  │
│  ┌───────────────┐                                          │
│  │ 3. 模式聚类    │  将相似模式归类，判断是否值得蒸馏           │
│  │               │  - 出现频率 > 阈值                         │
│  │               │  - 有明确的知识/流程可提取                  │
│  │               │  - 不与现有技能重复                        │
│  └───────┬───────┘                                          │
│          ▼                                                  │
│  ┌───────────────┐                                          │
│  │ 4. 草案生成    │  使用 LLM 生成技能结构:                   │
│  │               │  - skill.yaml (元数据)                     │
│  │               │  - prompts/instruction.md (使用说明)       │
│  │               │  - prompts/patterns.md (提取的模式)        │
│  │               │  - prompts/examples.md (真实对话示例)      │
│  │               │  - tools/*.py (可选, 工具代码草案)         │
│  └───────┬───────┘                                          │
│          ▼                                                  │
│  ┌───────────────┐                                          │
│  │ 5. 草案存储    │  保存到 skills/distilled/_drafts/         │
│  │               │  status = "draft"                         │
│  └───────┬───────┘                                          │
│          ▼                                                  │
│  ┌───────────────┐                                          │
│  │ 6. 通知用户    │  通知用户有新技能草案待审核                 │
│  └──────────────────────────────────────────────────────────┘
│                                                             │
│  ┌──────────────────────────────────────────────────────────┐│
│  │ 7. 人工审核 (用户操作)                                    ││
│  │    - 查看草案内容                                         ││
│  │    - 编辑修改                                             ││
│  │    - 批准 → status="active" → 自动加载                    ││
│  │    - 拒绝 → 删除草案                                      ││
│  └──────────────────────────────────────────────────────────┘│
│                                                             │
│  ┌──────────────────────────────────────────────────────────┐│
│  │ 8. 技能迭代 (持续优化)                                    ││
│  │    - 已激活技能继续积累相关对话                            ││
│  │    - 定期重新蒸馏，更新提示词和工具代码                    ││
│  │    - 版本递增: v1 → v2 → v3                              ││
│  └──────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

### 7.3 DistillationEngine 实现

```python
# skills/distill.py

import json
import logging
import re
import yaml
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger("DistillationEngine")


class DistillationEngine:
    """
    自动蒸馏引擎。

    从用户对话中提取模式，生成技能草案。
    """

    def __init__(
        self,
        db=None,                    # ChatDBManager
        skill_manager=None,         # SkillManager
        llm_client=None,            # 用于分析的 LLM 客户端
        draft_dir: str = "skills/distilled/_drafts",
    ):
        self.db = db
        self.skill_manager = skill_manager
        self.llm = llm_client
        self.draft_dir = Path(draft_dir)
        self.draft_dir.mkdir(parents=True, exist_ok=True)

        # 蒸馏配置
        self.min_conversations = 10     # 最少对话轮数才触发
        self.min_pattern_frequency = 3  # 模式最少出现次数
        self.max_draft_age_days = 7     # 草案最大保留天数
        self.analysis_window_days = 30  # 分析最近多少天的对话

    # ---- 主流程 ----

    async def run(self, user_id: int = None) -> Dict[str, Any]:
        """
        执行一次完整的蒸馏流程。

        :return: 蒸馏结果报告
        """
        report = {
            "timestamp": datetime.now().isoformat(),
            "conversations_analyzed": 0,
            "patterns_found": 0,
            "drafts_created": 0,
            "drafts": [],
        }

        # 1. 收集对话
        conversations = self._collect_conversations(user_id)
        report["conversations_analyzed"] = len(conversations)

        if len(conversations) < self.min_conversations:
            logger.info("对话数量不足 (%d < %d)，跳过蒸馏",
                        len(conversations), self.min_conversations)
            return report

        # 2. 模式挖掘
        patterns = await self._mine_patterns(conversations)
        report["patterns_found"] = len(patterns)

        if not patterns:
            logger.info("未发现可蒸馏的模式")
            return report

        # 3. 为每个模式生成草案
        for pattern in patterns:
            try:
                draft = await self._generate_draft(pattern, conversations)
                if draft:
                    saved_path = self._save_draft(draft)
                    report["drafts_created"] += 1
                    report["drafts"].append({
                        "name": draft["name"],
                        "path": str(saved_path),
                        "pattern_count": pattern.get("occurrence_count", 0),
                    })
            except Exception as e:
                logger.error("生成草案失败: %s", e, exc_info=True)

        # 4. 清理过期草案
        self._cleanup_old_drafts()

        logger.info("蒸馏完成: 分析 %d 轮对话, 发现 %d 个模式, 生成 %d 个草案",
                     report["conversations_analyzed"],
                     report["patterns_found"],
                     report["drafts_created"])

        return report

    # ---- 步骤实现 ----

    def _collect_conversations(self, user_id: int = None) -> List[Dict]:
        """从数据库收集最近对话"""
        if not self.db:
            return []

        try:
            cutoff = datetime.now() - timedelta(days=self.analysis_window_days)
            # 获取所有聊天记录
            chats = self.db.list_chats(user_id) if user_id else self.db.list_all_chats()
            conversations = []

            for chat in chats:
                messages = self.db.get_messages(chat['id'], user_id)
                for msg in messages:
                    conversations.append({
                        "chat_id": chat['id'],
                        "chat_name": chat.get('name', ''),
                        "role": msg['role'],
                        "content": msg['content'],
                        "timestamp": msg.get('timestamp', ''),
                    })

            return conversations

        except Exception as e:
            logger.error("收集对话失败: %s", e)
            return []

    async def _mine_patterns(self, conversations: List[Dict]) -> List[Dict]:
        """
        使用 LLM 分析对话，挖掘可蒸馏的模式。

        返回模式列表，每个模式包含:
        - name: 模式名称
        - description: 模式描述
        - occurrence_count: 出现次数
        - example_exchanges: 典型对话示例
        - category: 分类 (knowledge / workflow / tool_usage / preference)
        - suggested_tools: 建议的工具 (可选)
        """
        if not self.llm:
            return []

        # 构建分析 prompt
        analysis_prompt = self._build_analysis_prompt(conversations)

        try:
            messages = [
                {"role": "system", "content": analysis_prompt},
            ]
            response = self.llm.send_message(messages)

            # 解析 LLM 返回的 JSON
            patterns = self._parse_patterns_response(response)
            return patterns

        except Exception as e:
            logger.error("模式挖掘失败: %s", e)
            return []

    def _build_analysis_prompt(self, conversations: List[Dict]) -> str:
        """构建模式分析的 prompt"""
        # 截取对话 (避免太长)
        sampled = conversations[-200:]  # 最近 200 条

        dialog_text = ""
        for msg in sampled:
            role = "用户" if msg["role"] == "user" else "EXA"
            content = msg["content"][:200]  # 截断长消息
            dialog_text += f"{role}: {content}\n"

        return f"""你是一个对话分析专家。请分析以下 AI 助手 (EXA) 与用户的对话记录，识别可以蒸馏为"技能"的重复模式。

## 什么是可蒸馏的模式？

1. **知识型模式**: 用户反复询问某类知识，AI 每次都用类似的方式回答
   例: 用户经常问某个领域的专业术语解释

2. **工作流模式**: 用户经常要求执行某个固定的多步骤流程
   例: 用户经常让 AI "帮我审查这段代码"并遵循固定步骤

3. **工具使用模式**: AI 经常需要调用外部工具来完成某类任务
   例: AI 经常需要搜索最新信息来回答问题

4. **偏好模式**: 用户对某类回答有明确的偏好
   例: 用户总是要求"用简单的话解释"

## 对话记录

{dialog_text}

## 输出要求

请以 JSON 数组格式输出你发现的模式。每个模式包含:
- name: 模式名称 (英文, snake_case)
- display_name: 中文显示名
- description: 详细描述
- category: 分类 (knowledge / workflow / tool_usage / preference)
- occurrence_count: 估计出现次数
- example_exchanges: 2-3 个典型对话示例 (user + assistant 对)
- key_insights: 从对话中提取的关键知识点或流程步骤
- suggested_tools: 建议的工具 (可选, 如果需要外部工具)

只输出出现频率 >= {self.min_pattern_frequency} 次的模式。
如果没有发现值得蒸馏的模式，输出空数组 []。

请直接输出 JSON，不要有其他文字。"""

    def _parse_patterns_response(self, response: str) -> List[Dict]:
        """解析 LLM 返回的模式 JSON"""
        # 尝试提取 JSON
        json_match = re.search(r'\[.*\]', response, re.DOTALL)
        if not json_match:
            return []

        try:
            patterns = json.loads(json_match.group())
            if not isinstance(patterns, list):
                return []
            return patterns
        except json.JSONDecodeError:
            logger.warning("模式解析 JSON 失败")
            return []

    async def _generate_draft(
        self, pattern: Dict, conversations: List[Dict]
    ) -> Optional[Dict]:
        """
        根据模式生成技能草案。

        返回草案结构:
        {
            "skill.yaml": "...",
            "prompts/instruction.md": "...",
            "prompts/patterns.md": "...",
            "prompts/examples.md": "...",
            "tools/*.py": "..." (可选)
        }
        """
        if not self.llm:
            return None

        generation_prompt = f"""你是一个技能设计师。根据以下从对话中提取的模式，生成一个完整的技能草案。

## 模式信息

名称: {pattern.get('name', 'unknown')}
显示名: {pattern.get('display_name', '')}
描述: {pattern.get('description', '')}
分类: {pattern.get('category', '')}
出现次数: {pattern.get('occurrence_count', 0)}
关键洞察: {json.dumps(pattern.get('key_insights', []), ensure_ascii=False)}
建议工具: {json.dumps(pattern.get('suggested_tools', []), ensure_ascii=False)}

## 典型对话示例

{json.dumps(pattern.get('example_exchanges', []), ensure_ascii=False, indent=2)}

## 输出要求

请生成以下文件内容，以 JSON 格式输出:

{{
  "skill.yaml": "技能元数据 YAML 内容",
  "prompts/instruction.md": "技能使用说明 (Markdown, 含 YAML frontmatter)",
  "prompts/patterns.md": "从对话中提取的知识/模式 (Markdown, 含 YAML frontmatter)",
  "prompts/examples.md": "使用示例 (Markdown, 含 YAML frontmatter)",
  "tools/main.py": "工具代码 (如果需要外部工具, 否则为 null)"
}}

### skill.yaml 格式要求:
```yaml
name: {pattern.get('name', 'unknown')}
display_name: "{pattern.get('display_name', '')}"
description: "{pattern.get('description', '')}"
version: "0.1-draft"
author: "distilled"
source: "distilled"
enabled: false
status: "draft"
prompt_priority: 70
tags: [{pattern.get('category', '')}]
tools: []  # 或工具定义
```

### prompts/*.md 格式要求:
每个 MD 文件需要 YAML frontmatter:
```
---
name: xxx
category: skills
priority: 70
---
```

### tools/main.py 格式要求:
如果需要工具，生成一个 Python 类，包含:
- 类名 (PascalCase)
- 方法 (与 skill.yaml 中的 tools 定义对应)
- 完整的错误处理
- 类型注解

请直接输出 JSON，不要有其他文字。"""

        try:
            messages = [
                {"role": "system", "content": generation_prompt},
            ]
            response = self.llm.send_message(messages)

            # 解析返回的 JSON
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if not json_match:
                return None

            draft = json.loads(json_match.group())
            draft["_meta"] = {
                "pattern": pattern.get('name'),
                "created_at": datetime.now().isoformat(),
                "source_conversations": len(conversations),
            }
            return draft

        except Exception as e:
            logger.error("生成草案失败: %s", e)
            return None

    def _save_draft(self, draft: Dict) -> Path:
        """将草案保存到磁盘"""
        name = draft.get("skill.yaml", "").split("name:")[1].split("\n")[0].strip()
        if not name:
            name = f"draft_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        draft_dir = self.draft_dir / name
        draft_dir.mkdir(parents=True, exist_ok=True)

        # 保存各文件
        for file_path, content in draft.items():
            if file_path.startswith("_"):
                continue
            if content is None:
                continue

            full_path = draft_dir / file_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)

        logger.info("草案已保存: %s", draft_dir)
        return draft_dir

    def _cleanup_old_drafts(self):
        """清理过期草案"""
        if not self.draft_dir.exists():
            return

        cutoff = datetime.now() - timedelta(days=self.max_draft_age_days)
        for draft_dir in self.draft_dir.iterdir():
            if not draft_dir.is_dir():
                continue
            # 检查修改时间
            mtime = datetime.fromtimestamp(draft_dir.stat().st_mtime)
            if mtime < cutoff:
                import shutil
                shutil.rmtree(draft_dir)
                logger.info("清理过期草案: %s", draft_dir)

    # ---- 草案管理 ----

    def list_drafts(self) -> List[Dict]:
        """列出所有待审核草案"""
        drafts = []
        if not self.draft_dir.exists():
            return drafts

        for draft_dir in sorted(self.draft_dir.iterdir()):
            if not draft_dir.is_dir():
                continue
            yaml_file = draft_dir / "skill.yaml"
            if yaml_file.exists():
                try:
                    with open(yaml_file, 'r', encoding='utf-8') as f:
                        data = yaml.safe_load(f)
                    drafts.append({
                        "name": data.get('name', draft_dir.name),
                        "display_name": data.get('display_name', ''),
                        "description": data.get('description', ''),
                        "version": data.get('version', ''),
                        "path": str(draft_dir),
                        "files": [f.name for f in draft_dir.rglob("*") if f.is_file()],
                    })
                except Exception:
                    drafts.append({
                        "name": draft_dir.name,
                        "path": str(draft_dir),
                        "error": "无法解析 skill.yaml",
                    })
        return drafts

    def approve_draft(self, name: str) -> bool:
        """
        审核通过草案 → 移动到 distilled/ 并激活。

        :return: 是否成功
        """
        draft_dir = self.draft_dir / name
        if not draft_dir.exists():
            return False

        # 更新 skill.yaml 状态
        yaml_file = draft_dir / "skill.yaml"
        if yaml_file.exists():
            with open(yaml_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
            data['status'] = 'active'
            data['enabled'] = True
            # 更新版本号
            version = data.get('version', '0.1-draft')
            data['version'] = version.replace('-draft', '')
            with open(yaml_file, 'w', encoding='utf-8') as f:
                yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

        # 移动到 distilled/ 目录
        import shutil
        target_dir = Path("skills/distilled") / name
        if target_dir.exists():
            shutil.rmtree(target_dir)
        shutil.move(str(draft_dir), str(target_dir))

        # 通过 SkillManager 加载
        if self.skill_manager:
            self.skill_manager.install(str(target_dir))

        logger.info("草案已批准并激活: %s → %s", name, target_dir)
        return True

    def reject_draft(self, name: str) -> bool:
        """拒绝并删除草案"""
        draft_dir = self.draft_dir / name
        if not draft_dir.exists():
            return False
        import shutil
        shutil.rmtree(draft_dir)
        logger.info("草案已拒绝并删除: %s", name)
        return True

    def iterate_skill(self, skill_name: str) -> bool:
        """
        对已激活的蒸馏技能进行迭代优化。

        收集该技能激活后的新对话，重新蒸馏，更新提示词。
        """
        # TODO: 实现技能迭代
        logger.info("技能迭代: %s (待实现)", skill_name)
        return False
```

### 7.4 蒸馏生成的技能示例

假设用户经常让 EXA 帮忙审查代码，蒸馏系统可能生成如下草案：

```
skills/distilled/_drafts/code_review/
├── skill.yaml
├── prompts/
│   ├── instruction.md
│   ├── patterns.md
│   └── examples.md
└── (无 tools/ — 纯提示词技能)
```

**skill.yaml:**
```yaml
name: code_review
display_name: "代码审查"
description: "根据用户习惯的审查流程，对代码进行系统性审查"
version: "0.1-draft"
author: "distilled"
source: "distilled"
enabled: false
status: "draft"
prompt_priority: 70
tags: [workflow, code]
tools: []
```

**prompts/instruction.md:**
```markdown
---
name: code_review_instruction
category: skills
priority: 70
---

## 代码审查技能

当用户要求你审查代码时，按照以下流程进行：

### 审查流程

1. **理解意图**: 先确认用户想审查什么（功能、安全、性能、风格）
2. **整体浏览**: 快速扫描代码结构，理解整体逻辑
3. **逐层审查**: 按以下维度逐一检查
   - 正确性: 逻辑是否正确
   - 安全性: 是否有安全漏洞
   - 性能: 是否有明显性能问题
   - 可读性: 命名、注释、结构是否清晰
   - 边界情况: 是否处理了异常和边界
4. **总结建议**: 按严重程度分类给出建议
   - 必须修改 (会导致 bug 或安全问题)
   - 建议修改 (影响性能或可维护性)
   - 可选优化 (代码风格等)
```

**prompts/patterns.md:**
```markdown
---
name: code_review_patterns
category: skills
priority: 71
---

## 从历史对话中提取的审查模式

### 用户偏好

- 用户偏好简洁的审查意见，不要过于冗长
- 用户关注安全性，特别是输入验证和权限检查
- 用户使用 Python 为主，偶尔有 JavaScript

### 常见问题模式

- 忘记处理 None/空值
- SQL 拼接而非参数化查询
- 缺少错误处理
- 硬编码配置值
```

**prompts/examples.md:**
```markdown
---
name: code_review_examples
category: skills
priority: 72
---

### 真实对话示例

**用户**: 帮我看看这段登录代码有没有问题
[代码内容]

**EXA**: 我看了这段代码，有几个需要修改的地方：
1. 密码没有做哈希处理，直接明文比较了
2. SQL 语句是拼接的，有注入风险
3. 没有限制登录尝试次数

建议这样改：
[修改建议]
```

### 7.5 蒸馏触发方式

```python
# 三种触发方式:

# 1. 定时自动蒸馏 (推荐)
# 在 config.py 中配置:
DISTILLATION:
  AUTO_ENABLED: true
  INTERVAL_HOURS: 24        # 每 24 小时运行一次
  MIN_CONVERSATIONS: 10     # 最少对话轮数
  MIN_PATTERN_FREQUENCY: 3  # 模式最少出现次数

# 2. API 手动触发
# POST /api/skills/distill

# 3. 对话中触发
# 当用户说 "帮我总结一下你最近学到了什么" 时
# task_plugin 识别为蒸馏请求，调用 DistillationEngine
```

---

## 八、API 端点总览

### 8.1 聊天 API (现有)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chat/send` | 发送消息 |
| POST | `/api/chat/stream_send` | 流式发送 |
| GET | `/api/chat/list` | 聊天列表 |
| GET | `/api/chat/<id>` | 聊天历史 |
| POST | `/api/asr/recognize` | ASR 识别 |

### 8.2 Prompt 管理 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/prompts/list` | 列出所有提示词 |
| POST | `/api/prompts/<id>/toggle` | 启用/禁用 |
| POST | `/api/prompts/reload` | 热重载全部 |
| POST | `/api/prompts/upload` | 上传新提示词 |

### 8.3 性格管理 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/personality/list` | 列出性格预设 |
| POST | `/api/personality/switch` | 切换性格 |
| GET | `/api/personality/current` | 当前性格状态 |

### 8.4 技能管理 API (新增)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/skills/list` | 列出所有技能 |
| GET | `/api/skills/<name>` | 技能详情 |
| POST | `/api/skills/<name>/enable` | 启用技能 |
| POST | `/api/skills/<name>/disable` | 禁用技能 |
| DELETE | `/api/skills/<name>` | 卸载技能 |
| POST | `/api/skills/install` | 安装新技能 |

### 8.5 蒸馏 API (新增)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/skills/distill` | 手动触发蒸馏 |
| GET | `/api/skills/distill/drafts` | 列出待审核草案 |
| GET | `/api/skills/distill/drafts/<name>` | 草案详情 |
| POST | `/api/skills/distill/drafts/<name>/approve` | 批准草案 |
| POST | `/api/skills/distill/drafts/<name>/reject` | 拒绝草案 |
| GET | `/api/skills/distill/history` | 蒸馏历史 |

### 8.6 插件管理 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/plugins/list` | 列出所有插件 |
| POST | `/api/plugins/<name>/disable` | 禁用插件 |
| POST | `/api/plugins/<name>/enable` | 启用插件 |

---

## 九、数据流全景

以一次完整的用户交互为例，展示数据在各子系统间的流转：

```
用户: "帮我搜索一下 Python 最新版本"
         │
         ▼
┌── app.py ──────────────────────────────────────────────────┐
│  POST /api/chat/send                                        │
│  { message: "帮我搜索一下 Python 最新版本", tts_enabled: true }│
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌── ChatPipeline.process() ──────────────────────────────────┐
│                                                            │
│  1. 构建 PluginContext                                      │
│     ctx.message = "帮我搜索一下 Python 最新版本"             │
│     ctx.user_id = 42                                       │
│                                                            │
│  2. PromptEngine.build_system_prompt(user_info)            │
│     ├── library.get_content("core")        → 身份+格式     │
│     ├── personality.generate_prompt()       → 性格描述      │
│     ├── library.get_content("capabilities") → 任务处理等    │
│     ├── skill_registry.get_all_prompts()    → ★ web_search │
│     │   技能提示词: "你具备网页搜索能力..."                 │
│     └── 用户上下文 → "当前用户: xxx, 时间: ..."             │
│                                                            │
│     ctx.system_prompt = [拼接后的完整 prompt]               │
│                                                            │
│  3. PRE_FILTER (asr_filter_plugin)                         │
│     → 非语音输入，直接放行                                   │
│                                                            │
│  4. PRE_PROCESS (memory_plugin)                            │
│     → 加载历史消息，注入记忆摘要                             │
│                                                            │
│  5. MODEL_INVOKE (models_plugin)                           │
│     → 复杂度分析: score=0.2, 使用 deepseek-chat             │
│     → 调用 LLM                                             │
│     → AI 回复:                                              │
│       "好的，我来帮你搜索。"                                 │
│       <tool>{"skill":"web_search","tool":"search",          │
│              "params":{"query":"Python latest version"}}    │
│       </tool>                                               │
│                                                            │
│  6. POST_PROCESS (task_plugin)                             │
│     ├── 解析 <task> 标签 → 无                               │
│     ├── 解析 <tool> 标签 → ★ 发现技能工具调用               │
│     │   skill_registry.call_tool(                           │
│     │     "web_search", "search",                           │
│     │     {"query": "Python latest version"}                │
│     │   )                                                   │
│     │   → 返回: {results: [{title: "Python 3.13...", ...}]} │
│     ├── 将工具结果追加到回复                                 │
│     │   ctx.reply += "搜索到了，Python 最新版本是 3.13..."   │
│     └── memory_plugin: 保存对话                             │
│                                                            │
│  7. POST_TTS (tts_plugin)                                  │
│     → 提取 TTS 文本 (排除 <text> 标签)                      │
│     → 调用 TTS 服务 → ctx.audio = <音频数据>                │
│                                                            │
│  8. personality.on_interaction()                           │
│     → 更新情绪: curiosity +0.03                             │
│     → 更新亲密度: intimacy +0.02                            │
│                                                            │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌── 返回结果 ────────────────────────────────────────────────┐
│  {                                                         │
│    "reply": "好的，我来帮你搜索。Python 最新版本是 3.13...", │
│    "audio": "<base64 音频数据>",                            │
│    "model_type": "deepseek",                               │
│    "filtered": false                                       │
│  }                                                         │
└────────────────────────────────────────────────────────────┘
```

---

## 十、技能蒸馏数据流

```
┌── 定时触发 (每 24h) ──────────────────────────────────────┐
│                                                            │
│  DistillationEngine.run()                                  │
│         │                                                  │
│         ▼                                                  │
│  chatdbmgr ──→ 获取最近 30 天对话 (200 条)                  │
│         │                                                  │
│         ▼                                                  │
│  LLM 分析 ──→ 识别模式:                                    │
│    · "代码审查" (出现 12 次)                                │
│    · "翻译助手" (出现 8 次)                                 │
│    · "日程管理" (出现 5 次)                                 │
│         │                                                  │
│         ▼                                                  │
│  LLM 生成草案 ──→ 每个模式生成:                             │
│    · skill.yaml                                            │
│    · prompts/instruction.md                                │
│    · prompts/patterns.md                                   │
│    · prompts/examples.md                                   │
│         │                                                  │
│         ▼                                                  │
│  保存到 skills/distilled/_drafts/                           │
│    ├── code_review/                                        │
│    ├── translation_assistant/                              │
│    └── schedule_manager/                                   │
│         │                                                  │
│         ▼                                                  │
│  通知用户: "发现了 3 个新技能草案，请审核"                    │
│                                                            │
└────────────────────────────────────────────────────────────┘

┌── 用户审核 ───────────────────────────────────────────────┐
│                                                            │
│  GET /api/skills/distill/drafts                            │
│  → [{name: "code_review", description: "...", ...}, ...]   │
│                                                            │
│  GET /api/skills/distill/drafts/code_review                │
│  → 查看 skill.yaml + 所有 prompts 内容                      │
│                                                            │
│  POST /api/skills/distill/drafts/code_review/approve       │
│  → 移动到 skills/distilled/code_review/                    │
│  → status: "draft" → "active"                              │
│  → SkillManager.install() → 自动加载                       │
│  → SkillRegistry.register_skill() → 注册工具和提示词        │
│  → 下次对话时, code_review 的提示词自动注入 system prompt    │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

---

## 十一、迁移路线图

### Phase 1: 基础设施 (不改现有代码)
- [ ] `plugins/base.py`, `manager.py`, `pipeline.py`
- [ ] `prompt/library.py`, `personality.py`, `engine.py`
- [ ] `skills/loader.py`, `registry.py`, `manager.py`
- [ ] 创建 `prompts/` 目录，拆分现有 prompt 为 MD 文件
- [ ] 编写默认性格预设
- [ ] 单元测试

### Phase 2: 内置插件迁移
- [ ] `models_plugin.py` — 统一模型管理
- [ ] `asr_filter_plugin.py`
- [ ] `memory_plugin.py`
- [ ] `task_plugin.py` (含技能工具调用)
- [ ] `tts_plugin.py`

### Phase 3: 技能系统
- [ ] SkillLoader + SkillRegistry + SkillManager
- [ ] 内置技能示例 (file_manager, web_search)
- [ ] 技能管理 API
- [ ] task_plugin 集成技能工具调用

### Phase 4: 自动蒸馏
- [ ] DistillationEngine 核心流程
- [ ] 模式挖掘 prompt 工程
- [ ] 草案生成与存储
- [ ] 蒸馏 API + 审核流程
- [ ] 定时蒸馏任务

### Phase 5: app.py 瘦身
- [ ] 路由改用 ChatPipeline
- [ ] 删除硬编码逻辑
- [ ] 添加所有管理 API
- [ ] 集成测试

### Phase 6: 扩展生态
- [ ] 插件/技能编写指南
- [ ] 更多性格预设
- [ ] 更多内置技能
- [ ] 技能迭代优化
- [ ] 技能分享机制

---

## 十二、新旧对比

| 维度 | v3 (当前) | v4 (改进后) |
|------|-----------|-------------|
| **System Prompt** | 单字符串硬编码 | MD 文件库 + 性格 + 技能 动态组装 |
| **性格** | 无 | 大五人格 + 情绪 + 关系 + 预设切换 |
| **能力扩展** | 改 prompt.py | 写 MD 文件丢进 prompts/ |
| **技能** | 无 | MD 提示词 + Python 工具 的能力包 |
| **自进化** | 无 | 自动蒸馏对话 → 生成技能草案 → 人工审核 |
| **模型管理** | 分散在 models.py + app.py | 统一 models_plugin |
| **加新能力** | 改核心代码 | 写技能 / 写插件 / 写 MD |
| **关闭某个能力** | 改代码 | API toggle / disable |
| **app.py** | ~1060 行 | ~200 行 |
| **可扩展性** | 低 | 高 (插件 + 技能 + 提示词 三层扩展) |
