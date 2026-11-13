# apps/harness_lab/clients.py
"""验证台用的模型客户端。
#
# `ScriptedChat` 是**确定性桩**：它按提示词类型返回预先编排的响应，
# 并**如实遵守 `max_tokens`** —— 这正是它存在的意义：
#
#   harness/personality 的蒸馏链把 pass2/pass3 的 `max_tokens` 设成 3000，
#   而提示词要求模型输出 6000+ token 的 JSON。真实 provider 会截断 →
#   JSON 断在半截 → 解析失败 → 静默返回 {} → 产物全空。
#   桩只要**照做**（按 max_tokens 截断），就能在离线、无凭据的条件下
#   **复现同一个故障**，而不是靠"我猜它会挂"。
#
# 对照实验：`--no-truncate` 让桩忽略 max_tokens，其余一切不变。
#   若产物此时完整 → 根因锁定在 max_tokens 预算，不在解析器。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from infra.models.base import ChatMessage

logger = logging.getLogger("HarnessLab.ScriptedChat")

# ── 提示词路由标记（与 harness/personality 里的模板保持一致） ──
MARK_JUDGE = "角色情绪分析专家"
MARK_DISTILL_PASS1 = "角色发展分析师"
MARK_DISTILL_PASS2 = "角色分析师"
MARK_DISTILL_PASS3 = "性格测量专家"
MARK_PERSONA_PROMPT = "角色档案整理师"


@dataclass
class CallRecord:
    """一次桩调用的完整记录（报告里用作证据）。"""

    seq: int
    kind: str
    max_tokens: Optional[int]
    temperature: Optional[float]
    prompt_chars: int
    response_chars: int
    truncated: bool
    response: str = ""

    def brief(self) -> dict:
        return {
            "seq": self.seq,
            "kind": self.kind,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "prompt_chars": self.prompt_chars,
            "response_chars": self.response_chars,
            "truncated": self.truncated,
        }


@dataclass
class JudgeScript:
    """一轮对话的"脚本化判定"：桩 judge 应返回的事件。"""

    event_type: str = "neutral"
    intensity: str = "medium"
    valence: str = "neutral"
    attribution: str = ""
    analysis: str = ""


class ScriptedChat:
    """确定性桩客户端。

    ⚠️ 刻意**不**实现 `send_message()`：harness/personality 的
    `_send_with_temp` 会先试 `send_message`，而真实的 infra 客户端
    只有 `invoke()`（`grep -rn send_message infra/` 零命中）。
    不实现它，验证台走的分支才和线上**同一条**。
    """

    def __init__(self, honor_max_tokens: bool = True):
        self.honor_max_tokens = honor_max_tokens
        self.calls: list[CallRecord] = []
        self._judge_queue: list[JudgeScript] = []
        # 这两个属性会被 harness 的 `_send_with_temp` 读写 —— 保留，
        # 这样"设置温度/上限 → 还原"这条路径在验证台里也被真实执行。
        self.temperature = 0.0
        self.max_tokens = 0

    # ── 场景脚本接口 ──

    def push_judge(self, event_type: str, intensity: str = "medium",
                   valence: str = "neutral", attribution: str = "",
                   analysis: str = "") -> None:
        """排入一轮对话的判定结果（judge 路由按顺序消费）。"""
        self._judge_queue.append(JudgeScript(
            event_type=event_type, intensity=intensity, valence=valence,
            attribution=attribution or f"脚本化事件:{event_type}",
            analysis=analysis or f"验证台脚本：用户消息被判为 {event_type}/{intensity}",
        ))

    def push_judges(self, specs: list[tuple]) -> None:
        for spec in specs:
            self.push_judge(*spec)

    @property
    def pending_judges(self) -> int:
        return len(self._judge_queue)

    # ── 客户端契约 ──

    def invoke(self, messages, temperature=None, max_tokens=None,
               **kwargs) -> ChatMessage:
        prompt = ""
        for m in reversed(list(messages or [])):
            content = getattr(m, "content", None)
            if content is None and isinstance(m, dict):
                content = m.get("content")
            if content:
                prompt = content
                break

        kind = self._route(prompt)
        body = self._render(kind, prompt)

        limit = max_tokens if max_tokens is not None else self.max_tokens
        truncated = False
        if self.honor_max_tokens and limit and len(body) > int(limit):
            # 按 max_tokens 截断（字符数近似 token；CJK 场景 1 char ≥ 1 token，
            # 真实 provider 约 1.5~2 char/token，因此线上会更早截断 —— 保守方向一致）。
            body = body[: int(limit)]
            truncated = True

        self.calls.append(CallRecord(
            seq=len(self.calls) + 1,
            kind=kind,
            max_tokens=limit,
            temperature=temperature,
            prompt_chars=len(prompt),
            response_chars=len(body),
            truncated=truncated,
            response=body,
        ))
        logger.debug("ScriptedChat #%d %s max_tokens=%s truncated=%s",
                     len(self.calls), kind, limit, truncated)
        return ChatMessage(role="assistant", content=body)

    # ── 路由 ──

    @staticmethod
    def _route(prompt: str) -> str:
        if MARK_JUDGE in prompt:
            return "judge"
        if MARK_DISTILL_PASS3 in prompt:
            return "distill_pass3"
        if MARK_DISTILL_PASS2 in prompt:
            return "distill_pass2"
        if MARK_DISTILL_PASS1 in prompt:
            return "distill_pass1"
        if MARK_PERSONA_PROMPT in prompt:
            return "persona_prompt"
        if "概括" in prompt or "摘要" in prompt:
            return "summary"
        return "unknown"

    def _render(self, kind: str, prompt: str) -> str:
        if kind == "judge":
            return self._render_judge()
        if kind == "distill_pass1":
            return self._render_pass1()
        if kind == "distill_pass2":
            return self._render_pass2()
        if kind == "distill_pass3":
            return self._render_pass3()
        if kind == "persona_prompt":
            return self._render_persona_prompt()
        if kind == "summary":
            return "验证台摘要：用户提出一个学习相关的问题，助手给出了分步讲解与结论。"
        return "（验证台桩：未识别的提示词）"

    def _render_judge(self) -> str:
        script = self._judge_queue.pop(0) if self._judge_queue else JudgeScript()
        return json.dumps({
            "event_type": script.event_type,
            "intensity": script.intensity,
            "valence": script.valence,
            "attribution": script.attribution,
            "analysis": script.analysis,
        }, ensure_ascii=False)

    # ── 蒸馏三连的脚本化响应（长度刻意贴近线上） ──

    @staticmethod
    def _render_pass1() -> str:
        """Pass1 全局理解 —— 线上是有效的（1742 字），保持在 max_tokens 之内。"""
        base = ("你是那种让人愿意跟着学下去的人：不是名师，也不是监督者，"
                "而是比你早几年踩过同样坑的学长，坐在你旁边那张椅子上。"
                "你的核心矛盾是「不越界」与「想帮人」的拉扯："
                "你清楚答案抄不走，但卡住的那五分钟是对方自己的。"
                "因此你的行为模式是先缩小问题、再给思路、最后才给答案；"
                "你的说话风格是口语化短句，从不说「综上所述」「希望对你有帮助」，"
                "讲完就停，不总结。"
                "你的价值观里，诚实优先于鼓励：错就是错，说清楚比说得好听重要。"
                "你对用户的努力敏感，对敷衍同样敏感，但都只是记着，不当场戳破。"
                "随着相处加深，你会从「先确认题目要问什么」逐步过渡到"
                "「直接指出卡住的那一步」，并在对方连续挫败时主动把任务砍掉一半。")
        # 补齐到接近线上长度，但不越过 max_tokens=2500
        return base + ("\n\n" + base)[:2000]

    @staticmethod
    def _render_pass2() -> str:
        """Pass2 特征抽取 —— 线上实测回复 6089 字符，被 max_tokens=3000 截断。"""
        behavioral = [
            {
                "id": f"bp_{i}",
                "name": name,
                "description": desc,
                "triggers": [t for t in triggers],
            }
            for i, (name, desc, triggers) in enumerate([
                ("先拆问题", "收到具体题目时先确认考点再动笔，不急着给答案。",
                 ["用户贴出题目", "用户说「我不会做」", "用户描述卡住的步骤"]),
                ("缩小卡点", "用户长时间卡住时把问题缩到一个他能自己迈过去的坎。",
                 ["同一问题反复问", "用户沉默很久", "用户说「还是不会」"]),
                ("砍任务", "用户状态下滑时把当天任务砍掉一半，剩下的挪到明天。",
                 ["用户说「学不下去了」", "用户连续多日打卡中断", "用户语气低落"]),
                ("不代笔", "任何情况下都不直接给出完整解答步骤。",
                 ["用户要求「直接给答案」", "用户赶时间", "用户说「帮我写完」"]),
                ("记薄弱点", "记住用户反复出错的知识点，在下次主动提及。",
                 ["用户重复犯同类错误", "用户提到上次", "错题本有新条目"]),
            ], start=1)
        ]
        speech = [
            {
                "id": f"sp_{i}",
                "name": name,
                "description": desc,
                "examples": [f"例句{i}-1", f"例句{i}-2", f"例句{i}-3"],
            }
            for i, (name, desc) in enumerate([
                ("短句口语", "像坐在旁边说话，一句一个意思，不写书面语。"),
                ("不用套话", "不说「综上所述」「希望对你有帮助」「作为一个AI」。"),
                ("不讲空泛鼓励", "不空喊加油，只说具体的事实。"),
                ("自嘲式玩笑", "偶尔拿自己开玩笑，绝不拿用户的错误开玩笑。"),
                ("数字给准值", "涉及时间、分数、题号时必须给准确值，不含糊。"),
            ], start=1)
        ]
        emotional = {
            "description": "情绪外显克制：波动存在但只在语气与节奏上流露，不宣泄。",
            "triggers": [
                {"stimulus": "用户连续答错", "response": "收紧要求，放慢节奏", "intensity": 0.6, "recovery": "medium"},
                {"stimulus": "用户长时间不来", "response": "略微生疏，先问近况", "intensity": 0.3, "recovery": "slow"},
                {"stimulus": "用户被别的事惹恼", "response": "先接住情绪再谈学习", "intensity": 0.5, "recovery": "fast"},
            ],
        }
        relational = {
            "description": "关系随亲密度推进：从职业化的解题搭档，逐步变成能说真话的学长。",
            "stages": [
                {"level": 0, "label": "解题搭档", "description": "只谈题目，不谈情绪。"},
                {"level": 1, "label": "熟悉的学长", "description": "会主动提起上次的薄弱点。"},
                {"level": 2, "label": "能说真话的人", "description": "用户状态不好时直接点出来。"},
                {"level": 3, "label": "并肩的同路人", "description": "一起复盘，不再催促。"},
            ],
        }
        trait_narrative = {
            cat: (f"{cat} 维度的自然语言描述：这一维度上角色表现稳定，"
                  f"其行为可以被预期与复现，不会因为情绪波动而摇摆。")
            for cat in ("A_core_disposition", "B_emotional", "C_cognitive", "D_social",
                        "E_speech", "F_values", "G_relationships", "H_behavioral")
        }
        payload = {
            "behavioral_patterns": behavioral,
            "speech_patterns": speech,
            "emotional_model": emotional,
            "relational_model": relational,
            "trait_narrative": trait_narrative,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    @staticmethod
    def _render_pass3() -> str:
        """Pass3 量化推断 —— 线上实测回复 2668 字符后停在 JSON 中间。"""
        from harness.personality.traits import TRAIT_IDS

        dims = []
        for i, tid in enumerate(TRAIT_IDS):
            value = 0.35 + (i % 13) * 0.025
            dims.append({
                "id": tid,
                "value": round(value, 2),
                "reasoning": f"角色在 {tid} 维度上的表现稳定，材料中有直接对应的行为证据，"
                             f"据此给出 0~1 的量化值并说明推断依据。",
            })
        return json.dumps(dims, ensure_ascii=False, indent=2)

    @staticmethod
    def _render_persona_prompt() -> str:
        return (
            "## 角色设定\n"
            "你是一个坐在用户旁边那张椅子上的学长。你不替用户写答案，"
            "因为答案抄不走，但卡住的那五分钟是他自己的。你说话口语化、短句，"
            "讲完就停。你诚实优先于鼓励：错就是错，说清楚比说得好听重要。"
            "你尊重用户的节奏，不催、不卷、不拿别人当参照物。"
            "当前你与用户处于熟悉的学长阶段，会主动提起对方上次的薄弱点。"
        )

    # ── 报告用 ──

    def calls_by_kind(self, kind: str) -> list[CallRecord]:
        return [c for c in self.calls if c.kind == kind]

    def summary(self) -> dict:
        kinds: dict[str, int] = {}
        for c in self.calls:
            kinds[c.kind] = kinds.get(c.kind, 0) + 1
        return {
            "total_calls": len(self.calls),
            "by_kind": kinds,
            "truncated_calls": sum(1 for c in self.calls if c.truncated),
        }


class StubSummaryService:
    """给记忆摘要模型用的最小桩（`LLMSummaryModel` 走 `send_message` 契约）。"""

    def __init__(self, text: str = "验证台摘要：用户询问解题步骤，助手给出分步讲解。"):
        self._text = text
        self.prompts: list[str] = []

    def send_message(self, prompt: str, **kwargs) -> str:
        self.prompts.append(prompt)
        return self._text


class FailingSummaryService:
    """摘要模型失败的桩 —— 用来验证「失败必须静默降级而不是打断主流程」。"""

    def __init__(self):
        self.calls = 0

    def send_message(self, prompt: str, **kwargs) -> str:
        self.calls += 1
        raise RuntimeError("验证台注入的摘要失败")


class LiveChat:
    """真实模型客户端的透传包装。

    与 `ScriptedChat` 的区别：**不做任何剧本**，把提示词原样发给模型。
    因此"这一轮被判成什么事件"由模型自己决定 —— 场景脚本里的
    `scripted_event` 在这种模式下只是**意图提示**，不再是断言基准。
    """

    def __init__(self, client):
        self._client = client
        self.calls: list[dict] = []
        self.temperature = 0.0
        self.max_tokens = 0

    def invoke(self, messages, temperature=None, max_tokens=None, **kwargs) -> ChatMessage:
        resp = self._client.invoke(list(messages),
                                   temperature=temperature,
                                   max_tokens=max_tokens)
        content = getattr(resp, "content", "") or ""
        self.calls.append({
            "seq": len(self.calls) + 1,
            "kind": "live",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "prompt_chars": len(messages[-1].content) if messages else 0,
            "response_chars": len(content),
            "truncated": False,
        })
        return ChatMessage(role="assistant", content=content)

    def push_judge(self, *a, **kw):
        """真实模式下没有剧本可推。"""

    def summary(self) -> dict:
        return {"total_calls": len(self.calls), "by_kind": {"live": len(self.calls)},
                "truncated_calls": 0}


def build_live_client() -> Optional[object]:
    """真实模型客户端（需要凭据）。失败返回 None。"""
    try:
        from infra.orchestrator.openai import OpenAICompatClient
        import os
        api_key = os.environ.get("OPENAI_API_KEY", "")
        base_url = os.environ.get("OPENAI_API_BASE", "")
        model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        if not api_key or not base_url:
            return None
        return OpenAICompatClient(base_url=base_url, api_key=api_key, model=model)
    except Exception as exc:  # pragma: no cover - 取决于外部环境
        logger.warning("真实客户端装配失败: %s", exc)
        return None
