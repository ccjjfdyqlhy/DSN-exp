# -*- coding: utf-8 -*-
"""dsn_study 人格内核（apps/dsn_study/persona/）单测。

覆盖三块：

  * ``signals.extract_signals`` —— 表驱动的规则信号判定（契约 §3.2）；
  * ``engine.PersonaEngine`` —— 提示词呈现 / 回写 / 状态（契约 §3.3、§3.4）；
  * 角色卡**进了版本控制**（契约 §3.1 —— 现状 ``character_cards/`` 被忽略）。

红线 R6：人格系统的任何故障都只能降级，**绝不能让整轮对话失败**。
"""

from __future__ import annotations

import re
import sqlite3
import subprocess

import pytest

from apps.dsn_study.persona import (
    DEFAULT_CARDS_DIR,
    MAX_PROMPT_CHARS,
    PersonaEngine,
    Signal,
    extract_signals,
)
from harness.personality.character_card import CharacterCard
from harness.personality.events import (
    EVENT_COMPLAINT,
    EVENT_CONFLICT,
    EVENT_NEUTRAL,
    EVENT_PRAISE,
    EVENT_THANKS,
    EVENT_TYPES,
    EVENT_VENTING,
    INTENSITY_HIGH,
    INTENSITY_LOW,
    INTENSITY_MEDIUM,
)

CARD_PATH = DEFAULT_CARDS_DIR / "study_tutor.yaml"

#: 别的应用的人格标识 —— dsn_study 的 prompt 里出现就是串味。
FOREIGN_NAMES = ("EXA", "本地电脑上的 AI 同事")

#: 50 维特质的维度编号（如 A2 / F4）—— 原始向量绝不能进 prompt。
_DIM_ID_RE = re.compile(r"(?<![A-Za-z0-9])[A-H]\d(?![0-9])")


# ── 桩 ──

class _StubPV3:
    """最小 PEV3 桩 —— 只实现本包用到的公开接口。

    注意：这个基类**故意没有** ``apply_event`` —— 用来验证「harness 侧
    还没提供该方法」时的降级路径。
    """

    def __init__(self, *,
                 status: dict | None = None,
                 vector: dict | None = None,
                 status_raises: bool = False,
                 full_raises: bool = False,
                 apply_event_raises: bool = False):
        self.status_raises = status_raises
        self.full_raises = full_raises
        self.apply_event_raises = apply_event_raises
        self._status = status if status is not None else {
            "uid": 1,
            "card_id": "study_tutor",
            "total_interactions": 3,
            "mood": {"joy": 0.6, "sadness": 0.2, "anger": 0.1, "fear": 0.1},
            "affinity_value": 42.0,
            "affinity_level": {"level": 3, "label": "留意", "progress": 0.2},
            "evidence_total": 5,
        }
        self._vector = vector if vector is not None else {
            "A2": 0.72, "B4": 0.31, "E1": 0.50, "H2": 0.68,
        }
        self.applied: list[tuple] = []
        self.analyzed: list[tuple] = []
        self.bound: list[tuple] = []

    # -- PEV3 公开接口 --

    def get_personality_status(self, uid: int) -> dict:
        if self.status_raises:
            raise RuntimeError("人格状态服务挂了")
        return dict(self._status)

    def get_personality_full(self, uid: int) -> dict:
        if self.full_raises:
            raise RuntimeError("人格全量服务挂了")
        return {"uid": uid, "indicator_vector": dict(self._vector)}

    def get_card(self, card_id: str):
        return CharacterCard.from_yaml_file(CARD_PATH) if card_id == "study_tutor" else None

    def get_recent_events(self, uid: int = 0, card_id: str = "", limit: int = 30):
        return [{"ts": 1731000000.0}]

    def bind_user_card(self, uid: int, card_id: str) -> bool:
        self.bound.append((uid, card_id))
        return True

    def analyze_interaction(self, uid, user_message, ai_reply,
                            conversation_history: str = "", judge_chat=None):
        self.analyzed.append((uid, user_message, ai_reply))
        return None



