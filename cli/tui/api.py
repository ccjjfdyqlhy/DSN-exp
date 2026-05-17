# cli/tui/api.py
"""Async API client for DSN-exp server — chat, SSE streaming, ASR."""

from __future__ import annotations

import json
import logging
from typing import AsyncIterator, Optional

import aiohttp

logger = logging.getLogger("tui.api")


class APIClient:
    """Async HTTP client wrapping all DSN-exp API endpoints."""

    def __init__(self, server_url: str, auth):
        self.server_url = server_url
        self.auth = auth

    @property
    def headers(self) -> dict:
        return self.auth.headers

    def _url(self, path: str) -> str:
        return f"{self.server_url}{path}"

    # ── Chat ──

    async def get_chats(self) -> list[dict]:
        """GET /api/chat/list → [{chat_id, chat_name, message_count, created_at}]"""
        async with aiohttp.ClientSession() as s:
            async with s.get(self._url("/api/chat/list"), headers=self.headers) as resp:
                resp.raise_for_status()
                data = await resp.json()
                return data.get("chats", [])

    async def get_history(self, chat_id: int) -> list[dict]:
        """GET /api/chat/<id> → [{role, content}]"""
        async with aiohttp.ClientSession() as s:
            async with s.get(self._url(f"/api/chat/{chat_id}"), headers=self.headers) as resp:
                if resp.status == 404:
                    return []
                resp.raise_for_status()
                data = await resp.json()
                return data.get("messages", [])

    async def delete_chat(self, chat_id: int) -> bool:
        """DELETE /api/chat/<id> (if implemented on server; graceful fallback)"""
        async with aiohttp.ClientSession() as s:
            async with s.delete(self._url(f"/api/chat/{chat_id}"), headers=self.headers) as resp:
                return resp.status in (200, 204)

    # ── SSE Streaming ──

    async def stream_send(
        self,
        message: str,
        chat_id: Optional[int] = None,
        chat_name: str = "New Chat",
        model_type: str = "deepseek",
        tts_enabled: bool = True,
        is_asr_input: bool = False,
    ) -> AsyncIterator[dict]:
        """
        POST /api/chat/stream_send — yields SSE status events as dicts.
        Event types: parsing, request, text_ready, execution, tts, completed
        """
        payload = {
            "message": message,
            "chat_name": chat_name,
            "model_type": model_type,
            "tts_enabled": tts_enabled,
            "is_asr_input": is_asr_input,
        }
        if chat_id:
            payload["chat_id"] = chat_id

        timeout = aiohttp.ClientTimeout(total=300)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                self._url("/api/chat/stream_send"),
                headers=self.headers,
                json=payload,
            ) as resp:
                resp.raise_for_status()
                buffer = ""
                async for chunk in resp.content.iter_chunked(1024):
                    text = chunk.decode("utf-8", errors="replace")
                    buffer += text
                    while "\n\n" in buffer:
                        line, buffer = buffer.split("\n\n", 1)
                        for part in line.split("\n"):
                            if part.startswith("data: "):
                                try:
                                    data = json.loads(part[6:])
                                    yield data
                                except json.JSONDecodeError:
                                    logger.debug("SSE parse error: %s", part[:80])

    # ── Blocking send (fallback) ──

    async def send_blocking(
        self,
        message: str,
        chat_id: Optional[int] = None,
        chat_name: str = "New Chat",
        model_type: str = "deepseek",
        tts_enabled: bool = True,
        is_asr_input: bool = False,
    ) -> dict:
        """POST /api/chat/send — blocking, returns full response dict."""
        payload = {
            "message": message,
            "chat_name": chat_name,
            "model_type": model_type,
            "tts_enabled": tts_enabled,
            "is_asr_input": is_asr_input,
        }
        if chat_id:
            payload["chat_id"] = chat_id

        timeout = aiohttp.ClientTimeout(total=120)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                self._url("/api/chat/send"),
                headers=self.headers,
                json=payload,
            ) as resp:
                resp.raise_for_status()
                return await resp.json()

    # ── ASR ──

    async def recognize_audio(self, audio_bytes: bytes, filename: str = "recording.webm") -> str:
        """POST /api/asr/recognize — returns recognized text."""
        data = aiohttp.FormData()
        data.add_field("audio", audio_bytes, filename=filename, content_type="audio/webm")
        async with aiohttp.ClientSession() as s:
            async with s.post(self._url("/api/asr/recognize"), headers=self.headers, data=data) as resp:
                resp.raise_for_status()
                result = await resp.json()
                return result.get("text", "")
