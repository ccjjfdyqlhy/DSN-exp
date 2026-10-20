# DSN-exp

> 一个完全跑在本地的智能体底座：统一的模型调度、上下文装配、工具执行与多协议对外接口。
> 框架代号 **AICF**（Agent Infrastructure Cybernetics Framework），仓库同时承载框架与它的应用。

---

## 30 秒理解这个仓库

三层目录，**依赖单向向下**：

```
apps/     业务应用     语音陪伴 · Web 控制台 · 学习助手 · 若干最小示例
   │  只能用下面的能力，并补充业务语义
   ▼
harness/  Agent 核心   Agent 循环 · 工具 · 上下文 · 管线 · 记忆 · 人格 · SDK
   │  只关心“消息进、事件出”，不认识语音/学习/陪伴
   ▼
infra/    基础设施     模型编排 · 资源池 · 存储 · 网关 · 鉴权 · 策略
          不认识任何业务
```

一句话记住：**`infra` 管资源，`harness` 管思考，`apps` 管场景。**

日常使用的入口是 Web 控制台 `apps/dsn_ui`；想给新需求写应用，请先读
[应用开发指南](docs/app-development.md)，照着 `apps/dsn_study`（结构最规范）
与 `apps/coding_agent`（最小可读）写。

---

## 快速开始

### 环境

- Python **3.10+**（本仓库实测运行于 3.12；注意很多机器没有 `python` 命令，只有 `python3`）
- Node 18+（**仅**在需要重新构建 `dsn_ui` 前端时使用；构建产物已入库）

```bash
pip install -r requirements.txt   # 运行框架与应用
pip install -e .                  # 以 SDK 形式嵌入到别的项目（可选，只装框架）
cp .env.example .env              # 然后填写 API Key / 模型路径
```

> ⚠️ 两个已知的依赖陷阱：
> 1. `pip install -e .` **只装 `harness` + `infra`**，不含 Flask/FastAPI，跑应用必须用 `requirements.txt`；
> 2. `requirements.txt` 现已补齐 `psutil` / `opencv-python`（此前遗漏，干净环境会报 ModuleNotFoundError）。

### 启动

```bash
python main.py                    # 默认应用（DSN 语音陪伴）
python main.py --app dsn_ui       # Web 控制台（日常主入口）
python main.py --list             # 列出全部已注册应用
DSN_APP=dsn_ui python main.py     # 也可用环境变量
```

> ⚠️ 本机若只有 `python3` 而没有 `python`，把上面命令里的 `python` 换成 `python3` 即可。

### 打开 Web 控制台

```bash
python -m apps.dsn_ui.server --host 0.0.0.0 --port 8888 --slots 2
```

浏览器打开 <http://127.0.0.1:8888>。技术栈 FastAPI + SvelteKit 5。

---

## 想知道什么，看哪份文档

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

## 能力速览

### 模型编排（`infra/orchestrator`）

统一编排四类后端，对上层暴露同一套契约（`IChatClient` / `IEmbeddingClient`）：

| 后端 | 说明 |
|---|---|
| **llama.cpp** | 本地 GGUF，支持分层卸载、张量拆分、mmproj 视觉 |
| **Strata** | 自研大模型引擎，专家权重分层缓存 |
| **LM Studio** | 本地 GUI 模型库 |
| **OpenAI / Anthropic** | 远程 API，OpenAI 侧支持 chat 与 responses 双协议 |

`ModelScheduler` 按**优先级 + 并发插槽**管理显存：常驻、即时回收、驱逐与自动恢复。
踩过的坑（并发重复拉起、取消竞态、PDEATHSIG 绑错线程）已固化为代码注释与单飞逻辑。

### Agent 核心（`harness`）

- **Agent 循环** — 多步推理、工具调用、步数预算与收束轮（`harness/agent/loop.py`）
- **工具系统** — 注册表、wire 名编码、两阶段 toolbox 激活、18 个标准工具
- **上下文装配** — 分段预算剪裁（备忘 / 摘要 / 原文 / 尾部）
- **记忆与人格** — 向量记忆、弹性话题记忆、人格动力学（PEV3）
- **管线** — 8 个 HookPoint、事件总线、输出渲染与过滤
- **SDK** — `create_agent` / `@tool` 嵌入式用法

### 应用（`apps/`）

| 应用 | 说明 | 形态 |
|---|---|---|
| **`dsn_ui`** | Web 控制台：模型管理、对话、决策、资源调度 | FastAPI + SvelteKit，**主入口** |
| `dsn` | 语音陪伴：实时语音、情绪系统、话题记忆 | Flask + 终端控制台，规模最大 |
| `dsn_study` | 学习系统：题库、模拟考试、知识图谱 | Flask，**结构最规范的范例** |
| `coding_agent` | 编码助手示例 | 终端 REPL |
| `densechat` | DenseChat WebUI 复刻 | FastAPI |
| `emotion_exp` | 情绪状态机实验 | 终端 |
| `text_agent` | 最小占位示例 | 终端 |

---

## 模型接入

### 本地模型：放一个 YAML 即自动注册

在 `apps/dsn/model_profiles/` 放一个文件，`dsn_ui` 启动时自动注册：

```yaml
model: jev-27b-vl
engine: llama_cpp
priority: 88
orchestrated: true

llama_config:
  binary_path: ~/llama.cpp/build/bin/llama-server
  model_path: /path/to/model.gguf
  mmproj_path: /path/to/mmproj.gguf   # 有则自动具备视觉能力
  n_gpu_layers: 99
  tensor_split: "11,11"
  ctx_size: 32768
```

