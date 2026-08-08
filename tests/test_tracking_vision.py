"""主动视觉观察服务 + tracking 分天存储 单元测试。

覆盖:
  - 用户跟踪日志按天分表存储 (tracking_events_YYYYMMDD)
  - VisionObservationService: 照片保存 + VisionModel 描述 → 写入 tracking 日志
"""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
from db.chat import ChatDBManager
from tracking.core import TrackingEngine
from tracking.store import TrackingStore
from tracking.vision_observe import VisionObservationService
from config import Config

workdir = tempfile.mkdtemp(prefix="test_vision_")
db_path = os.path.join(workdir, "chats.db")
tracking_db = os.path.join(workdir, "tracking.db")
media_root = os.path.join(workdir, "media")

db = ChatDBManager(db_path=db_path)
db.add_or_update_user(uid=1, nickname="user_a")

print("=== Test 1: 分天存储 — 不同日期落到不同表 ===")
store = TrackingStore(db_path=tracking_db)
yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
today = datetime.now().strftime("%Y%m%d")
e1 = store.add_event(user_id=1, etype="text", payload="昨天的日志", _day=yesterday)
e2 = store.add_event(user_id=1, etype="text", payload="今天的日志", _day=today)
assert e1 > 0 and e2 > 0
tables = store.day_tables()
assert f"tracking_events_{yesterday}" in tables
assert f"tracking_events_{today}" in tables
# 各自独立：昨天表只有昨天数据
conn = store._get_connection()
y_rows = conn.execute(
    f"SELECT COUNT(*) AS n FROM tracking_events_{yesterday} WHERE user_id=1"
).fetchone()
t_rows = conn.execute(
    f"SELECT COUNT(*) AS n FROM tracking_events_{today} WHERE user_id=1"
).fetchone()
assert int(y_rows["n"]) == 1 and int(t_rows["n"]) == 1
print("  PASSED (昨天表=1条, 今天表=1条)")

print("\n=== Test 2: 分天存储 — 查询跨天聚合 + 时间范围路由 ===")
all_events = store.search_events(user_id=1)
assert len(all_events) == 2, len(all_events)
# 时间范围只路由到对应天表
yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
only_yesterday = store.search_events(user_id=1,
                                     since=f"{yesterday_str} 00:00:00",
                                     until=f"{yesterday_str} 23:59:59")
assert len(only_yesterday) == 1 and only_yesterday[0]["payload"] == "昨天的日志"
kw = store.search_events(user_id=1, keyword="今天的日志")
assert len(kw) == 1 and kw[0]["payload"] == "今天的日志"
print("  PASSED")

print("\n=== Test 3: VisionObservationService — 照片保存 + 描述写入 tracking ===")
engine = TrackingEngine(db=db, media_root=media_root, db_path=tracking_db)
svc = VisionObservationService(tracking_engine=engine, db=db)
# 1x1 PNG
import base64
png = base64.b64encode(bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c626001000000ffff03000006000557bfabd40000000049454e44ae426082"
)).decode()

# 模拟 VisionModel（避免真实 API）：monkeypatch _get_vision_model
class FakeVM:
    def ask(self, data_url, prompt="", **kw):
        return "用户坐在电脑前，环境明亮。"

svc._vision_model = FakeVM()
Config.ACTIVE_VISION_ENABLED = True
res = svc.ingest_observation(f"data:image/png;base64,{png}", timestamp="2026-08-08 10:00:00",
                             user_id=1, camera="front")
assert res["success"] is True
assert res["description"] == "用户坐在电脑前，环境明亮。"
assert res.get("image_path"), "照片应已保存"
assert os.path.exists(res["image_path"])
# 按天目录：<media>/<uid>/<date>/photo/
assert "/1/" in res["image_path"] and "/photo/" in res["image_path"]
print(f"  image_path={res['image_path']}")

# tracking 日志：photo + text 两条
events = engine.query_observations(user_id=1)
text_ev = [e for e in events if e["etype"] == "text"]
assert any(e["payload"] == "【视觉】用户坐在电脑前，环境明亮。" for e in text_ev), text_ev
photo_ev = [e for e in events if e["etype"] == "image"]
assert len(photo_ev) >= 1
assert photo_ev[0]["meta"].get("media_path") == res["image_path"]
print("  PASSED (photo + 【视觉】文本 均写入 tracking)")

print("\n=== Test 4: VisionObservationService — 未启用时拒绝 ===")
Config.ACTIVE_VISION_ENABLED = False
res_off = svc.ingest_observation(f"data:image/png;base64,{png}", user_id=1)
assert res_off["success"] is False
Config.ACTIVE_VISION_ENABLED = True
print("  PASSED")

db.close_connection()
import shutil as _sh
_sh.rmtree(workdir, ignore_errors=True)
print("\n=== ALL TRACKING-VISION TESTS PASSED ===")
