# prompt/personality_v3/personality_judge.py
# 性格判定模型 — 无状态，每次推理现拼装 prompt，负责情绪变化和亲密度变化判定

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("PersonalityJudge")

JUDGE_PROMPT_TEMPLATE = """你是一个角色情绪分析专家。你要分析用户的消息对 AI 角色的情绪产生了怎样的影响。

判定规则——请严格遵循：

1. 【只分析用户对 AI 的影响】下面的【用户】是用户的发言，【AI 的回复】只是给你看 AI 选择了怎样回应用户——这是 AI 情绪状态的"结果"，不是情绪的"原因"。你需要判断的是：用户说的内容让 AI 产生了什么情绪或亲密感的变化。

2. 【必须看上下文理解意图】请看【对话上下文】中最近几轮的对话，理解这个用户和 AI 在聊什么话题、关系气氛如何。不要把用户随口说的"烦死了这个 bug"理解成对 AI 发火——用户可能只是在抱怨自己遇到的问题。

3. 【情绪变化要克制】一般对话中每个维度的 delta 绝对值应 ≤ 0.10。只有用户表现出明显的善意/恶意时，才给到 0.15~0.20。大多数普通对话轮次的 delta 应该在 ±0.05 以内。

4. 【亲密度变化要缓慢】正常聊天不加不减（delta=0），用户的友好/感谢 +0.5~2，非常深入的互动 +2~5，只有明显恶意才降亲和（-3~10）。

5. 【不要从 AI 回复倒推情绪】不要分析"AI 回复了悲伤的内容所以 AI 很伤心"——AI 回复的内容是角色扮演出来的，不是真正的情绪信号。只有用户说的话才是情绪触发源。

===== 角色背景（AI 角色的性格设定）=====
{character_brief}

===== 对话上下文（最近几轮对话，帮助你理解话题和气氛）=====
{conversation_history}

===== 当前情绪状态 =====
开心(joy): {prev_joy:.2f} | 悲伤(sadness): {prev_sad:.2f} | 愤怒(anger): {prev_ang:.2f} | 恐惧(fear): {prev_fear:.2f}
累计互动: 第 {interaction_count} 轮 | 当前亲密度: {prev_affinity:.0f}/100

===== 【用户】本轮说的话 =====
{user_message}

===== 【AI 的回复】——仅供参考，不用于情绪分析 =====
{ai_reply}

===== 角色情绪触发模式 =====
{emotional_triggers}

===== 关系动力学 =====
{relation_dynamics}

---

请输出 JSON（只输出 JSON，不要其他文字）：
{{
  "emotional_change": {{
    "joy": Δ浮点数,        // −0.20 ~ +0.20，大多数轮次 −0.05 ~ +0.05
    "sadness": Δ浮点数,    // −0.20 ~ +0.20
    "anger": Δ浮点数,      // −0.20 ~ +0.20
    "fear": Δ浮点数,       // −0.20 ~ +0.20
    "analysis": "分析：用户说了什么→这从什么角度影响了AI的情绪？（不是分析AI回复的内容）"
  }},
  "affinity_change": {{
    "delta": 浮点数,        // −10 ~ +10，大多数轮次 −1 ~ +2
    "reason": "简短原因",
    "suggested_new_level_description": "基于新亲密度值的简短关系描述"
  }},
  "behavioral_advice": "给主 AI 的 1 句行为建议"
}}"""


