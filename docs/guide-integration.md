# 系统集成与迁移指导

> 来源: architecture.md §一 / §二 / §三 / §八 / §九 / §十 / §十一 / §十二
> 目标: 描述各子系统如何组装在一起，以及从当前 v3 到 v4 的迁移路线

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
│  │                      app.py (Flask, ~200 行)                 │   │
│  │  路由注册 · 认证中间件 · 构造 PluginContext · 调用 Pipeline   │   │
│  └─────────────────────────────────────────────────────────────┘   │
│       │              │              │              │                │
│       ▼              ▼              ▼              ▼                │
│  ┌─────────┐  ┌───────────┐  ┌──────────┐  ┌──────────────┐      │
│  │ usermgr │  │chatdbmgr  │  │  config  │  │   ASR 服务    │      │
│  │(OAuth2) │  │ (SQLite)  │  │ (.env)   │  │ (FunASR)     │      │
│  └─────────┘  └───────────┘  └──────────┘  └──────────────┘      │
│                                                                     │
│  ════════════════════ 三大独立子系统 ════════════════════          │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────┐     │
│  │                  插件系统 (plugins/)                       │     │
│  │  ChatPipeline: PRE_FILTER → PRE_PROCESS → MODEL_INVOKE    │     │
│  │              → POST_PROCESS → POST_TTS                     │     │
│  └───────────────────────────────────────────────────────────┘     │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────┐     │
│  │              Prompt 生态 (prompt/)                          │     │
│  │  PromptEngine ← PromptLibrary + PersonalitySystem          │     │
│  │                     + SkillRegistry (技能提示词)            │     │
│  └───────────────────────────────────────────────────────────┘     │
│                                                                     │
│  ┌───────────────────────────────────────────────────────────┐     │
│  │              技能系统 (skills/)                             │     │
│  │  SkillManager → SkillRegistry → 工具调用 + 提示词注入      │     │
│  │  DistillationEngine → 自动蒸馏 → 技能草案 → 审核          │     │
│  └───────────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 二、三大子系统关系

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

## 三、完整 API 端点总览

### 聊天 API (现有，保留)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chat/send` | 发送消息 |
| POST | `/api/chat/stream_send` | 流式发送 |
| GET | `/api/chat/list` | 聊天列表 |
| GET | `/api/chat/<id>` | 聊天历史 |
| POST | `/api/asr/recognize` | ASR 识别 |

### Prompt 管理 API (新增)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/prompts/list` | 列出所有提示词 |
| POST | `/api/prompts/<id>/toggle` | 启用/禁用 |
| POST | `/api/prompts/reload` | 热重载全部 |
| POST | `/api/prompts/upload` | 上传新提示词 |

### 性格管理 API (新增)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/personality/list` | 列出性格预设 |
| POST | `/api/personality/switch` | 切换性格 |
| GET | `/api/personality/current` | 当前性格状态 |

### 技能管理 API (新增)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/skills/list` | 列出所有技能 |
| GET | `/api/skills/<name>` | 技能详情 |
| POST | `/api/skills/<name>/enable` | 启用技能 |
| POST | `/api/skills/<name>/disable` | 禁用技能 |
| DELETE | `/api/skills/<name>` | 卸载技能 |
| POST | `/api/skills/install` | 安装新技能 |

### 蒸馏 API (新增)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/skills/distill` | 手动触发蒸馏 |
| GET | `/api/skills/distill/drafts` | 列出待审核草案 |
| GET | `/api/skills/distill/drafts/<name>` | 草案详情 |
| POST | `/api/skills/distill/drafts/<name>/approve` | 批准草案 |
| POST | `/api/skills/distill/drafts/<name>/reject` | 拒绝草案 |
| GET | `/api/skills/distill/history` | 蒸馏历史 |

### 插件管理 API (新增)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/plugins/list` | 列出所有插件 |
| POST | `/api/plugins/<name>/enable` | 启用插件 |
| POST | `/api/plugins/<name>/disable` | 禁用插件 |

---

## 四、一次完整交互的数据流

以"帮我搜索 Python 最新版本"为例：

