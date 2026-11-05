# apps/dsn_study/api/obsidian.py
# Obsidian 知识库控制 API。
#
#   GET  /api/obsidian/status  MCP 连接状态 + 已接入的工具 + vault 信息
#   POST /api/obsidian/index   触发知识点库索引（把知识图谱写成 Obsidian 笔记）

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request, g

logger = logging.getLogger("ObsidianAPI")

obsidian_bp = Blueprint("obsidian_api", __name__)

_mcp = None
_skills = None
_auth_manager = None


def init_obsidian_api(mcp_bridge, skill_registry, auth_manager):
    global _mcp, _skills, _auth_manager
    _mcp = mcp_bridge
    _skills = skill_registry
    _auth_manager = auth_manager


@obsidian_bp.before_request
def _require_auth():
    if not _auth_manager:
        return jsonify({"error": "Auth unavailable"}), 503
    user = _auth_manager.authenticate(request)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    g.user = user


@obsidian_bp.route("/api/obsidian/status", methods=["GET"])
def obsidian_status():
    """Obsidian / MCP 状态。"""
    from apps.dsn_study.config import Config
    info = {
        "vault_id": getattr(Config, "OBSIDIAN_VAULT_ID", "study"),
        "vault_path": getattr(Config, "OBSIDIAN_VAULT_PATH", ""),
        "kp_folder": getattr(Config, "OBSIDIAN_KP_FOLDER", "知识点库"),
        "note_folder": getattr(Config, "OBSIDIAN_NOTE_FOLDER", "学习笔记"),
        "mcp": _mcp.status() if _mcp is not None else {"enabled": False},
    }
    if _skills is not None:
        try:
            info["skill_tools"] = [
                k for k in _skills.list_active_tools()
                if k.startswith("obsidian_notes.")]
        except Exception:
            pass
    return jsonify(info)


@obsidian_bp.route("/api/obsidian/index", methods=["POST"])
def obsidian_index():
    """触发知识点库索引（同步执行；数量大时可能耗时数秒）。"""
    if _skills is None:
        return jsonify({"error": "Obsidian 技能未初始化"}), 503
    data = request.get_json(silent=True) or {}
    try:
        subject = (data.get("subject") or "").strip()
        limit = int(data.get("limit", 50))
        overwrite = bool(data.get("overwrite", False))
    except (TypeError, ValueError):
        return jsonify({"error": "参数不合法"}), 400

    insts = _skills.get_tool_instances("obsidian_notes")
    if not insts:
        return jsonify({"error": "Obsidian 技能未加载"}), 503
    tool = insts[0]

    import asyncio
    try:
        result = asyncio.run(tool.index_knowledge_points(
            subject=subject, limit=limit, overwrite=overwrite))
    except Exception as e:
        logger.warning("Obsidian 索引失败: %s", e, exc_info=True)
        return jsonify({"error": str(e)}), 500
    return jsonify(result)
