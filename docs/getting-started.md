# 本地运行与排障

> 读者：第一次在本机把这个项目跑起来的人，以及被环境问题卡住的人。
> 所有命令都在仓库根目录执行。

---

## 一、环境准备

### 1.1 Python

要求 **3.10+**。本仓库作者环境实测为 **3.12**（`~/anaconda3`）。

先确认你的解释器：

```bash
python3 --version        # 若系统只有 python3，下文命令请把 python 换成 python3
```

> ⚠️ **常见坑**：很多 Linux 发行版默认不提供 `python` 这个命令，只有 `python3`。
> README 里写的 `python main.py` 在这类机器上要写成 `python3 main.py`。

### 1.2 安装依赖

```bash
pip install -r requirements.txt   # 运行框架与全部应用所需
pip install -e .                  # 可选：以 SDK 方式安装 harness + infra
```

> `pip install -e .` 只会安装 **框架**（`harness` + `infra`）及其最小依赖，
> **不含** Flask/FastAPI 等应用依赖。想跑 Web 界面仍然需要 `requirements.txt`。

> ⚠️ `requirements.txt` 里的版本号是**精确钉死**的（`openai==2.38.0`、
> `numpy==1.26.4` 等），等于把作者那台机器冻住了。换机器装不上时，
> 先怀疑的是这些钉子，而不是你的环境：
>
> ```bash
> pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple   # 换镜像
> pip install -r requirements.txt --upgrade                                     # 放开版本约束
> ```
>
> 其中 `numpy==1.26.4` 没有 Python 3.13+ 的 wheel，
> `cryptography==50.0.0` 在部分平台需要 Rust 工具链。
>
> **推荐直接用一键安装器**，它会建独立虚拟环境并按 `requirements.txt` 安装：
>
> ```bash
> python3 installer.py
> ```
>
> 想先体检再决定：`python3 installer.py --doctor`（只读，不改动任何东西）。

### 1.3 配置

```bash
cp .env.example .env
```

然后编辑 `.env`，**至少**填写这两项：

```ini
MAIN_MODEL_TYPE=openai
MAIN_MODEL_NAME=deepseek-v4-flash
OPENAI_API_KEY=sk-你的真实密钥
OPENAI_API_BASE=https://api.deepseek.com/v1
```

`.env.example` 有 344 行、200+ 个变量，但**绝大多数都有合理默认值**。
完整的变量分类说明见 [configuration.md](configuration.md)。

> `.env` 已被 `.gitignore` 忽略，不会误提交。**不要**把密钥写进代码或文档。

### 1.4 确认装好了

```bash
python3 -c "import fastapi, flask, openai, yaml, dotenv; print('deps ok')"
python3 -c "import harness; print('harness', harness.__version__)"   # 期望 0.5.0
python3 main.py --list
python3 installer.py --doctor                                    # 环境体检（只读）
```

`--list` 的预期输出（7 个应用）：

```text
  coding_agent    基于 harness 的 coding agent 示例
  densechat       基于 harness 复刻的 DenseChat WebUI（代码助手）
  dsn            *  DSN 语音陪伴应用（默认）
  dsn_study       DSN 学习特化应用（题库、模拟考试、知识图谱）
  dsn_ui          现代化统一 Web 控制台与模型调度交互界面
  emotion_exp     基于 harness 话题上下文与情绪状态机的伴侣 Agent
  text_agent      harness 参考应用（纯文本 agent）
```

---

## 二、跑起来

### 2.1 最快验证：不需要任何 API Key

```bash
python3 -m apps.emotion_exp
```

没有 `OPENAI_API_KEY` 时它会自动降级到 `StubChatClient`（固定回复），
**因此一定能启动成功**。用它验证「框架能跑」是最快的方式。

### 2.2 Web 控制台（日常主入口）

```bash
python3 -m apps.dsn_ui.server --host 127.0.0.1 --port 8888 --slots 2
```

浏览器打开 <http://127.0.0.1:8888>。

| 参数 | 默认 | 环境变量 |
|---|---|---|
| `--host` | `0.0.0.0` | `DSN_UI_HOST` |
| `--port` | `8888` | `DSN_UI_PORT` |
| `--slots` | `2` | `DSN_UI_DEFAULT_SLOTS` |

