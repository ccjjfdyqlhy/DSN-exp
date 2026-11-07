# apps/dsn/CLI/config.py
# CLI 客户端本地配置：.dsn_client.json（与代码同目录，随 launcher 分发体系走）。
#
# 从原 psychoscope/minimal.py 的 load_config/save_config/prompt_backend_host 抽出。
# 另含一次性迁移：旧 psychoscope/.dsn_client.json → 新位置，避免升级后丢认证/后端地址。

from __future__ import annotations

import json
import shutil

from .env import DEFAULT_HOST, DEFAULT_PORT, HERE

CONFIG_FILE = HERE / ".dsn_client.json"
_LEGACY_CONFIG = HERE.parent / "psychoscope" / ".dsn_client.json"
_MIGRATED = False


def _migrate_legacy_config() -> None:
    """旧版客户端把配置放在 psychoscope/ 下；首次运行时搬到新位置（幂等）。"""
    global _MIGRATED
    if _MIGRATED or CONFIG_FILE.exists() or not _LEGACY_CONFIG.exists():
        _MIGRATED = True
        return
    try:
        shutil.copyfile(_LEGACY_CONFIG, CONFIG_FILE)
        _MIGRATED = True
        print(f"  已迁移旧配置: {_LEGACY_CONFIG} → {CONFIG_FILE}")
    except Exception:
        # 迁移失败不阻断启动，走首次询问流程
        _MIGRATED = True


def load_config() -> dict:
    _migrate_legacy_config()
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_config(cfg: dict):
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def prompt_backend_host(cfg: dict) -> str:
    """首次启动时询问后端地址并持久化到配置文件；端口固定 5000，仅记录主机名。"""
    while True:
        choice = input("  Backend address (default 127.0.0.1): ").strip()
        if not choice:
            host = DEFAULT_HOST
        else:
            for scheme in ("http://", "https://"):
                if choice.startswith(scheme):
                    choice = choice[len(scheme):].split("/")[0]
                    break
            host = choice.split(":")[0].strip()
        if not host:
            continue
        cfg["backend_host"] = host
        save_config(cfg)
        print(f"  Backend address saved: {host}:{DEFAULT_PORT}")
        return host
