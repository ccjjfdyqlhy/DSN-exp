# apps/dsn_ui/system1_api.py
"""The System-1 decision endpoint of the dual-system hybrid model: one forward
pass that returns a calibrated probability.
#
# ## Background: why two conversation endpoints exist
#
# The JEV-27B-VL model DSN hosts is a dual-system hybrid:
#
#   * **System 2 (normal chat)** - ordinary autoregressive generation that
#     writes the answer token by token. It goes through
#     `/v1/chat/completions`, which dsn_ui has supported for a while.
#
#   * **System 1 (decision)** - a typed-decision head fused into the weights at
#     training time. Give it a closed option set and it writes the answer
#     distribution onto the probability of the next token in a single forward
#     pass, with no reasoning text.
#
# On llama.cpp the correct way to reach System 1 is to read **logprobs**, not
# the content:
#
#     max_tokens=1, logprobs=true, top_logprobs=N
#     -> choices[0].logprobs.content[0] holds the vocabulary distribution
#     -> the probabilities of the option tokens (Y/N, A/B, digits) are picked
#        out and normalized
#
# (The `POST /v1/decide` endpoint in the model card belongs to the vLLM
# serve_decide.py sidecar. llama.cpp has no such endpoint, but the logprobs
# give the same distribution.)
#
# ## What this module does
#
# Only routing: parse the request, pick a backend, hand it to
# harness/decisions, build the response.
#
# The parts:
#   * transport (HTTP, logprobs)      -> infra/decision/client.py
#   * semantics (prompt, read, confidence) -> harness/decisions/core.py
#   * process lifecycle (start, reclaim)   -> infra/resources/decision_service.py
#   * use case adapters (emotion, crisis)  -> harness/decisions/use_cases.py
#
# ## Backend selection
#
#   1. **A pool managed decision resource**, when one is registered. It is
#      started on demand and reclaimed when idle. dsn_study uses this path.
#   2. **An orchestrator managed model**, the default here. JEV is also the
#      System-2 chat model, so the user may be chatting with it and the
#      idle reaper must not stop it behind their back.
#
# ## The contract
#
#     POST /v1/decide              one decision entry point (type: yes_no | choice | score)
#     GET  /v1/decide/capabilities probe whether the model can decide
#
# Request body (type=yes_no):
#     {
#       "model": "jev-27b-vl",          # optional, the default model otherwise
#       "type": "yes_no",
#       "state": "the email body ...",  # or "messages": [...]
#       "question": "does this email threaten to cancel the subscription?",
#       "image_url": "data:image/png;base64,..."   # optional, for image decisions
#     }
#
# Response:
#     {
#       "type": "yes_no",
#       "answer": true,
#       "probability": 0.9170,
#       "distribution": {"Y": 0.9170, "N": 0.0830},
#       "raw_candidates": {"Y": 0.9170, "N": 0.0829, "Yes": 0.0003},
#       "model": "jev-27b-vl",
#       "latency_ms": 412
#     }
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from harness.decisions.core import (
    DecisionError,
    DecisionRequest,
    build_messages,
    interpret,
)
from infra.decision.backends import orchestrator_decision_client
from infra.decision.client import DecisionUnavailable
from infra.decision.jev import scan_jev_models

logger = logging.getLogger("DSNUISystem1")

#: The decision types System-1 supports.
SUPPORTED_TYPES = ("yes_no", "choice", "score")

#: A choice question supports up to 256 options (double letter labels).
MAX_CHOICE_OPTIONS = 256


def register_system1_routes(app, engine) -> None:
    """Mount the System-1 decision routes on the FastAPI app."""

    # -- backend selection --

    def _resolve_model(model_name: Optional[str]) -> tuple[str, Any]:
        """Resolve the model name and its spec in the orchestrator."""
        orch = engine.orchestrator
        name = model_name or orch.get_default_model()
        if not name:
            raise HTTPException(status_code=400, detail="no model given and no default model")
        spec = orch._specs.get(name)
        if spec is None:
            raise HTTPException(status_code=404, detail=f"no such model: {name}")
        return name, spec

    def _is_decision_model(spec) -> bool:
        """Whether the model carries a decision head (the JEV family).

        The test is the **weight path**, not the name: a registry name can be
        changed at will, but a weight file that is a JEV main model always has
        the decision head. Auxiliary files (the projector, drafts, qlora
        derivatives) do not count.
        """
        cfg = getattr(spec, "llama_config", None)
        model_path = getattr(cfg, "model_path", None)
        if not model_path:
            return False
        for m in scan_jev_models():
            if os.path.abspath(m.model_path) == os.path.abspath(model_path):
                return True
        return False

    # -- routes --

    @app.get("/v1/decide/capabilities")
    async def decide_capabilities(model: Optional[str] = None):
        """Probe whether the model can serve a decision.

        It does not answer True unconditionally: only a model with a decision
        head (JEV and friends) returns probabilities with any calibration.
        An ordinary model returns logprobs too, but they are not calibrated.
        """
        try:
            name, spec = _resolve_model(model)
        except HTTPException as e:
            return JSONResponse(status_code=e.status_code, content={"error": e.detail})

        cfg = getattr(spec, "llama_config", None)
        vision = bool(getattr(cfg, "mmproj_path", None)) if cfg is not None else False
        launcher = getattr(spec, "launcher", None)
        endpoint = (getattr(launcher, "base_url", None)
                    or getattr(spec, "base_url", None) or "")

        if not _is_decision_model(spec):
            return {
                "model": name,
                "endpoint": endpoint,
                "system1": False,
                "system1_reason": "this model has no decision head (only the JEV family does)",
                "system2": True,
                "vision": vision,
                "supported_types": [],
                "max_choice_options": 0,
                "note": "System-1 needs a model with a fused typed-decision head",
            }

        # The model is running: probe it for real (identity check plus
        # logprobs).
        running = bool(launcher is not None and launcher.is_running())
        if running:
            try:
                with orchestrator_decision_client(
                        engine.orchestrator, name, timeout=10) as client:
                    ok, reason = client.probe(
                        expect_model_path=getattr(cfg, "model_path", "") or "")
            except DecisionUnavailable as e:
                ok, reason = False, str(e)[:200]
        else:
            # Not running: the model starts on demand through the scheduler
            # lease, so no probe here. Probing would load 16GB of weights for
            # nothing.
            ok, reason = True, "the model is not loaded yet (it starts on the first decision)"

        return {
            "model": name,
            "endpoint": endpoint,
            "system1": ok,
            "system1_reason": reason or None,
            "system2": True,
            "vision": vision,
            "supported_types": list(SUPPORTED_TYPES) if ok else [],
            "max_choice_options": MAX_CHOICE_OPTIONS if ok else 0,
            "note": "System-1 reads the probability distribution of a single forward "
                    "pass and generates no reasoning text"
            if ok else "this model cannot provide the logprobs a decision needs",
        }

    @app.post("/v1/decide")
    async def decide(req: Request):
        """The System-1 decision endpoint.

        One forward pass, with a calibrated probability and no chain of thought.
        """
        try:
            body = await req.json()
        except Exception:
            raise HTTPException(status_code=400, detail="the request body is not valid JSON")
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="the request body must be a JSON object")

        dtype = str(body.get("type") or "yes_no").strip().lower()
        if dtype not in SUPPORTED_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"unsupported decision type: {dtype} "
                        f"(pick one of {' / '.join(SUPPORTED_TYPES)})",
            )

        name, _spec = _resolve_model(body.get("model"))

        dreq = DecisionRequest(
            type=dtype,
            state=body.get("state") or body.get("text") or "",
            question=body.get("question") or "",
            options=body.get("options"),
            max_score=body.get("max_score", 5),
            model=name,
            image_url=body.get("image_url") or "",
            instruction=body.get("instruction") or "",
            messages=body.get("messages"),
        )
        try:
            dreq.validate()
        except DecisionError as e:
            raise HTTPException(status_code=400, detail=str(e))

        try:
            with orchestrator_decision_client(
                    engine.orchestrator, name, timeout=600) as client:
                raw = client.candidates(
                    build_messages(dreq), image_url=dreq.image_url or "")
                result = interpret(
                    raw.candidates, dreq, model=raw.model, latency_ms=raw.latency_ms)
        except DecisionUnavailable as e:
            logger.warning("the System-1 decision failed: model=%s err=%s", name, e)
            return JSONResponse(
                status_code=502,
                content={"error": {"type": "upstream_error", "message": str(e)}},
            )
        except DecisionError as e:
            raise HTTPException(status_code=400, detail=str(e))

        payload = result.to_dict()
        payload["model"] = payload.get("model") or name
        return payload

    logger.info("the System-1 decision API is enabled: GET /v1/decide/capabilities, POST /v1/decide")
