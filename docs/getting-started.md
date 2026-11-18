# 本地运行与排障

> 读者：第一次在本机把 **aicf-core** 跑起来的人，以及被环境问题卡住的人。
>
> ⚠️ **2026-11-18 起本仓只有底层库**（`harness` + `infra`）。
> 四个应用（控制台 / 语音 / 学习 / 编码助手）已拆到各自的仓库，
> 见 [split_migration.md](split_migration.md)。本文命令都在**本仓根目录**执行。

---

## 一、把 core 当库用

### 1.1 Python

要求 **3.10+**。先确认你的解释器：

```bash
python3 --version        # 若系统只有 python3，下文命令请把 python 换成 python3
```

> ⚠️ **常见坑**：很多 Linux 发行版默认不提供 `python` 这个命令，只有 `python3`。

### 1.2 安装

```bash
pip install -e ".[mcp,anthropic,socks]"   # 从源码装（含 MCP / Anthropic / SOCKS 三条可选线）
pip install -e .                            # 只要内核的话，最小依赖即可
```

或者直接从 PyPI 装（**当前发布版是 0.6.2**）：

```bash
pip install "aicf-core @ git+https://github.com/ccjjfdyqlhy/aicf-core.git"
```

extra 说明见 [README](../README_zh.md#-安装)：`personality` / `decisions` / `learning` /
`finetune` / `mcp` / `anthropic` / `socks` / `all`。

### 1.3 配置

```bash
cp .env.example .env
```

至少填这两项：

```ini
MAIN_MODEL_TYPE=openai
MAIN_MODEL_NAME=deepseek-v4-flash
OPENAI_API_KEY=sk-你的真实密钥
OPENAI_API_BASE=https://api.deepseek.com/v1
```

`.env.example` 有 400+ 行、200+ 个变量，但**绝大多数都有合理默认值**。
完整分类见 [configuration.md](configuration.md)。
> `.env` 已被 `.gitignore` 忽略。**不要**把密钥写进代码或文档。

### 1.4 确认装好了

```bash
python3 -c "import harness; print('harness', harness.__version__)"   # 期望 0.6.2
python3 -c "import infra; print('infra ok')"
python3 -m pytest -q tests/                                          # 跑测试
```

### 1.5 跑一个最小 Agent

```python
from harness import create_agent
from harness.tools import tool_from_function

def add(a: int, b: int) -> int:
    """把两个数相加。"""
    return a + b

agent = create_agent(
    model="deepseek-chat",
    base_url="https://api.deepseek.com/v1",
    api_key="sk-...",                 # 或 export OPENAI_API_KEY
    tools=[tool_from_function(add)],
)
print(agent.run("17 + 25 等于多少？").reply)
```

---

## 二、跑应用（不在本仓）

the web console lives in its own repository and installs with `pip install -e .`:

| 想跑什么 | 仓库 | 启动命令 | 默认端口 |
|---|---|---|---|
| Web 控制台 | [`aicf-ui`](https://github.com/ccjjfdyqlhy/aicf-ui) | `python -m aicf_ui.server` | 8888 |

```bash
git clone https://github.com/ccjjfdyqlhy/aicf-ui.git && cd aicf-ui
pip install -e .
python -m aicf_ui.server --host 127.0.0.1 --port 8888
```

浏览器打开 <http://127.0.0.1:8888>。

| 参数 | 默认 | 环境变量 |
|---|---|---|
| `--host` | `0.0.0.0` | `DSN_UI_HOST` |
| `--port` | `8888` | `DSN_UI_PORT` |
| `--slots` | `2` | `DSN_UI_DEFAULT_SLOTS` |

> the console repository also provides `installer.py`, which creates a virtual
> environment, installs dependencies and starts the first run.

## 三、接入模型

### 3.1 只接远程 API

填好 `.env` 的 `OPENAI_API_KEY` / `OPENAI_API_BASE` / `MAIN_MODEL_NAME` 即可。
任何 OpenAI 兼容端点都行（DeepSeek、Qwen、vLLM、OneAPI……）。

### 3.2 接本地 llama.cpp

1. 编译好 llama.cpp，确认 `llama-server` 可执行；
2. 在 `aicf-ui` 仓的 model profile 目录放一个 YAML（模板同目录）：

```yaml
model: my-model
engine: llama_cpp
priority: 80
orchestrated: true

llama_config:
  binary_path: ~/llama.cpp/build/bin/llama-server
  model_path: /absolute/path/to/model.gguf
  n_gpu_layers: 99
  ctx_size: 32768
```

3. 重启 `dsn_ui`，模型会自动出现在列表里。

> the console repository owns the active model profile directory and its
> template. copy the template there and edit the paths before restarting.
> `python installer.py --doctor` in the console repository checks for dead paths.

### 3.3 用图形界面配置（推荐新手）

`dsn_ui` 首次启动会引导「配置新实例」：扫描本地 GGUF、注册本地模型、
或添加远程 API Provider。相关端点在 `/api/onboarding/*`。

> 默认只扫描 `~/.lmstudio/models`。扫描不到模型是预期行为，
> 可用 `DSN_UI_MODEL_ROOTS` 指定其它目录（`os.pathsep` 分隔）。

---

## 四、常见问题

### 启动就卡住 / 进入交互式引导

这是 `aicf_dsn.main` 的**导入期副作用**：模块导入时就检查 `.env` 里
`OPENAI_API_KEY` 是否有效，无效则进入 onboarding 流程。

**影响**：任何 `import aicf_dsn.main`（包括测试、`/reboot`）都会触发。写测试时要避开。

**解决**：把 `.env` 的 `OPENAI_API_KEY` 填成非占位值。

### 前端报 `Unexpected token '<'`

说明请求打到了 SPA catch-all，返回了 `index.html` 而不是 JSON。两种可能：

1. **路由注册顺序错了**：`dsn_ui` 的所有 GET 路由必须在 catch-all 之前注册；
2. **接口根本不存在**：比如 `/v1/embeddings` 并未实现（`integration_api` 的
   模块 docstring 声称有，但实际没有）。

排查：`curl -i http://127.0.0.1:8888/你的路径` 看返回是不是 HTML。

### 模型调不了工具

传了 `tools` 但**没开 `execution_mode`** 时，服务端不会执行任何工具，
而是把 `tool_calls` 交还给客户端。检查请求体的 `execution_mode`。

### 改了口令/配置但不生效

三个高频原因：

| 现象 | 原因 |
|---|---|
| 改了 `DSN_UI_MODEL_PROFILES_DIR` 没反应 | 该变量未实现，只有硬编码路径生效 |
| 改了 `agent_settings.json` 被覆盖 | 该文件是**整文件覆盖**写入 |
| 改了前端源码但界面没变 | 后端只 serve `static/`，必须 `npm run build` |

### WebSocket / SSE 连不上或断流重复

- 确认是单进程启动；
- 检查 `X-Conversation-Id` 是否一致；
- 断线重连用 `/v1/stream?from=N` 续读，偏移会自动吸附到事件边界。

### 显存被占满 / 模型起不来

`ModelScheduler` 按优先级 + 并发槽位管理。检查两件事：

1. `--slots` 是否设得比显卡能承受的多；
2. 是否有**别的** llama-server 进程占着端口（`DSN_UI_LLAMA_SERVER` 指向的可执行文件）。

`dsn_ui` 的 `/api/system/resources` 能看到实时显存占用。

### 测试跑不起来

`pytest` 不是默认依赖，需要单独安装：`pip install pytest`。详见 [testing.md](testing.md)。

---

## 五、排障总则

1. **先看日志里的 warning。** 本项目大量子系统初始化失败只打一条 warning 然后
   置为 `None` 继续启动（world / tracking / semantic_cache / TTS 都是这样）。
   「某功能没反应」的第一嫌疑是启动日志。

2. **check which assembly path runs.** one product can carry more than one
   initialization path. confirm the one that actually executes before you edit.

3. **先确认配置从哪读。** 真相分散在 `.env`、各应用仓 `config.py` 的类属性、
   以及 `*.yaml` 的 `condition` 三处，可能互相覆盖。
