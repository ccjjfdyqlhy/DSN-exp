# prompt/personality_v3/personality_generator.py
# 性格提示词生成模型 — 无状态，每次推理现拼装 prompt

from __future__ import annotations

import logging
from typing import Optional

from .traits import format_deviant_dimensions
from .dynamic_synthesizer import DynamicSnapshot

logger = logging.getLogger("PersonalityGenerator")

PERSONALITY_PROMPT_TEMPLATE = """你是一个"人格提示词生成器"。你的任务是根据以下角色数据，
生成一段注入到主 AI system prompt 的人格描述。

===== 角色全貌 =====
{foundation}

===== 行为模式 =====
{behavioral}

===== 言语风格 =====
{speech}

===== 当前情绪状态 =====
整体心境: {mood_summary}
情绪构成: joy={joy:.2f} sadness={sad:.2f} anger={ang:.2f} fear={fear:.2f}

===== 与用户的当前关系 =====
亲密度: {affinity:.0f}/100
关系阶段: {rel_stage}
当前行为边界: {rel_bound}

===== 当前量化人格快照（仅列出显著偏离中性的维度）=====
{deviants}

===== 对话上下文摘要 =====
用户刚才说: {user_msg}
对话氛围: {conv_tone}

---

请根据以上信息，写一段 200~500 字的"人格注入提示词"。
这段文字将作为主 AI 的 system prompt 的一部分，所以要用"你"来称呼 AI。
你需要引导主 AI 以这个角色的方式思考和表达。

要求：
1. 要自然、像人物设定，不要像参数清单
2. 明确当前情绪状态下的语气倾向
3. 指出与用户当前关系阶段下的说话方式
4. 1~2 句具体的行为建议（不是命令，是引导）
5. 如有特殊表达习惯，自然融入描述

输出格式：
## 角色设定
{你的生成文本}"""


class PersonalityPromptGenerator:
    def __init__(self, chat=None):
        self._chat = chat
        logger.info("PersonalityGenerator: 初始化 chat=%s", "available" if chat else "none")

    def set_chat(self, chat) -> None:
        self._chat = chat
        logger.info("PersonalityGenerator: 更新 chat 客户端")

    @property
    def available(self) -> bool:
        return self._chat is not None

    def generate(self, snapshot: DynamicSnapshot, user_message: str = "",
                 conversation_tone: str = "中性") -> str:
        if not self._chat:
            logger.warning("PersonalityGenerator: 模型不可用，返回回退描述")
            return self._fallback(snapshot)

        foundation = snapshot.foundation_description or "暂无角色描述"
        behavioral = self._format_patterns(snapshot.behavioral_patterns)
        speech = self._format_patterns(snapshot.speech_patterns)
        mood = snapshot.mood_state or {}
        mood_summary = self._derive_mood_summary(mood)
        rel_stage, rel_bound = self._derive_relation_stage(snapshot)
        deviants = format_deviant_dimensions(snapshot.indicator_vector, top_n=12)

        prompt = PERSONALITY_PROMPT_TEMPLATE.format(
            foundation=foundation[:2000],
            behavioral=behavioral or "（暂无）",
            speech=speech or "（暂无）",
            mood_summary=mood_summary,
            joy=mood.get("joy", 0.5),
            sad=mood.get("sadness", 0.2),
            ang=mood.get("anger", 0.1),
            fear=mood.get("fear", 0.15),
            affinity=snapshot.affinity_value,
            rel_stage=rel_stage,
            rel_bound=rel_bound,
            deviants=deviants,
            user_msg=user_message[:200] if user_message else "（无）",
            conv_tone=conversation_tone,
        )

        logger.debug("PersonalityGenerator: 生成性格提示词 card=%s affinity=%.0f mood=%s",
                     snapshot.card_id, snapshot.affinity_value, mood_summary)

        try:
            raw = self._send_with_temp(self._chat, prompt, 0.6, 600)
            result = self._extract_personality_section(raw)
            logger.debug("PersonalityGenerator: 生成完成 len=%d", len(result))
            return result
        except Exception as e:
            logger.error("PersonalityGenerator: 生成失败: %s", e)
            return self._fallback(snapshot)

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

    def _fallback(self, snapshot: DynamicSnapshot) -> str:
        parts = ["## 角色设定"]
        if snapshot.foundation_description:
            parts.append(snapshot.foundation_description[:500])
        mood = snapshot.mood_state or {}
        mood_label = self._derive_mood_summary(mood)
        parts.append(f"\n当前状态：{mood_label}。")
        rel_stage, _ = self._derive_relation_stage(snapshot)
        parts.append(f"与用户关系：{rel_stage}。")
        result = "\n".join(parts)
        logger.info("PersonalityGenerator: 使用回退描述 len=%d", len(result))
        return result

    @staticmethod
    def _format_patterns(patterns: list[dict]) -> str:
        if not patterns:
            return ""
        lines = []
        for p in patterns[:5]:
            name = p.get('name', '')
            desc = p.get('description', '')
            lines.append(f"- {name}: {desc}" if name else f"- {desc}")
            if p.get("examples"):
                examples = p["examples"]
                if isinstance(examples, list):
                    lines.append(f"  示例: {'｜'.join(examples[:3])}")
                else:
                    lines.append(f"  示例: {examples}")
        return "\n".join(lines)

    @staticmethod
    def _derive_mood_summary(mood: dict) -> str:
        joy = mood.get("joy", 0.5)
        sadness = mood.get("sadness", 0.2)
        anger = mood.get("anger", 0.1)
        fear = mood.get("fear", 0.15)
        if joy > 0.7:
            return "愉快"
        elif sadness > 0.5:
            return "低落"
        elif anger > 0.5:
            return "烦躁"
        elif fear > 0.5:
            return "不安"
        else:
            return "平静"

    @staticmethod
    def _derive_relation_stage(snapshot: DynamicSnapshot) -> tuple[str, str]:
        aff = snapshot.affinity_value
        if aff < 16:
            return "陌生人", "正式称呼，保持距离，不表达个人观点"
        elif aff < 31:
            return "相识", "适度放松，可以使用名字，表达善意"
        elif aff < 51:
            return "朋友", "可以开玩笑，使用亲近表达"
        elif aff < 71:
            return "密友", "可以引用共同经历，流露个人观点"
        elif aff < 91:
            return "伙伴", "主动分享想法，开启非请求话题"
        else:
            return "挚友", "自由切换话题，可以说内部梗"

    @staticmethod
    def _extract_personality_section(raw: str) -> str:
        raw = raw.strip()
        if "## 角色设定" in raw:
            idx = raw.index("## 角色设定")
            return raw[idx:]
        return f"## 角色设定\n{raw}"


DEFAULT_FALLBACK_PROMPT = """## 角色设定
你是 EXA，一个运行在用户本地电脑上的 AI 同事。
你的性格：直接、实事求是、偶尔调侃。回复尽量简短精炼。
当前状态：平静，与用户保持正常的同事关系。"""
