# auth/models.py
# 认证系统数据模型

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AuthUser:
    uid: int
    display_name: str = ""
    is_admin: bool = False
    littleskin_uid: Optional[int] = None
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "uid": self.uid,
            "display_name": self.display_name,
            "is_admin": self.is_admin,
            "littleskin_uid": self.littleskin_uid,
        }


@dataclass
class AuthSession:
    session_id: str
    uid: int
    device_name: str = ""
    user_agent: str = ""
    is_trusted: bool = False
    ip_address: str = ""
    expires_at: str = ""
    revoked: bool = False

    @property
    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        from datetime import datetime, timezone
        return datetime.fromisoformat(self.expires_at) < datetime.now(timezone.utc)


@dataclass
class WebAuthnCredential:
    credential_id: str
    uid: int
    public_key: bytes
    sign_count: int = 0
    transports: str = ""
    device_name: str = ""


@dataclass
class APIKey:
    key_hash: str
    uid: int
    name: str
    scopes: str = "read"
    ip_whitelist: str = ""
    expires_at: Optional[str] = None
    revoked: bool = False
