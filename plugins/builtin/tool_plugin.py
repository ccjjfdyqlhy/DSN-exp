# plugins/builtin/tool_plugin.py
# 工具执行插件 — POST_PROCESS (priority=35)

from __future__ import annotations

import json
import logging
import re

from plugins.base import Plugin, HookPoint, PluginContext

logger = logging.getLogger("ToolPlugin")

_TOOL_RE = re.compile(r"<tool>\s*(.*?)\s*</tool>", re.DOTALL)


def _classify_tool_error(exc: Exception) -> str:
    """把工具执行异常归类为结构化 error_type，便于前端/模型区分错误原因。"""
    msg = str(exc) or ""
    if isinstance(exc, TypeError) and "missing" in msg:
        return "INVALID_PARAM"
    if isinstance(exc, ValueError):
        if "工具不存在" in msg:
            return "TOOL_NOT_FOUND"
        if "工具方法不存在" in msg:
            return "MISSING_METHOD"
        if "无法解析" in msg:
            return "UNRESOLVED_NAME"
    return "EXEC_ERROR"


class ToolPlugin(Plugin):
    name = "tool"
    description = "工具调用 — 原生 tool_calls + <tool> 标签降级"
    hooks = [HookPoint.POST_PROCESS]
    priority = 35

    def __init__(self, skill_registry=None):
        self._skill_registry = skill_registry

    def on_load(self) -> None:
        if self._skill_registry is None:
            logger.warning("skill_registry 未注入")

    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        if self._skill_registry is None or hook != HookPoint.POST_PROCESS:
            return ctx

        self._set_call_context(ctx)

        native_calls = ctx.extra.pop("_native_tool_calls", [])
        if native_calls:
            logger.info("ToolPlugin: 原生模式, %d 个 tool_calls 待处理", len(native_calls))
            return self._handle_native_tool_calls(native_calls, ctx)

        if ctx.original_reply and ("<tool>" in ctx.original_reply or "<task>" in ctx.original_reply):
            logger.info("ToolPlugin: XML 降级模式, 检测到标签")
        return self._handle_xml_tool_tags(ctx)

    def _set_call_context(self, ctx: PluginContext):
        from skills.context import set_call_context
        set_call_context(user_id=ctx.user_id, chat_id=ctx.chat_id or 0)
        # 注入到系统工具类的 _ctx
        self._inject_system_ctx(ctx)

    def _inject_system_ctx(self, ctx: PluginContext):
        for key, instance in self._skill_registry._tool_instances.items():
            cls = type(instance)
            if hasattr(cls, '_ctx'):
                cls._ctx["_uid"] = ctx.user_id
                cls._ctx["_cid"] = ctx.chat_id or 0
                if "_task_manager" in ctx.extra:
                    cls._ctx["task_manager"] = ctx.extra["_task_manager"]
                if "_db" in ctx.extra:
                    cls._ctx["db"] = ctx.extra["_db"]

    def _handle_native_tool_calls(self, tool_calls: list,
                                   ctx: PluginContext) -> PluginContext:
        from models import DETAIL_ACTIONS
        logger.info("ToolPlugin(native): 处理 %d 个原生 tool_calls", len(tool_calls))

        if DETAIL_ACTIONS:
            print("\n" + "=" * 60)
            print("🔧 [ToolPlugin] 接收原生 tool_calls:")
            print("=" * 60)

        results = []
        for tc in tool_calls:
            func_name = tc.get("function", {}).get("name", "unknown")
            try:
                func_args = json.loads(
                    tc.get("function", {}).get("arguments", "{}"))
            except json.JSONDecodeError:
                results.append({"function": func_name, "tool_call_id": tc["id"],
                                "success": False, "error": "JSON 解析失败",
                                "error_type": "INVALID_JSON"})
                logger.warning("  ✗ %s: JSON 解析失败", func_name)
                continue

            logger.info("  → 执行 %s args=%s", func_name,
                        json.dumps(func_args, ensure_ascii=False, default=str)[:100])

            if DETAIL_ACTIONS:
                print(f"\n  ▶ {func_name}")
                print("  ┌─ 参数:")
                for k, v in func_args.items():
                    v_str = json.dumps(v, ensure_ascii=False, default=str)
                    if len(v_str) > 300:
                        v_str = v_str[:300] + f"...(总{len(v_str)}字符)"
                    print(f"  │  {k} = {v_str}")
                print("  └─────────────")

            # 命名空间路由：skill-{skill_name}-{tool_name}
            parts = func_name.split("-", 2)
            if len(parts) >= 3 and parts[0] == "skill":
                skill_name = parts[1]
                tool_name = parts[2]
                try:
                    result_data = self._skill_registry.call_tool(
                        skill_name, tool_name, func_args)

                    if DETAIL_ACTIONS:
                        r_str = json.dumps(result_data, ensure_ascii=False, default=str)
                        if len(r_str) > 500:
                            r_str = r_str[:500] + f"...(总{len(r_str)}字符)"
                        print(f"  ✔ 结果: {r_str}")

                    results.append({
                        "function": func_name,
                        "tool_call_id": tc["id"],
                        "success": True,
                        "data": result_data,
                    })
                    logger.info("  ✓ %s 执行成功", func_name)

                    # 触发动作旁白
                    self._fire_action_narrative(func_name, func_args, ctx)

                except Exception as e:
                    logger.error("  ✗ %s 执行失败: %s", func_name, e)
                    if DETAIL_ACTIONS:
                        print(f"  ✗ 失败: {e}")
                    results.append({
                        "function": func_name,
                        "tool_call_id": tc["id"],
                        "success": False,
                        "error": str(e),
                        "error_type": _classify_tool_error(e),
                    })
            else:
                results.append({
                    "function": func_name,
                    "tool_call_id": tc.get("id", ""),
                    "success": False,
                    "error": f"无法解析工具名: {func_name}",
                    "error_type": "UNRESOLVED_NAME",
                })
                logger.warning("  ✗ %s: 无法解析", func_name)

        if results:
            ctx.extra.setdefault("_tag_results", []).extend(results)
            logger.info("ToolPlugin(native): %d 个 tool_calls", len(results))

        # 处理信号类结果 — 设置 ctx 标记供后续插件消费
        for r in results:
            if not r.get("success"):
                continue
            func = r.get("function", "")
            data = r.get("data", {})
            if isinstance(data, str):
                continue

            if func == "skill-system-confirm":
                if data.get("action") == "confirm_requested":
                    ctx.extra["confirm_requested"] = True
                    logger.info("ToolPlugin: confirm_requested 已设置")
            elif func == "skill-system-record_impression":
                if data.get("recorded"):
                    logger.info("ToolPlugin: impression 已记录")

        return ctx

    def _handle_xml_tool_tags(self, ctx: PluginContext) -> PluginContext:
        original = ctx.original_reply
        if not original:
            return ctx

        tool_matches = list(_TOOL_RE.finditer(original))
        if not tool_matches:
            return ctx

        logger.info("ToolPlugin(xml): %d 个 <tool> 标签", len(tool_matches))
        results: list[dict] = []

        for match in tool_matches:
            try:
                tool_data = json.loads(match.group(1).strip())
            except json.JSONDecodeError as e:
                results.append({"tag": "<tool>", "success": False,
                                "summary": f"JSON 解析: {e}",
                                "error_type": "INVALID_JSON"})
                continue

            skill_name = tool_data.get("skill", "")
            tool_name = tool_data.get("tool", "")
            params = tool_data.get("params", {})
            if not skill_name or not tool_name:
                continue

            try:
                result_data = self._skill_registry.call_tool(
                    skill_name, tool_name, params)
                results.append({"tag": "<tool>", "success": True,
                                "data": result_data,
                                "skill": skill_name, "params": params})
            except Exception as e:
                results.append({"tag": "<tool>", "success": False,
                                "summary": str(e),
                                "error_type": _classify_tool_error(e)})

        ctx.reply = _TOOL_RE.sub("", ctx.reply).strip()
        if results:
            ctx.extra.setdefault("_tag_results", []).extend(results)
            # 触发动作旁白（仅成功调用）
            for r in results:
                if r.get("success") and r.get("data"):
                    self._fire_action_narrative(
                        r.get("skill", ""), r.get("params", {}), ctx)
        return ctx

    # ── 动作旁白 ──

    def _fire_action_narrative(self, func_name: str, func_args: dict,
                                ctx: PluginContext) -> None:
        narrator = ctx.extra.get("_action_narrator")
        collector = ctx.extra.get("_narrative_collector")
        if narrator and collector:
            narrator.fire_action_narrative(
                action_type=func_name,
                params=func_args,
                collector=collector,
            )
