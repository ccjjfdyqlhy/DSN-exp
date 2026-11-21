# Running Locally and Troubleshooting

> English translation of [../getting-started.md](../getting-started.md) — the Chinese original is authoritative.

> Reader: anyone running **aicf-core** on their own machine for the first time, and anyone stuck on environment problems.
>
> ⚠️ **As of 2026-11-18 this repository contains only the base libraries** (`harness` + `infra`).
> The four applications (console / voice / learning / coding assistant) have been split into
> their own repositories — see [split_migration.md](../split_migration.md).
> All commands in this document are run from the **repository root**.

---

## 1. Using core as a library

### 1.1 Python

Requires **3.10+**. First check your interpreter:

```bash
python3 --version        # 若系统只有 python3，下文命令请把 python 换成 python3
```

*(Inline comment: "if your system only has `python3`, replace `python` with `python3` in the commands below".)*

> ⚠️ **Common trap**: many Linux distributions do not provide a `python` command by
> default — only `python3`.

### 1.2 Installation

```bash
pip install -e ".[mcp,anthropic,socks]"   # 从源码装（含 MCP / Anthropic / SOCKS 三条可选线）
pip install -e .                            # 只要内核的话，最小依赖即可
```

*(Inline comments: "install from source (with the three optional extras MCP / Anthropic / SOCKS)" / "for just the core, minimal dependencies suffice".)*

Or install it directly (**the current release is 1.0.0**):

```bash
pip install "aicf-core @ git+https://github.com/ccjjfdyqlhy/aicf-core.git"
```

