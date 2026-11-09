# apps/dsn_study_cli/env.py
# 环境底座 —— 路径常量、日志、可选依赖探测。
#
# 自 apps/dsn/CLI/env.py 收敛而来：study_CLI 不需要 VLC/音乐，
# 可选依赖只留摄像头（opencv）与录音（pvrecorder）；
# 任何缺失都**降级不抛异常** —— 没摄像头的机器照样能文字聊天。

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMP_DIR = HERE / "temp"
LOG_DIR = HERE / "logs"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5000

# ── 可选依赖探测（全部降级，不抛异常） ──

HAS_CAMERA = False
try:
    import cv2 as _cv2  # noqa: F401

    _cv2.setLogLevel(0)   # 静音 opencv 的初始化日志
    HAS_CAMERA = True
except Exception:   # noqa: BLE001
    _cv2 = None

HAS_PVRECORDER = False
try:
    from pvrecorder import PvRecorder as _PvRecorder  # noqa: F401

    HAS_PVRECORDER = True
except Exception:   # noqa: BLE001
    _PvRecorder = None


def setup_logging() -> logging.Logger:
    """初始化日志：控制台 + 文件（logs/cli_<时间戳>.log）。"""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_file = LOG_DIR / f"cli_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        handler = logging.FileHandler(log_file, encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root = logging.getLogger()
        root.addHandler(handler)
        root.setLevel(logging.INFO)
    except Exception:   # noqa: BLE001 - 日志文件建不出来就只用控制台
        pass
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter("%(message)s"))
    logging.getLogger().addHandler(console)
    return logging.getLogger("study_cli")


def ensure_dirs() -> None:
    for d in (TEMP_DIR, LOG_DIR):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception:   # noqa: BLE001
            pass


def env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


def env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default
