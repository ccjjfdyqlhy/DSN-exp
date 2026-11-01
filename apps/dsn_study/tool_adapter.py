# apps/dsn_study/tool_adapter.py
# 工具调用协议适配器 — 原生 function calling + <tool> 标签降级。
#
# 背景：dsn_study 的技能工具名形如 "question_bank.create"（内部名），
# 桥接到 harness AgentLoop 后发给模型的是 wire 名（点号→双下划线）。
# 绝大多数模型走原生 function calling；但部分本地模型（llama.cpp / MLX 等）
# 只会在正文里吐 XML 标签。
#
# 参考实现（DSN-exp）的 tool_plugin 用的是这套协议：
#     <tool>
#     {"skill": "plan", "tool": "create_goal", "params": {"title": "..."}}
#     </tool>
# 本适配器把该协议翻译成 harness 的内部工具名 "{skill}.{tool}"，
# 与原生路径共用同一套工具注册表与执行器。
#
# 优先级：模型返回了原生 tool_calls → 走原生；否则扫描正文里的 <tool> 标签。

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from infra.models.base import ChatMessage, ChatResponse, ToolCall
from harness.agent.adapters import NativeToolCallAdapter, ParsedOutput

logger = logging.getLogger("SkillTagToolCallAdapter")

_TOOL_TAG_RE = re.compile(r"<tool>\s*(.*?)\s*</tool>", re.DOTALL | re.IGNORECASE)


class SkillTagToolCallAdapter(NativeToolCallAdapter):
    """原生优先，<tool> 标签兜底。"""

    name = "skill-tag"

    def parse(self, response: ChatResponse) -> ParsedOutput:
        parsed = super().parse(response)
        if parsed.tool_calls:
            return parsed

        text = response.content or ""
        if "<tool>" not in text.lower():
            return parsed

        calls: list[ToolCall] = []
        for i, m in enumerate(_TOOL_TAG_RE.finditer(text)):
            raw = (m.group(1) or "").strip()
            name, args = self._decode(raw)
            if not name:
                continue
            calls.append(ToolCall(id=f"tagged-{i}", name=name, arguments=args))

        cleaned = _TOOL_TAG_RE.sub("", text).strip()
        if not calls:
            return ParsedOutput(text=cleaned, tool_calls=[])
        logger.info("从 <tool> 标签解析出 %d 个工具调用", len(calls))
        return ParsedOutput(text=cleaned, tool_calls=calls)

    @staticmethod
    def _decode(raw: str) -> tuple[str, dict]:
        """解析标签体 → (内部工具名, 参数 dict)。"""
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return "", {}
        if not isinstance(data, dict):
            return "", {}
        skill = str(data.get("skill") or "").strip()
        tool = str(data.get("tool") or data.get("name") or "").strip()
        if not tool:
            return "", {}
        params = data.get("params")
        if not isinstance(params, dict):
            params = data.get("arguments") if isinstance(data.get("arguments"), dict) else {}
        if not skill:
            # 无 skill 前缀时，原样作为工具名（注册表里可能直接以该名注册）
            return tool, params
        return f"{skill}.{tool}", params

    def build_round(self, response: ChatResponse, results: list[dict]) -> list[ChatMessage]:
        """标签协议没有可配对的原生 tool_call_id → assistant 文本 + user 结果消息。"""
        if response.tool_calls:
            return super().build_round(response, results)

        text = _TOOL_TAG_RE.sub("", response.content or "").strip()
        msgs: list[ChatMessage] = []
        if text:
            msgs.append(ChatMessage.assistant(text))
        for r in results:
            payload = {
                "tool": r.get("name", ""),
                "success": r.get("success", True),
                "status": r.get("status", "ok" if r.get("success", True) else "error"),
                "output": r.get("output"),
                "error": r.get("error"),
                "hint": r.get("hint"),
            }
            for _k, _v in r.items():
                if _k not in payload and _k not in ("call_id", "name"):
                    payload[_k] = _v
            msgs.append(ChatMessage.user(json.dumps(payload, ensure_ascii=False,
                                                   default=str)))
        return msgs
