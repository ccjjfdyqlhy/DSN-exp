# infra/resources/decision_service.py
"""The System-1 decision model (JEV) as a peripheral resource: start it on
demand, keep it alive while it is leased, reclaim it when it goes idle.
#
# ## Why it shares the pool with TTS
#
# The decision model plays the role of "read a probability quickly": emotion,
# crisis, tool routing, a retrieval gate. Its usage pattern is exactly the
# pattern of a voice service:
#
#   * **heavy**: the Q4_K_M weights of JEV-27B-VL are 16.5G and take both
#     cards once loaded;
#   * **occasional**: a conversation asks once in a while, not every turn;
#   * **reclaimable**: handing 16.5G of VRAM back when nothing needs it is
#     worth far more than keeping it around.
#
# So it goes into the ResourcePool and rides the same scheduling and reclaim
# machinery as TTS, ASR and the VLM: the pool starts it on the first
# decision (a tens of seconds cold start), the lease keeps it alive, and the
# IdleReaper stops the process after the idle timeout and returns the VRAM.
# The next request starts it again.
#
# There is no second implementation of that chain here, the reaper, the lease
# and the status view are all the existing ones.
#
# ## How it differs from the orchestrator managed path
#
# The same JEV can also be owned by the model orchestrator (dsn_ui does that:
# JEV is also its System-2 chat model). The difference is only about who
# decides when it should stay alive:
#
#   * the orchestrator evicts by slot and priority (a model the user is
#     chatting with must not be stopped);
#   * the pool reclaims by idle timeout (a decision model is used now and then
#     and should not hold both cards forever).
#
# Both ways to get a client live in infra/decision/backends.py.
"""

from __future__ import annotations

import logging
import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional

from infra.decision.backends import pool_decision_client
from infra.decision.client import DecisionClient, DecisionUnavailable
from infra.decision.jev import (
    DEFAULT_CTX_SIZE,
    DEFAULT_PORT,
    DEFAULT_TENSOR_SPLIT,
    FIXED_N_GPU_LAYERS,
    JevModel,
    build_jev_config,
    resolve_binary,
    scan_jev_models,
)
from infra.orchestrator import LlamaServerConfig, LlamaServerLauncher

from .pool import ResourceKind, ResourcePool, ResourceSpec

logger = logging.getLogger("DecisionService")

#: The resource name inside the pool.
DECISION_RESOURCE = "decision"

_lock = threading.RLock()
_state: dict[str, Any] = {"launcher": None, "model": None}


@dataclass
class DecisionConfig:
    """Configuration of the decision resource.

    This layer knows nothing about any application: each app (dsn_study,
    dsn_ui) reads these values from its own settings and passes them in. That
    keeps infra from having to know what a study system or a console is.
    """

    enabled: bool = True
    #: True means managed (the pool starts and stops the process), False means
    #: adopt (the pool only connects to a service that is already running).
    autostart: bool = True
    host: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    ctx_size: int = DEFAULT_CTX_SIZE
    n_gpu_layers: int = FIXED_N_GPU_LAYERS
    tensor_split: str = DEFAULT_TENSOR_SPLIT
    #: Idle seconds before the resource is stopped (0 means it stays up).
    idle_timeout: int = 900
    load_timeout: int = 600
    request_timeout: int = 120
    #: Explicit main model (empty means the JEV directory is scanned).
    model_path: str = ""
    #: Explicit vision projector (empty means it is paired with the main
    #: model in the same directory).
    mmproj_path: str = ""
    #: Keep the KV cache in system memory instead of VRAM.
    no_kv_offload: bool = False
    #: Log file for the server process (empty means no file).
    log_file: str = ""
    vram_estimate_mb: int = 20400
    display_name: str = "JEV decision model (System-1)"
    extra: dict = field(default_factory=dict)

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


# -- model discovery --

