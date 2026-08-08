# api/checkin.py
# 打卡系统 (Check-in / Attendance) 后端。
#
# 基于 tracking 子系统。用户通过 minimal.py 按下一个按键 → 主摄像头录像 + 麦克风录音
# → 再按停止 → 视频+音频上传 → 合并存档 → 标记今日已打卡 → 音频 ASR →
# 经 tracking 写入用户跟踪日志（文本前缀【打卡】）。
#
# 每日规则：打卡日按"凌晨4点边界"归并；每天多次打卡，最早一次为当日有效打卡。

from __future__ import annotations

import base64
import logging
import os
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, request, g

logger = logging.getLogger("Checkin")

checkin_bp = Blueprint("checkin_api", __name__)

_db = None
_auth_manager = None
_asr_model = None


def init_checkin_api(db=None, auth_manager=None, asr_model=None):
    """注入依赖（boot.py 启动时调用）。"""
    global _db, _auth_manager, _asr_model
    _db = db
    _auth_manager = auth_manager
    _asr_model = asr_model
    logger.info("Checkin API 已初始化")


@checkin_bp.before_request
def _require_auth():
    if not _auth_manager:
        return jsonify({"error": "Auth unavailable"}), 503
    user = _auth_manager.authenticate(request)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    g.user = user


def _uid() -> int:
    """从认证结果（dict）取 uid。authenticate 返回 {"uid": int, ...}。"""
    if g.user is None:
        return 0
    if isinstance(g.user, dict):
        return int(g.user.get("uid", 0) or 0)
    return int(getattr(g.user, "uid", 0) or 0)


def _asr_text(audio_bytes: bytes) -> str:
    """对音频字节做 ASR，返回文本；失败/不可用返回空串。"""
    global _asr_model
    if not audio_bytes:
        return ""
    if _asr_model is None:
        # 尝试从 boot 懒加载（与 app.py 一致）
        try:
            import boot
            _asr_model = boot.asr_model
        except Exception:
            pass
    if _asr_model is None:
        return ""
    try:
        res = _asr_model.generate(input=audio_bytes, use_itn=True,
                                  batch_size_s=60, language="zh")
        return (res[0].get("text", "").strip() if res else "") or ""
    except Exception as e:
        logger.warning("打卡音频 ASR 失败: %s", e)
        return ""


def _tracking() -> object:
    """从 flask app config 读取 tracking 引擎（懒）。"""
    from flask import current_app
    return current_app.config.get("TRACKING_ENGINE")


def _save_media(video_bytes: bytes, audio_bytes: bytes, uid: int,
                fps: float = 0.0, duration: float = 0.0) -> dict:
    """把视频/音频保存进 tracking 媒体库。返回 {video_path, audio_path, merged_path}。"""
    tracking = _tracking()
    video_path = ""
    audio_path = ""
    merged_path = ""
    if tracking is not None:
        try:
            media = tracking.media
            if audio_bytes:
                audio_path = media.save_audio(audio_bytes, sample_rate=16000, uid=uid) or ""
            if video_bytes:
                video_path = media.save_file(video_bytes, "checkin.mp4", kind="video", uid=uid) or ""
        except Exception:
            logger.warning("保存打卡媒体失败", exc_info=True)
    # 合并存档：视频与音频一起打包（简单合并：优先视频；若仅音频则存音频）
    if video_path and audio_path:
        merged_path = _merge_video_audio(video_path, audio_path, fps=fps, duration=duration)
    if not merged_path:
        merged_path = video_path or audio_path
    return {"video_path": video_path, "audio_path": audio_path, "merged_path": merged_path}


def _merge_video_audio(video_path: str, audio_path: str,
                       fps: float = 0.0, duration: float = 0.0) -> str:
    """用 ffmpeg 把视频和音频合并为一个 mp4，成功返回路径，失败返回空串。

    :param fps: 录像实际帧率（客户端测得）。若 >0 且视频标注 fps 偏差大，
                先归一化视频帧率，避免"视频比实际时长短"。
    :param duration: 真实录制时长（秒），用于 -shortest 对齐。
    """
    import shutil
    import subprocess
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return ""
    merged = video_path.rsplit(".", 1)[0] + "_merged.mp4"

    # 先归一化视频帧率：把容器帧率设为实际 fps，使视频时长=帧数/fps 正确
    norm_video = video_path
    if fps and fps > 1.0:
        norm_video = video_path.rsplit(".", 1)[0] + "_norm.mp4"
        try:
            proc = subprocess.run(
                [ffmpeg, "-y", "-i", video_path, "-r", f"{fps:.2f}",
                 "-c:v", "copy", "-an", norm_video],
                capture_output=True, timeout=30,
            )
            if proc.returncode != 0 or not os.path.exists(norm_video):
                norm_video = video_path  # 归一化失败则用原视频
        except Exception:
            norm_video = video_path

    try:
        cmd = [ffmpeg, "-y", "-i", norm_video, "-i", audio_path,
               "-c:v", "copy", "-c:a", "aac"]
        if duration and duration > 0.5:
            # 用真实时长对齐，避免 -shortest 把视频截到更短
            cmd += ["-t", f"{duration:.2f}"]
        else:
            cmd += ["-shortest"]
        cmd += [merged]
        proc = subprocess.run(cmd, capture_output=True, timeout=30)
        if proc.returncode == 0 and os.path.exists(merged):
            return merged
    except Exception:
        logger.warning("视频/音频合并失败", exc_info=True)
    return ""


