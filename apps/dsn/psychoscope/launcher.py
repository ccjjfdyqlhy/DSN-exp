#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# psychoscope/launcher.py
# DSN-exp minimal 客户端启动器（自动更新）
#
# 不再直接运行 minimal.py，而是通过本启动器：
#   1. 读取同目录 .dsn_client.json，得到对应的 DSN-exp 后端地址；
#   2. 请求后端 /api/update/manifest，与本地 minimal.py / launcher.py 的 sha256 比对；
#   3. 后端版本不同 → 下载并用原子写入替换本地文件；
#   4. 启动 minimal.py，原样透传所有命令行参数。
#
# 用法：python launcher.py [minimal.py 的全部参数，如 --host / --port / --pairing]
# 环境变量 DSN_SKIP_UPDATE=1 可跳过更新检查直接启动。

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
CONFIG_FILE = HERE / ".dsn_client.json"
MINIMAL_FILE = HERE / "minimal.py"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5000

# 需要与后端保持同步的客户端文件
CLIENT_FILES = ["minimal.py", "launcher.py"]

UPDATE_TIMEOUT = 8
DOWNLOAD_TIMEOUT = 60


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


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
    """比对并同步客户端文件，返回本次更新的文件名列表。"""
    manifest = _fetch_manifest(base)
    if manifest is None:
        return []

    updated = []
    for meta in manifest:
        name = meta.get("name")
        if name not in CLIENT_FILES or not meta.get("sha256"):
            continue
        remote_sha = meta["sha256"]
        local = HERE / name
        local_sha = _sha256_file(local)
        if local_sha == remote_sha:
            continue

        print(f"  [update] {name} 检测到更新: 本地 {str(local_sha)[:12] or '缺失'} → 后端 {remote_sha[:12]}")
        try:
            resp = requests.get(f"{base}/api/update/file/{name}", timeout=DOWNLOAD_TIMEOUT)
            if resp.status_code != 200:
                print(f"  [update] 下载 {name} 失败 (HTTP {resp.status_code})")
                continue
            data = resp.content
        except Exception as e:
            print(f"  [update] 下载 {name} 失败: {e}")
            continue

        actual = hashlib.sha256(data).hexdigest()
        if actual != remote_sha:
            print(f"  [update] {name} 校验失败，跳过本次更新")
            continue

        tmp = HERE / f".{name}.tmp.{os.getpid()}"
        try:
            tmp.write_bytes(data)
            os.replace(tmp, local)
            updated.append(name)
            print(f"  [update] {name} 已同步 ✓")
        except Exception as e:
            print(f"  [update] 写入 {name} 失败: {e}")
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
    return updated


def main() -> int:
    skip = os.environ.get("DSN_SKIP_UPDATE", "") == "1"
    argv = sys.argv[1:]
    cli_host, cli_port = _extract_host_port(argv)
    cfg = load_config()

    print("=" * 43)
    print("   DSN-exp  Minimal Launcher (auto-update)")
    print("=" * 43)

    host = _resolve_host(cli_host, cfg)
    base = f"http://{host}:{cli_port}"
    cfg_host = cfg.get("backend_host") or host
    print(f"  Backend : {cfg_host}:{cli_port}")

    if not MINIMAL_FILE.exists():
        print(f"  [ERROR] 未找到 {MINIMAL_FILE.name}，无法启动")
        return 1

    if not skip:
        updated = sync_files(base)
        if updated:
            print(f"  [update] 共更新 {len(updated)} 个文件")
        else:
            print("  [update] 客户端已是最新")
    else:
        print("  [update] 已跳过更新检查 (DSN_SKIP_UPDATE=1)")

    print(f"  启动 {MINIMAL_FILE.name} ...")
    print("=" * 43)
    try:
        os.execv(sys.executable, [sys.executable, str(MINIMAL_FILE)] + argv)
    except Exception as e:
        print(f"  [ERROR] 启动失败: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
