# document/__init__.py
# Document 子系统 — 打印机/扫描仪控制 + OCR/HMD 文档处理

from .scanner import ScannerTool
from .printer import PrinterTool
from .hmd import HmdClient
from .doc_processor import DocProcessor

__all__ = [
    "ScannerTool",
    "PrinterTool",
    "HmdClient",
    "DocProcessor",
]
