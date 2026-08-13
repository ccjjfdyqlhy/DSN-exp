# tests/test_prompt_ecosystem.py
# Prompt 生态加载测试 — PromptLibrary + PersonalitySystem + PromptEngine

"""
用法:
    python tests/test_prompt_ecosystem.py

测试内容:
    1. PromptLibrary — 扫描加载 MD 文件
    2. PromptLibrary — 按 category 聚合
    3. PromptLibrary — enable / disable / toggle
    4. PersonalitySystem — 加载性格预设
    5. PersonalitySystem — 性格切换 + 自然语言描述
    6. PersonalitySystem — 情绪动态更新 + 衰减
    7. PromptEngine — 组装完整 system prompt
    8. 旧 prompt.py 回退兼容性
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_library_scan():
    """1. PromptLibrary 扫描加载 MD 文件"""
    print("\n" + "=" * 60)
    print("Test 1: PromptLibrary 扫描加载")
    print("=" * 60)

    from apps.dsn.prompt.library import PromptLibrary

    lib = PromptLibrary()
    count = lib.scan_and_load("apps/dsn/prompt/prompts/core", "apps/dsn/prompt/prompts/capabilities")

    assert count >= 6, f"应至少加载 6 个文件，实际 {count}"
    print(f"  加载了 {count} 个文件")

    for entry in lib.entries:
        print(f"    [{entry.category:15s}] {entry.name:20s} pri={entry.priority} enabled={entry.enabled}")

    print("  PASSED")


def test_library_aggregation():
    """2. PromptLibrary 按 category 聚合"""
    print("\n" + "=" * 60)
    print("Test 2: PromptLibrary 按 category 聚合")
    print("=" * 60)

    from apps.dsn.prompt.library import PromptLibrary

    lib = PromptLibrary()
    lib.scan_and_load("apps/dsn/prompt/prompts/core", "apps/dsn/prompt/prompts/capabilities")

    core = lib.get_content_by_category("core")
    assert "EXA" in core, "core 应包含身份定义"
    assert "TTS" in core or "tts" in core.lower(), "core 应包含格式说明"
    print(f"  core 长度: {len(core)} 字符")

    caps = lib.get_content_by_category("capabilities")
    assert "task" in caps.lower(), "capabilities 应包含任务处理"
    assert "reminder" in caps, "capabilities 应包含提醒"
    assert "reasoner" in caps, "capabilities 应包含推理"
    print(f"  capabilities 长度: {len(caps)} 字符")

    # 查询单个
    fmt = lib.get_content("format")
    assert "TTS" in fmt or "tts" in fmt.lower()
    print(f"  format 内容: {fmt[:60]}...")

    print("  PASSED")


def test_library_toggle():
    """3. PromptLibrary enable / disable / toggle"""
    print("\n" + "=" * 60)
    print("Test 3: PromptLibrary enable / disable / toggle")
    print("=" * 60)

    from apps.dsn.prompt.library import PromptLibrary

    lib = PromptLibrary()
    lib.scan_and_load("apps/dsn/prompt/prompts/core")

    # 禁用 safety
    assert lib.disable("safety")
    core = lib.get_content_by_category("core")
    assert "后台禁区" not in core, "禁用后不应包含 safety 内容"
    print("  safety 已禁用，core 内容不再包含安全约束")

    # 启用
    assert lib.enable("safety")
    core = lib.get_content_by_category("core")
    assert "后台禁区" in core or "安全" in core, "启用后应包含 safety 内容"
    print("  safety 已重新启用")

    # 热重载
    assert lib.reload("safety")
    print("  safety 已热重载")

    # 列表
    entries = lib.list_entries()
    assert len(entries) >= 3
    print(f"  列出 {len(entries)} 个条目")

    print("  PASSED")


def test_personality_presets():
    """4. PersonalitySystem 加载 + 切换性格预设"""
    print("\n" + "=" * 60)
    print("Test 4: PersonalitySystem 性格预设")
    print("=" * 60)

    from apps.dsn.prompt._personality_v1_legacy import PersonalitySystem

    ps = PersonalitySystem()
    count = ps.scan_presets("apps/dsn/prompt/prompts/personality")
    assert count >= 4, f"应加载至少 4 个预设，实际 {count}"
    print(f"  加载了 {count} 个性格预设")

    presets = ps.list_presets()
    names = [p["name"] for p in presets]
    print(f"  可用预设: {names}")

    # 加载默认
    assert ps.load_preset("default")
    assert ps.profile.preset_name == "default"

    # 切换到傲娇
    assert ps.load_preset("tsundere")
    assert ps.profile.preset_name == "tsundere"
    assert ps.profile.sarcasm > 0.5, "傲娇应有高讽刺度"
    assert len(ps.profile.catchphrases) >= 2, "傲娇应有口头禅"
    print(f"  傲娇性格 — 讽刺度={ps.profile.sarcasm}, 口头禅={ps.profile.catchphrases}")

    # 切换到温柔
    assert ps.load_preset("gentle")
    assert ps.profile.agreeableness > 0.8, "温柔应有高宜人性"
    assert ps.profile.sarcasm == 0.0, "温柔不应有讽刺"
    print(f"  温柔性格 — 宜人性={ps.profile.agreeableness}, 讽刺度={ps.profile.sarcasm}")

    print("  PASSED")


def test_personality_prompt():
    """5. PersonalitySystem 自然语言描述生成"""
    print("\n" + "=" * 60)
    print("Test 5: PersonalitySystem 自然语言描述")
    print("=" * 60)

    from apps.dsn.prompt._personality_v1_legacy import PersonalitySystem

    ps = PersonalitySystem()
    ps.scan_presets("apps/dsn/prompt/prompts/personality")
    ps.load_preset("default")

    prompt = ps.generate_personality_prompt()
    print(f"  默认性格描述 ({len(prompt)} 字符):")
    for line in prompt.split("\n"):
        if line.strip():
            print(f"    {line.strip()[:100]}")

    assert "你的性格特点" in prompt
    assert "你的说话风格" in prompt
    print("\n  PASSED")


def test_personality_dynamics():
    """6. PersonalitySystem 情绪动态"""
    print("\n" + "=" * 60)
    print("Test 6: PersonalitySystem 情绪动态")
    print("=" * 60)

    from apps.dsn.prompt._personality_v1_legacy import PersonalitySystem

    ps = PersonalitySystem()
    ps.load_preset("default")

    init_curiosity = ps.profile.curiosity
    init_intimacy = ps.profile.intimacy

    # 模拟交互
    for i in range(5):
        ps.on_interaction(message_length=150, is_positive=True)
    assert ps.profile.intimacy > init_intimacy, "亲密度应增长"
    assert ps.profile.curiosity > init_curiosity, "长消息应增加好奇心"
    print(f"  5 次正面交互后: intimacy={ps.profile.intimacy:.3f}, curiosity={ps.profile.curiosity:.3f}")

    # 情绪衰减
    curr_curiosity = ps.profile.curiosity
    ps.decay(steps=10)
    assert ps.profile.curiosity < curr_curiosity, "衰减后好奇心应降低"
    print(f"  10 步衰减后: curiosity={ps.profile.curiosity:.3f}")

    # 不应低于基线
    assert ps.profile.curiosity >= ps.profile.curiosity_baseline - 0.01

    print("  PASSED")


def test_prompt_engine():
    """7. PromptEngine 组装完整 system prompt"""
    print("\n" + "=" * 60)
    print("Test 7: PromptEngine 组装")
    print("=" * 60)

    from apps.dsn.prompt.library import PromptLibrary
    from apps.dsn.prompt.personality_v2 import PersonalitySystemV2
    from apps.dsn.prompt.engine import PromptEngine

    lib = PromptLibrary()
    lib.scan_and_load("apps/dsn/prompt/prompts/core", "apps/dsn/prompt/prompts/capabilities")

    ps = PersonalitySystemV2()
    ps.scan_presets("apps/dsn/prompt/personality_v2/presets")
    ps.load_preset(42, "default")

    engine = PromptEngine(library=lib, personality_v2=ps)

    user_info = {"uid": 42, "nickname": "test_user"}
    prompt = engine.build_system_prompt(user_info)

    print(f"  完整 system prompt ({len(prompt)} 字符)")
    print("  ---")
    for line in prompt.split("\n"):
        if line.strip():
            print(f"  {line[:120]}")

    # 验证各部分都存在
    assert "EXA" in prompt, "应包含身份"
    assert "test_user" in prompt, "应包含用户昵称"
    assert "性格" in prompt, "应包含性格描述"
    assert "task" in prompt.lower(), "应包含能力定义"

    print("  ---")
    print("  PASSED")


def test_old_prompt_compat():
    """8. 旧 prompt.py 回退兼容性"""
    print("\n" + "=" * 60)
    print("Test 8: 旧 prompt.py 回退兼容")
    print("=" * 60)

    from apps.dsn.prompt import get_system_prompt as old_get

    # 不初始化 PromptEngine，验证回退工作
    user_info = {"uid": 1, "nickname": "user"}
    result = old_get(user_info)

    assert "EXA" in result
    assert "user" in result
    print(f"  回退提示词长度: {len(result)} 字符")
    print("  PASSED")


def test_engine_integration():
    """9. PromptEngine 初始化 + 旧 prompt.py 自动切换"""
    print("\n" + "=" * 60)
    print("Test 9: PromptEngine 初始化 + 自动切换")
    print("=" * 60)

    from apps.dsn.prompt.engine import init_prompt_engine

    engine = init_prompt_engine(
        library_dirs=["apps/dsn/prompt/prompts/core", "apps/dsn/prompt/prompts/capabilities"],
        personality_v2_dir="apps/dsn/prompt/personality_v2/presets",
    )

    # 验证旧 prompt.py 自动使用新引擎
    from apps.dsn.prompt import get_system_prompt
    result = get_system_prompt({"uid": 1, "nickname": "auto_user"})

    assert "性格" in result, "应通过新引擎生成性格描述"
    assert "auto_user" in result
    assert "capabilities" in result.lower() or "task" in result.lower()
    print(f"  新引擎提示词长度: {len(result)} 字符")

    # 获取初始提示词
    init = engine.get_initial_prompt({"uid": 1, "nickname": "new_user"})
    assert "幕启" in init or "场景说明" in init
    print(f"  初始提示词长度: {len(init)} 字符")

    print("  PASSED")


# ==============================

def main():
    print("=" * 60)
    print("  DSN-exp Prompt 生态测试")
    print("=" * 60)
    print(f"  Python: {sys.version}")
    print(f"  工作目录: {os.getcwd()}")

    tests = [
        ("PromptLibrary 扫描加载", test_library_scan),
        ("PromptLibrary 按 category 聚合", test_library_aggregation),
        ("PromptLibrary enable/disable/toggle", test_library_toggle),
        ("PersonalitySystem 性格预设", test_personality_presets),
        ("PersonalitySystem 自然语言描述", test_personality_prompt),
        ("PersonalitySystem 情绪动态", test_personality_dynamics),
        ("PromptEngine 组装", test_prompt_engine),
        ("旧 prompt.py 回退兼容", test_old_prompt_compat),
        ("PromptEngine 初始化 + 自动切换", test_engine_integration),
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
