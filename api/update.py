# api/update.py
# 客户端自动更新接口 — 向后端(本仓库)分发的 psychoscope/ 客户端文件提供同步服务。
#
# psychoscope/launcher.py 启动流程:
#   1. GET /api/update/manifest        → 各客户端文件的 sha256 清单
#   2. 与本地文件 sha256 比对
#   3. 不一致 → GET /api/update/file/<name> 下载并原子替换
#   4. 启动 minimal.py
#
# 该接口为公开接口（launcher 在认证之前就要使用），仅放行白名单内的文件。

import hashlib
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, Response

update_bp = Blueprint("client_update", __name__)

# 需要向后端客户端分发的文件（相对仓库根目录 psychoscope/ 下）
CLIENT_FILES = ["minimal.py", "launcher.py"]


def _client_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "psychoscope"


def _file_meta(name: str):
    path = _client_dir() / name
    if not path.exists():
        return None
    data = path.read_bytes()
    return {
        "name": name,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
    }


@update_bp.route("/api/update/manifest", methods=["GET"])
def update_manifest():
    """返回后端当前分发的客户端文件清单（含 sha256），供 launcher 比对。"""
    files = []
    mtimes = []
    for name in CLIENT_FILES:
        meta = _file_meta(name)
        if meta:
            files.append(meta)
            mtimes.append((_client_dir() / name).stat().st_mtime)
    version = ""
    if mtimes:
        version = datetime.fromtimestamp(max(mtimes)).strftime("%Y%m%d_%H%M%S")
    return jsonify({"version": version, "files": files})


@update_bp.route("/api/update/file/<name>", methods=["GET"])
def update_file(name):
    """下载指定客户端文件原文。仅允许白名单内的文件名。"""
    if name not in CLIENT_FILES:
        return jsonify({"error": "Unknown file"}), 404
    path = _client_dir() / name
    if not path.exists():
        return jsonify({"error": "File not found"}), 404
    return Response(
        path.read_bytes(),
        mimetype="text/plain; charset=utf-8",
        headers={"Cache-Control": "no-cache"},
    )
