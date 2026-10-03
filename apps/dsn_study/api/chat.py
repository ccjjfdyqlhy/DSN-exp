# api/chat.py
# 对话 API — harness AgentLoop 的 HTTP 入口（非流式）。
#
# POST /api/chat/send  {message, user_id?} → {reply, tool_calls}
# 工具与学习上下文注入由 boot 装配的 StudyEngine 提供。

from __future__ import annotations

import logging

from flask import Blueprint, current_app, g, jsonify, request

logger = logging.getLogger("Chat")

chat_bp = Blueprint("chat_api", __name__)

_auth_manager = None


def init_chat_api(auth_manager):
    global _auth_manager
    _auth_manager = auth_manager


@chat_bp.before_request
def _require_auth():
    if not _auth_manager:
        return jsonify({"error": "Auth unavailable"}), 503
    user = _auth_manager.authenticate(request)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    g.user = user


@chat_bp.route("/api/chat/send", methods=["POST"])
def send():
    engine = current_app.config.get("ENGINE")
    if not engine:
        return jsonify({"error": "Engine not ready"}), 503

    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "Missing message"}), 400

    user_id = g.user.get("uid", 0) or 1
    try:
        reply = engine.chat(message, user_id=user_id)
    except Exception as e:
        logger.exception("对话处理失败")
        return jsonify({"error": str(e)}), 500

    return jsonify({"reply": reply})
