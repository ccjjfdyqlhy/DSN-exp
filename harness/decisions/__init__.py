# harness/decisions/__init__.py
"""System-1 decision capability, the agent core layer.
#
# ## What this is
#
# System 1 gives the model a closed option set and it writes the answer
# distribution onto the probability of the next token in a single forward pass,
# with no reasoning text. So a judgement turns from "generate a paragraph and
# parse it" into "read a probability": one order of magnitude faster, and the
# result carries a confidence that can be thresholded.
#
# ## The three parts
#
#   * ``core``      - semantics: request and result types, prompts, reading the
#     distribution, confidence.
#   * ``service``   - facade: joins the transport (infra/decision) with the
#     semantics.
#   * ``use_cases`` - use cases: emotion, crisis, tool routing, retrieval gate,
#     generic classification.
#
# ## Layering
#
# This layer only cares about how the model thinks. The transport (HTTP and
# logprobs) and the process lifecycle (start and reclaim) belong to
# infra/decision and infra/resources. Nothing here knows about voice, study or
# interfaces, that is the job of the apps.
"""

from .core import (
    DECISION_TYPES,
    DecisionError,
    DecisionRequest,
    DecisionResult,
    build_messages,
    build_prompt,
    choice_confidence,
    interpret,
    label_variants,
    letter_labels,
    normalize,
    token_probability,
)
from .service import DecisionService
from .use_cases import (
    Classification,
    CrisisReading,
    DecisionGate,
    Decider,
    EmotionReading,
    GateOutcome,
    ToolRoute,
    classify,
    detect_crisis,
    needs_retrieval,
    probe_emotion,
    route_tool,
)

__all__ = [
    "DECISION_TYPES",
    "DecisionError",
    "DecisionRequest",
    "DecisionResult",
    "build_messages",
    "build_prompt",
    "choice_confidence",
    "interpret",
    "label_variants",
    "letter_labels",
    "normalize",
    "token_probability",
    "DecisionService",
    "Classification",
    "CrisisReading",
    "DecisionGate",
    "Decider",
    "EmotionReading",
    "GateOutcome",
    "ToolRoute",
    "classify",
    "detect_crisis",
    "needs_retrieval",
    "probe_emotion",
    "route_tool",
]
