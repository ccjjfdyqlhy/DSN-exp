# api/alarm.py
# 闹钟系统 REST API — Flask Blueprint
# 与 temp/alarm/server.py 功能对齐：独立 alarms 表 + 星期调度 + 心跳触发 + 倒计时

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify, g

logger = logging.getLogger("AlarmAPI")

alarm_bp = Blueprint("alarm_api", __name__)

_db = None
_auth_manager = None

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# ── 内存状态 ──
fired_log: set[str] = set()
dismissed_log: set[str] = set()  # "<alarm_id>:<YYYY-MM-DD>"
fired_log_lock = threading.Lock()


def init_alarm_api(db, auth_manager):
    global _db, _auth_manager
    _db = db
    _auth_manager = auth_manager
    _init_alarm_table()


def _init_alarm_table():
    conn = _db._get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS alarms (
            id TEXT PRIMARY KEY,
            time TEXT NOT NULL,
            days TEXT NOT NULL DEFAULT '[]',
            message TEXT NOT NULL DEFAULT '',
            sound TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()


@alarm_bp.before_request
def _require_auth():
    if _auth_manager:
        user = _auth_manager.authenticate(request)
        g.user = user
    else:
        g.user = {"uid": 0}


# ── 辅助 ──

def _row_to_alarm(row):
    return {
        "id": row["id"],
        "time": row["time"],
        "days": json.loads(row["days"]),
        "message": row["message"],
        "sound": row["sound"],
        "enabled": bool(row["enabled"]),
        "created_at": row["created_at"],
    }


def _validate_alarm(data):
    if not data or "time" not in data:
        return "缺少 time"
    try:
        datetime.strptime(data["time"], "%H:%M")
    except (ValueError, TypeError):
        return "time 格式需为 HH:MM"
    if "days" in data:
        for d in data["days"]:
            if d not in WEEKDAYS:
                return f"无效星期: {d}, 可选: {WEEKDAYS}"
    return None


# ── CRUD ──

@alarm_bp.route("/api/alarms", methods=["POST"])
def create_alarm():
    data = request.get_json(force=True, silent=True) or {}
    err = _validate_alarm(data)
    if err:
        return jsonify({"error": err}), 400

    alarm_id = str(uuid.uuid4())[:8]
    alarm = {
        "id": alarm_id,
        "time": data["time"],
        "days": data.get("days", WEEKDAYS.copy()),
        "message": data.get("message", "⏰ 闹钟响了!"),
        "sound": data.get("sound"),
        "enabled": True,
        "created_at": datetime.now().isoformat(),
    }
    conn = _db._get_connection()
    conn.execute(
        "INSERT INTO alarms (id, time, days, message, sound, enabled, created_at) VALUES (?,?,?,?,?,?,?)",
        (alarm["id"], alarm["time"], json.dumps(alarm["days"]),
         alarm["message"], alarm.get("sound"), int(alarm["enabled"]), alarm["created_at"]),
    )
    conn.commit()
    return jsonify({"ok": True, "alarm": alarm}), 201


@alarm_bp.route("/api/alarms", methods=["GET"])
def list_alarms():
    conn = _db._get_connection()
    rows = conn.execute("SELECT * FROM alarms ORDER BY time").fetchall()
    return jsonify({"alarms": [_row_to_alarm(r) for r in rows]})


@alarm_bp.route("/api/alarms/<alarm_id>", methods=["DELETE"])
def delete_alarm(alarm_id):
    conn = _db._get_connection()
    row = conn.execute("SELECT * FROM alarms WHERE id=?", (alarm_id,)).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    conn.execute("DELETE FROM alarms WHERE id=?", (alarm_id,))
    conn.commit()
    return jsonify({"ok": True})


@alarm_bp.route("/api/alarms/<alarm_id>", methods=["PATCH"])
def update_alarm(alarm_id):
    conn = _db._get_connection()
    row = conn.execute("SELECT * FROM alarms WHERE id=?", (alarm_id,)).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404

    data = request.get_json(force=True, silent=True) or {}
    sets = []
    vals = []
    for k in ("time", "message", "sound"):
        if k in data:
            sets.append(f"{k}=?")
            vals.append(data[k])
    if "enabled" in data:
        sets.append("enabled=?")
        vals.append(int(bool(data["enabled"])))
    if "days" in data:
        err = _validate_alarm({"time": row["time"], "days": data["days"]})
        if err:
            return jsonify({"error": err}), 400
        sets.append("days=?")
        vals.append(json.dumps(data["days"]))
    if sets:
        vals.append(alarm_id)
        conn.execute(f"UPDATE alarms SET {','.join(sets)} WHERE id=?", vals)
        conn.commit()
        row = conn.execute("SELECT * FROM alarms WHERE id=?", (alarm_id,)).fetchone()
    return jsonify({"ok": True, "alarm": _row_to_alarm(row)})


@alarm_bp.route("/api/alarms/<alarm_id>/dismiss", methods=["POST"])
def dismiss_alarm(alarm_id):
    """静音闹钟：将该闹钟今天及未来7天的触发标记为已忽略。"""
    conn = _db._get_connection()
    row = conn.execute("SELECT * FROM alarms WHERE id=?", (alarm_id,)).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    today = datetime.now().strftime("%Y-%m-%d")
    with fired_log_lock:
        for offset in range(8):
            d = (datetime.now() + timedelta(days=offset)).strftime("%Y-%m-%d")
            dismissed_log.add(f"{alarm_id}:{d}")
    return jsonify({"ok": True, "alarm_id": alarm_id})


# ── 当前时间 + 下一个闹钟倒计时 ──

@alarm_bp.route("/api/alarms/now", methods=["GET"])
def now_info():
    now = datetime.now()
    today_weekday = WEEKDAYS[now.weekday()]
    conn = _db._get_connection()
    all_alarms = conn.execute("SELECT * FROM alarms ORDER BY time").fetchall()

    next_alarm = None
    for offset in range(8):
        check_date = now + timedelta(days=offset)
        wd = WEEKDAYS[check_date.weekday()]
        for r in all_alarms:
            a = _row_to_alarm(r)
            if not a["enabled"]:
                continue
            if wd not in a["days"]:
                continue
            h, m = map(int, a["time"].split(":"))
            alarm_dt = check_date.replace(hour=h, minute=m, second=0, microsecond=0)
            if alarm_dt <= now and offset == 0:
                continue
            key = f"{a['id']}:{check_date.strftime('%Y-%m-%d')}"
            with fired_log_lock:
                fired = key in fired_log
            if next_alarm is None or alarm_dt < next_alarm["datetime"]:
                next_alarm = {
                    "id": a["id"],
                    "time": a["time"],
                    "message": a["message"],
                    "sound": a["sound"],
                    "date": check_date.strftime("%Y-%m-%d"),
                    "weekday": wd,
                    "datetime": alarm_dt,
                    "fired": fired,
                }

    result = {
        "server_time": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M"),
        "weekday": today_weekday,
    }

    if next_alarm:
        delta = next_alarm["datetime"] - now
        total_secs = int(delta.total_seconds())
        hours, remainder = divmod(total_secs, 3600)
        minutes, seconds = divmod(remainder, 60)
        result["next_alarm"] = {
            "id": next_alarm["id"],
            "time": next_alarm["time"],
            "message": next_alarm["message"],
            "sound": next_alarm["sound"],
            "date": next_alarm["date"],
            "weekday": next_alarm["weekday"],
            "countdown": f"{hours:02d}:{minutes:02d}:{seconds:02d}",
            "countdown_seconds": total_secs,
            "fired": next_alarm["fired"],
        }
    else:
        result["next_alarm"] = None

    return jsonify(result)


# ── 状态 ──

@alarm_bp.route("/api/alarms/status", methods=["GET"])
def alarm_status():
    conn = _db._get_connection()
    all_alarms = conn.execute("SELECT * FROM alarms").fetchall()
    with fired_log_lock:
        fired_count = len(fired_log)
    return jsonify({
        "alarm_count": len(all_alarms),
        "fired_today": fired_count,
    })


# ── 心跳检查（供 heartbeat.py 调用）──

def check_and_trigger() -> list[dict]:
    """返回当前时刻应触发的闹钟列表（供 heartbeat 端点调用）。"""
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    weekday = WEEKDAYS[now.weekday()]
    current_time = now.strftime("%H:%M")

    conn = _db._get_connection()
    all_alarms = conn.execute("SELECT * FROM alarms").fetchall()

    triggered = []
    for r in all_alarms:
        a = _row_to_alarm(r)
        if not a["enabled"]:
            continue
        if weekday not in a["days"]:
            continue
        if a["time"] != current_time:
            continue
        key = f"{a['id']}:{today}"
        with fired_log_lock:
            if key in fired_log or key in dismissed_log:
                continue
            fired_log.add(key)

        triggered.append({
            "id": a["id"],
            "time": a["time"],
            "message": a["message"],
            "sound": a.get("sound"),
        })

    return triggered


def _cleanup_fired_log():
    """后台线程：定期清理过期 fired_log 记录。"""
    while True:
        threading.Event().wait(60)
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        valid = {f":{today}", f":{yesterday}"}
        with fired_log_lock:
            fired_log.difference_update(
                k for k in fired_log if not any(k.endswith(s) for s in valid)
            )
            dismissed_log.difference_update(
                k for k in dismissed_log if not any(k.endswith(s) for s in valid)
            )


# 启动清理线程
_cleanup_thread = threading.Thread(target=_cleanup_fired_log, daemon=True)
_cleanup_thread.start()
