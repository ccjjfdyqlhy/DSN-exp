# apps/dsn_study/asr_filter.py
# ASR 输入过滤器 —— 判断这段语音该不该唤醒主模型。
#
# 为什么需要：语音输入没有"打字框"这个天然过滤器。用户在旁边说话、
# 咳嗽、看电视 —— 这些都不该把主模型叫醒并消耗一次推理。
# 过滤器先判一道：FORWARD（转发）/ HOLD（保留）。
#
# 与 apps/dsn/models/asr_filter.py 的关系：**不复用**（那边是 apps/dsn 的老实现，
# 且 `asr_filter.py:28` 用了 `Optional[...]` 却没 import typing → 导入即 NameError）。
# 本文件是按新基座重写的等价物，挂在 harness/pipeline 的 PRE_FILTER 钩子上。
#
# 契约（harness/pipeline/base.py:28）：
#   PRE_FILTER = "pre_filter"  # ASR 输入过滤（可短路）— dsn 兼容
#
# ⚠️ **fail-closed**：任何异常都判 HOLD。
#    改成 fail-open 的话，环境噪音会不断唤醒主模型 —— 一次噪音 = 一次推理。

from __future__ import annotations

import logging

logger = logging.getLogger("AsrFilter")

#: 判定输出
FORWARD = "FORWARD"
HOLD = "HOLD"

#: 过滤提示词（对齐参考实现的语义，角色名换成 dsn_study 的「小舟」）
FILTER_PROMPT = """你是一个对话过滤器，负责判断用户输入是否应该转发给主AI系统（小舟）。
请遵循以下规则：
 1. 当用户明显在与小舟对话（包含问题、请求或延续对话的内容）时，转发完整内容。
 2. 如果用户提到"小舟"、"小舟啊"或和主AI系统名字相似的发音，立即转发。
 3. 当用户使用"你"时，立即转发。
判断后只需输出"FORWARD"（转发）或"HOLD"（保留），无需解释。"""

#: 历史轮数上限（对齐参考实现 MAX_HISTORY = 20）
MAX_HISTORY = 20


class AsrFilterModel:
    """基于 LLM 的 ASR 输入过滤器。

    客户端按 duck-typing 适配（send_message / invoke / complete 任一即可），
    与 harness/personality 的做法一致 —— 不绑定具体 provider。
    """

    def __init__(self, chat=None, *, model_name: str = "",
                 temperature: float = 0.1, max_tokens: int = 10,
                 timeout: float = 30.0):
        self._chat = chat
        self.model_name = model_name
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self._history: list[dict] = []

    # ── 客户端访问 ──

    def set_chat(self, chat) -> None:
        self._chat = chat

    @property
    def available(self) -> bool:
        return self._chat is not None

    # ── 判定 ──

    def filter_input(self, user_input: str) -> str:
        """返回 FORWARD / HOLD。任何异常 → HOLD（fail-closed）。"""
        if not user_input or not user_input.strip():
            return HOLD
        if not self.available:
            # 没有过滤模型 = 不过滤 = 放行。
            # 这里与 fail-closed 的取舍不同：没有模型时「什么都不做」比
            # 「把所有语音都丢掉」更合理 —— 丢的是用户的正常说话。
            logger.debug("过滤模型不可用，放行")
            return FORWARD
        try:
            decision = self._decide(user_input)
        except Exception as exc:
            logger.warning("ASR 过滤判定失败（按 HOLD 处理）: %s", exc)
            return HOLD
        if decision not in (FORWARD, HOLD):
            logger.warning("过滤模型返回非法判定 %r（按 HOLD 处理）", decision)
            return HOLD
        return decision

    def _decide(self, user_input: str) -> str:
        """调模型判定。"""
        prompt = FILTER_PROMPT + "\n\n用户输入：" + user_input
        messages = [{"role": "system", "content": prompt}]
        messages += self._history[-MAX_HISTORY:]
        messages.append({"role": "user", "content": user_input})

        raw = self._send(messages)
        decision = (raw or "").strip().upper()
        # 模型有时会带解释，取第一个词
        for token in decision.replace("\n", " ").split():
            if token in (FORWARD, HOLD):
                decision = token
                break
        else:
            decision = HOLD

        self._history.append({"role": "user", "content": user_input})
        self._history.append({"role": "assistant", "content": decision})
        if len(self._history) > MAX_HISTORY * 2:
            self._history = self._history[-MAX_HISTORY * 2:]
        return decision

    def _send(self, messages: list[dict]) -> str:
        chat = self._chat
        if hasattr(chat, "send_message"):
            return chat.send_message(messages[-1]["content"]) or ""
        if hasattr(chat, "invoke"):
            from infra.models.base import ChatMessage
            msgs = [ChatMessage(role=m["role"], content=m["content"])
                    for m in messages]
            resp = chat.invoke(msgs, temperature=self.temperature,
                               max_tokens=self.max_tokens,
                               timeout=self.timeout)
            return resp.content or ""
        if hasattr(chat, "complete"):
            return chat.complete(messages[-1]["content"]) or ""
        raise RuntimeError("过滤模型客户端不可用（无 send_message/invoke/complete）")

    def __repr__(self) -> str:
        return "<AsrFilterModel available=%s>" % self.available
