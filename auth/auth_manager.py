# auth/auth_manager.py
# AuthManager — 统一认证入口，协调 L0-L4

from __future__ import annotations

import hashlib
import logging
import os
import secrets
from typing import Optional

logger = logging.getLogger("AuthManager")


class AuthManager:
    """统一认证管理器。"""

    def __init__(self, db=None, jwt_secret: str = "",
                 session_days: int = 30, pairing_digits: int = 8,
                 pairing_timeout: int = 300):
        self._db = db
        self._jwt_secret = jwt_secret or os.environ.get("JWT_SECRET", secrets.token_hex(32))

        from .pairing import PairingManager
        from .session import SessionManager
        from .api_key_manager import APIKeyManager
        from .network import NetworkDetector

        self.pairing = PairingManager(db, digits=pairing_digits, timeout_seconds=pairing_timeout)
        self.session = SessionManager(db, jwt_secret=self._jwt_secret, session_days=session_days)
        self.api_key = APIKeyManager(db)
        self.network = NetworkDetector()
        self.webauthn = None
        self.totp = None
        self._init_webauthn()
        self._init_totp()

    def _init_webauthn(self) -> None:
        try:
            from .webauthn_manager import WebAuthnManager
            wm = WebAuthnManager(self._db)
            self.webauthn = wm if wm.available else None
            if not wm.available:
                logger.info("WebAuthn 未安装 (pip install webauthn)")
        except ImportError:
            self.webauthn = None
            logger.info("WebAuthn 未安装 (pip install webauthn)")

    def _init_totp(self) -> None:
        try:
            from .totp_manager import TOTPManager
            tm = TOTPManager(self._db)
            self.totp = tm if tm.available else None
            if not tm.available:
                logger.info("TOTP 未安装 (pip install pyotp)")
        except ImportError:
            self.totp = None
            logger.info("TOTP 未安装 (pip install pyotp)")

    @property
    def db(self):
        return self._db

    @db.setter
    def db(self, value):
        self._db = value
        # 传播到所有子管理器
        if self.pairing:
            self.pairing._db = value
        if self.session:
            self.session._db = value
        if self.api_key:
            self.api_key._db = value
        if self.webauthn:
            self.webauthn._db = value
        if self.totp:
            self.totp._db = value

    # ═══════════ bootstrap ═══════════

    def generate_pairing_if_needed(self) -> str | None:
        """首次启动或没有用户时，生成配对码。返回码文本或 None"""
        if self._user_count() == 0:
            return self.pairing.generate()
        return None

    def _user_count(self) -> int:
        if self._db is None:
            return 0
        try:
            row = self._db._get_connection().execute("SELECT COUNT(*) as cnt FROM users").fetchone()
            return row["cnt"] if row else 0
        except Exception:
            return 0

    # ═══════════ authenticate (login_required 调用) ═══════════

    def authenticate(self, request) -> dict | None:
        """
        统一请求认证入口。
        按优先级: Session → JWT Bearer → API Key。
        返回 {"uid": int, "nickname": str, "auth_source": str} 或 None。
        """
        auth_header = request.headers.get("Authorization", "")
        api_key_header = request.headers.get("X-DSN-API-Key", "")
        logger.debug("authenticate: path=%s Authorization=%s X-DSN-API-Key=%s",
                     request.path,
                     auth_header[:28] + "..." if len(auth_header) > 28 else (auth_header or "<empty>"),
                     "present" if api_key_header else "<empty>")

        # 1. Session header
        if auth_header.startswith("Session "):
            session_id = auth_header[8:].strip()
            logger.debug("authenticate: trying session_id=%.12s...", session_id)
            result = self.session.validate(session_id)
            if result:
                uid = result["uid"]
                logger.debug("authenticate: session OK uid=%d", uid)
                user = self._get_user(uid)
                return {
                    "uid": uid,
                    "nickname": user.get("nickname", "用户"),
                    "display_name": user.get("display_name", ""),
                    "auth_source": "session",
                }
            logger.debug("authenticate: session validation failed")

        # 2. JWT Bearer (兼容旧 LittleSkin 客户端)
        if auth_header.startswith("Bearer "):
            jwt_token = auth_header[7:].strip()
            logger.debug("authenticate: trying JWT Bearer")
            try:
                import jwt as _jwt
                payload = _jwt.decode(jwt_token, self._jwt_secret, algorithms=["HS256"])
                uid = payload.get("uid", 0)
                if uid:
                    logger.debug("authenticate: JWT OK uid=%d", uid)
                    return {
                        "uid": uid,
                        "nickname": payload.get("nickname", "用户"),
                        "email": payload.get("email", ""),
                        "auth_source": "jwt",
                    }
                logger.debug("authenticate: JWT payload has no uid")
            except Exception as e:
                logger.debug("authenticate: JWT decode failed: %s", e)

        # 3. API Key
        if api_key_header:
            logger.debug("authenticate: trying API Key")
            uid = self.api_key.validate(api_key_header)
            if uid:
                logger.debug("authenticate: API Key OK uid=%d", uid)
                user = self._get_user(uid)
                return {
                    "uid": uid,
                    "nickname": user.get("nickname", "api"),
                    "auth_source": "api_key",
                }
            logger.debug("authenticate: API Key validation failed")

        logger.warning("authenticate: ALL METHODS FAILED path=%s", request.path)
        return None

    # ═══════════ user management ═══════════

    def create_user(self, display_name: str, is_admin: bool = False) -> int:
        if self._db is None:
            return 1
        try:
            conn = self._db._get_connection()
            cursor = conn.execute(
                "INSERT INTO users (uid, nickname, display_name, is_admin) VALUES ("
                "(SELECT COALESCE(MAX(uid), 0) + 1 FROM users), ?, ?, ?)",
                (display_name, display_name, 1 if is_admin else 0),
            )
            conn.commit()
            uid = cursor.lastrowid
            logger.info("创建用户 uid=%d name=%s admin=%s", uid, display_name, is_admin)
            return uid
        except Exception as e:
            logger.error("创建用户失败: %s", e)
            return 1

    def get_user(self, uid: int) -> dict | None:
        return self._get_user(uid)

    def list_users(self) -> list[dict]:
        if self._db is None:
            return []
        try:
            rows = self._db._get_connection().execute(
                "SELECT uid, nickname, display_name, is_admin, created_at "
                "FROM users ORDER BY uid"
            ).fetchall()
            return [
                {"uid": r["uid"], "display_name": r["display_name"] or r["nickname"],
                 "is_admin": bool(r["is_admin"])}
                for r in rows
            ]
        except Exception:
            return []

    def _get_user(self, uid: int) -> dict:
        if self._db is None:
            return {"uid": uid, "nickname": "用户"}
        try:
            row = self._db._get_connection().execute(
                "SELECT uid, nickname, display_name, is_admin, littleskin_uid FROM users WHERE uid = ?",
                (uid,)
            ).fetchone()
            if row:
                return dict(row)
        except Exception:
            pass
        return {"uid": uid, "nickname": "用户", "display_name": ""}

    def _get_uid_by_name(self, display_name: str) -> int:
        """通过 display_name 查询 uid"""
        if self._db is None or not display_name:
            return 0
        try:
            row = self._db._get_connection().execute(
                "SELECT uid FROM users WHERE display_name = ? OR nickname = ? LIMIT 1",
                (display_name, display_name)
            ).fetchone()
            if row:
                return row["uid"]
        except Exception:
            pass
        return 0

    # ═══════════ pairing shortcut ═══════════

    def verify_pairing(self, code: str, display_name: str, is_admin: bool = False) -> dict | None:
        """配对码验证快捷入口"""
        uid = self.pairing.verify(code, display_name=display_name, is_admin=is_admin)
        if uid is None:
            return None
        if display_name:
            self._update_user_name(uid, display_name)
        return {"uid": uid, "display_name": display_name, "is_admin": is_admin}

    def _update_user_name(self, uid: int, display_name: str) -> None:
        if self._db is None:
            return
        try:
            self._db._get_connection().execute(
                "UPDATE users SET display_name = ?, nickname = ? WHERE uid = ?",
                (display_name, display_name, uid),
            )
            self._db._get_connection().commit()
        except Exception:
            pass
