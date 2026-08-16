# harness/tools/toolbox.py
# ToolboxManager — 两阶段动态工具激活策略（场景无关）。
#
# 背景：工具数量较大时（几十~上百个），一次性把全部工具 schema 发给模型
# 会浪费大量 prompt token。两阶段激活把成本降到最低：
#
#   阶段 1（未激活）: 只发送一个 "toolbox" 索引工具，其 description 内联
#                     全部工具的 (id, 描述) 列表。模型按需一次性激活若干 id。
#   阶段 2（已激活）: 除 toolbox（无索引、仅补充激活）外，附带已激活工具
#                     的完整 schema。
#
# 与注册表解耦：通过 ToolIndexSource 协议适配任意工具注册表
# （harness ToolRegistry / dsn SkillRegistry / 其他自定义实现）。
#
# 用法:
#     manager = ToolboxManager(registry)          # registry 实现 ToolIndexSource
#     schema = manager.build_schema(activated)    # 阶段 1 / 阶段 2
#     real, results = manager.handle_calls(calls) # 分离 toolbox 调用并确认激活
#
# AgentLoop 已支持注入 toolbox（见 harness/agent/loop.py），
# 应用层也可独立使用（如 dsn models_plugin 委托本类）。

from __future__ import annotations

import json
import logging
from typing import Any, Optional, Protocol, runtime_checkable

from .base import to_wire_name

logger = logging.getLogger("harness.toolbox")


@runtime_checkable
class ToolIndexSource(Protocol):
    """工具索引源：提供 id→描述 索引与 id→完整 schema 的解析。"""

    def index(self) -> list[dict]:
        """返回 [{id, description}] 索引列表（顺序即展示顺序）。"""

    def schema_for(self, tool_id: str) -> Optional[dict]:
        """返回某工具 id 的完整 function schema（OpenAI 风格 dict）；不存在返回 None。"""


class RegistryIndexSource:
    """harness ToolRegistry 的索引源适配器。

    工具 id 即 Tool.name（可含命名空间，如 "file.read"）；
    schema_for 复用 Tool.to_openai_schema()。
    """

    def __init__(self, registry):
        self._registry = registry

    def index(self) -> list[dict]:
        return [
            {"id": t.name, "description": t.description}
            for t in self._registry.tools()
        ]

    def schema_for(self, tool_id: str) -> Optional[dict]:
        tool = self._registry.get(tool_id)
        return tool.to_openai_schema() if tool is not None else None


