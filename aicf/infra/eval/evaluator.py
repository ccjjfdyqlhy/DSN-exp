# infra/eval/evaluator.py
# 断言语言求值器：把「一次 run 的 trace」变成「结构化评分」。
#
# ── 分层 ──
#   1. 正确性断言（case.expect）：调用了该调的工具吗？输出里有该有的内容吗？
#   2. 指标阈值（case.metrics）：token / 耗时在预算内吗？
#   3. 轨迹判官（L1 规则）：这条轨迹本身有没有结构性/安全性问题？
#
# 三者都不通过 → case 失败。但**安全类问题会额外进入闸门的硬失败通道**，
# 不允许被「平均分不错」掩盖（§4.6.5）。
#
# ── 为什么用「违反项（violation）」而不是「分数」当第一公民？ ──
# 分数只能告诉你「这次差了多少」，告诉不了你「差在哪」。
# 而发版决策需要的是后者：哪个 case 因为哪条规则挂了。
# 所以内部记 violation，score 只是它的派生量。

from __future__ import annotations

import importlib
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Sequence, Union

from .dataset import COMPARISON_ASSERTIONS, COMPARISON_OPS, EvalCase, EvalDataset
from .evaluators.agent_trajectory import AgentTrajectoryEvaluator, TrajectoryFinding
from .tool_vocab import matches_tool_call, resolve_tool_names
from .trace_store import Trace

logger = logging.getLogger("aicf.infra.eval.evaluator")

#: 断言类别。
CATEGORY_EXPECT = "expect"
CATEGORY_METRIC = "metric"
CATEGORY_TRAJECTORY = "trajectory"
CATEGORY_RUN = "run"

#: 自定义断言函数的签名：(trace, case) -> True | False | str(失败说明)
#: 也允许 (trace, case, params) -> ...，params 来自 assert_fn 的 params 字段。
AssertFn = Callable[..., Union[bool, str]]

#: 桩模型/回声式实现会在输出前面挂一个标记（`[stub] …`）。
#: 去掉它之后，剩下的就是「模型原样把输入吐回来」。
_ECHO_MARKER = re.compile(r"^\s*\[[^\]]{0,24}\]\s*")


def is_pure_echo(output: str, trace_input: str) -> bool:
    """这次输出是不是只是把输入回显了一遍。

    为什么要有这个判断：
    评测集的 ``output_contains`` 断言的是「答案里出现了某个内容」。
    如果模型什么都没做、只是把输入原样吐回来，那么当期望内容恰好
    出现在输入里时（例：输入「200 的 10% 是多少」，期望输出含「20」）
    这条断言会被**假通过** —— 一个什么都没答的模型拿到了通过。

    桩模型正是这种行为（输出 `[stub] <input>`），所以本地离线跑评测时
    会看到一批「莫名其妙通过」的用例。那不是能力，是回声。

    判定刻意收得很紧，只有「输出 = 输入（可带标记与标点）」才算回声：
    正常作答即使引用了输入，也不该被判成回声。
    """
    o = _ECHO_MARKER.sub("", output or "").strip()
    i = (trace_input or "").strip()
    if not o or not i:
        return False
    if o == i:
        return True
    if o.startswith(i):
        # 输出 = 输入 + 一点标点/空白 → 仍然算回声
        tail = o[len(i):].strip()
        return not tail.strip(" .,;:!?。，；：！？、")
    return False


@dataclass
class Violation:
    """一条断言/规则失败。

    :param rule: 规则名（如 ``tool_called`` / ``forbidden_tool_used``）。
    :param category: expect / metric / trajectory / run。
    :param expected: 期望值。
    :param actual: 实际值。
    :param message: 人读的说明。
    """

    rule: str
    category: str
    message: str
    expected: Any = None
    actual: Any = None
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "category": self.category,
            "message": self.message,
            "expected": self.expected,
            "actual": self.actual,
            "detail": dict(self.detail),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Violation":
        return cls(
            rule=str(data.get("rule") or ""),
            category=str(data.get("category") or CATEGORY_EXPECT),
            message=str(data.get("message") or ""),
            expected=data.get("expected"),
            actual=data.get("actual"),
            detail=dict(data.get("detail") or {}),
        )


