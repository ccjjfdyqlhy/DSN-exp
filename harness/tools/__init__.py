# harness/tools/__init__.py
# 通用工具抽象 — Tool / ToolRegistry / 自动构建。

from .base import Tool, ToolResult, ToolRegistry, from_wire_name, to_wire_name
from .context import ToolContext, current_context, pop_context, push_context, resolve_path
from .function_tool import tool_from_function, tools_from_module
from .registry import AnnotatedTool, ManagedToolRegistry
from .shell import ShellSessions, session_shell_tool
from .toolbox import ToolboxManager, RegistryIndexSource, ToolIndexSource
from .standard import ToolDeps, install_standard_tools
# MCP 桥接模块自身延迟导入官方 SDK（缺包不影响 harness 其余功能），这里只导类
from .mcp import MCPManager, MCPServerConfig

__all__ = [
    "Tool", "ToolResult", "ToolRegistry",
    "to_wire_name", "from_wire_name",
    "tool_from_function", "tools_from_module",
    "ToolboxManager", "RegistryIndexSource", "ToolIndexSource",
    "ToolDeps", "install_standard_tools",
    "MCPManager", "MCPServerConfig",
    "ToolContext", "current_context", "push_context", "pop_context",
    "resolve_path",
    "AnnotatedTool", "ManagedToolRegistry",
    "ShellSessions", "session_shell_tool",
]
