# todo_api.py
# Todo SSE API 端点 — 暴露 todo 计划进度给客户端

from __future__ import annotations

import logging
from flask import Blueprint, Response, request, jsonify, g, current_app

from plugins.builtin.todo_store import get_todo_store

logger = logging.getLogger("TodoAPI")

todo_bp = Blueprint("todo_api", __name__)


def _auth_manager():
    return current_app.config.get("AUTH_MANAGER")


@todo_bp.before_request
def _require_auth():
    mgr = _auth_manager()
    if not mgr:
        return jsonify({"error": "Auth unavailable"}), 503
    user = mgr.authenticate(request)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    g.user = user


def _uid() -> int:
    uid = g.user.get("uid", 0)
    return uid


@todo_bp.route("/api/todo/stream/<todo_id>", methods=["GET"])
def todo_stream(todo_id: str):
    """
    SSE 端点：实时推送指定 todo 计划的进度。

    客户端连接后持续接收事件流:
      - snapshot: 当前完整状态
      - plan_created / plan_started: 计划创建/开始
      - item_updated: 某个子任务状态更新
      - plan_completed / plan_failed: 计划完成/失败
    """
    uid = _uid()
    store = get_todo_store()
    plan = store.get_plan(todo_id)

    if plan is None:
        return jsonify({"error": "Todo plan not found"}), 404
    # 归属校验：仅计划所属用户可订阅其进度流
    if plan.user_id != uid:
        return jsonify({"error": "Todo plan not found"}), 404

    def generate():
        q = store.subscribe(todo_id)
        try:
            import time as _time
            deadline = _time.time() + 300  # 5 分钟超时
            while _time.time() < deadline:
                try:
                    event = q.get(timeout=10)
                    yield event
                    # 检测到完成事件后立即关闭
                    if "completed" in event or "failed" in event:
                        break
                except Exception:
                    # 定期检查计划是否还存在
                    if store.get_plan(todo_id) is None:
                        break
                    # 发送心跳
                    yield f"data: {{\"type\": \"heartbeat\"}}\n\n"
        finally:
            store.unsubscribe(todo_id, q)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@todo_bp.route("/api/todo/plan/<todo_id>", methods=["GET"])
def todo_plan(todo_id: str):
    """获取指定 todo 计划的当前状态（非 SSE，单次查询）"""
    uid = _uid()
    store = get_todo_store()
    plan_dict = store.get_plan_dict(todo_id)
    if plan_dict is None:
        return jsonify({"error": "Todo plan not found"}), 404
    if plan_dict.get("user_id", 0) != uid:
        return jsonify({"error": "Todo plan not found"}), 404
    return jsonify(plan_dict)


@todo_bp.route("/api/todo/list", methods=["GET"])
def todo_list():
    """列出 todo 计划（按当前认证用户过滤）"""
    uid = _uid()
    store = get_todo_store()
    chat_id = request.args.get("chat_id", type=int)
    plans = store.list_plans(user_id=uid, chat_id=chat_id)
    return jsonify(plans)
