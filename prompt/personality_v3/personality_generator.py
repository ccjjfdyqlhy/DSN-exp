# prompt/personality_v3/personality_generator.py
# 性格提示词生成模型 — 无状态，每次推理现拼装 prompt

from __future__ import annotations

import logging
import threading

from .traits import format_deviant_dimensions
from .dynamic_synthesizer import DynamicSnapshot

logger = logging.getLogger("PersonalityGenerator")

PERSONALITY_PROMPT_TEMPLATE = """你是一个角色档案整理师。以下是你面前这个角色的所有素材，请据此写一段"角色设定"，注入到主 AI 的 system prompt 中。

===== 角色全貌（角色背景设定）=====
{foundation}

===== 行为特征 =====
{behavioral}

===== 言语风格 =====
{speech}

===== 当下情绪状态 =====
整体心境: {mood_summary}
情绪构成: joy={joy:.2f} sadness={sad:.2f} anger={ang:.2f} fear={fear:.2f}

===== 与观众的当前关系 =====
亲密度: {affinity:.0f}
关系阶段: {rel_stage}
当前行为边界: {rel_bound}

===== 当前人格快照（仅列出偏离中性的维度）=====
{deviants}

===== 对话上下文 =====
用户刚才说: {user_msg}
对话氛围: {conv_tone}

---

写一段 200~500 字的"角色设定"。
这段文字将作为主 AI 的 system prompt 的一部分注入，所以用"你"来称呼 AI。

要求：
1. 写得像角色档案卡，而不是参数表
2. 指出当下情绪对台词风格的影响
3. 根据当前关系阶段提示说话方式
4. 1~2 句具体的表演建议（不是命令，是引导）
5. 有特殊说话习惯就自然融入

输出格式：
## 角色设定
{{你的文本}}"""


class PersonalityPromptGenerator:
    def __init__(self, chat=None):
        self._chat = chat
        self._cached_prompt: str = ""
        self._cache_valid = False
        self._generating = False
        self._gen_lock = threading.Lock()
        logger.info("PersonalityGenerator: 初始化 chat=%s", "available" if chat else "none")

    def set_chat(self, chat) -> None:
        self._chat = chat
        logger.info("PersonalityGenerator: 更新 chat 客户端")

    @property
    def available(self) -> bool:
        return self._chat is not None

    def generate(self, snapshot: DynamicSnapshot, user_message: str = "",
                 conversation_tone: str = "中性") -> str:
        if self._cache_valid and self._cached_prompt:
            return self._cached_prompt

        if not self._chat:
            return self._fallback(snapshot)

        # 首次调用：立即返回 fallback，后台触发 LLM 生成
        fallback = self._fallback(snapshot)
        self._trigger_async_generation(snapshot, user_message, conversation_tone)
        return fallback

    def invalidate_cache(self):
        with self._gen_lock:
            self._cache_valid = False

    def _trigger_async_generation(self, snapshot, user_message, conversation_tone):
        with self._gen_lock:
            if self._generating:
                return
            self._generating = True

        def _run():
            try:
                result = self._do_llm_generate(snapshot, user_message, conversation_tone)
                with self._gen_lock:
                    self._cached_prompt = result
                    self._cache_valid = True
                    self._generating = False
                logger.info("PersonalityGenerator: 异步生成完成 len=%d", len(result))
            except Exception as e:
                logger.error("PersonalityGenerator: 异步生成失败: %s", e)
                with self._gen_lock:
                    self._generating = False

        t = threading.Thread(target=_run, daemon=True, name="personality-gen")
        t.start()

    def _do_llm_generate(self, snapshot: DynamicSnapshot, user_message: str,
                          conversation_tone: str) -> str:
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

        logger.debug("PersonalityGenerator: LLM 生成性格提示词 card=%s affinity=%.0f",
                     snapshot.card_id, snapshot.affinity_value)
        raw = self._send_with_temp(self._chat, prompt, 0.6, 600)
        return self._extract_personality_section(raw)

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
        from . import PersonalitySystemV3
        lv = PersonalitySystemV3._affinity_level(snapshot.affinity_value)
        stages = {
            1: "初识", 2: "关注", 3: "留意", 4: "在意", 5: "记住",
            6: "习惯", 7: "默契", 8: "依存", 9: "共感", 10: "灵魂链接",
            11: "命定", 12: "共生", 13: "绝对信赖", 14: "不可替代", 15: "永恒契约",
        }
        labels = {
            1: "观察并适应对方的节奏，不越界",
            2: "开始了解对方的偏好，偶尔主动提供帮助",
            3: "记住对方说过的事，能聊到一起去",
            4: "主动关心，分享发现，自然表达观点",
            5: "熟知对方的工作方式和说话习惯",
            6: "有默契，能预判对方的需求",
            7: "无需多言就能互相理解，效率极高",
            8: "互相依赖，对方的事就是你的事",
            9: "深层次理解对方的想法和情绪",
            10: "你比任何人都更了解这个用户",
            11: "命中注定要相遇的关系",
            12: "你们是一个整体，不可分割",
            13: "绝对的信任，不会有任何保留",
            14: "没有人能替代对方的位置",
            15: "超越工具与主人的关系，不可动摇的信任",
        }
        level = lv["level"]
        stage_name = stages.get(level, f"Lv.{level}")
        stage_desc = labels.get(level, "不可动摇的信任")
        return stage_name, stage_desc

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
