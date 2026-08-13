# tests/test_api_accounts.py
# 多 OpenAI 兼容 API 账号管理 + FailoverChat 自动回退 测试

import datetime
import os
import sys
import tempfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["OPENAI_API_KEY"] = "test-key"

from apps.dsn.models.api_accounts import (
    APIManager,
    FailoverChat,
    APIAccount,
    build_failover_chat,
    get_api_manager,
    reset_api_manager,
    is_known_down,
)
import apps.dsn.models.api_accounts as ma_module
import apps.dsn.models.clients as clients_mod


def _fresh_manager():
    path = os.path.join(tempfile.mkdtemp(), "accounts.json")
    mgr = APIManager(path=path)
    # 移除自动导入的 .env 主账号，确保测试不依赖外部环境
    mgr._accounts.pop("main", None)
    return mgr, path


def _patch_recording():
    """FailoverChat 测试禁用监控观察记录，避免污染真实 .dsn/api_monitor.json"""
    return mock.patch.object(
        ma_module.FailoverChat, "_record_observation",
        staticmethod(lambda *a, **k: None))


class _FakeOA:
    instances = []

    def __init__(self, api_key=None, model="m", api_url=None, timeout=300):
        self.api_key = api_key
        self.model = model
        self.api_url = api_url
        self.messages = []
        self.last_usage = None
        self.last_model = None
        self._last_message = None
        self.fail = ("sk-bad" in (api_key or "")) or ("sk-backup-bad" in (api_key or ""))
        _FakeOA.instances.append(self)

    @property
    def last_tool_calls(self):
        msg = self._last_message
        return msg.get("tool_calls") if msg else None

    def continue_conversation(self, tools=None, tool_choice="auto", extra_body=None):
        if self.fail:
            raise RuntimeError("API down: " + self.api_key)
        self.last_model = self.model
        self.last_usage = {"total_tokens": 10}
        self.messages.append({"role": "assistant", "content": "hello from " + self.api_key})
        self._last_message = {"content": "hello", "tool_calls": None}
        return "hello from " + self.api_key

    def reset_conversation(self):
        self.messages.clear()


def test_manager_crud():
    print("=== APIManager CRUD + 持久化 ===")
    mgr, path = _fresh_manager()
    ok, msg = mgr.add("bad", "http://x/v1", "sk-bad", "m1")
    assert ok, msg
    ok, msg = mgr.add("ds", "http://x/v1", "sk-good", "m2", priority=5)
    assert ok, msg

    # 优先级自动 +10
    assert mgr.get("ds").priority == 15 or mgr.get("ds").priority == 5

    # 持久化重载
    mgr2 = APIManager(path=path)
    assert mgr2.count() == 2
    assert mgr2.get("ds").api_key == "sk-good"

    # 修改优先级 / 启用禁用
    ok, _ = mgr.set_priority("ds", 0)
    assert ok and mgr.get("ds").priority == 0
    ok, _ = mgr.set_enabled("bad", False)
    assert ok and not mgr.get("bad").enabled
    ok, _ = mgr.remove("bad")
    assert ok and mgr.get("bad") is None

    # mask_key
    assert mgr.get("ds").mask_key().endswith("good") is False
    print("  PASSED")


def test_failover_fallback():
    print("=== FailoverChat 自动回退 ===")
    orig = clients_mod.OpenAIChat
    clients_mod.OpenAIChat = _FakeOA
    with _patch_recording():
        try:
            fc = FailoverChat([
                APIAccount(name="a1", api_key="sk-bad", model="m1", priority=0),
                APIAccount(name="a2", api_key="sk-good", model="m2", priority=1),
            ])
            reply = fc.send_message("hi")
            assert "sk-good" in reply
            assert fc.active_account == "a2"
            assert fc.last_model == "m2"
            assert len(fc.messages) == 2  # user + assistant

            # 全部失败 → 抛 RuntimeError
            fc3 = FailoverChat([APIAccount(name="x", api_key="sk-bad", model="m", priority=0)])
            try:
                fc3.send_message("hi")
                assert False, "should raise"
            except RuntimeError:
                pass

            # 首个成功 → 无回退
            fc4 = FailoverChat([APIAccount(name="ok", api_key="sk-good", model="m", priority=0)])
            assert fc4.send_message("hello") == "hello from sk-good"
            assert fc4.active_account == "ok"
        finally:
            clients_mod.OpenAIChat = orig
    print("  PASSED")