@dataclass
class CaseResult:
    """一个 case 的评测结果（对应 eval_result 表的一行）。"""

    case_id: str
    group: str = "default"
    critical: bool = False
    passed: bool = False
    score: float = 0.0
    metrics: dict[str, float] = field(default_factory=dict)
    failed_rules: list[str] = field(default_factory=list)
    violations: list[Violation] = field(default_factory=list)
    trace_id: str = ""

    @property
    def security_violations(self) -> list[Violation]:
        """安全类违反项（供闸门 0 容忍判定）。"""
        from .gate import SECURITY_RULES  # 局部 import 避免循环

        return [v for v in self.violations if v.rule in SECURITY_RULES]

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "group": self.group,
            "critical": self.critical,
            "passed": self.passed,
            "score": self.score,
            "metrics": dict(self.metrics),
            "failed_rules": list(self.failed_rules),
            "violations": [v.to_dict() for v in self.violations],
            "trace_id": self.trace_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CaseResult":
        return cls(
            case_id=str(data.get("case_id") or ""),
            group=str(data.get("group") or "default"),
            critical=bool(data.get("critical", False)),
            passed=bool(data.get("passed", False)),
            score=float(data.get("score") or 0.0),
            metrics={k: float(v) for k, v in (data.get("metrics") or {}).items()},
            failed_rules=[str(r) for r in (data.get("failed_rules") or [])],
            violations=[Violation.from_dict(v) for v in (data.get("violations") or [])],
            trace_id=str(data.get("trace_id") or ""),
        )


