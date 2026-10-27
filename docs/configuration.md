# 配置参考

> 读者：需要改配置、或排查「配置为什么不生效」的维护者。

---

## 一、配置从哪来（三条来源，可能互相覆盖）

```
1. 环境变量 / .env        ← 优先级最高，最常用
         ↓
2. apps/<app>/config.py    ← 类是「import 时快照」的类属性
         ↓
3. *.yaml（model_profiles、plugin.yaml、skill.yaml）
```

### 各应用读 .env 的方式并不统一

| 应用 | 读取方式 | 备注 |
|---|---|---|
| `dsn` | `apps/dsn/config.py` 中 `load_dotenv(repo_root/.env)` | 导入时快照 |
| `dsn_study` | `apps/dsn_study/config.py` | 同上 |
| `densechat` | `apps/densechat/config.py` + `server.py::main` 显式 `load_dotenv()` | |
| `emotion_exp` | `entry.py` 顶部 `load_dotenv()` | |
| `dsn_ui` | ✅ 经 `apps/dsn_ui/dotenv_boot.py` 加载（在 `config.py` 顶部被 import 时触发） | 2026-10 已修复 |

> ⚠️ **`dsn_ui` 的 `.env` 加载（2026-10 已修复）**：`UIConfig` 是导入时求值的类属性，
> 因此 `load_dotenv` 必须发生在它之前。现在 `apps/dsn_ui/config.py` 顶部会 import
> `apps/dsn_ui/dotenv_boot`，后者在 import 时加载仓库根的 `.env`。
>
> 优先级为：**进程环境变量 > `.env` > 代码内默认值**
>（`dotenv_boot.load_env(override=False)`）。

### `Config` 是「import 时快照」

`apps/dsn/config.py` 在模块导入时就把环境变量读成类属性。因此：

- 运行时改 `os.environ` **不会**影响已经导入的 `Config`；
- `/config set` 写 `.env` 后，对当前进程是否生效**未验证**。

---

## 二、最关键的配置项

`.env.example` 有 344 行、200+ 变量，但**大多数有合理默认值**。真正需要关心的是这些：

### 2.1 模型（必填）

| 变量 | 说明 | 示例 |
|---|---|---|
| `MAIN_MODEL_TYPE` | 主对话后端 | `openai` / `lmstudio` |
| `MAIN_MODEL_NAME` | 模型 ID | `deepseek-v4-flash` |
| `OPENAI_API_KEY` | 密钥（**必填**） | `sk-...` |
| `OPENAI_API_BASE` | 兼容端点，**不含** `/chat/completions` | `https://api.deepseek.com/v1` |

### 2.2 服务与端口

| 变量 | 默认 | 说明 |
|---|---|---|
| `SERVER_HOST` | `0.0.0.0` | dsn / dsn_study 监听地址 |
| `SERVER_PORT` | `5000` | dsn / dsn_study 端口 |
| `DSN_UI_HOST` | `0.0.0.0` | dsn_ui 监听地址 |
| `DSN_UI_PORT` | `8888` | dsn_ui 端口 |
| `DSN_UI_DEFAULT_SLOTS` | `2` | 并发模型槽位 |
| `DSN_UI_LOG_LEVEL` | `INFO` | dsn_ui 日志级别 |
| `DSN_UI_CORS_ORIGINS` | 仅本机 | 额外放行的跨域来源 |
| `DSN_UI_DATA_DIR` | `apps/dsn_ui/data` | 数据目录（记忆/凭据/缓存）。**测试用此变量隔离** |
| `DENSECHAT_PORT` | `8080` | densechat 端口 |

### 2.3 本地模型

| 变量 | 默认 | 说明 |
|---|---|---|
| `DSN_UI_LLAMA_SERVER` | `~/llama.cpp/build/bin/llama-server` | llama-server 可执行路径 |
| `LMSTUDIO_BASE_URL` | `http://localhost:4501` | LM Studio 端点 |
| `MAX_CONCURRENT_LM_MODELS` | `1` | 同时加载的本地模型数 |
| `MODEL_LOAD_TIMEOUT` | `180` | 模型加载超时（秒） |
| `MODEL_REQUEST_TIMEOUT` | `300` | 请求超时（秒） |
| `DSN_UI_MODEL_ROOTS` | `~/.lmstudio/models` | onboarding 扫描目录（`os.pathsep` 分隔） |

> ⚠️ `DSN_UI_MODEL_PROFILES_DIR` 在注释里出现但**未实现**。生效的 profile 目录
> 永远是 `apps/dsn/model_profiles/`。

### 2.4 Agent 行为

| 变量 | 默认 | 说明 |
|---|---|---|
| `AGENT_MAX_STEPS` | — | 单次任务最大工具调用步数；**0 或负数 = 不限制** |
| `AGENT_TOKEN_BUDGET` | — | Token 预算 |
| `TOOLBOX_ENABLED` | — | 是否启用两阶段工具激活 |
| `TOOL_CALL_MODE` | — | `native` / `tagged` 等工具调用协议 |

### 2.5 记忆与话题

