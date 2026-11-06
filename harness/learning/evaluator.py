
# harness/learning/evaluator.py
# 分层判官：把"这条轨迹能不能拿去训练"这件事拆成三层来看。
#
# 为什么分层（而不是一个大模型打分）：
#   便宜且确定的部分**不该**交给模型。结构完整性、工具轨迹合法性、
#   思维链泄漏这类问题用规则判，结果可复现、零成本、零延迟，
#   而且不会因为教师心情不好就误判。模型只该负责"内容好不好"。
#
# 三层：
#   L1 规则层（本地、确定性、免费）—— **一票否决**。
#      不通过就直接淘汰，不进入后面的层。
#   L2 本地判官层（本地模型：Bonsai / JEV）—— 按评分标准打内容分。
#   L3 远端教师层（远端 API）—— 可选，最贵，只在 L2 可疑时兜底或终审。
#
# 权重默认 L1:L2:L3 = 0.2 : 0.6 : 0.2；L3 没配置时按剩余权重归一化。

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from infra.finetune.dataset import normalize_messages, validate_messages

logger = logging.getLogger("harness.learning.evaluator")

#: 训练样本里不该出现的内容（与 dataset_builder 的 STRIP_FIELDS 对应）。
LEAK_FIELDS = ("reasoning_content", "thinking", "chain_of_thought")

#: 受保护字段（目标层）不该出现在训练样本里。
PROTECTED_FIELDS = ("constitution", "drives", "affect_state")


@dataclass
class EvalScore:
    """一次评测的结果。"""

    total: float = 0.0
    layers: dict[str, float] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    passed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": round(self.total, 4),
            "layers": {k: round(v, 4) for k, v in self.layers.items()},
            "reasons": list(self.reasons),
            "passed": self.passed,
        }


@dataclass
class EvalPolicy:
    """评测策略。"""

    threshold: float = 0.7
    weights: dict[str, float] = field(default_factory=lambda: {"rules": 0.2, "local": 0.6, "teacher": 0.2})
    #: 规则层是否一票否决。
    hard_gate: bool = True
    #: L2/L3 都不可用时是否允许通过（用于"只有规则可用"的降级场景）。
    allow_rules_only: bool = False


class RuleEvaluator:
    """L1：本地确定性规则。"""

    def __init__(self, *, max_tokens: int = 1024, min_assistant_turns: int = 1):
        self.max_tokens = max_tokens
        self.min_assistant_turns = min_assistant_turns

    def evaluate(self, messages: list[dict]) -> tuple[float, list[str]]:
        """返回 (分数 0~1, 问题列表)。分数 < 1 说明有扣分项。"""
        problems: list[str] = []
        msgs = normalize_messages(messages)
        if not msgs:
            return 0.0, ["消息为空"]

        # 1) 结构完整性：tool 消息必须跟在 assistant(tool_calls) 后面。
        for problem in validate_messages(msgs):
            problems.append(problem)

        # 2) assistant 轮次数量。
        assistant_turns = sum(1 for m in msgs if m.get("role") == "assistant")
        if assistant_turns < self.min_assistant_turns:
            problems.append(f"assistant 轮次不足（{assistant_turns} < {self.min_assistant_turns}）")

        # 3) 思维链泄漏：训练样本里不该带推理内容。
        leaked = [k for k in LEAK_FIELDS if any(k in m for m in msgs)]
        if leaked:
            problems.append(f"包含推理内容字段: {', '.join(leaked)}")

        # 4) 目标层泄漏。
        blob = str(msgs)
        for field in PROTECTED_FIELDS:
            if field in blob:
                problems.append(f"包含受保护字段: {field}")

        # 5) 长度：太长的样本在 11GB 卡上训练会被截断，等于浪费。
        total_chars = sum(len(str(m.get("content") or "")) for m in msgs)
        estimated = total_chars // 4
        if estimated > self.max_tokens:
            problems.append(f"长度超限（估算 {estimated} > {self.max_tokens} token）")

        if not problems:
            return 1.0, []
        # 每条问题扣 0.25，最低 0 分。
        return max(0.0, 1.0 - 0.25 * len(problems)), problems


class Evaluator:
    """分层评测器。"""

    def __init__(
        self,
        *,
        policy: Optional[EvalPolicy] = None,
        rules: Optional[RuleEvaluator] = None,
        local_judge: Optional[Callable[[list[dict], str], float]] = None,
        teacher: Optional[Any] = None,
    ):
        self.policy = policy or EvalPolicy()
        self.rules = rules or RuleEvaluator()
        #: L2：本地判官。签名 (messages, rubric) -> 0~1 的分数。
        self._local_judge = local_judge
        #: L3：远端教师（harness.learning.teacher.TeacherRefiner）。
        self._teacher = teacher

    def evaluate(
        self,
        messages: list[dict],
        *,
        rubric: str = "",
        has_user_data: bool = False,
    ) -> EvalScore:
        """评测一条轨迹。"""
        result = EvalScore()
        msgs = normalize_messages(messages)

        # L1 规则层
        rule_score, problems = self.rules.evaluate(msgs)
        result.layers["rules"] = rule_score
        result.reasons.extend(problems)
        if self.policy.hard_gate and problems:
            result.passed = False
            result.total = rule_score
            return result

        # L2 本地判官层
        if self._local_judge is not None:
            try:
                result.layers["local"] = max(0.0, min(1.0, float(self._local_judge(msgs, rubric))))
            except Exception as exc:
                logger.warning("本地判官失败: %s", exc)
                result.reasons.append(f"本地判官不可用: {exc}")

        # L3 远端教师层
        if self._teacher is not None:
            try:
                score = self._teacher.score(msgs, rubric, has_user_data=has_user_data)
                result.layers["teacher"] = float(score.get("score", 0.0))
                if score.get("reason"):
                    result.reasons.append(f"教师评语: {score['reason']}")
            except Exception as exc:
                logger.warning("教师评测失败: %s", exc)
                result.reasons.append(f"教师评测不可用: {exc}")

        result.total = self._aggregate(result.layers)
        result.passed = result.total >= self.policy.threshold
        return result

    def _aggregate(self, layers: dict[str, float]) -> float:
        """按权重加权；缺失的层把权重按比例分给其余层。"""
        weights = self.policy.weights
        present = {k: w for k, w in weights.items() if k in layers}
        total_weight = sum(present.values())
        if total_weight <= 0:
            # 没有可用的加权层（只剩 rules 但 hard_gate 放行了）→ 用规则分。
            return float(layers.get("rules", 0.0))
        return sum(layers[k] * w for k, w in present.items()) / total_weight
