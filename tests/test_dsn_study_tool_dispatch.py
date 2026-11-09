# -*- coding: utf-8 -*-
"""dsn_study 技能工具派发护栏（阶段 0）。

背景（2026-11-08 实机发现）：
`harness/skills/registry.py` 过去按**工具名**查工具类上的方法，
完全忽略 `skill.yaml` 里 `tools[].methods[].name` 声明的方法名。
凡是「工具名 ≠ 方法名」的技能声明，都是**注册成功、调用必挂**
（`ValueError: 工具方法不存在`）。

dsn_study 当时有 9 个这样的工具（Obsidian 技能全挂、学习跟踪 5 个全挂、
题库的读/改 2 个挂），而 `apps/dsn` 零例 —— 这正是「dsn 好用、study 不好用」
的根因。更糟的是**测试全绿**：既有用例调的都是恰好能用的工具，
9 个坏工具从未被任何测试触及。

本文件把这条护栏固化成回归测试：
  * 全部已注册工具都必须可派发；
  * 当年坏掉的 9 个工具必须逐一实调通过；
  * 基座层给出显式、可读的报错而不是静默失败。
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="module")
def study_app(tmp_path_factory):
    """启动一个隔离的 dsn_study 应用实例（不拉真实模型/TTS）。"""
    db = tmp_path_factory.mktemp("study") / "qb.db"
    os.environ["QUESTION_BANK_DB_PATH"] = str(db)
    os.environ["LOG_DIR"] = str(tmp_path_factory.mktemp("logs"))
    os.environ["TTS_AUTOSTART"] = "false"
    os.environ["TTS_WARMUP"] = "false"
    os.environ["MCP_ENABLED"] = "false"
    from apps.dsn_study import boot
    boot.create_application()
    return boot.engine


# ── 护栏 1：全部已注册工具都必须可派发 ──

def test_no_undispatchable_tools(study_app):
    """任何一个「注册成功但调用必挂」的工具都视为失败。

    这是最关键的一条：它把整类缺陷从「静默」变成「CI 阻塞」。
    """
    broken = study_app.skill_registry.undispatchable_tools()
    assert not broken, "存在无法派发的工具（注册成功但调用必挂）: %s" % (
        [b["key"] for b in broken],)


def test_undispatchable_probe_is_not_vacuous(study_app):
    """自检本身要有效：注入一个坏工具必须被探出来（防探针失效）。"""
    registry = study_app.skill_registry
    key = "probe_skill.probe_tool"
    registry._tool_instances[key] = object()          # 无同名方法 → 应被判为不可派发
    registry._tool_specs[key] = {"name": "probe_tool", "methods": [
        {"name": "some_other_method"}]}
    try:
        broken = registry.undispatchable_tools()
        assert any(b["key"] == key for b in broken), \
            "自检探针失效：坏工具没被探出来"
    finally:
        registry._tool_instances.pop(key, None)
        registry._tool_specs.pop(key, None)


# ── 护栏 2：当年坏掉的 9 个工具必须逐一实调通过 ──

def test_previously_broken_tools_are_callable(study_app):
    """这 9 个工具在 2026-11-08 之前全部调用必挂。"""
    registry = study_app.skill_registry
    # (skill, tool, 参数) —— 全部走基座的 call_tool（即模型调用的同一条路径）
    cases = [
        ("study_tracking", "record_study_session",
         {"subject": "数学", "minutes": 15}),
        ("study_tracking", "record_study_note",
         {"text": "护栏回归：学习笔记"}),
        ("study_tracking", "list_study_sessions", {}),
        ("study_tracking", "study_minutes_by_day", {"days": 3}),
        ("study_tracking", "study_daily_report", {}),
        ("question_bank", "get_question", {"question_id": 1}),
        ("question_bank", "update_question",
         {"question_id": 1, "difficulty": 5}),
    ]
    for skill, tool, params in cases:
        try:
            registry.call_tool(skill, tool, params)
        except Exception as exc:                       # noqa: BLE001
            pytest.fail("工具 %s.%s 调用失败: %s: %s"
                        % (skill, tool, type(exc).__name__, exc))


def test_previously_broken_async_tools_are_callable(study_app):
    """obsidian_notes 的 2 个工具是协程，走 call_tool_async。"""
    registry = study_app.skill_registry
    import asyncio

    async def _run():
        for tool, params in (("search_obsidian_notes", {"query": "护栏"}),
                             ("list_obsidian_notes", {})):
            # MCP 未接入时工具会返回 error 字典而不是抛异常 —— 那是配置态，
            # 不是派发缺陷；这里只断言「能派发到方法」且不抛 ValueError。
            try:
                await registry.call_tool_async("obsidian_notes", tool, params)
            except ValueError as exc:
                pytest.fail("工具 obsidian_notes.%s 派发失败: %s" % (tool, exc))

    asyncio.run(_run())


# ── 护栏 3：基座解析规则本身 ──

def test_resolve_method_prefers_tool_name(study_app):
    """工具名 == 方法名时，按工具名解析（绝大多数技能，行为不变）。"""
    registry = study_app.skill_registry
    inst = registry._tool_instances["study_tasks.create_reminder"]
    method = registry._resolve_method("study_tasks", "create_reminder", inst)
    assert method.__name__ == "create_reminder"


def test_resolve_method_falls_back_to_declared_method(study_app):
    """工具名 ≠ 方法名时，回退到 skill.yaml 声明的那个方法。"""
    registry = study_app.skill_registry
    inst = registry._tool_instances["study_tracking.record_study_session"]
    method = registry._resolve_method("study_tracking", "record_study_session", inst)
    assert method.__name__ == "record_session"


def test_resolve_method_raises_for_genuinely_missing(study_app):
    """既没有同名方法、又没有唯一声明的方法 → 显式报错（不静默）。"""
    registry = study_app.skill_registry
    inst = registry._tool_instances["study_tracking.record_study_session"]
    with pytest.raises(ValueError, match="工具方法不存在"):
        registry._resolve_method("study_tracking", "totally_absent_method", inst)


def test_boot_exposes_undispatchable_in_config(study_app):
    """boot 时把自检结果落到 app.config，供 /api/skills 暴露。"""
    from apps.dsn_study import boot
    app = boot.app
    assert app is not None, "boot.app 未赋值"
    assert "UNDISPATCHABLE_TOOLS" in app.config
    assert app.config["UNDISPATCHABLE_TOOLS"] == []
