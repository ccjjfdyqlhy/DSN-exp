# apps/dsn_ui/jev_integration.py
"""Register the JEV-27B-VL dual-system hybrid model with the orchestrator.
#
# ## What this module does now
#
# Only one thing: take the models found under the JEV root and register them as
# schedulable models of the orchestrator.
#
# "Where the model lives, how it starts and on which port" moved to
# infra/decision/jev.py. That is a resource question (process, port, VRAM,
# disk) and belongs to infra by the layering rule. It used to live here, which
# meant only dsn_ui could use the model and dsn_study had to copy the file for
# its own decisions. Two copies drift: a port conflict, or half of a VRAM
# change updated.
#
# ## What the model is
#
# JEV-27B-VL is a dual-system hybrid model and differs from an ordinary GGUF
# in two ways:
#
#  1. **System 1 (the decision head)** - a typed-decision head fused into the
#     weights at training time. Give it a closed option set and it writes the
#     answer distribution onto the probability of the next token in a single
#     forward pass, with no reasoning text. The decision endpoint reads those
#     logprobs (see apps/dsn_ui/system1_api.py).
#
#  2. **The qwen35 hybrid architecture** (Gated Delta Net linear attention) -
#     the fused GDN kernel in llama.cpp only exists for CUDA, so n_gpu_layers
#     is fixed at 99 and the projector has to stay on the CPU. The reasons and
#     the measurements are in infra/decision/jev.py.
#
# ## VRAM
#
# The Q4_K_M weights are 16.5G and take about 10.5G and 9.7G on the two cards
# once loaded, so the model **owns both cards** and cannot share the machine
# with Bonsai-2-27B. It therefore uses a port of its own, 8090 by default
# (avoiding Bonsai on 8080 and Strata on 8081).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from infra.decision.jev import (
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

logger = logging.getLogger("DSNUIJev")

__all__ = [
    "JevModel",
    "DEFAULT_PORT",
    "DEFAULT_CTX_SIZE",
    "DEFAULT_MODEL_ROOT",
    "DEFAULT_TENSOR_SPLIT",
    "FIXED_N_GPU_LAYERS",
    "resolve_model_root",
    "resolve_binary",
    "scan_jev_models",
    "build_jev_config",
    "register_jev_models",
    "jev_status",
]


def register_jev_models(
    orchestrator,
    *,
    model_root: Optional[Path | str] = None,
    binary: Optional[Path | str] = None,
    port: Optional[int] = None,
    ctx_size: Optional[int] = None,
    priority: int = 65,
    claimed_ports: Optional[set[int]] = None,
) -> list[str]:
    """Scan the JEV root and register the models with the orchestrator.

    Returns:
        the names that were registered. An empty list is normal when the
        directory is missing or holds no model, and does not stop dsn_ui from
        starting.
    """
    root = resolve_model_root(model_root)
    binary_path = resolve_binary(binary)
    if not binary_path:
        return []

    models = scan_jev_models(root)
    if not models:
        logger.info("no JEV model found, skipping the integration")
        return []

    claimed = set(claimed_ports or ())
    eff_ctx = ctx_size if ctx_size is not None else int(
        os.getenv("DSN_JEV_CTX", str(DEFAULT_CTX_SIZE)))
    preferred_port = port if port is not None else int(
        os.getenv("DSN_JEV_PORT", str(DEFAULT_PORT)))

    registered: list[str] = []
    for m in models:
        p, reason = pick_port(preferred_port, claimed, "127.0.0.1")
        claimed.add(p)
        if reason != "the configured port":
            logger.info("the port of the JEV model %s moved: %s", m.name, reason)

        cfg = build_jev_config(m, binary_path, port=p, ctx_size=eff_ctx)
        try:
            orchestrator.register_local_llamacpp(
                name=m.name,
                config=cfg,
                priority=priority,
                resident=False,
                immediate=False,
                load_timeout=300,
                request_timeout=600,
            )
            registered.append(m.name)
            logger.info(
                "registered the JEV model: %s (%s%s) port=%d ngl=%d",
                m.name, Path(m.model_path).name,
                f" + vision({Path(m.mmproj_path).name})" if m.is_multimodal else "",
                p, FIXED_N_GPU_LAYERS,
            )
        except Exception as e:
            logger.warning("cannot register the JEV model %s: %s", m.name, e)

    return registered


def jev_status(model_root: Optional[Path | str] = None) -> dict:
    """Status of the JEV integration, for the API."""
    root = resolve_model_root(model_root)
    exists = root.is_dir()
    binary = resolve_binary() if exists else None
    models = scan_jev_models(root) if exists else []
    return {
        "model_root": str(root),
        "available": bool(binary and models),
        "binary": binary,
        "fixed_n_gpu_layers": FIXED_N_GPU_LAYERS,
        "default_port": DEFAULT_PORT,
        "models": [
            {
                "name": m.name,
                "directory": m.directory,
                "model_path": m.model_path,
                "mmproj_path": m.mmproj_path,
                "multimodal": m.is_multimodal,
            }
            for m in models
        ],
    }
