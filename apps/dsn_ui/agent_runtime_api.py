# apps/dsn_ui/agent_runtime_api.py
"""Agent 运行时面板的后端接口。

只读聚合 + 技能视图。所有「写」操作（上下文策略、情绪调节、思考缓存配置）
都复用既有端点，本模块刻意不再提供第二套 setter，避免两处状态互相打架。

挂载（server.py 由 Lead 添加唯一一行；engine 是 create_app() 的局部变量，
因此必须显式传入）：

    from apps.dsn_ui.agent_runtime_api import register_agent_runtime_routes
    ...
    register_agent_runtime_routes(app, engine)

engine 是可选参数：不传也能注册成功，此时所有接口降级为 available=false
（前端显示空态而不是崩溃）。单测可直接 register_agent_runtime_routes(app)。

接口
----
GET /api/agent-runtime/overview
    {
      "available": bool,              # engine 是否可达
      "context": {
        "available": bool,
        "stats": {...} | null,        # engine.agent.get_context_stats()
        "strategy": str | null,       # 当前上下文溢出策略
        "settings": {                 # Agent 运行时设置
           "max_steps": int | null,
           "tool_max_output_chars": int | null,
           "context_overflow_strategy": str | null,
           "context_trigger_ratio": float | null,
           "summary_model": str | null
        } | null
      },
      "emotion": {
        "available": bool,
        "state": {...} | null,        # engine.agent.get_emotion_state()
        "summary": str | null,
        "mood": {...} | null          # get_mood_profile(): {label, emoji, behavior}
      },
      "tools": {
        "available": bool,
        "total": int,
        "toolbox_enabled": bool,
        "items": [{"id": str, "description": str}]
      },
      "skills": {...},               # 见 GET /api/agent-runtime/skills
      "errors": {section: message}   # 取数失败的分区（正常为空对象）
    }

GET /api/agent-runtime/skills
    {
      "enabled": bool,               # dsn_ui 运行时是否启用应用层技能（当前恒为 false）
      "available": bool,
      "source": "harness",
      "registry_reachable": bool,
      "message": str,
      "packages": [{"name": str, "group": str}]
    }
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# apps/dsn_ui/agent_runtime_api.py -> parents[2] == 仓库根目录
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILLS_ROOT = _REPO_ROOT / "apps" / "dsn" / "skills"

# register 时未显式传入 engine 时，可先用 bind_engine() 绑定。
_bound_engine: Optional[Any] = None

_EMOTION_DIMS = ("joly", "sorw", "angr", "fear", "meta")

_SKILLS_MESSAGE = (
    "dsn_ui 运行时使用 harness 工具集（两阶段 toolbox 激活），"
    "未启用应用层技能注入；下列技能包存在于 apps/dsn，但未接入本页面的 Agent 运行时。"
)


def bind_engine(engine: Any) -> None:
    """绑定 DSNUIEngine 实例。

    供「不方便改 register 调用点、但能先拿到 engine」的场景使用。
    """
    global _bound_engine
    _bound_engine = engine


def _resolve_engine() -> Optional[Any]:
    return _bound_engine


def _agent_of(engine: Optional[Any]) -> Optional[Any]:
    if engine is None:
        return None
    return getattr(engine, "agent", None)


def _safe(fn: Callable[[], Any], default: Any, errors: dict, name: str) -> Any:
    """执行取数函数；失败只记录并降级，绝不让整个接口 500。"""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - 面板取数必须容错
        logger.warning("Agent 运行时面板取数失败 [%s]: %s", name, exc)
        errors[name] = str(exc)
        return default


def _skill_packages() -> list[dict]:
    """只读枚举 apps/dsn 下已存在的技能包目录（不导入、不执行）。"""
    if not _SKILLS_ROOT.is_dir():
        return []

    packages: list[dict] = []
    for group in ("builtin", "custom", "distilled"):
        group_dir = _SKILLS_ROOT / group
        if not group_dir.is_dir():
            continue
        for child in sorted(group_dir.iterdir()):
            if not child.is_dir() or child.name.startswith(("_", ".")):
                continue
            packages.append({"name": child.name, "group": group})
    return packages


def _build_skills() -> dict:
    packages = _skill_packages()
    return {
        "enabled": False,
        "available": bool(packages),
        "source": "harness",
        "registry_reachable": (_SKILLS_ROOT / "registry.py").is_file(),
        "message": _SKILLS_MESSAGE,
        "packages": packages,
    }


def _build_context(agent: Optional[Any], errors: dict) -> dict:
    if agent is None:
        return {"available": False, "stats": None, "strategy": None, "settings": None}

    stats = _safe(agent.get_context_stats, {}, errors, "context.stats") or {}
    strategy = _safe(agent.get_context_strategy, None, errors, "context.strategy")

    def _settings() -> dict:
        return {
            "max_steps": agent.get_max_steps(),
            "tool_max_output_chars": agent.get_tool_max_output_chars(),
            "context_overflow_strategy": agent.get_context_strategy(),
            "context_trigger_ratio": agent.get_context_trigger_ratio(),
            "summary_model": agent.get_summary_model() or "",
        }

    settings = _safe(_settings, None, errors, "context.settings")

    return {
        "available": True,
        "stats": stats,
        "strategy": strategy,
        "settings": settings,
    }


def _build_emotion(engine: Optional[Any], agent: Optional[Any], errors: dict) -> dict:
    if agent is None:
        return {"available": False, "state": None, "summary": None, "mood": None}

    state = _safe(agent.get_emotion_state, None, errors, "emotion.state")
    summary = _safe(agent.get_emotion_summary, None, errors, "emotion.summary")

    def _mood() -> Any:
        emotion_engine = getattr(engine, "agent", None).emotion_engine
        getter = getattr(emotion_engine, "get_mood_profile", None)
        return getter() if callable(getter) else None

    mood = _safe(_mood, None, errors, "emotion.mood")

    return {"available": True, "state": state, "summary": summary, "mood": mood}


def _build_tools(agent: Optional[Any], errors: dict) -> dict:
    if agent is None:
        return {"available": False, "total": 0, "toolbox_enabled": False, "items": []}

    def _collect() -> dict:
        # 每次属性访问都必须在 guard 内部：子系统缺失时 __getattr__ 可能返回
        # 一个会抛错的桩，若在外面取属性，异常会逃过 _safe 直接打爆整个接口。
        coordinator = agent.tool_coordinator
        items = coordinator.tool_index() or []
        return {
            "available": True,
            "total": len(coordinator.tool_names()),
            "toolbox_enabled": bool(coordinator.toolbox.enabled),
            "items": items,
        }

    collected = _safe(_collect, None, errors, "tools")
    if collected is None:
        return {"available": False, "total": 0, "toolbox_enabled": False, "items": []}
    return collected


def _build_overview() -> dict:
    errors: dict = {}
    engine = _resolve_engine()
    agent = _agent_of(engine)

    return {
        "available": engine is not None and agent is not None,
        "context": _build_context(agent, errors),
        "emotion": _build_emotion(engine, agent, errors),
        "tools": _build_tools(agent, errors),
        "skills": _build_skills(),
        "errors": errors,
    }


def register_agent_runtime_routes(app: Any, engine: Any = None) -> None:
    """把 Agent 运行时面板接口注册到 FastAPI app 上。

    Args:
        app: FastAPI 实例（server.py 的 create_app() 内）。
        engine: DSNUIEngine 实例。可选；传入后接口返回真实数据，
            不传则降级为空态（available=false）。
    """
    if engine is not None:
        bind_engine(engine)

    @app.get("/api/agent-runtime/overview")
    async def get_agent_runtime_overview():
        """Agent 各子系统的一次性只读快照（缺失分区降级为 available=false）。"""
        return _build_overview()

    @app.get("/api/agent-runtime/skills")
    async def get_agent_runtime_skills():
        """dsn_ui 技能状态的诚实说明 + apps/dsn 技能包只读清单。"""
        return _build_skills()

    logger.info(
        "Agent 运行时接口已注册: /api/agent-runtime/overview, /api/agent-runtime/skills"
    )
