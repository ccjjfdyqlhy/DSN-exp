import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("skill.file_manager")


class FsExploreTool:
    """文件系统探索工具 — 默认 ~，只读。顶层方法由 skill.yaml 中 tool name 指定。"""

    def __init__(self, config: dict[str, Any] = None):
        self.config = config or {}
        self.base_dir = Path(self.config.get("base_dir", str(Path.home())))

    def _safe_path(self, path: str) -> Path:
        p = Path(path)
        if p.is_absolute():
            return p
        return (self.base_dir / p).resolve()

    # ── 顶层调度入口（tool name = explore_fs）──
    def explore_fs(self, tool: str, path: str = ".", **kwargs) -> dict[str, Any]:
        if tool == "list_dir":
            return self._list_dir(path)
        elif tool == "read_file":
            return self._read_file(path)
        return {"success": False, "error": f"未知子命令: {tool}"}

    def _read_file(self, path: str) -> dict[str, Any]:
        try:
            p = self._safe_path(path)
            if not p.exists():
                return {"success": False, "error": f"文件不存在: {path}"}
            if not p.is_file():
                return {"success": False, "error": f"不是文件: {path}"}
            size = p.stat().st_size
            if size > 1024 * 1024:
                return {"success": False, "error": f"文件过大 ({size} bytes), 超过1MB限制"}
            content = p.read_text(encoding='utf-8-sig')
            return {"success": True, "path": str(p), "size": size, "content": content}
        except PermissionError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            logger.exception("读取文件失败: %s", path)
            return {"success": False, "error": str(e)}

    def _list_dir(self, path: str = ".") -> dict[str, Any]:
        try:
            p = self._safe_path(path)
            if not p.exists():
                return {"success": False, "error": f"目录不存在: {path}"}
            if not p.is_dir():
                return {"success": False, "error": f"不是目录: {path}"}
            items = []
            for item in sorted(p.iterdir()):
                item_type = "dir" if item.is_dir() else "file"
                size = item.stat().st_size if item.is_file() else 0
                items.append({"name": item.name, "type": item_type, "size": size})
            return {"success": True, "path": str(p), "items": items, "count": len(items)}
        except PermissionError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            logger.exception("列出目录失败: %s", path)
            return {"success": False, "error": str(e)}
