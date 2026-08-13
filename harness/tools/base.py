# harness/tools.py
# 通用工具抽象 — Tool 定义、调用结果、注册表、LLM function-calling schema。
#
# 场景无关：不包含任何具体工具实现，只提供"工具是什么、如何注册、如何生成 schema"。

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class ToolResult:
    """工具执行结果。success=False 时 error 说明原因。"""
    success: bool = True
    output: Any = None
    error: Optional[str] = None
    data: dict = field(default_factory=dict)

    @classmethod
    def ok(cls, output: Any = None, **data) -> "ToolResult":
        return cls(success=True, output=output, data=data)

    @classmethod
    def fail(cls, error: str, **data) -> "ToolResult":
        return cls(success=False, error=error, data=data)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
            **self.data,
        }


@dataclass
class Tool:
    """一个可被 Agent 调用的工具。

    name        工具名（建议含命名空间，如 "file.read"）
    description 给 LLM 看的用途说明
    parameters  JSON-Schema 风格的参数定义
    handler     可调用对象：handler(**params) -> ToolResult | Any
    async_mode  标记是否需要异步执行（供执行器决策）
    """
    name: str
    description: str
    handler: Callable[..., Any]
    parameters: dict = field(default_factory=lambda: {"type": "object", "properties": {}})
    async_mode: bool = False
    version: str = "1.0"

    def run(self, **params) -> ToolResult:
        try:
            if inspect.iscoroutinefunction(self.handler):
                raise TypeError(
                    f"工具 {self.name} 的 handler 是 async 函数，请用 await run_async()")
            result = self.handler(**params)
        except Exception as e:  # noqa: BLE001
            return ToolResult.fail(str(e))
        return result if isinstance(result, ToolResult) else ToolResult.ok(result)

    async def run_async(self, **params) -> ToolResult:
        try:
            if inspect.iscoroutinefunction(self.handler):
                result = await self.handler(**params)
            else:
                result = self.handler(**params)
        except Exception as e:  # noqa: BLE001
            return ToolResult.fail(str(e))
        return result if isinstance(result, ToolResult) else ToolResult.ok(result)

    def to_openai_schema(self) -> dict:
        """转为 OpenAI function-calling 的 function 描述。"""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }

    def __repr__(self) -> str:
        return f"<Tool {self.name}>"


class ToolRegistry:
    """工具注册表。支持命名空间前缀与整体导出。"""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool, *, replace: bool = False) -> Tool:
        if tool.name in self._tools and not replace:
            raise KeyError(f"工具已注册: {tool.name}")
        self._tools[tool.name] = tool
        return tool

    def register_tool(self, name: str, description: str,
                      handler: Callable[..., Any], parameters: Optional[dict] = None,
                      *, async_mode: bool = False) -> Tool:
        return self.register(Tool(
            name=name, description=description, handler=handler,
            parameters=parameters or {"type": "object", "properties": {}},
            async_mode=async_mode,
        ))

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def require(self, name: str) -> Tool:
        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(f"工具不存在: {name}")
        return tool

    def has(self, name: str) -> bool:
        return name in self._tools

    def unregister(self, name: str) -> bool:
        return self._tools.pop(name, None) is not None

    def tools(self) -> list[Tool]:
        return list(self._tools.values())

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def build_schema(self, names: Optional[list[str]] = None) -> list[dict]:
        """生成 OpenAI function-calling schema 列表；names 为空则导出全部。"""
        selected = (
            [self._tools[n] for n in names if n in self._tools]
            if names is not None else list(self._tools.values())
        )
        return [t.to_openai_schema() for t in selected]

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __repr__(self) -> str:
        return f"<ToolRegistry tools={len(self._tools)}>"