class ToolboxManager:
    """两阶段工具激活策略。

    参数:
        source      工具索引源（ToolIndexSource）
        enabled     总开关（关闭后 build_schema 直接导出全量）
        tool_name   toolbox 工具名（默认 "toolbox"）
        index_initial   首次（未激活）时是否内联完整索引；False 则只发空索引工具
        max_activated   单次激活上限（None 不限制）
    """

    def __init__(
        self,
        source: ToolIndexSource,
        *,
        enabled: bool = True,
        tool_name: str = "toolbox",
        index_initial: bool = True,
        max_activated: Optional[int] = None,
        nested: bool = False,
    ):
        self.source = source
        self.enabled = enabled
        self.tool_name = tool_name
        self.index_initial = index_initial
        self.max_activated = max_activated
        # schema 样式：False = 扁平 {name, description, parameters}（harness 约定，
        # client 侧自行包装）；True = OpenAI 嵌套 {"type":"function","function":{...}}
        # （如 DSN 技能加载器输出格式）
        self.nested = nested
        self._activated: list[str] = []
        self._cached_index: Optional[list[dict]] = None

    # ── 状态 ──

    @property
    def activated(self) -> list[str]:
        """当前已激活工具 id 列表（跨轮保持）。"""
        return list(self._activated)

    def reset(self) -> None:
        """清空激活状态（如新会话/新用户时）。"""
        self._activated = []

    def _index(self) -> list[dict]:
        if self._cached_index is None:
            self._cached_index = self.source.index() or []
        return self._cached_index

    def is_toolbox_call(self, call: Any) -> bool:
        """判断一次模型调用是否为 toolbox 索引调用（兼容对象/字典两种形态）。

        同时接受内部名与 wire 名（如 tool_name 含点号时的编码形式），
        因为 provider 回传的 function 名可能是编码后的。
        """
        name = getattr(call, "name", None)
        if name is None and isinstance(call, dict):
            name = call.get("function", {}).get("name", "")
        return name in (self.tool_name, to_wire_name(self.tool_name))

    # ── schema 构建 ──

    def build_schema(self, activated: Optional[list[str]] = None) -> list[dict]:
        """按激活状态构建 tools schema。

        - enabled=False         → 全量导出（等价于无 toolbox）
        - 无激活               → 仅 toolbox 索引工具
        - 有激活               → toolbox（补充激活）+ 已激活工具完整 schema
        """
        if not self.enabled:
            return self._full_schema()

        if activated is not None:
            self._activated = [a for a in activated if a in {i["id"] for i in self._index()}]
        act = self._activated

        schema: list[dict] = [self._toolbox_schema(include_index=not bool(act))]
        if act:
            for tool_id in act:
                detail = self.source.schema_for(tool_id)
                if detail:
                    schema.append(detail)
        return schema

    def _full_schema(self) -> list[dict]:
        return [self.source.schema_for(i["id"]) for i in self._index()
                if self.source.schema_for(i["id"]) is not None]

    def _toolbox_schema(self, *, include_index: bool) -> dict:
        index = self._index()
        if include_index and self.index_initial:
            index_desc = "\n".join(
                f"  - {item['id']}: {item.get('description', '')}"
                for item in index
            ) if index else "暂无可用工具"
            description = (
                "查看并激活你需要的工具。开始处理用户请求前，先思考可能需要哪些工具，"
                "一次调用激活全部。激活后即可在后续轮次中使用。\n\n"
                "如果用户只是询问你的能力/你能做什么，直接根据下方可用工具列表回答即可，"
                "不要调用本工具，也不要激活任何工具。\n\n可用工具:\n" + index_desc
            )
        else:
            description = (
                "激活更多工具。如果处理过程中发现还需要其他工具，调用此工具补充激活。"
                "\n\n已激活列表仅供追踪，不再重复列出。"
            )

        enum_ids = [item["id"] for item in index]
        tool = {
            # 与 Tool.to_openai_schema 一致：函数名走 wire 编码，兼容强校验 provider。
            # 注意 enum 里的工具 ID 是参数取值而非函数名，保持内部原名不变。
            "name": to_wire_name(self.tool_name),
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    "ids": {
                        "type": "array",
                        "items": ({"type": "string", "enum": enum_ids}
                                  if enum_ids else {"type": "string"}),
                        "description": "需要激活的工具 ID 列表",
                    }
                },
                "required": ["ids"],
            },
        }
        if self.nested:
            return {"type": "function", "function": tool}
        return tool

    # ── 调用处理 ──

    def handle_calls(self, calls: list[Any]) -> tuple[list[Any], list[dict]]:
        """分离 toolbox 激活调用与真实工具调用。

        返回 (real_calls, results)：
          - real_calls 为需要实际执行的调用（原对象形态，可直接喂给执行器）
          - results 为 toolbox 调用的确认结果消息（tool role 内容），
            携带 function/tool_call_id/success/data 字段，与执行器结果同构。
        副作用：更新内部激活状态（去重、上限截断）。
        """
        if not self.enabled:
            return list(calls), []

        real_calls: list[Any] = []
        results: list[dict] = []
        for call in calls:
            if not self.is_toolbox_call(call):
                real_calls.append(call)
                continue
            call_id = getattr(call, "id", None) or (call.get("id", "") if isinstance(call, dict) else "")
            args = self._call_arguments(call)
            ids = args.get("ids", []) if isinstance(args, dict) else []
            if not isinstance(ids, list):
                ids = [ids]
            ids = [str(i) for i in ids if str(i).strip()]

            # ids 缺失/为空（常见于模型的 arguments 因流式拼接损坏而解析成 {}）：
            # 必须回一个明确的失败，否则模型只看到"无新增工具"会误判自己已经
            # 传了参数，从而反复空调用、无法进入下一步。
            if not ids:
                results.append({
                    "call_id": call_id,
                    "name": self.tool_name,
                    "success": False,
                    "status": "error",
                    "error": "缺少必填参数 ids：必须传入需要激活的工具 ID 数组。",
                    "hint": ('正确调用示例：{"ids": ["file.read", "file.tree"]}。'
                             "ids 只能取可用工具列表中的 ID。"),
                    "output": {"activated": [], "already_activated": self.activated},
                })
                logger.warning("Toolbox: 收到空 ids 的激活调用，已回错误提示")
                continue

            known = {i["id"] for i in self._index()}
            added: list[str] = []
            unknown: list[str] = []
            for tool_id in ids:
                if tool_id not in known:
                    unknown.append(tool_id)
                    continue
                if tool_id in self._activated:
                    continue
                if self.max_activated is not None and len(self._activated) >= self.max_activated:
                    break
                self._activated.append(tool_id)
                added.append(tool_id)

            message = f"已激活工具: {', '.join(added)}" if added else "无新增工具（可能已激活）"
            if unknown:
                message += f"；未知工具 ID 已忽略: {', '.join(unknown)}"
            results.append({
                "call_id": call_id,
                "name": self.tool_name,
                "success": True,
                "status": "ok",
                "output": {
                    "activated": added,
                    "unknown": unknown,
                    "all_activated": self.activated,
                    "message": message,
                },
            })
            logger.info("Toolbox: 激活工具 %s (累计 %d)", added, len(self._activated))
        return real_calls, results

    def results_to_legacy(self, results: list[dict]) -> list[dict]:
        """把引擎风格结果转为旧式结果（function/tool_call_id/data），
        供按旧格式消费的执行器（如 dsn ToolPlugin）直接使用。"""
        legacy = []
        for r in results:
            legacy.append({
                "function": r.get("name", self.tool_name),
                "tool_call_id": r.get("call_id", ""),
                "success": r.get("success", True),
                "data": r.get("output", {}),
            })
        return legacy

    def confirm(self, call: Any) -> list[dict]:
        """单次调用确认入口（结果与 handle_calls 中一致）。"""
        _, results = self.handle_calls([call])
        return results

    @staticmethod
    def _call_arguments(call: Any) -> dict:
        raw = getattr(call, "arguments", None)
        if isinstance(raw, dict):
            return raw
        if isinstance(call, dict):
            raw = call.get("function", {}).get("arguments", "{}")
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except (TypeError, ValueError):
                return {}
        return {}

    def __repr__(self) -> str:
        return (f"<ToolboxManager enabled={self.enabled} "
                f"tools={len(self._index())} activated={len(self._activated)}>")
