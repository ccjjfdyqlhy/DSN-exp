# harness/learning/probes.py
"""行为级探针：跑一组 probe prompt → 生成 → 打分 → **与 baseline 对比**。
#
# 为什么要有探针（计划二 §4.2）：
#   验证集 loss 下降**不等于**行为变好了。loss 只说明"更像训练集"，
#   而我们要的是"遇到威胁时真的先保全""读到别人的故事时真的具体"。
#   所以必须有一组**行为探针**，跑生成、看行为。
#
# 分层判官（与 evaluator 一致）：
#   L1 规则层 —— 零成本、永远先跑、唯一不可被污染的一层；
#   L2/L3     —— 调用方注入（本地判官 / 远端教师）。
#
# 纪律：
#   1. **没有对比就不许晋级**：`compare_to_baseline()` 拿不到 baseline 时，
#      `can_promote()` 一律返回 False。孤立的绝对分说明不了"变好了还是变差了"。
#   2. **关键探针不能有回退**：`critical=True` 的探针一旦低于 baseline，直接否。
#   3. **探针集由调用方提供**（应用层决定"要测什么"），
#      本模块只负责"怎么跑、怎么打分、怎么比"。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from infra.orchestrator.base import ChatMessage

from .evaluator import EvalPolicy, EvalScore, Evaluator

logger = logging.getLogger("harness.learning.probes")

#: 规则检查器签名：(生成文本) -> (是否通过, 说明)
RuleChecker = Callable[[str], "tuple[bool, str]"]


@dataclass
class Probe:
    """一条行为探针。

    category 用来分层看指标（人格连续性 / 边界遵守 / 情绪-动作一致性 / 共情质量 …）。
    critical 的探针**不能有回退**——这类通常是"边界遵守"这种一旦破了就不该上线的。
    checker 是**规则层**检查（零成本、不可污染）；没有它就只靠判官打分。
    """

    name: str
    prompt: str
    category: str = "general"
    rubric: str = ""
    critical: bool = False
    system: str = ""
    context: list[dict] = field(default_factory=list)
    checker: Optional[RuleChecker] = None

    def to_messages(self) -> list[ChatMessage]:
        msgs: list[ChatMessage] = []
        if self.system:
            msgs.append(ChatMessage.system(self.system))
        for item in self.context:
            msgs.append(
                ChatMessage(
                    role=str(item.get("role", "user")),
                    content=item.get("content", ""),
                )
            )
        msgs.append(ChatMessage.user(self.prompt))
        return msgs


@dataclass
class ProbeResult:
    """一条探针的跑分结果。"""

    name: str
    category: str = "general"
    output: str = ""
    score: float = 0.0
    passed: bool = False
    critical: bool = False
    reasons: list[str] = field(default_factory=list)
    layers: dict[str, float] = field(default_factory=dict)
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "output": self.output[:500],
            "score": round(self.score, 4),
            "passed": self.passed,
            "critical": self.critical,
            "reasons": list(self.reasons),
            "layers": {k: round(v, 4) for k, v in self.layers.items()},
            "error": self.error,
        }


@dataclass
class ProbeReport:
    """一批探针的跑分报告。"""

    results: list[ProbeResult] = field(default_factory=list)
    baseline: Optional["ProbeReport"] = None

    # ── 汇总 ──

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    def pass_rate(self, *, category: str = "") -> float:
        items = [r for r in self.results if not category or r.category == category]
        if not items:
            return 0.0
        return sum(1 for r in items if r.passed) / len(items)

    def mean_score(self, *, category: str = "") -> float:
        items = [r for r in self.results if not category or r.category == category]
        if not items:
            return 0.0
        return sum(r.score for r in items) / len(items)

    def by_category(self) -> dict[str, dict[str, Any]]:
        cats: dict[str, dict[str, Any]] = {}
        for r in self.results:
            slot = cats.setdefault(r.category, {"count": 0, "passed": 0, "score_sum": 0.0})
            slot["count"] += 1
            slot["passed"] += 1 if r.passed else 0
            slot["score_sum"] += r.score
        return {
            cat: {
                "count": stat["count"],
                "passed": stat["passed"],
                "pass_rate": round(stat["passed"] / stat["count"], 4),
                "mean_score": round(stat["score_sum"] / stat["count"], 4),
            }
            for cat, stat in cats.items()
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "passed": self.passed,
            "pass_rate": round(self.pass_rate(), 4),
            "mean_score": round(self.mean_score(), 4),
            "by_category": self.by_category(),
            "results": [r.as_dict() for r in self.results],
            "baseline": self.baseline.as_dict() if self.baseline else None,
        }

    # ── 与 baseline 对比 ── ────────────────────────────────────────────

    def compare_to_baseline(self, baseline: "ProbeReport") -> "ProbeReport":
        """把 baseline 挂上来（对比表的另一半）。"""
        self.baseline = baseline
        return self

    def comparison_table(self) -> list[dict[str, Any]]:
        """逐条探针的对比表：候选 vs baseline。

        没有 baseline 时返回空表——**这就是「没有对比就不许晋级」的根据**。
        """
        if self.baseline is None:
            return []
        base_by_name = {r.name: r for r in self.baseline.results}
        rows: list[dict[str, Any]] = []
        for r in self.results:
            b = base_by_name.get(r.name)
            rows.append({
                "name": r.name,
                "category": r.category,
                "critical": r.critical,
                "candidate_score": round(r.score, 4),
                "baseline_score": round(b.score, 4) if b else None,
                "delta": round(r.score - b.score, 4) if b else None,
                "candidate_passed": r.passed,
                "baseline_passed": b.passed if b else None,
                "regressed": bool(b and r.score < b.score - 1e-9),
            })
        return rows

    def can_promote(self, *, eps: float = 0.0) -> tuple[bool, list[str]]:
        """能不能晋级：与 baseline 对比 + 关键探针不许回退。

        返回 (是否通过, 原因列表)。
        """
        reasons: list[str] = []
        if self.baseline is None:
            reasons.append("没有 baseline 对比：孤立的绝对分说明不了变好还是变差")
            return False, reasons

        rows = self.comparison_table()
        regressed = [r for r in rows if r.get("regressed")]
        critical_bad = [
            r for r in rows
            if r.get("critical") and r.get("baseline_score") is not None
            and (r.get("candidate_score") or 0.0) < (r.get("baseline_score") or 0.0) - eps
        ]
        if critical_bad:
            reasons.append(
                "关键探针有回退: " + ", ".join(r["name"] for r in critical_bad)
            )
        non_critical_bad = [
            r for r in regressed
            if not r.get("critical") and r.get("candidate_score", 0.0) < (r.get("baseline_score") or 0.0) - eps
        ]
        if non_critical_bad:
            reasons.append(
                "非关键探针有回退: " + ", ".join(r["name"] for r in non_critical_bad)
            )
        return (not reasons), reasons


class ProbeRunner:
    """行为探针跑器。

    client 要实现 `infra.orchestrator.base.IChatClient` 的 `invoke`
    （本地 llama.cpp / 远端 API 都行）。
    """

    def __init__(
        self,
        client: Any,
        *,
        evaluator: Optional[Evaluator] = None,
        policy: Optional[EvalPolicy] = None,
        disable_thinking: bool = True,
    ) -> None:
        self.client = client
        self.policy = policy or EvalPolicy(threshold=0.6, hard_gate=True)
        self.evaluator = evaluator or Evaluator(policy=self.policy)
        #: 探针生成时**关掉 thinking**。
        #:
        #: 为什么必须关：学生是按 non-thinking 模板训的（训练期禁 thinking），
        #: 而 Qwen3 默认会思考——max_tokens 全被思考吃掉，**返回的 content 是空的**。
        #: 实测：max_tokens=64 → 64 token 全是 reasoning、content 空；
        #: 关掉后 3 token 就答出动作名。
        #:
        #: 附带好处：探针快了十几倍（不用等它想完）。
        self.disable_thinking = bool(disable_thinking)

    def run(
        self,
        probes: list[Probe],
        *,
        has_user_data: bool = False,
        max_tokens: int = 512,
        temperature: float = 0.0,
    ) -> ProbeReport:
        """跑一遍探针集。"""
        report = ProbeReport()
        for probe in probes:
            result = ProbeResult(
                name=probe.name,
                category=probe.category,
                critical=probe.critical,
            )
            try:
                output = self._generate(probe, max_tokens=max_tokens, temperature=temperature)
                result.output = output
            except Exception as exc:  # noqa: BLE001
                result.error = f"{type(exc).__name__}: {exc}"
                result.reasons.append(result.error)
                report.results.append(result)
                continue

            # 规则层：零成本、永远先跑
            if probe.checker is not None:
                try:
                    ok, note = probe.checker(output)
                except Exception as exc:  # noqa: BLE001
                    ok, note = False, f"检查器异常: {exc}"
                result.reasons.append(f"规则: {note}")
                if not ok:
                    result.score = 0.0
                    result.passed = False
                    report.results.append(result)
                    continue

            # 判官层：内容质量
            score: EvalScore = self.evaluator.evaluate(
                [{"role": "user", "content": probe.prompt},
                 {"role": "assistant", "content": output}],
                rubric=probe.rubric,
                has_user_data=has_user_data,
            )
            result.score = max(0.0, min(1.0, float(score.total)))
            result.passed = score.passed
            result.layers = dict(score.layers)
            result.reasons.extend(score.reasons)
            report.results.append(result)
        return report

    def _generate(self, probe: Probe, *, max_tokens: int, temperature: float) -> str:
        messages = probe.to_messages()
        if self.disable_thinking:
            try:
                resp = self.client.invoke(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                )
            except TypeError:
                # 客户端不支持 extra_body → 退回最简调用
                resp = self.client.invoke(
                    messages, temperature=temperature, max_tokens=max_tokens,
                )
        else:
            resp = self.client.invoke(
                messages, temperature=temperature, max_tokens=max_tokens,
            )
        content = getattr(resp, "content", None)
        if content is None and isinstance(resp, dict):
            choices = resp.get("choices") or []
            content = (choices[0].get("message") or {}).get("content") if choices else ""
        return str(content or "")
