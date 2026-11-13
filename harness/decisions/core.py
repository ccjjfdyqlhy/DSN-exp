# harness/decisions/core.py
"""Decision semantics - turning "the vocabulary distribution of one forward
pass" into "a typed answer".
#
# ## Why there is a separate layer
#
# A System-1 answer is not text, it is a distribution: the model puts
# probability mass on a few option tokens at the first position. Reading it
# therefore has two halves:
#
#   1. **Fetch the distribution** (transport) - send the request, read the
#      logprobs. That is infra/decision/client.py.
#   2. **Read the distribution** (semantics) - which tokens count as "yes",
#      which as "A", how to normalize, how to compute confidence and the
#      expected value. That is this module.
#
# Writing both in one place produces code like this: the same "merge Y and N"
# logic once in the dsn_ui decision endpoint and once in the dsn_study emotion
# check, and the two probabilities quietly disagree. This module keeps the
# semantics in one place and every app calls it.
#
# ## The three decision types
#
#   * ``yes_no`` - a binary judgement, the answer is a bool and the
#     probability is P(yes).
#   * ``choice`` - pick one of a closed option set, the answer is the label.
#   * ``score``  - rate from 0 to N, the answer is the expected value
#     sum(i * p_i).
#
# ## The detail that matters: token variants have to be merged
#
# The llama.cpp tokenizer treats ``Y``, `` Y``, ``Yes`` and ``yes`` as
# different tokens. Taking only the exactly equal one loses part of the
# probability mass and skews the normalized distribution (measured on the same
# sentence: skipping the merge drops P(Y) from 0.968 to about 0.94). So every
# option merges the probability over its spelling variants.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Union

#: The supported decision types.
DECISION_TYPES = ("yes_no", "choice", "score")

#: Spelling variants of the yes and no options. The Chinese forms are there
#: because a Chinese-tuned model sometimes answers with them.
YES_VARIANTS = ("Y", "Yes", "YES", "是")
NO_VARIANTS = ("N", "No", "NO", "否")


class DecisionError(ValueError):
    """The decision request itself is invalid (bad type, missing options)."""


@dataclass
class DecisionRequest:
    """One decision request.

    :param type: ``yes_no``, ``choice`` or ``score``.
    :param state: the state the decision is based on (an email, a ticket, a
        conversation).
    :param question: the question to ask the model.
    :param options: the option set for a choice. Either ``{"A": "text"}`` or
        ``["option one", "option two"]``, which is numbered A, B, C.
    :param max_score: the top of the score range (1 to 10, default 5).
    :param image_url: optional image as a data URL for an image decision.
    :param instruction: an extra hard constraint appended to the prompt.
    :param messages: OpenAI style messages passed straight through, for callers
        that build the multi turn context themselves. When given, the state and
        question are not used to build a prompt.
    """

    type: str = "yes_no"
    state: str = ""
    question: str = ""
    options: Union[dict[str, str], list[str], None] = None
    max_score: int = 5
    model: str = ""
    image_url: str = ""
    instruction: str = ""
    messages: Optional[list[dict]] = None

    def normalized_type(self) -> str:
        t = str(self.type or "yes_no").strip().lower()
        if t not in DECISION_TYPES:
            raise DecisionError(
                f"unsupported decision type: {t} (pick one of {' / '.join(DECISION_TYPES)})")
        return t

    def normalized_options(self) -> dict[str, str]:
        """Normalise the option set into ``{label: description}``.

        A list is numbered A, B, C. Labels past Z use two letters (AA, AB), so
        every label stays a single token and the probability can be read
        straight from the logprobs.
        """
        if self.options is None:
            return {}
        if isinstance(self.options, dict):
            return {str(k): ("" if v is None else str(v)) for k, v in self.options.items()}
        if isinstance(self.options, (list, tuple)):
            items = [str(o) for o in self.options]
            return {letter_labels(i): desc for i, desc in enumerate(items)}
        raise DecisionError("options must be a dict or a list")

    def normalized_max_score(self) -> int:
        try:
            v = int(self.max_score)
        except (TypeError, ValueError):
            v = 5
        return max(1, min(v, 10))

    def validate(self) -> None:
        """Check that the request hangs together. Raises :class:`DecisionError`."""
        t = self.normalized_type()
        if t == "choice":
            opts = self.normalized_options()
            if not opts:
                raise DecisionError(
                    'a choice request needs options (a dict like {"A": "text"} or a list)')
            if len(opts) < 2:
                raise DecisionError("a choice request needs at least two options")
        if t == "score":
            if self.normalized_max_score() < 1:
                raise DecisionError("max_score has to be at least 1")


@dataclass
class DecisionResult:
    """The outcome of one decision.

    The type of ``answer`` follows ``type``: a bool for yes_no, the option
    label for choice, the highest number for score. ``probability`` is the
    normalized probability of that answer.
    """

    type: str
    answer: Any
    probability: float
    distribution: dict[str, float] = field(default_factory=dict)
    label: Optional[str] = None
    expectation: Optional[float] = None
    confidence: float = 0.0
    raw_candidates: dict[str, float] = field(default_factory=dict)
    model: str = ""
    latency_ms: float = 0.0

    def to_dict(self) -> dict:
        """Turn the result into a JSON serialisable dict (the dsn_ui contract)."""
        out = {
            "type": self.type,
            "answer": self.answer,
            "probability": round(float(self.probability), 6),
            "distribution": {k: round(float(v), 6) for k, v in self.distribution.items()},
            "model": self.model,
            "latency_ms": round(float(self.latency_ms), 1),
        }
        if self.label is not None:
            out["label"] = self.label
        if self.expectation is not None:
            out["expectation"] = round(float(self.expectation), 6)
        if self.raw_candidates:
            out["raw_candidates"] = dict(
                sorted(self.raw_candidates.items(), key=lambda kv: -kv[1])[:8])
        return out


# -- probability helpers --

def letter_labels(count: int) -> str:
    """The label of option number ``count`` (zero based).

    A to Z, then AA, AB and so on. Every label is a single token, otherwise
    the probability read from the logprobs is a fragment of a subword and
    cannot be merged.
    """
    if count < 0:
        raise ValueError("count cannot be negative")
    i = count + 1
    out = ""
    while i > 0:
        i, rem = divmod(i - 1, 26)
        out = chr(ord("A") + rem) + out
    return out


def label_variants(label: str) -> list[str]:
    """The usual token spellings of an option label (case, leading space)."""
    base = [label, label.lower(), label.upper(), " " + label, " " + label.lower()]
    return list(dict.fromkeys(base))


def token_probability(candidates: dict[str, float], variants) -> float:
    """Sum the probability of one option over all of its spellings.

    This has to be done: in the llama.cpp tokenizer ``Y``, `` Y`` and ``Yes``
    are different tokens, and taking only the exactly equal one loses part of
    the probability mass and skews the normalized distribution.
    """
    wanted = {str(v).strip().lower() for v in variants}
    total = 0.0
    for token, prob in candidates.items():
        if str(token).strip().lower() in wanted:
            total += float(prob)
    return total


def normalize(raw: dict[str, float]) -> dict[str, float]:
    """Normalise the option probabilities to sum to one (empty when all zero)."""
    total = sum(float(v) for v in raw.values())
    if total <= 0:
        return {}
    return {k: float(v) / total for k, v in raw.items()}


def choice_confidence(distribution: dict[str, float]) -> float:
    """Confidence of a choice: ``(p_max - 1/n) / (1 - 1/n)``.

    A uniform guess scores 0 and certainty scores 1, so "0.9 out of three" and
    "0.9 out of two" can be compared. Looking at p_max alone would overstate
    how sure a multi option question is.
    """
    n = len(distribution)
    if n <= 1:
        return 1.0 if n == 1 else 0.0
    p_max = max(distribution.values())
    return max(0.0, min(1.0, (p_max - 1.0 / n) / (1.0 - 1.0 / n)))


# -- prompt construction --

def build_prompt(req: DecisionRequest) -> str:
    """Build the prompt for the decision type.

    The prompt stays deliberately minimal: question, state, options and one
    hard constraint. System 1 wants the distribution of the very first token,
    and any extra instruction moves probability mass onto another token (a
    model that thinks first is useless here).
    """
    parts: list[str] = []
    question = (req.question or "").strip()
    state = (req.state or "").strip()

    if req.normalized_type() == "yes_no":
        if question:
            parts.append(question)
        if state:
            parts.append("State:\n" + state)
        parts.append("Answer with a single letter: Y for yes, N for no.")
    elif req.normalized_type() == "choice":
        options = req.normalized_options()
        if question:
            parts.append(question)
        if state:
            parts.append("State:\n" + state)
        lines = "\n".join(f"  {k}: {v}" for k, v in options.items())
        parts.append(
            "Options (pick exactly one; the one-line description disambiguates):\n" + lines)
        parts.append("Answer with the option label only.")
    else:
        max_score = req.normalized_max_score()
        if question:
            parts.append(question)
        if state:
            parts.append("State:\n" + state)
        parts.append(
            f"Rate from 0 to {max_score}, where 0 is the lowest and {max_score} the highest. "
            "Answer with a single digit only.")

    if req.instruction:
        parts.append(req.instruction.strip())
    return "\n\n".join(p for p in parts if p)


def build_messages(req: DecisionRequest) -> list[dict]:
    """Build the messages sent to the model.

    When the caller supplies OpenAI messages they are used as is, which is how
    a caller that built a multi turn context gets it through.
    """
    if req.messages:
        messages = [m for m in req.messages if isinstance(m, dict)]
        if req.instruction:
            messages = list(messages) + [{"role": "user", "content": req.instruction}]
        return messages
    return [{"role": "user", "content": build_prompt(req)}]


# -- reading the distribution --

def interpret(
    candidates: dict[str, float],
    req: DecisionRequest,
    *,
    model: str = "",
    latency_ms: float = 0.0,
) -> DecisionResult:
    """Read the vocabulary distribution as a typed decision.

    :raises DecisionError: the request is invalid, or no option can be
        recognised in the vocabulary.
    """
    req.validate()
    dtype = req.normalized_type()

    if dtype == "yes_no":
        p_yes = token_probability(candidates, YES_VARIANTS)
        p_no = token_probability(candidates, NO_VARIANTS)
        dist = normalize({"Y": p_yes, "N": p_no})
        if not dist:
            raise DecisionError(f"no Y or N in the vocabulary, candidates: {sorted(candidates)[:8]}")
        answer = dist.get("Y", 0.0) >= 0.5
        return DecisionResult(
            type="yes_no",
            answer=answer,
            probability=dist.get("Y", 0.0),
            distribution={k: round(v, 6) for k, v in dist.items()},
            # For a binary question the confidence is |p - 0.5| doubled: 0.5
            # scores 0 and 1.0 scores 1.
            confidence=round(abs(dist.get("Y", 0.0) - 0.5) * 2.0, 6),
            raw_candidates=dict(candidates),
            model=model,
            latency_ms=latency_ms,
        )

    if dtype == "choice":
        options = req.normalized_options()
        raw = {label: token_probability(candidates, label_variants(label))
               for label in options}
        dist = normalize(raw)
        if not dist:
            raise DecisionError(
                f"no option label in the vocabulary, candidates: {sorted(candidates)[:8]}")
        best = max(dist, key=dist.get)
        return DecisionResult(
            type="choice",
            answer=best,
            label=options.get(best),
            probability=dist[best],
            distribution={k: round(v, 6) for k, v in dist.items()},
            confidence=round(choice_confidence(dist), 6),
            raw_candidates=dict(candidates),
            model=model,
            latency_ms=latency_ms,
        )

    max_score = req.normalized_max_score()
    raw = {str(i): token_probability(candidates, [str(i), " " + str(i)])
           for i in range(max_score + 1)}
    dist = normalize(raw)
    if not dist:
        raise DecisionError(f"no digit in the vocabulary, candidates: {sorted(candidates)[:8]}")
    scores = {int(k): round(v, 6) for k, v in dist.items()}
    best = max(scores, key=scores.get)
    # The distribution keys are strings ("0" to "5"), so they have to become
    # ints before the expected value is computed. Otherwise "5" * 0.3 raises
    # TypeError: can't multiply sequence by non-int.
    expectation = sum(int(k) * v for k, v in dist.items())
    return DecisionResult(
        type="score",
        answer=best,
        probability=scores[best],
        expectation=round(expectation, 6),
        distribution={k: v for k, v in scores.items()},
        confidence=round(choice_confidence({str(k): v for k, v in scores.items()}), 6),
        raw_candidates=dict(candidates),
        model=model,
        latency_ms=latency_ms,
    )
