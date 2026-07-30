from __future__ import annotations

import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models.clients import OpenAIChat, LMSummaryModel


class _Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "model": "test-model",
            "choices": [{"message": {"content": "ok"}}],
        }


class _Session:
    def __init__(self):
        self.calls = []

    def post(self, url, headers, json, timeout):
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return _Response()


def test_openai_chat_reuses_its_http_session():
    chat = OpenAIChat(api_key="test-key", api_url="https://api.test/v1", timeout=12)
    session = _Session()
    chat._http_session = session

    assert chat.send_message("first") == "ok"
    assert chat.send_message("second") == "ok"
    assert len(session.calls) == 2
    assert all(call["url"] == "https://api.test/v1/chat/completions" for call in session.calls)
    assert all(call["timeout"] == 12 for call in session.calls)


class _SummaryResponse:
    def __init__(self, status_code=200):
        self.status_code = status_code
        self.headers = {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(
                f"HTTP {self.status_code}", response=self,
            )

    def json(self):
        return {"choices": [{"message": {"content": "summary"}}]}


class _SummarySession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = 0

    def post(self, url, headers, json, timeout):
        self.calls += 1
        return next(self.responses)


def test_summary_retries_transient_503(monkeypatch):
    summary_model = LMSummaryModel(
        backend="openai",
        api_key="test-key",
        model_name="test-model",
    )
    session = _SummarySession([_SummaryResponse(503), _SummaryResponse()])
    summary_model._http_session = session
    sleeps = []
    monkeypatch.setattr("time.sleep", sleeps.append)

    result = summary_model.summarize_text("dialogue")
    assert result == "summary"
    assert session.calls == 2
    assert sleeps == [1.0]


def test_summary_does_not_retry_401(monkeypatch):
    summary_model = LMSummaryModel(
        backend="openai",
        api_key="test-key",
        model_name="test-model",
    )
    session = _SummarySession([_SummaryResponse(401)])
    summary_model._http_session = session
    monkeypatch.setattr("time.sleep", lambda delay: None)

    with pytest.raises(requests.exceptions.HTTPError):
        summary_model.summarize_text("dialogue")
    assert session.calls == 1
