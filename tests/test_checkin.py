"""打卡系统 (check-in) 单元测试: 每日规则 + 数据库存取 + tracking 联动。

覆盖:
  - checkin_date_for 凌晨4点边界归并
  - 每天多次打卡, 最早一次为有效打卡
  - 打卡状态/历史查询, 累计天数
"""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from apps.dsn.db.chat import ChatDBManager
from apps.dsn.tracking.core import TrackingEngine

workdir = tempfile.mkdtemp(prefix="test_checkin_")
db_path = os.path.join(workdir, "chats.db")
tracking_db = os.path.join(workdir, "tracking.db")
media_root = os.path.join(workdir, "media")

db = ChatDBManager(db_path=db_path)
db.add_or_update_user(uid=1, nickname="user_a")

print("=== Test 1: 凌晨4点边界归并 ===")
assert db.checkin_date_for(datetime(2026, 8, 8, 3, 0)) == "2026-08-07"   # 凌晨3点属于前一天
assert db.checkin_date_for(datetime(2026, 8, 8, 4, 0)) == "2026-08-08"   # 凌晨4点属于当天
assert db.checkin_date_for(datetime(2026, 8, 8, 23, 59)) == "2026-08-08"
assert db.checkin_date_for(datetime(2026, 8, 8, 0, 0)) == "2026-08-07"
print("  PASSED")

print("\n=== Test 2: 每天多次打卡, 最早一次为有效打卡 ===")
d1 = db.add_checkin(user_id=1, checkin_date="2026-08-08", checkin_time="08:30:00",
                    media_path="/tmp/a.mp4", text="【打卡】早起")
d2 = db.add_checkin(user_id=1, checkin_date="2026-08-08", checkin_time="20:00:00",
                    media_path="/tmp/b.mp4", text="【打卡】晚安")
assert d1 > 0 and d2 > 0
today = db.get_today_checkin(1, "2026-08-08")
assert today["checkin_time"] == "08:30:00", today   # 最早一次为有效打卡
assert db.get_valid_checkin_time(1, "2026-08-08") == "08:30:00"
print("  PASSED (有效打卡 = 最早 08:30:00)")

print("\n=== Test 3: 累计天数与历史 ===")
db.add_checkin(user_id=1, checkin_date="2026-08-07", checkin_time="09:00:00", text="")
db.add_checkin(user_id=1, checkin_date="2026-08-09", checkin_time="10:00:00", text="")
assert db.count_checkin_days(1) == 3   # 三个不同打卡日
hist = db.query_checkins(1, limit=10)
assert len(hist) == 4 and hist[0]["checkin_date"] == "2026-08-09"
print("  PASSED")

print("\n=== Test 4: 用户隔离 ===")
db.add_or_update_user(uid=2, nickname="user_b")
assert db.get_today_checkin(2, "2026-08-08") is None
assert db.count_checkin_days(2) == 0
print("  PASSED")

print("\n=== Test 5: tracking 联动 — 打卡写入【打卡】文本记录 ===")
engine = TrackingEngine(db=db, media_root=media_root, db_path=tracking_db)
tracking_text = "【打卡】今天也要加油"
engine.record_text(user_id=1, content=tracking_text, source="checkin",
                   note="打卡 2026-08-08 08:30:00")
obs = engine.query_observations(user_id=1, keyword="打卡")
assert any(o["payload"].startswith("【打卡】") for o in obs)
assert any(o["payload"] == tracking_text for o in obs)
assert any(o["source"] == "checkin" for o in obs)
print("  PASSED")

print("\n=== Test 6: 连续打卡天数 (streak) ===")
from datetime import datetime, timedelta
today = datetime.now().date()
# 造一个连续 3 天的序列（含今天）
for i in range(3):
    d = (today - timedelta(days=i)).isoformat()
    db.add_checkin(user_id=2, checkin_date=d, checkin_time="08:00:00", text="")
assert db.compute_checkin_streak(2) == 3, db.compute_checkin_streak(2)
# 再补一天 → 连续 4
db.add_checkin(user_id=2, checkin_date=(today - timedelta(days=3)).isoformat(),
               checkin_time="08:00:00", text="")
assert db.compute_checkin_streak(2) == 4, db.compute_checkin_streak(2)
# 断开：更早一天缺，不影响从今天往前的连续
print("  PASSED (streak=4)")

print("\n=== Test 7: 月度日历 checkin_month ===")
month = db.checkin_month(2, today.year, today.month)
assert month, month
# 日期按天聚合
dates = [m["date"] for m in month]
assert (today - timedelta(days=3)).isoformat() in dates
# 每条有 checkins 列表
for m in month:
    assert "checkins" in m and len(m["checkins"]) >= 1
    assert "checkin_time" in m["checkins"][0] and "media_path" in m["checkins"][0]
print(f"  本月 {len(month)} 个打卡日: {dates[:5]}...")
print("  PASSED")

print("\n=== Test 8: 跨月隔离 ===")
assert db.checkin_month(2, today.year, ((today.month % 12) + 1)) == []
assert db.checkin_month(2, today.year - 1, today.month) == []
print("  PASSED")

db.close_connection()
import shutil as _sh
_sh.rmtree(workdir, ignore_errors=True)
print("\n=== ALL CHECKIN TESTS PASSED ===")
