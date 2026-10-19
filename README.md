# DSN-exp

> 一个跑在本地的智能体底座：统一的模型调度、上下文记忆、工具执行与多协议接口。

---

## 它解决什么问题

本地跑 AI 的常见困境是：每换一个模型就要重写一套接入代码，每加一项能力（记忆、语音、工具）
就要在业务里再叠一层胶水。DSN-exp 把这些收敛成**一层可复用的框架**，
让"让智能体跑起来"成为配置问题，而不是工程问题。

当前仓库同时承载了框架（AICF）与若干基于它构建的应用，其中 `dsn_ui` 是日常使用的主入口。

---

## 架构

基于 **AICF**（Agent Infrastructure Cybernetics Framework），三层单向依赖：

```
apps/          具体应用（业务语义）
   ↓
harness/       Agent 核心（智能体逻辑）
   ↓
infra/         基础设施（资源与运行时）
```

| 层 | 职责 | 不做什么 |
|---|---|---|
| **`apps/`** | 装配与业务实现：语音陪伴、Web 控制台、编码助手、学习系统 | 不重复造框架能力 |
| **`harness/`** | Agent 循环、工具、记忆、人格、提示词、上下文装配、管线 | 不掺入具体业务语义 |
| **`infra/`** | 模型编排与调度、异构资源池、存储、网关、鉴权、策略 | 不知道任何业务 |

> 设计契约是**单向向下**。当前有 2 处 `infra → harness` 的逆向依赖
> （`infra/observability/core.py`、`infra/cache.py`），属待收敛的技术债。

细节见 [docs/aicf-overview.md](docs/aicf-overview.md)。

---

## 能力全景

### 模型调度（`infra/orchestrator`）

统一编排四类后端，对上层暴露同一套契约（`IChatClient` / `IEmbeddingClient`）：

| 后端 | 说明 |
|---|---|
| **llama.cpp** | 本地 GGUF，支持分层卸载、张量拆分、mmproj 视觉 |
| **Strata** | 自研大模型引擎（125B 级），专家权重分层缓存 |
| **LM Studio** | 本地 GUI 模型库 |
| **OpenAI / Anthropic** | 远程 API，含 Responses 协议 |

调度器按**优先级 + 并发槽位**管理显存，支持常驻、即时回收、驱逐与自动恢复。
实测踩过的坑已固化为代码注释（端口占用、并发重复拉起、取消竞态等）。

### Agent 核心（`harness/`）

- **Agent 循环** — 多步推理、工具调用、步数预算与收束轮
- **工具系统** — 注册表、wire 名编码、两阶段 toolbox 激活、标准工具集
- **上下文装配** — 分段预算剪裁（备忘 / 摘要 / 原文 / 尾部），按优先级取舍
- **记忆与人格** — 向量记忆、弹性话题记忆、人格动力学
- **管线** — 插件索引、事件总线、输出渲染
- **SDK** — `create_agent` / `@tool` 嵌入式用法

详见 [docs/sdk_guide.md](docs/sdk_guide.md)。

### 应用（`apps/`）

| 应用 | 说明 |
|---|---|
| **`dsn_ui`** | Web 控制台：模型管理、对话、决策、资源调度（主入口） |
| `dsn` | 语音陪伴：实时语音、情绪系统、话题记忆 |
| `dsn_study` | 学习系统：题库、模拟考试、知识图谱 |
| `coding_agent` | 编码助手示例 |
| `densechat` | DenseChat WebUI 复刻 |
| `emotion_exp` | 情绪状态机实验 |

---

## 快速开始

### 环境

- Python **3.10+**（推荐 3.12）
- Node 18+（仅在需要重新构建前端时使用）

```bash
pip install -r requirements.txt
cp .env.example .env      # 填写 API Key 等
```

### 启动

```bash
python main.py                  # 默认应用（DSN 语音陪伴）
python main.py --app dsn_ui     # 指定应用
python main.py --list           # 列出全部应用
```

### Web 控制台

