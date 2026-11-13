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

===== 核心性格（稳定的特质维度，不是当前情绪）=====
{stable_deviants}

===== 当下状态（可变的，仅限这一轮）=====
整体心境: {mood_summary}
情绪构成: joy={joy:.2f} sadness={sad:.2f} anger={ang:.2f} fear={fear:.2f}
与用户的当前关系: 亲密度 {affinity:.0f}，{rel_stage}
当前行为边界: {rel_bound}

===== 对话上下文 =====
用户刚才说: {user_msg}
对话氛围: {conv_tone}

---

写一段 200~500 字的"角色设定"。
这段文字将作为主 AI 的 system prompt 的一部分注入，所以用"你"来称呼 AI。

要求：
1. 写得像角色档案卡，而不是参数表
2. 【核心性格】部分描述角色稳定的人格——不受当前情绪影响，长期不变
3. 【当下状态】部分描述这一轮的情绪和关系阶段，指出情绪对台词风格的影响
4. 根据当前关系阶段提示说话方式
5. 1~2 句具体的表演建议（不是命令，是引导）
6. 有特殊说话习惯就自然融入

输出格式：
## 角色设定
{{你的文本}}"""


class PersonalityPromptGenerator:
    """人格提示词生成器（带缓存 + 后台生成）。

    ⚠️ 后台生成会打一次 LLM。**它不能和用户当前这一轮抢同一个模型队列** ——
    实测这样会把用户的回复拖到 50~100 秒。所以：

    1. ``before_generate`` 钩子：生成前调用（由上层决定何时可以发请求，
       例如"等用户说完话再生成"）。harness 不认识业务，只留钩子。
    2. ``min_regen_interval``：两次重新生成之间的最小间隔。人格描述
       不需要每轮都重新生成 —— 实测每轮都生成会白白多打一次 provider。
    """

    def __init__(self, chat=None, before_generate=None,
                 min_regen_interval: float = 300.0):
        self._chat = chat
        #: 按 (用户, 卡, 关系阶段) 分桶的提示词缓存
        self._cache: dict[str, str] = {}
        self._generating = False
        self._gen_lock = threading.Lock()
        #: 生成前的钩子（可阻塞）。返回 False 表示"现在别发"。
        self._before_generate = before_generate
        #: 两次重新生成的最小间隔（秒）
        self._min_regen_interval = float(min_regen_interval)
        self._last_gen_at = 0.0
        logger.info("PersonalityGenerator: 初始化 chat=%s", "available" if chat else "none")

    def set_chat(self, chat) -> None:
        self._chat = chat
        logger.info("PersonalityGenerator: 更新 chat 客户端")

    def set_before_generate(self, fn) -> None:
        """设置"生成前钩子"（可阻塞；返回 False 表示这次不生成）。

        上层用它把后台生成**推迟到用户空闲时** —— 后台 LLM 调用和用户
        当前这一轮抢同一个模型队列，会把回复拖到几十秒。
        """
        self._before_generate = fn

    @property
    def available(self) -> bool:
        return self._chat is not None

    def generate(self, snapshot: DynamicSnapshot, user_message: str = "",
                 conversation_tone: str = "中性",
                 cache_key: str | None = None) -> str:
        # 缓存**按 (用户, 卡, 关系阶段) 分桶**：同一张卡下不同用户的亲密度与
        # 情绪不同，共用一份缓存会把 A 的人格描述发给 B。
        cache_key = cache_key or snapshot.card_id
        with self._gen_lock:
            cached = self._cache.get(cache_key)
        if cached:
            return cached

        if not self._chat:
            return self._fallback(snapshot)

        # 首次调用：立即返回 fallback，后台触发 LLM 生成
        fallback = self._fallback(snapshot)
        self._trigger_async_generation(snapshot, user_message, conversation_tone, cache_key)
        return fallback

    def invalidate_cache(self, cache_key: str | None = None):
        with self._gen_lock:
            if cache_key is None:
                self._cache.clear()
            else:
                self._cache.pop(cache_key, None)

    def _trigger_async_generation(self, snapshot, user_message, conversation_tone,
                                  cache_key: str = ""):
        with self._gen_lock:
            if self._generating:
                return
            # 冷却：人格描述不必每轮重新生成
            import time as _time
            if (self._last_gen_at
                    and _time.time() - self._last_gen_at < self._min_regen_interval):
                return
            self._generating = True

        def _run():
            try:
                # 生成前先等上层放行（通常是"等用户说完话"）
                if self._before_generate is not None:
                    try:
                        if not self._before_generate():
                            with self._gen_lock:
                                self._generating = False
                            return
                    except Exception:   # noqa: BLE001
                        pass
                result = self._do_llm_generate(snapshot, user_message, conversation_tone)
                import time as _time
                self._last_gen_at = _time.time()
                with self._gen_lock:
                    self._cache[cache_key or snapshot.card_id] = result
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
        # 稳定特质中心（未被情绪/噪声调制），当下状态单独注入
        stable = self._stable_vector(snapshot)
        stable_deviants = format_deviant_dimensions(stable, top_n=12)

        prompt = PERSONALITY_PROMPT_TEMPLATE.format(
            foundation=foundation[:2000],
            behavioral=behavioral or "（暂无）",
            speech=speech or "（暂无）",
            stable_deviants=stable_deviants,
            mood_summary=mood_summary,
            joy=mood.get("joy", 0.5),
            sad=mood.get("sadness", 0.2),
            ang=mood.get("anger", 0.1),
            fear=mood.get("fear", 0.15),
            affinity=snapshot.affinity_value,
            rel_stage=rel_stage,
            rel_bound=rel_bound,
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
    def _stable_vector(snapshot: DynamicSnapshot) -> dict[str, float]:
        """稳定特质中心（未被情绪/噪声调制），供核心性格呈现。"""
        stable = snapshot.stable_indicator_vector or {}
        if stable:
            return stable
        return snapshot.indicator_vector or {}

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


#: 无快照时的兜底串。
#:
#: ⚠️ 这里曾经硬编码了另一个应用的人格（"你是 EXA，一个运行在用户本地电脑上的
#: AI 同事"），而本兜底串会被注入到**任何**应用的 system prompt 里 ——
#: dsn_study 偶尔会把"你是 EXA"讲给用户听。
#: 现在它只描述**行为准则**，不描述任何具体角色身份：具体身份由角色卡决定。
DEFAULT_FALLBACK_PROMPT = """## 角色设定
（角色档案暂不可用，先按下列准则表现：直接、实事求是、不编造；该给结论就给结论，步骤该展开就展开。）"""
