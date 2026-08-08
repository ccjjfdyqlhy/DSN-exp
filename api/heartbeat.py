# api/heartbeat.py
# 心跳接口 — 前端定期 POST /api/heartbeat，后端检查是否有未投递通知。
#
# 工作流程:
#   1. 前端每 N 秒发一次心跳请求
#   2. 后端检查 task_notifications 表中该用户是否有 delivered=0 的记录
#   3. 无 → {"has_notification": false}
#   4. 有 →
#      a. 根据 task_type 构造 prompt (reminder/vision)
#      b. 调 engine.chat 生成 AI 回复 + TTS
#      c. 标记 delivered=1
#      d. 返回 {"has_notification": true, "reply": ..., "audio_b64": ..., ...}
#   5. 前端收到后显示回复、播放 TTS
#
# 支持的 task_type:
#   - "reminder" | "habit" | "countdown" | "daily_plan" | "periodic": 提醒类
#   - "vision": 视觉感知类 → 主LLM根据场景描述决策是否主动说话

import json
import logging
from datetime import datetime

from flask import Blueprint, request, jsonify, g

from api.alarm import check_and_trigger as check_alarms

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
    """复用全局认证，未认证直接拒绝"""
    if not _auth_manager:
        return jsonify({"error": "Auth unavailable"}), 503
    user = _auth_manager.authenticate(request)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    g.user = user


# ── Prompt 构建 ──


def _build_reminder_prompt(notification: dict) -> str:
    """提醒类通知的 prompt。"""
    task_type = notification.get("task_type", "reminder")
    params = notification.get("params", {}) or {}
    result = notification.get("result", {}) or {}

    # result 可能是序列化的 JSON 字符串
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except (json.JSONDecodeError, TypeError):
            result = {}

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


def _build_vision_prompt(notification: dict) -> str:
    """视觉感知类通知的 prompt — 主LLM根据场景描述决策是否主动说话。

    通知数据格式:
      result.task_type = "vision"
      result.reason = "user_appeared" | "user_returned" | "light_changed" | "periodic"
      result.description = VisionModel 的场景描述
      result.timestamp = 观测时间
    """
    result = notification.get("result", {})
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except (json.JSONDecodeError, TypeError):
            result = {}

    desc = result.get("description", "")
    reason = result.get("reason", "")
    ts = result.get("timestamp", "")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    reason_labels = {
        "user_appeared": "用户出现在摄像头画面中",
        "user_returned": "用户回到了摄像头画面中",
        "light_changed": "环境光线发生了变化",
        "periodic": "距离上次主动观察已经过了一段时间",
    }
    reason_text = reason_labels.get(reason, "视觉环境发生了变化")

    prompt = (
        f"[视觉感知] 现在是 {now}，你通过摄像头观察到一些变化。\n"
        f"变化原因：{reason_text}\n"
        f"观测时间：{ts}\n"
        f"画面描述：{desc}\n\n"
        f"请根据这个视觉信息，判断是否需要主动跟用户说话。\n\n"
        f"决策规则：\n"
        f"1. 如果用户在忙（打字、工作、看书等），安静等待，不需要说话\n"
        f"2. 如果用户刚出现/回来，可以打个招呼问候\n"
        f"3. 如果环境有明显变化（天黑/天亮等），可以自然地提一句\n"
        f"4. 如果用户不在画面中，不说话\n"
        f"5. 如果用户只是正常活动，没有特殊情况，不说话\n\n"
        f"如果你认为需要说话，请用你的语气简短说一句（一两句话）。\n"
        f"如果你认为不需要说话，请回复一个空字符串或只有一个点号。\n"
        f"不要复述以上规则，不要带系统标记。"
    )
    return prompt


# ── 路由 ──


