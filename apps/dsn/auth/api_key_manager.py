# auth/api_key_manager.py
# APIKeyManager — L4 API 密钥管理

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger("APIKeyManager")


class APIKeyManager:
    """L4 API 密钥管理器。SHA-256 哈希存储，支持 scope + IP 白名单。"""

    PREFIX = "dsn_apk_"

    def __init__(self, db=None):
        self._db = db

    def create_key(self, uid: int, name: str, scopes: str = "read",
                   ip_whitelist: str = "", expires_days: int = 365) -> tuple[str, str]:
        """
        生成新 API Key。返回 (明文, key_hash)。
        明文仅此一次可见。
        """
        raw = self.PREFIX + secrets.token_urlsafe(32)
        key_hash = self._hash(raw)
        expires = (datetime.now(timezone.utc) + timedelta(days=expires_days)).isoformat() if expires_days else None

        if self._db:
            try:
                self._db._get_connection().execute(
                    "INSERT INTO auth_api_keys (key_hash, uid, name, scopes, ip_whitelist, expires_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (key_hash, uid, name, scopes, ip_whitelist, expires),
                )
                self._db._get_connection().commit()
                logger.info("API Key 已创建 uid=%d name=%s scopes=%s", uid, name, scopes)
            except Exception as e:
                logger.error("创建 API Key 失败: %s", e)

        return raw, key_hash

    def validate(self, key: str) -> int | None:
        """验证 API Key，返回 uid 或 None"""
        if not key.startswith(self.PREFIX):
            return None
        if not self._db:
            return None
        key_hash = self._hash(key)
        try:
            row = self._db._get_connection().execute(
                "SELECT uid, expires_at, revoked FROM auth_api_keys WHERE key_hash = ?",
                (key_hash,)
            ).fetchone()
            if not row:
                return None
            if row["revoked"]:
                return None
            if row["expires_at"]:
                try:
                    exp = datetime.fromisoformat(row["expires_at"])
                    if exp < datetime.now(timezone.utc):
                        return None
                except (ValueError, TypeError):
                    pass
            self._db._get_connection().execute(
                "UPDATE auth_api_keys SET last_used_at = datetime('now') WHERE key_hash = ?",
                (key_hash,)
            )
            self._db._get_connection().commit()
            return row["uid"]
        except Exception as e:
            logger.error("验证 API Key 失败: %s", e)
            return None

    def revoke(self, key_hash: str) -> bool:
        if not self._db:
            return False
        try:
            self._db._get_connection().execute(
                "UPDATE auth_api_keys SET revoked = 1 WHERE key_hash = ?", (key_hash,)
            )
            self._db._get_connection().commit()
            return True
        except Exception:
            return False

    def list_keys(self, uid: int) -> list[dict]:
        if not self._db:
            return []
        try:
            rows = self._db._get_connection().execute(
                "SELECT key_hash, name, scopes, ip_whitelist, "
                "created_at, last_used_at, expires_at, revoked "
                "FROM auth_api_keys WHERE uid = ? ORDER BY created_at DESC",
                (uid,)
            ).fetchall()
            results = []
            for r in rows:
                d = dict(r)
                d["key_hash"] = d["key_hash"][:16] + "..."
                results.append(d)
            return results
        except Exception:
            return []

    @staticmethod
    def _hash(key: str) -> str:
        return hashlib.sha256(key.encode()).hexdigest()
