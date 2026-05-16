# todo_api.py
# Todo SSE API 端点 — 暴露 todo 计划进度给客户端

from __future__ import annotations

import logging
from flask import Blueprint, Response, request, jsonify

from plugins.builtin.todo_store import get_todo_store

logger = logging.getLogger("TodoAPI")

todo_bp = Blueprint("todo_api", __name__)


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
    store = get_todo_store()
    plan = store.get_plan(todo_id)

    if plan is None:
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
    store = get_todo_store()
    plan_dict = store.get_plan_dict(todo_id)
    if plan_dict is None:
        return jsonify({"error": "Todo plan not found"}), 404
    return jsonify(plan_dict)


@todo_bp.route("/api/todo/list", methods=["GET"])
def todo_list():
    """列出 todo 计划（支持 user_id / chat_id 过滤）"""
    store = get_todo_store()
    user_id = request.args.get("user_id", type=int)
    chat_id = request.args.get("chat_id", type=int)
    plans = store.list_plans(user_id=user_id, chat_id=chat_id)
    return jsonify(plans)
