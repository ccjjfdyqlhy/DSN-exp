# skills/builtin/document/tools/scanner.py
# 扫描仪工具 — 封装 document.scanner.ScannerTool

from __future__ import annotations

import logging

logger = logging.getLogger("skill.document")


class ScannerTool:
    """扫描仪控制。AI 通过 <tool>{"skill":"document","tool":"scan",...}</tool> 调用。"""

    def __init__(self):
        from apps.dsn.document.scanner import ScannerTool as _ST
        self._st = _ST
        logger.info("ScannerTool 已就绪")

    def list_scanners(self) -> dict:
        result = self._st.list_scanners()
        count = len(result)
        logger.info("列出扫描仪: %d 台", count)
        return {"success": True, "scanners": result, "count": count}

    def scan(self, resolution: int = 300, mode: str = "Color",
             user_id: int = 0) -> dict:
        from apps.dsn.utils.workspace import get_workspace_manager
        wm = get_workspace_manager()
        output_dir = str(wm.user_uploads_dir(uid=user_id or 1))
        results = self._st.scan(
            resolution=resolution, mode=mode, fmt="png",
            output_dir=output_dir,
        )
        count = len(results)
        logger.info("扫描完成: %d 页 → %s (user_id=%d)",
                     count, output_dir, user_id or 1)
        
        # 生成文件序号列表说明
        file_list = []
        for i, file_info in enumerate(results, 1):
            file_list.append(f"{i}. {file_info['filename']}")
        
        summary = f"共{count}份\n" + "\n".join(file_list)
        
        return {
            "success": True,
            "files": results,
            "count": count,
            "summary": summary
        }
