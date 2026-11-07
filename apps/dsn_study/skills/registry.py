# apps/dsn_study/skills/registry.py
# 技能注册表 —— 复用 harness 的**唯一实现**。
#
# 去重说明（2026-11）：此前 dsn 与 dsn_study 各有一份 SkillRegistry 副本，
# 方法集还不一样（study 侧多 call_tool_async / is_async_tool /
# inject_dependencies / get_tool_instances），改一边不影响另一边 ——
# "同一个技能在两个应用里行为不一致"很难排查。
# 现统一到 harness/skills/registry.py，本文件只做转发。

from harness.skills.registry import SkillRegistry  # noqa: F401

__all__ = ["SkillRegistry"]
