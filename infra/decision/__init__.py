# infra/decision/__init__.py
"""System-1 decision infrastructure - transport and decision model assets.
#
# Layering:
#   * ``client.py`` - the logprobs channel to a local llama-server.
#   * ``jev.py``    - discovery and launch configuration for the JEV-27B-VL
#     dual-system model.
#
# The decision semantics (prompt construction, distribution reading, thresholds
# and use cases) live in ``harness/decisions``. infra only deals with
# processes and HTTP.
"""

from .backends import orchestrator_decision_client, pool_decision_client
from .client import (
    DEFAULT_TIMEOUT,
    DEFAULT_TOP_LOGPROBS,
    DecisionClient,
    DecisionUnavailable,
    RawDecision,
)
from .jev import (
    DEFAULT_CTX_SIZE,
    DEFAULT_MODEL_ROOT,
    DEFAULT_PORT,
    DEFAULT_TENSOR_SPLIT,
    FIXED_N_GPU_LAYERS,
    JevModel,
    build_jev_config,
    pick_port,
    resolve_binary,
    resolve_model_root,
    scan_jev_models,
)

__all__ = [
    "DecisionClient",
    "DecisionUnavailable",
    "RawDecision",
    "DEFAULT_TIMEOUT",
    "DEFAULT_TOP_LOGPROBS",
    "pool_decision_client",
    "orchestrator_decision_client",
    "JevModel",
    "build_jev_config",
    "scan_jev_models",
    "resolve_model_root",
    "resolve_binary",
    "pick_port",
    "DEFAULT_MODEL_ROOT",
    "DEFAULT_PORT",
    "DEFAULT_CTX_SIZE",
    "DEFAULT_TENSOR_SPLIT",
    "FIXED_N_GPU_LAYERS",
]
