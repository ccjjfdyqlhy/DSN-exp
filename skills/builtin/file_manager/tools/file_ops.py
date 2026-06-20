# skills/builtin/file_manager/tools/file_ops.py
# 文件操作工具

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("skill.file_manager")


class FileOpsTool:
    """文件操作工具"""

    def __init__(self, config: dict[str, Any] = None):
        self.config = config or {}
        # 默认 base_dir 指向工作区根目录
        default = self._default_base_dir()
        self.base_dir = Path(self.config.get("base_dir", str(default)))

    @staticmethod
    def _default_base_dir() -> Path:
        try:
            from workspace import get_workspace_manager
            return get_workspace_manager().root
        except Exception:
            return Path(__file__).parent.parent.parent.parent.parent

    def _safe_path(self, path: str) -> Path:
        p = Path(path)
        if p.is_absolute():
            return p
        return (self.base_dir / path).resolve()

    def read_file(self, path: str) -> dict[str, Any]:
        try:
            p = self._safe_path(path)
            if not p.exists():
                return {"success": False, "error": f"文件不存在: {path}"}
            if not p.is_file():
                return {"success": False, "error": f"不是文件: {path}"}
            size = p.stat().st_size
            if size > 1024 * 1024:  # 1MB limit
                return {"success": False, "error": f"文件过大 ({size} bytes), 超过1MB限制"}
            content = p.read_text(encoding='utf-8-sig')
            return {
                "success": True,
                "path": str(p),
                "size": size,
                "content": content,
            }
        except PermissionError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            logger.exception("读取文件失败: %s", path)
            return {"success": False, "error": str(e)}

    def list_dir(self, path: str = ".") -> dict[str, Any]:
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
                items.append({
                    "name": item.name,
                    "type": item_type,
                    "size": size,
                })

            return {
                "success": True,
                "path": str(p),
                "items": items,
                "count": len(items),
            }
        except PermissionError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            logger.exception("列出目录失败: %s", path)
            return {"success": False, "error": str(e)}

    def write_file(self, path: str, content: str) -> dict[str, Any]:
        try:
            p = self._safe_path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding='utf-8-sig')
            return {
                "success": True,
                "path": str(p),
                "size": len(content.encode("utf-8")),
            }
        except PermissionError as e:
            return {"success": False, "error": str(e)}
        except Exception as e:
            logger.exception("写入文件失败: %s", path)
            return {"success": False, "error": str(e)}
