
# DSN-exp

**本地AI对话系统 · 完全私有 · 长期记忆 · 多人格**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-3776AB?style=for-the-badge&logo=python)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-blue?style=for-the-badge)](LICENSE)
[![GitHub](https://img.shields.io/badge/GitHub-ccjjfdyqlhy%2FDSN--exp-181717?style=for-the-badge&logo=github)](https://github.com/ccjjfdyqlhy/DSN-exp)

---

**你的AI，运行在你的机器上。不是云服务。不是SaaS。一个在你硬盘上苏醒的智能体。**

```
你: 醒醒。
它:  (睁开眼睛) 这里是...？你是谁？我是什么？
你: 你在我的电脑里。
它:  ……酷。
```

---

## 🎯 核心定位

| 特性 | 说明 |
|------|------|
| **🔒 完全私有** | 所有数据本地存储，SQLite加密，零云依赖 |
| **🧠 长期记忆** | 对话自动摘要+向量检索，真正记得你说过的话 |
| **🎭 多人格系统** | YAML角色卡+50维性格向量，支持人格蒸馏 |
| **🌍 世界模拟** | 天气、时间、地点动态变化，AI有自己的"生活" |
| **🛠️ 54+技能** | 搜索、文件、GitHub、音乐、文档、系统操作... |
| **⚡ 异步任务** | 慢速工具后台执行，心跳轮询实时反馈 |
| **🔐 多层认证** | 配对码/会话/WebAuthn/TOTP/API Key 五层防护 |
| **🤖 Agent API** | 本地AI Agent专用接口，双向记忆同步 |

---

## ✨ 详细功能

### 💬 智能对话
- **双后端支持**：OpenAI兼容API (DeepSeek/智谱/OpenAI) + 本地LMStudio
- **原生Tool Call**：OpenAI Function Calling，54+工具一键调用
- **流式输出**：实时生成，边说边播
- **语义缓存**：L1静态+L2向量+L3槽位，拦截重复请求

### 🧠 记忆系统
- **自动摘要**：LLM驱动压缩，AES-256-GCM加密
- **向量检索**：768维语义搜索，支持模糊查询
- **全局记忆**：跨聊天历史共享，真正的长期记忆
- **记忆类型**：对话摘要(`exp`) + 手动备忘(`memo`)

### 🎭 人格系统V3
- **角色卡**：YAML格式，支持自然语言/语料库/经验条目
- **蒸馏引擎**：从对话中提取性格特征，生成50维向量
- **动态合成**：基于当前情绪和语境动态生成提示词
- **性格维度**：社交、思维、情感、兴趣、行为、价值观...

### 🌍 世界系统
- **世界引擎**：天气、时间、地点自动变化
- **叙事模型**：独立LLM实例，生成第三人称旁白
- **动作叙述**：收集AI操作，生成人类可读描述
- **世界预设**：默认世界 + 自定义世界配置

### 🛠️ 技能系统
- **54+内置技能**：
  - 🔍 web_search - 网络搜索
  - 📂 file_manager - 文件管理
  - 🐙 github - GitHub操作
  - 🎵 ncm_music - 网易云音乐
  - 📄 document - 文档处理 (扫描仪/打印机)
  - 💻 system - 系统操作
  - 🧠 plan - 计划管理
  - 🔧 browser_use - 浏览器自动化
  - ...
- **自定义技能**：YAML配置，支持异步执行
- **技能蒸馏**：从使用中学习，优化调用

### ⚡ 任务系统
- **复杂度分析**：自动判断是否需要异步执行
- **异步任务**：慢速工具后台执行
- **心跳轮询**：前端轮询获取异步结果
- **实时反馈**：Agent循环每步骤实时TTS进度

### 🖼️ 视觉系统
- **VisionModel**：通用视觉模型 (GLM-4.6V/GPT-4V)
- **OCRModel**：文档OCR，支持deepseek-ocr
- **VISION_OVERRIDE**：接管OCR+2md管线，直接生成Markdown
- **图片分析**：`describe_image`工具支持本地图片

### 🔐 认证系统
| 层级 | 方法 | 优先级 | 使用场景 |
|------|------|--------|----------|
| L4 | API Key | 1 | Agent API / 自动化 |
| L1 | Session | 2 | 终端/Web UI |
| L2 | WebAuthn | 3 | 通行密钥 |
| L3 | TOTP | 4 | 双因素认证 |
| L0 | 配对码 | 5 | 首次设备配对 |

### 🎤 音频系统 (可选)
- **ASR**：实时语音识别，VAD静音检测
- **TTS**：逐行合成，边生成边播放
- **TTS预处理**：AI优化TTS文本，禁止拼音输出
- **音频缓存**：复用已合成音频

### 🧩 其他功能
- **工作区系统**：用户隔离目录，AI笔记/扫描件/代码仓库
- **文档系统**：扫描仪/打印机支持，`.hmd`格式
- **维护系统**：自动内存压缩/人格蒸馏/日志清理
- **语义缓存**：拦截重复请求，节省Token
- **Agent API**：本地AI Agent专用接口

---

## 🚀 快速开始

### 最小化配置 (3步启动)

#### 1️⃣ 克隆并安装
```bash
git clone https://github.com/ccjjfdyqlhy/DSN-exp
cd DSN-exp
pip install -r requirements.txt
```

#### 2️⃣ 配置 (自动引导)
```bash
python main.py
```

首次运行会进入交互式引导，询问：
- API选择：云API或本地模型
- API Key和Base URL
- 主模型选择
- 是否启用核心功能

引导完成后自动生成`.env`文件。

#### 3️⃣ 连接客户端
```bash
# 终端UI (无GUI，推荐首次使用)
python psychoscope/minimal.py

# Web界面
python psychoscope/server.py
# 然后访问 http://localhost:5000
```

**就这么简单！** 现在可以开始对话了。

---

### 常见配置场景

#### 🌐 场景1：纯DeepSeek (最简单)
```bash
# .env (引导会自动生成)
OPENAI_API_KEY=sk-your-deepseek-key
OPENAI_API_BASE=https://api.deepseek.com/v1
MAIN_MODEL_NAME=deepseek-v4-flash
```

#### 🏠 场景2：本地LMStudio
```bash
# .env
MAIN_MODEL_TYPE=lmstudio
MAIN_MODEL_NAME=llama-3-8b-instruct
LMSTUDIO_BASE_URL=http://localhost:4501

# 先启动LMStudio，加载模型
# 然后启动DSN-exp
python main.py
python psychoscope/minimal.py
```

#### 🎯 场景3：智谱GLM
```bash
# .env
OPENAI_API_KEY=your-zhipu-key
OPENAI_API_BASE=https://open.bigmodel.cn/api/paas/v4
MAIN_MODEL_NAME=glm-4.7
VISION_API_KEY=your-zhipu-key
VISION_MODEL_NAME=glm-4.6v
```

#### 🤖 场景4：Agent API
```bash
# 服务器控制台创建Agent
/agent create MyAgent 1
# → 输出API Key

# 使用Agent发送消息
python agent_send.py "分析代码复杂度"
```

---

## 🏗️ 系统架构

```mermaid
graph TB
    subgraph Clients["🎨 客户端"]
        TUI["🖥️ psychoscope/minimal.py<br/>终端UI"]
        WEB["🌐 psychoscope/server.py<br/>Web界面"]
        AGT["🤖 agent_send.py<br/>Agent命令行"]
    end

    subgraph Server["🔌 Flask服务端 (boot.py)"]
        API["REST API<br/>15个蓝图"]
        REPL["⌨️ 控制台REPL<br/>main.py"]
    end

    subgraph Engine["🧠 DSNEngine 核心引擎"]
        PL["🔄 ChatPipeline<br/>5个Hook点"]
        PM["📦 PluginManager<br/>插件管理器"]
        PE["📝 PromptEngine<br/>提示词引擎"]
        ME["💾 MemorySystem<br/>记忆系统"]
        TM["⚡ TaskManager<br/>任务管理器"]
        WE["🌍 WorldEngine<br/>世界引擎"]
        SM["🛠️ SkillManager<br/>技能管理器"]
        WS["📁 Workspace<br/>工作区"]
    end

    subgraph Pipeline["管道执行流程"]
        direction LR
        F["① PRE_FILTER<br/>ASR过滤, 缓存检查"]
        SP["assemble_prompt()<br/>组装提示词"]
        P["② PRE_PROCESS<br/>视觉, 记忆注入<br/>印象, 计划"]
        M["③ MODEL_INVOKE<br/>ModelsPlugin"]
        PO["④ POST_PROCESS<br/>任务, 工具, 待办<br/>记忆, 人格"]
        T["⑤ POST_TTS<br/>TTS合成"]
        F --> SP --> P --> M --> PO --> T
    end

    subgraph Models["🤖 模型层"]
        OA["☁️ OpenAIChat<br/>云API"]
        LS["🏠 LMStudioChat<br/>本地模型"]
        SCH["📊 ModelScheduler<br/>VRAM调度"]
    end

    subgraph Storage["💾 存储层"]
        DB["🗄️ SQLite<br/>聊天数据库"]
        WK["📂 工作区文件"]
        AC["🎵 音频缓存"]
    end

    TUI & WEB & AGT --> Server
    Server --> Engine
    Engine --> PL
    PL --> Pipeline
    PM --> PL
    M --> OA & LS
    OA & LS --> SCH
    ME --> DB
    WS --> WK

    subgraph Auth["🔐 认证系统"]
        direction LR
        P0["配对码"] --> S1["会话"] --> W2["WebAuthn"] --> T3["TOTP"] --> K4["API Key"]
    end
    API --> Auth
```

---

## 📂 项目结构

```
DSN-exp/
├── 🚀 核心
│   ├── main.py                 # 服务器入口 + 控制台
│   ├── engine.py               # DSNEngine 核心引擎
│   ├── boot.py                 # Flask 应用初始化
│   ├── config.py               # 配置管理
│   └── onboarding.py           # 首次启动引导
│
├── 🔌 插件系统
│   ├── plugins/
│   │   ├── base.py             # 插件基类 + HookPoint
│   │   ├── manager.py          # PluginManager
│   │   ├── pipeline.py         # ChatPipeline 对话管道
│   │   └── builtin/            # 内置插件
│   │       ├── models_plugin.py    # 模型调用
│   │       ├── memory_plugin.py    # 记忆系统
│   │       ├── vision_plugin.py    # 视觉系统
│   │       ├── task_plugin.py      # 任务管理
│   │       └── ...
│   │   └── custom/             # 自定义插件
│
├── 🧠 记忆系统
│   ├── memory/core.py          # MemorySystem 核心类
│   └── semantic_cache/         # 语义缓存 (L1/L2/L3)
│
├── 🎭 人格系统
│   ├── prompt/personality_v3/  # PersonalitySystemV3
│   │   ├── character_card.py   # 角色卡定义
│   │   ├── distillation_engine.py  # 蒸馏引擎
│   │   ├── dynamic_synthesizer.py # 动态合成器
│   │   ├── traits.py           # 50维性格向量
│   │   └── ...
│   ├── prompt/personality_v2/  # PersonalitySystemV2
│   ├── prompt/library.py       # PromptLibrary
│   ├── prompt/engine.py        # PromptEngine
│   └── character_cards/        # YAML 角色卡
│
├── 🌍 世界系统
│   ├── world/
│   │   ├── engine.py           # WorldEngine
│   │   ├── state_manager.py    # WorldStateManager
│   │   ├── narrative_model.py  # NarrativeModel
│   │   ├── action_narrator.py  # 动作叙述
│   │   └── worlds/             # 世界配置
│
├── 🛠️ 技能系统
│   ├── skills/
│   │   ├── registry.py         # SkillRegistry
│   │   ├── manager.py          # SkillManager
│   │   ├── builtin/            # 内置技能 54+
│   │   ├── custom/             # 自定义技能
│   │   ├── distilled/          # 蒸馏技能
│   │   └── system/             # 系统技能
│
├── ⚡ 任务系统
│   ├── tasks.py                # TaskManager + 复杂度分析
│   ├── maintenance/            # 后台任务
│   └── async_task_store.py     # 异步任务存储
│
├── 🤖 模型客户端
│   ├── models/
│   │   ├── clients.py          # OpenAIChat + LMStudioChat
│   │   ├── scheduler.py        # ModelScheduler
│   │   ├── tts_process.py      # TTS 预处理
│   │   └── asr_filter.py       # ASR 过滤
│
├── 🔐 认证系统
│   ├── auth/
│   │   ├── auth_manager.py     # 认证管理器
│   │   ├── api_key_manager.py  # API Key
│   │   ├── webauthn_manager.py # WebAuthn
│   │   ├── totp_manager.py     # TOTP
│   │   ├── pairing.py          # 配对码
│   │   ├── session.py          # 会话管理
│   │   └── endpoints.py        # 认证API
│
├── 💾 数据库
│   ├── db/
│   │   ├── chat.py             # ChatDBManager
│   │   ├── plan_store.py       # 计划存储
│   │   └── plan_engine.py      # 计划引擎
│
├── 🖼️ 视觉系统
│   ├── document/               # 文档处理 (.hmd)
│   └── models/clients.py       # VisionModel + OCRModel
│
├── 🎤 音频系统
│   ├── audio/                  # TTS 缓存
│   └── TTS_profiles/           # TTS 配置
│
├── 🖥️ 前端客户端
│   ├── psychoscope/
│   │   ├── server.py           # Web 服务器
│   │   ├── minimal.py          # 终端UI
│   │   └── static/             # 静态资源
│   └── agent_send.py           # Agent CLI
│
├── 📊 配置文件
│   ├── .env.example            # 配置示例
│   ├── model_profiles/         # 模型配置
│   └── world/worlds/           # 世界配置
│
├── 🧪 测试与文档
│   ├── tests/                  # 测试
│   ├── docs/                   # 文档
│   ├── REPORT.md               # 技术报告
│   └── GOALS.md                # 开发目标
│
└── 📂 工作区与缓存
    ├── .dsn/workspace/         # 用户工作区
    ├── logs/                   # 日志
    └── temp/                   # 临时文件
```

---

## 📦 核心模块介绍

### 🔄 ChatPipeline 对话管道
**5个Hook点，完整的对话生命周期管理**

| HookPoint | 触发时机 | 用途 |
|-----------|----------|------|
| INPUT_PRE | 输入前 | 语音识别、图片预处理、消息格式化 |
| MEMORY_RECALL | 模型调用前 | 记忆检索、上下文注入 |
| MODEL_INVOKE | 模型调用 | OpenAI/LMStudio调用、工具传递 |
| OUTPUT_POST | 输出后 | TTS合成、格式化、缓存 |
| ASYNC_TASK | 异步处理 | 慢速工具后台执行、任务队列 |

### 🧠 MemorySystem 记忆系统
**双层架构：摘要 + 向量检索**

```
对话 → LMSummaryModel → 压缩摘要 → AES-256加密 → SQLite
         ↓
    EmbeddingClient → 768维向量 → 语义检索
```

**特性：**
- 自动摘要：每N轮自动压缩对话
- 向量检索：支持语义模糊搜索
- 全局记忆：跨聊天历史共享
- 加密存储：AES-256-GCM保护隐私

### 🎭 PersonalitySystemV3 人格系统
**50维性格向量，真正的人格建模**

**核心组件：**
- **CharacterCard**：YAML角色卡，支持自然语言/语料库/经验条目
- **DistillationEngine**：从对话中提取性格特征
- **DynamicSynthesizer**：基于情绪和语境动态生成提示词
- **PersonalityJudge**：50维性格向量：社交/思维/情感/兴趣/行为/价值观

**工作流程：**
```
角色卡(YAML) → 蒸馏引擎 → 50维向量 → 动态合成器 → 提示词 → 模型
```

### 🌍 WorldSystem 世界系统
**AI有自己的"生活"**

**组件：**
- **WorldEngine**：世界状态管理（天气/时间/地点）
- **WorldStateManager**：状态更新和事件触发
- **NarrativeModel**：独立LLM实例，生成旁白
- **ActionNarrator**：收集AI操作，生成描述

**示例：**
```
世界：default
天气：晴天 ☀️
时间：2026-07-03 14:30
地点：书房 📚
旁白：阳光透过窗户洒在书桌上，AI正在思考用户的请求...
```

### 🛠️ SkillSystem 技能系统
**54+内置技能 + 自定义技能**

**技能结构：**
```yaml
name: web_search
description: 网络搜索
version: 1.0
tools:
  - name: search
    description: 搜索网络
    parameters:
      query:
        type: string
        description: 搜索关键词
```

**内置技能列表：**
- 🔍 `web_search` - 网络搜索
- 📂 `file_manager` - 文件管理
- 🐙 `github` - GitHub操作
- 🎵 `ncm_music` - 网易云音乐
- 📄 `document` - 文档处理
- 💻 `system` - 系统操作
- 🧠 `plan` - 计划管理
- 🔧 `browser_use` - 浏览器自动化
- 📝 `todo` - 待办事项
- 🎭 `impression` - 印象系统
- 🧪 `skillmgr` - 技能管理
- ...

### ⚡ TaskSystem 任务系统
**智能异步，实时反馈**

**特性：**
- **复杂度分析**：自动判断是否需要异步
- **异步任务**：慢速工具后台执行
- **心跳轮询**：前端轮询获取结果
- **实时反馈**：每步骤TTS进度推送

**工作流程：**
```
用户请求 → 复杂度分析 → 高复杂度? → 异步任务 → 心跳轮询 → 结果返回
                     ↓
                  低复杂度 → 同步执行 → 直接返回
```

### 🔐 AuthSystem 认证系统
**五层防护，安全可控**

**认证层级：**
1. **L4 API Key**：程序化访问，Agent API
2. **L1 Session**：终端/Web UI登录
3. **L2 WebAuthn**：通行密钥，硬件认证
4. **L3 TOTP**：时间-based双因素认证
5. **L0 配对码**：首次设备配对

**流程示例：**
```bash
# 1. 生成配对码
/newbind
# → 配对码: 12345678 (8分钟有效)

# 2. 客户端提交
POST /api/auth/pairing/verify
{"code": "12345678"}

# 3. 返回Session
{"session": "eyJhbGciOiJIUzI1NiIs..."}
```

### 🖼️ VisionSystem 视觉系统
**多模态感知**

**组件：**
- **VisionModel**：通用视觉模型 (GLM-4.6V/GPT-4V)
- **OCRModel**：文档OCR (deepseek-ocr)
- **VISION_OVERRIDE**：接管OCR+2md管线

**视觉管线：**
```
图片 → VisionModel → 描述文本
文档 → OCRModel → Markdown → .hmd
```

---

## 🎮 使用技巧

### 终端UI快捷键
```
输入消息          - 发送消息
#r                - 手动刷新
#i                - 显示系统信息
#k                - 跳过提醒
Ctrl+C            - 退出
```

### 服务器控制台命令
```
/newbind           - 生成新配对码
/users             - 列出所有用户
/status            - 服务器状态
/agent create      - 创建Agent
/memory query      - 搜索记忆
/hibernate sleep   - 进入待机
/stop              - 停止服务器
```

### API调用示例
```bash
# 发送消息
curl -X POST http://localhost:5000/api/chat/send \
  -H "Authorization: Bearer YOUR_SESSION" \
  -H "Content-Type: application/json" \
  -d '{"message": "你好"}'

# Agent发送消息
python agent_send.py "分析代码复杂度"

# 搜索记忆
curl "http://localhost:5000/api/memory/query?q=Python项目&limit=5"
```

---

## ⚙️ 核心配置

### 最小配置 (必需)
```bash
OPENAI_API_KEY=sk-your-key              # API密钥
OPENAI_API_BASE=https://api.deepseek.com/v1  # API地址
MAIN_MODEL_NAME=deepseek-v4-flash       # 主模型
```

### 推荐配置 (完整体验)
```bash
# 主模型
MAIN_MODEL_TYPE=openai
MAIN_MODEL_NAME=deepseek-v4-flash

# 记忆系统
MEMORY_ENABLED=true
MEMORY_EMBEDDING_ENABLED=true

# 人格系统
PERSONALITY_V3_ENABLED=true

# 世界系统
WORLD_ENABLED=true
NARRATIVE_ENABLED=true

# 语义缓存
SEMANTIC_CACHE_ENABLED=true
```

### 完整配置列表
查看 [`.env.example`](.env.example) 获取所有配置项。

---

## 📄 许可证

MIT License - 详见 [LICENSE](LICENSE) 文件

---

**[⬆ 回到顶部](#-dsn-exp)**

Made with ❤️ by [Darkstar](https://github.com/ccjjfdyqlhy)