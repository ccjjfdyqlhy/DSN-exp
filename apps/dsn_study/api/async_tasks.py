# api/async_tasks.py
# 异步任务 API — POST /api/chat/async_send + GET /api/task/status/<id>
#
# 与参考实现（DSN-exp api/async_tasks.py）的对应关系：
#   - 参考版 /chat/async_send 走插件管线（engine.pipeline.process），
#     产出 reply + audio_b64；dsn_study 无插件管线，改为走 StudyEngine.chat，
#     产出 reply（纯文本，无 TTS）。
#   - 状态查询端点语义一致（STUDY 版额外做了归属校验 403）。

from __future__ import annotations

import logging
import threading
import uuid

from flask import Blueprint, jsonify, request, g, current_app

logger = logging.getLogger("AsyncTasks")

async_task_bp = Blueprint("async_tasks", __name__)

_auth_manager = None


def init_async_tasks_api(auth_manager):
    global _auth_manager
    _auth_manager = auth_manager


def _get_store():
    engine = current_app.config.get("ENGINE")
    return engine.async_task_store if engine else None


@async_task_bp.before_request
def _require_auth():
    if not _auth_manager:
        return jsonify({"error": "Auth unavailable"}), 503
    user = _auth_manager.authenticate(request)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    g.user = user


@async_task_bp.route("/api/chat/async_send", methods=["POST"])
def async_send():
    """异步对话：立即返回 task_id，结果由 /api/task/status/<id> 轮询。"""
    engine = current_app.config.get("ENGINE")
    if not engine:
        return jsonify({"error": "Engine not ready"}), 503

    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "Missing message"}), 400

    user_id = g.user.get("uid", 0)
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    chat_id = data.get("chat_id", 0) or 0
    session_id = data.get("session_id") or None
    task_id = f"async_{uuid.uuid4().hex[:16]}"
    store = engine.async_task_store
    store.create(task_id, user_id, chat_id)

    def _run():
        try:
            reply = engine.chat(message, user_id=user_id, session_id=session_id)
            store.complete(task_id, reply=reply or "")
        except Exception as e:
            logger.error("异步执行失败 %s: %s", task_id, e)
            store.complete(task_id, reply="", error=str(e))

    threading.Thread(target=_run, daemon=True).start()
    logger.info("异步发送: task_id=%s user=%d", task_id, user_id)
    return jsonify({"task_id": task_id, "status": "running"}), 202


@async_task_bp.route("/api/task/status/<task_id>", methods=["GET"])
def task_status(task_id: str):
    store = _get_store()
    if not store:
        return jsonify({"error": "Engine not ready"}), 503

    owner = store.owner_of(task_id)
    if owner is None:
        return jsonify({"error": "Task not found"}), 404
    if owner != g.user.get("uid", 0):
        return jsonify({"error": "Forbidden"}), 403

    record = store.lookup(task_id) or {}
    return jsonify({
        "task_id": task_id,
        "status": record.get("status", "unknown"),
        "reply": record.get("reply", ""),
        "audio_b64": record.get("audio_b64", ""),
        "chat_id": record.get("chat_id", 0),
        "error": record.get("error", ""),
        "done": record.get("status") in ("done", "failed"),
    })
