from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models.clients import OpenAIChat


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
