# apps/dsn/CLI/env.py
# CLI 客户端运行环境：可选依赖探测 + 日志 + 路径常量。
#
# 从原 psychoscope/minimal.py 的模块头部（依赖探测/路径/日志）抽出。
# 任何模块都不应反向 import 本包其它模块，保证本文件可作为底座被所有人引用。

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import numpy as np
import requests

HERE = Path(__file__).resolve().parent
TEMP_DIR = HERE / "temp"           # 摄像头试拍等临时产物
LOG_DIR = HERE / "logs"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5000

LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / f"cli_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

# ── 可选依赖探测（全部缺省降级，不抛异常）──

try:
    import vlc
    HAS_AUDIO = True
    # 全局 VLC 实例：哑界面 + 禁用键盘/鼠标抢占
    VLC_INSTANCE = vlc.Instance("--intf", "dummy", "--no-keyboard-events",
                                "--no-mouse-events", "--quiet")
except ImportError:
    vlc = None
    VLC_INSTANCE = None
    HAS_AUDIO = False
    print("[WARN] python-vlc not installed. pip install python-vlc")

try:
    from pvrecorder import PvRecorder
    HAS_PVRECORDER = True
except ImportError:
    PvRecorder = None  # 缺失时保持名字可导入，功能按 HAS_PVRECORDER 降级
    HAS_PVRECORDER = False
    print("[WARN] pvrecorder missing. pip install pvrecorder")

try:
    import cv2
    HAS_CAMERA = True
    # 抑制 OpenCV 摄像头枚举/抓帧时的控制台噪音（DSHOW/MSMF 警告、obsensor 错误刷屏）
    try:
        cv2.setLogLevel(0)  # 0 = LOG_LEVEL_SILENT
    except Exception:
        pass
except ImportError:
    cv2 = None
    HAS_CAMERA = False
    print("[WARN] opencv-python not installed. pip install opencv-python (本地摄像头需要)")


def setup_logging():
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname).1s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    for h in root.handlers[:]:
        root.removeHandler(h)

    fh = logging.FileHandler(str(LOG_FILE), encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    return logging.getLogger("cli")


log = setup_logging()

if HAS_AUDIO:
    log.info("VLC 就绪")
