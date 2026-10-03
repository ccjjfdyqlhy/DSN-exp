# api/async_tasks.py
# 异步任务状态查询 API — 供客户端 AsyncTaskPoller 轮询扫题/批处理结果。

from __future__ import annotations

import logging

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