```
用户消息
    │
    ▼
app.py → 认证 → 构造 PluginContext
    │
    ▼
ChatPipeline.process(ctx)
    │
    ├── 1. PromptEngine.build_system_prompt(user_info)
    │       ├── core/identity.md + format.md + safety.md
    │       ├── PersonalitySystem.generate_personality_prompt()
    │       ├── capabilities/task_handling.md + code_execution.md + ...
    │       ├── SkillRegistry.get_all_skill_prompts()
    │       │      └── web_search 的 instruction.md + examples.md
    │       └── 用户上下文
    │
    ├── 2. PRE_FILTER: asr_filter_plugin → 非语音，放行
    │
    ├── 3. PRE_PROCESS: memory_plugin → 加载历史 + 注入记忆摘要
    │
    ├── 4. MODEL_INVOKE: models_plugin
    │       → 复杂度分析 (score=0.2, 用 deepseek-chat)
    │       → 调用 LLM → AI 回复:
    │         "好的，我来帮你搜索。
    │          <tool>{"skill":"web_search","tool":"search",
    │                 "params":{"query":"Python latest version"}}</tool>"
    │
    ├── 5. POST_PROCESS:
    │       ├── task_plugin: 解析 <tool> 标签
    │       │   → SkillRegistry.call_tool("web_search", "search", {...})
    │       │   → 工具返回: {results: [{title: "Python 3.13...", ...}]}
    │       │   → 将结果追加到 ctx.reply
    │       └── memory_plugin: 保存对话 + 异步摘要
    │
    ├── 6. POST_TTS: tts_plugin
    │       → 提取纯文本 → TTS 合成 → ctx.audio
    │
    └── 7. PersonalitySystem.on_interaction()
            → curiosity +0.03, intimacy +0.02
    │
    ▼
返回 {
    "reply": "好的，我来帮你搜索。Python 最新版本是 3.13...",
    "audio": "<base64>",
    "chat_id": 42,
    "model_type": "deepseek"
}
```

---

## 五、迁移路线图

### Phase 1: 基础设施 (不改现有代码，纯新增)

**产出:** 新目录和新文件，app.py 照常运行

- [ ] 创建 `plugins/` 目录结构 + `base.py` `manager.py` `pipeline.py`
- [ ] 创建 `prompt/` 目录结构 + `engine.py` `library.py` `personality.py`
- [ ] 创建 `skills/` 目录结构 + `loader.py` `registry.py` `manager.py`
- [ ] 拆分 `DEFAULT_SYSTEM_PROMPT` 为 `prompts/core/*.md` 和 `prompts/capabilities/*.md`
- [ ] 编写默认性格预设 `prompts/personality/default.yaml`
- [ ] 编写单元测试

**验证:** 所有新模块可独立 import，不影响现有功能

### Phase 2: 内置插件迁移

**产出:** 现有功能以插件形式重新实现，但 app.py 仍用旧代码

- [ ] `plugins/builtin/models_plugin.py` — 封装 DeepSeekChat + LMStudioChat + ComplexityAnalyzer
- [ ] `plugins/builtin/asr_filter_plugin.py` — 封装 LMFilterModel
- [ ] `plugins/builtin/memory_plugin.py` — 封装 MemoryManager
- [ ] `plugins/builtin/task_plugin.py` — 封装 parse_task_instructions + task_manager
- [ ] `plugins/builtin/tts_plugin.py` — 封装 VocalExp

**验证:** 每个插件单独用 mock ctx 测试

### Phase 3: 技能系统

**产出:** 技能加载/注册/调用能力就绪

- [ ] `SkillLoader` + `SkillRegistry` + `SkillManager`
- [ ] 内置技能示例: `web_search` (含工具代码)
- [ ] 内置技能示例: `file_manager` (含工具代码)
- [ ] 技能管理 API 端点
- [ ] `task_plugin` 集成技能工具调用

**验证:** 加载 web_search 技能后，AI 回复中能正确调用搜索工具

### Phase 4: 自动蒸馏

**产出:** 技能自进化能力就绪

- [ ] `DistillationEngine` 核心流程
- [ ] 模式挖掘 + 草案生成 prompt 工程
- [ ] 草案保存 + 审核流程
- [ ] 蒸馏 API 端点
- [ ] 定时蒸馏任务

