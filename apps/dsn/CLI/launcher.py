#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# apps/dsn/CLI/launcher.py
# DSN-exp CLI 客户端启动器（自动更新，自包含：仅标准库 + requests）。
#
# 不直接运行客户端代码，而是通过本启动器：
#   1. 读取同目录 .dsn_client.json（或 --host / --port 参数），得到后端地址；
#   2. GET /api/update/manifest → 后端分发的多文件清单（相对路径 + sha256）；
#   3. 与本地 apps/ 下对应文件逐一比对，不一致 → 下载并原子替换；
#   4. 以 `python -m apps.dsn.CLI` 启动客户端，原样透传所有命令行参数。
#
# 目录同构约定：launcher 位于 <部署根>/apps/dsn/CLI/ 下；仓库内直接可用，
# 树莓派等边缘设备只需手动放置本文件，其余文件全部自动拉齐。
#
# 用法：python launcher.py [--host X] [--port N] [--pairing CODE] [--headless]
# 环境变量 DSN_SKIP_UPDATE=1 可跳过更新检查直接启动。

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
DEPLOY_ROOT = HERE.parents[2]        # <部署根>/apps/dsn/CLI/launcher.py → 部署根
CONFIG_FILE = HERE / ".dsn_client.json"
_LEGACY_CONFIG = HERE.parent / "psychoscope" / ".dsn_client.json"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5000

UPDATE_TIMEOUT = 8
DOWNLOAD_TIMEOUT = 60


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _migrate_legacy_config() -> None:
    """旧版客户端配置在 psychoscope/ 下；首次运行搬到新位置（幂等）。"""
    if CONFIG_FILE.exists() or not _LEGACY_CONFIG.exists():
        return
    try:
        CONFIG_FILE.write_bytes(_LEGACY_CONFIG.read_bytes())
        print(f"  [migrate] 旧配置已迁移: {_LEGACY_CONFIG} → {CONFIG_FILE}")
    except Exception:
        pass


def _extract_host_port(argv: list[str]) -> tuple[str | None, int]:
    """从命令行参数中提取 --host / --port（同时支持 '--x v' 与 '--x=v' 形式）。"""
    host: str | None = None
    port: int = DEFAULT_PORT
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--host" and i + 1 < len(argv):
            host = argv[i + 1].strip()
            i += 2
            continue
        if arg.startswith("--host="):
            host = arg.split("=", 1)[1].strip()
        elif arg == "--port" and i + 1 < len(argv):
            try:
                port = int(argv[i + 1])
            except ValueError:
                pass
            i += 2
            continue
        elif arg.startswith("--port="):
            try:
                port = int(arg.split("=", 1)[1])
            except ValueError:
                pass
        i += 1
    return host, port


def _resolve_host(cli_host: str | None, cfg: dict) -> str:
    if cli_host:
        return cli_host
    host = (cfg.get("backend_host") or "").strip()
    if not host:
        return DEFAULT_HOST
    for scheme in ("http://", "https://"):
        if host.startswith(scheme):
            host = host[len(scheme):].split("/")[0]
            break
    return host.split(":")[0].strip() or DEFAULT_HOST


def _sha256_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except Exception:
        return None


def _fetch_manifest(base: str) -> list[dict] | None:
    try:
        resp = requests.get(f"{base}/api/update/manifest", timeout=UPDATE_TIMEOUT)
        if resp.status_code != 200:
            print(f"  [update] 后端更新接口不可用 (HTTP {resp.status_code})")
            return None
        return resp.json().get("files", [])
    except Exception as e:
        print(f"  [update] 无法连接后端更新服务 {base}: {e}")
        return None


def sync_files(base: str) -> list[str]:
    """比对并同步客户端文件（相对部署根），返回本次更新的相对路径列表。"""
    manifest = _fetch_manifest(base)
    if manifest is None:
        return []

    updated = []
    for meta in manifest:
        rel = (meta.get("path") or "").replace("\\", "/")
        remote_sha = meta.get("sha256") or ""
        if not rel or ".." in rel.split("/") or rel.startswith("/") or not remote_sha:
            # 白名单由后端保证；本地再挡一层明显非法项
            continue
        local = DEPLOY_ROOT / rel
        local_sha = _sha256_file(local)
        if local_sha == remote_sha:
            continue

        print(f"  [update] {rel} 检测到更新: 本地 {str(local_sha)[:12] or '缺失'} → 后端 {remote_sha[:12]}")
        try:
            resp = requests.get(f"{base}/api/update/file/{rel}", timeout=DOWNLOAD_TIMEOUT)
            if resp.status_code != 200:
                print(f"  [update] 下载 {rel} 失败 (HTTP {resp.status_code})")
                continue
            data = resp.content
        except Exception as e:
            print(f"  [update] 下载 {rel} 失败: {e}")
            continue

        actual = hashlib.sha256(data).hexdigest()
        if actual != remote_sha:
            print(f"  [update] {rel} 校验失败，跳过本次更新")
            continue

        tmp = local.parent / f".{local.name}.tmp.{os.getpid()}"
        try:
            local.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_bytes(data)
            os.replace(tmp, local)
            updated.append(rel)
            print(f"  [update] {rel} 已同步 ✓")
        except Exception as e:
            print(f"  [update] 写入 {rel} 失败: {e}")
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
    return updated


def main() -> int:
    skip = os.environ.get("DSN_SKIP_UPDATE", "") == "1"
    argv = sys.argv[1:]
    cli_host, cli_port = _extract_host_port(argv)
    _migrate_legacy_config()
    cfg = load_config()

    print("=" * 43)
    print("   DSN-exp  CLI Launcher (auto-update)")
    print("=" * 43)

    host = _resolve_host(cli_host, cfg)
    base = f"http://{host}:{cli_port}"
    cfg_host = cfg.get("backend_host") or host
    print(f"  Backend : {cfg_host}:{cli_port}")
    print(f"  Root    : {DEPLOY_ROOT}")

    if not skip:
        updated = sync_files(base)
        if updated:
            print(f"  [update] 共更新 {len(updated)} 个文件")
        else:
            print("  [update] 客户端已是最新")
    else:
        print("  [update] 已跳过更新检查 (DSN_SKIP_UPDATE=1)")

    print(f"  启动 apps.dsn.CLI ...")
    print("=" * 43)
    try:
        # `-m` 以 cwd 解析包，必须先切到部署根
        os.chdir(DEPLOY_ROOT)
        os.execv(sys.executable, [sys.executable, "-m", "apps.dsn.CLI"] + argv)
    except Exception as e:
        print(f"  [ERROR] 启动失败: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