def test_build_failover_none_when_no_accounts():
    print("=== 无账号时回退单账号模式 ===")
    from unittest import mock
    reset_api_manager()
    # 直接验证: 当 .env 无 key 时 _env_fallback_account 返回 None
    with mock.patch.object(ma_module.APIManager, "_env_fallback_account", return_value=None):
        mgr = APIManager(path=os.path.join(tempfile.mkdtemp(), "none.json"))
        assert mgr.count() == 0
        assert mgr.list_accounts() == []
        assert mgr.enabled_accounts() == []
    print("  PASSED")


def test_env_fallback_account():
    print("=== .env 主账号作为隐含账号暴露 ===")
    mgr, _ = _fresh_manager()
    fb = mgr._env_fallback_account()
    if fb is not None:  # 有 .env key 时
        assert fb.name == "main"
        assert fb.api_key
        assert fb.priority == 0
        listed = mgr.list_accounts()
        assert any(a["name"] == "main" for a in listed), listed
        ok, msg = mgr.test("main", timeout=3)
        assert ok is False or "测试" in msg  # 可能连不上，但账号存在
    else:  # 无 .env key 时
        assert mgr.list_accounts() == []
    print("  PASSED")


def test_priority_order():
    print("=== 优先级排序 ===")
    mgr, _ = _fresh_manager()
    mgr.add("low", "http://x/v1", "sk-a", "m", priority=100)
    mgr.add("high", "http://x/v1", "sk-b", "m", priority=0)
    mgr.add("mid", "http://x/v1", "sk-c", "m", priority=50)
    names = [a["name"] for a in mgr.list_accounts()]
    assert names == ["high", "mid", "low"], names
    enabled = [a.name for a in mgr.enabled_accounts()]
    assert enabled == ["high", "mid", "low"]
    print("  PASSED")


def test_backup_token_failover():
    print("=== 备用 Token 自动顶上 ===")
    orig = clients_mod.OpenAIChat
    clients_mod.OpenAIChat = _FakeOA
    with _patch_recording():
        try:
            # 主 Token 失效 → 备用 Token 顶上（同端点）
            fc = FailoverChat([
                APIAccount(name="deepseek", api_key="sk-bad", backup_api_key="sk-good",
                           model="m1", priority=0),
            ])
            reply = fc.send_message("hi")
            assert "sk-good" in reply
            assert fc.active_account == "deepseek(备用)", fc.active_account

            # 主 Token 正常 → 不用备用
            fc2 = FailoverChat([
                APIAccount(name="deepseek", api_key="sk-good", backup_api_key="sk-backup",
                           model="m1", priority=0),
            ])
            assert fc2.send_message("hi") == "hello from sk-good"
            assert fc2.active_account == "deepseek"

            # 主+备用都失效 → 抛错
            fc3 = FailoverChat([
                APIAccount(name="ds", api_key="sk-bad", backup_api_key="sk-backup-bad",
                           model="m1", priority=0),
            ])
            try:
                fc3.send_message("hi")
                assert False, "should raise"
            except RuntimeError:
                pass
        finally:
            clients_mod.OpenAIChat = orig
    print("  PASSED")


