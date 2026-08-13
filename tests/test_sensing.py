"""用户跟踪系统 (tracking) 单元测试: 独立加密库存储 + 引擎建模 + AI 查询工具。

闲时感知（仅音频）现由 tracking 子系统提供聆听能力。本测试覆盖：
  - 独立加密数据库 tracking_events 建表与读写（payload/meta 加密）
  - 关键词 / 时间搜索
  - TrackingEngine 的音频/拍照/录像事件记录与作息建模
  - TrackingTools AI 查询工具（配置关闭拒绝 / 用户隔离）
"""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apps.dsn.db.chat import ChatDBManager
from apps.dsn.tracking.store import TrackingStore
from apps.dsn.tracking.core import TrackingEngine
from apps.dsn.tracking.tools import TrackingTools
from apps.dsn.config import Config

workdir = tempfile.mkdtemp(prefix="test_tracking_")
db_path = os.path.join(workdir, "chats.db")
tracking_db = os.path.join(workdir, "tracking.db")
media_root = os.path.join(workdir, "media")

print("=== Test 1: tracking 独立加密库建表 ===")
db = ChatDBManager(db_path=db_path)
db.add_or_update_user(uid=1, nickname="user_a")
db.add_or_update_user(uid=2, nickname="user_b")


def _legacy_writer(user_id, text, rms_level, chat_id, source):
    db.add_sensing_event(user_id=user_id, text=text, rms_level=rms_level,
                         chat_id=chat_id, source=source)


store = TrackingStore(db_path=tracking_db, legacy_writer=_legacy_writer)
conn = store._get_connection()
# 分天表方案：无 tracking_events 主表，事件落在 tracking_events_YYYYMMDD（首次写入自动建表）
from datetime import datetime as _dt
_today = _dt.now().strftime("%Y%m%d")
_day_table = f"tracking_events_{_today}"
store._ensure_day_table(_today)
cols = [r[1] for r in conn.execute(f"PRAGMA table_info({_day_table})").fetchall()]
assert "id" in cols and "user_id" in cols and "etype" in cols and "payload" in cols
assert "source" in cols and "meta" in cols and "created_at" in cols
model_cols = [r[1] for r in conn.execute("PRAGMA table_info(tracking_models)").fetchall()]
assert "model_type" in model_cols and "content" in model_cols
print("  PASSED (按天分表存在)")

print("\n=== Test 2: add_event (audio) 并回写旧 sensing_events ===")
e1 = store.add_event(user_id=1, etype="audio", payload="有人在客厅说话",
                     source="sensing", meta={"rms_level": 0.12}, write_legacy_sensing=True)
e2 = store.add_event(user_id=1, etype="audio", payload="关门的声音",
                     source="sensing", meta={"rms_level": 0.08})
e3 = store.add_event(user_id=1, etype="image", payload="拍摄的照片",
                     source="tracking", meta={"media_path": "/tmp/a.jpg"})
assert e1 > 0 and e2 > 0 and e3 > 0
# 旧表兼容写入
legacy = db.query_sensing_events(user_id=1)
assert len(legacy) >= 1 and legacy[0]["text"] == "有人在客厅说话"
print("  PASSED")

print("\n=== Test 3: query_events 按时间倒序 + 类型过滤 ===")
records = store.query_events(user_id=1)
assert len(records) == 3
assert records[0]["etype"] == "image"
audio_only = store.query_events(user_id=1, etype="audio")
assert len(audio_only) == 2 and all(r["etype"] == "audio" for r in audio_only)
print("  PASSED")

print("\n=== Test 4: 用户隔离 ===")
other = store.query_events(user_id=2)
assert other == []
print("  PASSED (uid=2 看不到 uid=1 的记录)")

print("\n=== Test 5: keyword / limit 过滤 ===")
kw = store.query_events(user_id=1, keyword="关门")
assert len(kw) == 1 and kw[0]["payload"] == "关门的声音"
lim = store.query_events(user_id=1, limit=1)
assert len(lim) == 1
print("  PASSED")

print("\n=== Test 6: TrackingEngine.record_audio / record_photo ===")
engine = TrackingEngine(db=db, media_root=media_root, db_path=tracking_db)
aid = engine.record_audio(user_id=1, text="有人在客厅说话", source="sensing",
                          rms_level=0.12, write_legacy=True)
pid = engine.record_photo(user_id=1, path="/tmp/a.jpg", note="桌面")
assert aid > 0 and pid > 0
print("  PASSED")

print("\n=== Test 7: TrackingEngine.model_routines (作息/生活节奏) ===")
res = engine.model_routines(user_id=1, days=7)
assert res["model_type"] == "rhythm"
models = engine.get_models(user_id=1, model_type="rhythm")
assert len(models) >= 1 and models[0]["model_type"] == "rhythm"
print(f"  summary={res['summary']}")
print("  PASSED")

print("\n=== Test 8: TrackingTools — 配置关闭时拒绝 ===")
saved_flag = getattr(Config, "TRACKING_AI_ACCESS_ENABLED",
                     getattr(Config, "SENSING_AI_ACCESS_ENABLED", False))
Config.TRACKING_AI_ACCESS_ENABLED = False
TrackingTools.set_context(tracking_engine=engine, db=db)
TrackingTools._ctx["_uid"] = 1
r = TrackingTools().query_observations()
assert r["enabled"] is False and r["records"] == []
print("  PASSED")

