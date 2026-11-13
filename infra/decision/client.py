# infra/decision/client.py
"""System-1 decision client - the logprobs channel to a local llama-server.
#
# ## What this channel is
#
# A dual-system model like JEV-27B-VL does not generate text in System 1
# (the decision head). Give it a closed option set and it writes the answer
# distribution straight onto the probability of the next token, in a single
# forward pass. So the thing to read is the probability, not the content.
#
# llama.cpp has no dedicated endpoint for this (that one belongs to the vLLM
# serve_decide.py sidecar), but logprobs give the same distribution:
#
#     max_tokens=1, logprobs=true, top_logprobs=N
#     -> choices[0].logprobs.content[0] holds the vocabulary distribution
#
# What you get is the same distribution the native engine produces, not a
# downgrade.
#
# ## Layering
#
# This module is transport only: it sends the request and reads the
# vocabulary distribution back. It knows nothing about yes/no, options or
# scores - that is harness/decisions.
#
# ## Why a dedicated client instead of reusing OpenAICompatChat
#
# 1. **One token only.** A normal chat client carries sampling parameters and
#    a large max_tokens, while a decision needs the full distribution at the
#    first position. One extra generated token is one extra chance for the
#    probability mass to land on the wrong token.
# 2. **top_logprobs.** A normal client never reads that field.
# 3. **Identity check.** Every local llama.cpp model defaults to port 8080 and
#    only one of them is actually running at a time. Asking the wrong model
#    returns a distribution that looks perfectly normal (still Y/N) but comes
#    from a model with no decision head, so the model_path in /props is
#    compared first.
"""

from __future__ import annotations

import json
import logging
import math
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("DecisionClient")

#: Default request timeout in seconds. A decision is one forward pass, so it
#: normally takes milliseconds to a few seconds. The cold start of the model
#: itself is handled by the resource layer, not here.
DEFAULT_TIMEOUT = 120.0

#: How many candidate tokens to pull from the vocabulary. A choice question
#: supports up to 256 options (double letter labels), so ask for enough to
#: cover them in one response.
DEFAULT_TOP_LOGPROBS = 32


class DecisionUnavailable(RuntimeError):
    """The decision endpoint cannot serve a decision.

    Three causes: the endpoint is not up, the model behind it has no decision
    head, or the response carries no logprobs. Callers should degrade rather
    than crash - a decision is an extra, not the main path.
    """


@dataclass
class RawDecision:
    """The raw result of one decision forward pass.

    candidates is the token -> probability map taken from the logprobs. It is
    neither normalized nor merged per option - that is harness/decisions.
    """

    candidates: dict[str, float] = field(default_factory=dict)
    model: str = ""
    latency_ms: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)


