# 配置参考

> 读者：需要改配置、或排查「配置为什么不生效」的维护者。

---

## 一、配置从哪来（三条来源，可能互相覆盖）

```text
1. environment variables / .env   <- highest priority, most common
2. config.py constants            <- class attributes snapshotted at import
3. *.yaml                         <- model_profiles, plugin.yaml, skill.yaml
```

`.env` loading is application-owned. the console loads it before its config
class is evaluated, so the order is: process environment, then `.env`, then code
defaults.

### config classes snapshot at import

an application config class usually reads environment variables into class
attributes when the module is imported. therefore:

- changing `os.environ` at runtime does not affect an already imported config;
- changing `.env` after import has no effect until the process restarts.

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
| `DSN_UI_HOST` | `0.0.0.0` | console listen address |
| `DSN_UI_PORT` | `8888` | console port |
| `DSN_UI_DEFAULT_SLOTS` | `2` | concurrent model slots |
| `DSN_UI_LOG_LEVEL` | `INFO` | console log level |
| `DSN_UI_CORS_ORIGINS` | local only | extra allowed origins |
| `DSN_UI_DATA_DIR` | the console package data directory | data, memory, credentials and cache; tests use it to isolate state |

### 2.3 本地模型

| 变量 | 默认 | 说明 |
|---|---|---|
| `DSN_UI_LLAMA_SERVER` | `~/llama.cpp/build/bin/llama-server` | llama-server 可执行路径 |
| `LMSTUDIO_BASE_URL` | `http://localhost:4501` | LM Studio 端点 |
| `MAX_CONCURRENT_LM_MODELS` | `1` | 同时加载的本地模型数 |
| `MODEL_LOAD_TIMEOUT` | `180` | 模型加载超时（秒） |
| `MODEL_REQUEST_TIMEOUT` | `300` | 请求超时（秒） |
| `DSN_UI_MODEL_ROOTS` | `~/.lmstudio/models` | onboarding 扫描目录（`os.pathsep` 分隔） |

the model profile directory belongs to the console repository. check its
configuration module for the active path and the template directory.

this repository ships no model profiles with absolute paths. such paths only work
on the machine that wrote them, and elsewhere they produce entries that list but
never load.

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
| api key / model | `.env` or `export` | yes |
| console port | `export DSN_UI_PORT=...` | yes |
| local model list | the console model profile directory | yes, scanned at startup |
| remote provider | console settings, stored in `data/api_providers.json` | no |
| model launch arguments | console settings, stored in `data/model_launch_overrides.json` | no |
| plugin switch | the `condition` field in `plugin.yaml` | yes |
| skill enablement | `skill.yaml` or `/api/skill/*` | depends |
| prompts | the console prompt directory | yes |

---

## 四、排查「配置不生效」

按顺序问四个问题：

1. **did this process read the file?** config classes snapshot values at import.
2. **is something with higher priority overriding it?** a `*.yaml` `condition`, a
   request field, or `DSN_UI_API_MODE_LOCKED` can beat an environment variable.
3. **这个变量真的被实现了吗？** 见 [technical-debt.md](technical-debt.md#p1-3-声明了但不生效的字段)。
4. **这个功能真的在运行路径上吗？** 参考 [maintenance.md](maintenance.md) 的「多套实现」表。

---

## 五、密钥与凭据

### `dsn_ui` 的凭据是加密存储的

- Provider 名单（明文）：`aicf-ui 仓的 aicf_ui/data/api_providers.json`
- 凭据密文（Fernet）：`aicf-ui 仓的 aicf_ui/data/dsn_ui_secrets.db`
- 主密钥来源顺序：`DSN_UI_SECRET_KEY` 环境变量 → `aicf-ui 仓的 aicf_ui/data/.secret_key`

> ⚠️ **备份时必须连 `.secret_key` 一起备份。** 密钥丢失且没设 `DSN_UI_SECRET_KEY` 时，
> 所有 provider 的 base_url / api_key 都**无法恢复**，只能重新填。

### 不要提交的文件

`.env`、`*.key`、`*.enc`、`*.pem`、`*.crt`、`*.db` 都已在 `.gitignore` 中。
