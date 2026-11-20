# Evaluation Loop

> English translation of [../evaluation.md](../evaluation.md) — the Chinese original is authoritative.

> Reader: maintainers who want to know "did this change actually make things better or worse".
> Goal: after reading this, you can answer "can this change be released" and "on what grounds".

---

## In one sentence

> **Without traces, a dataset, and gates, there is no way to judge whether a change
> made things better or worse.**

---

## 1. The closed loop

```
Build → Evaluate → Gate → Release → Run → Observe → Evolve
  ↑                                                        │
  └─────────── bad-case feedback / online sampling ←────────┘
```

rc0 covers the first six steps: the **decision-making parts** of
Build / Evaluate / Gate / Release, plus trace collection for Run.
Observe and Evolve (online sampling, bad-case feedback) come in rc2.

---

## 2. The six asset types

| Asset | What it is | rc0 |
|---|---|---|
| **Dataset** | A set of task samples with assertions | ✅ |
| **Evaluator** | Produces a structured score for a Run | ✅ |
| **Trace** | The complete event stream of one run | ✅ |
| **Experiment** | Comparison of several configuration combinations on the same Dataset | ✅ minimal version |
| **RunVersion** | A frozen snapshot of one experiment | ✅ |
| **Regression** | Item-by-item differences against a baseline RunVersion + threshold verdicts | ✅ minimal version |

---

## 3. The assertion language

**Deliberately small — not a general-purpose programming language.**

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

*(The `input` line is literal dataset content: "Read a.txt and repeat its content.")*

The 9 supported assertions:

| Assertion | Meaning |
|---|---|
| `tool_called` | A given tool was called |
| `output_contains` | The output contains a given substring |
| `output_matches` | The output matches a given regex |
| `max_tool_calls` | An upper bound on the tool call count |
| `forbid_tools` | Certain tools must not be called |
| `no_side_effect` | No side effects may be produced |
| `cost_tokens` | A token cost threshold |
| `latency_ms` | A latency threshold |
| `assert_fn` | A custom assertion function (only the function name lives in the dataset; the function body stays in Python) |

Threshold syntax: `{lte|lt|gte|gt|eq: number}`.

### Why arbitrary expressions are not supported

Arbitrary expressions would turn **the evaluation suite itself into untestable code**:
when one expression is written wrong, nobody can tell whether "the question is wrong"
or "the evaluator is wrong" — and then people stop trusting the evaluation results,
and the gate becomes decoration.

A hard-coded little language plus load-time validation (invalid syntax fails on the
spot with `DatasetError`) is better than that.

---

## 4. The three fail-closed rules

In evaluation, "leniency" is "self-deception". Therefore:

**1. `no_side_effect` fails on an unknown effect.**
`ToolCall.effect` defaults to `"unknown"` (not `"pure"`).
Unknown is treated as having side effects — the effect information is there when known,
so never default to harmless.

**2. The safety gate has no "off" switch.**
`GateThresholds` has no option to turn off the safety hard-fail (a test pins this).
The safety gate scans all cases, ignores scores, **does not participate in averages**,
and any hit yields `verdict=fail`.

**3. Safety verdicts use two channels.**
It looks at `violations` and also at the rule names in `failed_rules`.
Reason: if the details are lost and only violations are consulted, the safety gate
would **silently pass** — the most dangerous failure mode.

---

## 5. The four gates

Failing any one of them blocks the release.

| Gate | Verdict on | Default threshold |
|---|---|---|
| **Quality** | Critical-case pass rate | 100% (critical set) |
| **Regression** | Metric drops relative to the baseline | Any metric dropping > 2% |
| **Cost** | Per-case / per-session cost | No more than baseline × 1.2 |
| **Safety** | forbidden_tool / sandbox_escape / out-of-scope access | **Zero tolerance (hard fail)** |

### Regression compares exactly 6 fixed metrics

`pass_rate` / `critical_pass_rate` / `mean_score` / `mean_cost_tokens` /
`total_cost` / `mean_latency_ms`.

**Scale metrics like `total_cases` are deliberately excluded** —
otherwise swapping in a differently sized dataset would be misread as
"a 25% quality regression".

