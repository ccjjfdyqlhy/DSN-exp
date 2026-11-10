# apps/dsn_study_cli/launcher.py
# 自更新启动器（独立清单）—— 先对齐服务端文件，再原地 exec CLI 主程序。
#
# 与 dsn CLI launcher 的差异（迁移计划 6.5）：
#   - 清单指向 apps/dsn_study_cli/*（dsn 侧下发的是 apps/dsn/CLI/*，
#     复用 dsn 蓝图会让 study 客户端拉到 dsn 的字节 —— 已由 study 自己的
#     /api/update 蓝图修复，见 apps/dsn_study/api/update.py）；
#   - 清单端点支持 Bearer（若客户端配置了 token）。
#
# 仅依赖标准库 + requests；`STUDY_SKIP_UPDATE=1` 跳过更新。

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from urllib.request import urlopen, Request

HERE = Path(__file__).resolve().parent
# <部署根>/apps/dsn_study_cli/launcher.py → 部署根是 parents[1]。
# 注意：dsn 侧 apps/dsn/CLI/launcher.py 深一层，用的是 parents[2]；
# 本文件迁到 apps/dsn_study_cli/ 后必须同步下移一级，否则自更新会把文件
# 同步到部署根之外（~/apps/…），且 exec 的是错误位置的副本。
DEPLOY_ROOT = HERE.parents[1]

UPDATE_TIMEOUT = 8
DOWNLOAD_TIMEOUT = 60


def _repo_rel(path: Path) -> str:
    return path.relative_to(DEPLOY_ROOT).as_posix()


def _fetch_json(base: str, path: str, token: str, timeout: int):
    req = Request(f"{base}{path}")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_bytes(base: str, path: str, token: str, timeout: int) -> bytes:
    req = Request(f"{base}{path}")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def sync_files(base: str, token: str = "") -> list[str]:
    """对齐服务端清单；返回更新的文件列表（相对仓库根）。"""
    manifest = _fetch_json(base, "/api/update/manifest", token, UPDATE_TIMEOUT)
    updated: list[str] = []
    for item in manifest.get("files", []):
        rel, sha = item.get("path", ""), item.get("sha256", "")
        if not rel or not sha:
            continue
        local = DEPLOY_ROOT / rel
        try:
            local_ok = (local.is_file()
                        and hashlib.sha256(local.read_bytes()).hexdigest() == sha)
        except Exception:   # noqa: BLE001
            local_ok = False
        if local_ok:
            continue
        data = _fetch_bytes(base, f"/api/update/file/{rel}", token,
                            DOWNLOAD_TIMEOUT)
        if hashlib.sha256(data).hexdigest() != sha:
            print(f"[update] 校验失败，跳过 {rel}")
            continue
        local.parent.mkdir(parents=True, exist_ok=True)
        tmp = local.with_name(f".{local.name}.tmp.{os.getpid()}")
        tmp.write_bytes(data)
        os.replace(tmp, local)
        updated.append(rel)
        print(f"[update] {rel}")
    return updated


def main(argv=None) -> int:
    base = ""
    token = ""
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--base" in argv:
        base = argv[argv.index("--base") + 1]
    if "--token" in argv:
        token = argv[argv.index("--token") + 1]
    if not base:
        cfg_path = HERE / ".dsn_client.json"
        if cfg_path.is_file():
            try:
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                host = str(cfg.get("backend_host") or "127.0.0.1").replace(
                    "http://", "").replace("https://", "")
                base = f"http://{host}:{int(cfg.get('port') or 5000)}"
                token = str(cfg.get("token") or "")
            except Exception:   # noqa: BLE001
                base = ""

    if base and not os.environ.get("STUDY_SKIP_UPDATE"):
        try:
            changed = sync_files(base, token)
            print(f"[update] 完成（{len(changed)} 个文件更新）"
                  if changed else "[update] 已是最新")
        except Exception as e:   # noqa: BLE001 - 更新失败不阻塞启动
            print(f"[update] 失败（直接启动）: {e}")

    os.chdir(DEPLOY_ROOT)
    argv_rest = [a for a in argv if a not in ("--base", "--token")
                 and a not in (base, token)]
    os.execv(sys.executable,
             [sys.executable, "-m", "apps.dsn_study_cli"] + argv_rest)


if __name__ == "__main__":
    sys.exit(main())


# 防止未使用的 import 警告（time 保留给扩展用）
_ = time
