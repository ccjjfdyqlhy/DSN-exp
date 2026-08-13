# auth/totp_manager.py
# TOTPManager — L3 TOTP 后备认证

from __future__ import annotations

import logging

logger = logging.getLogger("TOTPManager")


class TOTPManager:
    """L3 TOTP 管理器。需要 pip install pyotp。"""

    def __init__(self, db=None, issuer: str = "DSN-exp"):
        self._db = db
        self._issuer = issuer
        self._otp = None

    @property
    def available(self) -> bool:
        try:
            import pyotp
            return True
        except ImportError:
            return False

    def setup(self, uid: int, username: str) -> dict | None:
        """生成 TOTP 种子 → 返回 {secret, uri, qr_data_uri}"""
        if not self.available:
            return None
        try:
            import pyotp
            import base64
            from io import BytesIO

            secret = pyotp.random_base32()
            uri = pyotp.totp.TOTP(secret).provisioning_uri(
                username, issuer_name=self._issuer,
            )

            qr_data_uri = None
            try:
                import qrcode
                img = qrcode.make(uri)
                buf = BytesIO()
                img.save(buf, format="PNG")
                qr_data_uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
            except ImportError:
                pass

            if self._db:
                self._db._get_connection().execute(
                    "INSERT OR REPLACE INTO auth_totp (uid, secret, enabled) VALUES (?, ?, 0)",
                    (uid, secret),
                )
                self._db._get_connection().commit()

            logger.info("TOTP 种子已生成 uid=%d", uid)
            return {"secret": secret, "uri": uri, "qr_data_uri": qr_data_uri}
        except Exception as e:
            logger.error("TOTP 设置失败: %s", e)
            return None

    def activate(self, uid: int, code: str) -> bool:
        """用验证码激活 TOTP"""
        if not self.available:
            return False
        if self.verify(uid, code):
            if self._db:
                self._db._get_connection().execute(
                    "UPDATE auth_totp SET enabled = 1 WHERE uid = ?", (uid,)
                )
                self._db._get_connection().commit()
            return True
        return False

    def verify(self, uid: int, code: str) -> bool:
        """验证 TOTP 码"""
        if not self.available:
            return False
        try:
            import pyotp
            if not self._db:
                return False
            row = self._db._get_connection().execute(
                "SELECT secret FROM auth_totp WHERE uid = ? AND enabled = 1", (uid,)
            ).fetchone()
            if not row:
                return False
            totp = pyotp.TOTP(row["secret"])
            return totp.verify(code)
        except Exception as e:
            logger.error("TOTP 验证失败: %s", e)
            return False

    def is_enabled(self, uid: int) -> bool:
        if not self._db:
            return False
        row = self._db._get_connection().execute(
            "SELECT enabled FROM auth_totp WHERE uid = ?", (uid,)
        ).fetchone()
        return bool(row and row["enabled"])
