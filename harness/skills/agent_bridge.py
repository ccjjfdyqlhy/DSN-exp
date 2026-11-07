# harness/skills/agent_bridge.py
# 技能工具 → AgentLoop 工具 的桥接 —— 下沉到 harness，两个应用共用。
#
# 下沉说明（2026-11）：此前这段逻辑写在 apps/dsn_study/boot.py 里
# （_bridge_tools_to_agent / _bridge_async_tools_to_agent 两个函数），
# 应用层各自抄一份，改一处就要记得改另一处。这里统一成一份实现。
#
# 关键点：同步工具与**协程工具**要分开桥接。
#   * 同步 handler 走 agent.register_tool(...)；
#   * 协程方法（如需要 await MCP 服务器）必须走 async_mode=True 的 handler，
#     否则 AgentLoop 的事件循环里 await 不到外部资源。

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger("SkillAgentBridge")


def bridge_skills_to_agent(agent: Any, skill_registry: Any,
                           skill_loader: Any = None) -> int:
    """把注册表里的全部技能工具桥接为 AgentLoop 工具。返回桥接数量。"""
    count = 0
    count += _bridge_sync(agent, skill_registry, skill_loader)
    count += _bridge_async(agent, skill_registry, skill_loader)
    return count


def _parameters_for(skill_name: str, spec: dict,
                    skill_loader: Any) -> dict:
    """从工具声明生成 function-calling 的 parameters schema。"""
    parameters = {"type": "object", "properties": {}}
    tool_spec_obj = spec.get("_tool_spec_obj")
    if tool_spec_obj is not None and skill_loader is not None:
        try:
            schema = skill_loader.build_function_schema(skill_name, tool_spec_obj)
            parameters = schema["function"]["parameters"]
        except Exception:
            logger.warning("工具 %s.%s 参数 schema 生成失败，使用空参",
                           skill_name, spec.get("name", ""), exc_info=True)
    return parameters


def _bridge_sync(agent: Any, skill_registry: Any,
                 skill_loader: Any = None) -> int:
    count = 0
    for key, spec in list(skill_registry._tool_specs.items()):
        skill_name, tool_name = key.split(".", 1)
        # 协程工具由 _bridge_async 处理（同步 handler 无法 await）
        if skill_registry.is_async_tool(skill_name, tool_name):
            continue
        parameters = _parameters_for(skill_name, spec, skill_loader)

        def _handler(_sk=skill_name, _tl=tool_name, **kwargs):
            return skill_registry.call_tool(_sk, _tl, kwargs)

        agent.register_tool(key, spec.get("description", ""), _handler,
                            parameters=parameters)
        count += 1
    return count


def _bridge_async(agent: Any, skill_registry: Any,
                  skill_loader: Any = None) -> int:
    """协程工具以异步 handler 桥接（需要 await 外部资源，如 MCP 服务器）。"""
    count = 0
    for key in list(skill_registry._tool_instances.keys()):
        skill_name, tool_name = key.split(".", 1)
        if not skill_registry.is_async_tool(skill_name, tool_name):
            continue
        spec = skill_registry._tool_specs.get(key) or {}
        parameters = _parameters_for(skill_name, spec, skill_loader)

        async def _ahandler(_sk=skill_name, _tl=tool_name, **kwargs):
            return await skill_registry.call_tool_async(_sk, _tl, kwargs)

        agent.register_tool(key, spec.get("description", ""), _ahandler,
                            parameters=parameters, async_mode=True)
        count += 1
    return count
