# apps/dsn_study/app.py
# DsnStudyAgent — 学习特化 Agent 门面（向后兼容壳）。
#
# 实际装配在 boot.py：本文件委托 boot.get_engine()，保证无论从
# REPL / WSGI / SDK 哪条路径进入，得到的都是同一套完整装配
# （技能工具 + 学习上下文注入 + 学习领域组件）。

from __future__ import annotations

from typing import Optional

from apps.dsn_study.boot import get_engine


class DsnStudyAgent:
    """学习特化 Agent 门面类。"""

    def __init__(self, client=None, *, system_prompt: str = "", max_steps: int = 0):
        # client/system_prompt/max_steps 参数保留兼容旧调用方；
        # 装配以 boot 为准（boot 统一读 Config 与技能提示词）。
        self._engine = get_engine()

    @property
    def engine(self):
        return self._engine

    @property
    def skill_registry(self):
        return self._engine.skill_registry

    def chat(self, message: str, user_id: int = 1) -> str:
        """执行一次带学习工具循环与上下文注入的对话。"""
        return self._engine.chat(message, user_id=user_id)

    def list_tools(self) -> list[str]:
        return self._engine.skill_registry.list_active_tools()

    def __repr__(self):
        return f"<DsnStudyAgent {self._engine!r}>"
