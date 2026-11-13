# prompt/personality_v3/distillation_engine.py
# 蒸馏引擎 — 4-Pass 将角色卡材料提炼为蒸馏产物

from __future__ import annotations

import json
import logging
import time
import re
from datetime import datetime, timezone

from .character_card import CharacterCard
from .traits import ALL_DIMENSIONS, TRAIT_IDS

logger = logging.getLogger("DistillationEngine")


class DistillationError(RuntimeError):
    """蒸馏产物不可用（解析失败 / 结构不完整）。

    ⚠️ 之前这里的行为是 **静默返回 {}**：解析失败只留一条 warning，
    于是"pass2/pass3 什么都没产出"被当成"这个角色就是这样"，
    线上那份 50 维全 0.5、四个结构化字段全空的产物就是这么来的。
    现在：**要么产出结构完整的产物，要么明确抛错**，绝不含糊过去。
    """


#: 各 pass 的输出预算（token）。
#:
#: 原值 3000 是线上事故的根源：pass2 的提示词要求 5 条行为模式 + 5 条言语模式
#: + 情绪模型 + 关系模型（≥4 阶段）+ 8 大类性格叙事，实测需要 ~6000 字符；
#: pass3 要求 50 个维度各带一句中文理由，实测需要 ~5700 字符。
#: 3000 的预算会把 JSON 截断在半截 → 解析失败 → 产物全空。
DISTILL_PASS1_MAX_TOKENS = 4000
DISTILL_PASS2_MAX_TOKENS = 8000
DISTILL_PASS3_MAX_TOKENS = 8000
#: 首次失败后的重试预算（再给一次机会，仍然不行就抛错）
DISTILL_RETRY_MAX_TOKENS = 16000


