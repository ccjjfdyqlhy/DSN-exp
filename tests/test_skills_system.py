# tests/test_skills_system.py
# 技能系统完整测试 — SkillLoader + SkillRegistry + SkillManager + SkillsPlugin + Distillation

"""
用法:
    python tests/test_skills_system.py

测试内容:
    1. SkillLoader — 加载内置技能
    2. SkillRegistry — 注册/工具调用/提示词聚合
    3. SkillManager — 扫描/启用/禁用/卸载
    4. SkillsPlugin — <tool> 标签解析与执行
    5. SkillsPlugin + PromptEngine 集成
    6. DistillPlugin — 蒸馏触发
    7. DistillationEngine — 对话收集 + 草案管理
"""

from __future__ import annotations

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_loader_load_skills():
    """1. SkillLoader 加载内置技能"""
    print("\n" + "=" * 60)
    print("Test 1: SkillLoader 加载内置技能")
    print("=" * 60)

    from skills.loader import SkillLoader

    loader = SkillLoader()

    # 加载 web_search
    ws = loader.load("skills/builtin/web_search")
    assert ws is not None
    assert ws.name == "web_search"
    assert ws.display_name == "网页搜索"
    assert len(ws.prompts) >= 2  # instruction + examples
    assert len(ws.tools) == 1
    assert ws.tools[0].name == "search"
    print(f"  web_search: {ws.name} — prompts={len(ws.prompts)}, tools={len(ws.tools)}")

    # 加载 file_manager
    fm = loader.load("skills/builtin/file_manager")
    assert fm is not None
    assert fm.name == "file_manager"
    assert len(ws.tools) >= 1
    assert len(fm.tools) >= 1  # read_file, list_dir, write_file
    print(f"  file_manager: {fm.name} — prompts={len(fm.prompts)}, tools={len(fm.tools)}")

    print("  PASSED")


def test_registry():
    """2. SkillRegistry 注册 + 工具调用 + 提示词聚合"""
    print("\n" + "=" * 60)
    print("Test 2: SkillRegistry 注册 + 工具调用 + 提示词聚合")
    print("=" * 60)

    from skills.loader import SkillLoader
    from skills.registry import SkillRegistry

    registry = SkillRegistry()
    loader = SkillLoader()

    # 注册 web_search
    ws = loader.load("skills/builtin/web_search")
    registry.register_skill(ws)
    assert registry.has_skill("web_search")
    assert "web_search.search" in registry.list_active_tools()
    print(f"  已注册工具: {registry.list_active_tools()}")

    # 聚合提示词
    prompts = registry.get_all_skill_prompts()
    assert "网页搜索" in prompts
    assert "使用方式" in prompts
    print(f"  聚合提示词长度: {len(prompts)} 字符")

    # 调用搜索工具
    result = registry.call_tool("web_search", "search",
                                {"query": "Python", "max_results": 3})
    assert result.get("query") == "Python"
    if result.get("success"):
        print(f"  搜索成功: {result.get('count', 0)} 条结果")
    else:
        print(f"  搜索返回: success={result.get('success')}, error={result.get('error', 'N/A')}")

    # 获取工具规格
    spec = registry.get_tool_spec("web_search", "search")
    assert spec is not None
    assert spec["name"] == "search"
    print(f"  工具规格: {spec['name']} ({spec['description'][:40]}...)")

    # 注册 file_manager 并测试
    fm = loader.load("skills/builtin/file_manager")
    registry.register_skill(fm)
    assert registry.has_skill("file_manager")

    # 测试 list_dir
    result = registry.call_tool("file_manager", "list_dir", {"path": "."})
    if result.get("success"):
        print(f"  list_dir 成功: {result.get('count', 0)} 项")
    else:
        print(f"  list_dir: {result.get('error', '')}")

    # 注销
    registry.unregister_skill("file_manager")
    assert not registry.has_skill("file_manager")

    print("  PASSED")


