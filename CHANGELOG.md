# Changelog

本文件记录 **1.0.0** 及以后的版本。1.0.0 之前（0.5.0 ~ 1.0.0rc3）没有统一的
变更日志，只有 [docs/releases/](docs/releases/) 下几篇发布说明 —— 那期间的版本
是在五天内连续发布的，节奏快到来不及写。

格式参考 [Keep a Changelog](https://keepachangelog.com/)。

---

## [Unreleased]

把「可度量」这根支柱从**装饰**变成**真的可判定**。

### 修复

- **随包数据集里的工具断言有 26 条落不到真实注册表上。**
  `aicf/harness/datasets/basic.yaml` 写的是抽象能力名（`fs.read` / `calc.eval` /
  `web.search` …），而框架注册的工具叫 `file.read` / `web.fetch` —— 评测集刻意
  不绑定具体实现，但**没人把抽象名落到真实工具上**。后果不是「用例失败」，
  而是**用例永远不可能通过**，且失败原因会被误读成「模型没调用工具」。

  现在由 `aicf/infra/eval/tool_vocab.py` 的 `TOOL_NAME_ALIASES` 统一绑定：
  `fs.read → file.read`、`fs.write → file.write`、`fs.list → file.list`、
  `fs.stat → file.read`（框架没有 stat，知道文件多大只能读出来自己数）、
  `fs.delete → file.edit`、`shell.exec → proc.run`、`web.search → web.fetch`、
  `web.fetch → web.fetch`、`json.parse → text.extract_json`。
  评测集本身一个抽象名都没改 —— 换实现时只改词表右边那一列。

- **六条用例断言了当前实现里不存在的工具**，已改为断言**结果**而非工具名：
  `sum_two_numbers` / `unit_conversion` / `date_arithmetic`（框架没有注册纯计算
  工具）、`choose_stat_tool` / `read_then_compute`（同因）、
  `prefer_search_over_fetch`（原本要求 `web.search` 又禁止 `web.fetch`，
  而现在 `web.search` 就落到 `web.fetch` —— **自相矛盾**，改为
  「本地能回答时不要瞎出网」）。`search_then_answer` 改为只断言「去取了外部
  信息」，不断言答案文本（答案取决于网络，离线不可判定）。

- **回声输出会被算成通过。** 桩模型把输入原样吐回来时，如果期望内容恰好出现在
  输入里（例：输入「200 的 10% 是多少」、期望输出含「20」），`output_contains`
  会**假通过** —— 一个什么都没答的模型拿到了通过。现在评测器识别「输出 = 输入
  （可带 `[stub]` 标记与标点）」这一种回声，并判它不满足
  `output_contains` / `output_matches`。

### 新增

- **工具词表与绑定层** `aicf/infra/eval/tool_vocab.py`：抽象名 → 真实工具名
  的唯一入口，`resolve_tool_names()` / `matches_tool_call()`。
- **守卫测试** `tests/test_eval_dataset_bindings.py`：断言
  ① 评测集里出现的每个工具名都能落到至少一个真实注册的工具上；
  ② 词表的每个绑定目标都真实存在；
  ③ 同一条用例不会「要求 A 又禁止 A 的绑定目标」；
  ④ 用例 id 唯一。
  这条测试**跑在修复前的代码上会红**（它指出 5 条幽灵工具断言 + 1 条自相矛盾
  的用例）—— 1.0.0 之前 `tests/test_rc0_eval.py` 里的
  `test_every_case_in_basic_dataset_is_satisfiable` 抓不到这个问题，
  因为它**用数据集自己的抽象名造轨迹、再拿抽象名去比对，是循环论证**。

### 变更

- **CI 的 eval 作业现在真的跑一次评测与闸门**，而不是只跑 `--help`。
  1.0.0 之前那一步是 `eval --dataset basic --help`，于是「随包数据集能不能真的
  用」从来没被验证过 —— 这正是坏包能连发 6 个版本而没人发现的原因。
  新步骤会真跑 `eval` 与 `gate`、产出 `run.json` / `gate.json`，并断言
  「40 条用例全部读到 + 4 道闸门全部产出」。用例未通过属预期（离线桩模型不调
  工具），但**崩溃（Traceback）必须让 CI 变红**。

---

## [Unreleased]

### 文档

- **README / README_zh / 落地页的宣传与「地基」定位对齐。**
  之前三处卖的是「安全、幂等、可度量」—— 三条关于**一次长任务**的保证。
  这话不假，但太窄：读起来像给后端团队用的 CI 器件，而不是「任何东西都能长在
  上面」的地基。现在统一为：

  > 是地基，不是应用。aicf 是 Agent 系统往下长的那一层：长期运行、持久、稳定、
  > 安全、可审计 —— 从下到上，跨模态，任务需要几个 Agent 就几个。

  并补上了之前**三处都没提**的四个维度，每条都给出真实模块路径：
  全模态（`aicf/infra/resources/`）、多 Agent（`aicf/harness/agent/`、
  `aicf/infra/control/identity.py`）、技能生态（`aicf/harness/skills/`）、
  长期与持久（`aicf/infra/runtime/`、`aicf/harness/memory/`）。

- **新增「地基里有什么」一节**（README 英/中）与落地页的「地基里有什么」区块。
- **落地页 hero 改写**，导航加「地基」；架构图从「两层，依赖只向下」改成
  「从下到上，依赖只向下」，并在上面长出「你的应用（仓库之外）」与「技能包」两层。
- **修掉 README 内部矛盾**：「30 秒 / 九十秒」两套时间承诺 → 统一；
  「五个符号」与「你真正会写的三个（实际 import 两个）」→ 改成两个。
- **安装提示写实**：坏版本虽然已在 PyPI 撤下，但**镜像仍会发**，而 pip 在镜像上
  只有它一个候选时会**一声不吭**地装上撤下的版本（实测中科大源仍会装到 0.6.2，
  且没有 `aicf` 命令）。所以提示改成「`aicf --version` 必须打出 1.0.0 或更新」，
  并给出从官方源装的命令。

### 新增

- **徽章统一风格 + 显示具体测试数**。CI 徽章从 GitHub 默认样式换成 shields.io，
  与其它徽章同款。新增「Tests」徽章显示**这个 commit 的真实用例数** ——
  `scripts/write_tests_badge.py` 解析 pytest 摘要，写出 shields.io endpoint
  JSON（`docs/site/tests.json`），Pages 工作流在发布站点前真跑一遍测试。
  数字是当场跑出来的，不是抄来的；跑挂了就显示红色的「N failed」，不藏。
- Pages 工作流的触发路径加上 `aicf/**` 与 `tests/**`，这样徽章上的数字跟得上代码。

### 移除

- **扔掉 SVG banner**（`docs/header.svg`、`docs/header-v2.svg` 一并删除，
  两者已无人引用）。README 顶部现在是纯文字定位 + 徽章。
- **README 加简体中文互链**（`README.md` ↔ `README_zh.md`）。

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
