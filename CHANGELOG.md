# Changelog

本文件记录 **1.0.0** 及以后的版本。1.0.0 之前（0.5.0 ~ 1.0.0rc3）没有统一的
变更日志，只有 [docs/releases/](docs/releases/) 下几篇发布说明 —— 那期间的版本
是在五天内连续发布的，节奏快到来不及写。

格式参考 [Keep a Changelog](https://keepachangelog.com/)。

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
