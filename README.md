## DSN-exp

EXA — 基于 Flask 的插件化 AI 助手系统，支持语音交互、技能扩展和自动进化。

---

### 目录结构

```
DSN-exp/
├── app.py                          # Flask 入口，API 路由与认证中间件
├── config.py                       # 配置管理（从 .env 加载）
├── usermgr.py                      # 用户认证：OAuth2 (LittleSkin) + JWT
├── chatdbmgr.py                    # 数据库管理：SQLite 持久化（用户/聊天/消息/记忆/任务）
│
├── models.py                       # LLM 客户端：DeepSeekChat、LMStudioChat、LMSummaryModel
├── memory.py                       # 记忆引擎：上下文组装与摘要替换
├── tasks.py                        # 任务引擎：提醒/推理/动作的异步调度与执行
├── vocal_infer.py                  # TTS 客户端：GPT-SoVITS 语音合成
├── ASR_filter.py                   # ASR 过滤器：小模型判断语音输入是否转发给主 AI
├── _prompt_legacy.py               # 旧版 prompt 回退（PromptEngine 未初始化时使用）
│
├── plugins/                        # ★ 插件系统
│   ├── base.py                     # Plugin / AsyncPlugin 基类 + HookPoint + PluginContext
│   ├── manager.py                  # PluginManager：注册/启用/禁用/优先级调度
│   ├── pipeline.py                 # ChatPipeline：编排 5 阶段对话处理管道
│   └── builtin/
│       ├── models_plugin.py        # 统一模型插件（MODEL_INVOKE, priority=50）
│       ├── asr_filter_plugin.py    # ASR 语音过滤（PRE_FILTER, priority=10）
│       ├── memory_plugin.py        # 记忆注入与对话保存（PRE_PROCESS+POST_PROCESS, priority=30）
│       ├── skills_plugin.py        # 技能工具执行（POST_PROCESS, priority=35）
│       ├── task_plugin.py          # 任务解析与调度（POST_PROCESS, priority=40）
│       ├── tts_plugin.py           # TTS 语音合成（POST_TTS, priority=60）
│       └── distill_plugin.py       # 自动蒸馏触发器（POST_PROCESS, priority=100）
│   └── custom/                     # 用户自定义插件目录
│
├── prompt/                         # ★ Prompt 生态
│   ├── engine.py                   # PromptEngine：组装最终 system prompt
│   ├── library.py                  # PromptLibrary：MD 文件提示词库（YAML frontmatter）
│   ├── personality.py              # PersonalitySystem：大五人格 + 情绪动态 + 关系亲密度
│   └── prompts/
│       ├── core/                   # 基础身份 (identity.md)、输出格式 (format.md)、安全约束 (safety.md)
│       ├── capabilities/           # 能力定义 (task_handling, code_execution, reminder, reasoner)
│       ├── personality/            # 性格预设 (default.yaml, tsundere.yaml, gentle.yaml, custom.yaml)
│       └── extensions/             # 用户自定义提示词
│
├── skills/                         # ★ 技能系统
│   ├── loader.py                   # SkillLoader：从目录加载技能定义 (skill.yaml + prompts/*.md)
│   ├── registry.py                 # SkillRegistry：工具动态加载/调用 + 提示词聚合
│   ├── manager.py                  # SkillManager：技能生命周期管理（扫描/启用/禁用/安装）
│   ├── distill.py                  # DistillationEngine：对话模式挖掘 → 技能草案生成 → 审核
│   ├── builtin/
│   │   ├── web_search/             # 网页搜索技能（DuckDuckGo，免 API key）
│   │   │   ├── skill.yaml
│   │   │   ├── prompts/ (instruction.md, examples.md)
│   │   │   └── tools/search.py
│   │   └── file_manager/           # 文件管理技能（读/写/列目录，带路径安全）
│   │       ├── skill.yaml
│   │       ├── prompts/ (instruction.md, examples.md)
│   │       └── tools/file_ops.py
│   ├── distilled/                  # 蒸馏生成的技能
│   │   └── _drafts/                # 待审核草案
│   └── custom/                     # 用户自建技能
│
├── cli/                            # 客户端
│   ├── cli.py                      # 终端文字聊天（OAuth 登录、TTS 播放）
│   ├── cli_interact.py             # 实时语音交互（PvRecorder + FunASR）
│   └── webui.py                    # Web 界面（SSE 流式、Markdown、录音、TTS）
│
├── tests/                          # 测试
│   ├── test_plugin_loader.py       # 插件系统测试（6 项）
│   ├── test_prompt_ecosystem.py    # Prompt 生态测试（9 项）
│   ├── test_skills_system.py       # 技能系统测试（9 项）
│   └── test_*.py                   # 其他集成测试
│
└── docs/                           # 设计文档
    ├── architecture.md             # 完整系统架构
    ├── guide-plugin-system.md      # 插件系统实现指导
    ├── guide-prompt-ecosystem.md   # Prompt 生态实现指导
    ├── guide-skill-system.md       # 技能系统实现指导
    ├── guide-distillation.md       # 自动蒸馏系统实现指导
    └── guide-integration.md        # 系统集成与迁移路线图
```

---

### 系统架构