def test_manager():
    """3. SkillManager 扫描 + 生命周期"""
    print("\n" + "=" * 60)
    print("Test 3: SkillManager 扫描 + 生命周期")
    print("=" * 60)

    from skills.registry import SkillRegistry
    from skills.manager import SkillManager

    registry = SkillRegistry()
    mgr = SkillManager(skill_dirs=["skills/builtin"], registry=registry)

    # 扫描加载
    count = mgr.scan_and_load()
    assert count >= 2, f"应加载至少 2 个技能，实际 {count}"
    print(f"  加载了 {count} 个技能")

    # 列表
    skills = mgr.list_skills()
    names = [s["name"] for s in skills]
    print(f"  技能列表: {names}")
    assert "web_search" in names
    assert "file_manager" in names

    # 禁用 web_search
    assert mgr.disable("web_search")
    assert not registry.has_skill("web_search")
    assert "网页搜索" not in registry.get_all_skill_prompts()
    print("  web_search 已禁用，提示词不含搜索相关内容")

    # 重新启用
    assert mgr.enable("web_search")
    assert registry.has_skill("web_search")
    assert "网页搜索" in registry.get_all_skill_prompts()
    print("  web_search 已重新启用")

    # 卸载
    assert mgr.unload("web_search")
    assert mgr.get_skill("web_search") is None

    # 重新扫描加载
    count2 = mgr.scan_and_load()
    assert registry.has_skill("web_search")
    print(f"  重新扫描: 加载了 {count2} 个技能")

    print("  PASSED")


def test_skills_plugin():
    """4. SkillsPlugin <tool> 标签解析与执行"""
    print("\n" + "=" * 60)
    print("Test 4: SkillsPlugin <tool> 标签解析与执行")
    print("=" * 60)

    from plugins.base import PluginContext, HookPoint
    from plugins.builtin.skills_plugin import SkillsPlugin
    from skills.loader import SkillLoader
    from skills.registry import SkillRegistry

    registry = SkillRegistry()
    loader = SkillLoader()

    ws = loader.load("skills/builtin/web_search")
    registry.register_skill(ws)

    fm = loader.load("skills/builtin/file_manager")
    registry.register_skill(fm)

    plugin = SkillsPlugin(skill_registry=registry)

    # 测试搜索 <tool>
    ctx = PluginContext(user_id=1, message="搜索测试", chat_id=1)
    ctx.original_reply = '好的，帮你搜索。\n<tool>\n{"skill": "web_search", "tool": "search", "params": {"query": "Python 3.13", "max_results": 2}}\n</tool>'
    ctx.reply = ctx.original_reply

    ctx = plugin.on_hook(HookPoint.POST_PROCESS, ctx)
    assert ctx.reply is not None
    assert "<tool>" not in ctx.reply, "reply 中不应再包含 <tool> 标签"
    print(f"  搜索回复: {ctx.reply[:120]}...")

    # 测试 list_dir <tool>
    ctx2 = PluginContext(user_id=1, message="列出目录", chat_id=1)
    ctx2.original_reply = '列出当前目录：\n<tool>\n{"skill": "file_manager", "tool": "list_dir", "params": {"path": "."}}\n</tool>'
    ctx2.reply = ctx2.original_reply

    ctx2 = plugin.on_hook(HookPoint.POST_PROCESS, ctx2)
    assert "<tool>" not in ctx2.reply
    print(f"  list_dir 回复: {ctx2.reply[:120]}...")

    # 测试多个 <tool> 标签
    ctx3 = PluginContext(user_id=1, message="多工具测试", chat_id=1)
    ctx3.original_reply = (
        '搜索：\n<tool>\n{"skill": "web_search", "tool": "search", '
        '"params": {"query": "test", "max_results": 1}}\n</tool>\n'
        '列出：\n<tool>\n{"skill": "file_manager", "tool": "list_dir", '
        '"params": {"path": "."}}\n</tool>'
    )
    ctx3.reply = ctx3.original_reply

    ctx3 = plugin.on_hook(HookPoint.POST_PROCESS, ctx3)
    assert "<tool>" not in ctx3.reply
    print(f"  多工具回复: {ctx3.reply[:200]}...")

    # 测试无效 JSON
    ctx4 = PluginContext(user_id=1, message="无效JSON", chat_id=1)
    ctx4.original_reply = '<tool>\n{invalid json}\n</tool>'
    ctx4.reply = ctx4.original_reply

    ctx4 = plugin.on_hook(HookPoint.POST_PROCESS, ctx4)
    assert "<tool>" not in ctx4.reply  # 标签被移除
    print("  无效 JSON 标签已正确移除")

    # 测试不存在的技能
    ctx5 = PluginContext(user_id=1, message="不存在", chat_id=1)
    ctx5.original_reply = '<tool>\n{"skill": "nonexistent", "tool": "foo", "params": {}}\n</tool>'
    ctx5.reply = ctx5.original_reply

    ctx5 = plugin.on_hook(HookPoint.POST_PROCESS, ctx5)
    assert "<tool>" not in ctx5.reply
    assert "工具调用失败" in ctx5.reply or "nonexistent" in ctx5.reply
    print("  不存在技能的错误已正确报告")

    print("  PASSED")


