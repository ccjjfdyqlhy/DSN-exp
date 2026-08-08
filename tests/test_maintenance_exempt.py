# tests/test_maintenance_exempt.py
# 维护(maint)期间请求放行判断测试：
#   heartbeat / vision(视频流) 属于基础监控设施，不应受 maint 状态影响而 503；
#   其他业务请求（chat/sensing 等）在 maint 时仍应被拦截。

import ast
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_exempt_fn():
    """从 api/app.py 提取 is_exempt_from_maintenance 纯函数定义（不 import 模块，
    避免触发完整的 boot 初始化）。"""
    src = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / "api" / "app.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "is_exempt_from_maintenance":
            mod = ast.Module(body=[node], type_ignores=[])
            ast.fix_missing_locations(mod)
            ns = {}
            exec(compile(mod, "<api.app>", "exec"), ns)
            return ns["is_exempt_from_maintenance"]
    raise AssertionError("api/app.py 中未找到 is_exempt_from_maintenance")


fn = _load_exempt_fn()


def test_maint_exempt_heartbeat():
    print("=== maint 放行: 心跳 ===")
    assert fn("/api/heartbeat") is True
    assert fn("/api/heartbeat/") is True


def test_maint_exempt_vision_stream():
    print("=== maint 放行: 视觉/视频流链路 ===")
    assert fn("/api/vision/stream-frame") is True
    assert fn("/api/vision/frame") is True
    assert fn("/api/vision/stream/door") is True
    assert fn("/api/vision/observation") is True
    assert fn("/api/vision/cameras") is True
    assert fn("/api/vision/note") is True


def test_maint_exempt_maintenance_api():
    print("=== maint 放行: 维护系统自身 API ===")
    assert fn("/api/maintenance/status") is True
    assert fn("/api/maintenance/sse") is True


def test_maint_blocks_business():
    print("=== maint 拦截: 业务请求 ===")
    assert fn("/api/chat") is False
    assert fn("/api/chat/async_send") is False
    assert fn("/api/sensing/event") is False
    assert fn("/api/music/state") is False
    assert fn("/api/task/xxx") is False
    assert fn("/") is False
    assert fn("") is False


if __name__ == "__main__":
    test_maint_exempt_heartbeat()
    test_maint_exempt_vision_stream()
    test_maint_exempt_maintenance_api()
    test_maint_blocks_business()
    print("\nALL MAINT EXEMPT TESTS PASSED")
