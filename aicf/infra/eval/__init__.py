# infra/eval/
# 评测闭环：Dataset → Evaluator → Gate（策划案 §4.6）。
#
# ── 这个包的依赖方向 ──
# infra/eval **不 import aicf.harness**（§6.2）：
# 评测层只消费本包定义的通用数据结构（Trace / ToolCall），
# 任何执行内核（ReAct / Workflow / Planner / 外部进程）都能把
# 自己的运行结果适配成 Trace 喂进来。
# 与 harness/learning/evaluator.py 的分层判官通过**应用层注入**汇合，
# 不产生包依赖（见 evaluators/agent_trajectory.py 的说明）。
#
# ── 六个概念 ──
#   Dataset    —— 带断言的任务样本（yaml / jsonl）
#   Trace      —— 一次运行的完整事件流（通用结构，见 trace_store.py）
#   Evaluator  —— 对一次 run 产出结构化评分（score + metrics + failed_rules）
#   RunVersion —— 一次实验的冻结快照（commit + artifact + dataset hash + model + tools）
#   Gate       —— 四道上线闸门（质量 / 回归 / 成本 / 安全）
#   Regression —— 与 baseline 的逐项差异 + 阈值判定

from .dataset import (
    ASSERTION_KINDS,
    COMPARISON_OPS,
    DatasetError,
    EvalCase,
    EvalDataset,
    dataset_summary,
    load_dataset,
    load_dataset_from_spec,
    validate_dataset,
)
from .evaluator import (
    AssertionRegistry,
    CaseResult,
    Evaluator,
    RunResult,
    Violation,
    aggregate_metrics,
    default_registry,
)
from .evaluators.agent_trajectory import (
    L1_RULES,
    AgentTrajectoryEvaluator,
    TrajectoryFinding,
)
from .experiment import (
    Experiment,
    Variant,
    VariantComparison,
    build_experiment,
    format_comparison_table,
)
from .gate import (
    GATE_COST,
    GATE_NAMES,
    GATE_QUALITY,
    GATE_REGRESSION,
    GATE_SAFETY,
    SECURITY_RULES,
    GateEvaluator,
    GateOutcome,
    GateReport,
    GateThresholds,
)
from .regression import (
    DEFAULT_MAX_DROP,
    MetricDelta,
    RegressionReport,
    compare_metrics,
)
from .run_version import RunVersion, capture_run_version, git_commit
from .sampling import (
    DEFAULT_SAMPLE_RATIO,
    ReplayQueue,
    ReplayQueueItem,
    SamplingDecision,
    SessionSampler,
)
from .badcase import (
    HARD_CASE_GROUP,
    STATUS_DISMISSED,
    STATUS_LABELLED,
    STATUS_NEW,
    STATUS_QUEUED,
    BadCaseIntake,
    LabelledBadCase,
)
from .trace_store import (
    EFFECT_EFFECTFUL,
    EFFECT_IDEMPOTENT,
    EFFECT_PURE,
    EFFECT_UNKNOWN,
    ToolCall,
    Trace,
    TraceStore,
    read_trace_jsonl,
    trace_from_events,
    write_trace_jsonl,
)

__all__ = [
    # dataset
    "ASSERTION_KINDS", "COMPARISON_OPS", "DatasetError", "EvalCase", "EvalDataset",
    "dataset_summary", "load_dataset", "load_dataset_from_spec", "validate_dataset",
    # evaluator
    "AssertionRegistry", "CaseResult", "Evaluator", "RunResult", "Violation",
    "aggregate_metrics", "default_registry",
    # 判官
    "L1_RULES", "AgentTrajectoryEvaluator", "TrajectoryFinding",
    # experiment
    "Experiment", "Variant", "VariantComparison", "build_experiment", "format_comparison_table",
    # gate
    "GATE_COST", "GATE_NAMES", "GATE_QUALITY", "GATE_REGRESSION", "GATE_SAFETY",
    "SECURITY_RULES", "GateEvaluator", "GateOutcome", "GateReport", "GateThresholds",
    # regression
    "DEFAULT_MAX_DROP", "MetricDelta", "RegressionReport", "compare_metrics",
    # run version
    "RunVersion", "capture_run_version", "git_commit",
    # sampling（rc2 P2：线上抽样）
    "DEFAULT_SAMPLE_RATIO", "ReplayQueue", "ReplayQueueItem",
    "SamplingDecision", "SessionSampler",
    # badcase（rc2 P2：坏样本回流）
    "HARD_CASE_GROUP", "STATUS_DISMISSED", "STATUS_LABELLED", "STATUS_NEW",
    "STATUS_QUEUED", "BadCaseIntake", "LabelledBadCase",
    # trace
    "EFFECT_EFFECTFUL", "EFFECT_IDEMPOTENT", "EFFECT_PURE", "EFFECT_UNKNOWN",
    "ToolCall", "Trace", "TraceStore", "read_trace_jsonl", "trace_from_events",
    "write_trace_jsonl",
]
