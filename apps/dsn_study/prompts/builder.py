# apps/dsn_study/prompts/builder.py
"""StudyPromptBuilder —— dsn_study 的 system prompt 组装器。

基于 `harness/prompts/engine.py`（片段化 + 占位符渲染器），补上三件事：

1. **逐轮重建**：旧实现只在 boot 时拼一次死字符串，禁用技能后其指令文本
   仍留在 prompt 里；现在每轮重建 → 禁用即刻生效。
2. **按 uid 的插槽**：`{personality}` 随用户 uid 变（PEV3 人格状态按用户存），
   所以渲染器需要一个「当前轮」的上下文。
3. **单一真源**：身份/人格/上下文/技能四段各自成片段，顺序由 frontmatter 的
   `order` 决定，不再靠字符串拼接的巧合顺序。
"""

from __future__ import annotations

import contextvars
import logging
import os
from typing import Callable, Optional

from harness.prompts.engine import PromptEngine

logger = logging.getLogger("StudyPrompts")

#: 当前轮的 uid 与学习上下文。
#: 用 **contextvars** 而不是实例属性：Flask 多线程 + 管线常驻事件循环线程
#: 会并发跑多轮对话，实例属性会被后一轮覆盖（人格按 uid 取值就串了）。
#: contextvars 天然按线程/任务隔离。
_TURN = contextvars.ContextVar("dsn_study_turn", default=None)

#: 片段目录（与本文件同级）
DEFAULT_FRAGMENTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "fragments")

#: 人格提供器：(uid) -> str
PersonalityProvider = Callable[[int], str]
#: 学习上下文提供器：(uid) -> str
ContextProvider = Callable[[int], str]


class StudyPromptBuilder:
    """组装 dsn_study 的 system prompt。"""

    def __init__(self, fragments_dir: Optional[str] = None,
                 skill_registry=None):
        self.fragments_dir = fragments_dir or DEFAULT_FRAGMENTS_DIR
        self._skill_registry = skill_registry
        self._engine = PromptEngine(self.fragments_dir)
        self._engine.register_renderer("skills", self._render_skills)
        self._engine.register_renderer("personality", self._render_personality)
        self._engine.register_renderer("user_context", self._render_context)
        try:
            self._engine.load_all()
        except Exception:
            logger.warning("提示词片段加载失败（将退回内置默认身份）",
                           exc_info=True)
        self._personality_provider: Optional[PersonalityProvider] = None
        self._context_provider: Optional[ContextProvider] = None

    # ── 提供器 ──

    def set_personality_provider(self, fn: Optional[PersonalityProvider]) -> None:
        """注册人格提供器（阶段 2 接 PEV3）。"""
        self._personality_provider = fn

    def set_context_provider(self, fn: Optional[ContextProvider]) -> None:
        """注册学习上下文提供器（阶段 7 接弹性上下文）。"""
        self._context_provider = fn

    # ── 渲染器 ──

    def _render_skills(self) -> str:
        """技能指令。

        每次都从注册表现取 —— `unregister_skill` 会把该技能的提示词一并摘掉，
        所以「禁用技能后指令文本残留」这个老问题在这里天然消失。
        """
        if self._skill_registry is None:
            return ""
        try:
            return self._skill_registry.get_all_skill_prompts() or ""
        except Exception:
            logger.warning("技能提示词聚合失败（已跳过）", exc_info=True)
            return ""

    @staticmethod
    def _turn() -> tuple:
        turn = _TURN.get()
        return (turn or (1, ""))

    def _render_personality(self) -> str:
        if self._personality_provider is None:
            return ""
        uid, _ctx = self._turn()
        try:
            return self._personality_provider(uid) or ""
        except Exception:
            logger.warning("人格提示词生成失败（已跳过）", exc_info=True)
            return ""

    def _render_context(self) -> str:
        uid, ctx = self._turn()
        if self._context_provider is None:
            return ctx or ""
        try:
            return self._context_provider(uid) or ""
        except Exception:
            logger.warning("学习上下文生成失败（已跳过）", exc_info=True)
            return ctx or ""

    # ── 对外 ──

    def begin_turn(self, uid: int = 1, context: str = "") -> None:
        """设置当前轮上下文（uid + 学习上下文文本）。

        写入 contextvars —— 并发对话互不干扰。
        返回值是 token，可传给 ``reset_turn`` 还原（一般不需要）。
        """
        _TURN.set((int(uid or 1), context or ""))

    def build(self, only_tags: Optional[list] = None,
              exclude_titles: Optional[set] = None,
              uid: Optional[int] = None,
              context: Optional[str] = None) -> str:
        """组装当前 system prompt。

        ``only_tags`` —— 只要某些标签的片段（例：只要 core+personality，
        给「扫题批次总结」那条轻量管线用，不必带 17KB 技能指令）。
        ``uid`` / ``context`` —— 直接指定本轮上下文（不写 contextvars）。
        """
        if uid is not None or context is not None:
            _TURN.set((int(uid or 1), context or ""))
        try:
            prompt = self._engine.build_system_prompt(
                only_tags=only_tags, exclude_titles=exclude_titles)
        except Exception:
            logger.warning("system prompt 组装失败（退回内置默认）",
                           exc_info=True)
            return FALLBACK_SYSTEM_PROMPT
        return prompt or FALLBACK_SYSTEM_PROMPT

    def summary(self) -> str:
        return self._engine.summary()

    def reload(self) -> None:
        """重新加载片段文件（片段改动后热更新）。"""
        try:
            self._engine.reload()
        except Exception:
            logger.warning("提示词片段重载失败", exc_info=True)

    def __repr__(self) -> str:
        return "<StudyPromptBuilder dir=%s>" % self.fragments_dir


#: 片段全部不可用时的兜底（与旧 DEFAULT_SYSTEM_PROMPT 一致）
FALLBACK_SYSTEM_PROMPT = (
    "你是一名专业的AI学习助手，擅长解题、组卷、模拟考试、错题归纳、学习计划管理"
    "与知识图谱梳理。请用清晰明了的中文回答。"
)