def resolve_decision_model(cfg: DecisionConfig) -> JevModel:
    """Locate the decision model to run.

    Priority:
      1. an explicit model_path in the config, which pairs with the mmproj in
         the same directory;
      2. otherwise the JEV root is scanned and the entry that looks like the
         main model is picked.
    """
    explicit = (cfg.model_path or "").strip()
    if explicit:
        model_path = os.path.abspath(os.path.expanduser(explicit))
        if not os.path.isfile(model_path):
            raise DecisionUnavailable(f"the decision model file does not exist: {model_path}")
        mmproj = (cfg.mmproj_path or "").strip()
        if not mmproj:
            for cand in sorted(os.listdir(os.path.dirname(model_path))):
                if "mmproj" in cand.lower() and cand.lower().endswith(".gguf"):
                    mmproj = os.path.join(os.path.dirname(model_path), cand)
                    break
        else:
            mmproj = os.path.abspath(os.path.expanduser(mmproj))
            if not os.path.isfile(mmproj):
                raise DecisionUnavailable(f"the vision projector does not exist: {mmproj}")
        return JevModel(
            name=os.path.basename(model_path),
            model_path=model_path,
            mmproj_path=mmproj or None,
            directory=os.path.basename(os.path.dirname(model_path)),
        )

    models = scan_jev_models()
    if not models:
        raise DecisionUnavailable(
            "no JEV decision model found on this machine, "
            "set DECISION_MODEL_PATH to a GGUF file")
    # Prefer a main model whose file name mentions JEV, the others are usually
    # drafts or qlora derivatives.
    for m in models:
        if "jev" in os.path.basename(m.model_path).lower():
            return m
    return models[0]


def resolve_decision_binary() -> Optional[str]:
    """Locate the llama-server binary (JEV needs the system llama.cpp build)."""
    return resolve_binary()


# -- launch configuration --

def build_decision_config(cfg: DecisionConfig, model: JevModel, binary: str) -> LlamaServerConfig:
    """Build the llama-server launch configuration for the decision model.

    It reuses the JEV specific parameters from infra/decision/jev.py (ngl fixed
    at 99, projector on the CPU, both cards taken), and the reasons are
    written down there.
    """
    return build_jev_config(
        model,
        binary,
        port=cfg.port,
        ctx_size=cfg.ctx_size,
        n_gpu_layers=cfg.n_gpu_layers,
        tensor_split=cfg.tensor_split,
        no_kv_offload=cfg.no_kv_offload,
    )


def build_decision_launcher(cfg: DecisionConfig) -> LlamaServerLauncher:
    """Build the lifecycle manager for the llama-server process."""
    model = resolve_decision_model(cfg)
    binary = resolve_decision_binary()
    if not binary:
        raise DecisionUnavailable(
            "no llama-server binary found (JEV needs the system llama.cpp build)")
    log_file = (cfg.log_file or "").strip()
    if log_file:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)
        except OSError:
            log_file = ""
    launcher = LlamaServerLauncher(
        build_decision_config(cfg, model, binary), log_file=log_file or None)
    with _lock:
        _state["launcher"] = launcher
        _state["model"] = model
    return launcher


# -- pool registration --

