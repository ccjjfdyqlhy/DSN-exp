# profiles.py — DenseChat WebUI 的任务模式（TaskProfile）注册表。
#
# 把 densechat 从"只写代码"的单一智能体，转型为通用任务平台：
# 每个会话在初始化时通过欢迎页滑条选择一个任务模式（profile），
# 不同 profile 对应不同的智能体：不同的系统提示词、工具集、技能集。
#
# 内置模式：
#   - dekacode : 代码助手（现状完整工具 + 代码技能）
#   - random   : 通用任务 + 多用户 AI 群聊（单 AI + N 用户，公共房间）
#   - anaii    : 占位（即将上线，无可用能力）
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

DEFAULT_PROFILE = "dekacode"

# random / anaii 的能力声明（UI 展示用）
_RANDOM_CAPABILITIES = {
    "multi_user": True,   # 多用户
    "group_chat": True,   # 一个 AI + 多用户群聊
}


@dataclass
class TaskProfile:
    """一个任务模式 = 一个智能体画像。"""

    id: str
    label: str
    description: str
    icon: str = "🤖"
    available: bool = True
    # 标准工具集过滤（None=全部；["file","text",...] 按命名空间前缀过滤）
    standard_include: Optional[list[str]] = None
    # 是否注册代码特调扩展工具（file.grep/glob、code.*、git.*、code.review、project.deps）
    extra_tools: bool = False
    # 是否加载 skills 目录技能
    load_skills: bool = False
    # 是否注册 task.split（SubAgentRunner 子任务委派）
    subagent_tool: bool = False
    # 预留能力声明
    capabilities: dict[str, Any] = field(default_factory=dict)
    # 系统提示词；空字符串表示由引擎动态生成（如 densechat 读 prompts/*.md）
    system_prompt: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "icon": self.icon,
            "available": self.available,
            "capabilities": dict(self.capabilities),
        }


# 通用任务模式的系统提示词（random / anaii 共用基础提示，anaii 由占位逻辑接管）
_GENERIC_SYSTEM_PROMPT = (
    "你是一名通用智能助手，运行在 DSN-exp harness 之上，帮助用户完成各类日常任务。\n"
    "你拥有以下通用能力：\n"
    "  - file.*：读取/写入/编辑/浏览工作区文件\n"
    "  - text.*：文本分块、抽取 JSON、diff 对比\n"
    "  - proc.run：执行 shell 命令（带超时与输出截断）\n"
    "  - web.fetch：抓取网页文本\n"
    "  - project.*：项目概览、文件快照、轻量待办\n"
    "  - batch.run：批量执行（map 风格）\n"
    "请根据任务类型选择合适的工具，先规划再执行，必要时拆解步骤。"
    "你没有为代码开发特调的符号图/调用链/Git 工具，但依然可以处理代码相关的文本任务。"
)


def _build_profiles() -> dict[str, TaskProfile]:
    profiles: dict[str, TaskProfile] = {}

    profiles[DEFAULT_PROFILE] = TaskProfile(
        id=DEFAULT_PROFILE,
        label="Dekacode",
        description="面向软件开发的代码助手：符号图、调用链、Git、代码审查等专属工具与技能。",
        icon="💻",
        available=True,
        standard_include=None,       # 全部标准工具
        extra_tools=True,            # file.grep/glob、code.*、git.*、code.review、project.deps
        load_skills=True,            # 加载 skills 目录技能
        subagent_tool=True,          # task.split 子任务委派
        capabilities={"multi_user": False, "group_chat": False},
        system_prompt="",            # 由引擎读 prompts/*.md 动态拼接
    )

    profiles["random"] = TaskProfile(
        id="random",
        label="Random",
        description="适合任意任务的通用助手：不带代码特调工具与技能。支持多用户 AI 群聊。",
        icon="🎲",
        available=True,
        standard_include=["file", "text", "proc", "web", "project", "batch"],
        extra_tools=False,
        load_skills=False,
        subagent_tool=False,
        capabilities=dict(_RANDOM_CAPABILITIES),
        system_prompt=_GENERIC_SYSTEM_PROMPT,
    )

    profiles["anaii"] = TaskProfile(
        id="anaii",
        label="Anaii",
        description="Anaii 智能体，即将上线。",
        icon="✨",
        available=False,             # 占位：不可用
        standard_include=[],
        extra_tools=False,
        load_skills=False,
        subagent_tool=False,
        capabilities=dict(_RANDOM_CAPABILITIES),
        system_prompt="你正在与 Anaii 对话。Anaii 智能体尚未开放，请等待后续版本。",
    )

    return profiles


PROFILES: dict[str, TaskProfile] = _build_profiles()


def get_profile(profile_id: Optional[str]) -> TaskProfile:
    """按 id 取 profile；未知/空回退到默认（densechat）。"""
    return PROFILES.get(profile_id or "") or PROFILES[DEFAULT_PROFILE]


def list_profiles() -> list[dict[str, Any]]:
    return [p.to_dict() for p in PROFILES.values()]


def profile_ids() -> list[str]:
    return list(PROFILES.keys())


__all__ = [
    "TaskProfile", "PROFILES", "DEFAULT_PROFILE",
    "get_profile", "list_profiles", "profile_ids",
]
