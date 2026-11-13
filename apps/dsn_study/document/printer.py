# document/printer.py
# 打印机控制工具 — 基于 pycups (CUPS)（自参考实现移植）

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time

try:
    import cups
    _CUPS_AVAILABLE = True
except ImportError:
    _CUPS_AVAILABLE = False

logger = logging.getLogger("PrinterTool")

# CUPS 后端（cupsfilter）默认以 `lp` 身份运行，无法穿透 0700 的家目录
# （本项目的 .dsn/ 就是 drwx------），直接送原始路径会报
# IPP `invalid-file-access`（0x0403）。故送印前先暂存到全局可读路径。
_STAGE_DIR = "/tmp/dsn-print"

# 手动双面打印的作业状态（记录哪些文件正等着翻面打印背面）
_PRINT_JOBS = "/tmp/dsn-print/jobs.json"

# 翻面指引 —— 对应 Windows 驱动里的「长边翻转」策略
FLIP_HINT = (
    "请把整摞纸**沿长边整体翻面**（像翻书一样，竖直方向翻，纸张上下不要颠倒），"
    "然后按原来的方向重新放进进纸口。"
)


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
    def _stage_for_cups(file_path: str) -> tuple[str, bool]:
        """把待打印文件复制到 CUPS 后端可读的路径。

        :return: (实际要送 CUPS 的路径, 是否为暂存副本)
        """
        try:
            src = os.path.abspath(file_path)
            if not os.path.isfile(src):
                return file_path, False
            # 已经全局可读就不用再拷一份
            mode = os.stat(src).st_mode & 0o777
            if mode & 0o004 and not _path_needs_privilege(src):
                return src, False
            os.makedirs(_STAGE_DIR, mode=0o755, exist_ok=True)
            dst = os.path.join(
                _STAGE_DIR,
                f"{os.path.basename(src)[:120]}.{os.getpid()}.staged",
            )
            shutil.copy2(src, dst)
            os.chmod(dst, 0o644)
            return dst, True
        except Exception as e:  # noqa: BLE001 - 暂存失败不阻断打印
            logger.warning("暂存打印文件失败，改用原始路径: %s", e)
            return file_path, False

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

        staged_path = file_path
        is_staged = False
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

            # 关键：送 CUPS 的必须是 lp 能读到的路径
            staged_path, is_staged = PrinterTool._stage_for_cups(file_path)

            job_id = conn.printFile(printer_name, staged_path, "DSN 打印任务", print_opts)
            logger.info("打印任务已提交: job_id=%d printer=%s path=%s",
                        job_id, printer_name, staged_path)
            return {
                "success": True,
                "job_id": job_id,
                "printer": printer_name,
                "printed_path": staged_path if is_staged else file_path,
            }

        except Exception as e:
            logger.error("打印失败: %s", e)
            return {"success": False, "error": str(e)}
        finally:
            # CUPS 提交时已把文件读进自己的队列，这里可以立刻清掉暂存副本
            if is_staged:
                try:
                    os.unlink(staged_path)
                except OSError:
                    pass

    # ══════════════════════════════════════════════════════════
    # 手动双面打印（单面打印机）
    # ══════════════════════════════════════════════════════════
    @staticmethod
    def pdf_page_count(path: str) -> int:
        """取 PDF 页数。优先 pdfinfo，其次解析 /Count。"""
        try:
            out = subprocess.run(["pdfinfo", path], capture_output=True,
                                 timeout=20)
            if out.returncode == 0:
                m = re.search(rb"Pages:\s+(\d+)",
                              out.stdout or b"")
                if m:
                    return int(m.group(1))
        except Exception:  # noqa: BLE001
            pass
        try:
            with open(path, "rb") as fh:
                data = fh.read()
            m = re.findall(rb"/Count\s+(\d+)", data)
            if m:
                return max(int(x) for x in m)
            return len(re.findall(rb"/Type\s*/Page[^s]", data))
        except OSError:
            return 0

    @staticmethod
    def _load_jobs() -> dict:
        try:
            with open(_PRINT_JOBS, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}

    @staticmethod
    def _save_jobs(jobs: dict) -> None:
        try:
            os.makedirs(os.path.dirname(_PRINT_JOBS), exist_ok=True)
            with open(_PRINT_JOBS, "w", encoding="utf-8") as fh:
                json.dump(jobs, fh, ensure_ascii=False, indent=2)
        except OSError:
            pass

    @staticmethod
    def print_duplex(file_path: str, printer_name: str = None,
                     phase: str = "first", copies: int = 1,
                     options: dict = None, reverse_back: bool = False) -> dict:
        """单面打印机的手动双面打印。

        这台打印机（Canon G3010LAN）没有自动双面单元，驱动也没有
        Windows 上那套「长边翻转」策略。所以双面靠**人手动翻纸**：

            phase="first"   → 打印奇数页（第 1,3,5,… 面）
            phase="second"  → 打印偶数页（第 2,4,6,… 面）

        典型流程：先调 phase="first"，把返回的 next_action 转述给用户，
        用户翻好纸插回去之后，再调一次 phase="second"。

        :param file_path: PDF 路径
        :param printer_name: 打印机名；None 用默认
        :param phase: "first" / "second"
        :param copies: 份数
        :param options: 额外 CUPS 选项
        :param reverse_back: 背面页序反转（出纸顺序与正面相反时用）。
            背面第 1 张纸要拿到的是「正面最后一张纸的背面」，
            所以出纸顺序反了就必须倒着打。默认 False（页序一致）。
        """
        if not _CUPS_AVAILABLE:
            return {"success": False, "error": "pycups 未安装"}
        phase = (phase or "first").strip().lower()
        if phase not in ("first", "second"):
            return {"success": False,
                    "error": "phase 只能是 first（奇数页/正面）或 second（偶数页/背面）"}

        if not os.path.isfile(file_path):
            return {"success": False, "error": f"文件不存在: {file_path}"}

        total = PrinterTool.pdf_page_count(file_path)
        if total <= 0:
            return {"success": False, "error": "无法读取 PDF 页数"}

        odd = [i for i in range(1, total + 1) if i % 2 == 1]
        even = [i for i in range(1, total + 1) if i % 2 == 0]
        if phase == "second" and reverse_back:
            even = list(reversed(even))
        pages = odd if phase == "first" else even

        if not pages:
            msg = ("这份文档只有 1 页，没有背面需要打印。"
                   if phase == "second" else "这份文档没有可打印的正面页。")
            return {"success": True, "phase": phase, "total_pages": total,
                    "printed_pages": "", "skipped": True, "message": msg}

        page_range = ",".join(str(p) for p in pages)
        res = PrinterTool.print_file(file_path, printer_name=printer_name,
                                     copies=copies, page_range=page_range,
                                     options=options)
        if not res.get("success"):
            return res

        jobs = PrinterTool._load_jobs()
        key = os.path.abspath(file_path)
        if phase == "first":
            jobs[key] = {
                "printer": res.get("printer"),
                "total_pages": total,
                "odd_pages": page_range,
                "even_pages": ",".join(str(p) for p in even),
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "state": "awaiting_flip",
            }
        else:
            jobs.pop(key, None)
        PrinterTool._save_jobs(jobs)

        out = {
            "success": True,
            "phase": phase,
            "job_id": res.get("job_id"),
            "printer": res.get("printer"),
            "total_pages": total,
            "printed_pages": page_range,
            "copies": copies,
        }
        if phase == "first":
            out["flip_hint"] = FLIP_HINT
            out["next_action"] = (
                f"已打印正面（奇数页 {page_range}）。"
                f"{FLIP_HINT}"
                f"翻好插回后，调用本工具 phase='second' 打印背面（偶数页）。")
        else:
            out["message"] = "背面（偶数页）已打印完成，双面打印结束。"
        return out

    @staticmethod
    def pending_flip_jobs() -> list[dict]:
        """列出所有等待翻面打印背面的作业。"""
        jobs = PrinterTool._load_jobs()
        out = []
        for path, j in jobs.items():
            out.append({"pdf_path": path, **j})
        return out


def _path_needs_privilege(path: str) -> bool:
    """判断路径上是否有 CUPS 后端（lp）无法穿透的目录。"""
    path = os.path.abspath(path)
    parts = path.split(os.sep)
    for i in range(1, len(parts)):
        d = os.sep + os.path.join(*parts[:i])
        try:
            mode = os.stat(d).st_mode
        except OSError:
            continue
        if not (mode & 0o001):        # 其它用户无 x 权限 → lp 穿不过去
            return True
    return False
