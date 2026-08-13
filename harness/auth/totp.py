# harness/auth/totp.py
# TOTP (RFC 6238) 实现 — 标准库 + hmac。

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time


class TOTP:
    """基于时间的一次性口令。"""

    def __init__(self, *, digits: int = 6, period: int = 30, window: int = 1):
        self.digits = digits
        self.period = period
        self.window = window

    def generate_secret(self, *, length: int = 20) -> str:
        """生成 base32 编码的共享密钥。"""
        raw = secrets.token_bytes(length)
        return base64.b32encode(raw).decode("ascii").rstrip("=")

    def current_code(self, secret: str, timestamp: Optional[int] = None) -> str:
        ts = int(timestamp or time.time())
        counter = ts // self.period
        return self._code_at(secret, counter)

    def verify(self, code: str, secret: str, timestamp: Optional[int] = None) -> bool:
        ts = int(timestamp or time.time())
        counter = ts // self.period
        code = str(code).strip()
        for offset in range(-self.window, self.window + 1):
            if hmac.compare_digest(self._code_at(secret, counter + offset), code):
                return True
        return False

    def provisioning_uri(self, secret: str, account: str, issuer: str = "") -> str:
        from urllib.parse import quote
        label = quote(f"{issuer}:{account}" if issuer else account)
        return f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}"

    def _code_at(self, secret: str, counter: int) -> str:
        key = base64.b32decode(self._pad_b32(secret))
        msg = struct.pack(">Q", counter)
        digest = hmac.new(key, msg, hashlib.sha1).digest()
        offset = digest[-1] & 0x0F
        code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** self.digits)
        return str(code).zfill(self.digits)

    @staticmethod
    def _pad_b32(secret: str) -> str:
        return secret + "=" * ((8 - len(secret) % 8) % 8)
