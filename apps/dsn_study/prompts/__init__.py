# apps/dsn_study/prompts/__init__.py
# dsn_study 的 system prompt 组装（基于 harness/prompts/engine.py）。
#
# 与旧做法的差别：
#   * 旧：boot 时把 DEFAULT_SYSTEM_PROMPT 与 17 个技能的指令拼成**死字符串**，
#         之后永不重建 → 禁用一个技能，它的指令文本仍留在 prompt 里；
#   * 新：片段化（PromptFragment）+ 占位符渲染器（{personality}/{user_context}/{skills}），
#         **每轮重建** → 禁用的技能指令自动消失，逐轮变化的人格/上下文自动生效。

from .builder import StudyPromptBuilder, DEFAULT_FRAGMENTS_DIR

__all__ = ["StudyPromptBuilder", "DEFAULT_FRAGMENTS_DIR"]