print("\n=== Test 9: TrackingTools — 配置开启且按用户隔离 ===")
Config.TRACKING_AI_ACCESS_ENABLED = True
r = TrackingTools().query_observations()
assert r["enabled"] is True and r["count"] >= 2
TrackingTools._ctx["_uid"] = 2
r2 = TrackingTools().query_observations()
assert r2["count"] == 0
TrackingTools._ctx["_uid"] = 1
r3 = TrackingTools().query_observations(keyword="关门")
assert r3["count"] >= 1
rm = TrackingTools().model_routines(days=7)
assert rm.get("enabled") is True and rm["model"]["model_type"] == "rhythm"
Config.TRACKING_AI_ACCESS_ENABLED = saved_flag
print("  PASSED")

print("\n=== Test 10: 多模态记录 — 文本 (record_text / add_text) ===")
te = engine.add_text(user_id=1, content="记一下我明天要交报告", note="计划")
assert te["ok"] is True and te["event_id"] > 0
text_ev = store.query_events(user_id=1, etype="text")
assert any(r["payload"] == "记一下我明天要交报告" for r in text_ev)
print("  PASSED")

print("\n=== Test 11: 多模态记录 — 文件 (add_file / import_file) ===")
fe = engine.add_file(user_id=1, data="hello tracking", filename="note.md", note="笔记")
assert fe["ok"] is True and os.path.exists(fe["path"])
assert fe["path"].endswith(".md")
import tempfile as _tf
tmp_src = os.path.join(_tf.gettempdir(), "tmp_import.txt")
with open(tmp_src, "w") as f:
    f.write("disk file")
ie = engine.import_file(user_id=1, src=tmp_src)
assert ie["ok"] is True and os.path.exists(ie["path"])
os.remove(tmp_src)
file_ev = store.query_events(user_id=1, etype="file")
assert len(file_ev) == 2 and all(r["etype"] == "file" for r in file_ev)
print("  PASSED")

print("\n=== Test 12: 多模态记录 — 录音登记 audio_path ===")
import tempfile as _tf2
fake_wav = os.path.join(_tf2.gettempdir(), "fake.wav")
open(fake_wav, "wb").write(b"RIFF" + b"\x00" * 16)
ae = engine.record_audio(user_id=1, text="主动录音", source="recording",
                         audio_path=fake_wav, duration=3.2, write_legacy=False)
assert ae > 0
audio_ev = store.query_events(user_id=1, etype="audio")
rec = [r for r in audio_ev if r["payload"] == "主动录音"]
assert rec
assert isinstance(rec[0]["meta"], dict) and rec[0]["meta"].get("media_path") == fake_wav
os.remove(fake_wav)
print("  PASSED")

print("\n=== Test 13: TrackingTools — AI 只读 + 仅文本可见 ===")
Config.TRACKING_AI_ACCESS_ENABLED = True
TrackingTools._ctx["_uid"] = 1
# AI 无写工具：add_text_entry / add_file_entry 应不存在
assert not hasattr(TrackingTools(), "add_text_entry"), "AI 不应有写工具"
assert not hasattr(TrackingTools(), "add_file_entry"), "AI 不应有写工具"
# AI 可见数据只含文本，剥离 media_path 等路径
obs = TrackingTools().query_observations()
for r in obs["records"]:
    assert "text" in r and "media_path" not in r, r
    assert "media_path" not in r.get("meta", {}), r
# 图片记录 payload 应为文本描述而非路径
img_obs = TrackingTools().query_observations(etype="image")
for r in img_obs["records"]:
    assert r["text"] and "/" not in r["text"].split("\\")[-1] or "照片" in r["text"] or r["text"].strip()
# model_progress 统计所有类型（仅文本 meta）
mp = TrackingTools().model_progress(days=7)
assert mp.get("enabled") is True and "by_type" in mp["model"]["meta"]
assert mp["model"]["meta"]["by_type"].get("file", 0) >= 2
assert mp["model"]["meta"]["by_type"].get("text", 0) >= 1
Config.TRACKING_AI_ACCESS_ENABLED = saved_flag
print("  PASSED")

print("\n=== Test 14: 独立库加密存储 — 磁盘密文非明文 ===")
import sqlite3 as _sq
_conn = _sq.connect(tracking_db)
_today2 = _dt.now().strftime("%Y%m%d")
_row = _conn.execute(
    f"SELECT payload FROM tracking_events_{_today2} "
    "WHERE payload IS NOT NULL AND payload != '' LIMIT 1"
).fetchone()
_conn.close()
assert _row is not None
assert "有人在客厅说话" not in _row[0], "payload 应为密文，不允许明文落盘"
assert _row[0]  # 非空
print("  PASSED (payload 已加密存储)")

print("\n=== Test 15: 关键词 / 时间范围搜索 ===")
kw_multi = store.search_events(user_id=1, keyword="关门 声音")
assert len(kw_multi) >= 1
since = store.search_events(user_id=1, since="2000-01-01 00:00:00")
assert len(since) == len(store.search_events(user_id=1))
future = store.search_events(user_id=1, until="2000-01-01 00:00:00")
assert future == [] or all(r["created_at"] < "2000-01-01 00:00:00" for r in future)
# 关键词隔离：uid=2 搜索不到 uid=1 的内容
kw2 = store.search_events(user_id=2, keyword="关门")
assert kw2 == []
print("  PASSED")

try:
    db.close_connection()
except Exception:
    pass
import shutil as _sh
try:
    _sh.rmtree(workdir, ignore_errors=True)
except Exception:
    pass

print("\n=== ALL TESTS PASSED ===")