| 变量 | 默认 | 说明 |
|---|---|---|
| `MEMORY_ENABLED` | `true` | 记忆总开关 |
| `MEMORY_EMBEDDING_ENABLED` | `false` | 启用向量检索（需 embedding 模型） |
| `MEMORY_SEARCH_THRESHOLD` | `0.5` | 检索相似度阈值 |
| `TOPIC_ENABLED` | `true` | 话题系统开关 |
| `TOPIC_IDLE_SECONDS` | `1800` | 静默多久划新话题 |
| `TOPIC_MAX_VERBATIM_CHARS` | `6000` | 话题原文注入预算（字符） |
| `TOPIC_SUMMARY_CHARS` | `2000` | 闭锁话题摘要预算 |

### 2.6 语音（ASR / TTS）

| 变量 | 说明 |
|---|---|
| `ASR_ENABLED` / `ASR_DEVICE` / `ASR_GPU_ID` | ASR 开关与设备 |
| `TTS_ENABLED` / `TTS_BASE_URL` | TTS 开关与端点 |
| `TTS_PROBE_*` | TTS 就绪探测的重试与退避 |

### 2.7 安全

| 变量 | 说明 |
|---|---|
| `JWT_SECRET` | **生产环境必须替换**为足够长的随机串 |
| `AUTH_SESSION_DAYS` | 会话有效期 |
| `AUTH_TOTP_ISSUER` | TOTP 发行者名 |
| `DSN_UI_SECRET_KEY` | dsn_ui 凭据加密主密钥（**丢失则 provider 密钥不可恢复**） |

### 2.8 维护与休眠

| 变量 | 说明 |
|---|---|
| `MAINTENANCE_ENABLED` | 维护系统开关 |
| `MAINTENANCE_SCHEDULE_STRATEGY` | 调度策略 |
| `MAINTENANCE_IDLE_TIMEOUT_MINUTES` | 空闲多久进入维护 |

### 2.9 外部 MCP 工具源（`mcp_servers.yaml`）

外部 MCP 服务器**不走 `.env`**，声明在仓库根 `mcp_servers.yaml`
（格式示例齐全，抄注释里的样例改即可）。要点：

| 字段 | 说明 |
|---|---|
| `name` / `transport` | 服务器短名与传输：`stdio` / `http` / `sse` |
| `command` / `args` / `env` / `cwd` | stdio 子进程声明 |
| `url` / `headers` | http / sse 目标地址与请求头 |
| `call_timeout` / `connect_timeout` | 单次调用 / 建连超时（秒，默认 120 / 30） |
| `tool_allowlist` / `tool_blocklist` | 注册范围过滤 |

- 密钥不写进文件：字符串里的 `${VAR}` 加载时从环境变量展开；
- 依赖官方 SDK：`pip install "mcp>=1.2"`（未装时仅外部 MCP 不可用）；
- 接入语义与惰性连接的设计见 [harness.md §4.5](harness.md)。

---

## 三、配置生效路径速查

| 你想改… | 改哪里 | 需要重启？ |
|---|---|---|
| API Key / 模型 | `.env`（dsn/dsn_study）或 `export`（dsn_ui） | 是 |
| dsn_ui 端口 | `export DSN_UI_PORT=...` | 是 |
| 本地模型清单 | `apps/dsn/model_profiles/*.yaml` | 是（dsn_ui 启动时扫描） |
| 远程 Provider | dsn_ui 设置页 → 存到 `data/api_providers.json` | 否 |
| 模型启动参数 | dsn_ui 界面 → `data/model_launch_overrides.json` | 否 |
| 插件开关 | `plugin.yaml` 的 `condition` | 是 |
| 技能启用 | `skill.yaml` 或 `/api/skill/*` | 视情况 |
| 提示词 | `apps/dsn/prompt/prompts/{core,capabilities,extensions}/` | 是 |

---

## 四、排查「配置不生效」

按顺序问四个问题：

1. **这个进程真的读了这个文件吗？** `dsn_ui` 不读 `.env`；`Config` 是导入时快照。
2. **有更高优先级的东西覆盖它吗？** `*.yaml` 的 `condition`、请求体字段、
   `DSN_UI_API_MODE_LOCKED` 都可能压过环境变量。
3. **这个变量真的被实现了吗？** 见 [technical-debt.md](technical-debt.md#p1-3-声明了但不生效的字段)。
4. **这个功能真的在运行路径上吗？** 参考 [maintenance.md](maintenance.md) 的「多套实现」表。

---

## 五、密钥与凭据

### `dsn_ui` 的凭据是加密存储的

- Provider 名单（明文）：`apps/dsn_ui/data/api_providers.json`
- 凭据密文（Fernet）：`apps/dsn_ui/data/dsn_ui_secrets.db`
- 主密钥来源顺序：`DSN_UI_SECRET_KEY` 环境变量 → `apps/dsn_ui/data/.secret_key`

> ⚠️ **备份时必须连 `.secret_key` 一起备份。** 密钥丢失且没设 `DSN_UI_SECRET_KEY` 时，
> 所有 provider 的 base_url / api_key 都**无法恢复**，只能重新填。

### 不要提交的文件

`.env`、`*.key`、`*.enc`、`*.pem`、`*.crt`、`*.db` 都已在 `.gitignore` 中。
