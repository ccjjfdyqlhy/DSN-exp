# auth.py
# 本地单用户认证垫片。
#
# dsn_study 是单机学习应用，不移植 apps.dsn 的完整多用户认证栈；
# 但搬运过来的 api 蓝图（scan/plan/study_timetable）依赖
# auth_manager.authenticate(request) -> {"uid": ...} 契约。
# 默认放行到固定本地用户（uid=1）；若设置了 DSN_STUDY_TOKEN，
# 则要求请求携带匹配的 Authorization: Bearer <token>。

from __future__ import annotations

import os
from typing import Optional


class LocalAuthManager:
    """单用户本地认证。authenticate(request) 永远返回本地用户或 None。"""

    LOCAL_UID = 1

    def __init__(self, token: Optional[str] = None):
        self.token = token or os.environ.get("DSN_STUDY_TOKEN", "")

    def authenticate(self, request) -> Optional[dict]:
        if self.token:
            header = request.headers.get("Authorization", "")
            if header != f"Bearer {self.token}":
                return None
        return {"uid": self.LOCAL_UID, "username": "local"}

    def __repr__(self):
        return "<LocalAuthManager protected=" + str(bool(self.token)) + ">"
