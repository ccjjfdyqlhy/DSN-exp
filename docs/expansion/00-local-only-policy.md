
# 本地专用策略（不上 GitHub）

> 本文件是**本地文档**，连同 `docs/expansion/` 整个目录都不进 GitHub。
> 生效日期：2026-11-06。

## 一、规则（一句话）

**只有 `infra/` 与 `harness/` 的通用改动、以及描述框架本身的既有共享文档进 GitHub；
其余一切（计划稿、新应用、实验产物、个人数据、模型权重）只留在本机。**

## 二、为什么要分

GitHub 上的 `DSN-exp` 是**框架仓库**：别人 clone 下来是为了用 infra/harness 写自己的应用。
而这一轮计划产生的东西——存在性应用 `dsn_existence`、训练工坊 HTTP 门面、
三份计划稿——是**研究性内容**，它们依赖本机环境（Bonsai 权重、`dsn-train` 环境、
远端教师 API 密钥），放进公开仓库只会带来噪声与误导。

同时 `docs/architecture.md` 的三层纪律要求 `apps/ → harness/ → infra/` 单向依赖：
这正好让**框架层可以独立发布**，而实验应用留在本地——框架层不知道应用的存在。

## 三、机制（三道闸门，都在 `.git/` 里，不会被提交）

| 闸门 | 文件 | 作用 |
|---|---|---|
| 1. 忽略 | `.git/info/exclude` | `docs/expansion/`、`apps/dsn_existence/`、`apps/dsn_ui/finetune*` 等路径不进入 `git status`，`git add -A` 也不会误收 |
| 2. 提交前拦截 | `.git/hooks/pre-commit` | 暂存区命中本地专用路径、或含 `apps/` 层改动 → **拒绝提交**并打印原因 |
| 3. 推送前拦截 | `.git/hooks/pre-push` | 再查一次待推送的提交，挡住 `--no-verify` 绕过 |

* 路径清单：`.git/local-only-policy.txt`（每行一个 git pathspec，`#` 为注释）
* `apps/` 白名单：`.git/apps-allow.txt`（默认空；确需提交某个 apps/ 通用修复时把路径写进去）
* 两个 hook 都用 **POSIX sh** 语法写（git 用 `/bin/sh` 执行 hook，不能用 `<(...)`）
* 绕过方式：`git commit --no-verify`（自行负责）

## 四、这一轮计划里，谁进 GitHub、谁不进

### 进 GitHub（框架层通用改动）

| 计划位置 | 落地文件 | 备注 |
|---|---|---|
| 计划二 §3.1-§3.7 | `infra/finetune/**`（base / runner / env / dataset / gguf / devices） | 训练作业、解释器体检、GGUF 工具封装 |
| 计划二 §3.6 | `infra/orchestrator/scheduler.py`（DeviceGate 独占闸门） | **就地扩展**，不新建 `device_pool.py` |
| 计划二 §3.7 | `infra/orchestrator/llamacpp.py`（`lora_path` / `lora_scale`） | 向后兼容，默认 `None` |
| 计划二 §4.1-§4.4 | `harness/learning/**`（dataset_builder / evaluator / promotion / selfplay） | 教师边界、判官分层、晋级规则 |
| 计划二 §9 | `tests/test_harness_finetune*.py`、`tests/test_infra_finetune*.py` | 框架层测试 |
| 计划二 §3.6 / 计划三 §10 | `docs/infra.md`、`docs/harness.md`、`docs/architecture.md` | 只写**框架层**的说明，不写本应用 |
| 计划二 §8 | `.env.example` 里的 `FINETUNE_*` 通用项 | 只放通用开关；本地 API 密钥不进仓库 |

### 不进 GitHub（本地专用）

| 计划位置 | 落地文件 | 原因 |
|---|---|---|
| 计划三 §7 | `apps/dsn_existence/**` | 存在性应用本体，研究性内容 |
| 计划三 §7 | `apps/dsn_existence/chaos.py` / `sandbox.py` / `writeback.py` | 混沌演练会杀进程、动沙箱，绝不能进公开仓库 |
| 计划二 §5 | `apps/dsn_ui/finetune_api.py` + SvelteKit「模型工坊」页签 | HTTP 门面与应用页面属于 apps 层 |
| 计划三 §6.5 | `tests/test_dsn_existence*` | 应用层测试 |
| 全部三份 | `docs/expansion/**` | 计划稿本身 |

> **注意**：`docs/README.md` 里如果加了指向 `docs/expansion/` 的索引行，
> 推到 GitHub 上会变成断链——pre-commit 钩子会拦下这种改动（含 `expansion/` 字样的暂存版本）。

## 五、提交前自检清单

```bash
git status --porcelain          # 只应看到 infra/ harness/ tests/ docs/ 的通用改动
git diff --cached --stat        # 确认没有 apps/ 与 docs/expansion/
git log --oneline origin/harness-refactor..HEAD   # 本地未推送的提交
```

推送前钩子还会再查一遍，所以即使误提交也不会被推上去。

## 六、待办（下一阶段开始写代码前确认）

1. `infra/finetune/` 的公共 API（`submit` / `status` / `promote` / `rollback`）先定稿，
   它是本地应用与 GitHub 框架之间的**唯一契约**；
2. 框架层不得反向 import `apps/`（守住 `docs/architecture.md` 的三层纪律）；
3. 远端教师的 API 密钥、本机权重、数据集一律走 `.env` / 本地路径，不进仓库。