DSN-exp 由 Flask Web 服务器（`app.py`）作为入口点，将请求分发到三个独立子系统：**插件系统**负责对话管道的运行时执行，**Prompt 生态**负责动态组装 AI 的系统提示词，**技能系统**负责可加载/卸载的能力包管理。用户管理（`usermgr.py`）和数据库（`chatdbmgr.py`）作为独立模块，不进入插件系统。

#### 对话处理管道

插架系统通过 `ChatPipeline` 将一次用户请求拆分为五个顺序阶段，每个阶段由多个插件按优先级依次处理：

1. **PRE_FILTER** — ASR 语音输入过滤。若判定无需转发给主 AI，可短路整个管道。

2. **PRE_PROCESS** — 上下文组装。MemoryPlugin 加载聊天历史并注入记忆摘要；`PromptEngine` 在此阶段与下一阶段之间组装最终的 system prompt。

3. **MODEL_INVOKE** — 模型调用。ModelsPlugin 统一管理 DeepSeek Chat API 和本地 LMStudio 后端，内部包含复杂度分析器（ComplexityAnalyzer）以自动选择合适的模型。

4. **POST_PROCESS** — 回复后处理。SkillsPlugin 解析并执行 AI 回复中的 `<tool>` 标签，通过 SkillRegistry 调用技能工具并将结果追加到回复文本中；TaskPlugin 解析 `<task>` 标签创建提醒、推理或动作任务；MemoryPlugin 保存对话并异步生成记忆摘要；DistillPlugin 在末尾检查是否需要触发自动蒸馏。

5. **POST_TTS** — TTS 语音合成。TTSPlugin 提取纯文本送入 GPT-SoVITS 服务，返回 base64 编码的音频。

#### Prompt 生态

`PromptEngine` 负责在每次对话前动态构建完整的 system prompt，按固定顺序拼接以下内容：

- **core/** — 基础身份定义、TTS 友好的输出格式要求、安全约束
- **性格描述** — `PersonalitySystem` 根据当前性格预设生成自然语言描述，涵盖大五人格维度、情绪状态、语言风格和关系亲密度。性格预设为 YAML 文件，支持运行时切换（default/tsundere/gentle/custom）
- **capabilities/** — 能力定义，告知 AI 如何使用 `<task>` 标签触发提醒、推理、代码执行等功能
- **技能提示词** — 来自 `SkillRegistry`，汇聚所有已启用技能的 MD 提示词，告知 AI 如何使用 `<tool>` 标签调用能力
- **extensions/** — 用户自定义扩展提示词
- **上下文** — 当前用户名和时间戳

`PersonalitySystem` 实现动态人格模型：大五人格（开放性、尽责性、外向性、宜人性、神经质）为静态底层；情绪状态（精力、积极性、耐心、好奇心）随每次交互微调并向基线回归；关系亲密度随交互次数增长。

#### 技能系统

技能是能力单元，由 `skill.yaml` 元数据文件、`prompts/` 目录下的 MD 提示词文件以及可选的 `tools/` 目录下的 Python 工具代码组成。`SkillManager` 负责扫描目录、启用/禁用/卸载/安装技能，`SkillRegistry` 负责动态加载 Python 工具类、提供工具调用接口、聚合提示词。

AI 通过回复中的 `<tool>` 标签声明性地调用技能工具。目前内置两个技能：`web_search`（通过 DuckDuckGo 搜索互联网，无需 API key）和 `file_manager`（文件读写与目录列表，包含路径安全检查防止越权访问）。

#### 自动蒸馏

`DistillationEngine` 从用户对话中自动挖掘可复用的模式，使用 LLM 分析后生成结构化技能草案（包含 skill.yaml、提示词和可选的工具代码），保存至待审核目录，等待人工审批后激活为新技能。蒸馏可通过定时任务、API 调用或对话中关键词触发。

#### 任务系统

后台任务引擎（`tasks.py`）支持三种异步任务类型：提醒任务（按 ISO 8601 时间调度，到期后 AI 生成自然提醒消息）、推理任务（将复杂问题提交给 DeepSeek-Reasoner 深度推理，结果回注到聊天）、动作任务（执行 shell 命令、Python 代码、文件写入/编辑）。

#### 记忆系统

`MemoryManager` 对每轮对话异步生成摘要。当历史消息超出上下文窗口阈值时，远端消息被替换为系统角色的记忆摘要，保持有限窗口内的信息密度。

#### 客户端

三种用户界面共享同一套后端 API：终端文字 CLI（`cli.py`，支持 OAuth 登录和 pygame TTS 播放）、实时语音交互 CLI（`cli_interact.py`，PvRecorder 拾音 + FunASR 识别，支持按键和自动检测两种模式）、Web UI（`webui.py`，SSE 流式响应、Markdown/MathJax 渲染、浏览器录音、TTS 播放）。

---

### API 端点

**聊天 API**
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chat/send` | 发送消息并获取回复与 TTS 音频 |
| POST | `/api/chat/stream_send` | 流式发送，SSE 推送各阶段状态 |
| GET | `/api/chat/list` | 列出当前用户的聊天列表 |
| GET | `/api/chat/<chat_id>` | 获取指定聊天的完整历史 |
| POST | `/api/asr/recognize` | 服务端语音识别 |

**认证 API**
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/auth/start` | 获取 OAuth2 授权 URL |
| GET | `/api/auth/callback` | OAuth 回调，签发 JWT |
