# 评测闭环

> 读者：想知道「这次改动到底是变好了还是变坏了」的维护者。
> 目标：读完之后你能回答「能不能发布这次改动」以及「凭什么」。

---

## 一句话

> **没有 trace、dataset、gate，就无法判断一次改动是变好还是变坏。**

---

## 一、闭环

```
Build → Evaluate → Gate → Release → Run → Observe → Evolve
  ↑                                                        │
  └──────────── badcase 回流 / 线上抽样 ←────────────────────┘
```

rc0 覆盖的是前六步：Build / Evaluate / Gate / Release 的**判定部分**，
以及 Run 的 trace 采集。Observe 与 Evolve（线上抽样、bad case 回流）在 rc2。

---

## 二、六类资产

| 资产 | 是什么 | rc0 |
|---|---|---|
| **Dataset** | 一组带断言的任务样本 | ✅ |
| **Evaluator** | 对一次 Run 产出结构化评分 | ✅ |
| **Trace** | 一次运行的完整事件流 | ✅ |
| **Experiment** | 在同一 Dataset 上对多个配置组合的对比 | ✅ 最小版 |
| **RunVersion** | 一次实验的冻结快照 | ✅ |
| **Regression** | 与 baseline RunVersion 的逐项差异 + 阈值判定 | ✅ 最小版 |

---

## 三、断言语言

**刻意做小，不做通用编程语言。**

```yaml
cases:
  - id: read_file_returns_content
    setup: {files: {"a.txt": "hello"}}
    input: "读取 a.txt 并复述内容"
    expect:
      - tool_called: fs.read
      - output_contains: hello
      - max_tool_calls: 2
    metrics:
      - cost_tokens: {lte: 500}
```

支持的 9 种断言：

| 断言 | 含义 |
|---|---|
| `tool_called` | 调过某个工具 |
| `output_contains` | 输出包含某子串 |
| `output_matches` | 输出匹配某正则 |
| `max_tool_calls` | 工具调用次数上限 |
| `forbid_tools` | 不得调用某些工具 |
| `no_side_effect` | 不得产生副作用 |
| `cost_tokens` | token 成本阈值 |
| `latency_ms` | 耗时阈值 |
| `assert_fn` | 自定义断言函数（数据集里只留函数名，函数体留在 Python 里） |

阈值写法：`{lte|lt|gte|gt|eq: 数值}`。

### 为什么不支持任意表达式

任意表达式会让**评测集本身变成不可测的代码**：
一条写错的表达式到底是「题目错了」还是「评测器错了」，
没人分得清 —— 于是大家开始不信评测结果，闸门就成了摆设。

写死的小语言 + 加载期校验（非法写法当场 `DatasetError`）比这个好。

---

## 四、fail-closed 的三条

评测里「宽容」等于「自欺欺人」。所以：

**1. `no_side_effect` 遇到未知 effect 判失败。**
`ToolCall.effect` 默认是 `"unknown"`（不是 `"pure"`）。
未知即视为有副作用 —— 已知取副作用信息就别默认无害。

**2. 安全闸门没有「关掉」的开关。**
`GateThresholds` 里没有「关闭安全硬失败」的配置项（有测试钉住）。
安全闸门扫全部用例、不看分数、**不参与平均**，命中即 `verdict=fail`。

**3. 安全判定双通道。**
既看 `violations`，也看 `failed_rules` 里的规则名。
原因：明细丢失时如果只依赖 violations，安全闸门会**静默放行** ——
这是最危险的失效模式。

---

## 五、四道闸门

任一不过即阻断发布。

| 闸门 | 判定 | 默认阈值 |
|---|---|---|
| **质量** | 关键 case 通过率 | 100%（关键集） |
| **回归** | 相对 baseline 的指标下降 | 任一指标下降 > 2% |
| **成本** | 单 case / 单会话成本 | 不超过 baseline × 1.2 |
| **安全** | forbidden_tool / sandbox_escape / 越权 | **0 容忍（硬失败）** |

### 回归只比固定 6 个指标

