# cli/tui/auth.py
"""OAuth2 authentication via LittleSkin + JWT token management."""

from __future__ import annotations

import os
import json
import asyncio
import logging
from pathlib import Path
from typing import Optional

from aiohttp import web
from cryptography.fernet import Fernet

logger = logging.getLogger("tui.auth")

_TOKEN_FILE = Path(__file__).resolve().parent.parent / "token.enc"
_KEY_FILE = Path(__file__).resolve().parent.parent / "secret.key"


class AuthManager:
    """Manages LittleSkin OAuth2 authentication and JWT token persistence."""

    def __init__(self, server_url: str = "http://localhost:5000"):
        self.server_url = server_url
        self.token: Optional[str] = None
        self.user: Optional[dict] = None
        self._cipher: Optional[Fernet] = None

    # ── Token persistence ──

    def _ensure_key(self) -> Fernet:
        if self._cipher:
            return self._cipher
        if _KEY_FILE.exists():
            self._cipher = Fernet(_KEY_FILE.read_bytes())
        else:
            key = Fernet.generate_key()
            _KEY_FILE.write_bytes(key)
            self._cipher = Fernet(key)
        return self._cipher

    def load_token(self) -> Optional[str]:
        """Load and decrypt stored JWT, or return None."""
        if not _TOKEN_FILE.exists():
            return None
        try:
            cipher = self._ensure_key()
            token = cipher.decrypt(_TOKEN_FILE.read_bytes()).decode("utf-8")
            parts = token.split(".")
            if len(parts) == 3:
                import base64
                payload = json.loads(base64.urlsafe_b64decode(parts[1] + "==").decode("utf-8"))
                self.user = {"uid": payload.get("uid", 0), "nickname": payload.get("nickname", "User")}
            self.token = token
            return token
        except Exception as e:
            logger.warning("Failed to load token: %s", e)
            return None

    def save_token(self, token: str) -> None:
        """Encrypt and persist JWT token."""
        cipher = self._ensure_key()
        _TOKEN_FILE.write_bytes(cipher.encrypt(token.encode("utf-8")))
        self.token = token
        parts = token.split(".")
        if len(parts) == 3:
            import base64
            payload = json.loads(base64.urlsafe_b64decode(parts[1] + "==").decode("utf-8"))
            self.user = {"uid": payload.get("uid", 0), "nickname": payload.get("nickname", "User")}

    def clear_token(self) -> None:
        self.token = None
        self.user = None
        if _TOKEN_FILE.exists():
            _TOKEN_FILE.unlink()

    @property
    def headers(self) -> dict:
        if self.token:
            return {"Authorization": f"Bearer {self.token}"}
        return {}

    @property
    def is_authenticated(self) -> bool:
        return self.token is not None

    # ── OAuth login flow (unified) ──

    async def login(self, timeout: float = 120) -> str:
        """
        Full login flow:
        1. Start local HTTP server on a random available port
        2. Request OAuth URL from server
        3. Open browser for user authorization
        4. Wait for callback with JWT token
        5. Save token

        Returns the JWT token string.
        Raises TimeoutError or RuntimeError on failure.
        """
        import socket
        import aiohttp

        # Find a free port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("localhost", 0))
            port = s.getsockname()[1]

        redirect_uri = f"http://localhost:{port}/callback"

        # Get auth URL from server
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.server_url}/api/auth/start",
                params={"redirect_uri": redirect_uri},
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"Server auth start failed: {resp.status}")
                data = await resp.json()
                auth_url = data.get("auth_url", "")
                if not auth_url:
                    raise RuntimeError("No auth_url in server response")

        # Start local callback server
        result: dict = {"token": None}
        event = asyncio.Event()

        async def handle_callback(request: web.Request) -> web.Response:
            token = request.query.get("token", "")
            if token:
                result["token"] = token
                event.set()
                return web.Response(
                    text="<html><body><h2>Login successful!</h2><p>You may close this window.</p></body></html>",
                    content_type="text/html",
                )
            return web.Response(text="Missing token", status=400)

        app = web.Application()
        app.router.add_get("/callback", handle_callback)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "localhost", port)
        await site.start()

        try:
            import webbrowser
            webbrowser.open(auth_url)
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            pass
        finally:
            await runner.cleanup()

        token = result.get("token")
        if token:
            self.save_token(token)
            return token
        raise TimeoutError("Login timed out — no token received")