> ⚠️ 必须**单进程**运行。SSE 广播与流会话注册表都是进程内单例，
> 用 uvicorn 多 worker 或 gunicorn 会破坏断线重连。

### 2.3 其他应用

```bash
python3 main.py --app dsn_study      # 学习助手（Flask，:5000）
python3 main.py                      # DSN UI 网页控制台（默认，:8888）
python3 main.py --app dsn            # DSN 语音陪伴（:5000，需终端）
python3 -m apps.coding_agent         # 编码助手 REPL
python3 -m apps.densechat            # DenseChat WebUI（:8080）
```

> ⚠️ `dsn` 与 `dsn_study` **默认端口都是 5000**，不要同时启动。

### 2.3.1 仓库级引导（按需求自动配置）

不确定该开哪些能力时，先运行根目录的 Textual TUI：

```bash
python3 onboarding.py            # 询问需求 → 选能力 → 确认计划 → 自动执行
python3 onboarding.py --list     # 只列出目标 / 应用 / 能力
python3 onboarding.py --check    # 非交互检查环境与已有资源
```

它会按你的选择写入 `.env`、安装依赖、克隆 llama.cpp / GPT-SoVITS、
下载 GGUF 模型并生成 `apps/dsn/model_profiles/onboarding_*.yaml`。
所有仓库克隆与下载都会在执行前列出，确认后才开始；已存在的文件会跳过。


### 2.4 端口一览

| 端口 | 服务 | 开关 |
|---|---|---|
| 8888 | dsn_ui Web 控制台 | `DSN_UI_PORT` |
| 5000 | dsn 主 API / dsn_study Web | `SERVER_PORT` |
| 5050 | dsn 调试接口 | `DEBUG_PLAY_AS_MODEL=true` |
| 8008 | dsn 管理后台 | `WEB_ADMIN_ENABLED=true` |
| 8080 | densechat | `DENSECHAT_PORT` |
| 4501 | LM Studio（被连接） | `LMSTUDIO_BASE_URL` |

---

## 三、接入模型

### 3.1 只接远程 API

填好 `.env` 的 `OPENAI_API_KEY` / `OPENAI_API_BASE` / `MAIN_MODEL_NAME` 即可。
任何 OpenAI 兼容端点都行（DeepSeek、Qwen、vLLM、OneAPI……）。

### 3.2 接本地 llama.cpp

1. 编译好 llama.cpp，确认 `llama-server` 可执行；
2. 在 `apps/dsn/model_profiles/` 放一个 YAML（模板见 `apps/dsn/model_profiles.example/`）：

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

> ⚠️ `apps/dsn/model_profiles/` 是**唯一生效的** profile 目录。
> `config.py` 注释里提到的 `DSN_UI_MODEL_PROFILES_DIR` 环境变量**并未实现**，改了不生效。
>
> 模板在 `apps/dsn/model_profiles.example/`，复制过去并改掉路径才会生效。
> 用 `python3 installer.py --doctor` 可以提前查出哪些 profile 的路径在本机不存在。

### 3.3 用图形界面配置（推荐新手）

`dsn_ui` 首次启动会引导「配置新实例」：扫描本地 GGUF、注册本地模型、
或添加远程 API Provider。相关端点在 `/api/onboarding/*`。

> 默认只扫描 `~/.lmstudio/models`。扫描不到模型是预期行为，
> 可用 `DSN_UI_MODEL_ROOTS` 指定其它目录（`os.pathsep` 分隔）。

---

## 四、常见问题

### 启动就卡住 / 进入交互式引导

这是 `apps.dsn.main` 的**导入期副作用**：模块导入时就检查 `.env` 里
`OPENAI_API_KEY` 是否有效，无效则进入 onboarding 流程。

**影响**：任何 `import apps.dsn.main`（包括测试、`/reboot`）都会触发。写测试时要避开。

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

2. **先确认走的哪条装配路径。** 同一个应用可能有多套初始化逻辑（`dsn` 有三套），
   行为不一致时先确认你改的是被实际执行的那一套。

3. **先确认配置从哪读。** 真相分散在 `.env`、`apps/*/config.py` 的类属性、
   以及 `*.yaml` 的 `condition` 三处，可能互相覆盖。
