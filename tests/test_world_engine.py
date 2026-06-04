"""Test WorldEngine functionality."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from world.engine import WorldEngine
from world.state_manager import WorldStateManager
from world.narrative_model import NarrativeModel

print("=== Test 1: WorldEngine load config ===")
engine = WorldEngine()
engine.load_config_file("world/worlds/default.yaml")
assert engine._day_length == 86400
assert engine._year_length == 31536000
assert engine._time_scale == 1.0
assert len(engine._seasons) == 4
print(f"  Seasons: {[s['name'] for s in engine._seasons]}")
print("  PASSED")

print("\n=== Test 2: World time ===")
t = engine.world_time_now()
print(f"  Year={t['year']}, Day={t['day_of_year']}, Time={t['hour']:02d}:{t['minute']:02d}")
print(f"  Season={t['season_name']}, DayPart={t['day_part']}, Daylight={t['daylight']}")
print(f"  Moon={t['moon_phase']}{t['moon_name']}")
assert "season" in t
assert "day_part" in t
assert "moon_phase" in t
print("  PASSED")

print("\n=== Test 3: Weather ===")
w = engine.get_weather()
print(f"  Current: {w['current']} — {w['description']}")
assert w["current"]
engine.refresh_weather()
w2 = engine.get_weather()
print(f"  After refresh: {w2['current']}")
print("  PASSED")

print("\n=== Test 4: Geography ===")
loc = engine.get_current_location()
print(f"  Location: {loc['name']}")
assert loc
rooms = engine._rooms
print(f"  Rooms: {[r['id'] for r in rooms]}")
assert len(rooms) >= 5

engine.move_to("storage", reason="测试移动")
loc2 = engine.get_current_location()
assert loc2["id"] == "storage"
print(f"  Moved to: {loc2['name']}")
print("  PASSED")

print("\n=== Test 5: Tool → Room mapping ===")
assert engine.map_tool_to_room("file_manager") == "storage"
assert engine.map_tool_to_room("web_search") == "network"
assert engine.map_tool_to_room("browser_use") == "network"
assert engine.map_tool_to_room("shell") == "core"
assert engine.map_tool_to_room("unknown_tool") == "core"
print("  file_manager → storage ✓")
print("  web_search → network ✓")
print("  browser_use → network ✓")
print("  shell → core ✓")
print("  PASSED")

print("\n=== Test 6: Events ===")
events = engine.poll_events()
print(f"  Polled events: {len(events)}")
for e in events:
    print(f"    [{e['source']}] {e['name']}: {e['text'][:60]}...")

engine.record_event("这是一条自定义测试事件")
full = engine.get_full_state()
print(f"  Recent events in state: {len(full['recent_events'])}")
print("  PASSED")

print("\n=== Test 7: State prompt ===")
prompt = engine.get_state_prompt()
print(f"  Prompt length: {len(prompt)} chars")
print(f"  First 200 chars: {prompt[:200]}")
assert "核心处理室" in prompt
print("  PASSED")

print("\n=== Test 8: Complete context ===")
ctx = engine.get_complete_context(mood_label="热忱")
print(f"  Context length: {len(ctx)} chars")
assert "热忱" in ctx
print("  PASSED")

print("\n=== Test 9: StateManager start/stop ===")
mgr = WorldStateManager(engine, update_interval=1.0)
mgr.start()
import time
time.sleep(2.0)
snap = mgr.get_snapshot()
assert snap is not None
assert "time" in snap
print(f"  Snapshot keys: {list(snap.keys())}")
mgr.stop()
print("  PASSED")

print("\n=== Test 10: to_dict / from_dict ===")
d = engine.to_dict()
print(f"  Serialized keys: {list(d.keys())}")
engine2 = WorldEngine.from_dict(d, engine._config)
assert engine2._weather == engine._weather
print("  Roundtrip OK")
print("  PASSED")

print("\n=== Test 11: NarrativeModel init ===")
import yaml
cfg = yaml.safe_load(open("world/worlds/default.yaml", encoding="utf-8-sig")) or {}
nm = NarrativeModel(
    model_type="deepseek",
    model_name="deepseek-v4-flash",
    temperature=0.9,
    max_tokens=150,
    keep_history=False,
)
nm.set_system_prompt("你是一个旁白测试。只输出\"测试通过\"。")
assert nm.keep_history is False
nm.keep_history = True
assert nm.keep_history is True
print("  PASSED")

print("\n=== ALL TESTS PASSED ===")
