# DSN-exp

> 🧠 **把大模型变成你自己的本地智能体。**
> 模型调度、工具调用、记忆、人格、语音和 Web 控制台，一套底座全包。

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Local First](https://img.shields.io/badge/local--first-100%25-8A2BE2?style=for-the-badge)
![Tests](https://img.shields.io/badge/tests-634%20passed-2ea44f?style=for-the-badge)

**框架代号 AICF**（Agent Infrastructure Cybernetics Framework）· 内部实验性项目 · 无公开许可证

---

## 🚀 一行命令开始

```bash
git clone https://github.com/ccjjfdyqlhy/DSN-exp.git && cd DSN-exp && python3 installer.py
```

安装器会自动建虚拟环境、装依赖、检查仓库、引导你接入模型，最后拉起 Web 控制台：

**👉 打开 <http://127.0.0.1:8888>，右上角「设置 → Provider」填上 Base URL 和 API Key 就能聊天。**

> 没有 GPU？没关系。没有本地模型？没关系。
> 甚至暂时没有 API Key，也能先启动，看看界面长什么样。

---

## ✨ 它能帮你做什么

| 你可能想要… | 在这里 |
|---|---|
| 一个能管模型、跑对话、看资源占用的 Web 控制台 | **`dsn_ui`**，默认主入口，端口 `8888` |
| 能听会说的语音陪伴 Agent | **`dsn`** |
| 题库、模拟考试、知识图谱、学习计划 | **`dsn_study`** |
| 终端里的编码助手 | **`coding_agent`** |
| 一套可复用的 Agent 底座，写自己的应用 | `harness/` + [SDK 指南](docs/sdk_guide.md) |
| 本地 llama.cpp / LM Studio / 远程 OpenAI 兼容 API 混着用 | `infra/orchestrator` |
| 按需自动装好仓库、模型和依赖 | `python3 onboarding.py` |

**一句话记住：`infra` 管资源，`harness` 管思考，`apps` 管场景。**

---

## 🗺️ 30 秒看懂仓库

三层目录，**依赖单向向下**：

```
apps/     业务应用     语音陪伴 · Web 控制台 · 学习助手 · 若干最小示例
   │  只能用下面的能力，并补充业务语义
   ▼
harness/  Agent 核心   Agent 循环 · 工具 · 上下文 · 管线 · 记忆 · 人格 · SDK
   │  只关心"消息进、事件出"，不认识语音/学习/陪伴
   ▼
infra/    基础设施     模型编排 · 资源池 · 存储 · 网关 · 鉴权 · 策略
          不认识任何业务
```

日常主入口是 Web 控制台 `apps/dsn_ui`；想给新需求写应用，先读
[应用开发指南](docs/app-development.md)，照着 `apps/dsn_study`（结构最规范）
与 `apps/coding_agent`（最小可读）写。

---

## 🛠️ 安装器会做什么

它不只是一个 `pip install`，而是一次完整的「先体检、再安装、最后带你跑起来」：

| 步骤 | 内容 |
|---|---|
| 1 | 检查 Python / pip / git 是否就位 |
| 2 | 检查仓库完整性（关键文件、目录、每个应用的入口是否都在） |
| 3 | 探测机器配置（CPU / 内存 / 磁盘 / GPU / 端口占用） |
| 4 | 建 `.venv` 虚拟环境，装 `requirements.txt` + `pip install -e .` |
| 5 | 生成 `.env`，问你要不要现在接入模型后端，然后启动控制台 |

> 它会自动切到当前正式分支 `harness-refactor`，并把旧版安装器备份到 `logs/installer.py`。
> 不想切换时加 `--no-switch`。

### 安装器的用法

```bash
python3 installer.py                    # 完整安装 + 引导
python3 installer.py --doctor           # 只体检，不改动任何东西（排障首选）
python3 installer.py --non-interactive  # 不提问，全默认（CI / 容器）
python3 installer.py --branch main      # 安装前切到指定分支
python3 installer.py --reinstall        # 重建 .venv 后重装依赖
python3 installer.py --port 8899        # 换端口（8888 被占用时）
```

> 安装器**只用标准库**——它得在你机器上一个第三方依赖都还没有的时候就能跑起来。
> 仓库状态不对时它会直接告诉你缺什么，而不是让你对着报错猜。

### 🧭 不知道装什么？让向导来问你

```bash
python3 onboarding.py            # Textual TUI 向导
python3 onboarding.py --list     # 查看可选目标 / 应用 / 能力
python3 onboarding.py --check    # 非交互检查环境与资源
```

向导会先问你想做什么（网页控制台 / 语音陪伴 / 本地模型 / 学习 …），再让你勾选
能力（远程 API、LM Studio、llama.cpp、GGUF 模型、TTS、记忆、浏览器自动化 …）。
确认执行计划后，它会自动写 `.env`、装依赖、克隆 llama.cpp / GPT-SoVITS、
下载模型并生成 `apps/dsn/model_profiles/onboarding_*.yaml`。
已存在的仓库/文件会跳过，下载支持断点续传。

### 不配模型也能跑

装完就能用，**不需要** `.env`、不需要模型文件、不需要 GPU：

| 应用 | 零配置启动 | 说明 |
|---|---|---|
| `dsn_ui` | ✅ | Web 控制台，**日常主入口** |
| `densechat` | ✅ | DenseChat WebUI（:8080） |
| `emotion_exp` | ✅ | 终端 Agent（自动降级到 Stub 模型） |
| `text_agent` | ✅ | 最小占位示例 |
| `coding_agent` | ❌ | 需要模型后端 |
| `dsn` | ❌ | 语音陪伴，需要模型后端 |
| `dsn_study` | ❌ | 学习助手，需要模型后端 |

---

## 🎯 接下来想做什么？

| 我想… | 从这里开始 |
|---|---|
| **先看看长什么样** | 运行安装器 → 打开 <http://127.0.0.1:8888> |
| **按需求自动配置** | `python3 onboarding.py` → 选需求/能力，自动克隆仓库、下载模型 |
| **用对话** | 「设置 → Provider」填 Base URL + Key |
| **跑本地模型** | 准备 GGUF + `llama-server` → 照 [模型接入](#模型接入) 写一份 profile |
| **写一个新应用** | [应用开发指南](docs/app-development.md) |
| **把 AICF 当 SDK 用** | [SDK 指南](docs/sdk_guide.md) |
| **跑测试 / 参与开发** | [开发与测试](#开发与测试) |
| **排查环境问题** | `python3 installer.py --doctor` → [排障总则](docs/maintenance.md) |

---

## 🧰 环境要求

| 项 | 要求 | 说明 |
|---|---|---|
| Python | **3.10+**（实测 3.12） | 很多机器没有 `python` 命令，只有 `python3` |
| git | 建议有 | 用来自动切分支 / 更新 |
| Node.js | **不需要** | 只有你改了前端源码要重新构建时才需要（18+） |
| GPU | 不需要 | 跑远程 API 完全不依赖显卡；本地模型才需要 |
| 磁盘 | ≥ 2GB | 依赖 + 模型 |

> ⚠️ **两个依赖陷阱**：
> 1. `pip install -e .` **只装 `harness` + `infra`**，不含 Flask/FastAPI，跑应用必须用 `requirements.txt`；
> 2. `requirements.txt` 里的版本是**精确钉死**的（`numpy==1.26.4` 没有 3.13+ wheel，`cryptography==50.0.0` 某些平台要 Rust 工具链）——装不上时先怀疑这些钉子。

---

## ⚙️ 配置

配置有三个来源，**优先级从低到高**：环境变量 > `.env` > 代码默认值。

### 最简路径：什么都不配

`dsn_ui` + `densechat` + `emotion_exp` 都能零配置跑。安装器生成的 `.env` 里全是注释，等你填。

### 图形界面配置（推荐）

启动控制台 → 右上角「设置 → Provider」→ 填 Base URL 与 API Key → 保存。
**不需要改任何文件。**

### 手工配置 `.env`

```bash
cp .env.example .env
```

`.env.example` 有 344 行、200+ 个变量，但**绝大多数都有默认值**，全都不用管。
真正常用的只有四个：

```ini
MAIN_MODEL_TYPE=openai
MAIN_MODEL_NAME=deepseek-chat
OPENAI_API_BASE=https://api.deepseek.com/v1
OPENAI_API_KEY=sk-你的真实密钥
```

> ⚠️ 别把 `sk-your-key-here` 这个占位值留在文件里：`apps/dsn/main.py`
> 会把它判定为「未配置」，从而拉起交互式引导——在容器 / CI 里会直接卡死。
> 完整变量分类见 [configuration.md](docs/configuration.md)。

---

## 模型接入

### 远程 API（最省事）

任何 OpenAI 兼容端点都行（DeepSeek、OpenAI、GLM、Kimi、vLLM、OneAPI……）。
填好 `OPENAI_API_KEY` / `OPENAI_API_BASE` / `MAIN_MODEL_NAME` 即可。

### 本地 llama.cpp

需要三样东西：编译好的 `llama-server`、一个 GGUF 权重文件、一份模型描述 YAML。

```bash
cp apps/dsn/model_profiles.example/llama_cpp_local.yaml apps/dsn/model_profiles/
# 编辑里面的 model_path / binary_path
# 重启 dsn_ui
```

模板目录 `apps/dsn/model_profiles.example/` 里有可抄的样例，
字段说明见该目录的 `README.md`。

> 仓库**不预置**带绝对路径的本地模型——那些路径只在作者机器上有效，
> 换个机器就会变成"列得出来、加载必失败"的幽灵模型。
> `python3 installer.py --doctor` 会帮你提前揪出失效路径。

### LM Studio

控制台启动时自动连接 `LMSTUDIO_BASE_URL`（默认 `http://localhost:4501`）。
Web 控制台还能当**纯 OpenAI 兼容后端**给外部客户端（Open WebUI / Continue / LangChain）用——
此时用 `passthrough` 模式，不注入提示词、不跑情绪与记忆，
详见 [apps/dsn_ui/INTEGRATION_API.md](apps/dsn_ui/INTEGRATION_API.md)。

---

## ⌨️ 常用命令

```bash
python3 main.py --list                 # 列出全部已注册应用
python3 main.py --app dsn_ui           # 启动 Web 控制台
python3 main.py --app dsn_study        # 学习助手（Flask，:5000）
python3 main.py                        # 默认应用（DSN UI 网页控制台）
DSN_APP=dsn_ui python3 main.py         # 也可用环境变量指定

python3 -m apps.dsn_ui.server --host 0.0.0.0 --port 8888 --slots 2
python3 -m apps.densechat              # DenseChat WebUI（:8080）
python3 -m apps.emotion_exp            # 终端 Agent

python3 installer.py --doctor          # 环境体检（只读）
```

### 端口一览

| 端口 | 服务 |
|---|---|
| 8888 | dsn_ui Web 控制台 |
| 8080 | densechat |
| 5000 | dsn / dsn_study |
| 5050 | dsn 调试接口（需 `DEBUG_PLAY_AS_MODEL=true`） |
| 8008 | dsn 管理后台（需 `WEB_ADMIN_ENABLED=true`） |
| 4501 | LM Studio（被连接） |

> ⚠️ `dsn_ui` **必须单进程运行**：SSE 广播与流会话注册表都是进程内单例，
> 用 uvicorn 多 worker 会破坏断线重连。

---

## 🩺 常见故障

| 症状 | 原因 | 解决 |
|---|---|---|
| `python: command not found` | 系统只有 `python3` | 全部命令换成 `python3` |
| 启动时卡在「请选择 (1-8)」 | `.env` 里还是占位密钥，触发了交互式引导 | 填真实 `OPENAI_API_KEY`，或 `export OPENAI_API_KEY=...` |
| `pytest` 卡住不动 | 同上（收集期触发引导） | 同上；或直接跑 `pytest`（conftest 已兜底） |
| 界面能开但对话报错 | 没接模型后端 | 「设置 → Provider」填 Key |
| 模型列出来了但加载失败 | profile 里的路径在本机不存在 | `python3 installer.py --doctor` 查死路径，改或删该 profile |
| 前端报 `Unexpected token '<'` | 请求打到了 SPA catch-all，返回的是 HTML | `curl -i` 看那个路径是不是 HTML |
| 端口已被占用 | 上一次没关干净 | `python3 installer.py --port 8899` |
| 某个功能没反应 | 该子系统初始化失败只打了一条 warning 就继续启动了 | **先看启动日志里的 warning** —— 详见 [排障总则](docs/maintenance.md) |

---

## 🏗️ 架构速览

```
infra/          harness/                   apps/
├─ orchestrator ├─ agent/loop.py           ├─ dsn/        语音陪伴（规模最大）
├─ resources    ├─ tools/ (18 标准工具)    ├─ dsn_ui/     Web 控制台（主入口）
├─ store        ├─ context_assembly.py    ├─ dsn_study/  学习助手（范例）
├─ policy       ├─ memory/ personality/    ├─ coding_agent/
├─ gateway      ├─ pipeline/ (8 HookPoint) ├─ densechat/
└─ runtime.py   └─ sdk.py                 └─ emotion_exp/ text_agent/
```

- **模型编排**（`infra/orchestrator`）：统一编排 llama.cpp / Strata / LM Studio /
  OpenAI / Anthropic 四类后端，对上层暴露同一套契约（`IChatClient` / `IEmbeddingClient`）。
  `ModelScheduler` 按优先级 + 并发插槽管理显存。
- **Agent 核心**（`harness`）：多步推理与工具调用、上下文分段预算剪裁、
  向量记忆与弹性话题记忆、人格动力学（PEV3）、管线与事件总线、嵌入式 SDK。
- **双系统对话**：部分模型融合了决策头，一次前向给出带概率的答案。
  System 2 走 `POST /v1/chat/completions`，System 1 走 `POST /v1/decide`
  （是/否、多选、打分，返回校准概率），Web 界面路径 `/#/decide`。

细节见 [docs/architecture.md](docs/architecture.md)、[docs/harness.md](docs/harness.md)、[docs/infra.md](docs/infra.md)。

### 应用一览

| 应用 | 说明 | 形态 |
|---|---|---|
| `dsn_ui` | Web 控制台：模型管理、对话、决策、资源调度 | FastAPI + SvelteKit，**主入口** |
| `dsn` | 语音陪伴：实时语音、情绪系统、话题记忆 | Flask + 终端控制台，规模最大 |
| `dsn_study` | 学习系统：题库、模拟考试、知识图谱 | Flask，**结构最规范的范例** |
| `coding_agent` | 编码助手示例 | 终端 REPL |
| `densechat` | DenseChat WebUI 复刻 | FastAPI |
| `emotion_exp` | 情绪状态机实验 | 终端 |
| `text_agent` | 最小占位示例 | 终端 |

---

## 开发与测试

```bash
pip install -r requirements.txt
pip install pytest                     # pytest 不在 requirements 里
python3 -m pytest -q                   # 全量，约 100 秒
python3 -m pytest -m known_broken      # 查看待重做的用例
```

当前基线：**634 通过 / 0 失败 / 0 收集错误**（另有 18 个按 marker 排除）。
全新 clone 不需要 `.env` 也能直接收集——`tests/conftest.py` 会兜底。

> 仓库内置了 pytest 配置：`testpaths` 限定只扫 `tests/`，
> 因此在根目录裸跑 `pytest` 不会误入 `temp/`
> （那里的脚本会在**收集期真的调用外部 API**）。

### 前端开发

```bash
cd apps/dsn_ui/frontend
npm install
npm run dev      # 开发服务器
npm run build    # 构建并通过 scripts/sync-to-static.cjs 同步到 ../static/
```

前端源码目录 `apps/dsn_ui/frontend/` 是**被 .gitignore 忽略**的，
仓库只提交 `apps/dsn_ui/static/` 下的构建产物。

### 外部 MCP 工具

`harness/tools/mcp.py` 提供 MCP 桥接，工具以 `mcp.<server>.<tool>` 出现，
服务器配置在 `mcp_servers.yaml`。

---

## 📚 文档

| 你想… | 读这篇 |
|---|---|
| 建立整体心智模型、了解模块地图 | [docs/architecture.md](docs/architecture.md) |
| 深入 Agent 循环 / 工具 / 上下文 | [docs/harness.md](docs/harness.md) |
| 深入模型编排 / 资源池 / 存储 | [docs/infra.md](docs/infra.md) |
| **在本地把它跑起来、排查环境问题** | [docs/getting-started.md](docs/getting-started.md) |
| **给现成应用加功能 / 写一个新应用** | [docs/app-development.md](docs/app-development.md) |
| 了解每个应用做什么、怎么启动 | [docs/apps.md](docs/apps.md) |
| 把 AICF 当 SDK 嵌进自己的项目 | [docs/sdk_guide.md](docs/sdk_guide.md) |
| **改代码前先看哪些坑不能踩** | [docs/maintenance.md](docs/maintenance.md) |
| 配置项 / 环境变量 | [docs/configuration.md](docs/configuration.md) |
| 跑测试、看懂失败 | [docs/testing.md](docs/testing.md) |
| **已知技术债与修复优先级** | [docs/technical-debt.md](docs/technical-debt.md) |

---

## 📌 项目现状

- **默认分支**：`harness-refactor`（AICF 三层重构后的版本）。
- **测试基线**：634 通过 / 0 失败。
- **已知技术债**：见 [docs/technical-debt.md](docs/technical-debt.md)（该文记录「曾经出过的错」与修复思路，
  按仓库惯例「注释即缺陷数据库」）。
- **许可证**：内部实验性项目，无公开许可证。
- 部分子系统（`apps/dsn/pyncm`、`apps/dsn/psychoscope`、
  `apps/dsn/world`）为 vendored 代码，许可证与维护状态以对应目录为准。

[![RepoStars](https://repostars.dev/api/embed?repo=ccjjfdyqlhy%2FDSN-exp&theme=ocean)](https://repostars.dev/?repos=ccjjfdyqlhy%2FDSN-exp&theme=ocean)