```bash
python -m apps.dsn_ui.server --host 0.0.0.0 --port 8888 --slots 2
```

打开 <http://127.0.0.1:8888>。技术栈为 FastAPI + SvelteKit 5。

---

## 模型接入

本地模型只需在 `apps/dsn/model_profiles/` 放一个 YAML，启动时自动注册：

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

远程 API 模型在设置页填 Base URL 与 Key 即可。

---

## 双系统对话

部分模型（如 JEV）在通用生成之外融合了**决策头**，能一次前向直接给出带概率的答案：

| 模式 | 端点 | 适用 |
|---|---|---|
| **System 2** | `POST /v1/chat/completions` | 常规对话、写作、代码，流式与图像 |
| **System 1** | `POST /v1/decide` | 是/否、多选、打分，返回校准概率 |

```bash
curl -X POST http://127.0.0.1:8888/v1/decide -H 'Content-Type: application/json' -d '{
  "type": "yes_no",
  "question": "这封邮件是否威胁取消订阅？",
  "state": "请今天退款，否则我们取消套餐。"
}'
# → {"answer": true, "probability": 0.9488}
```

Web 界面路径 `/#/decide`，支持图文决策。

---

## 目录结构

```
DSN-exp/
├── apps/                     业务应用
│   ├── dsn_ui/               Web 控制台（前后端）
│   │   ├── server.py         FastAPI 主服务（76 条路由）
│   │   ├── system1_api.py    System-1 决策接口
│   │   └── frontend/         SvelteKit 5（产物同步到 static/）
│   └── dsn/                  语音陪伴（实时语音 · 情绪 · 话题记忆）
├── harness/                  Agent 核心
│   ├── agent/                循环 · 子代理 · swarm
│   ├── tools/                工具注册表
│   ├── context_assembly.py   上下文预算剪裁
│   ├── memory/ · personality/ · prompts/ · pipeline/
│   └── sdk.py                嵌入式 SDK
├── infra/                    基础设施
│   ├── orchestrator/         模型编排（llama.cpp / Strata / LM Studio / API）
│   ├── resources/            异构资源池（ASR / TTS）
│   ├── store/ · gateway/ · auth/ · policy/
│   └── runtime.py            依赖注入与生命周期
├── docs/                     架构与 SDK 文档
├── tests/                    83 个测试文件
└── main.py                   启动入口
```

---

## 项目规模

| 模块 | 文件 | 行数 |
|---|---:|---:|
| `apps/dsn` | 253 | 58,865 |
| `apps/dsn_ui` | 22 | 10,815 |
| `apps/dsn_study` | 74 | 10,074 |
| `infra/orchestrator` | 15 | 5,776 |
| `harness/*` | 60+ | 9,500+ |
| `tests` | 83 | 14,476 |
| **合计** | **581** | **≈119,800** |

---

## 前端开发

```bash
cd apps/dsn_ui/frontend
npm install
npm run dev      # 开发服务器
npm run build    # 构建并同步到 ../static/
```

前端源码不入库（`.gitignore`），只有构建产物 `apps/dsn_ui/static/` 提交。

---

## 配置

环境变量优先，其次 `.env`：

| 变量 | 说明 | 默认 |
|---|---|---|
| `DSN_UI_HOST` | 监听地址 | `0.0.0.0` |
| `DSN_UI_PORT` | 端口 | `8888` |
| `DSN_UI_DEFAULT_SLOTS` | 并发模型槽位 | `2` |
| `DSN_UI_LLAMA_SERVER` | llama-server 路径 | `~/llama.cpp/build/bin/llama-server` |
| `DSN_UI_CORS_ORIGINS` | 允许的跨域来源 | 仅本机 |

完整清单见 `.env.example` 与 `apps/dsn_ui/config.py`。

---

## 文档

- [AICF 架构总览](docs/aicf-overview.md)
- [Harness 架构](docs/harness-architecture-current.md)
- [SDK 使用指南](docs/sdk_guide.md)
