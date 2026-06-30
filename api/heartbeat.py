# api/heartbeat.py
# 心跳接口 — 前端定期 POST /api/heartbeat，后端检查是否有已完成的提醒任务。
#
# 工作流程：
#   1. 前端每 N 秒发一次心跳请求
#   2. 后端检查 task_notifications 表中该用户是否有 delivered=0 的记录
#   3. 如果没有 → 返回 {"has_notification": false}，前端什么都不做
#   4. 如果有 →
#      a. 取出最早的一条，调用 engine.chat 生成 AI 提醒回复
#      b. 合成 TTS 音频
#      c. 标记该通知为 delivered=1
#      d. 返回 {"has_notification": true, "reply": ..., "audio_b64": ..., "task_id": ...}
#   5. 前端收到后立即显示回复、播放 TTS
#
# 这样设计的好处：
#   - 后端 reminder 完成后不需要立即通知前端（避免 SSE 单向通信问题）
#   - 前端心跳是主动拉取，符合"请求-响应"模型
#   - AI 回复和 TTS 在心跳请求中同步生成，前端拿到即可用

from __future__ import annotations

import logging
from datetime import datetime

from flask import Blueprint, request, jsonify, g, current_app

logger = logging.getLogger("Heartbeat")

heartbeat_bp = Blueprint("heartbeat_api", __name__)

_db = None
_task_manager = None
_auth_manager = None
_engine = None


def init_heartbeat_api(db, task_manager, auth_manager, engine):
    global _db, _task_manager, _auth_manager, _engine
    _db = db
    _task_manager = task_manager
    _auth_manager = auth_manager
    _engine = engine


@heartbeat_bp.before_request
def _require_auth():
    """复用全局认证"""
    if _auth_manager:
        user = _auth_manager.authenticate(request)
        g.user = user
    else:
        g.user = {"uid": 0}


def _build_reminder_prompt(notification: dict) -> str:
    """根据提醒通知构造发给主 AI 的消息。
    notification 包含 task_type / params / result 等字段。
    """
    task_type = notification.get("task_type", "reminder")
    params = notification.get("params", {}) or {}
    result = notification.get("result", {}) or {}
    reminder_text = result.get("reminder_text", "") or params.get("text", "提醒时间到了")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    type_labels = {
        "reminder": "一次性提醒",
        "habit": "周期性习惯",
        "countdown": "倒计时",
        "daily_plan": "每日计划",
        "periodic": "周期性任务",
    }
    type_label = type_labels.get(task_type, "提醒")

    prompt = (
        f"[系统事件] 现在时间是 {now}，你之前帮用户设置的一个{type_label}刚刚到期触发了。\n"
        f"提醒内容：{reminder_text}\n\n"
        f"请用你自己的语气、人格和说话方式，自然地提醒用户这件事。"
        f"要求：口语化、简短（一两句话即可）、带一点关心或性格色彩，"
        f"不要机械复述上面的格式，不要带任何系统标记。"
    )
    return prompt


@heartbeat_bp.route("/api/heartbeat", methods=["GET", "POST"])
def heartbeat():
    """前端心跳接口。
    返回:
      - {"has_notification": false}  无待通知提醒
      - {"has_notification": true, "reply": ..., "audio_b64": ..., "task_id": ...,
         "chat_id": ..., "notification_id": ...}  有待通知提醒，已生成 AI 回复 + TTS
    """
    uid = g.user.get("uid", 0) if g.user else 0
    if not uid:
        return jsonify({"has_notification": False})

    if _task_manager is None:
        return jsonify({"has_notification": False, "error": "TaskManager 不可用"}), 200

    # 1. 拉取该用户所有未投递的提醒通知
    try:
        notifications = _task_manager.fetch_pending_notifications(uid, limit=1)
    except Exception as e:
        logger.error("拉取待通知提醒失败 uid=%d: %s", uid, e)
        return jsonify({"has_notification": False, "error": str(e)}), 200

    if not notifications:
        return jsonify({"has_notification": False})

    notification = notifications[0]
    notification_id = notification["notification_id"]
    task_id = notification["task_id"]
    chat_id = notification.get("chat_id", 0) or 0
    logger.info("心跳命中待通知提醒: uid=%d task=%s notif=%d",
                uid, task_id, notification_id)

    # 2. 调用主 AI 生成提醒回复 + TTS
    if _engine is None:
        logger.warning("engine 不可用，无法生成 AI 提醒回复")
        # 仍然标记为已投递，避免反复触发
        try:
            _task_manager.mark_notification_delivered(notification_id)
        except Exception:
            pass
        return jsonify({
            "has_notification": True,
            "reply": notification["result"].get("reminder_text", "提醒时间到了"),
            "audio_b64": "",
            "task_id": task_id,
            "chat_id": chat_id,
            "notification_id": notification_id,
            "tts_error": "engine unavailable",
        })

    prompt = _build_reminder_prompt(notification)
    try:
        result = _engine.chat(
            message=prompt,
            user_id=uid,
            chat_id=chat_id if chat_id else None,
            chat_name="提醒",
            nickname=g.user.get("nickname", "用户"),
            tts_enabled=True,
            is_asr_input=False,
        )
    except Exception as e:
        logger.error("心跳生成 AI 提醒回复失败 uid=%d task=%s: %s", uid, task_id, e)
        # 失败也标记为已投递，避免死循环
        try:
            _task_manager.mark_notification_delivered(notification_id)
        except Exception:
            pass
        return jsonify({
            "has_notification": True,
            "reply": notification["result"].get("reminder_text", "提醒时间到了"),
            "audio_b64": "",
            "task_id": task_id,
            "chat_id": chat_id,
            "notification_id": notification_id,
            "error": str(e),
        })

    reply = result.get("reply", "") or notification["result"].get("reminder_text", "提醒时间到了")
    audio_b64 = result.get("audio_b64", "") or ""
    tts_error = result.get("tts_error", "")
    new_chat_id = result.get("chat_id", chat_id)

    # 3. 标记该通知为已投递
    try:
        _task_manager.mark_notification_delivered(notification_id)
    except Exception as e:
        logger.warning("标记通知已投递失败 notif=%d: %s", notification_id, e)

    logger.info("心跳提醒已投递: uid=%d task=%s reply=%d chars audio=%d chars",
                uid, task_id, len(reply), len(audio_b64))

    return jsonify({
        "has_notification": True,
        "reply": reply,
        "audio_b64": audio_b64,
        "tts_error": tts_error,
        "task_id": task_id,
        "chat_id": new_chat_id,
        "notification_id": notification_id,
        "task_type": notification.get("task_type", "reminder"),
    })


@heartbeat_bp.route("/api/heartbeat/dismiss", methods=["POST"])
def dismiss_notification():
    """前端主动忽略某条通知（标记 dismissed=1，不再触发）。"""
    uid = g.user.get("uid", 0) if g.user else 0
    data = request.get_json(silent=True) or {}
    notification_id = data.get("notification_id")
    if not notification_id:
        return jsonify({"success": False, "error": "缺少 notification_id"}), 400
    try:
        conn = _db._get_connection()
        conn.execute(
            "UPDATE task_notifications SET dismissed = 1 WHERE notification_id = ? AND user_id = ?",
            (notification_id, uid)
        )
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
