# workspace.py
# 最小工作区管理器 — 供 scanprint 等搬运代码落盘用。
#
# 对齐 utils.workspace 契约中被使用的两个方法:
#   user_uploads_dir(uid) / user_documents_dir(uid)
# 目录布局: <WORKSPACE_DIR>/users/<uid>/{uploads,documents}

from __future__ import annotations

import os
import threading
from pathlib import Path

from .config import Config

_lock = threading.Lock()
_manager = None


class WorkspaceManager:
    def __init__(self, workspace_dir: str):
        self._root = os.path.abspath(os.path.expanduser(workspace_dir))
        self._subdirs: dict[str, bool] = {}
        os.makedirs(self._root, exist_ok=True)

    def _user_dir(self, uid: int, sub: str) -> str:
        path = os.path.join(self._root, "users", str(uid or 1), sub)
        os.makedirs(path, exist_ok=True)
        return path

    def user_uploads_dir(self, uid: int = 1) -> str:
        return self._user_dir(uid, "uploads")

    def user_documents_dir(self, uid: int = 1) -> str:
        return self._user_dir(uid, "documents")

    # ── 契约扩展：对齐参考实现 utils.workspace 的 user_subdir / register_subdir ──
    # 供 skills/builtin/question_print（试卷 PDF 落盘）等搬运代码使用。

    def register_subdir(self, name: str, auto_create: bool = True) -> None:
        """声明一个子目录名（幂等）。"""
        self._subdirs[name] = auto_create

    def user_subdir(self, uid: int, name: str, display_name: str = "") -> Path:
        """返回 <root>/users/<uid>/<name>/，用户隔离（对齐参考实现契约）。"""
        self.register_subdir(name)
        return Path(self._user_dir(uid, name))

    def root_subdir(self, name: str) -> Path:
        """返回 <root>/<name>/（全局共享，无用户隔离）。"""
        self.register_subdir(name)
        path = Path(self._root) / name
        path.mkdir(parents=True, exist_ok=True)
        return path

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
