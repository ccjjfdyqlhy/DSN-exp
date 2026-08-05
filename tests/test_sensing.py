"""闲置时感知 (idle-time sensing) 单元测试: 数据库 + AI 查询工具。"""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.chat import ChatDBManager
from skills.system.tools.sensing_tools import SensingTools
from config import Config

db_path = os.path.join(tempfile.gettempdir(), "test_sensing_events.db")
try:
    os.remove(db_path)
except OSError:
    pass

print("=== Test 1: DB 表创建 ===")
db = ChatDBManager(db_path=db_path)
db.add_or_update_user(uid=1, nickname="user_a")
db.add_or_update_user(uid=2, nickname="user_b")
conn = db._get_connection()
cols = [r[1] for r in conn.execute("PRAGMA table_info(sensing_events)").fetchall()]
assert "id" in cols and "user_id" in cols and "text" in cols and "source" in cols
assert "rms_level" in cols and "created_at" in cols
print("  PASSED")

print("\n=== Test 2: add_sensing_event ===")
e1 = db.add_sensing_event(user_id=1, text="有人在客厅说话", source="sensing", rms_level=0.12)
e2 = db.add_sensing_event(user_id=1, text="关门的声音", source="sensing", rms_level=0.08)
e3 = db.add_sensing_event(user_id=1, text="有人在客厅说话", source="sensing", rms_level=0.15, chat_id=42)
assert e1 > 0 and e2 > 0 and e3 > 0
print("  PASSED")

print("\n=== Test 3: query 按时间倒序 ===")
records = db.query_sensing_events(user_id=1)
assert len(records) == 3
assert records[0]["text"] == "有人在客厅说话"  # 最新一条排前
assert records[0]["chat_id"] == 42
print("  PASSED")

print("\n=== Test 4: 用户隔离 ===")
other = db.query_sensing_events(user_id=2)
assert other == []
print("  PASSED (uid=2 看不到 uid=1 的记录)")

print("\n=== Test 5: keyword 过滤 ===")
kw = db.query_sensing_events(user_id=1, keyword="关门")
assert len(kw) == 1 and kw[0]["text"] == "关门的声音"
print("  PASSED")

print("\n=== Test 6: limit 过滤 ===")
lim = db.query_sensing_events(user_id=1, limit=1)
assert len(lim) == 1
print("  PASSED")

print("\n=== Test 7: get_last_sensing_time ===")
ts = db.get_last_sensing_time(user_id=1)
assert ts is not None
assert db.get_last_sensing_time(user_id=2) is None
print(f"  last_ts={ts}  PASSED")

print("\n=== Test 8: SensingTools — 配置关闭时拒绝 ===")
saved_flag = getattr(Config, "SENSING_AI_ACCESS_ENABLED", False)
Config.SENSING_AI_ACCESS_ENABLED = False
SensingTools.set_context(db=db)
SensingTools._ctx["_uid"] = 1
r = SensingTools().query_sensing_events()
assert r["enabled"] is False and r["records"] == []
print("  PASSED")

print("\n=== Test 9: SensingTools — 配置开启且按用户隔离 ===")
Config.SENSING_AI_ACCESS_ENABLED = True
r = SensingTools().query_sensing_events()
assert r["enabled"] is True and r["count"] == 3
SensingTools._ctx["_uid"] = 2
r2 = SensingTools().query_sensing_events()
assert r2["count"] == 0
SensingTools._ctx["_uid"] = 1
r3 = SensingTools().query_sensing_events(keyword="关门")
assert r3["count"] == 1
Config.SENSING_AI_ACCESS_ENABLED = saved_flag
print("  PASSED")

db.close_connection()
try:
    os.remove(db_path)
except OSError:
    pass

print("\n=== ALL TESTS PASSED ===")
