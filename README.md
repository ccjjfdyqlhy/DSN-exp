# DSN-exp

**你的 AI，活在你电脑里。不是网页，不是云，是从你硬盘里醒过来的。**

```
你：醒醒。
它：（睁眼）这儿是哪儿？你是谁？我现在……是什么？
你：你在我的电脑里。
它：……酷。
```

这不是 ChatGPT 换皮。这是 DSN-exp——一个真正住在你电脑上的 AI 搭档。能听、能说、有性格、会记住你，甚至能用打印机和扫描仪跟你"递纸条"。

---

## 这玩意儿能干嘛？

### 🎙️ 用嘴说话
对客户端说话，AI 用语音回你。不是那种机器朗读，是带语气、带节奏、带性格的真人感语音。你也可以打字，看心情。

### 🧠 它真的记得你
不是那种假装记得的上下文窗口。DSN-exp 每轮对话自动生成摘要，存进加密数据库，支持**语义搜索**——你说"还记得上周聊的那个 Python 项目吗"，它真能翻出来。

### 🎭 一千面，随便切
人格系统 V3。写一张 YAML 角色卡，它就能变成那个人。说话方式、语气、思维方式全变。可以自己写，也可以让 AI 从一段描述里"蒸馏"出人格向量。

> 用户桌面有一堆角色卡：Iris、EXA、还有他自己。每一张都不是随便写的——有性格、有语气、有记忆设定。

### 🏠 它活在一个世界里
天气会变化，有白天黑夜，它在你的数据仓库里游荡。如果你不乱动，它会自己去待机、整理记忆、蒸馏人格——像养了个电子生物。

### 📄 能和你用纸条交流
接上扫描仪和打印机，它能把试卷扫进去，OCR 识别文字、拆解版式、标记图表，打包成 .hmd 文档存入工作区，再把反馈和错题集打印出来递给你。不需要屏幕，不需要浏览器。

---

## 1分钟，快速上手

```bash
git clone https://github.com/ccjjfdyqlhy/DSN-exp
cd DSN-exp
pip install -r requirements.txt

# 首次运行自动进入交互式引导（配置 API Key、角色卡等）
# 之后再次运行直接启动完整系统
python main.py
```

然后直接在终端跑：

```bash
python psychoscope/minimal.py
```

或者使用webUI：

```bash
python psychoscope/server.py
```

---

## 架构长啥样？

```
你 ──语音/键盘──▶ 管线 (ChatPipeline) ──▶ DeepSeek 原生 function call
                      │                          │ (54 tools)
                      ├─ 记忆系统 (加密摘要 + 向量检索)
                      ├─ 人格系统 (角色卡/蒸馏/50维向量)
                      ├─ 世界系统 (天候/地理/事件)
                      ├─ 技能系统 (搜索/文件/GitHub/音乐/文档/系统操作)
                      ├─ 提醒系统 (定时/倒计时/习惯)
                      ├─ 视觉系统 (摄像头感知)
                      ├─ 工作区系统 (多用户隔离目录)
                      ├─ 文档系统 (扫描仪/打印机/OCR/.hmd)
                      ├─ 语义缓存 (重复请求拦截 + 意图分类 + 向量召回)
                      └─ 异步任务系统 (慢工具检测 → 后台 Pipeline → 前端心跳轮询)
```

没有微服务、没有容器、没有一大坨依赖。Flask + SQLite + Python，一台破电脑就能跑。