class _StubPV3WithEvent(_StubPV3):
    """带 ``apply_event`` 的桩（harness 侧提供新方法之后的形态）。"""

    def apply_event(self, uid, perception, conversation_history: str = ""):
        if self.apply_event_raises:
            raise RuntimeError("apply_event 挂了")
        self.applied.append((uid, perception, conversation_history))
        return None


def _engine(*, with_apply_event: bool = True, trace_sink=None,
            **kwargs) -> tuple[PersonaEngine, _StubPV3]:
    cls = _StubPV3WithEvent if with_apply_event else _StubPV3
    pv3 = cls(**kwargs)
    return PersonaEngine(pv3, trace_sink=trace_sink), pv3


# ══════════════════════════════════════════════════════════════
# 信号抽取（表驱动）
# ══════════════════════════════════════════════════════════════

class TestExtractSignals:

    @pytest.mark.parametrize("text,kwargs,event_type,intensity,valence", [
        # 显式答题结果
        ("今天这道题做完了", {"answer_correct": True},
         EVENT_PRAISE, INTENSITY_MEDIUM, "positive"),
        ("今天这道题做完了", {"answer_wrong": True},
         EVENT_COMPLAINT, INTENSITY_MEDIUM, "negative"),
        # 关键词规则
        ("谢谢你啊", {}, EVENT_THANKS, INTENSITY_MEDIUM, "positive"),
        ("你太厉害了", {}, EVENT_THANKS, INTENSITY_MEDIUM, "positive"),
        ("这道题我搞错了", {}, EVENT_COMPLAINT, INTENSITY_MEDIUM, "negative"),
        ("这一步我没懂", {}, EVENT_COMPLAINT, INTENSITY_MEDIUM, "negative"),
        ("今天真是烦", {}, EVENT_VENTING, INTENSITY_MEDIUM, "negative"),
        ("压力好大不想学了", {}, EVENT_VENTING, INTENSITY_MEDIUM, "negative"),
        ("你有病吧", {}, EVENT_CONFLICT, INTENSITY_HIGH, "negative"),
        ("别管我，滚", {}, EVENT_CONFLICT, INTENSITY_HIGH, "negative"),
        # 其它 → neutral（普通陈述句不能被误判成情绪事件）
        ("今天复习了二次函数，一共做了12道题", {},
         EVENT_NEUTRAL, INTENSITY_LOW, "neutral"),
    ])
    def test_rules(self, text, kwargs, event_type, intensity, valence):
        signals = extract_signals(text, "助手回复", **kwargs)
        assert len(signals) == 1
        sig = signals[0]
        assert isinstance(sig, Signal)
        assert sig.event_type == event_type
        assert sig.intensity == intensity
        assert sig.valence == valence

    @pytest.mark.parametrize("text,expected", [
        ("谢谢你，今天真是烦死了", EVENT_VENTING),   # venting > thanks
        ("谢谢你，别管我滚", EVENT_CONFLICT),       # conflict > thanks
        ("搞错了，好烦", EVENT_VENTING),            # venting > complaint
        ("搞错了，谢谢", EVENT_COMPLAINT),          # complaint > thanks
        ("谢谢你，学到了", EVENT_THANKS),           # 同规则内取一条
    ])
    def test_priority(self, text, expected):
        signals = extract_signals(text)
        assert len(signals) == 1
        assert signals[0].event_type == expected

    def test_at_most_one_signal(self):
        """一次调用最多返回 1 条 —— 一轮灌多条证据会让人格状态漂移。"""
        text = "谢谢你，烦死了，滚，我不想学了，搞错了"
        signals = extract_signals(text)
        assert len(signals) == 1
        assert signals[0].event_type == EVENT_CONFLICT

    def test_event_type_is_legal(self):
        """event_type 必须是 harness 的事件枚举。"""
        for text in ("谢谢", "搞错", "烦", "滚", "普通句子"):
            for sig in extract_signals(text):
                assert sig.event_type in EVENT_TYPES

    def test_normalization_is_fullwidth_and_case_insensitive(self):
        """全半角与大小写不敏感（NFKC + casefold）。"""
        assert extract_signals("ＡＢＣ 我搞错了")[0].event_type == EVENT_COMPLAINT
        assert extract_signals("THANKS")[0].event_type == EVENT_NEUTRAL
        assert extract_signals("真烦ＡＢＣ")[0].event_type == EVENT_VENTING

    def test_contradictory_answer_flags_fall_back_to_keywords(self):
        """两个答题标记互相矛盾 → 当作没给，退回关键词判定。"""
        sig = extract_signals("今天复习了函数",
                              answer_correct=True, answer_wrong=True)[0]
        assert sig.event_type == EVENT_NEUTRAL

    def test_reply_is_not_used_for_event_detection(self):
        """规则只看用户文本 —— 助手回复是结果，不是事件。"""
        assert extract_signals("好的", "谢谢你")[0].event_type == EVENT_NEUTRAL

    def test_empty_input_is_neutral(self):
        sig = extract_signals("")[0]
        assert sig.event_type == EVENT_NEUTRAL
        assert sig.intensity == INTENSITY_LOW