@checkin_bp.route("/api/checkin/record", methods=["POST"])
def checkin_record():
    """接收一次打卡：视频+音频（multipart），可选 text。
    流程：保存媒体 → ASR(音频) → tracking 写【打卡】日志 → 标记今日已打卡。
    请求: files: video(可选), audio(可选)；form: text(可选)。
    """
    if _db is None:
        return jsonify({"error": "Database unavailable"}), 503
    uid = _uid()
    if not uid:
        return jsonify({"error": "无法识别用户"}), 401

    video_bytes = (request.files["video"].read()
                   if "video" in request.files else b"")
    audio_bytes = (request.files["audio"].read()
                   if "audio" in request.files else b"")
    provided_text = (request.form.get("text") or "").strip()

    # 客户端上报的真实录制参数（用于修正视频时长）
    try:
        fps = float(request.form.get("fps", 0) or 0)
    except Exception:
        fps = 0.0
    try:
        duration = float(request.form.get("duration", 0) or 0)
    except Exception:
        duration = 0.0

    if not video_bytes and not audio_bytes:
        return jsonify({"error": "缺少 video/audio"}), 400

    # ASR：优先用用户提供的文本，否则对音频识别
    text = provided_text or _asr_text(audio_bytes)

    # 保存媒体 + 合并存档（用真实 fps/时长修正视频时长）
    media = _save_media(video_bytes, audio_bytes, uid, fps=fps, duration=duration)

    # 按 4 点边界归并打卡日，取当前时刻
    now = datetime.now()
    checkin_date = _db.checkin_date_for(now)
    checkin_time = now.strftime("%H:%M:%S")

    # 写入 tracking 日志（文本前缀【打卡】）
    tracking_text = ""
    if text:
        tracking_text = f"【打卡】{text}"
        try:
            tracking = _tracking()
            if tracking is not None:
                tracking.record_text(
                    user_id=uid,
                    content=tracking_text,
                    source="checkin",
                    note=f"打卡 {checkin_date} {checkin_time}",
                )
        except Exception:
            logger.warning("打卡 tracking 写入失败", exc_info=True)

    # 记录打卡（同一天最早一次为有效打卡）
    try:
        event_id = _db.add_checkin(
            user_id=uid,
            checkin_date=checkin_date,
            checkin_time=checkin_time,
            media_path=media.get("merged_path", "") or media.get("video_path", ""),
            video_path=media.get("video_path", ""),
            audio_path=media.get("audio_path", ""),
            text=tracking_text,
        )
    except Exception as e:
        logger.error("写入打卡记录失败: %s", e)
        return jsonify({"error": "Database error"}), 500

    today = _db.get_today_checkin(uid, checkin_date)
    return jsonify({
        "success": True,
        "checkin_id": event_id,
        "checkin_date": checkin_date,
        "checkin_time": checkin_time,
        "text": tracking_text,
        "today_checkin_time": (today or {}).get("checkin_time", checkin_time),
        "media": {k: v for k, v in media.items() if v},
    })


@checkin_bp.route("/api/checkin/status", methods=["GET"])
def checkin_status():
    """查询今日（4点边界）打卡状态：是否已打卡、今日最早打卡时间、累计天数。"""
    if _db is None:
        return jsonify({"error": "Database unavailable"}), 503
    uid = _uid()
    now = datetime.now()
    checkin_date = _db.checkin_date_for(now)
    today = _db.get_today_checkin(uid, checkin_date)
    count = _db.count_checkin_days(uid)
    return jsonify({
        "success": True,
        "checked_in": today is not None,
        "checkin_date": checkin_date,
        "checkin_time": (today or {}).get("checkin_time", ""),
        "today_count": 0 if today is None else 1,
        "total_days": count,
    })


@checkin_bp.route("/api/checkin/history", methods=["GET"])
def checkin_history():
    """查询打卡历史（按时间倒序）。"""
    if _db is None:
        return jsonify({"error": "Database unavailable"}), 503
    uid = _uid()
    try:
        limit = max(1, min(100, int(request.args.get("limit", 30))))
    except Exception:
        limit = 30
    records = _db.query_checkins(uid, limit=limit)
    return jsonify({"success": True, "records": records, "count": len(records)})
