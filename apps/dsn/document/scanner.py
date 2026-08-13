# document/scanner.py
# 扫描仪控制工具 — 基于 scanimage (SANE)

from __future__ import annotations

import logging
import os
import re
import subprocess
from pathlib import Path

logger = logging.getLogger("ScannerTool")


class ScannerTool:
    """扫描仪控制工具。底层调用 scanimage (SANE)。"""

    @staticmethod
    def list_scanners() -> list[dict]:
        """返回可用扫描仪列表 [{device, description}]"""
        try:
            result = subprocess.run(
                ["scanimage", "-L"], capture_output=True, text=True, timeout=15
            )
            output = result.stdout
            scanners = []
            for match in re.finditer(r"device `([^']+)'[^\n]*", output):
                device = match.group(1)
                rest = output[match.end():].split("\n")[0] if match.end() < len(output) else ""
                scanners.append({"device": device, "description": rest.strip()})
            return scanners
        except Exception as e:
            logger.error("列出扫描仪失败: %s", e)
            return []

    @staticmethod
    def scan(
        device: str = None,
        output_dir: str = None,
        resolution: int = 300,
        mode: str = "Color",
        fmt: str = "png",
        basename: str = "scan",
    ) -> list[dict]:
        """
        执行扫描，返回 [{filename, filepath, size}]。

        :param device: 扫描仪设备名，为 None 则自动发现第一个
        :param output_dir: 输出目录，默认 workspace/<user>/uploads/
        :param resolution: DPI (150/200/300/600)
        :param mode: Color / Gray / Lineart
        :param fmt: png / jpeg / tiff
        :param basename: 输出文件名前缀
        """
        if device is None:
            scanners = ScannerTool.list_scanners()
            if not scanners:
                raise RuntimeError("未找到扫描仪")
            device = scanners[0]["device"]

        if output_dir is None:
            try:
                from apps.dsn.utils.workspace import get_workspace_manager
                output_dir = str(get_workspace_manager().user_uploads_dir(uid=1))
            except Exception:
                output_dir = "/tmp/dsn_scans"

        os.makedirs(output_dir, exist_ok=True)

        # 查找已有的序号文件，确定起始序号
        existing_files = [f for f in os.listdir(output_dir) if f.startswith(f"{basename}_") and f.endswith(f".{fmt}")]
        existing_numbers = []
        for f in existing_files:
            try:
                # 提取序号部分，格式为 basename_N.ext
                num_part = f[len(basename)+1:-len(fmt)-1]
                if num_part.isdigit():
                    existing_numbers.append(int(num_part))
            except (ValueError, IndexError):
                continue
        
        next_number = max(existing_numbers) + 1 if existing_numbers else 1
        output_file = os.path.join(output_dir, f"{basename}_{next_number}.{fmt}")

        logger.info("开始扫描: device=%s resolution=%d mode=%s → %s", device, resolution, mode, output_file)
        cmd = (
            f"scanimage --device-name '{device}' "
            f"--resolution {resolution} --mode {mode} --format {fmt} "
            f"> '{output_file}'"
        )

        try:
            subprocess.run(cmd, shell=True, check=True, timeout=120)
            size = os.path.getsize(output_file)
            logger.info("扫描完成: %s (%d bytes, %d DPI)", output_file, size, resolution)
            return [{"filename": os.path.basename(output_file), "filepath": output_file, "size": size}]
        except subprocess.CalledProcessError as e:
            logger.error("扫描失败: %s", e)
            raise RuntimeError(f"扫描失败: {e}")
