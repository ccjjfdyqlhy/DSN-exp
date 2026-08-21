# harness/auth/__init__.py
# 通用认证层 — 身份 + API Key + TOTP + 签名会话 + 原生多用户。
# 标准库实现，无外部依赖。

from .base import Identity, IAuthenticator
from .api_key import APIKeyManager
from .session import SessionManager
from .totp import TOTP
from .users import User, UserStore, hash_password, verify_password

__all__ = [
    "Identity",
    "IAuthenticator",
    "APIKeyManager",
    "SessionManager",
    "TOTP",
    "User",
    "UserStore",
    "hash_password",
    "verify_password",
]
