# harness/auth/users.py
# 原生多用户认证底层：用户注册 / 登录 / 会话令牌。
#
# 无外部依赖：密码用 pbkdf2_hmac 哈希，令牌用 secrets.token_urlsafe 生成
# 并持久化到 SQLite（支持多设备会话与主动吊销）。
# 任意应用通过 UserStore 即可获得"注册-登录-鉴权"能力。

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from harness.store.sqlite import SqliteStore

_PBKDF2_ITERATIONS = 200_000
_TOKEN_TTL_SECONDS = 86400 * 7  # 7 天


@dataclass
class User:
    """已注册用户。"""
    uid: str
    username: str
    nickname: str = ""
    created_at: float = 0.0
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "username": self.username,
            "nickname": self.nickname,
            "created_at": self.created_at,
            **self.extra,
        }


def _hash_password(password: str, *, iterations: int = _PBKDF2_ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2${iterations}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(digest.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


def _now() -> float:
    return time.time()


class UserStore:
    """用户与会话令牌存储（SQLite）。"""

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self.store = SqliteStore(db_path)
        self._init_schema()

    def _init_schema(self) -> None:
        self.store.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                uid          TEXT PRIMARY KEY,
                username     TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                nickname     TEXT DEFAULT '',
                created_at   REAL NOT NULL
            )
            """
        )
        self.store.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_tokens (
                token      TEXT PRIMARY KEY,
                uid        TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                revoked    INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        self.store.execute(
            "CREATE INDEX IF NOT EXISTS idx_auth_tokens_uid ON auth_tokens(uid)"
        )

    # ── 用户 ──

    def register(self, username: str, password: str,
                 nickname: str = "") -> User:
        """注册新用户。用户名重复时抛 ValueError。"""
        username = (username or "").strip()
        if not username:
            raise ValueError("用户名不能为空")
        if len(password) < 6:
            raise ValueError("密码至少 6 位")
        if self.get_by_username(username):
            raise ValueError(f"用户名 {username!r} 已被注册")
        user = User(
            uid=secrets.token_hex(8),
            username=username,
            nickname=nickname or username,
            created_at=_now(),
        )
        self.store.execute(
            "INSERT INTO users (uid, username, password_hash, nickname, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (user.uid, user.username, _hash_password(password),
             user.nickname, user.created_at),
        )
        return user

    def authenticate(self, username: str, password: str) -> Optional[User]:
        """校验用户名密码；成功返回 User，失败返回 None。"""
        user = self.get_by_username(username)
        if user is None:
            return None
        rows = self.store.execute(
            "SELECT password_hash FROM users WHERE uid = ?", (user.uid,))
        if not rows:
            return None
        if not _verify_password(password, rows[0]["password_hash"]):
            return None
        return user

    def get_by_username(self, username: str) -> Optional[User]:
        rows = self.store.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
            ((username or "").strip(),),
        )
        return self._row_to_user(rows[0]) if rows else None

    def get_user(self, uid: str) -> Optional[User]:
        rows = self.store.execute("SELECT * FROM users WHERE uid = ?", (uid,))
        return self._row_to_user(rows[0]) if rows else None

    def list_users(self) -> list[User]:
        rows = self.store.execute(
            "SELECT * FROM users ORDER BY created_at ASC")
        return [self._row_to_user(r) for r in rows]

    @staticmethod
    def _row_to_user(row: Any) -> User:
        return User(
            uid=row["uid"],
            username=row["username"],
            nickname=row["nickname"] or "",
            created_at=row["created_at"],
        )

    # ── 会话令牌 ──

    def issue_token(self, uid: str, *, ttl_seconds: int = _TOKEN_TTL_SECONDS) -> str:
        """为用户签发一个登录令牌。"""
        token = secrets.token_urlsafe(32)
        now = _now()
        self.store.execute(
            "INSERT INTO auth_tokens (token, uid, created_at, expires_at, revoked)"
            " VALUES (?, ?, ?, ?, 0)",
            (token, uid, now, now + ttl_seconds),
        )
        return token

    def resolve_token(self, token: str) -> Optional[User]:
        """校验令牌：有效返回 User，否则返回 None。"""
        if not token:
            return None
        rows = self.store.execute(
            "SELECT * FROM auth_tokens WHERE token = ?", (token,))
        if not rows:
            return None
        row = rows[0]
        if row["revoked"] or row["expires_at"] < _now():
            return None
        return self.get_user(row["uid"])

    def revoke_token(self, token: str) -> None:
        self.store.execute(
            "UPDATE auth_tokens SET revoked = 1 WHERE token = ?", (token,))

    def revoke_all_tokens(self, uid: str) -> None:
        self.store.execute(
            "UPDATE auth_tokens SET revoked = 1 WHERE uid = ?", (uid,))

    def close(self) -> None:
        self.store.close()


__all__ = ["User", "UserStore", "hash_password", "verify_password"]


def hash_password(password: str, *, iterations: int = _PBKDF2_ITERATIONS) -> str:
    return _hash_password(password, iterations=iterations)


def verify_password(password: str, stored: str) -> bool:
    return _verify_password(password, stored)