def register_decision_resource(pool: ResourcePool, cfg: Optional[DecisionConfig] = None) -> None:
    """Register the decision model in the resource pool.

    With autostart False the resource runs in adopt mode: it only connects to
    a service that is already running and never kills a process.
    """
    cfg = cfg or DecisionConfig()
    if not cfg.enabled:
        logger.info("the decision model is disabled (enabled=false), not registered")
        return
    if pool.get_spec(DECISION_RESOURCE) is not None:
        return

    launcher = build_decision_launcher(cfg)
    model = _state.get("model")

    load_fn, unload_fn = launcher.create_scheduler_hooks(load_timeout=cfg.load_timeout)

    pool.register_resource(
        DECISION_RESOURCE,
        ResourceSpec(
            kind=ResourceKind.DECISION,
            display_name=cfg.display_name,
            base_url=cfg.base_url,
            endpoint="",
            # A high priority because a decision is a synchronous call on the
            # interactive path, it cannot wait in a queue.
            priority=85,
            # resident: a 27B model owns both cards and must never be evicted
            # by slot pressure, otherwise a running decision would land on
            # another model. The idle reaper handles the release instead.
            resident=True,
            # immediate False: releasing the lease must not unload the model
            # right away (one conversation asks several times).
            immediate=False,
            load_timeout=cfg.load_timeout,
            request_timeout=cfg.request_timeout,
            vram_estimate_mb=cfg.vram_estimate_mb,
            idle_timeout=cfg.idle_timeout,
            extra={
                "engine": "llama.cpp",
                "managed": bool(cfg.autostart),
                "adopt": not bool(cfg.autostart),
                "launch_mode": "command" if cfg.autostart else "adopt",
                "model": getattr(model, "model_path", ""),
                "mmproj": getattr(model, "mmproj_path", "") or "",
                "model_name": getattr(model, "name", ""),
                "port": cfg.port,
                "request_timeout": cfg.request_timeout,
                **cfg.extra,
            },
        ),
        load_fn,
        unload_fn,
    )
    logger.info("the decision resource is registered: %s (mode=%s)", cfg.base_url,
                "managed" if cfg.autostart else "adopt")


# -- usage --

@contextmanager
def decision_lease(
    pool: ResourcePool,
    cfg: Optional[DecisionConfig] = None,
    *,
    timeout: Optional[float] = None,
) -> Iterator[DecisionClient]:
    """Lease the decision model, which starts it on demand.

    The pool starts the service when it is not running yet (the llama-server
    cold start takes tens of seconds). Leaving the context returns the lease
    and the service keeps running until the idle reaper stops it.
    """
    cfg = cfg or DecisionConfig()
    wait = timeout if timeout is not None else float(cfg.request_timeout)
    spec = pool.get_spec(DECISION_RESOURCE)
    extra = spec.extra if spec and isinstance(spec.extra, dict) else {}
    try:
        with pool_decision_client(
            pool,
            DECISION_RESOURCE,
            timeout=wait,
            model=str(extra.get("model_name", "")),
        ) as client:
            yield client
    except TimeoutError as e:
        raise DecisionUnavailable(f"timed out waiting for the decision model ({wait:.0f}s): {e}") from e


def decision_provider(pool: ResourcePool, cfg: Optional[DecisionConfig] = None):
    """Return a provider that takes a lease per call.

    This is what harness/decisions.DecisionService consumes: the lease has to
    cover the whole decision (a forward pass of tens to hundreds of
    milliseconds), not only the moment the client is fetched.
    """
    cfg = cfg or DecisionConfig()

    def _provider():
        return decision_lease(pool, cfg)

    return _provider


# -- status --

def decision_status(pool: ResourcePool) -> dict:
    """Status view of the decision resource (for the admin page and the API)."""
    info: dict[str, Any] = {"registered": False, "loaded": False}
    rows = {r.get("name"): r for r in pool.list_resources()}
    row = rows.get(DECISION_RESOURCE)
    if row is not None:
        info["registered"] = True
        info["loaded"] = bool(row.get("loaded"))
        info["managed"] = bool(row.get("managed"))
        info["idle_timeout"] = int(row.get("idle_timeout") or 0)
        info["idle_seconds"] = round(float(row.get("idle_seconds") or 0.0), 1)
        spec = pool.get_spec(DECISION_RESOURCE)
        if spec is not None:
            extra = spec.extra if isinstance(spec.extra, dict) else {}
            info["base_url"] = spec.base_url
            info["model"] = extra.get("model", "")
            info["mmproj"] = extra.get("mmproj", "")
            info["port"] = extra.get("port")
    launcher = _state.get("launcher")
    if launcher is not None:
        info["running"] = launcher.is_running()
        info["command"] = launcher.command_string()
    return info