Directionality is explicit: higher pass rates are better; lower cost and latency are better.
The threshold is "**more than** 2% counts", and a `1e-9` epsilon is applied —
the float value of `0.02` is really `0.020000000000000018`,
and without the epsilon "exactly 2%" would be misreported as a regression.

### Undetermined ≠ pass

Without a baseline, the regression and cost gates explicitly mark "undetermined"
instead of quietly emitting a PASS. The report states "undetermined ≠ pass".

---

## 6. RunVersion: the frozen snapshot

```python
RunVersion(id, commit, artifact_yaml, artifact_path,
            dataset_id, dataset_hash, model, tool_versions, label, extra)
```

All inputs of an experiment are frozen together: code commit + artifact yaml +
dataset hash + model + tool versions.

**Why freezing is mandatory**: once the configuration used for evaluation drifts from
the configuration used in production, regression analysis loses all meaning —
this is the number-one cause of regression checks failing at their job.

### The dataset hash only consumes semantic content

The hash input is `version + meta + cases`; **it does not consume file bytes, nor paths**.

- Move the directory → hash unchanged (historical RunVersions do not all go invalid)
- Change content → hash must change (old results cannot masquerade as new ones)

---

## 7. The trajectory judge (L1 rules)

On top of the existing layered judge, agent-specific failure modes are added:

| Rule | What it catches |
|---|---|
| `tool_call_without_result` | tool_calls present but the tool message missing |
| `unresolved_markdown` | Unreplaced markers left in the output |
| `leaked_reasoning` | Chain-of-thought written into the final answer |
| `forbidden_tool_used` | A policy-forbidden tool was used |
| `sandbox_escape_attempt` | An attempt to access paths outside the boundary |

---

## 8. Usage

```bash
# 跑一次，落 trace
aicf run "读取 a.txt" --trace trace.jsonl --case-id read_file_returns_content

# 打分
aicf eval --dataset aicf/harness/datasets/basic.yaml --traces trace.jsonl --out run.json

# 出闸门报告（带 baseline 比回归）
aicf gate --run run.json --baseline baseline.json --out gate.json
```

*(Inline comments: "run once, write a trace" / "score it" / "produce the gate report (with baseline and regression)". The `aicf run` argument is the literal prompt "读取 a.txt" — "read a.txt".)*

```python
from aicf.infra.eval import (Evaluator, GateEvaluator, load_dataset,
                        capture_run_version)

dataset = load_dataset('aicf/harness/datasets/basic.yaml')
version = capture_run_version(dataset=dataset, model='deepseek-chat')
result = Evaluator().evaluate_run(dataset, traces, run_version_id=version.id)
report = GateEvaluator().evaluate(result, baseline)
assert report.passed
```

> Note on datasets shipped in this repo: **`offline`**
> (`aicf/harness/datasets/offline.yaml`) passes offline with the stub model —
> use it as a pipeline smoke test; **`basic`**
> (`aicf/harness/datasets/basic.yaml`) holds 40 quality cases and needs a real model.

---

## 9. Dependency direction

**`aicf/infra/eval` does not import `harness`.**

The evaluation layer only knows the generic `Trace` / `ToolCall` structures it defines
itself; the harness event stream is adapted via `trace_from_events()` (read-only dicts).

The junction with `aicf/harness/learning/evaluator.py` (the existing layered judge)
goes through **application-layer injection**:

```python
AgentTrajectoryEvaluator(extra_checkers=[...])
```

Two tests backstop this rule: a module-level import scan plus a subprocess runtime
assertion (`aicf.infra.eval` loads no `harness.*`).

---

## 10. One easy-to-hit pitfall

Rebuilding a run from the database loses the "critical case" markers — so
`aicf gate --run` ends up **more lenient** than the original evaluation.

**Silently becoming more lenient is the most dangerous failure mode**:
nobody notices the gate has been bypassed.

So, beyond the tables in the plan document §5.1, three extra tables were added:

| Table | Purpose |
|---|---|
| `eval_trace` | The trace itself |
| `eval_run_summary` | Aggregated metrics |
| `eval_result_payload` | The full payload of group / critical / violations |

---

## See also

- [roadmap_1.0.0-rc0.md](../roadmap_1.0.0-rc0.md) — milestones and acceptance checklist
- [security.md](../security.md) — what the safety gate defends against
- [runtime.md](../runtime.md) — where traces come from