class DecisionClient:
    """HTTP client for a local decision endpoint.

    Usage::

        client = DecisionClient("http://127.0.0.1:8090")
        raw = client.candidates([{"role": "user", "content": "..."}])
        # raw.candidates -> {"Y": 0.968, "N": 0.024, ...}
    """

    def __init__(
        self,
        base_url: str,
        model: str = "",
        timeout: float = DEFAULT_TIMEOUT,
        top_logprobs: int = DEFAULT_TOP_LOGPROBS,
        api_key: str = "",
    ):
        self.base_url = (base_url or "").rstrip("/")
        self.model = model or ""
        self.timeout = float(timeout)
        self.top_logprobs = int(top_logprobs)
        self.api_key = api_key or ""

    # -- low level HTTP --

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _get_json(self, path: str, timeout: float | None = None) -> dict:
        url = self.base_url + path
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout or 10.0) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise DecisionUnavailable(f"{path} returned HTTP {e.code}") from e
        except Exception as e:
            raise DecisionUnavailable(f"{path} is unreachable: {e}") from e

    def _post_json(self, path: str, payload: dict, timeout: float | None = None) -> dict:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:300]
            raise DecisionUnavailable(f"{path} returned HTTP {e.code}: {body}") from e
        except Exception as e:
            raise DecisionUnavailable(f"{path} request failed: {e}") from e

    # -- endpoint capabilities --

    def props(self) -> dict:
        """Read /props from llama-server (model identity, modalities, features)."""
        return self._get_json("/props")

    def health(self) -> bool:
        """Whether the endpoint is ready (/health reports ok)."""
        try:
            data = self._get_json("/health", timeout=3.0)
        except DecisionUnavailable:
            return False
        status = str(data.get("status", "")).lower()
        return status in ("ok", "ok ", "") or bool(data.get("ok"))

    def probe(self, expect_model_path: str = "") -> tuple[bool, str]:
        """Check whether this endpoint can serve a decision.

        Two steps, both required:

        1. **Identity check** against the model_path in /props. Every local
           llama.cpp model defaults to port 8080 and only one is running at a
           time, so without the check a decision can be answered by the wrong
           model (measured: gemma and JEV return nearly the same distribution,
           which is impossible to tell apart by eye).
        2. **A real probe request** to confirm logprobs come back. A model
           that is not loaded, an endpoint that is down and an empty
           distribution all mean "no decision support".

        :param expect_model_path: the model file to expect; empty skips the
            identity check and only verifies that logprobs arrive.
        :return: (supported, reason)
        """
        try:
            props = self.props()
        except DecisionUnavailable as e:
            return False, str(e)[:200]

        served = str(props.get("model_path") or "")
        if expect_model_path:
            want = str(expect_model_path)
            if not served:
                return False, "the endpoint reports no model identity"
            # Compare file names so a different path prefix (~ expansion) does
            # not look like a mismatch.
            if want.rsplit("/", 1)[-1] != served.rsplit("/", 1)[-1]:
                return False, (
                    "that model is not loaded: port %s is serving %s"
                    % (self.base_url, served.rsplit("/", 1)[-1])
                )[:200]

        probe_payload = {
            "messages": [{"role": "user", "content": "Answer Y or N only. Is 1+1=2?"}],
            "max_tokens": 1,
            "temperature": 0,
            "logprobs": True,
            "top_logprobs": 3,
            # Thinking would pollute the first step, so turn it off.
            "chat_template_kwargs": {"enable_thinking": False},
        }
        try:
            resp = self._post_json("/v1/chat/completions", probe_payload)
        except DecisionUnavailable as e:
            return False, str(e)[:200]
        try:
            choice = (resp.get("choices") or [])[0]
            content_lp = ((choice.get("logprobs") or {}).get("content") or [])
            if not content_lp:
                return False, "the upstream returned no logprobs"
            return True, ""
        except Exception as e:
            return False, f"cannot parse the response: {e}"[:200]

    # -- decision forward pass --

    def candidates(
        self,
        messages: list[dict],
        *,
        image_url: str = "",
        max_tokens: int = 1,
        top_logprobs: int | None = None,
        extra_body: dict | None = None,
    ) -> RawDecision:
        """Run one decision forward pass and return the vocabulary distribution.

        :param messages: OpenAI style messages.
        :param image_url: optional image as a data URL. For an image decision it
            is appended as an image_url content block on the first user message.
        :param max_tokens: generation cap. A decision uses 1.
        :param top_logprobs: how many candidate tokens to pull.
        """
        if not messages:
            raise DecisionUnavailable("the decision request carries no messages")

        payload_messages = messages
        if image_url:
            first = dict(messages[0])
            content = first.get("content")
            if isinstance(content, str):
                content = [{"type": "text", "text": content}]
            elif isinstance(content, list):
                content = list(content)
            else:
                content = []
            content.append({"type": "image_url", "image_url": {"url": image_url}})
            first["content"] = content
            payload_messages = [first] + list(messages[1:])

        payload = {
            "messages": payload_messages,
            # Only the distribution at the decision position matters, so no
            # extra content is generated.
            "max_tokens": max_tokens,
            "temperature": 0,
            "logprobs": True,
            "top_logprobs": int(top_logprobs or self.top_logprobs),
            # Thinking would pollute the first step, so turn it off.
            "chat_template_kwargs": {"enable_thinking": False},
        }
        if self.model:
            payload["model"] = self.model
        if extra_body:
            payload.update(extra_body)

        started = time.perf_counter()
        resp = self._post_json("/v1/chat/completions", payload)
        latency = (time.perf_counter() - started) * 1000.0

        try:
            choice = (resp.get("choices") or [])[0]
            content_lp = ((choice.get("logprobs") or {}).get("content") or [])
            if not content_lp:
                raise ValueError("the upstream returned no logprobs")
            first_tok = content_lp[0]
            candidates: dict[str, float] = {first_tok["token"]: float(first_tok["logprob"])}
            for alt in (first_tok.get("top_logprobs") or []):
                candidates[alt["token"]] = float(alt["logprob"])
        except Exception as e:
            raise DecisionUnavailable(f"cannot parse the logprobs: {e}") from e

        return RawDecision(
            candidates={t: math.exp(lp) for t, lp in candidates.items()},
            model=str(resp.get("model") or self.model or ""),
            latency_ms=round(latency, 1),
            raw=resp,
        )

    def __repr__(self) -> str:
        return f"<DecisionClient {self.base_url} model={self.model!r}>"
