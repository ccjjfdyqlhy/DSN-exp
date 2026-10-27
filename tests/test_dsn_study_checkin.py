# tests/test_dsn_study_checkin.py
# dsn_study 打卡 + 学习跟踪 lite（阶段 4，FEATURE_GAP.md）验收。
# 不依赖 Flask 服务：直接测数据层/门面；API 经 test_client 冒烟。

import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from apps.dsn_study.db.question_bank import QuestionBankDBManager
from apps.dsn_study.db.checkin_store import CheckinStore
from apps.dsn_study.tracking_lite import TrackingStore, StudyLog


@pytest.fixture(scope="module")
def db():
    return QuestionBankDBManager(
        db_path=tempfile.mkdtemp(prefix="dsn_study_checkin_") + "/qb.db")


@pytest.fixture(scope="module")
def checkin(db):
    return CheckinStore(db)


@pytest.fixture(scope="module")
def studylog(tmp_path_factory, checkin):
    store = TrackingStore(
        db_path=str(tmp_path_factory.mktemp("dsn_study_trk") / "tracking.db"))
    return StudyLog(store, checkin_store=checkin)


# ── 打卡数据层 ──

def test_checkin_date_boundary():
    # 凌晨 3 点属前一天，4 点起属当天
    assert CheckinStore.checkin_date_for(datetime(2026, 8, 8, 3, 0)) == "2026-08-07"
    assert CheckinStore.checkin_date_for(datetime(2026, 8, 8, 4, 0)) == "2026-08-08"


def test_checkin_record_and_validity(checkin):
    day = "2026-08-08"
    id1 = checkin.add_checkin(1, day, "08:30:00", text="第一次")
    id2 = checkin.add_checkin(1, day, "20:00:00", text="第二次")
    # 最早一次为有效打卡
    today = checkin.get_today_checkin(1, day)
    assert today["id"] == id1 and today["is_valid"] == 1
    assert today["checkin_time"] == "08:30:00"
    rows = checkin.query_checkins(1)
    assert len(rows) == 2 and {r["is_valid"] for r in rows} == {1, 0}
    assert checkin.count_checkin_days(1) == 1


def test_checkin_streak_and_calendar(checkin):
    uid = 7
    today = datetime.now()
    for offset in (0, 1, 2):
        d = (today - timedelta(days=offset)).strftime("%Y-%m-%d")
        checkin.add_checkin(uid, d, "09:00:00")
    assert checkin.compute_checkin_streak(uid) == 3

    month = today.strftime("%Y-%m")
    cal = checkin.month_calendar(uid, today.year, today.month)
    assert cal[today.strftime("%Y-%m-%d")] is True
    assert sum(1 for v in cal.values() if v) >= 3


# ── 学习日志门面 ──

def test_studylog_sessions_and_minutes(studylog):
    studylog.record_session(5, "数学", 45, note="刷函数题")
    studylog.record_session(5, "英语", 30)
    sessions = studylog.sessions(5)
    assert len(sessions) == 2
    assert sessions[0]["meta"]["subject"] == "英语"   # 倒序
    by_day = studylog.minutes_by_day(5, days=7)
    assert sum(by_day.values()) == 75.0


def test_studylog_daily_report(studylog, checkin):
    uid = 9
    now = datetime.now()
    day = now.strftime("%Y-%m-%d")
    # 打卡写入走 4 点边界归并（与 API 语义一致：凌晨属于前一天）
    checkin.add_checkin(uid, CheckinStore.checkin_date_for(now), "08:00:00", text="早打卡")
    studylog.record_session(uid, "物理", 60)
    report = studylog.daily_report(uid, day)
    assert report["success"] and report["date"] == day
    assert report["study"]["total_minutes"] == 60.0
    assert report["study"]["subjects"] == {"物理": 60.0}
    assert report["checkin"]["checked_in"] is True
    assert report["checkin"]["streak"] >= 1
    # plan 段落：注入了 plan_engine 才有（boot 路径由 API 冒烟覆盖）
    if studylog.plan_engine is not None:
        assert "plan" in report


def test_daily_report_checkin_matches_write_hour(studylog, checkin, monkeypatch):
    """回归：当日报告必须能读到「当天写入」的打卡（4 点边界两侧都要成立）。

    历史缺陷：daily_report 把自然日 strptime 成午夜（hour=0）再喂给
    checkin_date_for —— 午夜恒 <4，于是恒定回退一天；而写入侧用的是真实时刻。
    两侧口径不一致，导致 04:00~24:00 之间写入的打卡在当日报告里 checked_in
    恒为 False，表现为「20/24 小时必挂」的时间相关用例。

    本用例用受控时钟覆盖边界两侧（03:30 / 09:30），与运行时刻无关。
    """
    import apps.dsn_study.db.checkin_store as checkin_mod
    import apps.dsn_study.tracking_lite.studylog as studylog_mod

    base = datetime(2026, 8, 8, 0, 0, 0)

    class _FakeDateTime(datetime):
        fake = base

        @classmethod
        def now(cls, tz=None):
            return cls.fake

    monkeypatch.setattr(checkin_mod, "datetime", _FakeDateTime)
    monkeypatch.setattr(studylog_mod, "datetime", _FakeDateTime)

    for hour in (3, 9):
        _FakeDateTime.fake = base.replace(hour=hour, minute=30)
        now = _FakeDateTime.fake
        uid = 200 + hour
        day = now.strftime("%Y-%m-%d")

        checkin.add_checkin(uid, CheckinStore.checkin_date_for(now), "08:00:00", text="打卡")
        report = studylog.daily_report(uid, day)

        assert report["checkin"]["checked_in"] is True, f"{hour:02d}:30 打卡未计入当日报告"
        assert report["checkin"]["streak"] >= 1, f"{hour:02d}:30 连续天数未计入"


# ── API 冒烟（boot 装配 + 路由） ──

@pytest.fixture(scope="module")
def study_app():
    import os
    os.environ["QUESTION_BANK_DB_PATH"] = (
        tempfile.mkdtemp(prefix="dsn_study_checkin_boot_") + "/qb.db")
    from apps.dsn_study.boot import create_application
    return create_application()


def test_checkin_api_flow(study_app):
    client = study_app.test_client()
    rv = client.post("/api/checkin/record", json={"text": "今日开始学习"})
    assert rv.status_code == 200
    body = rv.get_json()
    assert body["success"] and body["streak"] >= 1

    rv = client.get("/api/checkin/status")
    assert rv.get_json()["checked_in"] is True

    rv = client.get("/api/checkin/calendar")
    cal = rv.get_json()
    assert cal["success"] and cal["checked_count"] >= 1

    rv = client.get("/api/checkin/history")
    assert rv.get_json()["count"] >= 1


def test_studylog_api_flow(study_app):
    client = study_app.test_client()
    rv = client.post("/api/studylog/session",
                     json={"subject": "化学", "minutes": 25, "note": "元素周期表"})
    assert rv.status_code == 201

    rv = client.post("/api/studylog/session", json={"subject": "化学", "minutes": 0})
    assert rv.status_code == 400

    rv = client.get("/api/studylog/report")
    report = rv.get_json()
    assert report["success"] and report["study"]["total_minutes"] >= 25.0

    rv = client.get("/api/studylog/sessions")
    assert rv.get_json()["count"] >= 1
