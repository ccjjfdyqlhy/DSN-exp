# skills/builtin/document/tools/printer.py
# 打印机工具 — 封装 document.printer.PrinterTool

from __future__ import annotations

import logging

logger = logging.getLogger("skill.document")


class PrinterTool:
    """打印机控制。AI 通过 <tool>{"skill":"document","tool":"print_file",...}</tool> 调用。"""

    def __init__(self):
        from apps.dsn.document.printer import PrinterTool as _PT
        self._pt = _PT
        logger.info("PrinterTool 已就绪")

    def list_printers(self) -> dict:
        result = self._pt.list_printers()
        count = len(result)
        logger.info("列出打印机: %d 台", count)
        return {"success": True, "printers": result, "count": count}

    def print_file(self, file_path: str, copies: int = 1,
                   page_range: str = None) -> dict:
        result = self._pt.print_file(
            file_path=file_path, copies=copies, page_range=page_range)
        logger.info("打印: %s (copies=%d, range=%s) → %s",
                     file_path, copies, page_range or "all",
                     "OK" if result.get("success") else result.get("error"))
        return result