def test_skills_plugin_empty():
    """5. SkillsPlugin 无工具标签时保持原样"""
    print("\n" + "=" * 60)
    print("Test 5: SkillsPlugin 无工具标签时保持原样")
    print("=" * 60)

    from plugins.base import PluginContext, HookPoint
    from plugins.builtin.skills_plugin import SkillsPlugin
    from skills.registry import SkillRegistry

    registry = SkillRegistry()
    plugin = SkillsPlugin(skill_registry=registry)

    ctx = PluginContext(user_id=1, message="hello", chat_id=1)
    ctx.original_reply = "这是普通回复，没有工具标签"
    ctx.reply = ctx.original_reply

    ctx = plugin.on_hook(HookPoint.POST_PROCESS, ctx)
    assert ctx.reply == ctx.original_reply
    print("  无标签回复保持不变")

    # 无 registry 时
    plugin2 = SkillsPlugin(skill_registry=None)
    ctx2 = PluginContext(user_id=1, message="test", chat_id=1)
    ctx2.original_reply = '<tool>\n{"skill": "x", "tool": "y", "params": {}}\n</tool>'
    ctx2.reply = ctx2.original_reply
    ctx2 = plugin2.on_hook(HookPoint.POST_PROCESS, ctx2)
    assert ctx2.reply == ctx2.original_reply  # 无 registry 时原样返回
    print("  无 registry 时原样返回")

    print("  PASSED")


def test_prompt_engine_with_skills():
    """6. PromptEngine + SkillRegistry 集成"""
    print("\n" + "=" * 60)
    print("Test 6: PromptEngine + SkillRegistry 集成")
    print("=" * 60)

    from skills.loader import SkillLoader
    from skills.registry import SkillRegistry
    from prompt.library import PromptLibrary
    from prompt._personality_v1_legacy import PersonalitySystem
    from prompt.engine import PromptEngine

    lib = PromptLibrary()
    lib.scan_and_load("prompt/prompts/core", "prompt/prompts/capabilities")

    ps = PersonalitySystem()
    ps.scan_presets("prompt/prompts/personality")
    ps.load_preset("default")

    registry = SkillRegistry()
    loader = SkillLoader()

    ws = loader.load("skills/builtin/web_search")
    registry.register_skill(ws)

    engine = PromptEngine(library=lib, personality=ps, skill_registry=registry)
    prompt = engine.build_system_prompt({"uid": 42, "nickname": "test_user"})

    # 验证技能提示词已注入
    assert "网页搜索" in prompt, "system prompt 应包含技能提示词"
    assert "使用方式" in prompt
    assert "EXA" in prompt  # core
    assert "性格" in prompt  # personality

    print(f"  system prompt 长度: {len(prompt)} 字符")
    print("  包含: EXA(身份), 性格描述, 能力定义, 技能提示词, 用户上下文")

    # 验证不重复注入
    count = prompt.count("网页搜索技能")
    assert count <= 1, f"技能提示词不应重复, 实际出现 {count} 次"

    print("  PASSED")