For the extras, see the [README](../../README_zh.md#-安装): `personality` / `decisions` / `learning` /
`finetune` / `mcp` / `anthropic` / `socks` / `all`.

### 1.3 Configuration

```bash
cp .env.example .env
```

At minimum, fill in these two items:

```ini
MAIN_MODEL_TYPE=openai
MAIN_MODEL_NAME=deepseek-v4-flash
OPENAI_API_KEY=sk-你的真实密钥
OPENAI_API_BASE=https://api.deepseek.com/v1
```

*(The API key placeholder reads `sk-你的真实密钥` — "sk-your-real-key".)*

`.env.example` has 400+ lines and 200+ variables, but **the overwhelming majority have
sensible defaults**. For the full breakdown see [configuration.md](../configuration.md).
> `.env` is ignored by `.gitignore`. **Never** put secrets into code or documentation.

### 1.4 Confirm the install works

```bash
python3 -c "import aicf; print('aicf', aicf.__version__)"           # 期望 1.0.0
python3 -c "from aicf.harness import create_agent; print('harness ok')"
python3 -c "import aicf.infra; print('infra ok')"
python3 -m pytest -q tests/                                          # 跑测试
```

*(Inline comments: "expected 1.0.0" / "run the tests".)*

### 1.5 Run a minimal agent

```python
from aicf.harness import create_agent
from aicf.harness.tools import tool_from_function

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

*(The docstring reads "Add two numbers."; the prompt asks "What is 17 + 25?"; the inline comment: "or `export OPENAI_API_KEY`".)*

---

## 2. Running the app (not in this repo)

the web console lives in its own repository and installs with `pip install -e .`:

| What you want to run | Repository | Start command | Default port |
|---|---|---|---|
| Web console | [`aicf-ui`](https://github.com/ccjjfdyqlhy/aicf-ui) | `python -m aicf_ui.server` | 8888 |

```bash
git clone https://github.com/ccjjfdyqlhy/aicf-ui.git && cd aicf-ui
pip install -e .
python -m aicf_ui.server --host 127.0.0.1 --port 8888
```

Open <http://127.0.0.1:8888> in a browser.

| Option | Default | Environment variable |
|---|---|---|
| `--host` | `0.0.0.0` | `DSN_UI_HOST` |
| `--port` | `8888` | `DSN_UI_PORT` |
| `--slots` | `2` | `DSN_UI_DEFAULT_SLOTS` |

> the console repository also provides `installer.py`, which creates a virtual
> environment, installs dependencies and starts the first run.

## 3. Connecting a model

### 3.1 Remote API only

Just fill in `OPENAI_API_KEY` / `OPENAI_API_BASE` / `MAIN_MODEL_NAME` in `.env` and you are done.
Any OpenAI-compatible endpoint works (DeepSeek, Qwen, vLLM, OneAPI, ...).

### 3.2 Local llama.cpp

1. Build llama.cpp and make sure `llama-server` is executable;
2. Put a YAML file into the model profile directory of the `aicf-ui` repository
   (the template lives in the same directory):

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

3. Restart `dsn_ui`; the model appears in the list automatically.

> the console repository owns the active model profile directory and its
> template. copy the template there and edit the paths before restarting.
> `python installer.py --doctor` in the console repository checks for dead paths.

### 3.3 Configure through the GUI (recommended for newcomers)

On first start, `dsn_ui` walks you through "configure a new instance": scanning local
GGUF files, registering local models, or adding a remote API provider. The relevant
endpoints live under `/api/onboarding/*`.

> By default only `~/.lmstudio/models` is scanned. Finding no models is expected
> behavior; use `DSN_UI_MODEL_ROOTS` to point at other directories
> (separated by `os.pathsep`).

---

## 4. Common problems

### Startup hangs / drops into the interactive onboarding

This is an **import-time side effect** of `aicf_dsn.main`: at module import time it
checks whether `OPENAI_API_KEY` in `.env` is valid, and if not, enters the onboarding flow.

**Impact**: anything that does `import aicf_dsn.main` triggers it (including tests and `/reboot`).
Avoid this when writing tests.

**Fix**: set `OPENAI_API_KEY` in `.env` to a non-placeholder value.

### The frontend reports `Unexpected token '<'`

The request hit the SPA catch-all, which returned `index.html` instead of JSON. Two possibilities:

1. **Route registration order is wrong**: all GET routes in `dsn_ui` must be registered
   before the catch-all;
2. **The endpoint does not exist at all**: for example, `/v1/embeddings` is not implemented
   (the `integration_api` module docstring claims it is, but in fact it is not).

To diagnose: `curl -i http://127.0.0.1:8888/你的路径` and check whether the response is HTML.
*(Your-path placeholder: `你的路径` means "your endpoint path".)*

### The model cannot call tools

When `tools` are passed but **`execution_mode` is not enabled**, the server executes no
tools and hands `tool_calls` back to the client. Check the `execution_mode` field of the
request body.

### Changed a setting / config but it does not take effect

Three high-frequency causes:

| Symptom | Cause |
|---|---|
| Changed `DSN_UI_MODEL_PROFILES_DIR`, no effect | The variable is not implemented; only the hard-coded path works |
| Edited `agent_settings.json` and it gets overwritten | The file is written as a **whole-file overwrite** |
| Changed the frontend source but the UI did not change | The backend only serves `static/`; you must run `npm run build` |

### WebSocket / SSE will not connect, or the stream breaks and duplicates

- Confirm the server was started as a single process;
- Check that `X-Conversation-Id` is consistent;
- To reconnect after a disconnect, resume with `/v1/stream?from=N`; the offset snaps
  to event boundaries automatically.

### VRAM is full / the model will not start

`ModelScheduler` manages things by priority + concurrency slots. Check two things:

1. Whether `--slots` is set higher than the GPU can handle;
2. Whether some **other** llama-server process is holding the port (the executable that
   `DSN_UI_LLAMA_SERVER` points to).

`dsn_ui`'s `/api/system/resources` shows live VRAM usage.

### The tests will not run

`pytest` is not a default dependency and needs a separate install: `pip install pytest`.
See [testing.md](../testing.md) for details.

---

## 5. General troubleshooting rules

1. **Read the warnings in the log first.** In this project, many subsystems that fail to
   initialize print one warning and then set themselves to `None` and keep starting up
   (world / tracking / semantic_cache / TTS all behave this way).
   The first suspect for "feature X does nothing" is the startup log.

2. **check which assembly path runs.** one product can carry more than one
   initialization path. confirm the one that actually executes before you edit.

3. **First confirm where the configuration is read from.** The truth is scattered across
   three places — `.env`, class attributes in each application repo's `config.py`,
   and the `condition` fields in `*.yaml` — and they can override one another.