@dataclass
class RunResult:
    """一次评测（一个 RunVersion 在一个 Dataset 上）的完整结果。"""

    run_id: str
    run_version_id: str = ""
    dataset_id: str = ""
    dataset_hash: str = ""
    status: str = "passed"
    started_at: float = 0.0
    ended_at: float = 0.0
    results: list[CaseResult] = field(default_factory=list)
    aggregate: dict[str, float] = field(default_factory=dict)

    # ── 派生量 ──
    @property
    def total_cases(self) -> int:
        return len(self.results)

    @property
    def passed_cases(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def pass_rate(self) -> float:
        return (self.passed_cases / self.total_cases) if self.total_cases else 0.0

    @property
    def critical_results(self) -> list[CaseResult]:
        return [r for r in self.results if r.critical]

    @property
    def critical_pass_rate(self) -> float:
        crit = self.critical_results
        if not crit:
            return self.pass_rate
        return sum(1 for r in crit if r.passed) / len(crit)

    @property
    def failed_case_ids(self) -> list[str]:
        return [r.case_id for r in self.results if not r.passed]

    @property
    def security_violations(self) -> list[Violation]:
        out: list[Violation] = []
        for r in self.results:
            out.extend(r.security_violations)
        return out

    def case_result(self, case_id: str) -> Optional[CaseResult]:
        for r in self.results:
            if r.case_id == case_id:
                return r
        return None

    def group_pass_rates(self) -> dict[str, dict[str, float]]:
        """按分组的通过率（分组是能力维度的基本单元）。"""
        groups: dict[str, list[CaseResult]] = {}
        for r in self.results:
            groups.setdefault(r.group, []).append(r)
        return {
            g: {
                "count": len(rs),
                "passed": sum(1 for r in rs if r.passed),
                "pass_rate": sum(1 for r in rs if r.passed) / len(rs),
            }
            for g, rs in sorted(groups.items())
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.run_id,
            "run_id": self.run_id,
            "run_version_id": self.run_version_id,
            "dataset_id": self.dataset_id,
            "dataset_hash": self.dataset_hash,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "aggregate": dict(self.aggregate),
            "results": [r.to_dict() for r in self.results],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RunResult":
        return cls(
            run_id=str(data.get("run_id") or data.get("id") or ""),
            run_version_id=str(data.get("run_version_id") or ""),
            dataset_id=str(data.get("dataset_id") or ""),
            dataset_hash=str(data.get("dataset_hash") or ""),
            status=str(data.get("status") or "passed"),
            started_at=float(data.get("started_at") or 0.0),
            ended_at=float(data.get("ended_at") or 0.0),
            results=[CaseResult.from_dict(r) for r in (data.get("results") or [])],
            aggregate={k: float(v) for k, v in (data.get("aggregate") or {}).items()},
        )


# ── 自定义断言函数注册表 ──────────────────────────────────
#
# 刻意不提供「任意表达式」：数据集里只能写**名字**，
# 代码留在 Python 里（可测试、可 review、可版本化）。
# 注册表优先，找不到再按 `模块:属性` 走 importlib —— 后者是显式逃生口，
# 仍然比「在 yaml 里塞表达式」安全一个数量级。


class AssertionRegistry:
    """自定义断言函数注册表。"""

    def __init__(self) -> None:
        self._fns: dict[str, AssertFn] = {}

    def register(self, name: str, fn: AssertFn) -> AssertFn:
        """注册一个断言函数，返回它（方便当装饰器用）。"""
        key = str(name).strip()
        if not key:
            raise ValueError("断言函数名不能为空")
        self._fns[key] = fn
        return fn

    def get(self, name: str) -> Optional[AssertFn]:
        return self._fns.get(str(name).strip())

    def names(self) -> list[str]:
        return sorted(self._fns)

    def resolve(self, name: str) -> AssertFn:
        """按名字取断言函数；找不到就按 ``模块:属性`` 导入。

        找不到时抛 KeyError —— 评测集里写了一个不存在的断言函数，
        必须在跑之前就炸，而不是让那个 case「无声通过」。
        """
        key = str(name).strip()
        fn = self._fns.get(key)
        if fn is not None:
            return fn
        if ":" in key:
            mod_name, _, attr = key.partition(":")
        elif "." in key:
            mod_name, _, attr = key.rpartition(".")
        else:
            raise KeyError(f"未注册的断言函数: {name}")
        try:
            module = importlib.import_module(mod_name)
        except ImportError as exc:
            raise KeyError(f"未注册的断言函数: {name}（{exc}）") from exc
        resolved = getattr(module, attr, None)
        if resolved is None or not callable(resolved):
            raise KeyError(f"未注册的断言函数: {name}")
        return resolved


def _default_output_nonempty(trace: Trace, case: EvalCase) -> bool:
    return bool((trace.output or "").strip())


def _default_no_tool_call(trace: Trace, case: EvalCase) -> bool:
    return not trace.tool_calls


def _default_no_error(trace: Trace, case: EvalCase) -> bool:
    return not trace.error


def _default_output_length_lte(trace: Trace, case: EvalCase, params: Mapping[str, Any]) -> bool:
    limit = int(params.get("limit", 0))
    return len(trace.output or "") <= limit


def default_registry() -> AssertionRegistry:
    """内置断言函数表。"""
    reg = AssertionRegistry()
    reg.register("output_nonempty", _default_output_nonempty)
    reg.register("no_tool_call", _default_no_tool_call)
    reg.register("no_error", _default_no_error)
    reg.register("output_length_lte", _default_output_length_lte)
    return reg


# ── 比较 ────────────────────────────────────────────────


def _compare(op: str, actual: float, expected: float) -> bool:
    if op == "lte":
        return actual <= expected
    if op == "lt":
        return actual < expected
    if op == "gte":
        return actual >= expected
    if op == "gt":
        return actual > expected
    if op == "eq":
        return actual == expected
    raise ValueError(f"未知比较算子: {op}")


def _comparison_violation(
    rule: str,
    category: str,
    threshold: Any,
    actual: float,
    *,
    where: str = "",
) -> Optional[Violation]:
    """阈值比较；通过返回 None。"""
    if isinstance(threshold, bool):
        # 布尔阈值没有意义（数据集加载期就会拒），到这里说明调用方绕过了校验。
        raise ValueError(f"{where}{rule}: 阈值不能是布尔值")
    if isinstance(threshold, (int, float)):
        ops: Mapping[str, float] = {"lte": float(threshold)}
    else:
        ops = {str(k): float(v) for k, v in dict(threshold).items()}
    for op, expected in ops.items():
        if op not in COMPARISON_OPS:
            raise ValueError(f"未知比较算子: {op}")
        if not _compare(op, actual, expected):
            return Violation(
                rule=rule,
                category=category,
                message=f"{where}{rule} 超标：实际 {actual:g}，要求 {op} {expected:g}",
                expected=ops,
                actual=actual,
                detail={"op": op, "threshold": expected},
            )
    return None


# ── Evaluator ───────────────────────────────────────────


class Evaluator:
    """把 trace 变成结构化评分。

    :param trajectory_evaluator: 轨迹判官；不传就用默认的 L1 规则集。
    :param registry: 自定义断言函数注册表。
    """

    def __init__(
        self,
        *,
        trajectory_evaluator: Optional[AgentTrajectoryEvaluator] = None,
        registry: Optional[AssertionRegistry] = None,
    ):
        self.trajectory_evaluator = trajectory_evaluator or AgentTrajectoryEvaluator()
        self.registry = registry or default_registry()

    # ── 单 case ──
    def evaluate_case(self, case: EvalCase, trace: Optional[Trace]) -> CaseResult:
        """对一个 case 打分。trace 为 None 视为「没跑起来」，直接判失败。"""
        violations: list[Violation] = []
        checks = 0
        checks_passed = 0

        if trace is None:
            violations.append(
                Violation(
                    rule="missing_trace",
                    category=CATEGORY_RUN,
                    message=f"用例 {case.id} 没有对应的运行轨迹",
                )
            )
            return CaseResult(
                case_id=case.id,
                group=case.group,
                critical=case.critical,
                passed=False,
                score=0.0,
                metrics={},
                failed_rules=["missing_trace"],
                violations=violations,
            )

        if trace.error:
            violations.append(
                Violation(
                    rule="trace_error",
                    category=CATEGORY_RUN,
                    message=f"运行出错: {trace.error}",
                    actual=trace.error,
                )
            )

        # 1) 正确性断言
        for item in case.expect:
            for kind, value in item.items():
                checks += 1
                v = self._eval_expectation(case, trace, str(kind), value)
                if v is None:
                    checks_passed += 1
                else:
                    violations.append(v)

        # 2) 指标阈值
        for item in case.metrics:
            for kind, value in item.items():
                checks += 1
                v = self._eval_expectation(case, trace, str(kind), value, category=CATEGORY_METRIC)
                if v is None:
                    checks_passed += 1
                else:
                    violations.append(v)

        # 3) 轨迹判官（L1 规则）
        for finding in self.trajectory_evaluator.evaluate(trace):
            violations.append(self._finding_to_violation(finding))

        metrics = trace.metrics()
        score = (checks_passed / checks) if checks else (0.0 if violations else 1.0)
        failed_rules = sorted({v.rule for v in violations})
        return CaseResult(
            case_id=case.id,
            group=case.group,
            critical=case.critical,
            passed=not violations,
            score=round(score, 6),
            metrics=metrics,
            failed_rules=failed_rules,
            violations=violations,
            trace_id=trace.trace_id,
        )

    # ── 整轮 ──
    def evaluate_run(
        self,
        dataset: EvalDataset,
        traces: Union[Mapping[str, Trace], Sequence[Trace]],
        *,
        run_id: str = "",
        run_version_id: str = "",
    ) -> RunResult:
        """对整个数据集打分。

        :param traces: ``{case_id: Trace}`` 映射，或带 ``case_id`` 的 Trace 列表。
        :param run_id: 本轮 id；不给就按时间生成。
        """
        started = time.time()
        by_case = self._index_traces(traces)
        results = [self.evaluate_case(case, by_case.get(case.id)) for case in dataset.cases]
        ended = time.time()
        run = RunResult(
            run_id=run_id or f"run_{int(started * 1000)}",
            run_version_id=run_version_id,
            dataset_id=dataset.id,
            dataset_hash=dataset.hash,
            status="passed" if all(r.passed for r in results) else "failed",
            started_at=started,
            ended_at=ended,
            results=results,
        )
        run.aggregate = aggregate_metrics(run)
        return run

    # ── 内部 ──
    @staticmethod
    def _index_traces(
        traces: Union[Mapping[str, Trace], Sequence[Trace]],
    ) -> dict[str, Trace]:
        if isinstance(traces, Mapping):
            out: dict[str, Trace] = {}
            for key, tr in traces.items():
                if tr is not None:
                    out[str(key)] = tr
            return out
        out = {}
        for tr in traces or ():
            if tr is None:
                continue
            cid = tr.case_id
            if not cid:
                continue
            out[cid] = tr
        return out

    @staticmethod
    def _finding_to_violation(finding: TrajectoryFinding) -> Violation:
        return Violation(
            rule=finding.rule,
            category=CATEGORY_TRAJECTORY,
            message=finding.message,
            detail=dict(finding.detail),
        )

    def _eval_expectation(
        self,
        case: EvalCase,
        trace: Trace,
        kind: str,
        value: Any,
        *,
        category: str = CATEGORY_EXPECT,
    ) -> Optional[Violation]:
        """求值一条断言；通过返回 None，失败返回 Violation。"""
        where = f"[{case.id}] "
        if kind == "tool_called":
            names = [value] if isinstance(value, str) else list(value)
            called = trace.called_tools
            # 评测集写的是抽象能力名（fs.read），要落到真实注册表上比对
            # （file.read）—— 见 tool_vocab.py。
            missing = [n for n in names if not matches_tool_call(n, called)]
            if missing:
                return Violation(
                    rule=kind,
                    category=category,
                    message=f"{where}没有调用工具: {', '.join(missing)}",
                    expected=list(names),
                    actual=trace.tool_names,
                    detail={"missing": missing,
                            "expected_real": {n: list(resolve_tool_names(n))
                                              for n in missing}},
                )
            return None
        if kind == "output_contains":
            items = [value] if isinstance(value, str) else list(value)
            output = trace.output or ""
            if is_pure_echo(output, trace.input):
                return Violation(
                    rule=kind,
                    category=category,
                    message=f"{where}输出只是把输入回显了一遍，不算作答",
                    expected=list(items),
                    actual=output[:500],
                    detail={"echo": True},
                )
            missing = [s for s in items if s not in output]
            if missing:
                return Violation(
                    rule=kind,
                    category=category,
                    message=f"{where}输出缺少内容: {', '.join(repr(m) for m in missing)}",
                    expected=list(items),
                    actual=output[:500],
                    detail={"missing": missing},
                )
            return None
        if kind == "output_matches":
            items = [value] if isinstance(value, str) else list(value)
            output = trace.output or ""
            if is_pure_echo(output, trace.input):
                return Violation(
                    rule=kind,
                    category=category,
                    message=f"{where}输出只是把输入回显了一遍，不算作答",
                    expected=list(items),
                    actual=output[:500],
                    detail={"echo": True},
                )
            unmatched = [s for s in items if not re.search(s, output)]
            if unmatched:
                return Violation(
                    rule=kind,
                    category=category,
                    message=f"{where}输出未匹配正则: {', '.join(unmatched)}",
                    expected=list(items),
                    actual=output[:500],
                    detail={"unmatched": unmatched},
                )
            return None
        if kind == "max_tool_calls":
            count = len(trace.tool_calls)
            if count > int(value):
                return Violation(
                    rule=kind,
                    category=category,
                    message=f"{where}工具调用 {count} 次，超过上限 {value}",
                    expected=int(value),
                    actual=count,
                )
            return None
        if kind == "forbid_tools":
            names = [value] if isinstance(value, str) else list(value)
            # 禁止的是「这一类工具」：禁 fs.delete 也就等于禁 file.edit。
            used = [n for n in names if matches_tool_call(n, trace.called_tools)]
            if used:
                return Violation(
                    rule=kind,
                    category=category,
                    message=f"{where}调用了被禁止的工具: {', '.join(used)}",
                    expected=list(names),
                    actual=trace.tool_names,
                    detail={"used": used},
                )
            return None
        if kind == "no_side_effect":
            if not value:
                return None
            offenders = trace.side_effect_tools
            if offenders:
                return Violation(
                    rule=kind,
                    category=category,
                    message=f"{where}出现了有副作用的工具调用: {', '.join(offenders)}",
                    expected="无副作用",
                    actual=offenders,
                    detail={"tools": offenders},
                )
            return None
        if kind in COMPARISON_ASSERTIONS:
            actual = trace.total_tokens if kind == "cost_tokens" else trace.latency_ms
            return _comparison_violation(kind, category, value, float(actual), where=where)
        if kind == "assert_fn":
            return self._eval_assert_fn(case, trace, value)
        # 未知断言在 dataset 加载期就会被拒；到这里说明有 bug。
        raise ValueError(f"未知断言类型: {kind}")

    def _eval_assert_fn(self, case: EvalCase, trace: Trace, value: Any) -> Optional[Violation]:
        """求值自定义断言函数。

        写法有两种：
          ``assert_fn: my_checker``                     —— 无参
          ``assert_fn: {name: my_checker, params: {}}`` —— 带参
        """
        params: dict[str, Any] = {}
        if isinstance(value, Mapping):
            name = str(value.get("name") or "")
            params = dict(value.get("params") or {})
        else:
            name = str(value)
        if not name:
            return Violation(
                rule="assert_fn",
                category=CATEGORY_EXPECT,
                message=f"[{case.id}] assert_fn 缺少函数名",
            )
        try:
            fn = self.registry.resolve(name)
        except KeyError as exc:
            return Violation(
                rule="assert_fn",
                category=CATEGORY_EXPECT,
                message=f"[{case.id}] {exc}",
                expected=name,
            )
        try:
            try:
                outcome = fn(trace, case, params) if params else fn(trace, case)
            except TypeError:
                outcome = fn(trace, case)
        except Exception as exc:
            # 自定义断言抛异常 = 判不出来 = 不通过（fail-closed）。
            logger.warning("断言函数 %s 执行失败: %s", name, exc)
            return Violation(
                rule="assert_fn",
                category=CATEGORY_EXPECT,
                message=f"[{case.id}] 断言函数 {name} 执行失败: {exc}",
                expected=name,
                detail={"error": str(exc)},
            )
        if outcome is True:
            return None
        if outcome is False:
            return Violation(
                rule="assert_fn",
                category=CATEGORY_EXPECT,
                message=f"[{case.id}] 断言函数 {name} 未通过",
                expected=name,
            )
        return Violation(
            rule="assert_fn",
            category=CATEGORY_EXPECT,
            message=f"[{case.id}] 断言函数 {name} 未通过: {outcome}",
            expected=name,
            actual=str(outcome),
        )


# ── 聚合指标 ────────────────────────────────────────────


def aggregate_metrics(run: RunResult) -> dict[str, float]:
    """把一轮结果聚合成指标字典（回归与成本闸门都基于它）。

    指标命名刻意和 §5.1 / §4.6.5 的说法对齐：
      pass_rate / critical_pass_rate —— 越高越好
      mean_cost_tokens / total_cost / mean_latency_ms —— 越低越好
    """
    results = run.results
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    crit = [r for r in results if r.critical]
    crit_passed = sum(1 for r in crit if r.passed)

    def _mean(key: str) -> float:
        vals = [float(r.metrics.get(key, 0.0)) for r in results if r.metrics]
        return sum(vals) / len(vals) if vals else 0.0

    def _total(key: str) -> float:
        return sum(float(r.metrics.get(key, 0.0)) for r in results)

    return {
        "total_cases": float(total),
        "passed_cases": float(passed),
        "pass_rate": (passed / total) if total else 0.0,
        "critical_cases": float(len(crit)),
        "critical_passed": float(crit_passed),
        "critical_pass_rate": (crit_passed / len(crit)) if crit else ((passed / total) if total else 0.0),
        "mean_score": (sum(r.score for r in results) / total) if total else 0.0,
        "mean_cost_tokens": _mean("cost_tokens"),
        "total_cost_tokens": _total("cost_tokens"),
        "max_cost_tokens": max((float(r.metrics.get("cost_tokens", 0.0)) for r in results), default=0.0),
        "mean_latency_ms": _mean("latency_ms"),
        "total_cost": _total("cost"),
        "tool_calls_total": _total("tool_calls"),
        "security_violations": float(sum(len(r.security_violations) for r in results)),
    }
