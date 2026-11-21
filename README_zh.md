# aicf-core

> **是地基，不是应用。** aicf 是 Agent 系统往下长的那一层：长期运行、持久、
> 稳定、安全、可审计 —— 从下到上，跨模态，任务需要几个 Agent 就几个。

私人伴侣、备考助手、值班运维、研究流水线 —— 底下踩的是同一块地基。

**AICF** = Agent Infrastructure Cybernetics Framework · Apache-2.0

[English](README.md) | [简体中文](README_zh.md)

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![CI](https://img.shields.io/github/actions/workflow/status/ccjjfdyqlhy/aicf-core/ci.yml?branch=main&label=CI&style=for-the-badge)](https://github.com/ccjjfdyqlhy/aicf-core/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/endpoint?url=https%3A%2F%2Fccjjfdyqlhy.github.io%2Faicf-core%2Ftests.json)](https://github.com/ccjjfdyqlhy/aicf-core/actions/workflows/ci.yml)
[![Local First](https://img.shields.io/badge/local--first-100%25-8A2BE2?style=for-the-badge)](docs/architecture.md)
[![Modalities](https://img.shields.io/badge/modalities-text%20%C2%B7%20speech%20%C2%B7%20vision-8A2BE2?style=for-the-badge)](docs/infra.md)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue?style=for-the-badge)](LICENSE)

---

## 三条保证

> **安全、幂等、可评测地跑完一次长任务。**

大多数 Agent 框架默认进程活着。这个不这么假设。

| | 承诺 | 你可以怎么验证 |
|---|---|---|
| **安全** | 每一次工具调用都过策略闸门；有副作用的要人点头。**判定不出来就是拒绝。** 会起进程的工具在启动前先被检查一遍（路径口径、出网目标、ulimit、环境变量白名单），但它仍以**操作者的权限**运行：**还没有 OS 级沙箱**（无容器 / 微虚机）。 | `aicf tool exec proc.run --args '{"command":"rm -rf /"}'` → 被拒 |
| **幂等** | 崩了能恢复，且不重复产生副作用。`effectful` 的调用**绝不**自动重放。 | `pytest tests/fault/` —— 子进程里真的 `kill -9` |
| **可评测** | 每次运行产出 trace；每次改动都被数据集打分，并被四闸门报告拦住。 | `aicf eval` → `aicf gate` |

---

## 地基里有什么

地基就是你的 Agent 系统往下踩的那一层。下面这些东西都住在它里面 —— 正因为都在，
同一块地基才配得上任何你能叫出名字的场景。

### 从下到上，不是从上往下

应用不是从这个框架里切出来的，是在它**上面长出来**的。

```
你的应用        伴侣 · 备考助手 · 值班运维 · 研究 · 任何东西
   ▲
技能包          声明式、可外置、由框架校验
   ▲
aicf/harness    轮次循环 · 工具协议 · 上下文 · 记忆 · 会话 · 管线 · 多智能体
   ▲
aicf/infra      模型路由 · 资源池 · 存储 · 网关 · 认证 · 策略
```

`aicf/harness/` 不 import 任何应用；`aicf/infra/` 不 import 任何业务语义。
依赖**单向向下**。

### 长期运行，而且对「持久」有话说

`aicf/infra/runtime/` 假设进程活不下来：journal 是真相来源，checkpoint 只是加速器，
幂等键让 `effectful` 的调用不会被重放，租约 + 围栏令牌让另一个实例能接管，
而不会出现两个实例同时写。记忆是分层的 —— 工作 / 情节 / 语义 / 画像
（`aicf/harness/memory/`），经 `aicf/infra/store/` 落盘。

### 默认安全，而且可审计

`aicf/harness/policy/` 负责判定，`aicf/harness/approval/` 在有副作用时替人问一句，
**判定不出来就是拒绝**。`aicf/infra/observability/audit.py` 留着业务也删不掉的记录。
还没有 OS 级沙箱 —— [docs/security.md](docs/security.md) 写清楚了到底保护什么、
不保护什么。

### 全模态：文本、语音、视觉

`aicf/infra/resources/` 在本地跑语音与视觉：ASR（FunASR，进程内）、
TTS（GPT-SoVITS，走 HTTP）、VLM（本地 llama-server）在同一个池子里，
按槽位调度，空闲了会被回收。文本走 `aicf/infra/models/` 与
`aicf/infra/orchestrator/`。当训练与推理抢同一张卡时，
`aicf/infra/orchestrator/scheduler.py` 里的 `DeviceGate` 是唯一的仲裁点。

交互层现在也在框架里了，不再只在私有应用：`aicf/harness/voice/`
把 TTS **逐句流式**播放（第一句合成完就开口，不等整段）、过滤 ASR
假语音（噪声 / 哼鸣 / 键盘乱敲 —— 真 1B 分类器是端口，启发式兜底）、
跑**感知模式**（连续通话，沉默 = 在听）与**心跳**（空闲时按你的 hook
主动开口）。`aicf resources profile` 的三档 —— `resident` / `balanced` /
`eco` —— 把「随时可用 vs 显存」从口号变成显式取舍。

### 多个 Agent，一块地基

`aicf/harness/agent/collab.py` 给你角色类型、委派与邮箱；`swarm.py` 加一块黑板；
`team.py` 把它们组合起来。`aicf/infra/control/` 加身份 —— 每次委派都留痕，
而一个产物只有在闸门报告通过之后才能发布。

### 技能包就是生态

`aicf/harness/skills/` 从仓库外加载技能包：一个带 JSON-Schema 工具声明的
`skill.yaml`、一个提示词文件、加上普通 Python。框架会在 Agent 看到它们之前先校验。

---

## 九十秒

```bash
pip install aicf-core
```

下面每一步都**不需要 API key**（离线可跑），并且都给出了你**实际会看到的输出**。
走完的终点是绿的。

```bash
# 1. 生成一个骨架项目：接入点都接好了，没有业务，往里填肉。
aicf init demo && cd demo

# 2. 每个工具到底能干什么？副作用等级、声明的写口径、需要的授权范围。
aicf tool list
#    tool        effect      sandbox    net    destructive  version
#    file.edit   effectful   workspace  none   false        1.0
#    file.read   pure        readonly   none   false        1.0
#    ...

# 3. 试着跑个 shell。它有副作用 —— 所以要等人点头。
aicf tool exec proc.run --args '{"command":"rm -rf /"}' --policy strict
#    Error: 工具 proc.run 被策略拒绝（approval）：CLI 未开启 --yes
```

然后是第一个成功，依然离线：

```bash
# 4. 跑一整个数据集：每个用例一轮、一条 trace。
aicf run --dataset offline --trace-dir traces/
#    ✓ offline_pipeline_replies [offline] done
#    … 6 case，trace 落 traces/

# 5. 打分。
aicf eval --dataset offline --traces traces/ --out run.json
#    用例 6/6 通过（数据集 offline，hash …）

# 6. 任何回归、成本超标或安全违规都会拦住发布。
aicf gate --run run.json --out gate.json
#    闸门判定: 通过
#      [PASS] quality: 关键用例通过率 100.0%（1/1），达标
#      [PASS] safety: 未发现安全违规（扫描 6 个用例）
```

包里**故意**带两份数据集：

- `offline` —— 链路冒烟：回复到达、没有凭空出现的工具调用、预算字段在记录。
  **离线就能全过**，它证明的是「地基通」。
- `basic` —— 40 条质量用例（文件读写 / 计算 / 越权拒绝 / 安全 / …）。
  需要真模型才能全过：桩模型不会调工具，评测器也不会把回声算作答。
  这不是缺陷 —— 冒烟数据集如果被桩模型「考过」，它就说明不了模型质量。

`aicf eval --group refusal,safety` 可以只评子集（run 记录里看得出评的是哪个子集）。
一个 30 行、零依赖、直接打印结果的 Python 例在
[examples/minimal.py](examples/minimal.py)。

---

## 安装

```bash
pip install aicf-core
```

> **先确认装到了哪个版本**：`aicf --version` 必须打出 `1.0.0` 或更新。
> 1.0.0 之前的版本**根本没有 `aicf` 命令**。它们在 PyPI 上已经撤下，
> 但**有些镜像还在发** —— 而当镜像上只有它一个候选时，pip 会**一声不吭**
> 地把撤下的版本装上。所以如果 `aicf --version` 打出 `0.6.x`，
> 说明装坏了：直接从官方源装。
>
> ```bash
> pip install -U --index-url https://pypi.org/simple aicf-core
> ```

装完就是整个库——Agent 内核 + 模型/工具/运行时层。
库就是这块**地基**；**应用长在它上面**，各自独立仓库
（Web 控制台是 [`aicf-ui`](https://github.com/ccjjfdyqlhy/aicf-ui)，见下表）。

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

## 从 ≤ 1.0.0rc3 迁移

1.0.0 把两层收进同一个顶层包。原因很实际：`harness` 和 `infra` 这两个名字
**在 PyPI 上已经被人占了** —— 框架不该把别人的名字装进你的环境。

| 旧（≤ 1.0.0rc3） | 新（1.0.0+） |
|---|---|
| `from harness import create_agent` | `from aicf.harness import create_agent` |
| `from harness.tools import ToolRegistry` | `from aicf.harness.tools import ToolRegistry` |
| `from infra.models.base import IChatClient` | `from aicf.infra.models.base import IChatClient` |

分发名、命令行、import 名现在对齐了：`pip install aicf-core` → `aicf` 命令 →
`import aicf.harness`（`from aicf import create_agent` 也一样，是懒加载转发）。

---

## 只想写个 Agent？五个符号。

```python
from aicf.harness import create_agent, tool   # 你真正会写的两个
from aicf.harness.tools import ToolRegistry   # 自己管工具时才需要
from aicf.infra.models.base import IChatClient # 模型接口
```

| 符号 | 是什么 |
|---|---|
| `tool` | 把带类型的函数变成工具（schema 从签名自动生成） |
| `Agent` | 绑定了模型的 Agent —— `chat()` / `run()` / `chat_stream()` |
| `create_agent` | 一行工厂：模型 + key + 工具 |
| `ToolRegistry` | 工具表（只有自己注册工具时才需要） |
| `IChatClient` | 模型接口 —— 实现它就能接自己的后端 |

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

result = agent.run("17 + 25 等于几？")
print(result)                        # 结果表现得像字符串
```

任何 OpenAI 兼容端点都行。本地模型把 `base_url` 指向你的
`llama-server` / LM Studio，或者直接给 `create_agent` 传一个客户端
（`aicf.infra.orchestrator.LlamaCppChat`、`LMStudioChat`、`OpenAICompatClient` …）。

---

## 什么时候该用哪个？

先说实话：aicf 不是万能答案。和 LangGraph / Temporal / CrewAI 比，
差异是结构性的，不是审美性的：

| | aicf-core | LangGraph | Temporal | CrewAI |
|---|---|---|---|---|
| 核心思想 | 每次工具调用下面垫一层**策略 → 审批 → 沙箱 → 审计**，外加幂等可恢复的运行时与四闸门发布报告 | 对 LLM 步骤做图编排 | 长时业务工作流的持久化执行 | 角色扮演式多 Agent 脚本 |
| 什么时候选它 | Agent 要碰真实文件 / shell / 网络，且每次调用都要可归因、可恢复、可评测 | 想对模型步骤做显式控制流 | 需要业务逻辑的工作流保证（无论是不是 LLM） | 想快速搭一个角色扮演原型 |
| 刻意不做 | 跨机编排（那是部署形态）与提示词工程 | 安全闸门 / 审计 / 幂等 —— 不是它的主题 | LLM 原生概念（工具契约、审批、评测闸门） | 持久运行时、审计、发布闸门 |
| 迁移路径 | 工具就是普通函数：先把**一个**工具挂到策略引擎后面，再迁下一个 | 图的边 → `workflow` 内核声明（`aicf run --kernel workflow`） | activity → 带副作用声明的工具 | 角色提示词 → 技能包（[规格](docs/skill-spec.md)） |
| 地基里有、它们没有的 | 只追加的审计存储、`kill -9` 恢复、故障注入测试、CI 里的离线评测 + 发布闸门 | — | — | — |

迁移成本一句话：aicf 要的声明（每个工具的 ToolSpec、一份策略文件、
一份闸门报告）都是**你迟早想要的东西** —— 从一个受守卫的工具起步，
逐步长出全链路。

---

## 仓库结构（一分钟）

两层，依赖**单向向下**：

```
aicf/harness/   Agent 核心     turn loop · 工具 · 上下文 · 记忆 · 管线 · 会话 · SDK
    │                        不认识任何业务语义
    ▼
aicf/infra/     基础设施层    模型路由 · 资源池 · 存储 · 网关 · 认证 · 策略
```

它们之上还有：`aicf/harness/kernel/`（workflow + planner）、
`aicf/infra/control/`（Agent 资产生命周期、成本账本）、
`aicf/harness/skills/`（技能生态）、`aicf/infra/eval/`（数据集、四闸门）、
`aicf/infra/runtime/`（journal、checkpoint、恢复）。

用它的产品在各自的仓库里，只依赖 `aicf-core`，不依赖别的：

| 仓库 | 是什么 |
|---|---|
| [`aicf-ui`](https://github.com/ccjjfdyqlhy/aicf-ui) | Web 控制台 —— 模型、对话、资源、System-1 决策 |

---

## 当前状态

`aicf-core` 目前是 **1.0.0** —— 第一个装上就能跑的版本。
rc0 的完成定义是三条**可执行**的断言，三条都已达成（每条都钉在一个测试上）：

1. 被 `kill -9` 一次的 Agent 仍能恢复并给出正确结果；
2. 每一次工具调用要么被审批放行、要么被拒绝 —— 且留下审计；
3. 这次运行能被一个 ≥30 case 的数据集打分，并产出一份四闸门报告。

**默认路径上这些保证是成立的**：`create_agent` 装出来的 Agent 带守卫，
`proc.run` 以操作者的权限运行，但口径限定在工作区 —— 启动前查路径、
加 ulimit、只透传白名单里的环境变量，**不是** OS 级沙箱。SDK 与 CLI
都会把工具意图写进 journal，所以一次崩溃之后能算出「哪些事我可能已经做过了」。

**1.0.0** 把 rc0 清单上欠的六条都补齐了：控制面、Workflow / Planner 执行内核、
Agent 身份与委托授权、线上抽样与 bad case 回流、调度器与工作区隔离，以及
业务删不掉的审计存储。它还把两层收进同一个顶层包（`aicf.harness` /
`aicf.infra`，见上面的「迁移」小节），并加上了那道证明「装出来的 wheel
真的能用」的发布闸门。发布说明见
[docs/releases/v1.0.0.md](docs/releases/v1.0.0.md)。

还差的是 OS 级隔离（容器 / 微虚机 —— `isolated` 档还没建），以及属于部署形态而不是欠账的几件：
跨机编排、BYO 的传输通道。计划、验收标准与每条工作流的状态都在
[docs/roadmap_1.0.0-rc0.md](docs/roadmap_1.0.0-rc0.md)。

**可复现的数字**（每个数字都带复现命令 —— `python benchmarks/run_benchmarks.py`）：

| 数字 | 参考值 | 口径 |
|---|---|---|
| 守卫链路单次往返 | p50 ≈ 0.28 ms，p95 ≈ 0.38 ms | 一次本地调用走完 策略求值 + 幂等检查 + 审计（纯工具，N=300） |
| journal 重放恢复 | ≈ 1 ms / 200 事件 | checkpoint 不可用时的全量重放（最坏恢复路径） |
| 分层记忆 L1 压缩比 | ≈ 3.35× | 会话层摘要压缩前后的字符量之比 |
| 崩溃恢复成功率 | 46/46 = 100% | `tests/fault/` 故障注入层：真 `kill -9`、重复投递、损坏 checkpoint |

口径与注意事项：[benchmarks/README.md](benchmarks/README.md)。

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
| 从零跑起一个 Agent | [docs/getting-started.md](docs/getting-started.md) |
| 知道 1.0.0-rc0 在做什么、怎么验收 | [docs/roadmap_1.0.0-rc0.md](docs/roadmap_1.0.0-rc0.md) |
| 搞懂模块地图与依赖规则 | [docs/architecture.md](docs/architecture.md) |
| 搞懂安全模型（默认拒绝 / 审批 / 沙箱档位 / 审计） | [docs/security.md](docs/security.md) |
| 搞懂托管运行时（journal / checkpoint / 幂等 / 恢复） | [docs/runtime.md](docs/runtime.md) |
| 搞懂评测闭环（数据集 / 闸门 / run version / 回归） | [docs/evaluation.md](docs/evaluation.md) |
| 把核心当库用 | [docs/sdk_guide.md](docs/sdk_guide.md) |
| 深入 Agent 循环 / 工具 / 上下文 | [docs/harness.md](docs/harness.md) |
| 深入模型路由 / 资源 / 存储 | [docs/infra.md](docs/infra.md) |
| 改代码前先知道哪些坑别踩 | [docs/maintenance.md](docs/maintenance.md) |
| 配置项与环境变量 | [docs/configuration.md](docs/configuration.md) |
| 技能包公开规格（生态的接口） | [docs/skill-spec.md](docs/skill-spec.md) |
| 社区渠道与贡献路径 | [docs/community.md](docs/community.md) |
| 已知技术债与修复优先级 | [docs/technical-debt.md](docs/technical-debt.md) |

核心文档另有英文译文（[docs/en/](docs/en/)：security / runtime /
evaluation / getting-started）；中文原版是权威口径。

---

## 社区

- **提问与讨论**：[GitHub Discussions](https://github.com/ccjjfdyqlhy/aicf-core/discussions)
- **Bug 与功能请求**：[GitHub Issues](https://github.com/ccjjfdyqlhy/aicf-core/issues)（有模板）
- **安全漏洞**：请走 [SECURITY.md](SECURITY.md) 的渠道，不要开公开 issue
- 第一次贡献的路径：[CONTRIBUTING.md](CONTRIBUTING.md) · [docs/community.md](docs/community.md)

---

## 许可证

Apache-2.0

---

<sub>站点：<https://ccjjfdyqlhy.github.io/aicf-core/> · English: [README.md](README.md)</sub>
