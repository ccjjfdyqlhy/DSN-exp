# plugins/builtin/skills_plugin.py
# 技能工具执行插件 — POST_PROCESS (priority 35, in memory 30 and task 40)

from __future__ import annotations

import json
import logging
import re

from plugins.base import Plugin, HookPoint, PluginContext

logger = logging.getLogger("SkillsPlugin")

_TOOL_RE = re.compile(r"<tool>\s*(.*?)\s*</tool>", re.DOTALL)


class SkillsPlugin(Plugin):
    """
    技能工具执行插件。

    POST_PROCESS 阶段 (priority 35):
    - 解析 AI 回复中的 <tool> 标签
    - 通过 SkillRegistry 调用对应技能工具
    - 将执行结果追加到 ctx.reply

    依赖: skill_registry (SkillRegistry 实例)
    """

    name = "skills"
    description = "技能工具执行 — 解析 <tool> 标签并调用 SkillRegistry"
    hooks = [HookPoint.POST_PROCESS]
    priority = 35

    def __init__(self, skill_registry=None):
        self._skill_registry = skill_registry

    def on_load(self) -> None:
        if self._skill_registry is None:
            logger.warning("skill_registry 未注入，SkillsPlugin 将跳过工具执行")

    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        if self._skill_registry is None:
            return ctx

        if hook == HookPoint.POST_PROCESS:
            return self._on_post_process(ctx)
        return ctx

    def _on_post_process(self, ctx: PluginContext) -> PluginContext:
        original = ctx.original_reply
        if not original:
            return ctx

        tool_matches = list(_TOOL_RE.finditer(original))
        if not tool_matches:
            return ctx

        tool_results: list[str] = []

        for match in tool_matches:
            try:
                tool_data = json.loads(match.group(1).strip())
            except json.JSONDecodeError as e:
                logger.error("解析 <tool> JSON 失败: %s", e)
                continue

            skill_name = tool_data.get("skill", "")
            tool_name = tool_data.get("tool", "")
            params = tool_data.get("params", {})

            if not skill_name or not tool_name:
                logger.warning("无效的 <tool> 数据: 缺少 skill 或 tool")
                continue

            try:
                result = self._skill_registry.call_tool(skill_name, tool_name, params)
                if isinstance(result, dict):
                    tool_results.append(self._format_tool_result(skill_name, tool_name, result))
                else:
                    tool_results.append(f"\n\n[工具 {skill_name}.{tool_name} 结果]\n{result}")
            except ValueError as e:
                logger.error("工具调用失败: %s", e)
                tool_results.append(f"\n\n[工具调用失败: {skill_name}.{tool_name}] {e}")
            except Exception as e:
                logger.exception("工具执行异常: %s.%s", skill_name, tool_name)
                tool_results.append(f"\n\n[工具执行异常: {skill_name}.{tool_name}] {e}")

        # 移除 <tool> 标签，追加工具结果
        cleaned = _TOOL_RE.sub("", original).strip()

        if tool_results:
            cleaned += "\n\n" + "\n".join(tool_results)

        ctx.reply = cleaned
        return ctx

    @staticmethod
    def _format_tool_result(skill: str, tool: str, result: dict) -> str:
        """格式化工具执行结果"""
        if not result.get("success", False):
            return f"\n\n[工具执行失败: {skill}.{tool}]\n{result.get('error', '未知错误')}"

        lines = [f"\n\n[工具 {skill}.{tool} 执行结果]"]

        if skill == "web_search" and tool == "search":
            lines.append(f"搜索: {result.get('query', '')}")
            for i, r in enumerate(result.get("results", []), 1):
                lines.append(f"  {i}. {r.get('title', '')}")
                if r.get("snippet"):
                    lines.append(f"     {r['snippet'][:200]}")
                if r.get("url"):
                    lines.append(f"     {r['url']}")

        elif skill == "file_manager":
            if tool == "list_dir":
                lines.append(f"目录: {result.get('path', '')}")
                for item in result.get("items", []):
                    type_mark = "[d]" if item.get("type") == "dir" else "[f]"
                    lines.append(f"  {type_mark} {item['name']}")
            elif tool == "read_file":
                lines.append(f"文件: {result.get('path', '')} ({result.get('size', 0)} bytes)")
                content = result.get("content", "")
                if len(content) > 2000:
                    content = content[:2000] + "\n...(内容截断)"
                lines.append(content)
            elif tool == "write_file":
                lines.append(f"已写入: {result.get('path', '')} ({result.get('size', 0)} bytes)")
            else:
                lines.append(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            lines.append(json.dumps(result, ensure_ascii=False, indent=2))

        return "\n".join(lines)
