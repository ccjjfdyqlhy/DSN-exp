# prompt/engine.py
# PromptEngine — 组装最终 system prompt

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
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
      2. 性格描述       — PersonalitySystemV3 或 V2 动态生成
      3. capabilities/ — 能力定义
      4. skills/       — 已加载技能的提示词 (从 SkillRegistry 注入)
      5. extensions/   — 用户扩展
      6. 用户上下文     — 用户名 + 当前时间
    """

    def __init__(
        self,
        library: PromptLibrary | None = None,
        personality_v2=None,  # PersonalitySystemV2
        personality_v3=None,  # PersonalitySystemV3
        skill_registry=None,  # SkillRegistry
    ):
        self.library = library or PromptLibrary()
        self._personality_v2 = personality_v2
        self._personality_v3 = personality_v3
        self._skill_registry = skill_registry

    @property
    def personality_v2(self):
        return self._personality_v2

    @personality_v2.setter
    def personality_v2(self, value):
        self._personality_v2 = value

    @property
    def personality_v3(self):
        return self._personality_v3

    @personality_v3.setter
    def personality_v3(self, value):
        self._personality_v3 = value

    def set_skill_registry(self, registry) -> None:
        self._skill_registry = registry

    def build_system_prompt(self, user_info: dict | None = None,
                             is_first_interaction: bool = False) -> str:
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

        # 2. 性格描述 — V3 优先，回退到 V2
        if self._personality_v3 and self._personality_v3.enabled:
            uid = user_info.get("uid", 0)
            v3_prompt = self._personality_v3.generate_personality_prompt(uid)
            if v3_prompt:
                sections.append(v3_prompt)
        elif self._personality_v2:
            uid = user_info.get("uid", 0)
            sections.append(self._personality_v2.build_prompt(uid))

        # 3/4. 原生 tool call 模式检查 — 决定是否注入 XML 语法说明和技能提示词
        _inject_skill_prompts = True
        try:
            from config import Config
            _mode = getattr(Config, "TOOL_CALL_MODE", "native")
            _type = getattr(Config, "MAIN_MODEL_TYPE", "deepseek")
            if _mode in ("native",) and _type == "deepseek":
                _inject_skill_prompts = False
        except Exception:
            pass

        # 3. capabilities/ — 原生 mode 下跳过（工具/标签语法已在 API tools 中）
        if _inject_skill_prompts:
            caps = self.library.get_content_by_category("capabilities")
            if caps:
                sections.append(caps)

        # 4. 技能提示词 — 原生 tool call 模式下跳过（工具定义在 API schema 中）
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
        user_context = f"当前用户：{nickname}\n当前时间：{now}"

        # 6.1 工作区路径
        try:
            from utils.workspace import get_workspace_manager
            wm = get_workspace_manager()
            uid = user_info.get("uid", 0)
            if uid:
                user_root = str(wm.user_dir(uid=uid))
                uploads_dir = str(wm.user_uploads_dir(uid=uid))
                documents_dir = str(wm.user_documents_dir(uid=uid))
                user_context += f"\n你的工作区目录：{user_root}"
                user_context += f"\n扫描文件存放目录：{uploads_dir}"
                user_context += f"\n文档输出目录：{documents_dir}"
        except Exception:
            pass

        sections.append(user_context)

        # 7. 首次对话初始化引导 (仅在第一次对话时注入)
        if is_first_interaction:
            init_path = Path(__file__).parent / "prompts" / "initialize.md"
            if init_path.exists():
                init_content = init_path.read_text(encoding="utf-8")
                # 去掉 YAML frontmatter (---...---)
                if init_content.startswith("---"):
                    parts = init_content.split("---", 2)
                    if len(parts) >= 3:
                        init_content = parts[2].strip()
                if init_content:
                    sections.append(init_content)

        # 8. constant:true 提示词 (每轮注入，作为持久指令)
        constant_prompts = self.library.get_constant_prompts()
        if constant_prompts:
            sections.append(constant_prompts)

        return "\n\n".join(s for s in sections if s.strip())

    def get_initial_prompt(self, user_info: dict | None = None) -> str:
        """返回首次对话时的系统提示词（含初始化引导）。"""
        return self.build_system_prompt(user_info, is_first_interaction=True)


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

    # V3 在 app.py 中独立初始化后注入，这里不在此初始化
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

    logger.warning("PromptEngine 未初始化，使用内置回退提示词")

    fallback = (
        "你叫 EXA，运行在用户的本地电脑上。"
        "你的性格：直接、不绕弯子、实事求是、偶尔调侃。"
        "回复尽量简短精炼。"
    )
    nickname = user_info.get("nickname", "用户") if user_info else "用户"
    return f"{fallback}\n\n当前用户：{nickname}"
