# maintenance/api.py
# Flask Blueprint — 维护状态查询 + SSE 进度流

from __future__ import annotations

import json
import logging
import queue
import threading
from datetime import datetime

import flask
from flask import Blueprint, Response, jsonify, request

from maintenance import config as maint_config
from maintenance.frontend_bridge import broadcast, subscribe, unsubscribe
from maintenance.state import ServerState

logger = logging.getLogger("maintenance.api")

maintenance_bp = Blueprint("maintenance", __name__, url_prefix="/api/maintenance")


def _get_maint_system():
    return flask.current_app.config.get("MAINTENANCE_SYSTEM")


def _require_auth():
    """触发/控制类操作需要认证，返回 (user, error_response) 二元组。"""
    mgr = flask.current_app.config.get("AUTH_MANAGER")
    if not mgr:
        return None, (jsonify({"error": "Auth unavailable"}), 503)
    user = mgr.authenticate(request)
    if not user:
        return None, (jsonify({"error": "Unauthorized"}), 401)
    return user, None


@maintenance_bp.route("/status")
def status():
    ms = _get_maint_system()
    if not ms:
        return jsonify({"error": "维护系统不可用"}), 503

    return jsonify({
        "state": ms.state.state.value,
        "request_count": ms.tracker.request_count(),
        "idle_minutes": ms.tracker.minutes_since_last_request(),
        "idle_probability": ms.tracker.idle_probability(datetime.now().hour),
        "schedule_strategy": maint_config.SCHEDULE_STRATEGY,
    })


@maintenance_bp.route("/sse")
def sse_stream():
    """SSE 事件流 — 推送维护进度到前端"""
    q = subscribe()

    def generate():
        while True:
            try:
                data = q.get(timeout=30)
                yield data
            except queue.Empty:
                yield ": heartbeat\n\n"
    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@maintenance_bp.route("/trigger", methods=["POST"])
def trigger_maintenance():
    _, err = _require_auth()
    if err:
        return err
    ms = _get_maint_system()
    if not ms:
        return jsonify({"error": "维护系统不可用"}), 503
    if ms.state.state != ServerState.READY:
        return jsonify({"error": f"服务器当前状态: {ms.state.state.value}"}), 409
    ms.trigger_maintenance()
    return jsonify({"success": True, "state": ms.state.state.value})


@maintenance_bp.route("/toggle_standby", methods=["POST"])
def toggle_standby():
    _, err = _require_auth()
    if err:
        return err
    ms = _get_maint_system()
    if not ms:
        return jsonify({"error": "维护系统不可用"}), 503
    if ms.state.state == ServerState.STANDBY:
        ms._wake_from_standby()
    else:
        ms.trigger_standby()
    return jsonify({"state": ms.state.state.value})