# ══════════════════════════════════════════════════════════════
# 提示词呈现
# ══════════════════════════════════════════════════════════════

class TestPromptBlock:

    def test_normal_path_contains_card_name(self):
        engine, _ = _engine()
        block = engine.prompt_block(1)
        assert "小舟" in block
        assert "## 角色设定" in block

    def test_normal_path_contains_profile_stage_and_traits(self):
        engine, _ = _engine()
        block = engine.prompt_block(1)
        # 档案正文（角色卡自然语言，逐字搬过来的）
        assert "小舟是那种你愿意跟着学下去的人" in block
        # 关系阶段
        assert "关系阶段" in block and "留意" in block
        # 偏离基线的特质（E1 = 0.5，偏离 0.00 → 不展示）
        assert "尽责性" in block
        assert "话量" not in block

    def test_length_limit(self):
        engine, _ = _engine()
        block = engine.prompt_block(1)
        assert len(block) <= MAX_PROMPT_CHARS

    def test_length_limit_truncates_long_profile(self):
        """卡片正文特别长时也必须截到上限内。"""
        engine, _ = _engine()
        card = CharacterCard.from_yaml_file(CARD_PATH)
        card.natural_language.personality = "很长的档案正文。" * 500
        engine._load_card = lambda card_id: card  # noqa: SLF001 —— 注入长卡片
        block = engine.prompt_block(1)
        assert len(block) <= MAX_PROMPT_CHARS

    def test_no_foreign_persona(self):
        """不得出现别的应用的人格身份。"""
        engine, _ = _engine()
        block = engine.prompt_block(1)
        for name in FOREIGN_NAMES:
            assert name not in block

    def test_no_raw_50d_vector(self):
        """不得把 50 维原始向量、维度编号塞进 prompt。"""
        engine, _ = _engine()
        block = engine.prompt_block(1)
        assert "indicator_vector" not in block
        assert not _DIM_ID_RE.search(block), block

    def test_status_failure_degrades_gracefully(self):
        """人格状态读挂了 → 降级（不抛），仍能给出角色卡档案。"""
        engine, _ = _engine(status_raises=True)
        block = engine.prompt_block(1)
        assert isinstance(block, str)
        assert "小舟" in block

    def test_full_status_failure_degrades_gracefully(self):
        engine, _ = _engine(full_raises=True)
        block = engine.prompt_block(1)
        assert isinstance(block, str)
        assert "小舟" in block

    def test_missing_card_degrades_gracefully(self):
        """没有可用角色卡 → 返回空串，不抛。"""
        engine, _ = _engine()
        engine._load_card = lambda card_id: None  # noqa: SLF001
        assert engine.prompt_block(1) == ""

    def test_unexpected_exception_never_escapes(self):
        """红线 R6：任何异常都必须降级，绝不抛出去。

        最坏情况：PEV3 的每个接口都炸。角色卡在**版本控制里**（本地目录），
        所以档案正文仍然拿得到 —— 这正是把卡片搬进版本控制的意义。
        """
        engine, pv3 = _engine()

        def boom(*args, **kwargs):
            raise RuntimeError("炸了")

        pv3.get_personality_status = boom
        pv3.get_personality_full = boom
        pv3.get_card = boom
        block = engine.prompt_block(1)
        assert isinstance(block, str)
        assert "小舟" in block


