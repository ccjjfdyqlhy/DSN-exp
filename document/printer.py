# document/printer.py
# 打印机控制工具 — 基于 pycups (CUPS)

from __future__ import annotations

import logging

try:
    import cups
    _CUPS_AVAILABLE = True
except ImportError:
    _CUPS_AVAILABLE = False

logger = logging.getLogger("PrinterTool")


class PrinterTool:
    """打印机控制工具。底层调用 CUPS API。"""

    @staticmethod
    def list_printers() -> list[dict]:
        """返回 [{name, state, state_reason, description}]"""
        if not _CUPS_AVAILABLE:
            return []
        try:
            conn = cups.Connection()
            printers = conn.getPrinters()
            return [
                {
                    "name": name,
                    "state": info.get("printer-state", 0),
                    "state_reason": info.get("printer-state-reasons", ""),
                    "description": info.get("printer-info", ""),
                }
                for name, info in printers.items()
            ]
        except Exception as e:
            logger.error("列出打印机失败: %s", e)
            return []

    @staticmethod
    def print_file(
        file_path: str,
        printer_name: str = None,
        copies: int = 1,
        page_range: str = None,
        options: dict = None,
    ) -> dict:
        """
        使用 CUPS 打印文件。

        :param file_path: 文件路径（PDF/JPG/PNG/TXT 等）
        :param printer_name: 打印机名，为 None 则用第一台
        :param copies: 份数
        :param page_range: 页码范围，如 "1" / "1-3" / "1,3,5"
        :param options: 其他 CUPS 选项
        """
        if not _CUPS_AVAILABLE:
            return {"success": False, "error": "pycups 未安装"}

        try:
            conn = cups.Connection()
            printers = conn.getPrinters()
            if not printers:
                return {"success": False, "error": "未发现打印机"}

            if printer_name is None:
                printer_name = list(printers.keys())[0]

            if printer_name not in printers:
                return {"success": False, "error": f"打印机不存在: {printer_name}"}

            print_opts = options.copy() if options else {}
            if copies > 1:
                print_opts["copies"] = str(copies)
            if page_range:
                print_opts["page-ranges"] = page_range

            job_id = conn.printFile(printer_name, file_path, "DSN 打印任务", print_opts)
            logger.info("打印任务已提交: job_id=%d printer=%s", job_id, printer_name)
            return {"success": True, "job_id": job_id, "printer": printer_name}

        except Exception as e:
            logger.error("打印失败: %s", e)
            return {"success": False, "error": str(e)}
