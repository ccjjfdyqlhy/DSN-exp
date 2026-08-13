# tests/test_dynamic_router.py
# 动态账户路由测试 — 监控记录 + 可靠性学习 + 时段生成

import datetime
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["OPENAI_API_KEY"] = "test-key"

from apps.dsn.models.api_accounts import APIManager
from apps.dsn.models.dynamic_router import (
    DynamicRouter,
    MonitorStore,
    reset_dynamic_router,
)


def _setup():
    tmp = tempfile.mkdtemp()
    mgr = APIManager(path=os.path.join(tmp, "accounts.json"))
    mgr._accounts.pop("main", None)  # 不依赖 .env 主账号
    mgr.add("good", "http://x/v1", "sk-good", "m", priority=50)
    mgr.add("flaky", "http://x/v1", "sk-flaky", "m", priority=10)
    store = MonitorStore(path=os.path.join(tmp, "monitor.json"))
    router = DynamicRouter(store=store, api_manager=mgr)
    router.set_enabled(True)
    return mgr, store, router


def _seed(router, account, ok_hours, fail_hours, source="request"):
    """在指定小时注入成功/失败观察（每小时多条）。"""
    for h in ok_hours:
        for _ in range(3):
            router.record(account, True, 200, source=source, hour=h)
    for h in fail_hours:
        for _ in range(3):
            router.record(account, False, 5000, source=source, hour=h)


def test_record_and_persist():
    print("=== 观察记录 + 持久化 ===")
    mgr, store, router = _setup()
    router.record("good", True, 150, source="check", hour=9)
    router.flush()

    store2 = MonitorStore(path=store._path)
    assert store2.count() == 1
    o = store2.snapshot()[0]
    assert o["account"] == "good"
    assert o["hour"] == 9
    assert o["ok"] is True
    assert o["source"] == "check"
    print("  PASSED")


def test_reliability():
    print("=== 可靠性估计 ===")
    mgr, store, router = _setup()
    _seed(router, "good", ok_hours=[9, 10], fail_hours=[])
    _seed(router, "flaky", ok_hours=[], fail_hours=[9, 10])
    obs = store.snapshot()
    rel_good, n_good = router._reliability(obs, "good", 10)
    rel_flaky, n_flaky = router._reliability(obs, "flaky", 10)
    assert n_good >= 3 and n_flaky >= 3
    assert rel_good > rel_flaky, (rel_good, rel_flaky)
    # 无观察时段返回 None
    rel_none, n_none = router._reliability(obs, "good", 22)
    assert rel_none is None and n_none == 0
    print(f"  good={rel_good:.2f} flaky={rel_flaky:.2f}")
    print("  PASSED")


def test_recompute_ranks_accounts():
    print("=== 学习生成时段: 可靠账号在对应时段优先 ===")
    mgr, store, router = _setup()
    # good 白天可靠；flaky 白天烂、晚上可靠
    _seed(router, "good", ok_hours=[9, 10, 11], fail_hours=[])
    _seed(router, "flaky", ok_hours=[20, 21, 22], fail_hours=[9, 10, 11])

    res = router.recompute()
    assert res["applied"] == 2

    good = mgr.get("good")
    flaky = mgr.get("flaky")

    # 白天 (10:00) good 优先级应低于 flaky（更优先）
    assert good.effective_priority(datetime.datetime(2026, 1, 1, 10, 0)) < \
        flaky.effective_priority(datetime.datetime(2026, 1, 1, 10, 0))
    # 晚上 (21:00) flaky 应优先于 good
    assert flaky.effective_priority(datetime.datetime(2026, 1, 1, 21, 0)) < \
        good.effective_priority(datetime.datetime(2026, 1, 1, 21, 0))
    print("  PASSED")


def test_manual_hours_excluded():
    print("=== 手动时段不被动态时段覆盖 ===")
    mgr, store, router = _setup()
    # good 手动 pin 白天 08:00-20:00 优先级 0
    mgr.set_time_slot("good", "08:00", "20:00", 0)
    _seed(router, "good", ok_hours=[9, 10], fail_hours=[])
    _seed(router, "flaky", ok_hours=[9, 10], fail_hours=[])

    res = router.recompute()
    good = mgr.get("good")
    # 白天命中手动时段 0
    assert good.effective_priority(datetime.datetime(2026, 1, 1, 10, 0)) == 0
    # 动态学习时段不应覆盖 08:00-20:00
    for s in mgr.dynamic_slots("good"):
        start = int(s["start"].split(":")[0])
        end = int(s["end"].split(":")[0])
        assert end <= 8 or start >= 20, f"动态时段 {s} 覆盖了手动时段"
    print("  PASSED")


def test_recompute_disabled_noop():
    print("=== 关闭时 recompute 不写入 ===")
    mgr, store, router = _setup()
    _seed(router, "good", ok_hours=[9], fail_hours=[])
    router.set_enabled(False)
    res = router.recompute()
    assert res["applied"] == 0
    assert mgr.dynamic_slots("good") == []
    print("  PASSED")


def test_clear():
    print("=== clear 清空历史与动态时段 ===")
    mgr, store, router = _setup()
    _seed(router, "good", ok_hours=[9], fail_hours=[])
    router.recompute()
    assert len(mgr.dynamic_slots("good")) > 0
    router.clear()
    assert store.count() == 0
    assert mgr.dynamic_slots("good") == []
    print("  PASSED")


def test_schedule_hours_excluded():
    print("=== /login schedule 时段不被动态学习覆盖 ===")
    mgr, store, router = _setup()
    # 手动安排白天 promote good（提优）; 夜间 demote flaky（降级）
    ok, msg = mgr.add_schedule("08:00", "20:00", "good", "promote")
    assert ok, msg
    ok, msg = mgr.add_schedule("20:00", "00:00", "flaky", "demote")
    assert ok, msg
    # 两个账号白天都可靠；flaky 夜间也可用
    _seed(router, "good", ok_hours=[9, 10, 11], fail_hours=[])
    _seed(router, "flaky", ok_hours=[9, 10, 11, 21], fail_hours=[])

    router.recompute()
    # good 的动态学习时段不得覆盖 08:00-20:00 (promote)
    for s in mgr.dynamic_slots("good"):
        start = int(s["start"].split(":")[0])
        end = int(s["end"].split(":")[0])
        assert end <= 8 or start >= 20, f"动态时段 {s} 覆盖了 promote 安排"
    # flaky 的动态学习时段不得覆盖 20:00-24:00 (demote)
    for s in mgr.dynamic_slots("flaky"):
        start = int(s["start"].split(":")[0])
        end = int(s["end"].split(":")[0])
        assert end <= 20 or start >= 24, f"动态时段 {s} 覆盖了 demote 安排"
    # good 白天由 promote 提到最高
    assert mgr.get("good").effective_priority(
        datetime.datetime(2026, 1, 1, 12, 0)) < 0
    print("  PASSED")


if __name__ == "__main__":
    reset_dynamic_router()
    test_record_and_persist()
    test_reliability()
    test_recompute_ranks_accounts()
    test_manual_hours_excluded()
    test_recompute_disabled_noop()
    test_clear()
    test_schedule_hours_excluded()
    print("\nALL DYNAMIC ROUTER TESTS PASSED")