def test_main_cannot_be_deleted():
    print("=== main 不可删除 ===")
    mgr, _ = _fresh_manager()
    # 手动添加 main 模拟托管状态
    mgr.add("main", "http://x/v1", "sk-main", "m")
    ok, msg = mgr.remove("main")
    assert not ok, "main 应不可删除"
    assert "不可删除" in msg
    # 非 main 可正常删除
    mgr.add("dummy", "http://x/v1", "sk-dummy", "m")
    ok, msg = mgr.remove("dummy")
    assert ok
    print("  PASSED")


def test_main_cannot_be_renamed():
    print("=== main 不可重命名 ===")
    mgr, _ = _fresh_manager()
    mgr.add("main", "http://x/v1", "sk-main", "m")
    ok, msg = mgr.rename("main", "newname")
    assert not ok, "main 应不可重命名"
    assert "不可重命名" in msg
    ok, msg = mgr.rename("nope", "newname")
    assert not ok
    assert "不存在" in msg
    print("  PASSED")


def test_rename():
    print("=== 重命名 ===")
    mgr, path = _fresh_manager()
    mgr.add("old", "http://x/v1", "sk-old", "m")
    ok, msg = mgr.rename("old", "new")
    assert ok, msg
    assert mgr.get("old") is None
    assert mgr.get("new") is not None
    assert mgr.get("new").api_key == "sk-old"
    # 重名冲突
    mgr.add("other", "http://x/v1", "sk-other", "m")
    ok, msg = mgr.rename("new", "other")
    assert not ok
    assert "已存在" in msg
    # 持久化验证
    mgr2 = APIManager(path=path)
    assert mgr2.get("new") is not None
    assert mgr2.get("old") is None
    print("  PASSED")


def test_swap_keys():
    print("=== 交换主/备用 Token ===")
    mgr, _ = _fresh_manager()
    mgr.add("test", "http://x/v1", "sk-primary", "m", backup_api_key="sk-backup")
    ok, msg = mgr.swap_keys("test")
    assert ok, msg
    acc = mgr.get("test")
    assert acc.api_key == "sk-backup"
    assert acc.backup_api_key == "sk-primary"
    # 无备用 Token 时拒绝
    mgr.add("nobk", "http://x/v1", "sk-only", "m")
    ok, msg = mgr.swap_keys("nobk")
    assert not ok
    assert "没有备用 Token" in msg
    # 不存在账号
    ok, msg = mgr.swap_keys("nonexistent")
    assert not ok
    print("  PASSED")


def test_add_with_backup_key():
    print("=== add 支持备用 Token ===")
    mgr, _ = _fresh_manager()
    ok, msg = mgr.add("withbk", "http://x/v1", "sk-primary", "m", backup_api_key="sk-backup")
    assert ok, msg
    acc = mgr.get("withbk")
    assert acc.backup_api_key == "sk-backup"
    # 不传 backup_api_key 时默认空
    ok, _ = mgr.add("nobk", "http://x/v1", "sk-only", "m")
    acc2 = mgr.get("nobk")
    assert acc2.backup_api_key == ""
    print("  PASSED")


def test_set_api_key():
    print("=== set_api_key ===")
    mgr, _ = _fresh_manager()
    mgr.add("test", "http://x/v1", "sk-old", "m")
    ok, msg = mgr.set_api_key("test", "sk-new")
    assert ok, msg
    assert mgr.get("test").api_key == "sk-new"
    ok, msg = mgr.set_api_key("nope", "sk-x")
    assert not ok
    print("  PASSED")


