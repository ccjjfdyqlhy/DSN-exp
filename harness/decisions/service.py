# harness/decisions/service.py
"""Decision facade - joins the transport (infra) with the semantics (core).
#
# ## Why a facade
#
# A caller usually does two things: run a decision and find out whether one is
# possible right now. Building the client, fetching the candidates and
# interpreting them by hand spreads that chain over the whole codebase, so the
# facade turns it into two methods.
#
# ## A client factory rather than a client
#
# The decision model is owned by the peripheral resource pool: it starts on the
# first decision (the llama-server cold start takes tens of seconds) and the
# idle reaper stops it again. So every decision fetches a client instead of
# holding one for the lifetime of the process. The factory raises
# :class:`DecisionUnavailable` when no client can be had, and the caller
# degrades instead of crashing.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Callable, Iterator, Optional, Union

from infra.decision.client import DecisionClient, DecisionUnavailable

from .core import (
    DecisionError,
    DecisionRequest,
    DecisionResult,
    build_messages,
    interpret,
)

logger = logging.getLogger("DecisionService")

#: A provider of decision clients. Two shapes are accepted:
#:   * a callable that returns a client (the client lifetime is not managed
#:     here);
#:   * a callable that returns a context manager (recommended), so the lease
#:     covers the whole decision, not just the moment the client is fetched.
ClientFactory = Callable[[], Union[DecisionClient, "ContextManager[DecisionClient]"]]


class DecisionService:
    """Facade for running decisions."""

    def __init__(self, client_factory: ClientFactory, *, default_model: str = ""):
        self._factory = client_factory
        self.default_model = default_model or ""

    @contextmanager
    def _acquire(self) -> Iterator[DecisionClient]:
        """Fetch a client, keeping the lease open until the decision is done."""
        obj = self._factory()
        if hasattr(obj, "__enter__") and hasattr(obj, "__exit__"):
            with obj as client:
                yield client
        else:
            yield obj

    # ── main entry point ──

    def decide(self, req: DecisionRequest) -> DecisionResult:
        """Run one decision.

        :raises DecisionUnavailable: the decision endpoint cannot serve a
            decision (not up, or no decision head).
        :raises DecisionError: the request itself is invalid.
        """
        with self._acquire() as client:
            if not req.model and client.model:
                req.model = client.model
            raw = client.candidates(
                build_messages(req),
                image_url=req.image_url or "",
            )
            return interpret(raw.candidates, req, model=raw.model, latency_ms=raw.latency_ms)

    # ── convenience wrappers ──

    def decide_yes_no(
        self,
        question: str,
        state: str = "",
        *,
        model: str = "",
        image_url: str = "",
    ) -> DecisionResult:
        return self.decide(DecisionRequest(
            type="yes_no", question=question, state=state,
            model=model or self.default_model, image_url=image_url))

    def decide_choice(
        self,
        question: str,
        state: str = "",
        options: Union[dict[str, str], list[str], None] = None,
        *,
        model: str = "",
        image_url: str = "",
    ) -> DecisionResult:
        return self.decide(DecisionRequest(
            type="choice", question=question, state=state, options=options,
            model=model or self.default_model, image_url=image_url))

    def decide_score(
        self,
        question: str,
        state: str = "",
        max_score: int = 5,
        *,
        model: str = "",
        image_url: str = "",
    ) -> DecisionResult:
        return self.decide(DecisionRequest(
            type="score", question=question, state=state, max_score=max_score,
            model=model or self.default_model, image_url=image_url))

    # ── capabilities ──

    def probe(self) -> tuple[bool, str]:
        """Check whether the decision endpoint can serve a decision."""
        try:
            with self._acquire() as client:
                return client.probe()
        except DecisionUnavailable as e:
            return False, str(e)[:200]
        except Exception as e:
            return False, str(e)[:200]

    def available(self) -> bool:
        """Whether a decision is possible right now (a failed probe means no)."""
        ok, _ = self.probe()
        return ok

    def __repr__(self) -> str:
        return f"<DecisionService model={self.default_model!r}>"