### 远程 API：在「设置 → Provider」里填 Base URL 与 Key

也支持把 `dsn_ui` 当作**纯 OpenAI 兼容后端**给外部客户端（Open WebUI / Continue /
LangChain）使用——此时用 `passthrough` 模式，不注入任何提示词、不跑情绪与记忆：
详见 [apps/dsn_ui/INTEGRATION_API.md](apps/dsn_ui/INTEGRATION_API.md)。

---

## 双系统对话（System 1 / System 2）

部分模型（如 JEV 系列）在通用生成之外融合了**决策头**，一次前向即可给出带概率的答案：

| 模式 | 端点 | 适用 |
|---|---|---|
| **System 2** | `POST /v1/chat/completions` | 常规对话、写作、代码，流式与图像 |
| **System 1** | `POST /v1/decide` | 是/否、多选、打分，返回校准概率 |

System 1 在 llama.cpp 上没有独立端点，`apps/dsn_ui/system1_api.py` 通过
`max_tokens=1 + logprobs` 读取词表分布来实现，逻辑见该文件头部注释。
Web 界面路径 `/#/decide`，支持图文决策。

---

## 目录结构

```
DSN-exp/
├── main.py / run.py / launcher.py   启动器（应用选择 + 入口分发）
├── apps.yaml                        应用注册表（可选，与内置清单合并）
├── apps/                            业务应用
│   ├── dsn_ui/                      Web 控制台（FastAPI + SvelteKit 5）
│   │   ├── server.py                主服务（约 3k 行，路由集中注册）
│   │   ├── agent.py                 对话协调器（api_mode 分支在这里）
│   │   ├── system1_api.py           System-1 决策接口
│   │   └── static/                  前端构建产物（前端源码不入库）
│   ├── dsn/                         语音陪伴（实时语音 · 情绪 · 话题记忆）
│   ├── dsn_study/                   学习助手
│   ├── coding_agent/ densechat/ emotion_exp/ text_agent/   示例与实验应用
├── harness/                         Agent 核心
│   ├── agent/                       循环 · 装配器 · 子代理 · swarm · 模式
│   ├── tools/                       工具抽象与 18 个标准工具
│   ├── context_assembly.py          分段上下文预算剪裁
│   ├── memory/ personality/ prompts/ pipeline/ skills/ codegraph/
│   └── sdk.py                       嵌入式 SDK
├── infra/                           基础设施
│   ├── orchestrator/                模型编排（llama.cpp / Strata / LM Studio / API）
│   ├── resources/                   异构资源池（ASR / TTS）
│   ├── policy/  store/  tasks/  gateway/  auth/  observability/
│   ├── runtime.py                   DI 容器与生命周期
│   └── models/                      ⚠️ 兼容 shim，新代码请直接用 infra.orchestrator
├── tests/                           90 个测试文件
└── docs/                            架构与维护文档（17 篇，已随仓库入库）
```

### 项目规模（实测）

| 模块 | 文件 | 行数 |
|---|---:|---:|
| `apps/dsn` | 253 | 58,158 |
| `apps/dsn_ui` | 29 | 11,613 |
| `apps/dsn_study` | 74 | 9,552 |
| `infra/` | 55 | 10,778 |
| `harness/` | 58 | 10,226 |
| `tests/` | 90 | 15,407 |
| 其余示例应用 | 24 | 4,154 |
| **合计** | **约 583** | **约 120k** |

---

## 测试

```bash
python -m pytest -q          # 全量，约 78 秒
python -m pytest -m known_broken   # 查看待重做的用例
```

当前基线：**547 通过 / 0 失败 / 0 收集错误**（另有 18 个按 marker 排除）。

> 仓库内置了 pytest 配置：`testpaths` 限定只扫 `tests/`，因此在根目录裸跑
> `pytest` 不再误入 `temp/`（那里的脚本会在**收集期真的调用外部 API**）。
> 运行前需 `pip install pytest`。详见 [docs/testing.md](docs/testing.md)。

---
## 前端开发

```bash
cd apps/dsn_ui/frontend
npm install
npm run dev      # 开发服务器
npm run build    # 构建并通过 scripts/sync-to-static.cjs 同步到 ../static/
```

前端源码目录 `apps/dsn_ui/frontend/` 是**被 .gitignore 忽略**的，仓库只提交
`apps/dsn_ui/static/` 下的构建产物。

---

## 关于文档的版本控制

**`docs/` 下的 17 篇架构与维护文档已随仓库入库**（2026-10-20 起）。

此前 `.gitignore` 里有 `/docs/` 一行，导致这些文档只存在于本地工作副本，
克隆仓库的新成员看不到任何架构信息。入库前已逐项核查过：
无密钥 / 无个人邮箱 / 无绝对家目录路径 / 无二进制文件。

`docs/archive/` 存的是**已被取代的旧版文档**与一次性完成记录，
其自带 `README.md` 明确标注「架构已过时，不要作为现状依据」，排查历史问题时可参考。

详见 [docs/maintenance.md](docs/maintenance.md) 的“文档与仓库卫生”一节。

---

## 许可证与状态

内部实验性项目，无公开许可证。部分子系统（`apps/dsn/pyncm`、`apps/dsn/psychoscope`、
`apps/dsn/world`）为 vendored 或实验性代码，维护时请先读对应说明再改动。