def test_distill_plugin():
    """7. DistillPlugin 触发逻辑"""
    print("\n" + "=" * 60)
    print("Test 7: DistillPlugin 触发逻辑")
    print("=" * 60)

    from plugins.base import PluginContext, HookPoint
    from plugins.builtin.distill_plugin import DistillPlugin

    # 无 engine 时跳过
    plugin = DistillPlugin(distillation_engine=None)
    ctx = PluginContext(user_id=1, message="test", chat_id=1)
    ctx = plugin.on_hook(HookPoint.POST_PROCESS, ctx)
    assert ctx.reply == ""  # 无变化
    print("  无 distillation_engine 时跳过")

    # 关键词触发检测
    assert "蒸馏技能" in DistillPlugin._TRIGGER_KEYWORDS
    assert "总结学到了什么" in DistillPlugin._TRIGGER_KEYWORDS
    print(f"  触发关键词: {len(DistillPlugin._TRIGGER_KEYWORDS)} 个")

    print("  PASSED")


def test_distillation_engine():
    """8. DistillationEngine 核心方法"""
    print("\n" + "=" * 60)
    print("Test 8: DistillationEngine 核心方法")
    print("=" * 60)

    from skills.distill import DistillationEngine

    # 无 db 时
    engine = DistillationEngine(db=None, skill_manager=None, llm_client=None)
    result = engine.run(user_id=1)
    assert result["conversations_analyzed"] == 0
    assert result["drafts_created"] == 0
    print("  无 db 时: 对话0, 草案0")

    # 测试 draft 管理
    drafts = engine.list_drafts()
    assert isinstance(drafts, list)
    print(f"  当前草案数: {len(drafts)}")

    # reject 不存在的草案
    assert not engine.reject_draft("nonexistent_draft")
    print("  拒绝不存在草案: 返回 False")

    # approve 不存在的草案
    assert not engine.approve_draft("nonexistent_draft")
    print("  批准不存在草案: 返回 False")

    print("  PASSED")


def test_file_manager_tool():
    """9. FileManager 工具实际操作"""
    print("\n" + "=" * 60)
    print("Test 9: FileManager 工具实际操作")
    print("=" * 60)

    from skills.loader import SkillLoader
    from skills.registry import SkillRegistry

    registry = SkillRegistry()
    loader = SkillLoader()

    fm = loader.load("skills/builtin/file_manager")
    registry.register_skill(fm)

    # list_dir
    result = registry.call_tool("file_manager", "list_dir", {"path": "."})
    if result.get("success"):
        print(f"  list_dir: {result.get('count', 0)} 项")
        for item in result.get("items", [])[:5]:
            print(f"    {item['name']} ({item['type']})")

    # 测试写入 + 读取 + 清理
    test_path = "skills/distilled/_drafts/_test_skill_io.txt"
    write_result = registry.call_tool("file_manager", "write_file",
                                       {"path": test_path, "content": "hello skills test"})
    if write_result.get("success"):
        print(f"  write_file: OK ({write_result.get('size')} bytes)")

        read_result = registry.call_tool("file_manager", "read_file",
                                          {"path": test_path})
        if read_result.get("success"):
            assert read_result["content"] == "hello skills test"
            print(f"  read_file: OK, content='{read_result['content']}'")

        # 清理
        os.remove(test_path)
        print("  测试文件已清理")

    # 路径安全测试
    result = registry.call_tool("file_manager", "read_file",
                                 {"path": "../../etc/passwd"})
    assert not result.get("success"), "越权路径应被拒绝"
    print(f"  路径安全检查: {result.get('error', '')}")

    print("  PASSED")


# ==============================

def main():
    print("=" * 60)
    print("  DSN-exp 技能系统测试")
    print("=" * 60)
    print(f"  Python: {sys.version}")
    print(f"  工作目录: {os.getcwd()}")

    tests = [
        ("SkillLoader 加载内置技能", test_loader_load_skills),
        ("SkillRegistry 注册+工具调用+提示词聚合", test_registry),
        ("SkillManager 扫描+生命周期", test_manager),
        ("SkillsPlugin tool标签解析与执行", test_skills_plugin),
        ("SkillsPlugin 无工具标签时保持原样", test_skills_plugin_empty),
        ("PromptEngine + SkillRegistry 集成", test_prompt_engine_with_skills),
        ("DistillPlugin 触发逻辑", test_distill_plugin),
        ("DistillationEngine 核心方法", test_distillation_engine),
        ("FileManager 工具实际操作", test_file_manager_tool),
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