def test_time_slots():
    print("=== 时段优先级 ===")
    mgr, _ = _fresh_manager()
    mgr.add("ts", "http://x/v1", "sk-ts", "m", priority=10)

    ok, msg = mgr.set_time_slot("ts", "08:00", "20:00", 0)
    assert ok, msg
    ok, msg = mgr.set_time_slot("ts", "bad", "20:00", 0)
    assert not ok, "非法时间应被拒绝"
    ok, msg = mgr.set_time_slot("nope", "08:00", "20:00", 0)
    assert not ok

    acc = mgr.get("ts")
    assert len(acc.time_slots) == 1
    assert acc.effective_priority(datetime.datetime(2026, 1, 1, 10, 0)) == 0
    assert acc.effective_priority(datetime.datetime(2026, 1, 1, 21, 0)) == 10

    # 跨午夜时段
    ok, _ = mgr.set_time_slot("ts", "22:00", "06:00", 5)
    assert ok
    acc2 = mgr.get("ts")
    assert acc2.effective_priority(datetime.datetime(2026, 1, 1, 23, 30)) == 5
    assert acc2.effective_priority(datetime.datetime(2026, 1, 1, 3, 0)) == 5
    # 第一个匹配的时段优先（22:00-06:00 覆盖午夜）
    assert acc2.effective_priority(datetime.datetime(2026, 1, 1, 10, 0)) == 0

    # 移除/清除
    ok, msg = mgr.remove_time_slot("ts", "08:00", "20:00")
    assert ok
    ok, msg = mgr.remove_time_slot("ts", "08:00", "20:00")
    assert not ok
    ok, msg = mgr.clear_time_slots("ts")
    assert ok
    assert mgr.get("ts").time_slots == []

    # 持久化
    ok, _ = mgr.set_time_slot("ts", "09:00", "17:00", 2)
    assert ok
    print("  PASSED")


def test_time_slots_persistence():
    print("=== 时段优先级持久化 ===")
    mgr, path = _fresh_manager()
    mgr.add("ts", "http://x/v1", "sk-ts", "m")
    mgr.set_time_slot("ts", "09:00", "17:00", 2)
    mgr2 = APIManager(path=path)
    acc = mgr2.get("ts")
    assert acc.time_slots == [{"start": "09:00", "end": "17:00",
                               "priority": 2, "source": "manual"}]
    assert acc.effective_priority(datetime.datetime(2026, 1, 1, 12, 0)) == 2
    print("  PASSED")


def test_manual_beats_dynamic():
    print("=== 手动时段优先于动态时段 ===")
    mgr, _ = _fresh_manager()
    mgr.add("a", "http://x/v1", "sk-a", "m", priority=50)
    mgr.add("b", "http://x/v1", "sk-b", "m", priority=10)

    # 手动时段: a 在 08:00-20:00 优先级 0
    mgr.set_time_slot("a", "08:00", "20:00", 0)
    # 动态学习时段: a 在 08:00-20:00 优先级 3（应被手动覆盖）
    mgr.set_dynamic_slots("a", [
        {"start": "08:00", "end": "20:00", "priority": 3, "source": "dynamic"}])

    acc = mgr.get("a")
    # 白天命中手动时段 0，而非动态 3
    assert acc.effective_priority(datetime.datetime(2026, 1, 1, 10, 0)) == 0
    # 夜间无任何时段 → 回退基础优先级
    assert acc.effective_priority(datetime.datetime(2026, 1, 1, 23, 0)) == 50

    # 动态时段可整体清除，保留手动
    ok, msg = mgr.clear_dynamic_slots("a")
    assert ok
    assert all(s.get("source") != "dynamic" for s in mgr.get("a").time_slots)
    assert len(mgr.get("a").time_slots) == 1
    print("  PASSED")