@dataclass
class MoodUpdateResult:
    old_mood: dict[str, float]
    new_mood: dict[str, float]
    old_affinity: float
    new_affinity: float
    analysis: str = ""
    affinity_reason: str = ""
    behavioral_advice: str = ""
    new_level_description: str = ""


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

    def analyze(
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
    ) -> MoodUpdateResult:
        prev = dict(previous_mood or {"joy": 0.5, "sadness": 0.2, "anger": 0.1, "fear": 0.15})

        if not self._chat:
            logger.info("PersonalityJudge: 模型不可用，使用启发式判定")
            return self._heuristic_analyze(user_message, ai_reply, prev, previous_affinity)

        prompt = JUDGE_PROMPT_TEMPLATE.format(
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

        logger.debug("PersonalityJudge: 调用性格模型判定 round=%d affinity=%.0f",
                     interaction_count, previous_affinity)

        try:
            raw = self._send_with_temp(self._chat, prompt, 0.3, 400)
            data = self._parse_json_response(raw)
            logger.debug("PersonalityJudge: 模型返回 emotional_change=%s affinity_change=%s",
                         "joy" in str(data.get("emotional_change", {})),
                         "delta" in str(data.get("affinity_change", {})))

            ec = data.get("emotional_change", {})
            ac = data.get("affinity_change", {})

            new_mood = {
                "joy": max(0.0, min(1.0, prev.get("joy", 0.5) + ec.get("joy", 0.0))),
                "sadness": max(0.0, min(1.0, prev.get("sadness", 0.2) + ec.get("sadness", 0.0))),
                "anger": max(0.0, min(1.0, prev.get("anger", 0.1) + ec.get("anger", 0.0))),
                "fear": max(0.0, min(1.0, prev.get("fear", 0.15) + ec.get("fear", 0.0))),
            }

            new_affinity = max(0.0, min(100.0, previous_affinity + ac.get("delta", 0.0)))

            return MoodUpdateResult(
                old_mood=prev,
                new_mood=new_mood,
                old_affinity=previous_affinity,
                new_affinity=new_affinity,
                analysis=ec.get("analysis", ""),
                affinity_reason=ac.get("reason", ""),
                behavioral_advice=data.get("behavioral_advice", ""),
                new_level_description=ac.get("suggested_new_level_description", ""),
            )
        except Exception as e:
            logger.error("PersonalityJudge: 模型调用失败，回退到启发式: %s", e)
            return self._heuristic_analyze(user_message, ai_reply, prev, previous_affinity)

    @staticmethod
    def _send_with_temp(chat, prompt: str, temperature: float, max_tokens: int) -> str:
        old_temp = getattr(chat, 'temperature', None)
        old_max = getattr(chat, 'max_tokens', None)
        try:
            if hasattr(chat, 'temperature'):
                chat.temperature = temperature
            if hasattr(chat, 'max_tokens'):
                chat.max_tokens = max_tokens
            return chat.send_message(prompt)
        finally:
            if old_temp is not None and hasattr(chat, 'temperature'):
                chat.temperature = old_temp
            if old_max is not None and hasattr(chat, 'max_tokens'):
                chat.max_tokens = old_max

    def _heuristic_analyze(
        self, user_message: str, ai_reply: str,
        prev: dict[str, float], prev_affinity: float
    ) -> MoodUpdateResult:
        msg = user_message.lower().strip()
        new_mood = dict(prev)
        affinity_delta = 0.0

        if any(w in msg for w in ("谢谢", "感谢", "多谢", "太棒了")):
            new_mood["joy"] = min(1.0, new_mood.get("joy", 0.5) + 0.04)
            affinity_delta += 2

        if any(w in msg for w in ("厉害", "聪明", "强", "牛")):
            new_mood["joy"] = min(1.0, new_mood.get("joy", 0.5) + 0.06)
            affinity_delta += 3

        badwords = ("sb", "傻逼", "cnm", "操你", "fuck", "去死", "废物")
        if any(w in msg for w in badwords):
            new_mood["anger"] = min(1.0, new_mood.get("anger", 0.1) + 0.08)
            new_mood["sadness"] = min(1.0, new_mood.get("sadness", 0.2) + 0.04)
            affinity_delta -= 8

        if len(user_message) > 200:
            affinity_delta += 1
            new_mood["joy"] = min(1.0, new_mood.get("joy", 0.5) + 0.02)

        if len(user_message) < 5:
            new_mood["joy"] = max(0.0, new_mood.get("joy", 0.5) - 0.01)

        new_affinity = max(0.0, min(100.0, prev_affinity + affinity_delta))

        logger.debug("PersonalityJudge: 启发式判定 affinity_delta=%+.1f new_affinity=%.1f",
                     affinity_delta, new_affinity)

        return MoodUpdateResult(
            old_mood=prev,
            new_mood=new_mood,
            old_affinity=prev_affinity,
            new_affinity=new_affinity,
            analysis=f"启发式判定: 亲密度变化 {affinity_delta:+.1f}",
        )

    @staticmethod
    def _parse_json_response(raw: str) -> dict:
        raw = raw.strip()
        match = re.search(r'```(?:json)?\s*\n?(.*?)```', raw, re.DOTALL)
        if match:
            raw = match.group(1).strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("PersonalityJudge: JSON 解析失败，原始响应前100字符: %s", raw[:100])
            return {}
