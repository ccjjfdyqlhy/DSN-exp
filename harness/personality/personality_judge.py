# prompt/personality_v3/personality_judge.py
# 性格判定模型 — 无状态，每次推理现拼装 prompt。
# 职责: 把用户消息分类为结构化事件 (PerceptionRecord)，不含任何数值。
# 所有数值演化由 dynamics_engine 确定性完成。

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from .events import (
    PerceptionRecord,
    EVENT_TYPES,
    EVENT_THANKS,
    EVENT_PRAISE,
    EVENT_CONFLICT,
    EVENT_VENTING,
    EVENT_SILENCE,
    EVENT_PERSONAL_SHARING,
    EVENT_NEUTRAL,
    INTENSITY_MEDIUM,
)

logger = logging.getLogger("PersonalityJudge")


JUDGE_PROMPT_TEMPLATE = """你是一个角色情绪分析专家。你要把用户的消息分类为"事件"，供角色动力学引擎推演情绪与关系变化。

判定规则——请严格遵循：

1. 【只分析用户对 AI 的影响】下面的【用户】是用户的发言，【AI 的回复】只是给你看 AI 选择了怎样回应用户——这是 AI 情绪状态的"结果"，不是事件的判断依据。你需要判断的是：用户这条消息在角色视角下是什么性质的事件。

2. 【必须看上下文理解意图】请看【对话上下文】中最近几轮的对话，理解话题和气氛。不要把用户随口说的"烦死了这个 bug"分类成对 AI 发火——用户可能只是在抱怨自己遇到的问题（这是 venting）。

3. 【分类要克制】大多数普通对话轮次属于 neutral。只有用户明确表达情感/意图时，才选择具体事件类型。

===== 事件类型枚举 =====
{event_types}

===== 角色背景（AI 角色的性格设定）=====
{character_brief}

===== 对话上下文（最近几轮对话，帮助你理解话题和气氛）=====
{conversation_history}

===== 当前情绪状态 =====
开心(joy): {prev_joy:.2f} | 悲伤(sadness): {prev_sad:.2f} | 愤怒(anger): {prev_ang:.2f} | 恐惧(fear): {prev_fear:.2f}
累计互动: 第 {interaction_count} 轮 | 当前亲密度: {prev_affinity:.0f}

===== 【用户】本轮说的话 =====
{user_message}

===== 【AI 的回复】——仅供参考，不用于事件分类 =====
{ai_reply}

===== 角色情绪触发模式 =====
{emotional_triggers}

===== 关系动力学 =====
{relation_dynamics}

---

请输出 JSON（只输出 JSON，不要其他文字）：
{{
  "event_type": "<枚举之一>",
  "intensity": "low | medium | high",
  "valence": "positive | neutral | negative",
  "attribution": "简短说明用户此举的动机或意图",
  "analysis": "分析：用户说了什么→这在角色视角下是什么事件→为何归为此类（不是分析AI回复的内容）"
}}"""


@dataclass
class MoodUpdateResult:
    """动力学引擎的推演结果（由 dynamics_engine 构造）。"""

    old_mood: dict[str, float]
    new_mood: dict[str, float]
    old_affinity: float
    new_affinity: float
    analysis: str = ""
    affinity_reason: str = ""
    behavioral_advice: str = ""
    new_level_description: str = ""
    affinity_delta: float = 0.0
    mood_delta: dict[str, float] = field(default_factory=dict)
    rule_id: str = ""


