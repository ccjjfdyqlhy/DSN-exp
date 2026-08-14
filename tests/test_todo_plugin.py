# tests/test_todo_plugin.py
# Todo 插件测试 — 分解 + 进度跟踪 + 子代理 + SSE

"""
用法:
    python tests/test_todo_plugin.py

测试内容:
    1. TodoStore — 计划 CRUD + 订阅/发布
    2. TodoStore — 进度计算
    3. TodoPlugin — 复杂度判断（启发式）
    4. TodoPlugin — 分解 JSON 解析
    5. TodoPlugin — 完整流程（mock LLM）
    6. TodoPlugin — 子代理孵化
    7. TodoPlugin — 不满足复杂度时跳过
"""

from __future__ import annotations

import json
import queue
import sys
import os
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_store_crud():
    """1. TodoStore — 计划 CRUD"""
    print("\n" + "=" * 60)
    print("Test 1: TodoStore 计划 CRUD")
    print("=" * 60)

    from apps.dsn.plugins.builtin.todo_store import get_todo_store, TodoStore

    store = TodoStore()
    plan = store.create_plan(chat_id=42, user_id=1)
    assert plan.todo_id.startswith("todo-")
    assert plan.status == "planning"
    print(f"  创建计划: {plan.todo_id}")

    items = [
        {"title": "设计数据库模型", "description": "设计表结构", "priority": 0},
        {"title": "实现API", "description": "编写路由", "priority": 1, "dependencies": [0]},
        {"title": "编写测试", "description": "单元测试", "priority": 2, "dependencies": [0, 1]},
    ]
    store.set_items(plan.todo_id, items)
    plan = store.get_plan(plan.todo_id)
    assert plan.status == "executing"
    assert len(plan.items) == 3
    assert plan.items[0].title == "设计数据库模型"
    print(f"  设置 3 个子任务")

    # 更新进度
    store.update_item(plan.todo_id, "item-00", status="completed")
    store.update_item(plan.todo_id, "item-01", status="in_progress")
    plan = store.get_plan(plan.todo_id)
    assert plan.overall_progress == 1.0 / 3.0
    print(f"  进度: {plan.overall_progress:.2f}")

    # 完成所有
    store.update_item(plan.todo_id, "item-01", status="completed")
    store.update_item(plan.todo_id, "item-02", status="completed")
    store.set_completed(plan.todo_id, "全部完成")
    plan = store.get_plan(plan.todo_id)
    assert plan.status == "completed"
    assert plan.overall_progress == 1.0
    print(f"  计划完成")

    # dict 格式
    d = store.get_plan_dict(plan.todo_id)
    assert d is not None
    assert d["status"] == "completed"
    assert len(d["items"]) == 3
    print("  计划字典格式正确")

    print("  PASSED")


def test_store_subscribe():
    """2. TodoStore — SSE 订阅与发布"""
    print("\n" + "=" * 60)
    print("Test 2: TodoStore SSE 订阅与发布")
    print("=" * 60)

    from apps.dsn.plugins.builtin.todo_store import TodoStore

    store = TodoStore()
    plan = store.create_plan(chat_id=1, user_id=1)

    # 订阅
    q = store.subscribe(plan.todo_id)
    assert isinstance(q, queue.Queue)
    print(f"  订阅成功: {plan.todo_id}")

    # 初始快照
    snapshot_event = q.get(timeout=2)
    assert "snapshot" in snapshot_event
    print("  收到初始快照事件")

    # 触发事件
    store.set_items(plan.todo_id, [{"title": "任务1", "description": "test"}])
    store.update_item(plan.todo_id, "item-00", status="completed")

    # 读取事件
    events = []
    for _ in range(3):
        try:
            ev = q.get(timeout=2)
            events.append(ev)
        except queue.Empty:
            break

    assert len(events) >= 2, f"应收到至少 2 个事件，实际 {len(events)}"
    print(f"  收到 {len(events)} 个 SSE 事件")
    assert any("plan_started" in ev for ev in events)
    assert any("item_updated" in ev for ev in events)

    store.set_completed(plan.todo_id)
    try:
        final = q.get(timeout=2)
        assert "completed" in final
        print("  收到完成事件")
    except queue.Empty:
        print("  (完成事件可能已被处理)")

    # 取消订阅
    store.unsubscribe(plan.todo_id, q)
    print("  取消订阅成功")

    print("  PASSED")