**验证:** 积累足够对话后，系统能自动发现模式并生成草案

### Phase 5: app.py 瘦身

**产出:** app.py 从 ~1060 行缩减到 ~200 行

- [ ] `chat_send()` 改用 `ChatPipeline.process()`
- [ ] `chat_stream_send()` 改用 `ChatPipeline.process()`
- [ ] 删除硬编码逻辑（`create_chat_client`, `parse_task_instructions` 等）
- [ ] 添加所有管理 API (prompts, personality, skills, plugins, distill)
- [ ] 在 `__init__` 或 `before_first_request` 中初始化各个管理器

**验证:** 所有现有功能 + 新功能端到端正常

### Phase 6: 扩展生态

- [ ] 编写插件/技能开发者指南
- [ ] 更多性格预设 (tsundere, gentle, custom)
- [ ] 更多内置技能
- [ ] 技能迭代优化（已激活技能的持续蒸馏）
- [ ] 考虑技能分享/导入机制

---

## 六、新旧对比

| 维度 | v3 (当前) | v4 (目标) |
|------|-----------|-----------|
| **System Prompt** | 单字符串硬编码 | MD 文件库 + 性格 + 技能 动态组装 |
| **性格** | 无 | 大五人格 + 情绪 + 关系 + 预设切换 |
| **能力扩展** | 改 prompt.py | 写 MD 文件丢进 prompts/ 或加载技能 |
| **技能** | 无 | MD 提示词 + Python 工具 的能力包 |
| **自进化** | 无 | 自动蒸馏对话 → 生成技能草案 → 人工审核 |
| **模型管理** | 分散在 models.py + app.py | 统一 models_plugin |
| **加新能力** | 改核心代码 | 写技能 / 写插件 / 写 MD |
| **关闭能力** | 改代码 | API toggle / disable |
| **app.py** | ~1060 行 | ~200 行 |
| **可扩展性** | 低 | 高 (插件 + 技能 + 提示词 三层扩展) |

---

## 七、目录结构总览 (目标)

```
DSN-exp/
├── app.py                      # Flask 入口 (~200 行，纯胶水)
├── config.py                   # 从 .env 加载
├── .env.example                # 环境变量模板
├── usermgr.py                  # 用户认证 (独立)
├── chatdbmgr.py                # 数据库管理 (独立)
│
├── models.py                   # 底层 LLM 客户端
├── memory.py                   # 底层记忆引擎
├── tasks.py                    # 底层任务引擎
├── vocal_infer.py              # 底层 TTS 客户端
├── ASR_filter.py               # 底层过滤引擎
│
├── prompt/                     # ★ Prompt 生态
│   ├── engine.py
│   ├── library.py
│   ├── personality.py
│   └── prompts/
│       ├── core/               # identity.md, format.md, safety.md
│       ├── capabilities/       # task_handling.md, code_execution.md, ...
│       ├── personality/        # default.yaml, tsundere.yaml, ...
│       └── extensions/
│
├── skills/                     # ★ 技能系统
│   ├── loader.py
│   ├── registry.py
│   ├── manager.py
│   ├── distill.py
│   ├── builtin/                # web_search/, file_manager/
│   ├── distilled/              # 蒸馏生成的技能
│   │   └── _drafts/            # 待审核草案
│   └── custom/                 # 用户自建技能
│
├── plugins/                    # ★ 插件系统
│   ├── base.py
│   ├── manager.py
│   ├── pipeline.py
│   ├── builtin/                # models_plugin, asr_filter_plugin, ...
│   └── custom/
│
└── cli/                        # 客户端
    ├── cli.py
    ├── cli_interact.py
    └── webui.py
```

---

## 八、关键设计决策

1. **插件不负责认证** — usermgr.py 作为独立模块，在 Flask 中间件层处理
2. **模型调用是唯一的大插件** — 避免多个模块各自创建 LLM 客户端，统一管理
3. **prompt 和 skills 是独立子系统** — 不和插件系统耦合，有自己的生命周期
4. **蒸馏是可选的** — 即使不开启蒸馏，技能系统仍然可手动创建技能
5. **app.py 只做胶水** — 不包含任何业务逻辑，只负责路由注册、认证、构造 Context、调用 Pipeline
