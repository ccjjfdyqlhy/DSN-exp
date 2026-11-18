# harness/approval/session.py
# 审批放行缓存 —— 「这个人已经批过这个工具了，别再问一遍」。
#
# 场景：用户点了「本会话内始终允许 shell」，如果每次调用都重新弹窗，
# 长任务会变得无法使用。但缓存必须有明确的**作用域**，否则「允许一次」
# 会被误当成「永久允许」—— 那是安全事故。
#
# 作用域语义（策划案 §4.4.3）：
#   once          只这一次，不记缓存
#   session       本会话内该工具都放行
#   tool:<name>   该工具跨会话放行
#   always        该工具永久放行（等价于 tool:<name>，语义上更明确）

from __future__ import annotations

import threading
from typing import Optional

from .base import SCOPE_ALWAYS, SCOPE_ONCE, SCOPE_SESSION, scope_tool


class ApprovalCache:
    """放行缓存。线程安全。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # (session_id, tool) → True 表示本会话内放行
        self._session: set[tuple[str, str]] = set()
        # tool → True 表示跨会话放行
        self._global: set[str] = set()

    # ── 查询 ──────────────────────────────────────────────
    def is_allowed(self, tool: str, *, session_id: str = '',
                   scope: Optional[str] = None) -> bool:
        """这个工具在给定作用域下是否已经放行过。"""
        with self._lock:
            if tool in self._global:
                return True
            if session_id and (session_id, tool) in self._session:
                return True
            return False

    # ── 写入 ──────────────────────────────────────────────
    def remember(self, tool: str, *, session_id: str = '',
                 scope: Optional[str] = None) -> None:
        """按作用域记住一次放行。

        scope='once' 或 None → 不记（一次性放行）。
        scope='session'      → 本会话内放行。
        scope='tool:<name>'  → 该工具跨会话放行。
        scope='always'       → 该工具永久放行。
        """
        if not scope or scope == SCOPE_ONCE:
            return
        with self._lock:
            if scope == SCOPE_SESSION:
                if session_id:
                    self._session.add((session_id, tool))
                return
            if scope == SCOPE_ALWAYS or scope == scope_tool(tool):
                self._global.add(tool)
                return
            # 未知作用域：按最宽松处理会出事，按最保守处理（不记）才安全。
            return

    def forget(self, tool: str, *, session_id: str = '') -> None:
        with self._lock:
            self._global.discard(tool)
            if session_id:
                self._session.discard((session_id, tool))

    def clear(self, *, session_id: str | None = None) -> None:
        with self._lock:
            if session_id is None:
                self._session.clear()
                self._global.clear()
            else:
                for key in [k for k in self._session if k[0] == session_id]:
                    self._session.discard(key)

    def __len__(self) -> int:
        with self._lock:
            return len(self._session) + len(self._global)


__all__ = ['ApprovalCache']