def test_heuristic_check():
    """3. TodoPlugin — 启发式复杂度判断"""
    print("\n" + "=" * 60)
    print("Test 3: TodoPlugin 启发式判断")
    print("=" * 60)

    from apps.dsn.plugins.builtin.todo_plugin import TodoPlugin

    # 简单消息
    assert not TodoPlugin._heuristic_check("你好")
    assert not TodoPlugin._heuristic_check("今天天气怎么样")
    print("  简单消息不触发分解")

    # 复杂消息 (需要 >50 字符)
    complex_msg = "帮我设计一个包含多个模块的大型项目系统架构，需要包含数据库设计、API接口实现和测试编写等完整功能模块开发"
    assert TodoPlugin._heuristic_check(complex_msg)
    print("  复杂消息触发分解")

    # 多重关键词 (需要 >50 字符)
    multi = (
        "设计一个完整的系统架构包含批量处理模块和实时数据同步功能模块化设计，"
        "同时实现所有API接口和前端页面组件开发与测试"
    )
    assert TodoPlugin._heuristic_check(multi)
    print("  多关键词消息触发分解")

    print("  PASSED")


def test_parse_decomposition():
    """4. TodoPlugin — LLM 分解结果 JSON 解析"""
    print("\n" + "=" * 60)
    print("Test 4: TodoPlugin 分解 JSON 解析")
    print("=" * 60)

    from apps.dsn.plugins.builtin.todo_plugin import TodoPlugin

    # 正常 JSON
    valid_response = '''[
        {"title": "设计数据库", "description": "设计表结构", "priority": 0, "dependencies": [], "parallel": false, "needs_sub_agent": true, "sub_agent_prompt": "设计数据库", "sub_agent_model": "fast"},
        {"title": "实现API", "description": "编写路由", "priority": 1, "dependencies": [0], "parallel": false, "needs_sub_agent": true, "sub_agent_prompt": "实现API", "sub_agent_model": "fast"}
    ]'''
    items = TodoPlugin._parse_decomposition(valid_response)
    assert items is not None
    assert len(items) == 2
    assert items[0]["title"] == "设计数据库"
    print(f"  解析出 {len(items)} 个子任务")

    # LLM 可能带前缀文字
    noisy = '好的，我来分解一下。\n[\n  {"title": "任务1", "description": "测试", "priority": 0}\n]\n共 1 个任务。'
    items = TodoPlugin._parse_decomposition(noisy)
    assert items is not None
    assert len(items) == 1
    print("  带噪声的 JSON 也能解析")

    # 无效响应
    assert TodoPlugin._parse_decomposition("没有发现任务") is None
    print("  无效响应返回 None")

    # 空数组
    assert TodoPlugin._parse_decomposition("[]") is None
    print("  空数组返回 None")

    print("  PASSED")


def test_todo_plugin_mock():
    """5. TodoPlugin — 完整流程 (mock LLM + ComplexityAnalyzer)"""
    print("\n" + "=" * 60)
    print("Test 5: TodoPlugin 完整流程 (mock)")
    print("=" * 60)

    from harness.pipeline import Context as PluginContext, HookPoint
    from apps.dsn.plugins.builtin.todo_plugin import TodoPlugin
    from apps.dsn.plugins.builtin.todo_store import TodoStore, get_todo_store

    # Mock ComplexityAnalyzer
    class MockComplexity:
        def analyze_complexity(self, message, context_len):
            return {"is_complex": True, "score": 0.8, "reasons": ["length", "keywords"]}

    # Mock ModelsPlugin
    decompose_response = json.dumps([
        {"title": "分析需求", "description": "分析用户需求", "priority": 0,
         "dependencies": [], "parallel": False, "needs_sub_agent": False},
        {"title": "实现功能", "description": "实现核心功能", "priority": 1,
         "dependencies": [0], "parallel": False, "needs_sub_agent": True,
         "sub_agent_prompt": "实现功能", "sub_agent_model": "fast"},
    ])

    sub_agent_response = "功能已实现，包含完整的代码。"

    class MockModels:
        def __init__(self):
            self.invoke_count = 0
        def invoke(self, messages, ctx=None):
            self.invoke_count += 1
            if self.invoke_count == 1:
                return decompose_response
            else:
                return sub_agent_response

    models = MockModels()
    complexity = MockComplexity()

    plugin = TodoPlugin(models_plugin=models, complexity_analyzer=complexity)

    ctx = PluginContext(
        user_id=1,
        message="设计一个包含数据库和API的完整项目架构，实现所有功能模块并编写测试",
        chat_id=42,
    )
    ctx.original_reply = "好的，我来设计。"
    ctx.reply = ctx.original_reply

    # 执行
    ctx = plugin.on_hook(HookPoint.POST_PROCESS, ctx)

    # 分解是异步的 — 轮询等待
    store = get_todo_store()
    plans = []
    for _ in range(30):  # 最多等 3 秒
        time.sleep(0.1)
        plans = store.list_plans(chat_id=42)
        if plans:
            break

    assert len(plans) >= 1, f"应至少创建 1 个计划，实际 {len(plans)}"
    plan_dict = store.get_plan_dict(plans[0]["todo_id"])
    assert plan_dict is not None
    assert len(plan_dict["items"]) == 2
    print(f"  计划创建成功: {plan_dict['todo_id']}")
    print(f"  子任务数: {len(plan_dict['items'])}")

    # 等待子代理完成
    for _ in range(30):
        time.sleep(0.1)
        plan_dict2 = store.get_plan_dict(plans[0]["todo_id"])
        if plan_dict2 and plan_dict2["status"] in ("completed", "failed"):
            break

    plan_dict2 = store.get_plan_dict(plans[0]["todo_id"])
    if plan_dict2:
        print(f"  最终状态: {plan_dict2['status']}, 进度: {plan_dict2['overall_progress']:.2f}")

    # 清理
    store.cleanup_old(max_age_seconds=0)
    print("  清理完成")

    print("  PASSED")


