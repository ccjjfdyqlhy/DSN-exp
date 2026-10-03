# workspace.py
# 最小工作区管理器 — 供 scanprint 等搬运代码落盘用。
#
# 对齐 utils.workspace 契约中被使用的两个方法:
#   user_uploads_dir(uid) / user_documents_dir(uid)
# 目录布局: <WORKSPACE_DIR>/users/<uid>/{uploads,documents}

from __future__ import annotations

import os
import threading

from .config import Config

_lock = threading.Lock()
_manager = None


class WorkspaceManager:
    def __init__(self, workspace_dir: str):
        self._root = os.path.abspath(os.path.expanduser(workspace_dir))

    def _user_dir(self, uid: int, sub: str) -> str:
        path = os.path.join(self._root, "users", str(uid or 1), sub)
        os.makedirs(path, exist_ok=True)
        return path

    def user_uploads_dir(self, uid: int = 1) -> str:
        return self._user_dir(uid, "uploads")

    def user_documents_dir(self, uid: int = 1) -> str:
        return self._user_dir(uid, "documents")

    def __repr__(self):
        return f"<WorkspaceManager root={self._root}>"


def init_workspace_manager(workspace_dir: str = None) -> WorkspaceManager:
    global _manager
    with _lock:
        if _manager is None:
            _manager = WorkspaceManager(workspace_dir or getattr(Config, "WORKSPACE_DIR", ".dsn/workspace"))
    return _manager


def get_workspace_manager() -> WorkspaceManager:
    return _manager if _manager is not None else init_workspace_manager()