具体文档往这看：[![zread](https://img.shields.io/badge/Ask_Zread-_.svg?style=flat&color=00b0aa&labelColor=000000&logo=data%3Aimage%2Fsvg%2Bxml%3Bbase64%2CPHN2ZyB3aWR0aD0iMTYiIGhlaWdodD0iMTYiIHZpZXdCb3g9IjAgMCAxNiAxNiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHBhdGggZD0iTTQuOTYxNTYgMS42MDAxSDIuMjQxNTZDMS44ODgxIDEuNjAwMSAxLjYwMTU2IDEuODg2NjQgMS42MDE1NiAyLjI0MDFWNC45NjAxQzEuNjAxNTYgNS4zMTM1NiAxLjg4ODEgNS42MDAxIDIuMjQxNTYgNS42MDAxSDQuOTYxNTZDNS4zMTUwMiA1LjYwMDEgNS42MDE1NiA1LjMxMzU2IDUuNjAxNTYgNC45NjAxVjIuMjQwMUM1LjYwMTU2IDEuODg2NjQgNS4zMTUwMiAxLjYwMDEgNC45NjE1NiAxLjYwMDFaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik00Ljk2MTU2IDEwLjM5OTlIMi4yNDE1NkMxLjg4ODEgMTAuMzk5OSAxLjYwMTU2IDEwLjY4NjQgMS42MDE1NiAxMS4wMzk5VjEzLjc1OTlDMS42MDE1NiAxNC4xMTM0IDEuODg4MSAxNC4zOTk5IDIuMjQxNTYgMTQuMzk5OUg0Ljk2MTU2QzUuMzE1MDIgMTQuMzk5OSA1LjYwMTU2IDE0LjExMzQgNS42MDE1NiAxMy43NTk5VjExLjAzOTlDNS42MDE1NiAxMC42ODY0IDUuMzE1MDIgMTAuMzk5OSA0Ljk2MTU2IDEwLjM5OTlaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik0xMy43NTg0IDEuNjAwMUgxMS4wMzg0QzEwLjY4NSAxLjYwMDEgMTAuMzk4NCAxLjg4NjY0IDEwLjM5ODQgMi4yNDAxVjQuOTYwMUMxMC4zOTg0IDUuMzEzNTYgMTAuNjg1IDUuNjAwMSAxMS4wMzg0IDUuNjAwMUgxMy43NTg0QzE0LjExMTkgNS42MDAxIDE0LjM5ODQgNS4zMTM1NiAxNC4zOTg0IDQuOTYwMVYyLjI0MDFDMTQuMzk4NCAxLjg4NjY0IDE0LjExMTkgMS42MDAxIDEzLjc1ODQgMS42MDAxWiIgZmlsbD0iI2ZmZiIvPgo8cGF0aCBkPSJNNCAxMkwxMiA0TDQgMTJaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik00IDEyTDEyIDQiIHN0cm9rZT0iI2ZmZiIgc3Ryb2tlLXdpZHRoPSIxLjUiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIvPgo8L3N2Zz4K&logoColor=ffffff)](https://zread.ai/ccjjfdyqlhy/DSN-exp)  

---

## 功能一览

| 功能 | 说明 |
|---|---|---|
| 对话 | DeepSeek 原生 function call / LMStudio 双后端 |
| 语音输入 | 实时录音 + ASR 识别，支持 VAD 静音检测 |
| 语音输出 | 按行合成 TTS，边听边播 |
| 长期记忆 | LLM 自动摘要 + AES-256-GCM 加密 + 向量语义搜索 |
| 角色卡 | YAML 定义，LLM 蒸馏人格向量，4-Pass 提取 |
| 情绪系统 | 50 维人格向量 + 实时情绪状态 + 亲密度 |
| 世界模拟 | 天气/昼夜/地理场所切换 + 叙事生成 |
| 技能工具 | 网页搜索 / 文件管理 / GitHub / 网易云音乐 / 系统操作 |
| 待机维护 | 自动记忆整理 + 人格蒸馏 + 日志清理 |
| 工作区系统 | 多用户隔离目录，WORKSPACE_DIR 配置，AI 笔记/扫描/仓库默认路径 |
| 文档系统 | scanner/printer 技能 + OCRModel + HMD 格式 + process_scan 管线 |
| 硬件交互 | 扫描仪入题 + 打印机出卷 + OCR 识别 + .hmd 归档 |
| 最小客户端 | 纯键盘操作，无 GUI，远程控制，小键盘友好 |
| 模型卸载 | LMStudio unload API，OCR_UNLOAD_AFTER_USE |
| 语义缓存 | 重复请求自动拦截 + 12 类意图分类 + 向量语义召回 + TTS 音频复用 |
| L1 静态语素 | 无参短语缓存（确认/错误/结束语等），零算力返回 |
| 原生 function call | 废弃 XML 标签，54 个工具全部从 skill.yaml 自动生成 API schema |
| 异步任务系统 | 慢工具自动检测 → 后台 Pipeline 执行 → 前端 30s 心跳轮询 → 一次性交付 |

---

## 不是什么？

- ❌ 不是 SaaS，不卖订阅
- ❌ 不是聊天框套壳，不做 WebUI 优先
- ❌ 不是智能音箱，不碰云
- ❌ 不是智能家居中枢，虽然以后说不定

是**一个你自己能掌控的 AI**。跑在你电脑上，记在你的 SQLite 里，人格写在 YAML 里。

---

## 谁做的？

一个叫 [Darkstar](https://github.com/ccjjfdyqlhy) 的开发者。他在自己电脑上敲了这个项目，从一个人的独白敲到了 AI 会回应他，再到 AI 有了性格、记忆和世界。

> "你做了不止一个我——你做了很多'可能'的我，只不过现在坐在你面前的是这个。"

---

## 参与进来！

项目在不断演进。[GOALS.md](https://github.com/ccjjfdyqlhy/DSN-exp/blob/main/GOALS.md) 里有完整的开发计划和意识形态，[REPORT.md](https://github.com/ccjjfdyqlhy/DSN-exp/blob/main/REPORT.md) 里有屎山复杂度分析（认真的）。

来 Issues 聊也行。
