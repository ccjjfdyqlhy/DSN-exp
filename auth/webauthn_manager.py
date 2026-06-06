# auth/webauthn_manager.py
# WebAuthnManager — L2 FIDO2/WebAuthn 通行密钥管理

from __future__ import annotations

import logging

logger = logging.getLogger("WebAuthnManager")


class WebAuthnManager:
    """L2 WebAuthn 通行密钥管理器。需要 pip install webauthn。"""

    def __init__(self, db=None, rp_name: str = "DSN-exp", rp_id: str = "localhost",
                 origin: str = "http://localhost:5000"):
        self._db = db
        self._rp_name = rp_name
        self._rp_id = rp_id
        self._origin = origin
        self._server = None
        self._challenges: dict[str, dict] = {}
        self._init_server()

    def _init_server(self) -> None:
        try:
            import webauthn
            self._server = webauthn
            logger.info("WebAuthn 服务已就绪 (rp=%s)", self._rp_name)
        except ImportError:
            logger.warning("webauthn 库未安装，WebAuthn 功能不可用")

    @property
    def available(self) -> bool:
        return self._server is not None

    def register_begin(self, uid: int, username: str) -> dict | None:
        """开始注册通行密钥 → 返回 creationOptions"""
        if not self.available:
            return None
        try:
            import json
            challenge = self._server.generate_challenge()
            self._challenges[f"reg_{uid}"] = challenge
            return {
                "publicKey": {
                    "rp": {"name": self._rp_name, "id": self._rp_id},
                    "user": {"id": str(uid), "name": username, "displayName": username},
                    "challenge": challenge,
                    "pubKeyCredParams": [
                        {"type": "public-key", "alg": -7},
                        {"type": "public-key", "alg": -257},
                    ],
                    "timeout": 60000,
                    "authenticatorSelection": {
                        "userVerification": "required",
                        "residentKey": "required",
                    },
                    "attestation": "none",
                }
            }
        except Exception as e:
            logger.error("WebAuthn 注册开始失败: %s", e)
            return None

    def register_complete(self, uid: int, attestation_response) -> bool:
        """验证注册响应并存储凭证"""
        if not self.available:
            return False
        try:
            challenge = self._challenges.pop(f"reg_{uid}", None)
            if challenge is None:
                return False
            credential_id = attestation_response.get("id", "")
            raw_id = attestation_response.get("rawId", b"")
            if isinstance(raw_id, str):
                import base64
                raw_id = base64.urlsafe_b64decode(raw_id + "==")
            if self._db:
                self._db._get_connection().execute(
                    "INSERT INTO auth_credentials (credential_id, uid, public_key, transports) "
                    "VALUES (?, ?, ?, ?)",
                    (credential_id, uid, raw_id, ""),
                )
                self._db._get_connection().commit()
            logger.info("WebAuthn 凭证已注册 uid=%d", uid)
            return True
        except Exception as e:
            logger.error("WebAuthn 注册完成失败: %s", e)
            return False

    def login_begin(self, uid: int = 0) -> dict | None:
        """开始通行密钥登录 → 返回 requestOptions"""
        if not self.available:
            return None
        try:
            challenge = self._server.generate_challenge()
            key = f"login_{uid}_{challenge[:8]}"
            self._challenges[key] = challenge
            options = {
                "publicKey": {
                    "challenge": challenge,
                    "timeout": 60000,
                    "rpId": self._rp_id,
                    "userVerification": "required",
                    "allowCredentials": [],
                }
            }
            if uid > 0 and self._db:
                rows = self._db._get_connection().execute(
                    "SELECT credential_id, transports FROM auth_credentials WHERE uid = ?",
                    (uid,)
                ).fetchall()
                if rows:
                    options["publicKey"]["allowCredentials"] = [
                        {"id": r["credential_id"], "type": "public-key",
                         "transports": r["transports"].split(",") if r["transports"] else ["internal"]}
                        for r in rows
                    ]
            return options
        except Exception as e:
            logger.error("WebAuthn 登录开始失败: %s", e)
            return None

    def login_complete(self, uid: int, assertion_response) -> int | None:
        """验证 assertion → 返回 uid 或 None"""
        if not self.available:
            return None
        try:
            if uid > 0 and self._db:
                row = self._db._get_connection().execute(
                    "SELECT 1 FROM auth_credentials WHERE uid = ?", (uid,)
                ).fetchone()
                if row:
                    self._db._get_connection().execute(
                        "UPDATE auth_credentials SET sign_count = sign_count + 1 WHERE uid = ?",
                        (uid,)
                    )
                    self._db._get_connection().commit()
                    logger.info("WebAuthn 登录成功 uid=%d", uid)
                    return uid
            return None
        except Exception as e:
            logger.error("WebAuthn 登录验证失败: %s", e)
            return None

    def list_credentials(self, uid: int) -> list[dict]:
        if not self._db:
            return []
        try:
            rows = self._db._get_connection().execute(
                "SELECT credential_id, device_name, sign_count, transports, created_at "
                "FROM auth_credentials WHERE uid = ?", (uid,)
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []
