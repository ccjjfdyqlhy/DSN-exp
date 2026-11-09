# apps/dsn_study/api/heartbeat.py
# 心跳接口 — 自 apps/dsn/api/heartbeat.py 移植（dsn_study 功能补齐阶段 1）。
#
# 工作流程:
#   1. 前端每 N 秒发一次心跳请求
#   2. 后端检查 task_notifications 表中该用户是否有 delivered=0 的记录
#   3. 无 → 检查闹钟触发 → {"has_notification": false}
#   4. 有 → 构造提醒 prompt → engine.chat 生成 AI 回复 → 标记 delivered=1
#      → 返回 {"has_notification": true, "reply": ...}
#
# 与 dsn 原版的差异:
#   - StudyEngine.chat(message, user_id) 返回纯文本（无 TTS/audio 字段）；
#   - 视觉感知字段（迁移计划阶段 5）：vision_request / active_vision / streams /
#     sensing 四块经 after_request 注入（与 dsn 逐字段对齐）。vision_request 是
#     "AI 主动说『看一下』"的唯一通道；sensing/tracking 恒为 disabled
#     （study 无麦克风感知硬件链路，仅保留字段形状供 CLI 自配置）。

import json
import logging
from datetime import datetime

from flask import Blueprint, request, jsonify, g

from apps.dsn_study.api.alarm import check_and_trigger as check_alarms

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
        f"请用你自己的语气自然地提醒用户这件事。"
        f"要求：口语化、简短（一两句话即可）、带一点关心，"
        f"不要机械复述上面的格式，不要带任何系统标记。"
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

    # 1. 拉取该用户所有未投递的通知
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
                # 修复：同一分钟有多个闹钟时，此前只投递第一个——其余的
                # 已被标记 fired，当天永远不会再展示。现在全部拼接投递。
                messages = [a["message"] for a in triggered_alarms]
                alarm_prompt = (
                    f"[系统闹钟] 现在时间是 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}，"
                    f"你之前设置的闹钟响了。\n"
                    f"闹钟消息：{'；'.join(messages)}\n\n"
                    f"请用你自己的语气，简短地提醒用户这件事。一两句话即可。"
                )
                # 修复：AI 生成失败此前会让整个分支落进外层 except，返回
                # has_notification=False——但闹钟已被标记 fired，这条闹钟
                # 当天被静默吞掉。失败时也要返回兜底文案。
                try:
                    reply = _engine_chat_safe(alarm_prompt, uid)
                except Exception as e:
                    logger.error("闹钟 AI 回复生成失败 uid=%d: %s", uid, e, exc_info=True)
                    reply = ""
                if not reply:
                    reply = "⏰ " + "；".join(
                        f"{a['time']} {a['message']}" for a in triggered_alarms)
                alarm = triggered_alarms[0]
                audio_b64, tts_error = _synthesize(reply)
                return jsonify({
                    "has_notification": True,
                    "reply": reply,
                    "audio_b64": audio_b64,
                    "tts_error": tts_error,
                    "task_id": f"alarm_{alarm['id']}",
                    "task_type": "alarm",
                    "alarm": alarm,
                    "alarms": triggered_alarms,
                })
        except Exception as e:
            logger.error("闹钟检查失败: %s", e)
        return jsonify({"has_notification": False})

    notification = notifications[0]
    notification_id = notification["notification_id"]
    task_id = notification["task_id"]
    chat_id = notification.get("chat_id", 0) or 0

    # 原子领取（delivered 0→2）：fetch 与"生成 AI 回复"之间可达数十秒，
    # Flask 多线程下两次心跳此前会取到同一条通知，同一提醒生成两次 AI
    # 回复、重复展示。领取失败说明已被其它心跳处理，直接结束本次。
    try:
        if not _task_manager.claim_notification(notification_id):
            return jsonify({"has_notification": False})
    except Exception as e:
        logger.error("领取通知失败 notif=%d: %s", notification_id, e, exc_info=True)
        return jsonify({"has_notification": False, "error": "Internal error"}), 200

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
            logger.warning("标记通知已投递失败", exc_info=True)
        return jsonify({
            "has_notification": True,
            "reply": "（AI 不可用）",
            "task_id": task_id,
            "chat_id": chat_id,
            "notification_id": notification_id,
            "task_type": task_type,
        })

    # 2. 构造提醒 prompt 并生成 AI 回复
    prompt = _build_reminder_prompt(notification)
    try:
        reply = _engine_chat_safe(prompt, uid) or "（通知生成失败）"
    except Exception as e:
        logger.error("心跳生成 AI 回复失败 uid=%d task=%s type=%s: %s",
                     uid, task_id, task_type, e, exc_info=True)
        reply = "（通知生成失败）"

    # 3. 标记为已投递
    try:
        _task_manager.mark_notification_delivered(notification_id)
    except Exception as e:
        logger.warning("标记通知已投递失败 notif=%d: %s", notification_id, e)

    logger.info("心跳通知已投递: uid=%d task=%s type=%s reply=%d chars",
                uid, task_id, task_type, len(reply))

    audio_b64, tts_error = _synthesize(reply)
    return jsonify({
        "has_notification": True,
        "reply": reply,
        "audio_b64": audio_b64,
        "tts_error": tts_error,
        "task_id": task_id,
        "chat_id": chat_id,
        "notification_id": notification_id,
        "task_type": task_type,
    })


def _synthesize(reply: str) -> tuple:
    """把提醒文案合成为语音。返回 (audio_b64, tts_error)；不可用时为 (None, "")。

    语音是增强项：任何失败都降级为纯文本，绝不影响通知投递。
    """
    if not reply or _engine is None:
        return None, ""
    voice = getattr(_engine, "voice", None)
    if voice is None:
        return None, ""
    try:
        return voice.synthesize_b64(reply)
    except Exception as e:
        logger.warning("提醒语音合成失败（已降级为纯文本）: %s", e)
        return None, str(e)


def _engine_chat_safe(prompt: str, uid: int) -> str:
    """经 StudyEngine 生成 AI 回复（返回纯文本；异常向上抛由调用方兜底）。

    使用独立的 notify 会话：此前不传 session_id，系统事件 prompt 会混进
    用户主聊天会话的历史里，污染后续对话上下文。
    """
    return _engine.chat(message=prompt, user_id=uid, session_id=f"notify-{uid}")


# ── 视觉感知字段注入（迁移计划阶段 5.3） ──

@heartbeat_bp.after_request
def _inject_vision_fields(response):
    """向 /api/heartbeat 响应注入:
    - vision_request: 当存在待响应的按需 look_around 请求时下发给客户端
    - active_vision: 主动视觉配置 {enabled, interval, camera}，供 CLI 自配置周期观测线程
    - streams: 实时流推送配置 {enabled, interval}，无人订阅/未启用时不推送
    - sensing / tracking: 闲置感知配置（study 无感知硬件，恒 disabled，字段形状保留）

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
        from apps.dsn_study.api.vision import coordinator as _coord
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

    # 主动视觉配置（让 CLI 自配置周期观测线程）
    try:
        from apps.dsn_study.config import Config as _Cfg
        data["active_vision"] = {
            "enabled": bool(getattr(_Cfg, "ACTIVE_VISION_ENABLED", False)),
            "interval": int(getattr(_Cfg, "ACTIVE_VISION_INTERVAL", 300)),
            "camera": getattr(_Cfg, "ACTIVE_VISION_CAMERA", "") or "",
        }
        changed = True
    except Exception:
        logger.warning("注入 active_vision 配置失败", exc_info=True)

    # 实时监控流推送配置：有订阅者或显式启用时让 CLI 周期推帧。
    # 无人观看时不推送，避免无谓的抓帧和网络开销。
    try:
        from apps.dsn_study.config import Config as _Cfg
        from apps.dsn_study.api.vision import stream_hub as _hub
        enabled = bool(getattr(_Cfg, "VISION_STREAMS_ENABLED", False))
        if _hub is not None and _hub.has_local_subscribers():
            enabled = True
        data["streams"] = {
            "enabled": enabled,
            "interval": float(getattr(_Cfg, "STREAM_LOCAL_INTERVAL", 2.0)),
        }
        changed = True
    except Exception:
        logger.warning("注入 streams 推送配置失败", exc_info=True)

    # 闲置时感知配置（study 无麦克风感知硬件链路，恒 disabled；
    # 字段形状保留，CLI 侧据此自配置、不会误启用聆听线程）
    try:
        from apps.dsn_study.config import Config as _Cfg
        data["sensing"] = {
            "enabled": False,
            "cooldown": int(getattr(_Cfg, "SENSING_COOLDOWN", 60)),
            "max_record_secs": float(getattr(_Cfg, "SENSING_MAX_RECORD_SECS", 6.0)),
        }
        data["tracking"] = {
            "enabled": False,
            "cooldown": int(getattr(_Cfg, "SENSING_COOLDOWN", 60)),
            "max_record_secs": float(getattr(_Cfg, "SENSING_MAX_RECORD_SECS", 6.0)),
        }
        changed = True
    except Exception:
        logger.warning("注入 sensing/tracking 配置失败", exc_info=True)

    if changed:
        response.set_data(json.dumps(data, ensure_ascii=False))
        response.headers["Content-Length"] = str(len(response.get_data()))
    return response


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
