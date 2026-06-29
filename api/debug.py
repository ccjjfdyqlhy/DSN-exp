# api/debug.py
# DEBUG_PLAY_AS_MODEL — 调试模式 API 蓝图
# 注册在独立端口 (127.0.0.1:DEBUG_PLAY_AS_MODEL_PORT)

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from threading import Lock

from flask import Blueprint, jsonify, request

logger = logging.getLogger("DebugAPI")

debug_bp = Blueprint("debug", __name__)

# 会话存储：session_id -> session_data
_sessions: dict[str, dict] = {}
_sessions_lock = Lock()
_MAX_SESSIONS = 64

# 引擎引用（由 create_debug_app 注入）
_engine = None


def set_engine(engine):
    global _engine
    _engine = engine


def _cleanup_stale_sessions():
    now = datetime.now()
    stale = [sid for sid, sd in _sessions.items()
             if (now - sd.get("_created", now)).total_seconds() > 1800]
    for sid in stale:
        _sessions.pop(sid, None)


def _get_or_create_session(session_id: str = "") -> tuple[str, dict]:
    with _sessions_lock:
        if session_id and session_id in _sessions:
            return session_id, _sessions[session_id]
        _cleanup_stale_sessions()
        if len(_sessions) >= _MAX_SESSIONS:
            oldest = min(_sessions.keys(),
                         key=lambda k: _sessions[k].get("_created", datetime.min))
            _sessions.pop(oldest, None)
        sid = session_id or f"debug_{uuid.uuid4().hex[:16]}"
        data = {"_created": datetime.now()}
        _sessions[sid] = data
        return sid, data


@debug_bp.route("/debug/chat", methods=["POST"])
def debug_chat():
    """阶段1: 用户发消息 → PRE_PROCESS → 返回上下文"""
    if _engine is None:
        return jsonify({"error": "Engine not available"}), 503

    data = request.get_json(silent=True) or {}
    message = data.get("message", "").strip()
    if not message:
        return jsonify({"error": "Missing message"}), 400

    session_id, _ = _get_or_create_session(data.get("session_id", ""))
    history = data.get("history", [])

    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(
            _engine.chat_debug(
                message=message,
                session_id=session_id,
                user_id=data.get("user_id", 1),
                chat_id=data.get("chat_id"),
                history=history,
            )
        )
    finally:
        loop.close()

    # 保存会话上下文
    with _sessions_lock:
        sd = _sessions.get(session_id, {})
        sd["user_id"] = result["context"]["user_id"]
        sd["chat_id"] = result["context"]["chat_id"]
        sd["message"] = result["context"]["message"]
        sd["system_prompt"] = result["context"]["system_prompt"]
        sd["history"] = result["context"]["history"]
        sd["full_history"] = result["context"]["history"]
        sd["extra"] = result["extra"]
        sd["tts_enabled"] = data.get("tts_enabled", True)
        _sessions[session_id] = sd

    return jsonify({
        "session_id": session_id,
        "status": "await_model",
        "context": {
            "system_prompt": result["context"]["system_prompt"],
            "message": result["context"]["message"],
            "history_count": len(result["context"]["history"]),
        },
        "skills": result["skills"],
        "filtered": result["context"]["filtered"],
    })


@debug_bp.route("/debug/respond", methods=["POST"])
def debug_respond():
    """阶段2: 模型角色回复 → POST_PROCESS → 返回最终结果"""
    if _engine is None:
        return jsonify({"error": "Engine not available"}), 503

    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id", "")
    reply = data.get("reply", "").strip()
    tool_calls = data.get("tool_calls")

    if not session_id or session_id not in _sessions:
        return jsonify({"error": "Invalid or expired session"}), 400
    if not reply and not tool_calls:
        return jsonify({"error": "Missing reply"}), 400

    session_data = _sessions[session_id]

    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(
            _engine.chat_debug_respond(
                reply=reply or "",
                session_data=session_data,
                tool_calls=tool_calls,
            )
        )
    finally:
        loop.close()

    # 同步上下文字段回到会话
    if "_context" in result:
        ctx = result.pop("_context")
        with _sessions_lock:
            sd = _sessions.get(session_id, {})
            sd.update(ctx)
            _sessions[session_id] = sd

    return jsonify({
        "session_id": session_id,
        "status": result.get("status", "completed"),
        "reply": result.get("reply", ""),
        "original_reply": result.get("original_reply", ""),
        "filtered": result.get("filtered", False),
        "step": result.get("step", 0),
        "max_steps": result.get("max_steps", 0),
        "tool_results": result.get("tool_results", []),
    })


@debug_bp.route("/debug/skills", methods=["GET"])
def debug_skills():
    """获取所有可用技能和工具列表"""
    if _engine is None:
        return jsonify({"error": "Engine not available"}), 503
    return jsonify({"skills": _engine._get_skills_info()})


@debug_bp.route("/debug/health", methods=["GET"])
def debug_health():
    return jsonify({"status": "ok", "mode": "play_as_model", "sessions": len(_sessions)})


@debug_bp.route("/debug/session/<session_id>", methods=["DELETE"])
def debug_clear_session(session_id):
    with _sessions_lock:
        _sessions.pop(session_id, None)
    return jsonify({"status": "cleared"})


def create_debug_app(engine):
    """创建独立的调试模式 Flask 应用"""
    from flask import Flask
    app = Flask("DSN-Debug")
    app.config["DEBUG"] = True
    app.register_blueprint(debug_bp)
    set_engine(engine)

    @app.after_request
    def add_cors(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
        return response

    return app
