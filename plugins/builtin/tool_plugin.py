# plugins/builtin/tool_plugin.py
# 工具执行插件 — POST_PROCESS (priority=35)
# 替代旧 SkillsPlugin，统一写入 _tag_results 供引擎层 agent 循环消费

from __future__ import annotations

import json
import logging
import re

from plugins.base import Plugin, HookPoint, PluginContext

logger = logging.getLogger("ToolPlugin")

_TOOL_RE = re.compile(r"<tool>\s*(.*?)\s*</tool>", re.DOTALL)


class ToolPlugin(Plugin):
    """处理 <tool> 标签，调用 SkillRegistry 执行技能工具。"""

    name = "tool"
    description = "<tool> 标签解析与 SkillRegistry 调用"
    hooks = [HookPoint.POST_PROCESS]
    priority = 35

    def __init__(self, skill_registry=None):
        self._skill_registry = skill_registry

    def on_load(self) -> None:
        if self._skill_registry is None:
            logger.warning("skill_registry 未注入，ToolPlugin 将跳过工具执行")

    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        if self._skill_registry is None or hook != HookPoint.POST_PROCESS:
            return ctx
        return self._on_post_process(ctx)

    def _on_post_process(self, ctx: PluginContext) -> PluginContext:
        original = ctx.original_reply
        if not original:
            return ctx

        tool_matches = list(_TOOL_RE.finditer(original))
        if not tool_matches:
            return ctx

        logger.info("ToolPlugin: 发现 %d 个 <tool> 标签，开始执行", len(tool_matches))

        results: list[dict] = []

        for match in tool_matches:
            try:
                tool_data = json.loads(match.group(1).strip())
            except json.JSONDecodeError as e:
                logger.error("解析 <tool> JSON 失败: %s", e)
                results.append({
                    "tag": "<tool>", "success": False,
                    "skill": "", "tool": "",
                    "summary": f"JSON 解析失败: {e}",
                    "error": str(e),
                })
                continue

            skill_name = tool_data.get("skill", "")
            tool_name = tool_data.get("tool", "")
            params = tool_data.get("params", {})

            if not skill_name or not tool_name:
                logger.warning("无效的 <tool> 数据: 缺少 skill 或 tool")
                continue

            try:
                result = self._skill_registry.call_tool(skill_name, tool_name, params)
                results.append({
                    "tag": "<tool>", "success": True,
                    "skill": skill_name, "tool": tool_name,
                    "data": result,
                })
            except ValueError as e:
                logger.error("工具调用失败: %s", e)
                results.append({
                    "tag": "<tool>", "success": False,
                    "skill": skill_name, "tool": tool_name,
                    "summary": f"调用失败: {e}",
                    "error": str(e),
                })
            except Exception as e:
                logger.exception("工具执行异常: %s.%s", skill_name, tool_name)
                results.append({
                    "tag": "<tool>", "success": False,
                    "skill": skill_name, "tool": tool_name,
                    "summary": f"执行异常: {e}",
                    "error": str(e),
                })

        ctx.reply = _TOOL_RE.sub("", ctx.reply).strip()

        if results:
            ctx.extra.setdefault("_tag_results", []).extend(results)
            logger.info("ToolPlugin: 已写入 %d 条结果到 _tag_results", len(results))

        return ctx
