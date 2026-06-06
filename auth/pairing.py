# auth/pairing.py
# PairingManager — L0 一次性配对码

from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger("PairingManager")


class PairingManager:
    """L0 配对码管理器。终端打印一次性数字码，用于初始装机。"""

    def __init__(self, db=None, digits: int = 8, timeout_seconds: int = 300):
        self._db = db
        self._digits = digits
        self._timeout = timeout_seconds
        self._current_code: Optional[str] = None
        self._current_expires: float = 0.0
        self._failures: int = 0
        self._locked_until: float = 0.0

    def generate(self) -> str:
        """生成新配对码。返回码文本。"""
        self._current_code = "".join(
            str(random.randint(0, 9)) for _ in range(self._digits)
        )
        self._current_expires = time.time() + self._timeout
        self._failures = 0
        self._locked_until = 0.0
        self._persist_code()
        logger.info("配对码已生成 (过期: %ds)", self._timeout)
        return self._current_code

    def verify(self, code: str) -> Optional[int]:
        """
        验证配对码。
        成功 → 创建新用户并返回 uid。
        失败 → 返回 None，连续失败超限后自动换码。
        """
        now = time.time()

        if now > self._locked_until and self._locked_until > 0:
            self._locked_until = 0.0
            self._failures = 0

        if now > self._locked_until and self._locked_until == 0.0 and self._failures == 0:
            pass  # ok

        if self._locked_until > 0 and now < self._locked_until:
            return None

        if self._current_code is None:
            self.generate()
            return None

        if now > self._current_expires:
            self.generate()
            return None

        if code != self._current_code:
            self._failures += 1
            if self._failures >= 5:
                self.generate()
                logger.warning("配对码验证失败 %d 次，已自动更换", self._failures)
            return None

        self._current_code = None
        self._failures = 0

        uid = self._create_default_user()
        self._mark_code_used(code)
        logger.info("配对码验证成功, 创建用户 uid=%d", uid)
        return uid

    def is_active(self) -> bool:
        if self._current_code is None:
            return False
        return time.time() < self._current_expires

    def get_status(self) -> dict:
        return {
            "active": self.is_active(),
            "locked": time.time() < self._locked_until if self._locked_until > 0 else False,
            "failures": self._failures,
            "timeout_seconds": self._timeout,
            "digits": self._digits,
        }

    def _create_default_user(self) -> int:
        if self._db is None:
            return 1
        try:
            cursor = self._db._get_connection().execute(
                "INSERT INTO users (uid, nickname, display_name, is_admin) VALUES ("
                "(SELECT COALESCE(MAX(uid), 0) + 1 FROM users), '用户', '管理员', 1)"
            )
            self._db._get_connection().commit()
            uid = cursor.lastrowid or 1
            return uid
        except Exception:
            return 1

    def _persist_code(self) -> None:
        if self._db is None:
            return
        try:
            expires = datetime.now(timezone.utc) + timedelta(seconds=self._timeout)
            self._db._get_connection().execute(
                "INSERT INTO auth_pairing_codes (code, expires_at) VALUES (?, ?)",
                (self._current_code, expires.isoformat()),
            )
            self._db._get_connection().commit()
        except Exception:
            pass

    def _mark_code_used(self, code: str) -> None:
        if self._db is None:
            return
        try:
            self._db._get_connection().execute(
                "UPDATE auth_pairing_codes SET used = 1 WHERE code = ?", (code,)
            )
            self._db._get_connection().commit()
        except Exception:
            pass