@heartbeat_bp.route("/api/heartbeat", methods=["GET", "POST"])
def heartbeat():
    """前端心跳接口。"""
    uid = g.user.get("uid", 0) if g.user else 0
    if not uid:
        return jsonify({"has_notification": False})

    if _task_manager is None:
        return jsonify({"has_notification": False, "error": "TaskManager 不可用"}), 200

    # 1. 拉取该用户所有未投递的通知 (reminder + vision)
    try:
        notifications = _task_manager.fetch_pending_notifications(uid, limit=1)
    except Exception as e:
        logger.error("拉取待通知失败 uid=%d: %s", uid, e, exc_info=True)
        return jsonify({"has_notification": False, "error": "Internal error"}), 200

    if not notifications:
        # 2. 检查闹钟触发
        try:
            triggered_alarms = check_alarms(uid)
            if triggered_alarms:
                alarm = triggered_alarms[0]
                alarm_prompt = (
                    f"[系统闹钟] 现在时间是 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}，"
                    f"你之前设置的闹钟响了。\n"
                    f"闹钟消息：{alarm['message']}\n\n"
                    f"请用你自己的语气，简短地提醒用户这件事。一两句话即可。"
                )
                if _engine:
                    try:
                        result = _engine.chat(
                            message=alarm_prompt,
                            user_id=uid,
                            chat_id=None,
                            chat_name="闹钟",
                            nickname=g.user.get("nickname", "用户"),
                            tts_enabled=True,
                        )
                        reply = result.get("reply", alarm["message"])
                        audio_b64 = result.get("audio_b64", "") or ""
                        tts_error = result.get("tts_error", "")
                        return jsonify({
                            "has_notification": True,
                            "reply": reply,
                            "audio_b64": audio_b64,
                            "tts_error": tts_error,
                            "task_id": f"alarm_{alarm['id']}",
                            "task_type": "alarm",
                            "alarm": alarm,
                        })
                    except Exception as e:
                        logger.error("闹钟 AI 回复失败: %s", e)
                return jsonify({
                    "has_notification": True,
                    "reply": f"⏰ {alarm['message']}",
                    "audio_b64": "",
                    "task_id": f"alarm_{alarm['id']}",
                    "task_type": "alarm",
                    "alarm": alarm,
                })
        except Exception as e:
            logger.error("闹钟检查失败: %s", e)
        return jsonify({"has_notification": False})

    notification = notifications[0]
    notification_id = notification["notification_id"]
    task_id = notification["task_id"]
    chat_id = notification.get("chat_id", 0) or 0

    # 解析 result 字段
    raw_result = notification.get("result") or "{}"
    if isinstance(raw_result, str):
        try:
            parsed_result = json.loads(raw_result)
        except (json.JSONDecodeError, TypeError):
            parsed_result = {}
    else:
        parsed_result = raw_result

    task_type = parsed_result.get("task_type", notification.get("task_type", "reminder"))
    logger.info("心跳命中待通知: uid=%d task=%s type=%s notif=%d",
                uid, task_id, task_type, notification_id)

    if _engine is None:
        logger.warning("engine 不可用，无法生成 AI 回复")
        try:
            _task_manager.mark_notification_delivered(notification_id)
        except Exception:
            logger.warning("Operation failed", exc_info=True)
        fallback_reply = "（AI 不可用）"
        return jsonify({
            "has_notification": True,
            "reply": fallback_reply,
            "audio_b64": "",
            "task_id": task_id,
            "chat_id": chat_id,
            "notification_id": notification_id,
            "task_type": task_type,
            "tts_error": "engine unavailable",
        })

    # 2. 根据 task_type 构造 prompt
    if task_type == "vision":
        prompt = _build_vision_prompt(notification)
    else:
        prompt = _build_reminder_prompt(notification)

    # 3. 调主 AI 生成回复 + TTS
    try:
        result = _engine.chat(
            message=prompt,
            user_id=uid,
            chat_id=chat_id if chat_id else None,
            chat_name="提醒" if task_type != "vision" else "视觉感知",
            nickname=g.user.get("nickname", "用户"),
            tts_enabled=True,
            is_asr_input=False,
        )
    except Exception as e:
        logger.error("心跳生成 AI 回复失败 uid=%d task=%s type=%s: %s", uid, task_id, task_type, e, exc_info=True)
        try:
            _task_manager.mark_notification_delivered(notification_id)
        except Exception:
            logger.warning("Operation failed", exc_info=True)
        return jsonify({
            "has_notification": True,
            "reply": "（通知生成失败）",
            "audio_b64": "",
            "task_id": task_id,
            "chat_id": chat_id,
            "notification_id": notification_id,
            "task_type": task_type,
            "error": "Internal error",
        })

    reply = result.get("reply", "")
    audio_b64 = result.get("audio_b64", "") or ""
    tts_error = result.get("tts_error", "")
    new_chat_id = result.get("chat_id", chat_id)

    # 视觉通知特殊处理: 如果 LLM 返回空/纯标点，表示"不需要说话"，不推送
    if task_type == "vision":
        stripped = reply.strip().strip(".,。，！!?？\n")
        if not stripped or len(stripped) <= 1:
            logger.info("视觉通知: LLM 决策不说话, 静默丢弃 reply=%r", reply)
            try:
                _task_manager.mark_notification_delivered(notification_id)
            except Exception:
                logger.warning("Operation failed", exc_info=True)
            return jsonify({"has_notification": False})

    # 4. 标记为已投递
    try:
        _task_manager.mark_notification_delivered(notification_id)
    except Exception as e:
        logger.warning("标记通知已投递失败 notif=%d: %s", notification_id, e)

    logger.info("心跳通知已投递: uid=%d task=%s type=%s reply=%d chars audio=%d chars",
                uid, task_id, task_type, len(reply), len(audio_b64))

    return jsonify({
        "has_notification": True,
        "reply": reply,
        "audio_b64": audio_b64,
        "tts_error": tts_error,
        "task_id": task_id,
        "chat_id": new_chat_id,
        "notification_id": notification_id,
        "task_type": task_type,
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
        logger.error("取消通知失败: %s", e, exc_info=True)
        return jsonify({"success": False, "error": "Internal error"}), 500


# ── 视觉感知字段注入 ──

@heartbeat_bp.after_request
def _inject_vision_fields(response):
    """向 /api/heartbeat 响应注入:
    - vision_request: 当存在待响应的按需 look_around 请求时下发给客户端
    - active_vision: 主动视觉配置 {enabled, interval}，供 minimal.py 自配置周期观测线程
    - sensing: 闲置时感知配置 {enabled, cooldown, max_record_secs}，供 minimal.py 自配置

    与通知逻辑解耦：无论是否有通知，每次心跳都附带这几个字段。
    """
    if request.path != "/api/heartbeat":
        return response

    try:
        data = response.get_json()
    except Exception:
        data = None
    if not isinstance(data, dict):
        return response

    changed = False

    # on-demand 视觉请求（来自 VisionCoordinator）
    try:
        from api.vision import coordinator as _coord
        if _coord is not None:
            # after_request 也会在认证失败(401/503)时运行，此时 g.user 未设置，
            # 必须用 getattr 安全读取，否则 AttributeError 会覆盖原始响应
            user = getattr(g, "user", None)
            uid = user.get("uid", 0) if user else 0
            vr = _coord.pending_for_uid(uid)
            if vr:
                data["vision_request"] = vr
                changed = True
    except Exception:
        logger.warning("注入 vision_request 失败", exc_info=True)

    # 主动视觉配置（让 minimal.py 自配置周期观测线程）
    try:
        from config import Config
        data["active_vision"] = {
            "enabled": bool(getattr(Config, "ACTIVE_VISION_ENABLED", False)),
            "interval": int(getattr(Config, "ACTIVE_VISION_INTERVAL", 300)),
            "camera": getattr(Config, "ACTIVE_VISION_CAMERA", "") or "",
        }
        changed = True
    except Exception:
        logger.warning("注入 active_vision 配置失败", exc_info=True)

    # 闲置时感知配置（让 minimal.py 自配置闲置监听线程）
    # 兼容：sensing.enabled 沿用旧字段（其聆听能力现由 tracking 子系统提供），
    # 同时下发 tracking 配置供 tracking 聆听器自配置。
    try:
        from config import Config
        _sens_enabled = bool(getattr(Config, "SENSING_ENABLED", False))
        _trk_enabled = bool(getattr(Config, "TRACKING_ENABLED", _sens_enabled))
        data["sensing"] = {
            "enabled": _sens_enabled,
            "cooldown": int(getattr(Config, "SENSING_COOLDOWN", 60)),
            "max_record_secs": float(getattr(Config, "SENSING_MAX_RECORD_SECS", 6.0)),
        }
        data["tracking"] = {
            "enabled": _trk_enabled,
            "cooldown": int(getattr(Config, "SENSING_COOLDOWN", 60)),
            "max_record_secs": float(getattr(Config, "SENSING_MAX_RECORD_SECS", 6.0)),
        }
        changed = True
    except Exception:
        logger.warning("注入 sensing/tracking 配置失败", exc_info=True)

    if changed:
        response.set_data(json.dumps(data, ensure_ascii=False))
    return response
