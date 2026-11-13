# apps/dsn_study/models/decision_service.py
"""The System-1 decision service for dsn_study: emotion, crisis, tone and
question classification.
#
# ## What it solves
#
# The hard part of a voice conversation is not what to say but how to say it:
# do not lecture someone who is low, do not speak slowly to someone who is
# angry, and switch to care the moment self harm comes up. Making the main
# model generate that kind of tone costs seconds per turn, while a decision
# model answers in a single forward pass (measured at 0.55 to 0.7s on this
# machine) and returns a confidence that can be thresholded.
#
# ## The trade-off: rules first, the model as backup
#
# Not every turn deserves a question to the model. So:
#   * the **crisis check** runs a keyword pre-filter first and only asks the
#     model when something looks suspicious. The cost is that a miss is never
#     checked at all, so the keyword list has to cover the explicit phrasings.
#   * the **emotion read** only runs on voice turns by default
#     (DECISION_PROBE_SCOPE=voice), because typed input already carries
#     emotion cues while voice does not.
#
# ## Degradation
#
# When the decision model is down, the start fails or a request times out, the
# result is "no signal" and the conversation carries on. Voice and emotion are
# extras, they must never take the main path down with them.
#
# The lifecycle lives in infra/resources/decision_service.py: start on demand,
# keep the lease alive, reclaim the VRAM when idle (the same IdleReaper that
# handles TTS).
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass, field
from typing import Optional

from harness.decisions.service import DecisionService
from harness.decisions.use_cases import (
    CrisisReading,
    EmotionReading,
    classify,
    detect_crisis,
    probe_emotion,
)
from infra.decision.client import DecisionUnavailable
from infra.resources.decision_service import (
    DECISION_RESOURCE,
    DecisionConfig,
    decision_lease,
    decision_provider,
    decision_status,
    register_decision_resource,
)

logger = logging.getLogger("StudyDecision")

#: The crisis keyword pre-filter. Only a hit asks the model.
#:
#: The pre-filter exists because a crisis check on every turn costs 0.7s and
#: almost no conversation carries a crisis signal. The rules keep 99% of the
#: traffic away from the model and the model only shows up when something
#: looks wrong. A hit does not mean there is a crisis, the model still has to
#: confirm it (misses are worse than false alarms here).
CRISIS_KEYWORDS = (
    "不想活", "活不下去", "自杀", "自残", "结束生命", "了结自己",
    "伤害自己", "想死", "轻生", "没意思活着", "消失算了",
    "割腕", "跳楼", "吞药", "一了百了", "不想醒",
    "hurt myself", "kill myself", "suicide", "end my life",
)

#: The crisis keyword pattern (Chinese by substring, English by word).
_CRISIS_RE = re.compile(
    "|".join(re.escape(k) for k in CRISIS_KEYWORDS), re.IGNORECASE)


@dataclass
class StateProbe:
    """The result of reading the user state."""

    emotion: EmotionReading = field(default_factory=EmotionReading)
    crisis: CrisisReading = field(default_factory=CrisisReading)
    degraded: bool = False
    reason: str = ""

    @property
    def tone_hint(self) -> str:
        """A one line hint for the main model (the tone to use).

        An empty string means there is no usable signal.
        """
        if self.crisis.is_crisis:
            return "用户可能正处在需要立即关怀的状态：先共情与确认安全，不要讲道理、不要给学习建议。"
        if self.emotion.degraded:
            return ""
        label = self.emotion.label
        if label in ("低落", "疲惫"):
            return "用户情绪偏低：语气温和简短，先接住情绪再谈正事，不要催促。"
        if label == "生气":
            return "用户有些生气：先认可他的感受，别辩解，别急着给方案。"
        if label == "焦虑":
            return "用户可能焦虑：把事情拆小、给确定的下一步，别含糊。"
        if label == "开心":
            return "用户心情不错：可以轻松些，适度幽默。"
        return ""

    def to_dict(self) -> dict:
        return {
            "emotion": self.emotion.to_dict(),
            "crisis": self.crisis.to_dict(),
            "degraded": self.degraded,
            "reason": self.reason,
            "tone_hint": self.tone_hint,
        }


def free_vram_mb() -> int:
    """The free VRAM across all GPUs in MB, or -1 when it cannot be read.

    The decision model fills both cards (measured 9.9G plus 9.9G) and the pool
    holds other heavy services (the VLM/Bonsai at about 12G, TTS at 2.8G).
    Squeezing them in does not make things slower, it makes them crash with
    an out of memory error, so the free space is checked before the model
    starts.
    """
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total,memory.used",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5)
    except Exception:
        return -1
    free = 0
    for line in (out.stdout or "").strip().splitlines():
        try:
            total, used = (int(x) for x in line.split(","))
        except ValueError:
            continue
        free += max(0, total - used)
    return free


def vram_guard(pool=None, cfg=None) -> None:
    """Raise when there is not enough VRAM to start the decision model.

    The check only applies when the process has to be started. When the model
    is already running, that part of the VRAM is its own, and counting it as
    free space made the guard block decisions that would have worked (measured:
    right after the lease was returned the model was still up, only 2.5G was
    free, and the decision was refused by its own guard).

    The threshold defaults to 17G: the weights are 16.5G and the CUDA context
    and the KV cache need about 15.7G in total, measured.
    """
    from apps.dsn_study.config import Config
    from apps.dsn_study.models.resource_setup import get_study_pool

    p = pool or get_study_pool()
    if p is not None:
        try:
            if p.snapshot().get(DECISION_RESOURCE, {}).get("loaded"):
                return
        except Exception:
            pass

    required = int(getattr(Config, "DECISION_VRAM_REQUIRED_MB", 17000))
    free = free_vram_mb()
    if free < 0 or free >= required:
        return
    raise DecisionUnavailable(
        f"not enough VRAM to start the decision model (needs about {required}MB, {free}MB free)")


def _config() -> DecisionConfig:
    """Build the decision resource configuration from the app settings."""
    from apps.dsn_study.config import Config

    return DecisionConfig(
        enabled=bool(getattr(Config, "DECISION_ENABLED", True)),
        autostart=bool(getattr(Config, "DECISION_AUTOSTART", True)),
        host=getattr(Config, "DECISION_HOST", "127.0.0.1"),
        port=int(getattr(Config, "DECISION_PORT", 8092)),
        ctx_size=int(getattr(Config, "DECISION_CTX_SIZE", 4096)),
        n_gpu_layers=int(getattr(Config, "DECISION_NGL", 99)),
        tensor_split=str(getattr(Config, "DECISION_TENSOR_SPLIT", "8,12")),
        no_kv_offload=bool(getattr(Config, "DECISION_NO_KV_OFFLOAD", True)),
        load_timeout=int(getattr(Config, "DECISION_LOAD_TIMEOUT", 900)),
        request_timeout=int(getattr(Config, "DECISION_REQUEST_TIMEOUT", 120)),
        idle_timeout=int(getattr(Config, "DECISION_IDLE_TIMEOUT", 900)),
        vram_estimate_mb=int(getattr(Config, "DECISION_VRAM_ESTIMATE_MB", 20000)),
        log_file=str(getattr(Config, "DECISION_LOG_FILE", "") or ""),
        display_name="JEV decision model (System-1)",
    )


def register_study_decision(pool) -> None:
    """Register the decision model in the dsn_study resource pool."""
    cfg = _config()
    if not cfg.enabled:
        logger.info("the decision model is disabled (DECISION_ENABLED=false), not registered")
        return
    register_decision_resource(pool, cfg)


def get_decision_service(pool=None) -> Optional[DecisionService]:
    """The decision service facade, or None when the resource is not registered.

    Every decision takes a lease, so the service is guaranteed to be alive
    during the call and the idle reaper decides when it stops.
    """
    from apps.dsn_study.models.resource_setup import get_study_pool

    p = pool or get_study_pool()
    if p is None or p.get_spec(DECISION_RESOURCE) is None:
        return None
    cfg = _config()
    inner = decision_provider(p, cfg)

    def _provider():
        # Check the VRAM before the start: breaking another service is worse
        # than losing one emotion reading.
        vram_guard(p, cfg)
        return inner()

    return DecisionService(_provider)


def probe_state(text: str, *, is_voice: bool = False,
                pool=None) -> StateProbe:
    """Read the user state (emotion and crisis).

    :param is_voice: a voice turn. The emotion read defaults to voice turns
        only, which saves one forward pass.
    """
    from apps.dsn_study.config import Config

    service = get_decision_service(pool)
    if service is None:
        return StateProbe(degraded=True, reason="the decision service is not ready")

    scope = str(getattr(Config, "DECISION_PROBE_SCOPE", "voice")).lower()
    if scope == "off":
        return StateProbe(degraded=True, reason="the decision probe is disabled")

    def _decider(req):
        return service.decide(req)

    emotion = EmotionReading(degraded=True, reason="not probed")
    if (scope == "all" or is_voice) and bool(
            getattr(Config, "DECISION_EMOTION_ENABLED", True)):
        emotion = probe_emotion(text or "", _decider)

    crisis = CrisisReading()
    if bool(getattr(Config, "DECISION_CRISIS_ENABLED", True)):
        if _CRISIS_RE.search(text or ""):
            # A keyword hit means the model confirms it (a miss is worse than a
            # false alarm here).
            crisis = detect_crisis(text or "", _decider)
        else:
            crisis = CrisisReading(reason="no crisis keyword, the model was not asked")

    degraded = emotion.degraded and crisis.degraded
    return StateProbe(emotion=emotion, crisis=crisis, degraded=degraded)


def warmup_decision(pool=None) -> bool:
    """Warm the decision model up in the background.

    The first decision then does not wait for the cold start. A failure is
    not raised: a decision model that is down only means there is no emotion
    reading.
    """
    from apps.dsn_study.models.resource_setup import get_study_pool

    p = pool or get_study_pool()
    if p is None or p.get_spec(DECISION_RESOURCE) is None:
        return False
    try:
        vram_guard(p)
        ok = p.ensure_running(DECISION_RESOURCE)
        logger.info("the decision model warmup: %s", "ready" if ok else "not ready")
        return bool(ok)
    except Exception as e:
        logger.warning("the decision model warmup failed, it starts on demand: %s", e)
        return False


def classify_question(text: str, labels, *, pool=None) -> Optional[str]:
    """Sort a question into one of the given labels (question type and so on).

    Returns None when no decision is possible.
    """
    service = get_decision_service(pool)
    if service is None:
        return None
    out = classify(text or "", labels, lambda req: service.decide(req))
    return out.label or None


def needs_retrieval(question: str, context: str = "", *, pool=None):
    """Check whether a question needs external material.

    Returns None when no decision is possible.
    """
    from harness.decisions.use_cases import needs_retrieval as _needs

    service = get_decision_service(pool)
    if service is None:
        return None
    return _needs(question or "", context or "", lambda req: service.decide(req))


def decision_service_status(pool=None) -> dict:
    """Status of the decision subsystem (for the REST API and the admin page)."""
    from apps.dsn_study.config import Config
    from apps.dsn_study.models.resource_setup import get_study_pool

    p = pool or get_study_pool()
    info: dict = {"enabled": bool(getattr(Config, "DECISION_ENABLED", True))}
    if p is None:
        info["registered"] = False
        return info
    try:
        info.update(decision_status(p))
    except Exception as e:
        info["error"] = str(e)
    return info
