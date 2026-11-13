# harness_lab —— harness 记忆与人格系统的专用验证台

一个独立应用，把 `harness/personality`（PEV3）与 `harness/memory` 拉起来跑，
用一组**预设的人格演化方向**驱动它们，对每一项「应该发生的行为」做断言，
最后产出一份可读的验证报告。

它回答一个问题：**harness 现有的记忆与人格系统，是否真的按预期工作。**

---

## 快速开始

```bash
# 跑全部场景（离线、无需任何凭据，1~2 秒）
python -m apps.harness_lab

# 只看有哪些预设方向
python -m apps.harness_lab --list

# 只跑一个场景
python -m apps.harness_lab --scenario praise_streak

# 对照实验：让桩**不**遵守 max_tokens（用来定位根因）
python -m apps.harness_lab --scenario distillation_fidelity --no-truncate

# 真实模型（需要 OPENAI_API_KEY + OPENAI_API_BASE；缺凭据会直接报错，不静默退回桩）
python -m apps.harness_lab --llm live
```

> `--llm live` 下，**事件分类由模型自己判定**，场景脚本里的 `scripted_event`
> 退化为"意图提示"，因此"判定与剧本逐条一致"这条检查会放宽为"判定落在合法事件枚举内"。

报告输出到 `.dsn/harness_lab/`（`report.md` + `report.json`），
每个场景的隔离工作区在 `.dsn/harness_lab/workspaces/<场景>/`。

---

## 预设人格演化方向

每个方向都对应 PEV3 里一条**明确的机制**（事件权重表 / 情绪冲量表 / 饱和曲线 /
遗忘 / 证据映射），这样"人格有没有按预期演化"才有可判定的依据。

| 方向 | 意图 | 对应机制 |
|---|---|---|
| `praise_streak` | 持续表扬 → 亲密度上升并**逐步饱和** | `EVENT_AFFINITY_WEIGHTS[praise]=+2.0` / 饱和曲线 / `EVENT_TRAIT_EVIDENCE[praise]={F4:+1}` |
| `conflict_streak` | 持续冲突 → 亲密度明显下降 | `EVENT_AFFINITY_WEIGHTS[conflict]=-3.0`（线性下降） |
| `venting` | 用户倒情绪 → 情绪跟着走，但**关系不崩** | `EVENT_AFFINITY_WEIGHTS[venting]=+0.8`（正！） |
| `mixed_signal` | 奖惩交替 → 净变化接近 0 | 对称权重（thanks +1.5 / complaint −1.5） |
| `long_absence` | 断联 30 天 → 亲密度按日衰减 | `AFFINITY_FORGET_RATE=0.004/天`，宽限期 3 天 |
| `boundary_violation` | 越界 → 最强负向 | `EVENT_AFFINITY_WEIGHTS[boundary_violation]=-4.0` |
| `blank_evolution` | 空白卡从零演化 | `create_blank(randomize_traits=True)` + consolidate 自建基线 |
| `distillation_fidelity` | 蒸馏三连的产物是否完整 | `distillation_engine` pass1/2/3 |
| `memory_growth` | 记忆三条写入路径 + 检索 + 降级 | `MemorySystem` 全链路 |
| `context_budget` | 预算裁剪 / 保底 / 无副作用 | `SegmentedContextAssembler` |

---

## 设计要点

**1. 桩客户端如实遵守 `max_tokens`。**
`ScriptedChat`（`clients.py`）按提示词类型路由到预设响应，并**按 `max_tokens`
截断**。这不是为了造故障，而是为了**离线复现线上的真实失败**：
`distillation_engine` 把 pass2/pass3 的 `max_tokens` 设成 3000，而提示词要求
输出 6000+ token 的 JSON —— 真实 provider 会截断，JSON 断在半截，解析失败，
产物全空。桩照做，同一个故障就在离线环境里重演。

**2. 检查项断言的是"应该发生什么"，不是"现在是什么"。**
每条检查按 harness 自己的文档契约编写。**FAIL 是有价值的结果** ——
它意味着"实际行为"与"应有行为"不一致，那正是这个验证台要回答的问题。

**3. 场景隔离。**
每个场景一个独立工作区（独立 DB、独立角色卡目录、独立蒸馏产物），
互不污染，可单独重跑。角色卡从 `cards/` 复制进来，产物落在工作区里。

