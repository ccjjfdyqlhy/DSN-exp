# prompt/personality_v3/distillation_engine.py
# 蒸馏引擎 — 4-Pass 将角色卡材料提炼为蒸馏产物

from __future__ import annotations

import json
import logging
import time
import re
from datetime import datetime, timezone
from typing import Optional

from .character_card import CharacterCard
from .traits import ALL_DIMENSIONS, TRAIT_IDS

logger = logging.getLogger("DistillationEngine")


PASS1_GLOBAL_UNDERSTANDING = """你是一个角色分析师。请仔细阅读以下材料，然后写一段角色全貌描述。

要求：
1. 用自然语言描述这个角色，像写人物简介一样
2. 必须涵盖：核心性格、行为模式、说话风格、价值观、情绪特质
3. 特别关注经历描述中的因果链条——角色的性格是怎样形成的
4. 识别角色最核心的性格矛盾或复杂性
5. 描述亲密度变化方式——角色如何与不同距离的人相处
6. 600~2000 字，中文

===== 角色卡自然语言描述 =====
{card_nl}

===== 经历描述 =====
{experiences_text}

===== 语料素材 =====
{corpus_text}

===== 用户额外提示 =====
{user_notes}

请输出角色全貌描述："""


PASS2_FEATURE_EXTRACTION = """你是一个角色分析师。基于以下角色全貌描述和原始材料，请提取系统化的特征。

===== 角色全貌描述 =====
{foundation}

===== 原始材料摘要 =====
{materials_summary}

请以 JSON 格式输出，包含以下字段：

1. "behavioral_patterns": 行为模式列表
   - 每条包含: "id"(如bp_1), "name", "description", "triggers"(触发场景列表)
   - 至少 5 条，体现角色在压力/放松/社交中的不同行为

2. "speech_patterns": 言语模式列表
   - 每条包含: "id"(如sp_1), "name", "description", "examples"(示例列表)
   - 涵盖口头禅、句式偏好、修辞习惯、禁忌用语
   - 至少 5 条

3. "emotional_model": 情绪反应模型描述
   - "description": 整体描述
    - "triggers": 数组，每个元素 {{"stimulus": 触发情景, "response": 反应, "intensity": 强度0~1, "recovery": "fast"/"medium"/"slow"}}

4. "relational_model": 关系动态模型
    - "description": 整体描述
    - "stages": 数组，每个元素 {{"level": 0, "label": 阶段名, "description": 行为描述}}
   - 从陌生到亲密的渐进过程，至少 4 个阶段

5. "trait_narrative": 性格维度自然语言描述
   - 对以下 8 个大类各写 1~3 段描述字符串
   - A_core_disposition, B_emotional, C_cognitive, D_social, E_speech, F_values, G_relationships, H_behavioral
   - 要自然语言，不要列数字

只输出 JSON，不要有其他文字。"""


PASS3_QUANTIZATION = """你是一个性格测量专家。基于提供的角色材料，请为以下 50 个维度每个给出一个 0.00~1.00 的浮点值。

评分要求：
1. 每个值精确到小数点后两位
2. 每个值后面给出单句推论理由
3. 如果材料中没有直接相关的内容，基于角色整体形象合理推断
4. 注意维度之间的逻辑一致性（例如话量高和外向性高应该大致吻合）
5. 大部分维度的值应该在 0.2~0.8 之间，只有极少数极端值 <0.1 或 >0.9

===== 角色全貌描述 =====
{foundation}

===== 特征描述 =====
{features_text}

===== 需要评分的维度 =====
{dimensions_text}

===== 用户手动覆盖（已指定的维度直接填用户值，理由写"用户手动指定"）=====
{manual_overrides_text}

请以 JSON 数组输出，每个元素:
{{"id": "A1", "value": 0.72, "reasoning": "角色对新鲜事物持谨慎开放态度，愿意尝试但不冲动"}}

只输出 JSON 数组，不要有其他文字。"""


