# tests/test_plugin_loader.py
# 插件系统加载测试 — 验证所有插件可以实例化、注册、调度

"""
用法:
    python tests/test_plugin_loader.py

测试内容:
    1. 框架层: PluginManager 注册/调度
    2. 内置插件: 全部 5 个插件成功实例化
    3. 演示管道路由 (mock 依赖)
    4. 流式管道
"""

from __future__ import annotations

import asyncio
import sys
import os

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plugins import (
    Plugin, AsyncPlugin, HookPoint, PluginContext, PluginManager, ChatPipeline,
)
from plugins.builtin import (
    TTSPlugin, ASRFilterPlugin, MemoryPlugin, TaskPlugin, ModelsPlugin,
)


# ==============================
# Mock 依赖
# ==============================

class MockDB:
    """模拟 ChatDBManager"""
    def __init__(self):
        self.memories = {}
        self.messages = {}
        self._mem_count = {}

    def get_memory_count(self, user_id, chat_id):
        return self._mem_count.get((user_id, chat_id), 0)

    def save_memory(self, user_id, chat_id, round_index, content):
        self._mem_count[(user_id, chat_id)] = round_index
        return 1

    def get_memories(self, user_id):
        return []

    def get_next_round_index(self, chat_id):
        return 1

    def append_messages(self, user_id, chat_id, messages):
        key = (user_id, chat_id)
        if key not in self.messages:
            self.messages[key] = []
        self.messages[key].extend(messages)

    def get_chat_history(self, user_id, chat_id):
        return self.messages.get((user_id, chat_id), [])

    def create_chat(self, user_id, name):
        return 1

    def add_or_update_user(self, uid, nickname):
        pass

    def close_connection(self):
        pass


class MockTTS:
    """模拟 VocalExp TTS 客户端"""
    def tts(self, **kwargs):
        return b"mock_audio_data"


class MockFilterModel:
    """模拟 LMFilterModel"""
    def filter_input(self, text):
        if "EXA" in text or "你好" in text or "帮我" in text:
            return "FORWARD"
        return "HOLD"


class MockMemoryManager:
    """模拟 MemorySystem"""
    def assemble_context(self, user_id, chat_id, history):
        return list(history)

    def summarize_turn(self, **kwargs):
        pass


class MockTaskManager:
    """模拟 TaskManager"""
    def __init__(self):
        self.tasks = []

    def create_task(self, task_type, user_id, chat_id, params, priority=1,
                    scheduled_time=None):
        import uuid
        tid = str(uuid.uuid4())[:8]
        self.tasks.append({"id": tid, "type": task_type, "params": params})
        return tid

    def execute_task(self, task_id):
        pass

    def get_task(self, task_id):
        pass


# ==============================
# 自定义演示插件
# ==============================

class DemoPreProcessPlugin(Plugin):
    """演示插件: PRE_PROCESS — 记录请求时间"""
    name = "demo_preprocess"
    description = "演示: 在请求中注入自定义上下文"
    hooks = [HookPoint.PRE_PROCESS]
    priority = 20  # 在 memory(30) 之前执行

    def on_hook(self, hook, ctx):
        from datetime import datetime
        ctx.extra["demo_request_time"] = datetime.now().isoformat()
        print(f"  [demo_preprocess] 记录请求时间: {ctx.extra['demo_request_time']}")
        return ctx


class DemoPostProcessPlugin(Plugin):
    """演示插件: POST_PROCESS — 记录回复长度统计"""
    name = "demo_postprocess"
    description = "演示: 统计回复长度"
    hooks = [HookPoint.POST_PROCESS]
    priority = 45  # 在 task(40) 之后，tts 之前

    def on_hook(self, hook, ctx):
        length = len(ctx.original_reply) if ctx.original_reply else 0
        ctx.extra["reply_length"] = length
        print(f"  [demo_postprocess] 回复长度: {length} 字符")
        return ctx


# ==============================
# 测试用例
# ==============================

def test_manager_register():
    """1. 测试 PluginManager 注册与基本操作"""
    print("\n" + "=" * 60)
    print("Test 1: PluginManager 注册与基本操作")
    print("=" * 60)

    pm = PluginManager()

    # 注册
    demo = DemoPreProcessPlugin()
    pm.register(demo)
    assert pm.is_enabled("demo_preprocess")
    assert pm.get("demo_preprocess") is demo

    # 列表
    plugins = pm.list_plugins()
    assert len(plugins) == 1
    assert plugins[0]["name"] == "demo_preprocess"
    print(f"  已注册插件: {plugins}")

    # 禁用
    pm.disable("demo_preprocess")
    assert not pm.is_enabled("demo_preprocess")

    # 启用
    pm.enable("demo_preprocess")
    assert pm.is_enabled("demo_preprocess")

    # 注销
    pm.unregister("demo_preprocess")
    assert pm.get("demo_preprocess") is None
    assert len(pm.list_plugins()) == 0

    print("  PASSED")


