# plugins/builtin/subagent_runner.py
# 子代理执行器 — 隔离上下文 + 工具调用小循环 + 完成后即释放

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from harness.pipeline import Context as PluginContext

logger = logging.getLogger("SubAgentRunner")

# 不支持原生 function calling 的模型类型（走纯文本调用）
_NO_NATIVE_TOOLS = ("fast", "lmstudio")


@dataclass
class SubAgentResult:
    """子代理一次执行的产物（用完即释放，不保留状态）"""
    output: str = ""
    tool_trace: list = field(default_factory=list)   # 已执行工具的结果
    steps: int = 0
    error: str = ""


class SubAgentRunner:
    """
    隔离上下文的工具型子代理。

    - 上下文独立: 每次 run 从零构建 messages，不携带主对话历史
    - 小循环: 最多 max_steps 轮 (LLM → 执行原生 tool_calls → 回喂结果)，
      模型返回纯文本回复即终止；不进入主模型的完整 Agent 循环
    - 工具执行: 原生 function calling，通过 skill_registry.call_tool 执行
    - 用完即释放: 返回 SubAgentResult 后不保留任何会话状态
    """

    def __init__(self, models_plugin=None, skill_registry=None,
                 db=None, task_manager=None, max_steps: int = 3,
                 tools_builder=None):
        self._models = models_plugin
        self._skill_registry = skill_registry
        self._db = db
        self._task_mgr = task_manager
        self._max_steps = max(max_steps, 1)
        self._tools_builder = tools_builder  # 可选: () -> tools schema

    # ── 入口 ──

    def run(self, system_prompt: str, task: str, *,
            user_id: int = 0, chat_id: int | None = None,
            model_type: str | None = None,
            tools: list[dict] | None = None) -> SubAgentResult:
        """
        执行一个子代理。

        system_prompt 由主模型 (assigner) 书写；task 为具体子任务描述。
        上下文完全隔离：仅包含 system + task + 本次小循环产生的消息。
        """
        result = SubAgentResult()
        if self._models is None:
            result.error = "models_plugin 未注入，无法执行子代理"
            logger.warning(result.error)
            return result

        effective_type = model_type or getattr(self._models, '_model_type', None)
        tools_schema = tools if tools is not None else self._build_tools_schema(effective_type)

        # 隔离上下文：独立的 PluginContext（chat_id 置空避免写入主对话历史）
        sub_ctx = PluginContext(
            user_id=user_id,
            chat_id=None,
            message=task,
            model_type=effective_type,
        )
        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task},
        ]

        last_reply = ""
        for step in range(self._max_steps):
            result.steps = step + 1
            try:
                if tools_schema:
                    last_reply = self._models.invoke(messages, sub_ctx,
                                                     tools=tools_schema)
                else:
                    last_reply = self._models.invoke(messages, sub_ctx)
            except Exception as e:
                logger.error("子代理 LLM 调用失败 (step=%d): %s", step + 1, e)
                result.error = str(e)
                break

            tool_calls = sub_ctx.extra.pop("_native_tool_calls", [])
            if not tool_calls:
                break

            # 执行工具并回喂结果（单次迭代内完成）
            exec_results = self._execute_tool_calls(tool_calls, user_id,
                                                    chat_id or 0)
            result.tool_trace.extend(exec_results)

            assistant_msg = {
                "role": "assistant",
                "content": last_reply or "",
                "tool_calls": tool_calls,
            }
            messages.append(assistant_msg)
            for r in exec_results:
                content = json.dumps(r.get("data", r.get("error", "")),
                                     ensure_ascii=False, default=str)
                messages.append({
                    "role": "tool",
                    "tool_call_id": r.get("tool_call_id", "unknown"),
                    "content": content,
                })

            logger.info("子代理 step=%d 执行 %d 个工具", step + 1, len(exec_results))
        else:
            logger.warning("子代理达到最大步数 %d", self._max_steps)

        result.output = self._clean(last_reply)
        return result

    # ── 工具 schema ──

    def _build_tools_schema(self, effective_type: str | None) -> list[dict] | None:
        if effective_type in _NO_NATIVE_TOOLS:
            return None
        if self._tools_builder is not None:
            try:
                return self._tools_builder()
            except Exception as e:
                logger.warning("自定义 tools_builder 失败: %s", e)
        # 优先复用 models_plugin 的全量工具 schema（绕过 toolbox 激活流程）
        if self._models is not None and hasattr(self._models, '_build_full_schema'):
            try:
                return self._models._build_full_schema()
            except Exception as e:
                logger.warning("构建全量工具 schema 失败: %s", e)
        if self._skill_registry is not None:
            try:
                return self._skill_registry.get_tools_schema()
            except Exception as e:
                logger.warning("从 skill_registry 构建工具 schema 失败: %s", e)
        return None

    # ── 工具执行 ──

    def _execute_tool_calls(self, tool_calls: list, user_id: int,
                            chat_id: int) -> list[dict]:
        if self._skill_registry is None:
            return [{
                "function": tc.get("function", {}).get("name", "unknown"),
                "tool_call_id": tc.get("id", ""),
                "success": False,
                "error": "skill_registry 未注入，无法执行工具",
            } for tc in tool_calls]

        # 线程级调用上下文（保证并发子代理互不串扰）
        from apps.dsn.skills.context import set_call_context
        set_call_context(user_id=user_id, chat_id=chat_id)
        self._inject_system_ctx(user_id, chat_id)

        results: list[dict] = []
        for tc in tool_calls:
            func_name = tc.get("function", {}).get("name", "unknown")
            try:
                func_args = json.loads(
                    tc.get("function", {}).get("arguments", "{}"))
            except json.JSONDecodeError:
                results.append({
                    "function": func_name,
                    "tool_call_id": tc.get("id", ""),
                    "success": False,
                    "error": "JSON 解析失败",
                })
                continue

            parts = func_name.split("-", 2)
            if len(parts) < 3 or parts[0] != "skill":
                results.append({
                    "function": func_name,
                    "tool_call_id": tc.get("id", ""),
                    "success": False,
                    "error": f"无法解析工具名: {func_name}",
                })
                continue

            skill_name, tool_name = parts[1], parts[2]
            try:
                data = self._skill_registry.call_tool(
                    skill_name, tool_name, func_args)
                results.append({
                    "function": func_name,
                    "tool_call_id": tc.get("id", ""),
                    "success": True,
                    "data": data,
                })
                logger.info("子代理工具执行成功: %s", func_name)
            except Exception as e:
                logger.error("子代理工具执行失败: %s: %s", func_name, e)
                results.append({
                    "function": func_name,
                    "tool_call_id": tc.get("id", ""),
                    "success": False,
                    "error": str(e),
                })
        return results

    def _inject_system_ctx(self, user_id: int, chat_id: int) -> None:
        """把用户/会话/DB/TaskManager 注入系统工具类（与 ToolPlugin 一致）"""
        if self._skill_registry is None:
            return
        for instance in self._skill_registry._tool_instances.values():
            cls = type(instance)
            if not hasattr(cls, '_ctx'):
                continue
            cls._ctx["_uid"] = user_id
            cls._ctx["_cid"] = chat_id
            if self._task_mgr is not None:
                cls._ctx["task_manager"] = self._task_mgr
            if self._db is not None:
                cls._ctx["db"] = self._db

    # ── 工具 ──

    @staticmethod
    def _clean(reply: str) -> str:
        if not reply:
            return ""
        import re
        cleaned = re.sub(r"<text>(.*?)</text>", r"\1", reply,
                         flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"<tool>.*?</tool>", "", cleaned,
                         flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"<task>.*?</task>", "", cleaned,
                         flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"<[^>]+>", "", cleaned)
        cleaned = re.sub(r"\n{2,}", "\n", cleaned)
        return cleaned.strip()
