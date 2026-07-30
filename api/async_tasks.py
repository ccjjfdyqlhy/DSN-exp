# api/async_tasks.py
# 异步任务 API — POST /async_send + GET /task/status

from __future__ import annotations

import asyncio
import logging
import threading
import uuid

from flask import Blueprint, request, jsonify, current_app, g

from plugins.base import PluginContext

logger = logging.getLogger("AsyncTasks")

async_task_bp = Blueprint("async_tasks", __name__, url_prefix="/api")


def _get_engine():
    return current_app.config.get("ENGINE")


def _auth_manager():
    return current_app.config.get("AUTH_MANAGER")


@async_task_bp.before_request
def _require_auth():
    mgr = _auth_manager()
    if not mgr:
        return jsonify({"error": "Auth unavailable"}), 503
    user = mgr.authenticate(request)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    g.user = user


@async_task_bp.route("/chat/async_send", methods=["POST"])
def async_send():
    engine = _get_engine()
    if not engine:
        return jsonify({"error": "Engine not ready"}), 503

    data = request.get_json(silent=True) or {}
    message = data.get("message", "").strip()
    if not message:
        return jsonify({"error": "Missing message"}), 400

    chat_id = data.get("chat_id", 0)
    user_id = g.user.get("uid", 0)
    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    task_id = f"async_{uuid.uuid4().hex[:16]}"
    store = engine.async_task_store
    store.create(task_id, user_id, chat_id)

    ctx = PluginContext(
        user_id=user_id,
        message=message,
        chat_id=chat_id,
        history=data.get("history", []),
        full_history=data.get("full_history", []),
    )
    ctx.extra["_async_task_id"] = task_id
    ctx.tts_enabled = True

    def _run_pipeline():
        try:
            _loop = asyncio.new_event_loop()
            asyncio.set_event_loop(_loop)
            result_ctx = _loop.run_until_complete(engine.pipeline.process(ctx))
            _loop.close()

            reply = result_ctx.reply or ""
            audio_b64 = result_ctx.audio_b64 or ""
            if not reply:
                store.complete(task_id, reply="任务已完成", error="")
            else:
                store.complete(task_id, reply=reply, audio_b64=audio_b64)
        except Exception as e:
            logger.error("异步执行失败 %s: %s", task_id, e)
            store.complete(task_id, error=str(e))

    thread = threading.Thread(target=_run_pipeline, daemon=True)
    thread.start()

    logger.info("异步发送: task_id=%s user=%d message=%s", task_id, user_id, message[:50])
    return jsonify({
        "task_id": task_id,
        "status": "running",
    }), 202


@async_task_bp.route("/task/status/<task_id>", methods=["GET"])
def task_status(task_id):
    engine = _get_engine()
    if not engine:
        logger.warning("心跳查询 task=%s — engine 不可用", task_id)
        return jsonify({"error": "Engine not ready"}), 503

    uid = g.user.get("uid", 0)
    record = engine.async_task_store.lookup(task_id)
    if not record:
        logger.warning("心跳查询 task=%s — 未找到", task_id)
        return jsonify({"error": "Task not found"}), 404

    # 归属校验：仅允许任务创建者查询自己的异步任务
    owner_id = engine.async_task_store.owner_of(task_id)
    if owner_id and owner_id != uid:
        logger.warning("心跳查询 task=%s — 用户 %d 无权访问 (owner=%d)", task_id, uid, owner_id)
        return jsonify({"error": "Task not found"}), 404

    status = record["status"]
    reply_preview = record.get("reply", "")[:60]
    logger.info("心跳查询 task=%s — status=%s reply=%s",
                task_id, status, reply_preview or "(空)")

    if status == "running":
        return jsonify({"status": "running"})

    if status == "failed":
        return jsonify({
            "status": "failed",
            "task_id": record["task_id"],
            "error": record.get("error", ""),
            "reply": record.get("reply", ""),
        })

    return jsonify({
        "status": "done",
        "task_id": record["task_id"],
        "reply": record["reply"],
        "audio_b64": record.get("audio_b64", ""),
        "chat_id": record.get("chat_id", 0),
    })
