# harness/auth/session.py
# 签名会话令牌 — HMAC 签名，无 JWT 依赖。

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Optional


class SessionManager:
    """签发/校验 HMAC 签名的会话令牌。"""

    def __init__(self, secret: str, *, ttl_seconds: int = 86400 * 7):
        self._secret = secret.encode("utf-8")
        self._ttl = ttl_seconds

    def sign(self, payload: dict, *, ttl_seconds: Optional[int] = None) -> str:
        body = {
            "payload": payload,
            "exp": int(time.time()) + (ttl_seconds or self._ttl),
        }
        data = json.dumps(body, separators=(",", ":")).encode("utf-8")
        sig = hmac.new(self._secret, data, hashlib.sha256).digest()
        data_enc = base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")
        sig_enc = base64.urlsafe_b64encode(sig).decode("ascii").rstrip("=")
        return f"{data_enc}.{sig_enc}"

    def verify(self, token: str) -> Optional[dict]:
        try:
            data_enc, sig_enc = token.split(".", 1)
            data = base64.urlsafe_b64decode(data_enc + "=" * (-len(data_enc) % 4))
            sig = base64.urlsafe_b64decode(sig_enc + "=" * (-len(sig_enc) % 4))
        except (ValueError, base64.binascii.Error):
            return None
        expected = hmac.new(self._secret, data, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            return None
        try:
            body = json.loads(data)
        except (ValueError, TypeError):
            return None
        if int(body.get("exp", 0)) < time.time():
            return None
        return body.get("payload")

    @property
    def ttl_seconds(self) -> int:
        return self._ttl
