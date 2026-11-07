# api/update.py
# 客户端自动更新接口 — 向后端(本仓库)分发的 CLI 客户端包提供同步服务。
#
# apps/dsn/CLI/launcher.py 启动流程:
#   1. GET /api/update/manifest        → 分发文件清单（仓库根相对路径 + sha256）
#   2. 与本地文件 sha256 比对
#   3. 不一致 → GET /api/update/file/<path> 下载并原子替换
#   4. 以 `python -m apps.dsn.CLI` 启动客户端
#
# 该接口为公开接口（launcher 在认证之前就要使用），仅放行白名单内的文件。
# 白名单 = CLI 包全部源码 + CLI 的 tracking 运行期 import 闭包（全标准库依赖）。
# 注意：CLI 包新增模块时必须同步登记此处，否则边缘设备拉不到新文件。

import hashlib
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, Response

update_bp = Blueprint("client_update", __name__)

# 分发清单（仓库根相对路径，POSIX 风格）。
# 1) CLI 包自身（apps/dsn/CLI/ 全部源码，含 __init__ / __main__ / launcher）
_CLI_DIR = Path(__file__).resolve().parent.parent / "CLI"
_CLI_FILES = sorted(p.name for p in _CLI_DIR.glob("*.py"))
# 2) tracking 运行期闭包：sensing.py 懒加载 apps.dsn.tracking.audio_listen 时
#    会经 tracking/__init__ 拉起 core → store / media / vision_capture。
#    （vision_observe / webcam / tools 不在闭包内，不分发）
_TRACKING_FILES = [
    "apps/dsn/tracking/__init__.py",
    "apps/dsn/tracking/audio_listen.py",
    "apps/dsn/tracking/core.py",
    "apps/dsn/tracking/media.py",
    "apps/dsn/tracking/store.py",
    "apps/dsn/tracking/vision_capture.py",
]
# 3) 包骨架 __init__（独立部署目录树的根）
_SCAFFOLD_FILES = [
    "apps/__init__.py",
    "apps/dsn/__init__.py",
]

DISTRIBUTED_FILES = sorted(set(_SCAFFOLD_FILES + _TRACKING_FILES
                               + [f"apps/dsn/CLI/{name}" for name in _CLI_FILES]))

# update.py 位于 apps/dsn/api/ 下，仓库根为其上三级
REPO_ROOT = Path(__file__).resolve().parents[3]


def _resolve_safe(rel: str) -> Path | None:
    """把清单内相对路径解析为仓库内绝对路径；越界（目录穿越）返回 None。"""
    if not rel or rel.startswith("/") or "\\" in rel or ".." in Path(rel).parts:
        return None
    path = (REPO_ROOT / rel).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError:
        return None
    return path


def _file_meta(rel: str):
    """返回白名单内文件的 sha256/size 元数据；缺失或路径非法返回 None。"""
    path = _resolve_safe(rel)
    if path is None or not path.is_file():
        return None
    data = path.read_bytes()
    return {"path": rel, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}


@update_bp.route("/api/update/manifest", methods=["GET"])
def update_manifest():
    """返回后端当前分发的客户端文件清单（含 sha256），供 launcher 比对。"""
    files = []
    mtimes = []
    for rel in DISTRIBUTED_FILES:
        meta = _file_meta(rel)
        if meta:
            files.append(meta)
            path = _resolve_safe(rel)
            if path:
                mtimes.append(path.stat().st_mtime)
    version = datetime.fromtimestamp(max(mtimes)).strftime("%Y%m%d_%H%M%S") if mtimes else ""
    return jsonify({"version": version, "files": files})


@update_bp.route("/api/update/file/<path:rel>", methods=["GET"])
def update_file(rel: str):
    """下载指定客户端文件原文。仅允许白名单内的相对路径（防目录穿越）。"""
    path = _resolve_safe(rel)
    if path is None or rel not in DISTRIBUTED_FILES or not path.is_file():
        return jsonify({"error": "Unknown file"}), 404
    return Response(
        path.read_bytes(),
        mimetype="text/plain; charset=utf-8",
        headers={"Cache-Control": "no-cache"},
    )
