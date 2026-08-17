# harness/tools.py
# 通用工具抽象 — Tool 定义、调用结果、注册表、LLM function-calling schema。
#
# 场景无关：不包含任何具体工具实现，只提供"工具是什么、如何注册、如何生成 schema"。

from __future__ import annotations

import asyncio
import inspect
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# ── 线路名（wire name）编解码 ──
#
# harness 内部工具名带命名空间点号（如 "file.read"），可读性好；但部分 OpenAI 兼容
# 服务端会强校验 function 名必须匹配 ^[a-zA-Z0-9_-]+$，点号会直接被拒（400
# invalid_request_error）。因此在"发给模型"的边界上把点号编码为双下划线，在
# "解析模型调用"的边界上再还原，内部命名与工具注册表完全不变。
_WIRE_SAFE_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
_WIRE_SEP = "__"


def to_wire_name(name: str) -> str:
    """把内部工具名转成 provider 可接受的 function 名（file.read → file__read）。"""
    if not name:
        return name
    wire = name.replace(".", _WIRE_SEP)
    # 兜底：其余非法字符统一替换为下划线，保证一定能过 provider 校验
    if not _WIRE_SAFE_RE.match(wire):
        wire = re.sub(r"[^a-zA-Z0-9_-]", "_", wire)
    return wire


def from_wire_name(wire: str, known: Optional[Any] = None) -> str:
    """把 provider 返回的 function 名还原为内部工具名（file__read → file.read）。

    known 可传入可迭代的合法工具名集合；命中原名或还原名时优先返回该名字，
    避免误伤本身就带双下划线的工具名。
    """
    if not wire:
        return wire
    names = set(known) if known is not None else None
    if names is not None and wire in names:
        return wire
    restored = wire.replace(_WIRE_SEP, ".")
    if names is not None and restored not in names:
        return wire
    return restored


@dataclass
class ToolResult:
    """工具执行结果。

    success  是否成功（False 时 error 说明原因）
    status   执行状态: ok | error | retry | deferred（模型可据此决定下一步）
    hint     给 Agent 的下一步提示（继续尝试 / 换工具 / 询问用户等）
    data     附加结构化字段（随 to_dict 一起回喂模型）
    """
    success: bool = True
    output: Any = None
    error: Optional[str] = None
    status: str = "ok"
    hint: Optional[str] = None
    data: dict = field(default_factory=dict)

    @classmethod
    def ok(cls, output: Any = None, *, hint: Optional[str] = None,
           status: str = "ok", **data) -> "ToolResult":
        return cls(success=True, output=output, hint=hint,
                   status=status, data=data)

    @classmethod
    def fail(cls, error: str, *, hint: Optional[str] = None,
             status: str = "error", **data) -> "ToolResult":
        return cls(success=False, error=error, hint=hint,
                   status=status, data=data)

    @classmethod
    def retry(cls, error: str, *, hint: Optional[str] = None, **data) -> "ToolResult":
        """失败但值得重试（如临时性错误）。"""
        return cls(success=False, error=error, hint=hint,
                   status="retry", data=data)

    @classmethod
    def deferred(cls, output: Any = None, *, hint: Optional[str] = None,
                 **data) -> "ToolResult":
        """已接受但结果稍后到达（异步任务）。"""
        return cls(success=True, output=output, hint=hint,
                   status="deferred", data=data)

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "status": self.status,
            "output": self.output,
            "error": self.error,
            "hint": self.hint,
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
                # 同步 handler 移到线程池执行，避免阻塞事件循环：
                # 否则一个耗时的同步工具（grep 大目录 / proc.run / web.fetch）
                # 会卡住整个 asyncio 循环——前端无响应、turn_timeout 无法取消、
                # 服务端连 SIGINT 都可能失效。
                result = await asyncio.to_thread(self.handler, **params)
        except Exception as e:  # noqa: BLE001
            return ToolResult.fail(str(e))
        return result if isinstance(result, ToolResult) else ToolResult.ok(result)

    def to_openai_schema(self) -> dict:
        """转为 OpenAI function-calling 的 function 描述。

        name 使用 wire 名（点号编码为双下划线），兼容强校验
        ^[a-zA-Z0-9_-]+$ 的 provider；模型回调时由 from_wire_name 还原。
        """
        return {
            "name": to_wire_name(self.name),
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
