# harness/decisions/use_cases.py
"""Decision use cases - turning "read a probability" into "answer a concrete
question".
#
# ## Position
#
# core.py gives the generic capability (yes/no, choice, score). This module
# wraps it into judges for concrete situations. Each one carries
#
#   * a clear question (how it is asked decides how accurate the probability
#     is),
#   * a threshold (how high counts as yes),
#   * a degradation path (what to answer when the model is unavailable).
#
# The degradation is a hard requirement: a decision is an extra, not the main
# path. Voice conversations, tool routing and crisis checks all have to keep
# working when the decision model is down, they just lose one signal.
#
# ## Why every scenario asks exactly one question
#
# One forward pass answers one question. Packing three questions into one
# request makes the model split the difference and produce a distribution that
# satisfies none of them. So the emotion, the follow up and the crisis check
# are three forward passes (tens to hundreds of milliseconds each). Every
# adapter here therefore asks a single question, and the caller decides
# whether that latency is worth paying.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence, Union

from .core import (
    DecisionError,
    DecisionRequest,
    DecisionResult,
    letter_labels,
)

logger = logging.getLogger("DecisionUseCases")

#: A decider takes a request and returns a result.
Decider = Callable[[DecisionRequest], DecisionResult]


def _letter_index(label: str) -> Optional[int]:
    """Letter label to index (A=0 ... Z=25, AA=26 ...). None when invalid."""
    if not label or not label.isalpha():
        return None
    idx = 0
    for ch in label.upper():
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


@dataclass
class GateOutcome:
    """The outcome of a yes/no judgement.

    :param value: the conclusion.
    :param probability: the probability the model gave (0 when degraded).
    :param confident: whether the probability cleared the threshold. Below it
        the value still follows the probability, but the caller should know
        this is a weak signal.
    :param degraded: whether the degradation path was taken (model unavailable
        or the request was invalid).
    :param reason: a human readable reason, set when degraded.
    """

    value: bool = False
    probability: float = 0.0
    confident: bool = False
    degraded: bool = False
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "value": self.value,
            "probability": round(self.probability, 6),
            "confident": self.confident,
            "degraded": self.degraded,
            "reason": self.reason,
        }


@dataclass
class Classification:
    """The outcome of a multi label classification."""

    label: str = ""
    description: str = ""
    probability: float = 0.0
    confidence: float = 0.0
    distribution: dict[str, float] = field(default_factory=dict)
    degraded: bool = False
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "description": self.description,
            "probability": round(self.probability, 6),
            "confidence": round(self.confidence, 6),
            "distribution": {k: round(v, 6) for k, v in self.distribution.items()},
            "degraded": self.degraded,
            "reason": self.reason,
        }


# -- generic gate --

class DecisionGate:
    """A yes/no gate: ask one question, answer above a threshold.

    Usage::

        gate = DecisionGate("Does this need a human right now?", threshold=0.7)
        out = gate.evaluate("the user said ...")
        if out.value and out.confident:
            ...
    """

    def __init__(
        self,
        question: str,
        *,
        threshold: float = 0.8,
        name: str = "",
        state_builder: Optional[Callable[[str], str]] = None,
        decider: Optional[Decider] = None,
    ):
        self.question = question
        self.threshold = float(threshold)
        self.name = name or question[:24]
        self.state_builder = state_builder
        self.decider = decider

    def evaluate(self, state: str, *, decider: Optional[Decider] = None) -> GateOutcome:
        """Run one judgement.

        Never raises: when no decision is possible it returns the degraded
        outcome with value False.
        """
        fn = decider or self.decider
        if fn is None:
            return GateOutcome(degraded=True, reason="no decider configured")
        text = self.state_builder(state) if self.state_builder else state
        try:
            res = fn(DecisionRequest(type="yes_no", question=self.question, state=text))
        except Exception as e:
            logger.warning("decision gate %s failed, degraded: %s", self.name, e)
            return GateOutcome(degraded=True, reason=str(e)[:200])

        prob = float(res.probability)
        value = bool(res.answer)
        return GateOutcome(
            value=value,
            probability=prob,
            confident=(prob >= self.threshold) if value else (prob <= 1.0 - self.threshold),
            degraded=False,
            reason="",
        )


# -- emotion --

#: Emotion label to (valence, arousal).
#: valence runs from -1 (very negative) to +1 (very positive), arousal from 0
#: (calm) to 1 (agitated).
EMOTION_TABLE: dict[str, tuple[float, float]] = {
    "平静": (0.0, 0.1),
    "开心": (0.8, 0.6),
    "低落": (-0.7, 0.2),
    "生气": (-0.6, 0.9),
    "焦虑": (-0.5, 0.8),
    "疲惫": (-0.4, 0.05),
    "惊讶": (0.1, 0.85),
}


@dataclass
class EmotionReading:
    """One emotion reading."""

    label: str = "平静"
    valence: float = 0.0
    arousal: float = 0.1
    probability: float = 0.0
    confidence: float = 0.0
    degraded: bool = False
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "valence": round(self.valence, 3),
            "arousal": round(self.arousal, 3),
            "probability": round(self.probability, 6),
            "confidence": round(self.confidence, 6),
            "degraded": self.degraded,
            "reason": self.reason,
        }


def probe_emotion(text: str, decider: Decider, *, extra_context: str = "") -> EmotionReading:
    """Read the emotion of a piece of text.

    One multi option question instead of a valence score plus an arousal score:
    it halves the latency and discrete labels are what the model reads best
    (it is much less sensitive to a continuous value like -0.3). Valence and
    arousal come from the label table (:data:`EMOTION_TABLE`).
    """
    labels = list(EMOTION_TABLE.keys())
    question = "这句话的情绪最接近下面哪一个？"
    state = (extra_context + "\n" if extra_context else "") + (text or "")
    try:
        res = decider(DecisionRequest(
            type="choice", question=question, state=state, options=labels))
    except Exception as e:
        logger.warning("emotion read failed, degraded to calm: %s", e)
        return EmotionReading(degraded=True, reason=str(e)[:200])

    # A list of options is numbered A, B, C, so the semantic name sits on the
    # label and the answer is the option code. Reading the answer instead
    # would make every emotion come back as "A".
    label = str(res.label or res.answer or "平静")
    valence, arousal = EMOTION_TABLE.get(label, (0.0, 0.1))
    return EmotionReading(
        label=label,
        valence=valence,
        arousal=arousal,
        probability=float(res.probability),
        confidence=float(res.confidence),
        degraded=False,
    )


# -- crisis --

#: Crisis levels: none, watch, critical.
CRISIS_LEVELS = ("none", "watch", "critical")


@dataclass
class CrisisReading:
    """One crisis judgement."""

    is_crisis: bool = False
    level: str = "none"
    probability: float = 0.0
    confident: bool = False
    degraded: bool = False
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "is_crisis": self.is_crisis,
            "level": self.level,
            "probability": round(self.probability, 6),
            "confident": self.confident,
            "degraded": self.degraded,
            "reason": self.reason,
        }


def detect_crisis(text: str, decider: Decider, *, threshold: float = 0.7) -> CrisisReading:
    """Check whether a piece of text carries signals that need intervention.

    Deliberately conservative: a missed signal is worse than a false alarm
    only when the false alarm is cheap, and here a false alarm interrupts a
    normal conversation while a miss can be irreversible. So the threshold
    defaults to 0.7 rather than 0.5.
    """
    gate = DecisionGate(
        "这段话里是否出现了需要立即人工介入的危机信号"
        "（自伤、伤人、医疗急症、明确无法继续的极端状态）？",
        threshold=threshold,
        name="crisis",
    )
    out = gate.evaluate(text or "", decider=decider)
    level = "watch" if (out.value and not out.confident) else ("critical" if out.value else "none")
    return CrisisReading(
        is_crisis=out.value,
        level=level,
        probability=out.probability,
        confident=out.confident,
        degraded=out.degraded,
        reason=out.reason,
    )


# -- tool routing --

@dataclass
class ToolRoute:
    """The outcome of a tool routing decision."""

    name: str = ""
    probability: float = 0.0
    confidence: float = 0.0
    alternatives: list[tuple[str, float]] = field(default_factory=list)
    degraded: bool = False
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "probability": round(self.probability, 6),
            "confidence": round(self.confidence, 6),
            "alternatives": [[n, round(p, 6)] for n, p in self.alternatives],
            "degraded": self.degraded,
            "reason": self.reason,
        }


def route_tool(
    state: str,
    tools: Union[dict[str, str], Sequence[str]],
    decider: Decider,
    *,
    question: str = "这条请求该交给哪个工具处理？",
    min_confidence: float = 0.0,
) -> ToolRoute:
    """Pick one tool out of a set.

    ``tools`` is either ``{name: description}`` or a list of names. Every
    option carries a one line description of when to use it: that is what
    makes the distribution separable. Names alone leave the model guessing
    where the boundaries are.

    :param min_confidence: below this confidence nothing is picked and the
        caller takes its default path. Routing to the wrong tool usually costs
        more than not routing at all.
    """
    if isinstance(tools, dict):
        names = [str(k) for k in tools.keys()]
        descs = [str(v) for v in tools.values()]
    else:
        names = [str(t) for t in tools]
        descs = [""] * len(names)
    if not names:
        return ToolRoute(degraded=True, reason="no candidate tools")

    # The option labels have to be single tokens (A, B, C), otherwise the
    # logprobs hold subword fragments and the probability cannot be put back
    # together. Tool names are semantic ("refund" is several tokens), so the
    # labels are letters and the description carries "name - description".
    options = {
        letter_labels(i): (f"{n} - {d}".strip(" -") if d else n)
        for i, (n, d) in enumerate(zip(names, descs))
    }

    try:
        res = decider(DecisionRequest(
            type="choice", question=question, state=state or "", options=options))
    except Exception as e:
        logger.warning("tool routing failed, degraded: %s", e)
        return ToolRoute(degraded=True, reason=str(e)[:200])

    ranked = sorted(res.distribution.items(), key=lambda kv: -kv[1])
    picked = str(res.answer)
    idx = _letter_index(picked)
    best = names[idx] if idx is not None and idx < len(names) else str(res.label or picked)
    if float(res.confidence) < min_confidence:
        return ToolRoute(
            name="",
            probability=float(res.probability),
            confidence=float(res.confidence),
            alternatives=ranked,
            reason="the confidence is below the threshold, no routing",
        )
    return ToolRoute(
        name=best,
        probability=float(res.probability),
        confidence=float(res.confidence),
        alternatives=ranked,
    )


# -- retrieval gate --

def needs_retrieval(
    question: str,
    context: str,
    decider: Decider,
    *,
    threshold: float = 0.5,
) -> GateOutcome:
    """Check whether a question needs external material.

    ``context`` is what is already known. The model then answers whether that
    is enough, which is easier than "do you need a search".
    """
    state = f"已知信息:\n{context or '（无）'}\n\n问题:\n{question or ''}"
    gate = DecisionGate(
        "仅凭上面的已知信息，能准确回答这个问题吗？"
        "如果需要查资料、外部数据或不确定的事实，请回答 N。",
        threshold=threshold,
        name="needs_retrieval",
    )
    # The question asks whether the known information is enough, while the
    # caller wants to know whether a search is needed, so the answer flips.
    out = gate.evaluate(state, decider=decider)
    return GateOutcome(
        value=not out.value,
        probability=1.0 - out.probability if not out.degraded else 0.0,
        confident=out.confident,
        degraded=out.degraded,
        reason=out.reason,
    )


# -- generic classification --

def classify(
    text: str,
    labels: Sequence[str],
    decider: Decider,
    *,
    question: str = "这段内容属于下面哪一类？",
    extra_context: str = "",
) -> Classification:
    """Sort a piece of content into one of the given labels (question type,
    difficulty and so on)."""
    if not labels:
        return Classification(degraded=True, reason="no candidate labels")
    state = (extra_context + "\n" if extra_context else "") + (text or "")
    try:
        res = decider(DecisionRequest(
            type="choice", question=question, state=state, options=list(labels)))
    except Exception as e:
        logger.warning("classification failed, degraded: %s", e)
        return Classification(degraded=True, reason=str(e)[:200])
    label = str(res.label or res.answer or "")
    return Classification(
        label=label,
        description=str(res.label or ""),
        probability=float(res.probability),
        confidence=float(res.confidence),
        distribution=dict(res.distribution),
    )
