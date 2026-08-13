# auth/session.py
# SessionManager — L1 设备信任 Cookie + 会话验证

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger("SessionManager")


class SessionManager:
    """L1 会话管理器。设备信任 Cookie + 短期 session 验证。"""

    def __init__(self, db=None, jwt_secret: str = "", session_days: int = 30):
        self._db = db
        self._jwt_secret = jwt_secret or os.environ.get("JWT_SECRET", secrets.token_hex(32))
        self._session_days = session_days

    def create_session(self, uid: int, device_name: str = "",
                       user_agent: str = "", ip_address: str = "",
                       trust_device: bool = False) -> tuple[str, str, str]:
        """
        创建会话。
        返回: (session_id, device_token, expires_iso)。
        session_id: 短期会话令牌（API header 使用）
        device_token: 长期设备令牌（Cookie 使用）
        """
        session_id = "dsn_ses_" + secrets.token_hex(32)
        device_token = secrets.token_hex(32)
        device_hash = self._hash_token(device_token)
        expires = datetime.now(timezone.utc) + timedelta(days=self._session_days)
        expires_str = expires.isoformat()

        if self._db:
            try:
                self._db._get_connection().execute(
                    "INSERT INTO auth_sessions (session_id, uid, device_token_hash, "
                    "device_name, user_agent, is_trusted, ip_address, expires_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (session_id, uid, device_hash, device_name, user_agent,
                     1 if trust_device else 0, ip_address, expires_str),
                )
                self._db._get_connection().commit()
            except Exception as e:
                logger.error("创建会话失败: %s", e)

        return session_id, device_token, expires_str

    def validate(self, session_id: str) -> dict | None:
        """验证 session，返回 {"uid": int} 或 None"""
        if not self._db:
            logger.warning("Session.validate: no db, returning None")
            return None
        try:
            row = self._db._get_connection().execute(
                "SELECT uid, expires_at, revoked FROM auth_sessions "
                "WHERE session_id = ?", (session_id,)
            ).fetchone()
            if not row:
                logger.debug("Session.validate: session_id not found in DB")
                return None
            if row["revoked"]:
                logger.debug("Session.validate: session revoked uid=%d", row["uid"])
                return None
            if row["expires_at"]:
                try:
                    exp = datetime.fromisoformat(row["expires_at"])
                    now = datetime.now(timezone.utc)
                    if exp < now:
                        logger.debug("Session.validate: session expired uid=%d exp=%s now=%s",
                                     row["uid"], row["expires_at"], now.isoformat())
                        return None
                except (ValueError, TypeError):
                    pass
            # Update last_used_at
            self._db._get_connection().execute(
                "UPDATE auth_sessions SET last_used_at = datetime('now') WHERE session_id = ?",
                (session_id,)
            )
            self._db._get_connection().commit()
            logger.debug("Session.validate: OK uid=%d", row["uid"])
            return {"uid": row["uid"]}
        except Exception as e:
            logger.error("验证会话失败: %s", e)
            return None

    def validate_device_token(self, device_token: str) -> int | None:
        """
        通过长期设备令牌恢复会话。
        返回 uid 或 None。
        """
        if not self._db:
            logger.warning("Session.validate_device_token: no db")
            return None
        device_hash = self._hash_token(device_token)
        try:
            row = self._db._get_connection().execute(
                "SELECT uid, expires_at, revoked FROM auth_sessions "
                "WHERE device_token_hash = ? AND is_trusted = 1 "
                "ORDER BY created_at DESC LIMIT 1", (device_hash,)
            ).fetchone()
            if not row:
                logger.debug("Session.validate_device_token: no trusted session for hash")
                return None
            if row["revoked"]:
                logger.debug("Session.validate_device_token: device session revoked")
                return None
            if row["expires_at"]:
                try:
                    exp = datetime.fromisoformat(row["expires_at"])
                    now = datetime.now(timezone.utc)
                    if exp < now:
                        logger.debug("Session.validate_device_token: device expired exp=%s now=%s",
                                     row["expires_at"], now.isoformat())
                        return None
                except (ValueError, TypeError):
                    pass
            logger.debug("Session.validate_device_token: OK uid=%d", row["uid"])
            return row["uid"]
        except Exception as e:
            logger.error("验证设备令牌失败: %s", e)
            return None

    def recover(self, uid: int, device_token: str, ip_address: str = "") -> dict | None:
        """信任设备恢复：验证设备令牌+uid → 返回 session 信息"""
        logger.debug("Session.recover: uid=%d device_token_hash=%s", uid, self._hash_token(device_token)[:12])
        stored_uid = self.validate_device_token(device_token)
        if stored_uid is None:
            logger.debug("Session.recover: device_token validation failed (no trusted session)")
            return None
        if stored_uid != uid:
            logger.debug("Session.recover: uid mismatch stored=%d requested=%d", stored_uid, uid)
            return None
        session_id, _, expires = self.create_session(
            uid, device_name="recovered", ip_address=ip_address, trust_device=True,
        )
        logger.info("Session.recover: OK uid=%d new_session=%.12s...", uid, session_id)
        return {"session_id": session_id, "uid": uid, "expires_at": expires}

    def revoke_session(self, session_id: str) -> bool:
        if not self._db:
            return False
        try:
            self._db._get_connection().execute(
                "UPDATE auth_sessions SET revoked = 1 WHERE session_id = ?",
                (session_id,)
            )
            self._db._get_connection().commit()
            return True
        except Exception:
            return False

    def list_sessions(self, uid: int) -> list[dict]:
        if not self._db:
            return []
        try:
            rows = self._db._get_connection().execute(
                "SELECT session_id, device_name, user_agent, is_trusted, "
                "ip_address, created_at, last_used_at, expires_at, revoked "
                "FROM auth_sessions WHERE uid = ? ORDER BY created_at DESC LIMIT 20",
                (uid,)
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def _hash_token(self, token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()
