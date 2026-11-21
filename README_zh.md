<div align="center">

# aicf-core

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![CI](https://img.shields.io/github/actions/workflow/status/ccjjfdyqlhy/aicf-core/ci.yml?branch=main&label=CI&style=for-the-badge)](https://github.com/ccjjfdyqlhy/aicf-core/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/endpoint?url=https%3A%2F%2Fccjjfdyqlhy.github.io%2Faicf-core%2Ftests.json)](https://github.com/ccjjfdyqlhy/aicf-core/actions/workflows/ci.yml)
[![Local First](https://img.shields.io/badge/local--first-100%25-8A2BE2?style=for-the-badge)](docs/architecture.md)
[![Modalities](https://img.shields.io/badge/modalities-text%20%C2%B7%20speech%20%C2%B7%20vision-8A2BE2?style=for-the-badge)](docs/infra.md)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue?style=for-the-badge)](LICENSE)

**把 Agent 稳定到打不死的那层地基。**
特化给陪伴式系统 —— 长期在线，随叫随到。

[English](README.md) | [简体中文]

</div>

## aicf-core 是什么

aicf-core 是特化做一件事的 Agent 基础设施：**长期在线、随时响应的陪伴式
系统。** 这类系统不能跟着机器重启掉线，也不能在对话中途丢一句 —— 所以它
脚下的地基必须打不死、一直醒着。

大多数 Agent 框架默认进程活着。aicf-core 反过来假设：进程一定会死 ——
崩溃、断电、发版重启、一个随手 `kill -9` —— 而任务照样跑完。状态在
journal 里，`effectful` 的调用绝不重放，另一个实例可以接管。

在这层运行时周围，是一个 Agent 系统值得被信任之前需要的一切：每次工具
调用前的策略闸门与人工审批、业务删不掉的审计、分层记忆、多智能体协作、
本地语音与视觉，以及决定「什么能发布」的评测闭环。

**AICF** = Agent Infrastructure Cybernetics Framework · Apache-2.0。它是
一个库，不是应用 —— 应用长在它上面，在各自的仓库里（Web 控制台是
[`aicf-ui`](https://github.com/ccjjfdyqlhy/aicf-ui)）。

## 三条保证

> **安全、打不死、可评测地跑完一次长任务。**

| | 保证 | 怎么验证 |
|---|---|---|
| **安全** | 每次工具调用都过策略闸门；有副作用的要等人点头；判定不出来就是**拒绝**。 | `aicf tool exec proc.run --args '{"command":"rm -rf /"}'` → 被拒 |
| **打不死** | 跑到一半被杀？从断点恢复，副作用不重放。真实 `kill -9` 故障注入：46/46 恢复。 | `pytest tests/fault/` |
| **可评测** | 每次运行产出 trace；每次改动被数据集打分，四道闸门可以拦住不达标的发布。 | `aicf eval` → `aicf gate` |

一句诚实的补充：工具以操作者权限运行 —— 启动前会查路径口径、加
`ulimit`、只透传白名单环境变量，但**还没有 OS 级沙箱**。到底保护什么、
不保护什么，[docs/security.md](docs/security.md) 写得很清楚。

## 九十秒

```bash
pip install aicf-core

# 生成一个骨架项目：接入点都接好了，没有业务
aicf init demo && cd demo
```

下面每一步都**离线可跑** —— 不需要 API key —— 终点是绿的。

```bash
# 1. 试着跑个 shell。它有副作用 —— 所以要等人点头。
aicf tool exec proc.run --args '{"command":"rm -rf /"}' --policy strict
#    → 被拒

# 2. 离线跑一整个数据集：每个用例一轮、一条 trace。
aicf run --dataset offline --trace-dir traces/

# 3. 打分。有回归、成本超标或安全违规，发布会被拦下。
aicf eval --dataset offline --traces traces/ --out run.json
aicf gate --run run.json --out gate.json
```

五行写个 Agent：

```python
from aicf.harness import create_agent, tool

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
print(agent.run("17 + 25 等于几？"))
```

任何 OpenAI 兼容端点都行。本地模型把 `base_url` 指向你的
`llama-server` / LM Studio。

## 里面有什么

```
你的应用 / 技能包
   ▲
aicf/harness    轮次循环 · 工具 · 上下文 · 记忆 · 会话 · 多智能体
   ▲
aicf/infra      模型路由 · 资源池 · 存储 · 网关 · 认证 · 策略
```

依赖**单向向下**：`harness` 不 import 任何应用，`infra` 不 import 任何
业务语义。模块地图见 [docs/architecture.md](docs/architecture.md)。

箱子里还有（每个一句话）：

- **多智能体** —— 角色、委派、邮箱、黑板；每次委派都留痕
- **语音与视觉** —— 本地 ASR / TTS / VLM 同池调度；感知模式（沉默 = 在听）、空闲心跳主动开口、`resident` 常驻档让模型一直热着
- **技能包** —— 仓库外的声明式包，Agent 见到之前先被框架校验
- **学习闭环** —— 轨迹 → 数据集 → 判官 → 晋级，同样过四道闸门

## 安装

```bash
pip install aicf-core
```

> `aicf --version` 必须打出 `1.0.0` 或更新。更早的版本没有 `aicf` 命令；
> 它们在 PyPI 上已撤下，但有些镜像还在发 —— 请从官方源装：
> `pip install -U --index-url https://pypi.org/simple aicf-core`

可选 extra，用到哪块再装哪块：

```bash
pip install "aicf-core[personality]"   # 人格动态
pip install "aicf-core[decisions]"     # System-1 决策头
pip install "aicf-core[learning]"      # 轨迹 → 数据集 → 判官 → 晋级
pip install "aicf-core[finetune]"      # 本地 SFT（会拉 torch）
pip install "aicf-core[mcp]"           # 外部 MCP 工具源
pip install "aicf-core[all]"           # 全都要
```

## 文档

| 我想… | 看这个 |
|---|---|
| 从零跑起一个 Agent | [docs/getting-started.md](docs/getting-started.md) |
| 模块地图与依赖规则 | [docs/architecture.md](docs/architecture.md) |
| 安全模型（默认拒绝 / 审批 / 沙箱档位 / 审计） | [docs/security.md](docs/security.md) |
| 托管运行时（journal / 幂等 / 恢复） | [docs/runtime.md](docs/runtime.md) |
| 评测闭环（数据集 / 闸门 / 回归） | [docs/evaluation.md](docs/evaluation.md) |
| 把核心当库用 | [docs/sdk_guide.md](docs/sdk_guide.md) |
| 技能包公开规格 | [docs/skill-spec.md](docs/skill-spec.md) |
| 可复现的数字 | [benchmarks/README.md](benchmarks/README.md) |
| 路线图与各工作流状态 | [docs/roadmap_1.0.0-rc0.md](docs/roadmap_1.0.0-rc0.md) |
| 其余全部 | [docs/](docs/) |

核心文档另有英文译文（[docs/en/](docs/en/)）；中文原版是权威口径。

## 社区

- **提问与讨论**：[GitHub Discussions](https://github.com/ccjjfdyqlhy/aicf-core/discussions)
- **Bug 与功能请求**：[GitHub Issues](https://github.com/ccjjfdyqlhy/aicf-core/issues)
- **安全漏洞**：请走 [SECURITY.md](SECURITY.md) 的渠道，不要开公开 issue
- **第一次贡献**：[CONTRIBUTING.md](CONTRIBUTING.md)

## 许可证

Apache-2.0

---

<sub>站点：<https://ccjjfdyqlhy.github.io/aicf-core/></sub>
