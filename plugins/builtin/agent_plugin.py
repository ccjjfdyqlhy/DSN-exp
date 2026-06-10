# plugins/builtin/agent_plugin.py
# Agent 循环插件 — 工具反馈回路 + 多步代理循环 (POST_PROCESS, priority=35)

from __future__ import annotations

import json
import logging
import re
import time

from plugins.base import Plugin, HookPoint, PluginContext

logger = logging.getLogger("AgentPlugin")

_TOOL_RE = re.compile(r"<tool>\s*(.*?)\s*</tool>", re.DOTALL)

# 工具结果最大字符数（单条）
_MAX_TOOL_RESULT_LEN = 3000


class AgentPlugin(Plugin):
    """
    Agent 循环插件。

    POST_PROCESS 阶段 (priority=35):
    1. 解析 AI 回复中的 <tool> 标签
    2. 通过 SkillRegistry 执行工具
    3. 将工具结果注入对话历史，再次调用 LLM
    4. 如果新回复仍含 <tool> 标签，循环继续
    5. 达到最大步数或无新工具时终止

    依赖:
    - skill_registry (SkillRegistry) — 工具执行
    - models_plugin (ModelsPlugin)  — LLM 再调用

    配置 (通过 ctx.agent_* 或构造函数):
    - max_steps: 最大循环步数 (默认 5)
    - token_budget: token 预算 (默认 8000)
    - agent_timeout: 总超时秒数 (默认 120)
    """

    name = "agent"
    description = "Agent 循环 — <tool> 标签执行 + LLM 反馈回路 + 多步编排"
    hooks = [HookPoint.POST_PROCESS]
    priority = 35

    def __init__(
        self,
        skill_registry=None,
        models_plugin=None,
        max_steps: int = 5,
        token_budget: int = 8000,
        agent_timeout: float = 120.0,
        impression_manager=None,
    ):
        self._skill_registry = skill_registry
        self._models_plugin = models_plugin
        self._default_max_steps = max_steps
        self._default_token_budget = token_budget
        self._default_timeout = agent_timeout
        self._impression = impression_manager

    def on_load(self) -> None:
        if self._skill_registry is None:
            logger.warning("skill_registry 未注入，AgentPlugin 将跳过工具执行")
        if self._models_plugin is None:
            logger.warning("models_plugin 未注入，AgentPlugin 将无法进行 LLM 再调用")

    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        if self._skill_registry is None:
            return ctx
        if hook != HookPoint.POST_PROCESS:
            return ctx
        if not ctx.agent_active:
            # 非 agent 模式：像旧 SkillsPlugin 一样处理（单次执行 + 结果追加）
            return self._run_single_pass(ctx)

        return self._run_agent_loop(ctx)

    # ── 单次执行模式（向后兼容旧 SkillsPlugin 行为）──

    def _run_single_pass(self, ctx: PluginContext) -> PluginContext:
        """非 agent 模式：执行 <tool> 标签，结果直接追加到 reply"""
        original = ctx.original_reply
        if not original:
            return ctx

        tool_matches = list(_TOOL_RE.finditer(original))
        if not tool_matches:
            return ctx

        tool_results = self._execute_tools(tool_matches)

        cleaned = _TOOL_RE.sub("", ctx.reply if ctx.reply else original).strip()
        if tool_results:
            cleaned += "\n\n" + "\n".join(tool_results)

        ctx.reply = cleaned
        return ctx

    # ── Agent 循环模式 ──

    def _run_agent_loop(self, ctx: PluginContext) -> PluginContext:
        """Agent 循环：执行工具 → 反馈 LLM → 检查是否有新工具 → 重复"""
        max_steps = ctx.agent_max_steps or self._default_max_steps
        deadline = time.time() + self._default_timeout
        step_count = 0

        # 构建消息列表：system prompt + 原始历史
        base_messages = [{"role": "system", "content": ctx.system_prompt}]
        base_messages.extend(ctx.full_history)

        # 追加用户消息（含时间戳）
        from datetime import datetime
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        base_messages.append({
            "role": "user",
            "content": f"[{now}] {ctx.message}",
        })

        current_reply = ctx.original_reply  # LLM 首轮回复（含标签）

        while step_count < max_steps and time.time() < deadline:
            # 解析当前回复中的工具调用
            tool_matches = list(_TOOL_RE.finditer(current_reply))
            if not tool_matches:
                break  # 无工具标签，循环结束

            step_count += 1
            ctx.agent_step_count = step_count
            logger.info("Agent 第 %d 步: 发现 %d 个工具调用", step_count, len(tool_matches))

            # 执行工具
            tool_results = self._execute_tools(tool_matches)

            # 将本轮 AI 回复加入消息历史
            base_messages.append({
                "role": "assistant",
                "content": current_reply,
            })

            # 将工具结果作为用户消息注入
            for result_text in tool_results:
                base_messages.append({
                    "role": "user",
                    "content": f"[工具结果]\n{result_text}",
                })

            # 检查 token 预算
            total_chars = sum(len(m.get("content", "")) for m in base_messages)
            budget = ctx.agent_token_budget or self._default_token_budget
            if total_chars > budget:
                # 裁剪：保留 system prompt + 最近的消息
                kept = [base_messages[0]]  # system prompt
                kept.extend(base_messages[-20:])  # 最近 20 条
                base_messages = kept
                logger.info("Agent 第 %d 步: 超出 token 预算，已裁剪历史", step_count)

            # 再次调用 LLM
            if self._models_plugin is None:
                logger.warning("models_plugin 未注入，无法继续 Agent 循环")
                break

            try:
                current_reply = self._models_plugin.invoke(base_messages, ctx)
                if self._impression and current_reply:
                    self._extract_impressions(current_reply, ctx.user_id)
            except Exception as e:
                logger.error("Agent 第 %d 步 LLM 调用失败: %s", step_count, e)
                if tool_results:
                    current_reply = "工具已执行，但生成回复时出错。\n" + "\n".join(tool_results)
                break

        # 循环结束 — 清理最终回复
        clean = _TOOL_RE.sub("", current_reply).strip()
        ctx.reply = clean
        ctx.extra["agent_steps_executed"] = step_count

        if step_count >= max_steps:
            logger.warning("Agent 达到最大步数 %d", max_steps)

        return ctx

    # ── 工具执行 ──

    def _execute_tools(self, tool_matches: list) -> list[str]:
        """执行一组 <tool> 标签，返回格式化结果文本列表"""
        results: list[str] = []

        for match in tool_matches:
            try:
                tool_data = json.loads(match.group(1).strip())
            except json.JSONDecodeError as e:
                logger.error("Agent 解析 <tool> JSON 失败: %s", e)
                results.append(f"JSON 解析失败: {e}")
                continue

            skill_name = tool_data.get("skill", "")
            tool_name = tool_data.get("tool", "")
            params = tool_data.get("params", {})

            if not skill_name or not tool_name:
                results.append("工具调用缺少 skill 或 tool 字段")
                continue

            try:
                result = self._skill_registry.call_tool(skill_name, tool_name, params)
                results.append(self._format_tool_result(skill_name, tool_name, result))
            except ValueError as e:
                logger.error("Agent 工具调用失败: %s", e)
                results.append(f"{skill_name}.{tool_name} 调用失败: {e}")
            except Exception as e:
                logger.exception("Agent 工具执行异常: %s.%s", skill_name, tool_name)
                results.append(f"{skill_name}.{tool_name} 执行异常: {e}")

        return results

    def _extract_impressions(self, text: str, user_id: int) -> None:
        """从文本中提取 IMPRESSION: 标签并写入 DB"""
        if not self._impression:
            return
        import re
        pat = re.compile(r"IMPRESSION\s*:\s*(.+?)\s*:\s*(.+?)\s*:\s*(\d+)", re.IGNORECASE)
        for m in pat.finditer(text):
            try:
                category = m.group(1).strip()
                content = m.group(2).strip()
                confidence = min(1.0, max(0.1, int(m.group(3)) / 100.0))
                if content and len(content) >= 2:
                    self._impression.add(
                        user_id, category, content,
                        confidence, "inferred",
                    )
                    logger.info("Agent 步骤提取印象: uid=%d cat=%s", user_id, category)
            except Exception:
                pass

    @staticmethod
    def _format_tool_result(skill: str, tool: str, result) -> str:
        """格式化单个工具结果为 LLM 友好的文本"""
        if not isinstance(result, dict):
            return str(result)[:_MAX_TOOL_RESULT_LEN]

        if not result.get("success", False):
            return f"skill={skill}, tool={tool}, 执行失败: {result.get('error', '未知错误')}"

        # 根据技能类型优化格式
        if skill == "web_search" and tool == "search":
            lines = [f"搜索完成 (query={result.get('query', '')}):"]
            for i, r in enumerate(result.get("results", []), 1):
                lines.append(f"  {i}. {r.get('title', '')}")
                if r.get("snippet"):
                    lines.append(f"     {r['snippet'][:300]}")
                if r.get("url"):
                    lines.append(f"     URL: {r['url']}")
            return "\n".join(lines)

        if skill == "file_manager":
            if tool == "list_dir":
                lines = [f"目录 {result.get('path', '')} 内容:"]
                for item in result.get("items", []):
                    type_mark = "[DIR]" if item.get("type") == "dir" else "[FILE]"
                    lines.append(f"  {type_mark} {item['name']}")
                return "\n".join(lines)
            elif tool == "read_file":
                content = result.get("content", "")
                if len(content) > _MAX_TOOL_RESULT_LEN:
                    content = content[:_MAX_TOOL_RESULT_LEN] + "\n...(已截断)"
                return (
                    f"文件 {result.get('path', '')} "
                    f"({result.get('size', 0)} bytes):\n{content}"
                )
            elif tool == "write_file":
                return (
                    f"已写入文件 {result.get('path', '')} "
                    f"({result.get('size', 0)} bytes)"
                )

        # 通用格式
        return json.dumps(result, ensure_ascii=False, indent=2)
