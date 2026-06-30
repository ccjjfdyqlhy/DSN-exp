# api/agent.py
# AI Agent 对话接口 — POST /api/agent/send
# 供 OpenClaw 等本地 AI Agent 与 DSN-exp 主 AI 对话

from __future__ import annotations

import logging
from datetime import datetime

from flask import Blueprint, request, jsonify, g, current_app

logger = logging.getLogger("AgentAPI")

agent_bp = Blueprint("agent_api", __name__, url_prefix="/api/agent")

INTRO_SYSTEM = (
    "今天是 {date}。"
    "一个名为 {agent_name} 的本地 AI 助手刚刚通过 API 连接到 DSN-exp。"
    "请你立即用中文做一段简短的自我介绍：\n"
    " - 说明你是谁（你的角色/人格）\n"
    " - 说明你和你的用户 {user_name} 的关系（例如：你们认识多久、平时怎么交流）\n"
    " - 最后向 {agent_name} 随便说点什么你想说的。\n"
    "直接说出即可，不要用标签或特殊格式。"
)


def _get_engine():
    return current_app.config.get("ENGINE")


def _get_db():
    return current_app.config.get("DB")


@agent_bp.before_request
def _require_auth():
    from auth.endpoints import authenticate_from_request
    user = authenticate_from_request()
    if user is None:
        return jsonify({"error": "未认证"}), 401
    if user.get("auth_source") != "api_key":
        return jsonify({"error": "Agent 接口仅支持 API Key 认证，禁止 Session / JWT"}), 403
    g.user = user


@agent_bp.route("/send", methods=["POST"])
def agent_send():
    """Agent 发送消息，同步返回主 AI 回复。"""
    engine = _get_engine()
    db = _get_db()
    if not engine:
        return jsonify({"error": "Engine 不可用"}), 503
    if not db:
        return jsonify({"error": "DB 不可用"}), 503

    uid = g.user.get("uid", 0)
    agent_name = g.user.get("nickname", "Agent")
    if not uid:
        return jsonify({"error": "用户 ID 无效"}), 400

    data = request.get_json(silent=True) or {}
    message = data.get("message", "").strip()
    if not message:
        return jsonify({"error": "消息不能为空"}), 400

    bound_uid = db.get_bound_user(uid)
    if not bound_uid:
        return jsonify({"error": "该 Agent 未绑定任何用户，请先使用 /agent create 创建并绑定"}), 400

    is_first = db.get_agent_chat_count(uid) == 0

    chat_id = data.get("chat_id")
    if not chat_id:
        chat_id = db.create_chat(uid, f"Agent-{agent_name}", chat_type="agent")

    history = db.get_chat_history(uid, chat_id)

    user_row = db._get_connection().execute(
        "SELECT nickname, display_name FROM users WHERE uid = ?", (bound_uid,)
    ).fetchone()
    user_name = (user_row["display_name"] or user_row["nickname"]) if user_row else "用户"

    if is_first:
        intro = INTRO_SYSTEM.format(
            date=datetime.now().strftime("%Y年%m月%d日 %H:%M"),
            agent_name=agent_name,
            user_name=user_name,
        )
        intro_msg = {"role": "system", "content": intro}
        history.insert(0, intro_msg)

    try:
        result = engine.chat(
            message=message,
            user_id=uid,
            chat_id=chat_id,
            chat_name=f"Agent-{agent_name}",
            history=history,
            nickname=agent_name,
            tts_enabled=False,
            is_asr_input=False,
            cross_user_id=bound_uid,
        )
    except Exception as e:
        logger.error("Agent 对话失败 uid=%d: %s", uid, e)
        return jsonify({"error": str(e)}), 500

    reply = result.get("reply", "") or result.get("original_reply", "")

    return jsonify({
        "reply": reply,
        "chat_id": result.get("chat_id", chat_id),
    })
