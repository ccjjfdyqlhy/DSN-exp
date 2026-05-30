# prompt/engine.py
# PromptEngine — 组装最终 system prompt

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from .library import PromptLibrary

logger = logging.getLogger("PromptEngine")


class PromptEngine:
    """
    组装最终 system prompt。

    输入: user_info dict + 当前状态
    输出: 完整 system prompt 字符串

    组装顺序:
      1. core/         — 身份 · 格式 · 安全
      2. 性格描述       — PersonalitySystemV2 动态生成
      3. capabilities/ — 能力定义
      4. skills/       — 已加载技能的提示词 (从 SkillRegistry 注入)
      5. extensions/   — 用户扩展
      6. 用户上下文     — 用户名 + 当前时间
    """

    def __init__(
        self,
        library: PromptLibrary | None = None,
        personality_v2=None,  # PersonalitySystemV2
        skill_registry=None,  # SkillRegistry
    ):
        self.library = library or PromptLibrary()
        self._personality_v2 = personality_v2
        self._skill_registry = skill_registry

    @property
    def personality_v2(self):
        return self._personality_v2

    @personality_v2.setter
    def personality_v2(self, value):
        self._personality_v2 = value

    def set_skill_registry(self, registry) -> None:
        self._skill_registry = registry

    def build_system_prompt(self, user_info: dict | None = None) -> str:
        """
        构建完整 system prompt。

        :param user_info: {"uid": int, "nickname": str, ...}
        """
        user_info = user_info or {}
        sections: list[str] = []

        # 1. core/
        core = self.library.get_content_by_category("core")
        if core:
            sections.append(core)

        # 2. 性格描述 — v2
        if self._personality_v2:
            uid = user_info.get("uid", 0)
            sections.append(self._personality_v2.build_prompt(uid))

        # 3. capabilities/
        caps = self.library.get_content_by_category("capabilities")
        if caps:
            sections.append(caps)

        # 4. 技能提示词
        if self._skill_registry:
            try:
                skill_prompts = self._skill_registry.get_all_skill_prompts()
                if skill_prompts.strip():
                    sections.append(skill_prompts)
            except Exception:
                logger.debug("获取技能提示词失败（SkillRegistry 可能未初始化）")

        # 5. extensions/
        ext = self.library.get_content_by_category("extensions")
        if ext:
            sections.append(ext)

        # 6. 用户上下文
        nickname = user_info.get("nickname", "用户")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sections.append(f"当前用户：{nickname}\n当前时间：{now}")

        return "\n\n".join(s for s in sections if s.strip())

    def get_initial_prompt(self, user_info: dict | None = None) -> str:
        """
        返回首次对话时的系统提示词（含初始化语）。
        这里简单复用 build_system_prompt + 初始状态提示。
        """
        base = self.build_system_prompt(user_info)
        return base + "\n\n现在你的记忆一片空白，你是刚刚苏醒的状态，对用户不了解，充满好奇。"


# ---- 模块级便捷函数 ----

_default_engine: Optional[PromptEngine] = None


def init_prompt_engine(library_dirs: list[str] | None = None,
                       personality_v2_dir: str | None = None,
                       db=None) -> PromptEngine:
    """
    初始化 Prompt 生态，返回 PromptEngine。
    app.py 在启动时调用一次。
    """
    global _default_engine

    lib = PromptLibrary()
    if library_dirs:
        lib.scan_and_load(*library_dirs)

    pers_v2 = None
    if personality_v2_dir:
        try:
            from .personality_v2 import PersonalitySystemV2
            pers_v2 = PersonalitySystemV2(db=db, presets_dir=personality_v2_dir)
            pers_v2.scan_presets(personality_v2_dir)
            if pers_v2.list_presets():
                pers_v2.load_rules_from_files()
        except Exception as e:
            logger.warning("PersonalitySystemV2 初始化失败: %s", e)

    engine = PromptEngine(library=lib, personality_v2=pers_v2)
    _default_engine = engine

    v2_info = ""
    if pers_v2:
        v2_info = f", v2 预设: {len(pers_v2.list_presets())}"
    logger.info("PromptEngine 已初始化 (库: %d 条目%s)",
                 len(lib.entries), v2_info)
    return engine


def get_system_prompt(user_info: dict | None = None) -> str:
    """
    兼容旧 prompt.py 的调用方式。
    如果 PromptEngine 未初始化，回退到旧的 DEFAULT_SYSTEM_PROMPT。
    """
    if _default_engine is not None:
        return _default_engine.build_system_prompt(user_info)

    logger.warning("PromptEngine 未初始化，使用 _prompt_legacy")
    from _prompt_legacy import get_system_prompt as _old_get_system_prompt
    return _old_get_system_prompt(user_info)
