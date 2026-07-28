import logging
from pathlib import Path
from typing import Any

from config import Config

logger = logging.getLogger("skill.file_manager")


class FsExploreTool:
    """文件系统探索工具 — 默认 ~，只读。每次操作后自动返回当前工作目录的绝对路径。"""

    def __init__(self, config: dict[str, Any] = None):
        self.config = config or {}
        self.base_dir = Path(self.config.get("base_dir", str(Path.home())))

    @staticmethod
    def _cwd() -> str:
        return str(Path.cwd().resolve())

    def _safe_path(self, path: str) -> Path:
        p = Path(path)
        if p.is_absolute():
            return p
        return (self.base_dir / p).resolve()

    def explore_fs(self, tool: str, path: str = ".", **kwargs) -> dict[str, Any]:
        if tool == "list_dir":
            return self._list_dir(path)
        elif tool == "read_file":
            return self._read_file(path)
        elif tool == "pwd":
            return self._pwd()
        return {"success": False, "error": f"未知子命令: {tool}", "cwd": self._cwd()}

    def _pwd(self) -> dict[str, Any]:
        return {"success": True, "cwd": self._cwd()}

    def _read_file(self, path: str) -> dict[str, Any]:
        try:
            p = self._safe_path(path)
            if not p.exists():
                return {"success": False, "error": f"文件不存在: {path}", "cwd": self._cwd()}
            if not p.is_file():
                return {"success": False, "error": f"不是文件: {path}", "cwd": self._cwd()}
            size = p.stat().st_size
            max_bytes = Config.FILE_READ_MAX_SIZE_MB * 1024 * 1024
            if size > max_bytes:
                return {
                    "success": False,
                    "error": f"文件过大 ({size} bytes), 超过{Config.FILE_READ_MAX_SIZE_MB}MB限制",
                    "cwd": self._cwd(),
                }
            content = p.read_text(encoding='utf-8-sig')
            return {"success": True, "path": str(p), "size": size, "content": content, "cwd": self._cwd()}
        except PermissionError as e:
            return {"success": False, "error": str(e), "cwd": self._cwd()}
        except Exception as e:
            logger.exception("读取文件失败: %s", path)
            return {"success": False, "error": str(e), "cwd": self._cwd()}

    def _list_dir(self, path: str = ".") -> dict[str, Any]:
        try:
            p = self._safe_path(path)
            if not p.exists():
                return {"success": False, "error": f"目录不存在: {path}", "cwd": self._cwd()}
            if not p.is_dir():
                return {"success": False, "error": f"不是目录: {path}", "cwd": self._cwd()}
            items = []
            for item in sorted(p.iterdir()):
                item_type = "dir" if item.is_dir() else "file"
                size = item.stat().st_size if item.is_file() else 0
                items.append({"name": item.name, "type": item_type, "size": size})
            return {"success": True, "path": str(p), "items": items, "count": len(items), "cwd": self._cwd()}
        except PermissionError as e:
            return {"success": False, "error": str(e), "cwd": self._cwd()}
        except Exception as e:
            logger.exception("列出目录失败: %s", path)
            return {"success": False, "error": str(e), "cwd": self._cwd()}