PASS1_GLOBAL_UNDERSTANDING = """你是一个角色发展分析师。请仔细阅读以下所有材料，然后写一段更新后的角色全貌描述。

重要原则：每一个经历条目（包括歌词、文章、对话记录等）都是角色真实遇到过的东西。你需要根据这些内容来发展角色的故事、气质和世界观。不要仅仅复述材料——要根据角色已有的性格基调，想象这些经历如何塑造、改变或深化了角色的内心世界。

要求：
1. 用自然语言写一段人物小传，涵盖所有经历素材
2. 必须涵盖：核心性格、行为模式、说话风格、价值观、情绪特质
3. 如果经历中包含了歌词/文学作品/文化素材——想象角色在哪个人生阶段、在什么心境下接触了这些内容。把这种"接触"本身变成角色故事的一部分。角色的音乐品味、阅读偏好、对某些歌词的共鸣——这些都是性格的线索
4. 明确写出：哪些经历强化了哪些性格特质？哪些经历让角色产生了新的理解或微妙的变化？
5. 识别角色最核心的性格矛盾或复杂性
6. 描述亲密度变化方式——角色如何与不同距离的人相处
7. 600~2000 字，中文，用现在时书写

===== 角色卡自然语言描述 =====
{card_nl}

===== 经历列表（从上到下是时间线） =====
{experiences_text}

===== 语料素材 =====
{corpus_text}

===== 用户额外提示 =====
{user_notes}

请输出更新后的角色全貌描述："""


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
        :param main_chat: OpenAIChat 实例，用于蒸馏（推荐 DeepSeek API）
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
            model_name: str = "openai") -> DistilledTraits:
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
        foundation = self._pass1_global_understanding(card_nl, experiences_text, corpus_text, user_notes, model_name, card.card_id)

        # Pass 2: 特征抽取
        logger.info("[蒸馏 Pass 2/4] 特征抽取...")
        materials_summary = f"{card_nl[:2000]}\n\n{experiences_text[:2000]}\n\n{corpus_text[:1000]}"
        features = self._pass2_feature_extraction(foundation, materials_summary, model_name, card.card_id)

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
            foundation, features_text, dimensions_text, manual_text, model_name, card.card_id
        )

        # Pass 4: 组装
        logger.info("[蒸馏 Pass 4/4] 校验 & 组装...")
        indicator_vector = self._validate_vector(indicator_vector)
        indicator_vector = self._apply_manual_overrides(indicator_vector, card.manual_overrides)

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

    def _call_model(self, prompt: str, model_name: str, temperature: float = 0.3,
                    max_tokens: int = 2000, pass_name: str = "", card_id: str = "") -> str:
        chat = self._main_chat or self._fast_chat
        if not chat:
            raise RuntimeError("蒸馏引擎未配置任何模型")
        try:
            reply = self._send_with_temp(chat, prompt, temperature, max_tokens)
            if pass_name and card_id:
                self._log_distill_pass(card_id, pass_name, prompt, reply)
            return reply
        except Exception as e:
            if self._fast_chat and chat is not self._fast_chat:
                logger.warning("主模型调用失败(%s)，回退到快速模型", e)
                reply = self._send_with_temp(self._fast_chat, prompt, temperature, max_tokens)
                if pass_name and card_id:
                    self._log_distill_pass(card_id, pass_name, prompt, reply)
                return reply
            raise

    def _log_distill_pass(self, card_id: str, pass_name: str, prompt: str, reply: str) -> None:
        try:
            from pathlib import Path as _P
            from datetime import datetime as _DT
            log_dir = _P(__file__).parent.parent.parent / "logs" / "distill"
            log_dir.mkdir(parents=True, exist_ok=True)
            ts = _DT.now().strftime("%Y%m%d_%H%M%S")
            prompt_path = log_dir / f"{card_id}_{ts}_{pass_name}_prompt.txt"
            reply_path = log_dir / f"{card_id}_{ts}_{pass_name}_reply.txt"
            prompt_path.write_text(prompt, encoding="utf-8")
            reply_path.write_text(reply, encoding="utf-8")
            logger.info("蒸馏日志已保存: %s", prompt_path.name)
        except Exception:
            logger.warning("Operation failed", exc_info=True)

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
                from infra.models.base import ChatMessage
                resp = chat.invoke([ChatMessage(role="user", content=prompt)], temperature=temperature, max_tokens=max_tokens)
                return resp.content or ""
            if hasattr(chat, 'complete'):
                from infra.models.base import ChatMessage
                resp = chat.complete([ChatMessage(role="user", content=prompt)])
                return resp.content or ""
            return ""
        finally:
            if old_temp is not None and hasattr(chat, 'temperature'):
                chat.temperature = old_temp
            if old_max is not None and hasattr(chat, 'max_tokens'):
                chat.max_tokens = old_max

    def _pass1_global_understanding(self, card_nl: str, experiences_text: str,
                                      corpus_text: str, user_notes: str, model_name: str,
                                      card_id: str = "") -> str:
        prompt = PASS1_GLOBAL_UNDERSTANDING.format(
            card_nl=card_nl or "（无）",
            experiences_text=experiences_text or "（无）",
            corpus_text=corpus_text or "（无）",
            user_notes=user_notes or "（无）",
        )
        return self._call_model(prompt, model_name, temperature=0.4,
                                max_tokens=DISTILL_PASS1_MAX_TOKENS,
                                pass_name="pass1", card_id=card_id)

    def _pass2_feature_extraction(self, foundation: str, materials_summary: str, model_name: str,
                                   card_id: str = "") -> dict:
        prompt = PASS2_FEATURE_EXTRACTION.format(
            foundation=foundation,
            materials_summary=materials_summary[:4000],
        )
        raw = self._call_model(prompt, model_name, temperature=0.3,
                               max_tokens=DISTILL_PASS2_MAX_TOKENS,
                               pass_name="pass2", card_id=card_id)
        try:
            features = self._parse_json_response(raw)
            self._validate_features(features)
            return features
        except DistillationError as exc:
            logger.warning("pass2 产物不可用（%s），用更大预算重试一次", exc)

        raw = self._call_model(prompt, model_name, temperature=0.3,
                               max_tokens=DISTILL_RETRY_MAX_TOKENS,
                               pass_name="pass2_retry", card_id=card_id)
        features = self._parse_json_response(raw)
        self._validate_features(features)
        return features

    @staticmethod
    def _validate_features(features) -> None:
        """校验 pass2 的结构完整性 —— 不完整就是失败，不接受"空产物"。"""
        if not isinstance(features, dict):
            raise DistillationError(f"pass2 产物不是对象: {type(features).__name__}")
        problems: list[str] = []
        for key, minimum in (("behavioral_patterns", 5), ("speech_patterns", 5)):
            items = features.get(key)
            got = len(items) if isinstance(items, list) else 0
            if got < minimum:
                problems.append(f"{key} 需要 ≥{minimum} 条，实得 {got}")
        for key in ("emotional_model", "relational_model"):
            if not features.get(key):
                problems.append(f"{key} 为空")
        stages = (features.get("relational_model") or {}).get("stages") or []
        if len(stages) < 4:
            problems.append(f"relational_model.stages 需要 ≥4 段，实得 {len(stages)}")
        narrative = features.get("trait_narrative")
        got = len(narrative) if isinstance(narrative, dict) else 0
        if got < 8:
            problems.append(f"trait_narrative 需要 ≥8 个大类，实得 {got}")
        if problems:
            raise DistillationError("；".join(problems))

    def _pass3_quantization(self, foundation: str, features_text: str,
                             dimensions_text: str, manual_text: str, model_name: str,
                             card_id: str = "") -> dict[str, float]:
        prompt = PASS3_QUANTIZATION.format(
            foundation=foundation[:3000],
            features_text=features_text[:2000],
            dimensions_text=dimensions_text,
            manual_overrides_text=manual_text,
        )
        raw = self._call_model(prompt, model_name, temperature=0.2,
                               max_tokens=DISTILL_PASS3_MAX_TOKENS,
                               pass_name="pass3", card_id=card_id)
        try:
            items = self._parse_json_response(raw)
            vec, missing = self._items_to_vector(items)
            if missing:
                raise DistillationError(
                    f"pass3 缺少 {len(missing)} 个维度：{missing[:5]}")
            return vec
        except DistillationError as exc:
            logger.warning("pass3 产物不可用（%s），用更大预算重试一次", exc)

        raw = self._call_model(prompt, model_name, temperature=0.2,
                               max_tokens=DISTILL_RETRY_MAX_TOKENS,
                               pass_name="pass3_retry", card_id=card_id)
        items = self._parse_json_response(raw)
        vec, missing = self._items_to_vector(items)
        if missing:
            raise DistillationError(
                f"pass3 重试后仍缺少 {len(missing)} 个维度：{missing[:5]}")
        return vec

    @staticmethod
    def _items_to_vector(items) -> tuple[dict[str, float], list[str]]:
        """把 pass3 的数组转成 50 维向量。

        返回 (向量, 缺失维度列表)。**不再静默把缺失维度补成 0.5** ——
        补 0.5 等于宣称"这个角色在这一维上恰好是中庸"，而真相是
        "模型没输出这一维"。两者的区别，正是线上那份全 0.5 产物的来源。
        """
        if isinstance(items, dict):
            items = [items]
        vec: dict[str, float] = {}
        for item in (items if isinstance(items, list) else []):
            if not isinstance(item, dict):
                continue
            tid = str(item.get("id", ""))
            if tid in TRAIT_IDS and tid not in vec:
                try:
                    vec[tid] = max(0.0, min(1.0, float(item.get("value", 0.5))))
                except (ValueError, TypeError):
                    continue
        missing = [tid for tid in TRAIT_IDS if tid not in vec]
        return vec, missing

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

        logger.error("蒸馏响应 JSON 解析失败。原始响应前 300 字符: %s", raw[:300])
        raise DistillationError(
            f"蒸馏响应不是合法 JSON（长度 {len(raw)}，可能是被 max_tokens 截断）")
