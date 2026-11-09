# tests/test_dsn_cli_no_auth.py
# dsn CLI 的 --no-auth 路径回归测试。
#
# 曾经的 bug（计划 MIGRATION_PLAN 6.4 记载、本轮修复）：
#   apps/dsn/CLI/app.py 构造 client 时写的是 DSNClient(host, args.port) ——
#   **没传 no_auth=True**；而 DSNClient.__init__ 才把 self._no_auth 定下来。
#   于是 --no-auth 模式下 self._no_auth 恒 False → client.py 的
#   send_text / send_audio / send_async 三条路径都在
#   `if (not self.api_key and not self._no_auth)` 处直接 return None，
#   即**所有对话与语音发送静默失效**（终端无任何报错）。
#
# 本测试锁死三件事：
#   1. no_auth=True 时 self._no_auth 为 True；
#   2. 三条发送路径在无 api_key 时**不再早退**（会真正发起请求）；
#   3. app.py 的构造点确实把 args.no_auth 传了进去（静态核对）。

from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.dsn.CLI.client import DSNClient


class _Resp:
    status_code = 200
    text = ""

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_lines(self):
        return iter([])


class _Session:
    """最小 requests.Session 替身：记录是否真的发起了请求。"""

    def __init__(self):
        self.calls = []

    def post(self, url, **kw):
        self.calls.append((url, kw))
        return _Resp()

    def get(self, url, **kw):
        self.calls.append((url, kw))
        return _Resp()


def test_no_auth_flag_is_stored():
    client = DSNClient("127.0.0.1", 1, no_auth=True)
    assert client._no_auth is True
    assert DSNClient("127.0.0.1", 1)._no_auth is False


def test_send_paths_do_not_short_circuit_without_api_key():
    """无 api_key + no_auth=True → 不得早退（早退 = 静默失效）。"""
    client = DSNClient("127.0.0.1", 1, no_auth=True)
    session = _Session()
    client._session = session
    client.chat_id = 7

    client.send_text("你好")
    client.send_audio("QUJD")
    client.send_async("在吗")

    assert len(session.calls) == 3, (
        f"no_auth 模式下发送被静默丢弃，实际请求数 {len(session.calls)}")
    for url, _kw in session.calls:
        assert url.startswith("http://127.0.0.1:1/")


def test_send_paths_short_circuit_when_auth_required():
    """默认（有认证要求）且无 api_key → 仍应早退（行为未变）。"""
    client = DSNClient("127.0.0.1", 1)
    session = _Session()
    client._session = session
    client.chat_id = 7

    client.send_text("你好")
    client.send_audio("QUJD")
    client.send_async("在吗")

    assert session.calls == [], "无 api_key 且非 no_auth 时不应发起请求"


def test_app_passes_no_auth_to_constructor():
    """app.py 的构造点必须把 args.no_auth 传进 DSNClient（静态 AST 核对）。"""
    app_path = Path(__file__).resolve().parents[1] / "apps" / "dsn" / "CLI" / "app.py"
    tree = ast.parse(app_path.read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name)
             and n.func.id == "DSNClient"]
    assert calls, "app.py 里找不到 DSNClient 构造点"
    kwargs = {kw.arg: kw.value for kw in calls[0].keywords}
    assert "no_auth" in kwargs, "DSNClient 构造未传 no_auth —— --no-auth 会静默失效"
    assert isinstance(kwargs["no_auth"], ast.Attribute) and \
        kwargs["no_auth"].attr == "no_auth"


def test_client_signature_accepts_no_auth():
    sig = inspect.signature(DSNClient.__init__)
    assert "no_auth" in sig.parameters
    assert sig.parameters["no_auth"].default is False