class PersonalityJudge:
    def __init__(self, chat=None):
        self._chat = chat
        logger.info("PersonalityJudge: 初始化 chat=%s", "available" if chat else "none")

    def set_chat(self, chat) -> None:
        self._chat = chat
        logger.info("PersonalityJudge: 更新 chat 客户端")

    @property
    def available(self) -> bool:
        return self._chat is not None

    def classify(
        self,
        user_message: str,
        ai_reply: str,
        previous_mood: dict[str, float] | None = None,
        previous_affinity: float = 20.0,
        interaction_count: int = 0,
        character_brief: str = "",
        emotional_triggers: str = "",
        relation_dynamics: str = "",
        conversation_history: str = "",
    ) -> PerceptionRecord:
        prev = dict(previous_mood or {"joy": 0.5, "sadness": 0.2, "anger": 0.1, "fear": 0.15})

        if not self._chat:
            logger.info("PersonalityJudge: 模型不可用，使用启发式分类")
            return self._heuristic_classify(user_message)

        prompt = JUDGE_PROMPT_TEMPLATE.format(
            event_types="\n".join(f"- {t}" for t in EVENT_TYPES),
            character_brief=character_brief[:1200] or "（无）",
            conversation_history=conversation_history or "（尚无对话历史）",
            prev_joy=prev.get("joy", 0.5),
            prev_sad=prev.get("sadness", 0.2),
            prev_ang=prev.get("anger", 0.1),
            prev_fear=prev.get("fear", 0.15),
            prev_affinity=previous_affinity,
            user_message=user_message[:800],
            ai_reply=ai_reply[:500],
            interaction_count=interaction_count,
            emotional_triggers=emotional_triggers or "（无）",
            relation_dynamics=relation_dynamics or "（无）",
        )

        logger.debug("PersonalityJudge: 调用性格模型分类 round=%d affinity=%.0f",
                     interaction_count, previous_affinity)

        try:
            raw = self._send_with_temp(self._chat, prompt, 0.3, 400)
            data = self._parse_json_response(raw)
            if "event_type" in data:
                record = PerceptionRecord(
                    event_type=str(data.get("event_type", EVENT_NEUTRAL)),
                    intensity=str(data.get("intensity", INTENSITY_MEDIUM)),
                    valence=str(data.get("valence", "neutral")),
                    attribution=str(data.get("attribution", "")),
                    analysis=str(data.get("analysis", "")),
                )
                logger.debug("PersonalityJudge: 分类结果 %s/%s", record.event_type, record.intensity)
                return record
            logger.warning("PersonalityJudge: 响应缺少 event_type，回退启发式")
        except Exception as e:
            logger.error("PersonalityJudge: 模型调用失败，回退到启发式: %s", e)
        return self._heuristic_classify(user_message)

    # 兼容旧名
    analyze = classify

    @staticmethod
    def _send_with_temp(chat, prompt: str, temperature: float, max_tokens: int) -> str:
        old_temp = getattr(chat, 'temperature', None)
        old_max = getattr(chat, 'max_tokens', None)
        try:
            if hasattr(chat, 'temperature'):
                chat.temperature = temperature
            if hasattr(chat, 'max_tokens'):
                chat.max_tokens = max_tokens
            if hasattr(chat, 'send_message'):
                return chat.send_message(prompt)
            if hasattr(chat, 'invoke'):
                from harness.models.base import ChatMessage
                resp = chat.invoke([ChatMessage(role="user", content=prompt)], temperature=temperature, max_tokens=max_tokens)
                return resp.content or ""
            if hasattr(chat, 'complete'):
                from harness.models.base import ChatMessage
                resp = chat.complete([ChatMessage(role="user", content=prompt)])
                return resp.content or ""
            return ""
        finally:
            if old_temp is not None and hasattr(chat, 'temperature'):
                chat.temperature = old_temp
            if old_max is not None and hasattr(chat, 'max_tokens'):
                chat.max_tokens = old_max

    @staticmethod
    def _heuristic_classify(user_message: str) -> PerceptionRecord:
        """无模型时的启发式分类 —— 只输出事件，不产生数值。"""
        msg = user_message.lower().strip()
        msg_len = len(user_message)

        if any(w in msg for w in ("谢谢", "感谢", "多谢", "太棒了", "辛苦啦", "非常感谢")):
            return PerceptionRecord(EVENT_THANKS, INTENSITY_MEDIUM, "positive",
                                    attribution="用户致谢", analysis="启发式判定: 感谢")
        if any(w in msg for w in ("厉害", "聪明", "强", "牛", "好棒", "真棒", "优秀")):
            return PerceptionRecord(EVENT_PRAISE, INTENSITY_MEDIUM, "positive",
                                    attribution="用户夸赞", analysis="启发式判定: 夸赞")
        badwords = ("sb", "傻逼", "cnm", "操你", "fuck", "去死", "废物", "滚", "混蛋")
        if any(w in msg for w in badwords):
            return PerceptionRecord(EVENT_CONFLICT, "high", "negative",
                                    attribution="用户攻击性表达", analysis="启发式判定: 冲突")
        ventwords = ("烦死了", "崩溃", "难受", "好烦", "压力", "累死了", "心累", "唉", "焦虑")
        if any(w in msg for w in ventwords):
            return PerceptionRecord(EVENT_VENTING, INTENSITY_MEDIUM, "neutral",
                                    attribution="用户在发泄自己的情绪", analysis="启发式判定: 用户抱怨自己的问题")
        if msg_len < 5:
            return PerceptionRecord(EVENT_SILENCE, "low", "neutral",
                                    attribution="极简回应", analysis="启发式判定: 简短回应")
        if msg_len > 200:
            return PerceptionRecord(EVENT_PERSONAL_SHARING, INTENSITY_MEDIUM, "positive",
                                    attribution="用户长段分享", analysis="启发式判定: 长段分享/深入沟通")
        return PerceptionRecord(EVENT_NEUTRAL, INTENSITY_MEDIUM, "neutral",
                                attribution="", analysis="启发式判定: 普通对话")

    @staticmethod
    def _parse_json_response(raw: str) -> dict:
        raw = raw.strip()
        match = re.search(r'```(?:json)?\s*\n?(.*?)```', raw, re.DOTALL)
        if match:
            raw = match.group(1).strip()
        else:
            # 尝试提取第一个形如 { ... } 的 JSON 块
            brace_match = re.search(r'\{.*\}', raw, re.DOTALL)
            if brace_match:
                raw = brace_match.group(0).strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("PersonalityJudge: JSON 解析失败，原始响应前100字符: %s", raw[:100])
            return {}
