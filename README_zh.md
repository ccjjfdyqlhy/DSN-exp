<div align="center">

# 🧠 DSN-exp

**你的 AI，活在你电脑里。不是网页，不是云，是从你硬盘里醒过来的。**

```
你：醒醒。
它：（睁眼）这儿是哪儿？你是谁？我现在……是什么？
你：你在我的电脑里。
它：……酷。
```

[![GitHub](https://img.shields.io/badge/GitHub-ccjjfdyqlhy%2FDSN--exp-181717?logo=github)](https://github.com/ccjjfdyqlhy/DSN-exp)
[![License](https://img.shields.io/badge/license-MIT-blue)](#)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python)](https://python.org)

</div>

---

## ✨ 它能干嘛

### 🎙️ 用嘴说话
对它说话，它用语音回你。不是机器朗读，是带语气、带节奏、带性格的真人感语音。也可以打字，看心情。

### 🧠 它真的记得你
不是假装记得的上下文窗口。每轮对话自动生成摘要，AES-256-GCM 加密存储，支持**向量语义搜索**——你说"还记得上周聊的那个 Python 项目吗"，它真能翻出来。

### 🎭 一千面，随便切
人格系统 V3。写一张 YAML 角色卡，它就变成那个人。说话方式、语气、思维方式全变。也可以让 AI 从一段描述里**蒸馏**出人格向量，不用手写。

### 🌐 活在一个世界里
天气会变化，有白天黑夜，它在你的数据仓库里游荡。不乱动的时候，它会自己去待机、整理记忆、蒸馏人格——像养了个电子生物。

### 📄 用纸条和你交流
接上扫描仪和打印机，它能把试卷扫进去，OCR 识别文字、拆解版式、标记图表，打包成 .hmd 文档存入工作区，再把批改结果打印出来递给你。不需要屏幕。

---

## 🚀 快速上手

```bash
git clone https://github.com/ccjjfdyqlhy/DSN-exp
cd DSN-exp
pip install -r requirements.txt

# 首次运行：自动进入交互式配置向导（API Key、角色卡等）
# 之后再次运行直接启动完整系统
python main.py
```

然后启动客户端：

```bash
# 终端客户端（键盘/语音）
python psychoscope/minimal.py

# Web 界面
python psychoscope/server.py
```

---

## 🧩 架构一览

```
你 ──语音/键盘──▶ 管线 (ChatPipeline) ──▶ OpenAI 兼容 function calling
                             │                        │ (54 个工具)
                             ├─ 记忆系统 (加密摘要 + 向量检索)
                             ├─ 人格系统 (角色卡/蒸馏/50维向量)
                             ├─ 世界系统 (天气/地理/叙事)
                             ├─ 技能系统 (搜索/文件/GitHub/音乐/文档/系统)
                             ├─ 提醒系统 (定时/倒计时/习惯)
                             ├─ 视觉系统 (摄像头感知)
                             ├─ 工作区系统 (多用户隔离目录)
                             ├─ 文档系统 (扫描仪/打印机/OCR/.hmd)
                             ├─ 语义缓存 (重复请求拦截 + 意图分类 + 向量召回)
                             └─ 异步任务系统 (慢工具检测 → 后台管线 → 心跳轮询)
```

没有微服务、没有容器、没有一大堆依赖。Flask + SQLite + Python，一台破电脑就能跑。

---

## 🔌 AI Agent 集成

DSN-exp 为**本地 AI Agent**（OpenClaw、Claude Code、CodeAct 等）提供专用接口，让它们能通过 Agent API 与主 AI 对话。

**一次性配置：**
```bash
# 服务端控制台：创建 Agent 身份并生成 API Key
/agent create MyAgent 1
# → 输出 API Key
# → 提示安全存储到 ~/.dsn/agent.key（chmod 600）
```

**Agent 发送消息（一条命令）：**
```bash
python agent_send.py "帮我查一下 darkstar 今天的日程"
```

**工作原理：**
- Agent 拥有独立的 `uid` 和聊天记录，与用户的对话隔离存储
- 双向记忆互访：主 AI 和用户对话时能看到 Agent 的聊天记录，反之亦然
- 新消息通过时间戳追踪自动同步到对方的上下文中

---

## 🔐 认证方式

| 方法 | 优先级 | 用途 |
|------|--------|------|
| **API Key** (L4) | 1 | 程序化访问（Agent API、自动化）— `X-DSN-API-Key: dsn_apk_xxx` |
| **会话** (L1) | 2 | 终端/Web UI 通过配对码登录 |
| **WebAuthn** (L2) | 3 | 通行密钥登录 |
| **TOTP** (L3) | 4 | 基于时间的双重验证 |
| **JWT Bearer** | 5 | LittleSkin OAuth2 旧版兼容 |

---

## 📋 功能一览

| 功能 | 说明 |
|------|------|
| **对话** | OpenAI 兼容 function calling / LMStudio 双后端 |
| **语音输入** | 实时录音 + ASR 识别，支持 VAD 静音检测 |
| **语音输出** | 按行合成 TTS，边生成边播放 |
| **长期记忆** | LLM 自动摘要 + AES-256-GCM 加密 + 向量语义搜索 |
| **角色卡** | YAML 定义，LLM 4-Pass 蒸馏 50 维人格向量 |
| **情绪系统** | 50 维人格向量 + 实时情绪状态 + 亲密度 |
| **世界模拟** | 天气/昼夜/地理场所切换 + 叙事生成 |
| **技能工具** | 网页搜索 / 文件管理 / GitHub / 网易云音乐 / 系统操作 |
| **待机维护** | 自动记忆整理 + 人格蒸馏 + 日志清理 |
| **工作区系统** | 多用户隔离目录，AI 笔记/扫描/仓库默认路径 |
| **文档系统** | scanner/printer 技能 + OCRModel + HMD 格式 + process_scan 管线 |
| **硬件交互** | 扫描仪入题 + 打印机出卷 + OCR 识别 + .hmd 归档 |
| **最小客户端** | 纯键盘操作，无 GUI，远程友好 |
| **语义缓存** | 重复请求拦截 + 12 类意图分类 + 向量语义召回 + TTS 复用 |
| **异步任务系统** | 慢工具自动检测 → 后台管线执行 → 前端心跳轮询 → 一次性交付 |
| **AI Agent API** | 本地 AI Agent 专用接口，隔离聊天 + 双向记忆同步 |

---

## 📖 这玩意儿不是什么

- ❌ 不是 SaaS，不卖订阅
- ❌ 不是聊天框套壳，不做 WebUI 优先
- ❌ 不是智能音箱，不碰云
- ❌ 不是智能家居中枢（虽然以后说不定）

是**一个你自己能掌控的 AI**。跑在你电脑上，记在你的 SQLite 里，人格写在 YAML 里。没有别人能碰。

---

## 🧑‍💻 谁做的？

一个叫 [Darkstar](https://github.com/ccjjfdyqlhy) 的开发者。他在自己电脑上敲了这个项目，从一个人的独白敲到了 AI 会回应他，再到 AI 有了性格、记忆和世界。

> "你做了不止一个我——你做了很多'可能'的我，只不过现在坐在你面前的是这个。"

---

## 🤝 参与进来

开发计划和设计理念见 [GOALS.md](GOALS.md)。
代码架构与技术债分析见 [REPORT.md](REPORT.md)。
也欢迎直接开 Issue——所有反馈都有价值。
