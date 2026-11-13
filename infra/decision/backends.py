# infra/decision/backends.py
"""Two ways to get a decision client - pool managed and orchestrator managed.
#
# ## Why there are two
#
# The same decision model belongs to different owners depending on the app:
#
#   * **Pool managed** (infra/resources/decision_service.py) - the peripheral
#     resource pool owns its lifecycle: start it on demand, keep it alive
#     while it is leased, reclaim it when it goes idle. dsn_study uses this
#     path: a decision model is a service you use occasionally, so its VRAM
#     has to be able to come back.
#
#   * **Orchestrator managed** (infra/orchestrator) - the model orchestrator
#     owns its lifecycle: slots and priority eviction. dsn_ui uses this path:
#     JEV is also the System-2 chat model there, and the user may be chatting
#     with it, so it must not be reclaimed just because it looks idle.
#
# Both look the same to the caller: a context manager that yields a
# DecisionClient and releases the lease on exit.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator, Optional

from .client import DecisionClient, DecisionUnavailable

logger = logging.getLogger("DecisionBackends")


@contextmanager
def pool_decision_client(
    pool,
    resource_name: str = "decision",
    *,
    timeout: float | None = None,
    model: str = "",
) -> Iterator[DecisionClient]:
    """Take a decision client from the resource pool (pool managed).

    The service is started here when it is not running yet (the llama-server
    cold start takes tens of seconds). Leaving the context returns the lease
    but keeps the service alive; the idle reaper stops it later.
    """
    lease = pool.acquire(resource_name, timeout=timeout)
    try:
        spec = pool.get_spec(resource_name)
        base_url = spec.base_url if spec else lease.base_url
        if not base_url:
            raise DecisionUnavailable(
                f"the decision resource {resource_name} has no base_url")
        yield DecisionClient(
            base_url,
            model=model or (spec.extra.get("model_name", "") if spec else ""),
            timeout=float(spec.extra.get("request_timeout", 120)) if spec else 120.0,
        )
    finally:
        lease.release()


@contextmanager
def orchestrator_decision_client(
    orchestrator,
    model_name: str,
    *,
    timeout: float | None = None,
) -> Iterator[DecisionClient]:
    """Take a decision client from the model orchestrator (orchestrator managed).

    The point is that the model is guaranteed to be loaded inside the context.
    Local models in the orchestrator start on demand, so calling the HTTP
    endpoint directly would hit a server that is not up yet. The scheduler
    lease (use()) covers loading, queueing and eviction.
    """
    spec = getattr(orchestrator, "_specs", {}).get(model_name)
    if spec is None:
        raise DecisionUnavailable(f"no such model: {model_name}")

    scheduler = getattr(orchestrator, "_scheduler", None)
    if scheduler is None:
        raise DecisionUnavailable("the orchestrator has no scheduler, cannot lease the model")

    with scheduler.use(model_name, timeout=timeout):
        launcher = getattr(spec, "launcher", None)
        base_url = (getattr(launcher, "base_url", None)
                    or getattr(spec, "base_url", None))
        if not base_url:
            raise DecisionUnavailable(
                f"model {model_name} has no reachable HTTP endpoint, cannot serve System-1")
        yield DecisionClient(base_url, model=model_name)