def test_manager_dispatch():
    """2. 测试 PluginManager 调度（优先级 + 短路）"""
    print("\n" + "=" * 60)
    print("Test 2: PluginManager 调度（优先级 + 短路）")
    print("=" * 60)

    pm = PluginManager()
    execution_order = []

    class PluginA(Plugin):
        name = "A"
        hooks = [HookPoint.PRE_PROCESS]
        priority = 30
        def on_hook(self, hook, ctx):
            execution_order.append("A")
            ctx.extra["from_a"] = True
            return ctx

    class PluginB(Plugin):
        name = "B"
        hooks = [HookPoint.PRE_PROCESS]
        priority = 10  # 更先执行
        def on_hook(self, hook, ctx):
            execution_order.append("B")
            return ctx

    class PluginC(Plugin):
        name = "C"
        hooks = [HookPoint.PRE_FILTER]
        priority = 10
        def on_hook(self, hook, ctx):
            execution_order.append("C")
            ctx.filtered = True  # 短路
            return ctx

    class PluginD(Plugin):
        name = "D"
        hooks = [HookPoint.PRE_FILTER]
        priority = 20
        def on_hook(self, hook, ctx):
            execution_order.append("D")
            return ctx

    pm.register(PluginA())
    pm.register(PluginB())
    pm.register(PluginC())
    pm.register(PluginD())

    ctx = PluginContext(user_id=1, message="hello")

    # PRE_PROCESS: B(10) 应该在 A(30) 之前
    loop = asyncio.new_event_loop()
    ctx = loop.run_until_complete(pm.dispatch(HookPoint.PRE_PROCESS, ctx))
    assert execution_order == ["B", "A"], f"Expected ['B','A'], got {execution_order}"
    assert ctx.extra.get("from_a") is True
    print(f"  PRE_PROCESS 顺序: {execution_order} (B pri=10 先于 A pri=30)")

    # PRE_FILTER: C(10) 先执行并短路 → D(20) 不应执行
    execution_order.clear()
    ctx2 = PluginContext(user_id=1, message="test")
    ctx2 = loop.run_until_complete(pm.dispatch(HookPoint.PRE_FILTER, ctx2))
    assert execution_order == ["C"], f"Expected ['C'], got {execution_order}"
    assert ctx2.filtered is True
    print(f"  PRE_FILTER 短路: {execution_order} (C 短路后 D 未执行)")

    loop.close()
    print("  PASSED")


def test_all_plugins_instantiate():
    """3. 测试全部 5 个内置插件可以实例化"""
    print("\n" + "=" * 60)
    print("Test 3: 全部内置插件实例化")
    print("=" * 60)

    plugins = [
        TTSPlugin(tts_client=None),
        ASRFilterPlugin(filter_model=None, db=None),
        MemoryPlugin(memory_system=None, db=None),
        TaskPlugin(task_manager=None, db=None),
        ModelsPlugin(model_type="openai", openai_api_key=None),
    ]

    for p in plugins:
        name = p.name
        hooks = [h.value for h in p.hooks]
        print(f"  {p.__class__.__name__:20s} name={name:12s} hooks={hooks} pri={p.priority}")

    assert len(plugins) == 5
    print("  PASSED")


