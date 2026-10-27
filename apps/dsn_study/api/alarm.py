# apps/dsn_study/api/alarm.py
# 闹钟系统 REST API — 自 apps/dsn/api/alarm.py 移植（dsn_study 功能补齐阶段 1）。
# 原版零 apps.dsn 依赖（仅 flask + 注入的 db），迁移 SQL 对 users 表的存在性做了防御
# （study 库无 users 表——认证为本地单用户垫片）。
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
            user_id INTEGER NOT NULL DEFAULT 0,
            time TEXT NOT NULL,
            days TEXT NOT NULL DEFAULT '[]',
            message TEXT NOT NULL DEFAULT '',
            sound TEXT,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
    """)
    # 迁移：为旧表补充 user_id 列，并将遗留闹钟归属到首个管理员用户
    # （study 库无 users 表，归属查询失败时保留默认归属 uid=1）
    cols = [r[1] for r in conn.execute("PRAGMA table_info(alarms)").fetchall()]
    if "user_id" not in cols:
        conn.execute("ALTER TABLE alarms ADD COLUMN user_id INTEGER NOT NULL DEFAULT 0")
        try:
            conn.execute(
                "UPDATE alarms SET user_id = "
                "(SELECT uid FROM users ORDER BY is_admin DESC, uid ASC LIMIT 1) "
                "WHERE user_id = 0"
            )
        except Exception:
            conn.execute("UPDATE alarms SET user_id = 1 WHERE user_id = 0")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_alarms_user ON alarms(user_id)")
    conn.commit()


@alarm_bp.before_request
def _require_auth():
    if not _auth_manager:
        return jsonify({"error": "Auth unavailable"}), 503
    user = _auth_manager.authenticate(request)
    if not user:
        return jsonify({"error": "Unauthorized"}), 401
    g.user = user


# ── 辅助 ──

def _row_to_alarm(row):
    return {
        "id": row["id"],
        "user_id": row["user_id"],
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
        # 修复：不校验类型时，POST days=3 / null 会对标量迭代抛未捕获
        # TypeError → 500；字符串 "Mon" 会被逐字符校验，错误信息也令人困惑。
        if not isinstance(data["days"], list):
            return "days 需为星期列表"
        for d in data["days"]:
            if d not in WEEKDAYS:
                return f"无效星期: {d}, 可选: {WEEKDAYS}"
    return None


# ── CRUD ──

@alarm_bp.route("/api/alarms", methods=["POST"])
def create_alarm():
    uid = g.user.get("uid", 0)
    if not uid:
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(force=True, silent=True) or {}
    err = _validate_alarm(data)
    if err:
        return jsonify({"error": err}), 400

    # 修复：id 此前截断为 8 位十六进制，闹钟数量增长或恶意枚举下可能撞主键
    # → 未捕获 IntegrityError → 500。id 对前端是透明字符串，用完整 uuid。
    alarm_id = str(uuid.uuid4())
    alarm = {
        "id": alarm_id,
        "user_id": uid,
        "time": data["time"],
        "days": data.get("days", WEEKDAYS.copy()),
        "message": data.get("message", "⏰ 闹钟响了!"),
        "sound": data.get("sound"),
        "enabled": True,
        "created_at": datetime.now().isoformat(),
    }
    conn = _db._get_connection()
    conn.execute(
        "INSERT INTO alarms (id, user_id, time, days, message, sound, enabled, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (alarm["id"], alarm["user_id"], alarm["time"], json.dumps(alarm["days"]),
         alarm["message"], alarm.get("sound"), int(alarm["enabled"]), alarm["created_at"]),
    )
    conn.commit()
    return jsonify({"ok": True, "alarm": alarm}), 201


@alarm_bp.route("/api/alarms", methods=["GET"])
def list_alarms():
    uid = g.user.get("uid", 0)
    if not uid:
        return jsonify({"error": "Unauthorized"}), 401
    conn = _db._get_connection()
    rows = conn.execute(
        "SELECT * FROM alarms WHERE user_id=? ORDER BY time", (uid,)
    ).fetchall()
    return jsonify({"alarms": [_row_to_alarm(r) for r in rows]})


@alarm_bp.route("/api/alarms/<alarm_id>", methods=["DELETE"])
def delete_alarm(alarm_id):
    uid = g.user.get("uid", 0)
    if not uid:
        return jsonify({"error": "Unauthorized"}), 401
    conn = _db._get_connection()
    row = conn.execute(
        "SELECT * FROM alarms WHERE id=? AND user_id=?", (alarm_id, uid)
    ).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    conn.execute("DELETE FROM alarms WHERE id=? AND user_id=?", (alarm_id, uid))
    conn.commit()
    return jsonify({"ok": True})


@alarm_bp.route("/api/alarms/<alarm_id>", methods=["PATCH"])
def update_alarm(alarm_id):
    uid = g.user.get("uid", 0)
    if not uid:
        return jsonify({"error": "Unauthorized"}), 401
    conn = _db._get_connection()
    row = conn.execute(
        "SELECT * FROM alarms WHERE id=? AND user_id=?", (alarm_id, uid)
    ).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404

    data = request.get_json(force=True, silent=True) or {}
    # 修复：PATCH 对 time 此前不做校验，坏数据（"25:99"/"abc"/null）直接入库，
    # 之后 GET /api/alarms/now 的解析路径每次都抛异常 → 该用户闹钟接口
    # 永久 500，直到手工修库。更新路径与创建路径同标准。
    if "time" in data:
        err = _validate_alarm({"time": data["time"]})
        if err:
            return jsonify({"error": err}), 400
    if "message" in data and data["message"] is not None \
            and not isinstance(data["message"], str):
        return jsonify({"error": "message 需为字符串"}), 400
    if "sound" in data and data["sound"] is not None \
            and not isinstance(data["sound"], str):
        return jsonify({"error": "sound 需为字符串"}), 400
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
        vals.append(uid)
        conn.execute(f"UPDATE alarms SET {','.join(sets)} WHERE id=? AND user_id=?", vals)
        conn.commit()
        row = conn.execute(
            "SELECT * FROM alarms WHERE id=? AND user_id=?", (alarm_id, uid)
        ).fetchone()
    return jsonify({"ok": True, "alarm": _row_to_alarm(row)})


@alarm_bp.route("/api/alarms/<alarm_id>/dismiss", methods=["POST"])
def dismiss_alarm(alarm_id):
    """静音闹钟：将该闹钟今天及未来7天的触发标记为已忽略。"""
    uid = g.user.get("uid", 0)
    if not uid:
        return jsonify({"error": "Unauthorized"}), 401
    conn = _db._get_connection()
    row = conn.execute(
        "SELECT * FROM alarms WHERE id=? AND user_id=?", (alarm_id, uid)
    ).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    with fired_log_lock:
        for offset in range(8):
            d = (datetime.now() + timedelta(days=offset)).strftime("%Y-%m-%d")
            dismissed_log.add(f"{alarm_id}:{d}")
    return jsonify({"ok": True, "alarm_id": alarm_id})


# ── 当前时间 + 下一个闹钟倒计时 ──

@alarm_bp.route("/api/alarms/now", methods=["GET"])
def now_info():
    uid = g.user.get("uid", 0)
    if not uid:
        return jsonify({"error": "Unauthorized"}), 401
    now = datetime.now()
    today_weekday = WEEKDAYS[now.weekday()]
    conn = _db._get_connection()
    all_alarms = conn.execute(
        "SELECT * FROM alarms WHERE user_id=? ORDER BY time", (uid,)
    ).fetchall()

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
            # 容错：库里的坏行（历史脏数据）只跳过本条，不能让整个接口 500
            try:
                h, m = map(int, str(a["time"]).split(":"))
                alarm_dt = check_date.replace(hour=h, minute=m, second=0, microsecond=0)
            except (ValueError, AttributeError, TypeError):
                logger.warning("闹钟 %s 的时间字段非法: %r，已跳过", a["id"], a["time"])
                continue
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
    uid = g.user.get("uid", 0)
    if not uid:
        return jsonify({"error": "Unauthorized"}), 401
    conn = _db._get_connection()
    all_alarms = conn.execute(
        "SELECT * FROM alarms WHERE user_id=?", (uid,)
    ).fetchall()
    # 修复：fired_today 此前直接 len(fired_log)——那是全局集合（含其他用户
    # 与昨天残留），统计完全失真。按"当前用户的闹钟 id + 今天的日期"过滤。
    today = datetime.now().strftime("%Y-%m-%d")
    my_ids = {r["id"] for r in all_alarms}
    with fired_log_lock:
        fired_count = sum(
            1 for k in fired_log
            if k.rsplit(":", 1)[0] in my_ids and k.endswith(f":{today}")
        )
    return jsonify({
        "alarm_count": len(all_alarms),
        "fired_today": fired_count,
    })


# ── 心跳检查（供 heartbeat.py 调用）──

#: 触发宽窗（分钟）：闹钟时刻已过但在窗口内仍补触发。
#: 心跳依赖前端轮询，浏览器休眠/网络抖动会让"精确等于当前分钟"错过触发，
#: 闹钟当天静默丢失；完全放开 `<=` 又会让重启后的应用把今天所有错过的
#: 闹钟一次性引爆。默认 10 分钟平衡两者。
ALARM_TRIGGER_GRACE_MINUTES = 10


def _alarm_minutes(time_str: str) -> Optional[int]:
    """"HH:MM" → 当天分钟数；非法返回 None。"""
    try:
        h, m = map(int, str(time_str).split(":"))
        if not (0 <= h <= 23 and 0 <= m <= 59):
            return None
        return h * 60 + m
    except (ValueError, AttributeError, TypeError):
        return None


def check_and_trigger(uid: int) -> list[dict]:
    """返回当前时刻（含宽窗内错过未触发的）应触发的闹钟列表。"""
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    weekday = WEEKDAYS[now.weekday()]
    current_minutes = now.hour * 60 + now.minute

    conn = _db._get_connection()
    all_alarms = conn.execute(
        "SELECT * FROM alarms WHERE user_id=?", (uid,)
    ).fetchall()

    triggered = []
    for r in all_alarms:
        a = _row_to_alarm(r)
        if not a["enabled"]:
            continue
        if weekday not in a["days"]:
            continue
        # 修复：严格 `time != current_time` 时，心跳间隔 > 60s / 浏览器休眠 /
        # 网络抖动导致该分钟内没有心跳的话，闹钟当天不响也不补触发。
        # 改为"已到时刻且在宽窗内未触发则补触发"。
        alarm_min = _alarm_minutes(a["time"])
        if alarm_min is None:
            logger.warning("闹钟 %s 的时间字段非法: %r，已跳过", a["id"], a["time"])
            continue
        if not (alarm_min <= current_minutes
                <= alarm_min + ALARM_TRIGGER_GRACE_MINUTES):
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


def _prune_logs_once() -> None:
    """单次清理（供后台线程与单测复用）：早于昨天的记录才删，
    保留昨天（当日历史）、今天与全部未来日期（dismiss 的多天静音）。"""
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    def _expired(key: str) -> bool:
        try:
            date_part = key.rsplit(":", 1)[1]
        except IndexError:
            return True
        # ISO 日期可直接字典序比较
        return date_part < yesterday

    with fired_log_lock:
        # 先物化再删除：difference_update 直接喂生成器（迭代同一个 set）
        # 会抛 "Set changed size during iteration"——原实现的清理线程正是
        # 因此在第一次触发时静默死亡。
        expired_fired = [k for k in fired_log if _expired(k)]
        expired_dismissed = [k for k in dismissed_log if _expired(k)]
        fired_log.difference_update(expired_fired)
        dismissed_log.difference_update(expired_dismissed)


def _cleanup_fired_log():
    """后台线程：定期清理过期 fired_log / dismissed_log 记录。

    修复：清理逻辑此前只保留以今天/昨天结尾的 key——dismiss 写入的
    未来 7 天静音记录会在 60 秒内被删掉，"静音几天"实际只静音当天。
    """
    while True:
        threading.Event().wait(60)
        _prune_logs_once()


# 启动清理线程
_cleanup_thread = threading.Thread(target=_cleanup_fired_log, daemon=True)
_cleanup_thread.start()
