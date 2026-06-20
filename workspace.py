# workspace.py
# 工作区管理器 — 全局 AI 工作区单例

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger("WorkspaceManager")


class WorkspaceManager:
    """
    全局工作区管理器。

    插件/技能只需注册子目录名，自动映射到 workspace/<user>/<name>/。
    没有用户上下文的组件使用 workspace/<name>/（全局共享）。

    用法:
        wm = get_workspace_manager()
        wm.register_subdir("notebook")
        path = wm.user_subdir(uid, "notebook")  # → workspace/Darkstar/notebook/
    """

    def __init__(self):
        self._root: Path | None = None
        self._db = None
        self._subdirs: dict[str, bool] = {}  # name → auto_create

    # ── 初始化 ──

    def init(self, db=None, workspace_dir: str | None = None) -> None:
        """初始化工作区根目录（启动时调用）"""
        if db:
            self._db = db
        raw = workspace_dir or ".dsn/workspace"
        p = Path(raw)
        if not p.is_absolute():
            p = Path(__file__).parent / p
        self._root = p.resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        logger.info("工作区根目录: %s", self._root)

    @property
    def root(self) -> Path:
        if self._root is None:
            raise RuntimeError("WorkspaceManager 未初始化，请先调用 init()")
        return self._root

    # ── 子目录注册 ──

    def register_subdir(self, name: str, auto_create: bool = True) -> None:
        """
        注册一个子目录名。
        插件/技能在初始化时调用此方法声明需要的文件夹。
        之后通过 user_subdir(uid, name) 获取路径。
        """
        self._subdirs[name] = auto_create
        logger.debug("工作区注册子目录: %s (auto_create=%s)", name, auto_create)

    # ── 目录解析 ──

    def user_subdir(self, uid: int, name: str, display_name: str = "") -> Path:
        """返回 workspace/<user>/<name>/，用户隔离。"""
        if name not in self._subdirs:
            self.register_subdir(name)
        d = self._user_dir(uid, display_name) / name
        if self._subdirs.get(name):
            d.mkdir(parents=True, exist_ok=True)
        return d

    def root_subdir(self, name: str) -> Path:
        """返回 workspace/<name>/（全局共享，无用户隔离）。"""
        if name not in self._subdirs:
            self.register_subdir(name)
        d = self.root / name
        if self._subdirs.get(name):
            d.mkdir(parents=True, exist_ok=True)
        return d

    # ── 便捷别名（向后兼容，内部委托给 user_subdir）──

    def user_dir(self, uid: int = 0, display_name: str = "") -> Path:
        """返回用户根目录 workspace/<user>/"""
        return self._user_dir(uid, display_name)

    def user_repos_dir(self, uid: int = 0, display_name: str = "") -> Path:
        return self.user_subdir(uid, "repos", display_name)

    def user_notebook_dir(self, uid: int = 0, display_name: str = "") -> Path:
        return self.user_subdir(uid, "notebook", display_name)

    def user_uploads_dir(self, uid: int = 0, display_name: str = "") -> Path:
        return self.user_subdir(uid, "uploads", display_name)

    def user_projects_dir(self, uid: int = 0, display_name: str = "") -> Path:
        return self.user_subdir(uid, "projects", display_name)

    def user_documents_dir(self, uid: int = 0, display_name: str = "") -> Path:
        return self.user_subdir(uid, "documents", display_name)

    # ── 内部 ──

    def _user_dir(self, uid: int, display_name: str) -> Path:
        name = self._resolve_username(uid, display_name)
        d = self.root / name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def resolve(self, subpath: str, uid: int = 0) -> Path:
        """
        将路径解析为绝对路径。
        如果 subpath 是绝对路径，原样返回（不限制全局访问）。
        如果是相对路径，锚定到 user_dir(uid)。
        """
        p = Path(subpath)
        if p.is_absolute():
            return p
        if uid:
            return self._user_dir(uid, "") / subpath
        return self.root / subpath

    def _resolve_username(self, uid: int, display_name: str) -> str:
        if display_name:
            return self._sanitize_name(display_name)
        if uid and self._db is not None:
            try:
                from auth.auth_manager import AuthManager
                user = AuthManager(self._db).get_user(uid)
                name = user.get("display_name") or user.get("nickname", "")
                if name:
                    return self._sanitize_name(name)
            except Exception:
                pass
        return f"user_{uid}" if uid else "default"

    @staticmethod
    def _sanitize_name(name: str) -> str:
        name = re.sub(r'[^\w\u4e00-\u9fff\-]', '_', name)
        return name or "default"


# ── 全局单例访问 ──

_workspace_manager: WorkspaceManager | None = None


def get_workspace_manager() -> WorkspaceManager:
    global _workspace_manager
    if _workspace_manager is None:
        _workspace_manager = WorkspaceManager()
    return _workspace_manager


def init_workspace_manager(db=None, workspace_dir: str | None = None) -> WorkspaceManager:
    wm = get_workspace_manager()
    wm.init(db=db, workspace_dir=workspace_dir)
    return wm
