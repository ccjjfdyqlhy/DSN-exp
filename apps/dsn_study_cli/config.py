# apps/dsn_study_cli/config.py
# 客户端配置 —— .dsn_client.json（JSON 直读直写）。
#
# 字段：backend_host / port / token / uid / display_name / chat_id /
#       mic_device_index / camera_map。
# token 即服务端的 DSN_STUDY_TOKEN（Bearer）；未设 token 时服务端
# LocalAuthManager 全放行到 uid=1，客户端也无需头。

from __future__ import annotations

import json
import threading
from pathlib import Path

from apps.dsn_study_cli.env import HERE

CONFIG_FILE = HERE / ".dsn_client.json"

_LOCK = threading.Lock()

_DEFAULTS = {
    "backend_host": "",
    "port": 5000,
    "token": "",
    "uid": 1,
    "display_name": "study-cli",
    "chat_id": 0,
    "mic_device_index": -1,
    # 麦克风按**名字**选（子串匹配）——PipeWire 设备序号会随 USB 插拔漂移。
    # 空字符串表示不按名字选，退回 mic_device_index。
    "mic_device_name": "",
    # 显式钉住摄像头逻辑名 → cv2 设备索引（避免枚举顺序漂移）。
    # 例：{"doc": 2} 表示「文档摄像头」固定用 /dev/video2。
    "camera_map": {},
}


def load_config() -> dict:
    with _LOCK:
        cfg = dict(_DEFAULTS)
        if CONFIG_FILE.is_file():
            try:
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    cfg.update(data)
            except Exception:   # noqa: BLE001 - 坏文件当无配置
                pass
        return cfg


def save_config(cfg: dict) -> None:
    with _LOCK:
        try:
            CONFIG_FILE.write_text(
                json.dumps(cfg, ensure_ascii=False, indent=2),
                encoding="utf-8")
        except Exception:   # noqa: BLE001
            pass


def backend_base(cfg: dict) -> str:
    """服务端 base URL（剥掉可能误写的 scheme）。"""
    host = str(cfg.get("backend_host") or "127.0.0.1")
    host = host.replace("http://", "").replace("https://", "").rstrip("/")
    port = int(cfg.get("port") or 5000)
    return f"http://{host}:{port}"
