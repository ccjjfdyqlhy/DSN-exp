# dual/__init__.py
# 双模协同包 — Instant (快速回复) + Main (深度处理)

from .request_pool import RequestPool, RequestEntry
from .stream_session import StreamSession, StreamRegistry
from .instant_context import InstantContext
from .instant_registry import InstantContextRegistry
from .tts_synth import TTSSynthesizer
from .instant_service import InstantModelService, InstantResult
from .main_dispatcher import MainModelDispatcher
from .coordinator import DualCoordinator

__all__ = [
    "RequestPool",
    "RequestEntry",
    "StreamSession",
    "StreamRegistry",
    "InstantContext",
    "InstantContextRegistry",
    "TTSSynthesizer",
    "InstantModelService",
    "InstantResult",
    "MainModelDispatcher",
    "DualCoordinator",
]