# ══════════════════════════════════════════════════════════════
# 状态回写
# ══════════════════════════════════════════════════════════════

class TestFeedback:

    def test_never_raises(self):
        engine, pv3 = _engine(apply_event_raises=True)
        engine.feedback(1, "谢谢你", "不客气")   # 不抛就算过

    def test_apply_event_missing_degrades(self):
        """PEV3 没有 apply_event → 降级为不做事并记一条日志，不崩。"""
        traces: list[dict] = []
        engine, pv3 = _engine(with_apply_event=False, trace_sink=traces.append)
        engine.feedback(1, "谢谢你", "不客气")
        assert pv3.applied == []
        assert pv3.analyzed == []
        assert any(t.get("degraded") == "apply_event_missing" for t in traces)

    def test_rules_path_applies_event(self):
        """默认路径：规则信号 → PerceptionRecord → apply_event。"""
        engine, pv3 = _engine()
        engine.feedback(1, "谢谢你，这题终于搞懂了", "不客气")
        assert len(pv3.applied) == 1
        uid, perception, history = pv3.applied[0]
        assert uid == 1
        assert perception.event_type == EVENT_THANKS
        assert perception.intensity == INTENSITY_MEDIUM
        assert perception.valence == "positive"
        assert history == ""

    def test_answer_flags_reach_perception(self):
        engine, pv3 = _engine()
        engine.feedback(1, "做完了", "不错", answer_correct=True)
        assert pv3.applied[0][1].event_type == EVENT_PRAISE

    def test_llm_not_called_when_use_llm_judge_false(self):
        """use_llm_judge=False → 不调用 LLM（热路径不排队）。"""
        engine, pv3 = _engine()
        engine.feedback(1, "谢谢你", "不客气")
        assert pv3.analyzed == []
        assert len(pv3.applied) == 1

    def test_llm_called_when_use_llm_judge_true(self):
        pv3 = _StubPV3()
        engine = PersonaEngine(pv3, use_llm_judge=True)
        engine.feedback(1, "谢谢你", "不客气")
        assert pv3.analyzed and pv3.analyzed[0][0] == 1
        assert pv3.applied == []

    def test_trace_sink_failure_does_not_break(self):
        def bad_sink(payload):
            raise RuntimeError("trace 挂了")

        engine, _ = _engine(trace_sink=bad_sink)
        engine.feedback(1, "谢谢你", "不客气")   # 不抛


# ══════════════════════════════════════════════════════════════
# 状态查询 / 卡片管理
# ══════════════════════════════════════════════════════════════

class TestStatus:

    def test_fields_present(self):
        engine, _ = _engine()
        data = engine.status(1)
        for field in ("uid", "card_id", "affinity", "affinity_level",
                      "total_interactions", "mood", "traits",
                      "evidence_total", "last_updated"):
            assert field in data, "status 缺字段: %s" % field
        assert data["uid"] == 1
        assert data["card_id"] == "study_tutor"
        assert data["affinity"] == 42.0
        assert data["total_interactions"] == 3
        assert data["evidence_total"] == 5
        assert data["mood"]["joy"] == 0.6
        assert isinstance(data["traits"], list)
        assert data["traits"], "偏离基线的特质没返回"

    def test_status_failure_degrades(self):
        engine, _ = _engine(status_raises=True)
        data = engine.status(1)
        assert data["uid"] == 1
        assert data["affinity"] == 0.0
        assert data["card_id"] == ""
        assert isinstance(data["traits"], list)


