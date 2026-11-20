# aicf/__init__.py
"""AICF —— Agent Infrastructure Cybernetics Framework 的顶层命名空间。
#
# 这个包**只做命名空间**，不装业务逻辑：
#
#   aicf.harness   Agent 核心层（turn loop / 工具协议 / 上下文装配 / 记忆 / 会话）
#   aicf.infra     基础设施层（模型路由 / 资源池 / 存储 / 网关 / 认证 / 策略）
#
# 依赖方向永远是 aicf.harness → aicf.infra，单向。
#
# ## 为什么是 aicf.harness 而不是 harness
#
# 1. **顶层名字不能乱占**：`harness` 与 `infra` 在 PyPI 上都已被他人占用，
#    谁先装谁抢。框架把自己的内部目录名泄漏到全局命名空间，等于
#    「装一个包，坏三个环境」。
# 2. **一个东西一个名字**：分发名 `aicf-core`、CLI `aicf`、import `aicf.*`
#    三者对齐，用户不用在三个名字之间猜。
# 3. **给未来留位置**：以后要加插件层、适配层，有 aicf.<层> 的位置。
#
# ## 用法
#
# ```python
# from aicf.harness import create_agent, tool   # 显式路径（推荐）
# from aicf import create_agent, tool           # 等价简写
# ```
#
# 简写走懒加载（PEP 562）：`import aicf` 本身不会拉起 openai 等重依赖，
# 只有真的取到某个符号时才会去 import aicf.harness。
"""

from __future__ import annotations

from typing import Any

#: 可以从 aicf 顶层直接取用的常用符号（转发到 aicf.harness）。
_FORWARDED = frozenset(
    {
        "Agent",
        "AgentRuntime",
        "Conversation",
        "ConversationManager",
        "PromptEngine",
        "Team",
        "Tool",
        "ToolRegistry",
        "ToolResult",
        "create_agent",
        "tool",
    }
)


def __getattr__(name: str) -> Any:
    """把顶层的常用符号转发到 aicf.harness（懒加载）。"""
    if name in _FORWARDED:
        from aicf import harness as _harness

        return getattr(_harness, name)
    raise AttributeError(f"module 'aicf' has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | _FORWARDED)


def __getattr__(name: str) -> Any:
    """把顶层的常用符号转发到 aicf.harness（懒加载）。

    ``__version__`` 也走这条路：版本号的**唯一真相源**是
    ``aicf.harness.__version__``（由 tests/test_version.py 与 pyproject 互相钉死）。
    从已安装的发行版元数据里读版本，在源码树里会读到过期的 egg-info，
    那种「装的是 A、跑的是 B」的错位正是这个项目栽过的地方。
    """
    if name in _FORWARDED or name == "__version__":
        from aicf import harness as _harness

        return getattr(_harness, name)
    raise AttributeError(f"module 'aicf' has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | _FORWARDED | {"__version__"})


__all__ = ["__version__", *sorted(_FORWARDED)]