class DistilledTraits:
    def __init__(self, data: dict):
        self.distillation_id: str = data.get("distillation_id", "")
        self.card_id: str = data.get("card_id", "")
        self.version: int = data.get("version", 1)
        self.content_fingerprint: str = data.get("content_fingerprint", "")
        self.model_used: str = data.get("model_used", "")
        self.created_at: str = data.get("created_at", "")

        self.foundation_description: str = data.get("foundation_description", "")

        self.behavioral_patterns: list[dict] = data.get("behavioral_patterns", [])
        self.speech_patterns: list[dict] = data.get("speech_patterns", [])
        self.emotional_model: dict = data.get("emotional_model", {})
        self.relational_model: dict = data.get("relational_model", {})
        self.indicator_vector: dict[str, float] = data.get("indicator_vector", {})
        self.trait_narrative: dict[str, str] = data.get("trait_narrative", {})

    def to_dict(self) -> dict:
        return {
            "distillation_id": self.distillation_id,
            "card_id": self.card_id,
            "version": self.version,
            "content_fingerprint": self.content_fingerprint,
            "model_used": self.model_used,
            "created_at": self.created_at,
            "foundation_description": self.foundation_description,
            "behavioral_patterns": self.behavioral_patterns,
            "speech_patterns": self.speech_patterns,
            "emotional_model": self.emotional_model,
            "relational_model": self.relational_model,
            "indicator_vector": self.indicator_vector,
            "trait_narrative": self.trait_narrative,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


class DistillationEngine:
    def __init__(self, main_chat=None, fast_chat=None):
        """
        :param main_chat: DeepSeekChat 实例，用于蒸馏（推荐 DeepSeek API）
        :param fast_chat: 备用 LMStudioChat 实例
        """
        self._main_chat = main_chat
        self._fast_chat = fast_chat

    def set_chats(self, main_chat=None, fast_chat=None) -> None:
        if main_chat:
            self._main_chat = main_chat
        if fast_chat:
            self._fast_chat = fast_chat

    def run(self, card: CharacterCard, user_notes: str = "",
            model_name: str = "deepseek") -> DistilledTraits:
        """
        执行完整的 4-Pass 蒸馏流程。
        """
        fingerprint = card.compute_fingerprint()
        logger.info("开始蒸馏角色卡 %s (指纹: %s)", card.card_id, fingerprint)
        t_start = time.time()

        card_nl = card.natural_language.combined()
        experiences_text = card.get_experiences_text()
        corpus_text = card.get_corpus_text()

        # Pass 1: 全局理解
        logger.info("[蒸馏 Pass 1/4] 全局理解...")
        foundation = self._pass1_global_understanding(card_nl, experiences_text, corpus_text, user_notes, model_name)

        # Pass 2: 特征抽取
        logger.info("[蒸馏 Pass 2/4] 特征抽取...")
        materials_summary = f"{card_nl[:2000]}\n\n{experiences_text[:2000]}\n\n{corpus_text[:1000]}"
        features = self._pass2_feature_extraction(foundation, materials_summary, model_name)

        # Pass 3: 量化推断
        logger.info("[蒸馏 Pass 3/4] 量化推断...")
        features_text = json.dumps({
            "behavioral": features.get("behavioral_patterns", [])[:3],
            "speech": features.get("speech_patterns", [])[:3],
            "emotional": features.get("emotional_model", {}),
        }, ensure_ascii=False)
        dimensions_text = self._format_dimensions_for_prompt()
        manual_text = json.dumps(card.manual_overrides, ensure_ascii=False) if card.manual_overrides else "无"
        indicator_vector = self._pass3_quantization(
            foundation, features_text, dimensions_text, manual_text, model_name
        )
        indicator_vector = self._apply_manual_overrides(indicator_vector, card.manual_overrides)

        # Pass 4: 组装
        logger.info("[蒸馏 Pass 4/4] 校验 & 组装...")
        indicator_vector = self._validate_vector(indicator_vector)

        distilled = DistilledTraits({
            "distillation_id": f"distill_{card.card_id}_{fingerprint[:12]}",
            "card_id": card.card_id,
            "version": 1,
            "content_fingerprint": fingerprint,
            "model_used": model_name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "foundation_description": foundation,
            "behavioral_patterns": features.get("behavioral_patterns", []),
            "speech_patterns": features.get("speech_patterns", []),
            "emotional_model": features.get("emotional_model", {}),
            "relational_model": features.get("relational_model", {}),
            "indicator_vector": indicator_vector,
            "trait_narrative": features.get("trait_narrative", {}),
        })

        elapsed = time.time() - t_start
        logger.info("蒸馏完成: %s (耗时 %.1fs)", distilled.distillation_id, elapsed)
        return distilled

    def _call_model(self, prompt: str, model_name: str, temperature: float = 0.3, max_tokens: int = 2000) -> str:
        chat = self._main_chat or self._fast_chat
        if not chat:
            raise RuntimeError("蒸馏引擎未配置任何模型")
        try:
            return self._send_with_temp(chat, prompt, temperature, max_tokens)
        except Exception as e:
            if self._fast_chat and chat is not self._fast_chat:
                logger.warning("主模型调用失败(%s)，回退到快速模型", e)
                return self._send_with_temp(self._fast_chat, prompt, temperature, max_tokens)
            raise

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

    def _pass1_global_understanding(self, card_nl: str, experiences_text: str,
                                     corpus_text: str, user_notes: str, model_name: str) -> str:
        prompt = PASS1_GLOBAL_UNDERSTANDING.format(
            card_nl=card_nl or "（无）",
            experiences_text=experiences_text or "（无）",
            corpus_text=corpus_text or "（无）",
            user_notes=user_notes or "（无）",
        )
        return self._call_model(prompt, model_name, temperature=0.4, max_tokens=2500)

    def _pass2_feature_extraction(self, foundation: str, materials_summary: str, model_name: str) -> dict:
        prompt = PASS2_FEATURE_EXTRACTION.format(
            foundation=foundation,
            materials_summary=materials_summary[:4000],
        )
        raw = self._call_model(prompt, model_name, temperature=0.3, max_tokens=3000)
        return self._parse_json_response(raw)

    def _pass3_quantization(self, foundation: str, features_text: str,
                             dimensions_text: str, manual_text: str, model_name: str) -> dict[str, float]:
        prompt = PASS3_QUANTIZATION.format(
            foundation=foundation[:3000],
            features_text=features_text[:2000],
            dimensions_text=dimensions_text,
            manual_overrides_text=manual_text,
        )
        raw = self._call_model(prompt, model_name, temperature=0.2, max_tokens=3000)
        items = self._parse_json_response(raw)
        if isinstance(items, dict):
            items = [items]

        vec = {}
        for item in items if isinstance(items, list) else []:
            tid = item.get("id", "")
            if tid in TRAIT_IDS:
                try:
                    val = float(item.get("value", 0.5))
                    vec[tid] = max(0.0, min(1.0, val))
                except (ValueError, TypeError):
                    vec[tid] = 0.5

        # 补全缺失维度
        for tid in TRAIT_IDS:
            if tid not in vec:
                vec[tid] = 0.5

        return vec

    def _apply_manual_overrides(self, vec: dict[str, float], overrides: dict[str, float]) -> dict[str, float]:
        for tid, val in overrides.items():
            if tid in vec:
                vec[tid] = max(0.0, min(1.0, float(val)))
                logger.info("维度 %s 使用手动覆盖值: %.2f", tid, vec[tid])
        return vec

    def _validate_vector(self, vec: dict[str, float]) -> dict[str, float]:
        for tid in TRAIT_IDS:
            if tid not in vec:
                vec[tid] = 0.5
            vec[tid] = round(max(0.0, min(1.0, vec[tid])), 2)
        return vec

    def _format_dimensions_for_prompt(self) -> str:
        lines = []
        for t in ALL_DIMENSIONS:
            lines.append(f"{t.tid} {t.name}({t.name_en}): 低={t.low_desc}, 高={t.high_desc}")
        return "\n".join(lines)

    @staticmethod
    def _parse_json_response(raw: str) -> dict | list:
        raw = raw.strip()
        # 提取 ```json ... ``` 或直接的 JSON
        match = re.search(r'```(?:json)?\s*\n?(.*?)```', raw, re.DOTALL)
        if match:
            raw = match.group(1).strip()

        # 尝试直接解析
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # 尝试从文本中提取 JSON 对象
        brace_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass

        # 尝试从文本中提取 JSON 数组
        bracket_match = re.search(r'\[.*\]', raw, re.DOTALL)
        if bracket_match:
            try:
                return json.loads(bracket_match.group(0))
            except json.JSONDecodeError:
                pass

        # 尝试修复常见 JSON 错误: 多余的引号、尾部逗号等
        try:
            fixed = re.sub(r',\s*}', '}', raw)
            fixed = re.sub(r',\s*]', ']', fixed)
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass

        logger.warning("蒸馏响应 JSON 解析失败，返回空字典。原始响应前300字符: %s", raw[:300])
        return {}