class TestCards:

    def test_study_tutor_card_is_listed(self):
        engine, _ = _engine()
        cards = engine.cards()
        ids = [c["card_id"] for c in cards]
        assert "study_tutor" in ids

    def test_switch_binds_card(self):
        engine, pv3 = _engine()
        assert engine.switch(1, "study_tutor") is True
        assert pv3.bound == [(1, "study_tutor")]

    def test_switch_unknown_card_returns_false(self):
        engine, _ = _engine()
        assert engine.switch(1, "不存在的卡") is False

    def test_switch_failure_never_raises(self):
        engine, pv3 = _engine()
        pv3.bind_user_card = lambda uid, cid: (_ for _ in ()).throw(RuntimeError("挂了"))
        assert engine.switch(1, "study_tutor") is False


# ══════════════════════════════════════════════════════════════
# 卡片进版本控制（契约 §3.1）
# ══════════════════════════════════════════════════════════════

class TestCardVersioning:

    def test_card_file_exists(self):
        assert CARD_PATH.is_file(), "缺少版本化角色卡: %s" % CARD_PATH

    def test_card_is_valid(self):
        card = CharacterCard.from_yaml_file(CARD_PATH)
        assert not card.validate(), card.validate()
        assert card.card_id == "study_tutor"
        assert card.natural_language.personality.strip()
        assert card.natural_language.behavior.strip()

    def test_card_natural_language_is_verbatim(self):
        """自然语言必须与原卡逐字一致（不能被改写）。"""
        repo_root = CARD_PATH.parents[4]
        legacy_candidates = [
            repo_root / "apps" / "dsn_study" / "character_cards" / "study_tutor.yaml",
            CARD_PATH.parent / "_legacy" / "study_tutor.yaml",
        ]
        legacy = next((p for p in legacy_candidates if p.is_file()), None)
        if legacy is None:
            pytest.skip("本机没有旧卡（已被 .gitignore 忽略），无法比对")
        legacy_card = CharacterCard.from_yaml_file(legacy)
        card = CharacterCard.from_yaml_file(CARD_PATH)
        for field in ("personality", "behavior", "speech_style", "values",
                      "emotional_traits"):
            assert getattr(card.natural_language, field) == \
                getattr(legacy_card.natural_language, field), field
        # 语料也不能丢
        assert [c.content for c in card.corpus] == \
            [c.content for c in legacy_card.corpus]

    def test_card_is_not_gitignored(self):
        """新卡目录**不能**被 .gitignore 命中（现状 character_cards/ 被忽略）。"""
        repo_root = CARD_PATH.parents[4]
        try:
            proc = subprocess.run(
                ["git", "check-ignore", "-q", str(CARD_PATH.relative_to(repo_root))],
                cwd=str(repo_root), capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as exc:   # pragma: no cover
            pytest.skip("git 不可用: %s" % exc)
        assert proc.returncode != 0, "角色卡被 .gitignore 忽略了"


# ══════════════════════════════════════════════════════════════
# 与真实底座（PEV3）的集成
# ══════════════════════════════════════════════════════════════

class _RowDB:
    """最小 DB 适配器 —— PEV3 需要 sqlite3.Row 工厂。"""

    def __init__(self):
        self._conn = sqlite3.connect(":memory:")
        self._conn.row_factory = sqlite3.Row

    def _get_connection(self):
        return self._conn


class TestRealPEV3:

    def _pv3(self):
        from harness.personality import PersonalitySystemV3
        pv3 = PersonalitySystemV3(
            db=_RowDB(),
            cards_dir=str(DEFAULT_CARDS_DIR),
            default_card_path=str(CARD_PATH),
        )
        pv3.init_tables()
        assert pv3.bind_user_card(1, "study_tutor")
        return pv3

    def test_prompt_block_with_real_pv3(self):
        engine = PersonaEngine(self._pv3())
        block = engine.prompt_block(1)
        assert "小舟" in block
        assert len(block) <= MAX_PROMPT_CHARS

    def test_feedback_updates_state_with_real_pv3(self):
        """人格闭环真的跑：interaction 计数增加、亲密度变化。"""
        engine = PersonaEngine(self._pv3())
        before = engine.status(1)
        engine.feedback(1, "谢谢！这道题终于搞懂了", "不客气", answer_correct=True)
        after = engine.status(1)
        assert after["total_interactions"] > before["total_interactions"]
        assert after["affinity"] != before["affinity"]