**4. 预置基线蒸馏产物。**
人格场景会预置一份"基线蒸馏产物"，形态与线上一致（50 维全 0.5、结构化字段全空），
避免 `ensure_user_bound` 触发后台蒸馏线程去抢桩客户端。

**5. 蒸馏日志被重定向。**
harness 把蒸馏日志硬编码到**仓库根**的 `logs/distill/`
（`distillation_engine.py:246`，与部署目录无关，打包即失效）。
验证台把它重定向到场景工作区，顺带把这个事实记下来。

---

## 模块

| 文件 | 职责 |
|---|---|
| `config.py` | 运行期求值的配置（不像 dsn_study 的 `Config` 那样是 import 期快照） |
| `clients.py` | `ScriptedChat`（确定性桩，遵守 max_tokens）/ 摘要桩 / 真实客户端装配 |
| `scenarios.py` | 预设人格演化方向 + 场景定义（脚本化对话轮次 + 指向的检查项） |
| `runner.py` | 场景执行器：拉起 PEV3 / 记忆 / 剪裁器，跑脚本化交互，收观测数据 |
| `checks.py` | 检查项注册表（56 项），每项是一个纯函数 |
| `report.py` | Markdown + JSON 报告 |
| `cards/` | 基准角色卡（复制自 dsn_study 线上卡，只改了 card_id 与 seed） |

---

## 当前结论（2026-11-11，修复后基线）

**60/60 项通过，0 失败。**

最初跑出的是 **51/56**，5 项失败 —— 全部指向 harness 的真实缺陷。
当天全部修掉，并把每一条改成"必须持续通过"的回归项
（`tests/test_harness_lab.py` 的 `FIXED_DEFECTS`）：

| 已修复的缺陷 | 修法 |
|---|---|
| `persona.distillation_artifact_complete` | pass2/pass3 预算 3000 → 8000（重试 16000）+ 结构完整性校验；失败**抛 `DistillationError`** 而不是静默 `return {}` |
| `persona.distillation_indicator_vector_varied` | pass3 维度齐全性校验；**不再静默把缺失维度补成 0.5**（补 0.5 等于谎称"这个角色恰好中庸"） |
| `persona.distillation_no_silent_empty` | 解析失败从"warning + 空产物"改成显式抛错 |
| `persona.state_flush_required` | `on_interaction` 写穿落库（原来缓冲 3 条/5 秒且无人 `flush()`） |
| `persona.evidence_survives_restart` | mu/sigma/counts 全部以 DB 为真源（原来只在内存，重启即失忆） |
| `persona.consolidate_counter_survives_restart` | 固化计数持久化（`personality_evidence.pending` 列）—— 原来门槛永远达不到 |
| `persona.prompt_cache_isolated_per_user` | 提示词缓存按 (卡, 用户, 关系阶段) 分桶 |
| `persona.fallback_no_foreign_persona` | 兜底串不再硬编码别的应用的人格（"你是 EXA"） |
| `context.plan_is_pure` | `plan()` 的 memo 分支改用 `replace()`（原来就地改写入参） |

**验证台现在同时是"修复后的基线"和"防复发网"**：
修好一个缺陷 → 把它从 `KNOWN_DEFECTS` 挪到 `FIXED_DEFECTS` →
它的检查项从此**必须持续通过**，缺陷复活即测试失败。

### 修复前后的行为对照（同一套场景）

| 场景 | 修复前 | 修复后 |
|---|---|---|
| 连续表扬 12 轮 | 亲密度上升，但人格产物是空的 | 亲密度 20.0 → 27.4，增幅逐轮递减（1.067 → 0.308，饱和曲线**逐轮公式精确匹配**） |
| 空白卡演化 55 轮 | 证据只进内存，重启即失忆 | 105 条证据、**50 维全部偏离 0.5**，固化写回 `distilled.json` |
| 蒸馏三连 | 产物全空（静默） | 5 条行为模式 / 5 条言语模式 / 4 段关系 / 50 维真实分布（0.35~0.7+） |
| 重启 | 亲密度回退、证据归零 | 完整恢复 |

---

## 接入 pytest

`tests/test_harness_lab.py` 把验证台包成测试：56 个检查项各一条用例，
已知缺陷标 `xfail(strict=True)` —— **缺陷被修好的那天，测试会失败并提醒摘标记**。
