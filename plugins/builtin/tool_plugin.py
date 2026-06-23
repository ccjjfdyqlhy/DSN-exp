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
                    "summary": self._summarize_result(skill_name, tool_name, params, result),
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

    @staticmethod
    def _summarize_result(skill: str, tool: str, params: dict, result) -> str:
        if not isinstance(result, dict):
            s = str(result)
            return s[:500] + "…" if len(s) > 500 else s

        if not result.get("success", True):
            return f"{skill}.{tool} 失败: {result.get('error', '未知错误')}"

        lines = [f"{skill}.{tool} 成功"]

        if tool == "scan":
            files = result.get("files", [])
            lines.append(f"扫描完成，{result.get('count', len(files))} 页")
            for f in files:
                path = f.get("filepath", f.get("path", ""))
                size = f.get("size", 0)
                if size:
                    lines.append(f"  → {path} ({size} bytes)")
                else:
                    lines.append(f"  → {path}")

        elif tool == "list_scanners":
            scanners = result.get("scanners", [])
            for s in scanners:
                name = s.get("name", s) if isinstance(s, dict) else s
                status = s.get("status", "") if isinstance(s, dict) else ""
                lines.append(f"  {name}" + (f" ({status})" if status else ""))

        elif tool == "list_printers":
            printers = result.get("printers", [])
            for p in printers:
                name = p.get("name", p) if isinstance(p, dict) else p
                lines.append(f"  {name}")

        elif tool == "print_file":
            lines.append(f"打印已提交: {params.get('file_path', '')}")

        elif tool == "process_scan":
            hmd = result.get("hmd_path", "")
            docs = result.get("documents", [])
            photos = result.get("photos", [])
            lines.append(f"处理完成: {len(docs)} 文档, {len(photos)} 照片")
            if hmd:
                lines.append(f"  .hmd: {hmd}")
            if result.get("feedback_text"):
                lines.append(f"  反馈: {result['feedback_text'][:300]}")

        elif tool == "read_hmd":
            mda = result.get("mda", "")
            mdb = result.get("mdb", "")
            images = result.get("images", [])
            lines.append(f"读取 .hmd 完成: mdA={len(mda)}字, mdB={len(mdb)}字, 图片={len(images)}张")

        elif skill == "web_search":
            results_list = result.get("results", [])
            lines.append(f"搜索到 {len(results_list)} 条结果")
            for r in results_list[:5]:
                title = r.get("title", "")
                url = r.get("url", "")
                lines.append(f"  {title}")
                if url:
                    lines.append(f"    {url}")
            if len(results_list) > 5:
                lines.append(f"  ...还有 {len(results_list) - 5} 条")

        elif skill == "file_manager":
            sub_tool = params.get("tool", tool)
            if tool in ("explore_fs", "workspace_file") and sub_tool:
                if sub_tool in ("list_dir",):
                    items = result.get("items", [])
                    lines.append(f"目录共 {len(items)} 项")
                    for item in items[:20]:
                        marker = "📁" if item.get("type") == "dir" else "📄"
                        lines.append(f"  {marker} {item['name']}")
                    if len(items) > 20:
                        lines.append(f"  ...还有 {len(items) - 20} 项")
                elif sub_tool in ("read_file",):
                    content = result.get("content", "")
                    lines.append(f"读取 {result.get('path', '')} ({result.get('size', 0)} bytes)")
                    lines.append(content[:300])
                    if len(content) > 300:
                        lines.append("  ...(已截断)")
                elif sub_tool in ("write_file",):
                    lines.append(f"已写入 {result.get('path', '')} ({result.get('size', 0)} bytes)")

        else:
            snippet = json.dumps(result, ensure_ascii=False, indent=2)
            if len(snippet) > 500:
                snippet = snippet[:500] + "\n  ..."
            lines.append(snippet)

        return "\n".join(lines)
