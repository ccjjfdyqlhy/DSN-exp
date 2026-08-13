# auth/pairing.py
# PairingManager — L0 一次性配对码

from __future__ import annotations

import logging
import secrets
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
            str(secrets.randbelow(10)) for _ in range(self._digits)
        )
        self._current_expires = time.time() + self._timeout
        self._failures = 0
        self._locked_until = 0.0
        self._persist_code()
        logger.info("配对码已生成 (过期: %ds)", self._timeout)
        return self._current_code

    def verify(self, code: str, display_name: str = "", is_admin: bool = False) -> Optional[int]:
        """
        验证配对码。
        成功 → 若 display_name 已有对应用户则复用，否则创建新用户。
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

        # [临时做法] 如果 display_name 已有对应用户，复用有聊天记录的那个，删除无记录的重复用户
        if display_name and self._db:
            try:
                conn = self._db._get_connection()
                rows = conn.execute(
                    "SELECT uid FROM users WHERE display_name = ?", (display_name,)
                ).fetchall()
                if rows:
                    uids = [r["uid"] for r in rows]
                    if len(uids) == 1:
                        uid = uids[0]
                    else:
                        uid_with_chat = None
                        uids_to_remove = []
                        for duid in uids:
                            chat_row = conn.execute(
                                "SELECT COUNT(*) AS cnt FROM messages m "
                                "JOIN chats c ON m.chat_id = c.chat_id "
                                "WHERE c.user_id = ?", (duid,)
                            ).fetchone()
                            if chat_row and chat_row["cnt"] > 0:
                                if uid_with_chat is None:
                                    uid_with_chat = duid
                                else:
                                    uids_to_remove.append(duid)
                            else:
                                uids_to_remove.append(duid)
                        if uid_with_chat is None:
                            uid_with_chat = uids[0]
                            uids_to_remove = [u for u in uids if u != uid_with_chat]
                        for ruid in uids_to_remove:
                            try:
                                conn.execute("DELETE FROM users WHERE uid = ?", (ruid,))
                                logger.warning("[临时] 删除无聊天记录的重名用户 uid=%d (display_name=%s)", ruid, display_name)
                            except Exception:
                                logger.warning("Operation failed", exc_info=True)
                        conn.commit()
                        uid = uid_with_chat
                    # 更新复用用户的 display_name 和 is_admin
                    conn.execute(
                        "UPDATE users SET display_name = ?, is_admin = ? WHERE uid = ?",
                        (display_name, 1 if is_admin else 0, uid),
                    )
                    conn.commit()
                    self._mark_code_used(code)
                    logger.info("配对码验证成功, 复用用户 uid=%d (display_name=%s)", uid, display_name)
                    return uid
            except Exception:
                logger.warning("Operation failed", exc_info=True)

        uid = self._create_default_user(display_name, is_admin)
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

    def _create_default_user(self, display_name: str = "", is_admin: bool = False) -> int:
        if self._db is None:
            return 1
        name = display_name or "管理员"
        admin = 1 if is_admin else 0
        try:
            cursor = self._db._get_connection().execute(
                "INSERT INTO users (uid, nickname, display_name, is_admin) VALUES ("
                "(SELECT COALESCE(MAX(uid), 0) + 1 FROM users), '用户', ?, ?)",
                (name, admin),
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
            logger.warning("Connection failed", exc_info=True)

    def _mark_code_used(self, code: str) -> None:
        if self._db is None:
            return
        try:
            self._db._get_connection().execute(
                "UPDATE auth_pairing_codes SET used = 1 WHERE code = ?", (code,)
            )
            self._db._get_connection().commit()
        except Exception:
            logger.warning("Connection failed", exc_info=True)