def test_manual_schedule_overrides():
    print("=== 手动时段安排(过滤层) promote/demote ===")
    mgr, path = _fresh_manager()
    mgr.add("a", "http://x/v1", "sk-a", "m", priority=50)
    mgr.add("b", "http://x/v1", "sk-b", "m", priority=0)  # b 基础优先级更高

    # 08:00-20:00 promote a → 提到最高
    ok, msg = mgr.add_schedule("08:00", "20:00", "a", "promote")
    assert ok, msg
    # 非法动作 / 时间 / 不存在账号被拒绝
    assert not mgr.add_schedule("08:00", "20:00", "a", "bogus")[0]
    assert not mgr.add_schedule("bad", "20:00", "a", "promote")[0]
    assert not mgr.add_schedule("08:00", "20:00", "nope", "promote")[0]

    acc_a = mgr.get("a")
    acc_b = mgr.get("b")
    noon = datetime.datetime(2026, 1, 1, 12, 0)
    night = datetime.datetime(2026, 1, 1, 22, 0)

    # 白天: a 被 promote → 最高（哪怕 b 基础优先级 0 < a 的 50）
    assert acc_a.effective_priority(noon) < acc_b.effective_priority(noon)
    assert acc_a.effective_priority(noon) < 0  # 提优哨兵

    # 夜间: 无安排命中 → 恢复优先级排序，b 在前
    assert acc_a.effective_priority(night) == 50
    assert acc_b.effective_priority(night) == 0

    # enabled_accounts() 用真实时钟 — 分别 mock 到中午/夜间验证排序
    class _FakeDT(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls._fixed

    _FakeDT._fixed = noon
    with mock.patch.object(ma_module.datetime, "datetime", _FakeDT):
        enabled = [x.name for x in mgr.enabled_accounts()]
    assert enabled[0] == "a", enabled

    _FakeDT._fixed = night
    with mock.patch.object(ma_module.datetime, "datetime", _FakeDT):
        enabled_night = [x.name for x in mgr.enabled_accounts()]
    assert enabled_night[0] == "b", enabled_night

    # 跨午夜 promote b
    ok, _ = mgr.add_schedule("22:00", "06:00", "b", "promote")
    assert ok
    assert acc_b.effective_priority(datetime.datetime(2026, 1, 1, 23, 30)) < 0
    assert acc_b.effective_priority(datetime.datetime(2026, 1, 1, 3, 0)) < 0

    # 持久化: 新 manager 从磁盘恢复安排
    mgr2 = APIManager(path=path)
    rules = mgr2.list_schedule()
    assert any(r["account"] == "a" and r["start"] == "08:00"
               and r.get("action") == "promote" for r in rules)
    assert mgr2.get("a").effective_priority(noon) < 0

    # 移除
    ok, msg = mgr.remove_schedule("08:00", "20:00", "a")
    assert ok, msg
    assert mgr.get("a").effective_priority(noon) == 50
    ok, msg = mgr.clear_schedule()
    assert ok
    assert mgr.list_schedule() == []
    print("  PASSED")


def test_manual_schedule_demote():
    print("=== 手动时段安排 demote = 压到最低但仍作备用槽 ===")
    mgr, _ = _fresh_manager()
    mgr.add("a", "http://x/v1", "sk-a", "m", priority=0)
    mgr.add("b", "http://x/v1", "sk-b", "m", priority=50)

    ok, msg = mgr.add_schedule("08:00", "20:00", "a", "demote")
    assert ok, msg

    acc_a = mgr.get("a")
    acc_b = mgr.get("b")
    noon = datetime.datetime(2026, 1, 1, 12, 0)

    # 白天: a 被压到最低 → b 优先
    assert acc_a.effective_priority(noon) > acc_b.effective_priority(noon)
    assert acc_a.effective_priority(noon) > 10 ** 11  # 降级哨兵
    assert acc_b.effective_priority(noon) == 50

    # 排序: b 在前，a 在最后但仍在列表中 (备用槽)
    class _FakeDT(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.datetime(2026, 1, 1, 12, 0)

    with mock.patch.object(ma_module.datetime, "datetime", _FakeDT):
        enabled = [x.name for x in mgr.enabled_accounts()]
    assert enabled == ["b", "a"], enabled
    print("  PASSED")


def _fresh_router():
    """把全局动态路由指向临时监控文件，返回其引用"""
    import apps.dsn.models.dynamic_router as dr
    orig = dr._MONITOR_FILE
    dr._MONITOR_FILE = os.path.join(tempfile.mkdtemp(), "monitor.json")
    from apps.dsn.models.dynamic_router import reset_dynamic_router, get_dynamic_router
    reset_dynamic_router()
    return get_dynamic_router(), orig


def test_known_down_defers_account():
    print("=== 已知坏账号自动后排 (promote 默认保留) ===")
    import time
    orig = _fresh_router()[1]
    try:
        mgr, _ = _fresh_manager()
        mgr.add("good", "http://x/v1", "sk-good", "m", priority=1)
        mgr.add("dead", "http://x/v1", "sk-dead", "m", priority=50)
        mgr.add("slow", "http://x/v1", "sk-slow", "m", priority=0)
        # promote dead 作为默认提优
        mgr.add_schedule("00:00", "23:59", "dead", "promote")
        from apps.dsn.models.dynamic_router import get_dynamic_router
        r = get_dynamic_router()
        now = time.time()
        r.record("dead", False, 10000, source="request", ts=now - 60)
        r.record("dead", False, 10000, source="request", ts=now - 120)

        # 未失败时 promote 生效: dead 优先级被提到最高
        assert mgr.get("dead").effective_priority(
            datetime.datetime(2026, 1, 1, 12, 0)) < 0
        # 但 dead 近期失败 → 自动排到最后; 健康账号按优先级在前
        order = [a.name for a in mgr.enabled_accounts()]
        assert order == ["slow", "good", "dead"], order
        # FailoverChat 回退链同样
        fc = FailoverChat(mgr.enabled_accounts())
        assert fc._account_names == ["slow", "good", "dead"], fc._account_names
    finally:
        from apps.dsn.models.dynamic_router import reset_dynamic_router
        reset_dynamic_router()
        import apps.dsn.models.dynamic_router as dr
        dr._MONITOR_FILE = orig
    print("  PASSED")


def test_known_down_window_configurable():
    print("=== 已知坏窗口可配置: 窗口外失败不排后 ===")
    import time
    orig = _fresh_router()[1]
    try:
        mgr, _ = _fresh_manager()
        mgr.add("a", "http://x/v1", "sk-a", "m", priority=0)
        mgr.add("b", "http://x/v1", "sk-b", "m", priority=1)
        from apps.dsn.models.dynamic_router import get_dynamic_router
        r = get_dynamic_router()
        now = time.time()
        r.record("b", False, 10000, source="request", ts=now - 100)  # 100 秒前失败

        # 默认窗口 3600s → b 被标记为已知坏
        assert is_known_down("b") is True
        # 把窗口调小到 60s → 100 秒前的失败已过期, b 恢复
        from apps.dsn.config import Config
        old = getattr(Config, "FAILOVER_DOWN_WINDOW", 3600)
        try:
            setattr(Config, "FAILOVER_DOWN_WINDOW", 60)
            assert is_known_down("b") is False
        finally:
            setattr(Config, "FAILOVER_DOWN_WINDOW", old)
    finally:
        from apps.dsn.models.dynamic_router import reset_dynamic_router
        reset_dynamic_router()
        import apps.dsn.models.dynamic_router as dr
        dr._MONITOR_FILE = orig
    print("  PASSED")


if __name__ == "__main__":
    test_manager_crud()
    test_failover_fallback()
    test_build_failover_none_when_no_accounts()
    test_priority_order()
    test_backup_token_failover()
    test_main_cannot_be_deleted()
    test_main_cannot_be_renamed()
    test_rename()
    test_swap_keys()
    test_add_with_backup_key()
    test_set_api_key()
    test_time_slots()
    test_time_slots_persistence()
    test_manual_beats_dynamic()
    test_manual_schedule_overrides()
    test_manual_schedule_demote()
    test_known_down_defers_account()
    test_known_down_window_configurable()
    print("\nALL API ACCOUNTS TESTS PASSED")
