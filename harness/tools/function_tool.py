# harness/tools/function_tool.py
# 从 Python 函数自动构建 Tool — 从签名/类型注解/docstring 生成 JSON schema。
#
# 让 skill 作者只写普通函数，无需手写 parameters schema。

from __future__ import annotations

import inspect
from typing import Any, Callable, Optional, get_type_hints

from . import Tool


def _to_json_type(tp: Any) -> dict:
    """把 Python 类型映射为 JSON-Schema 类型。"""
    origin = getattr(tp, "__origin__", None)
    if origin is list:
        return {"type": "array"}
    if origin is dict:
        return {"type": "object"}
    if tp is int or (isinstance(tp, type) and issubclass(tp, int)):
        return {"type": "integer"}
    if tp is float or (isinstance(tp, type) and issubclass(tp, float)):
        return {"type": "number"}
    if tp is bool or (isinstance(tp, type) and issubclass(tp, bool)):
        return {"type": "boolean"}
    if tp is str or (isinstance(tp, type) and issubclass(tp, str)):
        return {"type": "string"}
    if tp in (None, type(None)):
        return {"type": "string"}
    return {"type": "string"}


def tool_from_function(
    fn: Callable[..., Any],
    name: Optional[str] = None,
    description: Optional[str] = None,
    *,
    namespace: str = "",
) -> Tool:
    """从函数构建 Tool。docstring 作为 description，签名/注解生成 parameters。"""
    tool_name = name or fn.__name__
    if namespace and "." not in tool_name:
        tool_name = f"{namespace}.{tool_name}"

    desc = (description or inspect.getdoc(fn) or "").strip()
    sig = inspect.signature(fn)
    try:
        hints = get_type_hints(fn)
    except Exception:
        hints = {}

    properties: dict[str, dict] = {}
    required: list[str] = []
    for pname, p in sig.parameters.items():
        if pname in ("self", "cls"):
            continue
        if p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        js = _to_json_type(hints.get(pname, str))
        if p.default is inspect.Parameter.empty:
            required.append(pname)
        else:
            js["default"] = p.default
        properties[pname] = js

    parameters: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        parameters["required"] = required

    return Tool(
        name=tool_name,
        description=desc,
        handler=fn,
        parameters=parameters,
        async_mode=inspect.iscoroutinefunction(fn),
    )


def tools_from_module(module: Any, *, namespace: str = "",
                      include: Optional[list[str]] = None) -> list[Tool]:
    """从模块中所有顶层函数批量构建 Tool。"""
    tools = []
    for name, obj in inspect.getmembers(module, inspect.isfunction):
        if name.startswith("_"):
            continue
        if include and name not in include:
            continue
        try:
            tools.append(tool_from_function(obj, namespace=namespace))
        except (ValueError, TypeError):
            continue
    return tools
