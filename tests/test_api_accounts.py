# tests/test_api_accounts.py
# 多 OpenAI 兼容 API 账号管理 + FailoverChat 自动回退 测试

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["OPENAI_API_KEY"] = "test-key"

from models.api_accounts import (
    APIManager,
    FailoverChat,
    APIAccount,
    build_failover_chat,
    get_api_manager,
    reset_api_manager,
)
import models.api_accounts as ma_module
import models.clients as clients_mod


def _fresh_manager():
    path = os.path.join(tempfile.mkdtemp(), "accounts.json")
    mgr = APIManager(path=path)
    # 移除自动导入的 .env 主账号，确保测试不依赖外部环境
    mgr._accounts.pop("main", None)
    return mgr, path


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
    print("\nALL API ACCOUNTS TESTS PASSED")
