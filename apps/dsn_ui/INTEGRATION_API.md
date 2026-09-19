# DSN 集成 API

dsn_ui 启动后对外暴露三类 API，可被 Open WebUI、Continue、Cline、LangChain、
Anthropic SDK 等标准客户端直接使用。

## 1. OpenAI Chat Completions 兼容

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/v1/models` | 模型列表（llama-ui 兼容格式） |
| GET  | `/v1/integration/models` | 模型列表 + 加载状态 + **多模态能力** |
| POST | `/v1/chat/completions` | 对话补全（流式/非流式，支持图像） |

```bash
curl http://127.0.0.1:8888/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"bonsai:bonsai2:27B","messages":[{"role":"user","content":"hi"}],"stream":false}'
```

### 图像输入（多模态）

`content` 传数组，含 `image_url` 内容块。**图像结构会被完整保留**，
不会像早期版本那样被拍平成文本丢弃：

```json
{
  "model": "bonsai:bonsai2:27B",
  "messages": [{"role": "user", "content": [
    {"type": "text", "text": "这张图里有什么？"},
    {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}
  ]}]
}
```

## 2. Anthropic Messages 兼容

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/v1/messages` | Anthropic Messages API（流式/非流式） |

支持 Anthropic 的 content block：`text` / `image`(base64 或 url) /
`tool_use` / `tool_result`，以及 `system` 字符串或数组。

流式返回遵循 Anthropic 事件序列：
`message_start → content_block_start → content_block_delta… →
content_block_stop → message_delta → message_stop`

```bash
curl http://127.0.0.1:8888/v1/messages \
  -H 'Content-Type: application/json' \
  -d '{"model":"bonsai:bonsai2:27B","max_tokens":256,
       "messages":[{"role":"user","content":"hi"}]}'
```

## 3. ★ DSN 专有：显存/模型管理

普通 OpenAI 兼容服务无法显式控制显存；dsn_ui 提供以下端点：

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/v1/models/load` | 加载模型到显存 |
| POST | `/v1/models/unload` | 从显存卸载，释放槽位 |
| POST | `/api/integration/models/reload` | 卸载后重新加载（应用新启动参数） |
| GET  | `/api/integration/capabilities` | 能力自描述，供集成方探测 |
| GET  | `/api/integration/bonsai` | Bonsai-demo 集成状态 |

```bash
# 加载（wait=false 则立即返回，异步完成）
curl -X POST http://127.0.0.1:8888/v1/models/load \
  -H 'Content-Type: application/json' \
  -d '{"model":"bonsai:bonsai2:27B","wait":true}'

# 卸载
curl -X POST http://127.0.0.1:8888/v1/models/unload \
  -H 'Content-Type: application/json' \
  -d '{"model":"bonsai:bonsai2:27B"}'
```

> `reload` 的典型用途：切换「卸载上下文到 CPU 内存」等启动参数后，
> 一次性重建模型实例使其生效。

## 4. Bonsai-demo 集成（自定义 llama.cpp + 本地多模态）

dsn_ui 启动时自动扫描 `~/Bonsai-demo` 并注册其模型，**无需手动配置**：

* **自定义二进制**：优先使用 demo 自带的 `bin/{cuda,vulkan,rocm,hip,cpu,mac}/llama-server`，
  以获得其三进制量化与 mtmd 多模态支持（系统 llama.cpp 未必兼容）。
* **自动注入 `LD_LIBRARY_PATH`**：该二进制的私有 `.so` 在同目录，
  不加会报 `error while loading shared libraries: libllama.so.0`。
* **多模态**：同目录存在 `*mmproj*.gguf` 时自动附加 `--mmproj` 启用图像输入。

### 相关环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `BONSAI_DEMO_DIR` | `~/Bonsai-demo` | demo 目录 |
| `BONSAI_BIN` | 自动探测 | 显式指定 llama-server 路径 |
| `DSN_BONSAI_NGL` | `999` | GPU 分层数（显存不足时调小，如 `20`） |
| `DSN_BONSAI_CTX` | `8192` | 上下文长度 |

### 显存提示

Bonsai 27B 在 11GB 卡上较吃紧。若同时运行多个实例会 CUDA OOM，此时：

1. 调小 `DSN_BONSAI_NGL`；
2. 或开启硬件页的「卸载上下文到 CPU 内存」降低 KV 占用；
3. 或先用 `/v1/models/unload` 释放其它模型。

> 端口冲突：若 8080 已被**外部** llama-server 占用（例如手动跑了
> `start_llama_server.sh`），DSN 会在日志中告警 —— 此时请求会命中那个
> 外部服务而非 DSN 托管实例。需要独立托管请改用其它端口。

## 5. 客户端接入示例

### Anthropic SDK

```python
import anthropic
client = anthropic.Anthropic(base_url="http://127.0.0.1:8888", api_key="dummy")
msg = client.messages.create(
    model="bonsai:bonsai2:27B", max_tokens=256,
    messages=[{"role": "user", "content": "你好"}],
)
print(msg.content[0].text)
```

### OpenAI SDK

```python
from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:8888/v1", api_key="dummy")
r = client.chat.completions.create(
    model="bonsai:bonsai2:27B",
    messages=[{"role": "user", "content": "你好"}],
)
print(r.choices[0].message.content)
```
