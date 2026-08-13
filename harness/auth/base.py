# harness/auth/base.py
# 通用认证抽象。

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable


@dataclass
class Identity:
    """认证后的主体。"""
    uid: str
    nickname: str = ""
    scopes: list[str] = field(default_factory=list)
    source: str = ""                 # api_key | session | totp | webauthn | ...
    extra: dict = field(default_factory=dict)

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes

    def to_dict(self) -> dict:
        return {
            "uid": self.uid,
            "nickname": self.nickname,
            "scopes": self.scopes,
            "source": self.source,
            **self.extra,
        }


@runtime_checkable
class IAuthenticator(Protocol):
    """认证器接口 — 从请求上下文解析身份，失败返回 None。"""

    def authenticate(self, request: Any) -> Optional[Identity]: ...
