<div align="center">
<img src="docs/header.svg" width="1200" alt="aicf-core — 本地 Agent 的底层引擎">
</div>

# aicf-core

> **是引擎，不是应用。** 场景无关的 Agent 内核：轮次循环、工具协议、上下文装配、
> 记忆、会话持久化、多智能体协作——只有这些，没有别的。

**AICF** = Agent Infrastructure Cybernetics Framework · Apache-2.0

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Local First](https://img.shields.io/badge/local--first-100%25-8A2BE2?style=for-the-badge)](docs/architecture.md)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue?style=for-the-badge)](LICENSE)
[![CI](https://github.com/ccjjfdyqlhy/aicf-core/actions/workflows/ci.yml/badge.svg)](https://github.com/ccjjfdyqlhy/aicf-core/actions/workflows/ci.yml)

---

## 一句话承诺

> **安全、幂等、可评测地跑完一次长任务。**

大多数 Agent 框架默认进程活着。这个不这么假设。

| | 承诺 | 你可以怎么验证 |
|---|---|---|
| **安全** | 每一次工具调用都过策略闸门；有副作用的要人点头；要进沙箱。**判定不出来就是拒绝。** | `aicf tool exec proc.run --args '{"command":"rm -rf /"}'` → 被拒 |
| **幂等** | 崩了能恢复，且不重复产生副作用。`effectful` 的调用**绝不**自动重放。 | `pytest tests/fault/` —— 子进程里真的 `kill -9` |
| **可评测** | 每次运行产出 trace；每次改动都被数据集打分，并被四闸门报告拦住。 | `aicf eval` → `aicf gate` |

---

## 九十秒

```bash
pip install aicf-core
```

```bash
# 1. 每个工具到底能干什么？副作用等级、沙箱档位、需要的授权范围。
aicf tool list

# 2. 试着跑个 shell。它有副作用 —— 所以要等人点头。
aicf tool exec proc.run --args '{"command":"rm -rf /"}' --policy strict
#    Error: 工具 proc.run 被策略拒绝（approval）：CLI 未开启 --yes

# 3. 跑一轮，留下 trace。
aicf run "总结一下这个仓库" --trace trace.jsonl

# 4. 用数据集打分（数据集随包分发）。
aicf eval --dataset basic --traces trace.jsonl --out run.json

# 5. 任何回归、成本超标或安全违规都会拦住发布。
aicf gate --run run.json --out gate.json
```

上面每一步都**不需要 API key** —— 走桩模型离线可跑。

---

## 安装

```bash
pip install aicf-core
```

装完就是整个库——Agent 内核 + 模型/工具/运行时层。
**不含任何应用代码和界面**：Web 控制台在独立的仓库里（见下表）。

可选 extra，用到哪块再装哪块：

```bash
pip install "aicf-core[personality]"   # 人格动态（PEV3）
pip install "aicf-core[decisions]"     # System-1 决策头
pip install "aicf-core[learning]"      # 轨迹 → 数据集 → 分层判官 → 晋级 闭环
pip install "aicf-core[finetune]"      # 本地 SFT（会拉 torch）
pip install "aicf-core[mcp]"           # 外部 MCP 工具源
pip install "aicf-core[all]"           # 全都要
```

---

## 只想写个 Agent？五个符号。

```python
from harness import create_agent, tool   # 你真正会写的三个
from harness.tools import ToolRegistry   # 自己管工具时才需要
from infra.models.base import IChatClient # 模型接口
```

| 符号 | 是什么 |
|---|---|
| `tool` | 把带类型的函数变成工具（schema 从签名自动生成） |
| `Agent` | 绑定了模型的 Agent —— `chat()` / `run()` / `chat_stream()` |
| `create_agent` | 一行工厂：模型 + key + 工具 |
| `ToolRegistry` | 工具表（只有自己注册工具时才需要） |
| `IChatClient` | 模型接口 —— 实现它就能接自己的后端 |

```python
from harness import create_agent, tool

@tool
def add(a: int, b: int) -> int:
    """加两个数。"""
    return a + b

agent = create_agent(
    model="deepseek-chat",
    base_url="https://api.deepseek.com/v1",
    api_key="sk-...",                 # 或者直接 export OPENAI_API_KEY
    tools=[add],
)

result = agent.run("17 + 25 等于几？")
print(result)                        # 结果表现得像字符串
```

任何 OpenAI 兼容端点都行。本地模型把 `base_url` 指向你的
`llama-server` / LM Studio，或者直接给 `create_agent` 传一个客户端
（`infra.orchestrator.LlamaCppChat`、`LMStudioChat`、`OpenAICompatClient` …）。

---

## 仓库结构（30 秒）

两层，依赖**单向向下**：

```
harness/   Agent 核心    轮次循环 · 工具协议 · 上下文 · 记忆 · 管线 · 会话 · SDK
   │                      不知道任何产品概念
   ▼
infra/     基础设施      模型路由 · 资源池 · 存储 · 网关 · 认证 · 策略
```

```
apps/  →  没了。Web 控制台在独立仓库：
```

| 仓库 | 是什么 |
|---|---|
| [`aicf-ui`](https://github.com/ccjjfdyqlhy/aicf-ui) | Web 控制台 —— 模型、对话、资源、System-1 决策 |

它只依赖 `aicf-core`，不依赖别的。

---

## 当前状态

`aicf-core` 目前是 **1.0.0rc2**。rc0 的完成定义是三条**可执行**的断言，
三条都已达成（每条都钉在一个测试上）：

1. 被 `kill -9` 一次的 Agent 仍能恢复并给出正确结果；
2. 每一次工具调用要么被审批放行、要么被拒绝 —— 且留下审计；
3. 这次运行能被一个 ≥30 case 的数据集打分，并产出一份四闸门报告。

**默认路径上这些保证是成立的**：`create_agent` 装出来的 Agent 带守卫，
`proc.run` 在工作区沙箱里跑，SDK 与 CLI 都会把工具意图写进 journal，
所以一次崩溃之后能算出「哪些事我可能已经做过了」。

**rc2** 补的是「应用的状态放在哪」：通用文档存储、不在项目里的状态目录，
以及真正生效的沙箱写权限档位。发布说明见
[docs/releases/v1.0.0rc2.md](docs/releases/v1.0.0rc2.md)。

下一步是 **rc1**：控制面（AgentArtifact 与生命周期）、Workflow / Planner
执行内核、Agent 身份与委托授权。计划、验收标准与每条工作流的状态都在
[docs/roadmap_1.0.0-rc0.md](docs/roadmap_1.0.0-rc0.md)。

---

## 开发

```bash
git clone https://github.com/ccjjfdyqlhy/aicf-core.git && cd aicf-core
pip install -e ".[mcp,anthropic,socks]"
pip install pytest pytest-asyncio
python -m pytest -q tests/
```

---

## 文档

| 我想… | 看这个 |
|---|---|
| 知道 1.0.0-rc0 在做什么、怎么验收 | [docs/roadmap_1.0.0-rc0.md](docs/roadmap_1.0.0-rc0.md) |
| 搞懂模块地图与依赖规则 | [docs/architecture.md](docs/architecture.md) |
| 搞懂安全模型（默认拒绝 / 审批 / 沙箱 / 审计） | [docs/security.md](docs/security.md) |
| 搞懂托管运行时（journal / checkpoint / 幂等 / 恢复） | [docs/runtime.md](docs/runtime.md) |
| 搞懂评测闭环（数据集 / 闸门 / run version / 回归） | [docs/evaluation.md](docs/evaluation.md) |
| 把核心当库用 | [docs/sdk_guide.md](docs/sdk_guide.md) |
| 深入 Agent 循环 / 工具 / 上下文 | [docs/harness.md](docs/harness.md) |
| 深入模型路由 / 资源 / 存储 | [docs/infra.md](docs/infra.md) |
| 改代码前先知道哪些坑别踩 | [docs/maintenance.md](docs/maintenance.md) |
| 配置项与环境变量 | [docs/configuration.md](docs/configuration.md) |
| 已知技术债与修复优先级 | [docs/technical-debt.md](docs/technical-debt.md) |

---

## 许可证

Apache-2.0
