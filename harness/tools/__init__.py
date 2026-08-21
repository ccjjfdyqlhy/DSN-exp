# harness/tools/__init__.py
# 通用工具抽象 — Tool / ToolRegistry / 自动构建。

from .base import Tool, ToolResult, ToolRegistry, from_wire_name, to_wire_name
from .function_tool import tool_from_function, tools_from_module
from .toolbox import ToolboxManager, RegistryIndexSource, ToolIndexSource
from .standard import ToolDeps, install_standard_tools

__all__ = [
    "Tool", "ToolResult", "ToolRegistry",
    "to_wire_name", "from_wire_name",
    "tool_from_function", "tools_from_module",
    "ToolboxManager", "RegistryIndexSource", "ToolIndexSource",
    "ToolDeps", "install_standard_tools",
]