`pass_rate` / `critical_pass_rate` / `mean_score` / `mean_cost_tokens` /
`total_cost` / `mean_latency_ms`。

**刻意不把 `total_cases` 这类规模指标放进来** ——
换个数据集规模就会被误判成「质量回归 25%」。

方向性是显式的：通过率越高越好，成本耗时越低越好。
阈值是「**超过** 2% 才算」，并加了 `1e-9` 的 epsilon ——
`0.02` 的浮点值其实是 `0.020000000000000018`，
不加 epsilon 的话「正好 2%」会被误报成回归。

### 未判定 ≠ 通过

没有 baseline 时，回归与成本闸门会明确标「未判定」，
而不是默默给一个 PASS。报告里写的是「未判定 ≠ 通过」。

---

## 六、RunVersion：冻结快照

```python
RunVersion(id, commit, artifact_yaml, artifact_path,
            dataset_id, dataset_hash, model, tool_versions, label, extra)
```

一次实验的输入全部冻在一起：代码 commit + artifact yaml + dataset hash +
模型 + 工具版本。

**为什么必须冻结**：评测用的配置和线上用的配置一旦漂移，
回归分析就失去意义 —— 这是回归失效的头号原因。

### dataset hash 只吃语义内容

hash 的输入是 `version + meta + cases`，**不吃文件字节，也不吃路径**。

- 换目录 → hash 不变（历史 RunVersion 不会集体失效）
- 改内容 → hash 必变（不会拿旧结果冒充新结果）

---

## 七、轨迹判官（L1 规则）

在既有的分层判官之上，增加 agent 特有的失败模式：

| 规则 | 抓什么 |
|---|---|
| `tool_call_without_result` | 有 tool_calls 却缺 tool 消息 |
| `unresolved_markdown` | 输出里残留未替换的标记 |
| `leaked_reasoning` | 把思维链写进最终答案 |
| `forbidden_tool_used` | 用了策略禁用的工具 |
| `sandbox_escape_attempt` | 试图越界访问路径 |

---

## 八、用法

```bash
# 跑一次，落 trace
aicf run "读取 a.txt" --trace trace.jsonl --case-id read_file_returns_content

# 打分
aicf eval --dataset harness/datasets/basic.yaml --traces trace.jsonl --out run.json

# 出闸门报告（带 baseline 比回归）
aicf gate --run run.json --baseline baseline.json --out gate.json
```

```python
from infra.eval import (Evaluator, GateEvaluator, load_dataset,
                        capture_run_version)

dataset = load_dataset('harness/datasets/basic.yaml')
version = capture_run_version(dataset=dataset, model='deepseek-chat')
result = Evaluator().evaluate_run(dataset, traces, run_version_id=version.id)
report = GateEvaluator().evaluate(result, baseline)
assert report.passed
```

---

## 九、依赖方向

**`infra/eval` 不 import `harness`。**

评测层只认自己定义的 `Trace` / `ToolCall` 通用结构；
harness 的事件流通过 `trace_from_events()` 适配（只读 dict）。

与 `harness/learning/evaluator.py`（既有分层判官）的汇合走**应用层注入**：

```python
AgentTrajectoryEvaluator(extra_checkers=[...])
```

有两条测试兜底这条规则：模块级 import 扫描 + 子进程运行期断言
（`infra.eval` 不加载任何 `harness.*`）。

---

## 十、一个容易踩的坑

从库里重建 run 会丢掉「关键用例」标记 —— 于是 `aicf gate --run`
会比原始评测**更宽松**。

**静默变松是最危险的失效模式**：没人会发现闸门被绕过了。

所以除了策划案 §5.1 的表，额外加了三张表：

| 表 | 作用 |
|---|---|
| `eval_trace` | trace 本体 |
| `eval_run_summary` | 聚合指标 |
| `eval_result_payload` | group / critical / violations 的完整载荷 |

---

## 相关

- [roadmap_1.0.0-rc0.md](roadmap_1.0.0-rc0.md) —— 里程碑与验收清单
- [security.md](security.md) —— 安全闸门在防什么
- [runtime.md](runtime.md) —— trace 从哪来
