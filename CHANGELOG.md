# Changelog

本文件记录 **1.0.0** 及以后的版本。1.0.0 之前（0.5.0 ~ 1.0.0rc3）没有统一的
变更日志，只有 [docs/releases/](docs/releases/) 下几篇发布说明 —— 那期间的版本
是在五天内连续发布的，节奏快到来不及写。

格式参考 [Keep a Changelog](https://keepachangelog.com/)。

---

## [Unreleased]

---

## [1.0.1] — 2026-11-21

**1.0.0 之后的第一个版本。核心变化：README 的上手流程走完是**绿的**，
并且新增了四件此前只存在于设计稿里的能力 —— 记忆溯源、语音交互层、
资源档位、`aicf init` 脚手架。

### 新增

- **`aicf init <name>` —— 空白脚手架。** 新建一个文件夹、跑一条命令，
  得到一套**写好了接入点、但没有业务**的骨架（`agent.py` / `tools/` /
  `policies/` / `traces/` + README + `pyproject.toml`），自己往里填肉。
  每个接入点都是能直接跑的最小接线，不是 TODO 列表。
- **语音交互层 `aicf/harness/voice/`。** 流式逐句朗读、假语音过滤、
  感知模式（连续通话、沉默=在听）。此前这些只在应用层，框架层没有。
- **记忆溯源 `aicf/harness/memory/provenance.py`。** Source（不可变证据）→
  Artifact（可修订解释）两级模型，带 revision 链、**证据闸门**
  （`EvidenceGate`）与**披露矩阵**（`DisclosureMatrix`）；记忆写入进审计轨。
  这是「持久记忆**可审计**」这根支柱的实现。
- **资源档位 `resident` / `balanced` / `eco`。** `resident` 显存换延迟、
  永不自动卸载（第一次语音请求的延迟 == 常驻延迟）；`eco` 显存优先。
  显式解决「随时可用」与显存的冲突。
- **`aicf learn` 与 `benchmarks/`。** 轨迹 → 数据集 → 判官 → 晋级闭环，
  以及**可复现的基准数字**（记忆压缩比、崩溃恢复成功率）。
- **离线评测集 `offline.yaml`。** 零 API key 验证 run → trace → eval → gate
  链路，**6/6 通过、闸门判定「通过」**。
  与 `basic`（40 case，质量回归，需真模型）刻意分开 ——
  不把「链路坏了」和「模型退步了」混进一张报告。

### 修复

- **评测集与注册表脱节。** 随包数据集里 27 条工具断言有 26 条指向不存在的
  工具名（`fs.read` / `calc.eval` / `web.search` …），而注册表里叫
  `file.read` / `web.fetch` —— 这些断言**永远不可能通过**，且失败原因会被
  误读成「模型没调用工具」。现在由 `aicf/infra/eval/tool_vocab.py` 统一绑定，
  评测集本身一个抽象名都没改。另有 6 条断言了当前实现里不存在的工具的用例
  已改为断言结果而非工具名。
- **回声算通过。** 桩模型把输入原样吐回来时，若期望内容恰好出现在输入里，
  `output_contains` 会**假通过**。评测器现在识别回声并判它不满足断言。
- **CI 的 eval 作业只跑 `--help`。** 「随包数据集能不能真的用」从来没被验证过
  —— 这正是坏包能连发 6 个版本而没人发现的原因。现在真跑一次 eval 与闸门。
- **沙箱说法自相矛盾。** README 承诺「and a sandbox」，而 `SECURITY.md`
  写着「there is no sandbox」。已按代码事实统一：策略闸门 + 审批 + 默认拒绝 +
  执行前检查，**没有 OS 级沙箱**。

### 变更

- **README / README_zh / 落地页的宣传口径统一为「是地基，不是应用」。**
  之前三处卖的是「安全、幂等、可度量」—— 三条关于**一次长任务**的保证，
  太窄，读起来像给后端团队用的 CI 器件。补上了此前三处都没提的四个维度：
  全模态、多 Agent、技能生态、长期持久，每条给出真实模块路径。
- **新增英文文档与英文落地页**（`docs/en/` 四份、`docs/site/en/`），
  以及 `docs/community.md`、`docs/skill-spec.md`。
- **README 新增简体中文互链**，并新增显示**具体测试数**的徽章
  （Pages 工作流发布前真跑一遍测试，数字是当场跑出来的）。
- **版本一致性做成测试**：`tests/test_version.py` 现在会扫描所有文档里的
  「当前发布版是 X」声明，X 必须等于 pyproject 的版本；
  下限声明（`1.0.0 or newer`）也不能高于当前版本。

### 发布说明

[docs/releases/v1.0.1.md](docs/releases/v1.0.1.md)

### 发布闸门

`scripts/wheel_smoke.py` 从 5 项扩到 **11 项**，新增覆盖 1.0.1 的新能力：
两份评测集随包分发、CLI 含新命令、`aicf init` 真能生成骨架、
新模块可 import，以及 **README 全流程端到端跑通且闸门判定「通过」**。

---

---

---

## [1.0.0] — 2026-11-20

第一个「装出来就能用」的正式版。

### 破坏性变更（Breaking）

- **import 路径改为 `aicf.harness.*` / `aicf.infra.*`。**
  原先的顶层包 `harness` 与 `infra` 在 PyPI 上都已被他人占用，框架把自己的
  内部目录名泄漏进用户的全局命名空间，等于「装一个包，坏三个环境」。现在两
  层收进一个顶层包 `aicf`，顶层不再占用别人的名字。

  | 旧（≤ 1.0.0rc3） | 新（1.0.0） |
  |---|---|
  | `from harness import create_agent` | `from aicf.harness import create_agent` |
  | `from harness.tools import ToolRegistry` | `from aicf.harness.tools import ToolRegistry` |
  | `from infra.models.base import IChatClient` | `from aicf.infra.models.base import IChatClient` |

  `from aicf import create_agent` 也可用（PEP 562 懒加载转发）。
  分发名不变（仍是 `aicf-core`），CLI 不变（仍是 `aicf`）。

### 修复

- **发布出去的包第一次真的能用。** 0.6.2 ~ 1.0.0rc3 都成功发布到了 PyPI，
  但那些包里**没有 console_scripts 入口点，也没有随包分发的评测集** ——
  `pip install aicf-core` 装到的版本连 `aicf` 命令都没有，README 上
  「九十秒上手」的每一条命令都是 `command not found`。原因是 pip 默认不装
  预发布版本，用户拿到的是最早的 0.6.2。

### 新增

- **发布闸门：装出来真的能用。** `scripts/wheel_smoke.py` 构建 wheel、装进
  全新虚拟环境、按 README 的说法去用它（`aicf --version` / `tool list` /
  `eval --dataset basic` / 公开 import 路径 / 已安装版本与声明版本一致 /
  顶层包只有 `aicf`）。它接在 `release.yml` 的 publish 之前与 `ci.yml` 的
  每次 push 上 —— 源码树里测试全绿是发现不了 wheel 缺陷的。
- **CHANGELOG**（本文件）与 [docs/releases/v1.0.0.md](docs/releases/v1.0.0.md)；
  此前仓库没有统一的变更日志。
- **GitHub Pages 文档站**：<https://ccjjfdyqlhy.github.io/aicf-core/>，
  静态站点，站点根为 `docs/site/`。

### 文档

- README 增加「迁移」小节（中英双语），给出 import 路径对照表。
- README 的「九十秒」如实说明：离线桩模型不会调工具，所以数据集用例在本地
  不通过；`aicf gate` 是 CI 用的闸门，要求每个用例一条 trace（`--case-id`）。
- 历史发布说明（rc0/rc2/rc3）保留原貌，各自加了命名空间迁移提示。

---

## [1.0.0rc3] — 2026-11-20

补齐 rc0 路线图列出的六项：控制面（agent 资产的生命周期、成本账本）、
workflow 与 planner 两个内核、身份与委派、采样与坏用例闭环、调度器与工作
区隔离、业务删不掉的审计轨。见 [docs/releases/v1.0.0rc3.md](docs/releases/v1.0.0rc3.md)。

## [1.0.0rc2] — 2026-11-19

文档存储（状态不落进项目目录）、上下文恢复只还原压栈的那个上下文。

## [1.0.0rc0] — 2026-11-19

第一版候选：策略闸门、审批 broker、托管运行时与日志、故障注入层、
评测层与四闸门、共享契约层、`aicf` 命令行。见
[docs/releases/v1.0.0rc0.md](docs/releases/v1.0.0rc0.md)。

## [0.6.2] — 2026-11-18

收敛为纯库：移除 `apps/` 与根级胶水，README 按纯库视角重写。

## [0.6.1] — 2026-11-17

SDK 六项上手友好度改进，并修掉一个静默丢工具的 SDK bug。

## [0.6.0] — 2026-11-17

多 agent 协作（角色类型、邮箱结算）、模型编排的文件上传与 anthropic 分页、
事件 sink 深度。

## [0.5.1] / [0.5.0] — 2026-11-15

首个公开发布：turn loop、工具协议、上下文装配、会话持久化、子 agent 协作。
