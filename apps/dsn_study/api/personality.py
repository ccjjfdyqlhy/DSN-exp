# apps/dsn_study/api/personality.py
# 人格系统 API（阶段 2）—— 复用 harness/personality（PEV3）。
#
# 路由形状与 apps/dsn 的 /api/personality/* **保持一致**，
# 这样既有的 dsn 客户端（CLI 的 _verify_api_key 会打 /api/personality/status）
# 和运维脚本可以直接复用。

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request, g

logger = logging.getLogger("PersonalityAPI")

personality_bp = Blueprint("personality_api", __name__)

_personality = None
_auth_manager = None


def init_personality_api(personality, auth_manager):
    """注入依赖（boot.py 启动时调用）。"""
    global _personality, _auth_manager
    _personality = personality
    _auth_manager = auth_manager
    return personality_bp


@personality_bp.before_request
def _require_auth():
    if _auth_manager is None:
        return jsonify({"error": "Auth unavailable"}), 503
    user = _auth_manager.authenticate(request)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    g.user = user


def _uid() -> int:
    return int(g.user.get("uid", 0) or 1)


@personality_bp.route("/api/personality/status", methods=["GET"])
def personality_status():
    """人格快照：情绪、好感度、特质标签、证据量。"""
    if _personality is None:
        return jsonify({"error": "Personality system not available"}), 503
    try:
        return jsonify(_personality.get_personality_status(_uid()))
    except Exception as exc:
        logger.warning("人格状态查询失败", exc_info=True)
        return jsonify({"error": "查询失败: %s" % exc}), 500


@personality_bp.route("/api/personality/current", methods=["GET"])
def personality_current():
    """当前人格全量状态（含完整 50 维向量）。"""
    if _personality is None:
        return jsonify({"error": "Personality system not available"}), 503
    try:
        return jsonify(_personality.get_personality_full(_uid()))
    except Exception as exc:
        logger.warning("人格全量查询失败", exc_info=True)
        return jsonify({"error": "查询失败: %s" % exc}), 500


@personality_bp.route("/api/personality/list", methods=["GET"])
def personality_list():
    """可用角色卡清单。"""
    if _personality is None:
        return jsonify({"error": "Personality system not available"}), 503
    try:
        return jsonify({"cards": _personality.list_cards()})
    except Exception as exc:
        logger.warning("角色卡清单查询失败", exc_info=True)
        return jsonify({"error": "查询失败: %s" % exc}), 500


@personality_bp.route("/api/personality/switch", methods=["POST"])
def personality_switch():
    """切换当前用户绑定的角色卡。"""
    if _personality is None:
        return jsonify({"error": "Personality system not available"}), 503
    data = request.get_json(silent=True) or {}
    card_id = data.get("card_id")
    if not card_id:
        return jsonify({"error": "Missing card_id"}), 400
    try:
        ok = _personality.bind_user_card(_uid(), card_id)
        return jsonify({"success": bool(ok), "card_id": card_id})
    except Exception as exc:
        logger.warning("角色卡切换失败", exc_info=True)
        return jsonify({"error": "切换失败: %s" % exc}), 500


@personality_bp.route("/api/personality/prompt", methods=["GET"])
def personality_prompt():
    """当前注入 system prompt 的人格段落（调试用）。"""
    if _personality is None:
        return jsonify({"error": "Personality system not available"}), 503
    try:
        text = _personality.generate_personality_prompt(_uid())
        return jsonify({"prompt": text or ""})
    except Exception as exc:
        logger.warning("人格提示词生成失败", exc_info=True)
        return jsonify({"error": "生成失败: %s" % exc}), 500