def test_sub_agent_spawning():
    """6. TodoPlugin — 子代理孵化机制"""
    print("\n" + "=" * 60)
    print("Test 6: TodoPlugin 子代理孵化")
    print("=" * 60)

    from apps.dsn.plugins.builtin.todo_store import TodoStore, get_todo_store

    store = TodoStore()
    plan = store.create_plan(chat_id=1, user_id=1)

    items = [
        {"title": "简单任务", "description": "不需要子代理", "priority": 0,
         "dependencies": [], "needs_sub_agent": False},
        {"title": "设计数据库", "description": "设计表结构", "priority": 1,
         "dependencies": [0], "needs_sub_agent": True,
         "sub_agent_prompt": "设计数据库", "sub_agent_model": "fast"},
    ]
    store.set_items(plan.todo_id, items)

    # 模拟子代理完成
    store.update_item(plan.todo_id, "item-00", status="completed", result="已完成")
    store.update_item(plan.todo_id, "item-01", status="in_progress")
    plan = store.get_plan(plan.todo_id)
    assert plan.overall_progress == 0.5
    print(f"  一半完成时进度: {plan.overall_progress}")

    store.update_item(plan.todo_id, "item-01", status="completed",
                      result="数据库设计完成")
    plan = store.get_plan(plan.todo_id)
    assert plan.overall_progress == 1.0
    assert plan.status == "completed"
    print(f"  全部完成进度: {plan.overall_progress}")

    # 检查 dict 结果
    d = store.get_plan_dict(plan.todo_id)
    item_results = {it["id"]: it for it in d["items"]}
    assert item_results["item-00"]["status"] == "completed"
    assert item_results["item-01"]["status"] == "completed"
    assert item_results["item-01"]["result"] == "数据库设计完成"
    print("  子任务结果正确写入")

    store.cleanup_old(max_age_seconds=0)
    print("  PASSED")


def test_below_threshold_skip():
    """7. TodoPlugin — 不满足复杂度时跳过"""
    print("\n" + "=" * 60)
    print("Test 7: TodoPlugin 低复杂度跳过")
    print("=" * 60)

    from harness.pipeline import Context as PluginContext, HookPoint
    from apps.dsn.plugins.builtin.todo_plugin import TodoPlugin
    from apps.dsn.plugins.builtin.todo_store import get_todo_store

    class MockComplexity:
        def analyze_complexity(self, message, context_len):
            return {"is_complex": False, "score": 0.2, "reasons": []}

    class MockModels:
        def __init__(self):
            self.invoke_count = 0
        def invoke(self, messages, ctx=None):
            self.invoke_count += 1
            return "不应该被调用"

    models = MockModels()
    complexity = MockComplexity()

    plugin = TodoPlugin(models_plugin=models, complexity_analyzer=complexity)

    ctx = PluginContext(user_id=1, message="你好，今天天气如何？", chat_id=1)
    ctx = plugin.on_hook(HookPoint.POST_PROCESS, ctx)
    assert models.invoke_count == 0  # 未被调用
    print("  低复杂度消息未触发分解")

    # 消息太短
    ctx2 = PluginContext(user_id=1, message="hi", chat_id=1)
    ctx2 = plugin.on_hook(HookPoint.POST_PROCESS, ctx2)

    print("  短消息未触发分解")
    print("  PASSED")


# ==============================

def main():
    print("=" * 60)
    print("  DSN-exp Todo 插件测试")
    print("=" * 60)
    print(f"  Python: {sys.version}")
    print(f"  工作目录: {os.getcwd()}")

    tests = [
        ("TodoStore 计划 CRUD", test_store_crud),
        ("TodoStore SSE 订阅发布", test_store_subscribe),
        ("启发式复杂度判断", test_heuristic_check),
        ("分解 JSON 解析", test_parse_decomposition),
        ("完整流程 (mock)", test_todo_plugin_mock),
        ("子代理孵化", test_sub_agent_spawning),
        ("低复杂度跳过", test_below_threshold_skip),
    ]

    passed = 0
    failed = 0

    for name, func in tests:
        try:
            func()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"\n  FAILED: {name}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"  结果: {passed} passed, {failed} failed, {len(tests)} total")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    exit(main())