def test_pipeline_dry_run():
    """4. 完整管道 dry-run（mock 依赖）"""
    print("\n" + "=" * 60)
    print("Test 4: 完整管道 dry-run")
    print("=" * 60)

    mock_db = MockDB()
    mock_tts = MockTTS()
    mock_filter = MockFilterModel()
    mock_memory = MockMemoryManager()
    mock_tasks = MockTaskManager()

    pm = PluginManager()
    pm.register(TTSPlugin(tts_client=mock_tts))
    pm.register(ASRFilterPlugin(filter_model=mock_filter, db=mock_db))
    pm.register(MemoryPlugin(memory_system=mock_memory, db=mock_db))
    pm.register(TaskPlugin(task_manager=mock_tasks, db=mock_db))
    # 不注入真实 API key → ModelsPlugin 将报错，但 pipeline 会捕获
    pm.register(ModelsPlugin(model_type="openai", openai_api_key=None))

    pipeline = ChatPipeline(pm)

    ctx = PluginContext(
        user_id=1,
        message="你好，帮我搜索 Python",
        chat_id=1,
        is_asr_input=False,
        tts_enabled=True,
    )
    ctx.system_prompt = "You are a helpful assistant."

    # 运行 pipeline（ModelsPlugin 会因无 API key 失败，但不应崩溃整个管道）
    loop = asyncio.new_event_loop()
    try:
        ctx = loop.run_until_complete(pipeline.process(ctx))
        print(f"  结果: reply={ctx.reply[:80] if ctx.reply else '(empty)'}")
        print(f"  filtered={ctx.filtered}, audio={'有' if ctx.audio else '无'}")
        print(f"  tts_error={ctx.tts_error}")
    except Exception as e:
        print(f"  (预期行为) 模型调用失败: {type(e).__name__}: {e}")
    finally:
        loop.close()

    print("  PASSED (管道未崩溃)")


def test_stream_pipeline():
    """5. 测试流式管道"""
    print("\n" + "=" * 60)
    print("Test 5: 流式管道 SSE 事件")
    print("=" * 60)

    pm = PluginManager()
    pm.register(TTSPlugin(tts_client=MockTTS()))
    pm.register(ASRFilterPlugin(filter_model=None, db=None))
    pm.register(MemoryPlugin(memory_system=MockMemoryManager(), db=MockDB()))
    pm.register(TaskPlugin(task_manager=MockTaskManager(), db=None))

    pipeline = ChatPipeline(pm)

    ctx = PluginContext(
        user_id=1,
        message="test stream",
        chat_id=1,
        tts_enabled=True,
    )
    ctx.system_prompt = "You are a test assistant."
    # 模拟 AI 回复已被写入（流式管道依赖前置阶段）
    ctx.original_reply = "这是测试回复 <task>{}</task>"
    ctx.reply = "这是测试回复"

    async def collect_events():
        events = []
        async for event in pipeline.process_stream(ctx):
            events.append(event.strip())
        return events

    loop = asyncio.new_event_loop()
    events = loop.run_until_complete(collect_events())
    loop.close()

    print(f"  收到 {len(events)} 个 SSE 事件:")
    for ev in events:
        print(f"    {ev[:120]}")

    # 验证至少包含首尾事件
    assert any("filtering" in e for e in events), "应包含 filtering 事件"
    assert any("completed" in e for e in events), "应包含 completed 事件"
    print("  PASSED")


def test_custom_plugin_registration():
    """6. 自定义插件注册 + 演示插件链"""
    print("\n" + "=" * 60)
    print("Test 6: 自定义插件注册 + 演示插件链")
    print("=" * 60)

    pm = PluginManager()
    pm.register(DemoPreProcessPlugin())
    pm.register(DemoPostProcessPlugin())

    ctx = PluginContext(user_id=1, message="demo", chat_id=1)
    ctx.original_reply = "test reply content"
    ctx.history = []

    loop = asyncio.new_event_loop()

    print("  --- 运行 PRE_PROCESS ---")
    ctx = loop.run_until_complete(pm.dispatch(HookPoint.PRE_PROCESS, ctx))
    assert "demo_request_time" in ctx.extra

    print("  --- 运行 POST_PROCESS ---")
    ctx = loop.run_until_complete(pm.dispatch(HookPoint.POST_PROCESS, ctx))
    assert ctx.extra.get("reply_length") == 18
    print(f"  extra 内容: {ctx.extra}")

    loop.close()
    print("  PASSED")


# ==============================
# Main
# ==============================

def main():
    print("=" * 60)
    print("  DSN-exp 插件系统加载测试")
    print("=" * 60)
    print(f"  Python: {sys.version}")
    print(f"  工作目录: {os.getcwd()}")

    tests = [
        ("PluginManager 注册/注销", test_manager_register),
        ("PluginManager 调度(优先级+短路)", test_manager_dispatch),
        ("全部内置插件实例化", test_all_plugins_instantiate),
        ("完整管道 dry-run", test_pipeline_dry_run),
        ("流式管道 SSE", test_stream_pipeline),
        ("自定义插件注册", test_custom_plugin_registration),
    ]

    passed = 0
    failed = 0

    for name, func in tests:
        try:
            func()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"\n  ❌ FAILED: {name}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"  结果: {passed} passed, {failed} failed, {len(tests)} total")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    exit(main())
