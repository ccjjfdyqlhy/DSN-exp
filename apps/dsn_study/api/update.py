# apps/dsn_study/api/update.py
# study_CLI 自更新分发端点（迁移计划阶段 6.5）。
#
# 为什么不复用 apps.dsn.api.update：那份蓝图的下发清单指向 apps/dsn/CLI/*，
# study 客户端会拉到 **dsn 的字节**。本蓝图的白名单只认
# apps/dsn_study_cli/*（顶层 .py），加两份部署骨架。
#
# 鉴权：dsn 的 update 路由完全无鉴权；study 版在服务端配置了
# DSN_STUDY_TOKEN 时要求 Bearer（launcher 会从 .dsn_client.json 带 token），
# 未配置 token 时与 dsn 行为一致放行 —— 至少「清单严格受限」这一底线永远成立。

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from flask import Blueprint, jsonify, request

update_bp = Blueprint("study_client_update", __name__)

REPO_ROOT = Path(__file__).resolve().parents[3]     # apps/dsn_study/api/ → 仓库根
CLI_DIR = REPO_ROOT / "apps" / "dsn_study_cli"

# 分发清单：CLI 目录全部 .py + 部署目录树骨架
_DISTRIBUTED = sorted(
    [f"apps/dsn_study_cli/{p.name}" for p in CLI_DIR.glob("*.py")]
    + ["apps/__init__.py", "apps/dsn_study/__init__.py"]
) if CLI_DIR.is_dir() else ["apps/__init__.py", "apps/dsn_study/__init__.py"]

_TOKEN = None


def init_update_api(token: str = ""):
    """注入鉴权 token（boot.py 传入 Config.DSN_STUDY_TOKEN）。"""
    global _TOKEN
    _TOKEN = (token or "").strip()


def _auth_ok() -> bool:
    if not _TOKEN:
        return True    # 服务端未启用 token → 与 dsn 行为一致放行
    header = request.headers.get("Authorization", "")
    return header == f"Bearer {_TOKEN}"


def _resolve_safe(rel: str) -> Path | None:
    """防目录穿越：拒绝绝对路径 / 反斜杠 / .. 段；必须落在白名单。"""
    if not rel or rel.startswith("/") or "\\" in rel or ".." in rel.split("/"):
        return None
    if rel not in _DISTRIBUTED:
        return None
    p = (REPO_ROOT / rel).resolve()
    try:
        p.relative_to(REPO_ROOT.resolve())
    except ValueError:
        return None
    return p


@update_bp.route("/api/update/manifest", methods=["GET"])
def update_manifest():
    if not _auth_ok():
        return jsonify({"error": "Unauthorized"}), 401
    files = []
    latest = 0.0
    for rel in _DISTRIBUTED:
        p = REPO_ROOT / rel
        if not p.is_file():
            continue
        data = p.read_bytes()
        latest = max(latest, p.stat().st_mtime)
        files.append({
            "path": rel,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        })
    version = time_safe_version(latest)
    return jsonify({"version": version, "files": files})


def time_safe_version(mtime: float) -> str:
    import time as _time
    return _time.strftime("%Y%m%d_%H%M%S", _time.localtime(mtime))


@update_bp.route("/api/update/file/<path:rel>", methods=["GET"])
def update_file(rel: str):
    if not _auth_ok():
        return jsonify({"error": "Unauthorized"}), 401
    p = _resolve_safe(rel)
    if p is None or not p.is_file():
        return jsonify({"error": "Unknown file"}), 404
    return p.read_text(encoding="utf-8", errors="replace"), 200, {
        "Content-Type": "text/plain; charset=utf-8"}
