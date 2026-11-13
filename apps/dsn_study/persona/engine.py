"""PersonaEngine —— dsn_study 的人格薄层。

底座是 ``harness/personality``（PEV3）：动力学 / 证据 / 审计 / 落库全在那边，
本模块只做 dsn_study 关心的四件事：

  1. **卡片管理** —— 版本化的角色卡目录（``persona/cards/``）+ 切换；
  2. **信号抽取** —— 见 ``signals.py``（零 LLM 的规则路径）；
  3. **提示词呈现** —— 只把「有意义的东西」放进 system prompt：
     档案正文 + 关系阶段 + 偏离基线（≥0.05）的特质，上限 800 字；
  4. **API 数据形状** —— ``status()`` 给前端一个稳定契约。

红线 R6：**任何异常都必须降级**（人格故障不能让整轮对话失败）。
因此本模块里每一个对外方法都是「先 try、再降级、绝不抛」。

接线方须知：PEV3 的 ``cards_dir`` 要指向本包的 ``cards/`` 目录，
否则 ``switch()`` 绑定不上（角色卡以这里为准，版本控制里只有这一份）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from harness.personality.character_card import CharacterCard
from harness.personality.events import PerceptionRecord
from harness.personality.traits import deviant_dimensions

from .signals import Signal, extract_signals

logger = logging.getLogger("StudyPersona")

__all__ = ["PersonaEngine", "MAX_PROMPT_CHARS", "DEFAULT_CARDS_DIR"]

#: 人格段落的长度上限（字）。
MAX_PROMPT_CHARS = 800

#: 版本化的角色卡目录（**进版本控制**）。
DEFAULT_CARDS_DIR = Path(__file__).resolve().parent / "cards"

#: 默认角色卡 id（与 Config.PERSONALITY_DEFAULT_CARD 对齐）。
DEFAULT_CARD_ID = "study_tutor"

#: 特质偏离基线多少才值得进 prompt（低于它就不展示 —— 没信息量的噪声）。
TRAIT_DEVIATION_THRESHOLD = 0.05

#: prompt 里最多列几个偏离特质。
MAX_PROMPT_TRAITS = 5

#: status() 里最多返回几个偏离特质。
MAX_STATUS_TRAITS = 20

#: 其它应用的人格标识 —— 出现在 dsn_study 的 prompt 里就是串味，必须清掉。
_FOREIGN_PERSONA_MARKERS = ("EXA", "本地电脑上的 AI 同事", "本地电脑上的AI同事")


def _sanitize(text: str) -> str:
    """清掉跨应用的人格串味（本包自己也不能引入这类问题）。"""
    for marker in _FOREIGN_PERSONA_MARKERS:
        if marker in text:
            logger.warning("人格段落出现其它应用的人格标识（已移除）: %s", marker)
            text = text.replace(marker, "")
    return text.strip()


class PersonaEngine:
    """dsn_study 的人格接入层（薄层：卡片 + 信号 + 呈现 + API 形状）。"""

    def __init__(self, pv3, *,
                 use_llm_judge: bool = False,
                 trace_sink: Optional[Callable[[dict], None]] = None,
                 cards_dir: str | Path | None = None):
        """
        :param pv3: ``harness.personality.PersonalitySystemV3`` 实例。
        :param use_llm_judge: True 时 ``feedback()`` 走 PEV3 的 LLM 判定
            （``analyze_interaction``）；默认 False —— 走规则信号，热路径不排队。
        :param trace_sink: 可观测回调，收到一条 dict（失败也会回调）。
        :param cards_dir: 角色卡目录，默认本包的 ``cards/``。
        """
        self._pv3 = pv3
        self._use_llm_judge = bool(use_llm_judge)
        self._trace_sink = trace_sink
        self._cards_dir = Path(cards_dir) if cards_dir else DEFAULT_CARDS_DIR

    # ── 公共属性 ──

    @property
    def cards_dir(self) -> Path:
        return self._cards_dir

    @property
    def use_llm_judge(self) -> bool:
        return self._use_llm_judge

    # ── 提示词呈现 ──

    def prompt_block(self, uid: int) -> str:
        """给 system prompt 的人格段落。

        **任何异常都必须降级成 '' 或一段安全文本，绝不能抛出去**（红线 R6）。

        只呈现有意义的东西：档案正文 + 关系阶段 + 偏离基线 ≥0.05 的特质。
        不塞 50 维原始向量、情绪向量、亲密度等级表。
        """
        try:
            return self._render_prompt(uid)
        except Exception:   # noqa: BLE001 —— 红线 R6：人格故障不能拖垮整轮对话
            logger.warning("人格段落生成失败（降级为空）", exc_info=True)
            return ""

    def _render_prompt(self, uid: int) -> str:
        status = self._safe_status(uid)

        card_id = str(status.get("card_id") or "")
        card = self._load_card(card_id) or self._load_card(self._default_card_id())
        if card is None:
            logger.warning("没有可用角色卡 —— 人格段落为空")
            return ""

        name = card.display_name or card.name or card.card_id
        intro = "你是「%s」" % name
        if card.description:
            desc = card.description.strip()
            intro += "，%s" % (desc if desc.endswith(("。", "！", "？")) else desc + "。")
        else:
            intro += "。"

        head = ["## 角色设定", intro]
        tail: list[str] = []

        stage = self._relation_stage(status)
        if stage:
            tail.append("关系阶段：%s。" % stage)

        traits = self._deviant_traits(uid, limit=MAX_PROMPT_TRAITS)
        trait_line = self._render_traits(traits)
        if trait_line:
            tail.append(trait_line)

        profile = self._profile_text(card)
        # 预算：固定段（标题/关系/性格）先占位，档案正文拿剩下的
        part_count = len(head) + len(tail) + (1 if profile else 0)
        reserved = sum(len(p) for p in head) + sum(len(p) for p in tail)
        reserved += max(0, part_count - 1)          # 换行符
        room = MAX_PROMPT_CHARS - reserved
        if not profile or room <= 0:
            profile = ""
        else:
            profile = profile[:room]

        parts = head + ([profile] if profile else []) + tail
        text = "\n".join(parts)
        if len(text) > MAX_PROMPT_CHARS:
            text = text[:MAX_PROMPT_CHARS]
        return _sanitize(text)

    @staticmethod
    def _profile_text(card: CharacterCard) -> str:
        """档案正文 —— 自然语言部分（逐字来自角色卡）。"""
        natural = getattr(card, "natural_language", None)
        if natural is None:
            return ""
        for part in (natural.personality, natural.behavior, natural.speech_style):
            text = (part or "").strip()
            if text:
                return text
        return (natural.combined() or "").strip()

    @staticmethod
    def _relation_stage(status: dict) -> str:
        """关系阶段（只给标签，不给等级表，也不给亲密度数值）。"""
        level = status.get("affinity_level")
        if isinstance(level, dict):
            return str(level.get("label") or "")
        if isinstance(level, str):
            return level.strip()
        return ""

    @staticmethod
    def _render_traits(traits: list[dict]) -> str:
        """偏离基线的特质 —— 一行，可读，不带维度编号。"""
        items = []
        for item in traits:
            name = str(item.get("name") or item.get("tid") or "")
            label = str(item.get("label") or "")
            if name and label.startswith(name):
                label = label[len(name):]
            if not name and not label:
                continue
            items.append(("%s %s" % (name, label)).strip())
        if not items:
            return ""
        return "当前性格：" + "、".join(items)

    # ── 状态回写 ──

    def feedback(self, uid: int, user_msg: str, reply: str, *,
                 answer_correct: bool | None = None,
                 answer_wrong: bool | None = None) -> None:
        """回写人格状态。

        **绝不阻塞调用方**：默认路径只做规则判定（零网络调用），
        之后由 PEV3 在本地推进状态；``use_llm_judge=True`` 时才会发起
        LLM 调用 —— 那条路径请由调用方放到后台线程（与既有 dsn_study
        的做法一致）。

        **绝不抛异常**：人格回写失败只记日志。
        """
        try:
            if self._use_llm_judge:
                self._feedback_llm(uid, user_msg, reply)
            else:
                self._feedback_rules(uid, user_msg, reply,
                                     answer_correct, answer_wrong)
        except Exception:   # noqa: BLE001 —— 回写失败不影响本轮对话
            logger.warning("人格回写失败（已忽略）", exc_info=True)
            self._trace({"event": "persona.feedback", "uid": uid, "ok": False,
                         "degraded": "exception"})

    def _feedback_rules(self, uid: int, user_msg: str, reply: str,
                        answer_correct: bool | None,
                        answer_wrong: bool | None) -> None:
        apply_event = getattr(self._pv3, "apply_event", None)
        if not callable(apply_event):
            # harness 侧还没提供 apply_event（老版本）—— 降级为「不做事」，
            # 记一条日志，绝不崩。
            logger.warning("PEV3 未提供 apply_event —— 人格回写降级（本次不推进状态）")
            self._trace({"event": "persona.feedback", "uid": uid, "path": "rules",
                         "ok": False, "degraded": "apply_event_missing"})
            return

        signals = extract_signals(user_msg, reply,
                                  answer_correct=answer_correct,
                                  answer_wrong=answer_wrong)
        signal: Optional[Signal] = signals[0] if signals else None
        if signal is not None:
            perception = PerceptionRecord(
                event_type=signal.event_type,
                intensity=signal.intensity,
                valence=signal.valence,
                attribution="dsn_study 规则信号",
                analysis=signal.reason,
            )
        else:
            # 规则没命中 → 用 PEV3 的关键词启发式兜底（同样零 LLM）。
            # **必须兜底**：否则没有信号的那一轮人格状态就不推进
            # （交互计数不增、亲密度不动），人格就"停"住了。
            perception = self._heuristic_perception(user_msg)
            if perception is None:
                self._trace({"event": "persona.feedback", "uid": uid, "path": "rules",
                             "ok": True, "degraded": "no_signal"})
                return
        self._call_apply_event(apply_event, uid, perception)
        # 用 perception 而不是 signal —— 兜底分支里 signal 可能是 None
        self._trace({"event": "persona.feedback", "uid": uid, "path": "rules",
                     "ok": True, "event_type": perception.event_type,
                     "intensity": perception.intensity,
                     "valence": perception.valence})

    def _heuristic_perception(self, user_msg: str) -> Optional[PerceptionRecord]:
        """PEV3 的关键词启发式分类（零 LLM）作为兜底。"""
        classify = getattr(self._pv3, "classify_heuristic", None)
        if not callable(classify):
            return None
        try:
            perception = classify(user_msg or "")
        except Exception:   # noqa: BLE001
            logger.warning("启发式兜底分类失败（跳过本轮回写）", exc_info=True)
            return None
        if perception is None:
            return None
        try:
            perception.analysis = perception.analysis or "启发式兜底分类"
        except Exception:   # noqa: BLE001
            pass
        return perception

    @staticmethod
    def _call_apply_event(apply_event: Callable, uid: int,
                          perception: PerceptionRecord):
        """调用 PEV3.apply_event —— 兼容签名漂移（老版本没有 conversation_history）。"""
        try:
            return apply_event(uid, perception, conversation_history="")
        except TypeError:
            logger.debug("apply_event 签名不兼容，去掉 conversation_history 重试")
            return apply_event(uid, perception)

    def _feedback_llm(self, uid: int, user_msg: str, reply: str) -> None:
        analyze = getattr(self._pv3, "analyze_interaction", None)
        if not callable(analyze):
            logger.warning("PEV3 未提供 analyze_interaction —— 人格回写降级")
            self._trace({"event": "persona.feedback", "uid": uid, "path": "llm",
                         "ok": False, "degraded": "analyze_interaction_missing"})
            return
        analyze(uid, user_msg, reply, conversation_history="")
        self._trace({"event": "persona.feedback", "uid": uid, "path": "llm",
                     "ok": True})

    # ── 状态查询 ──

    def status(self, uid: int) -> dict:
        """人格状态（API 契约形状）。

        ``{uid, card_id, affinity, affinity_level, total_interactions,
        mood, traits, evidence_total, last_updated}``
        """
        data = {
            "uid": int(uid),
            "card_id": "",
            "affinity": 0.0,
            "affinity_level": {},
            "total_interactions": 0,
            "mood": {},
            "traits": [],
            "evidence_total": 0,
            "last_updated": "",
        }
        raw = self._safe_status(uid)
        data["card_id"] = str(raw.get("card_id") or "")
        try:
            data["affinity"] = float(raw.get("affinity_value") or 0.0)
        except (TypeError, ValueError):
            data["affinity"] = 0.0
        try:
            data["total_interactions"] = int(raw.get("total_interactions") or 0)
        except (TypeError, ValueError):
            data["total_interactions"] = 0
        try:
            data["evidence_total"] = int(raw.get("evidence_total") or 0)
        except (TypeError, ValueError):
            data["evidence_total"] = 0

        mood = raw.get("mood") or {}
        if isinstance(mood, dict):
            data["mood"] = {str(k): float(v) for k, v in mood.items()
                            if isinstance(v, (int, float))}

        level = raw.get("affinity_level")
        if isinstance(level, (dict, str)):
            data["affinity_level"] = level

        data["traits"] = self._deviant_traits(uid, limit=MAX_STATUS_TRAITS)
        data["last_updated"] = self._last_updated(uid)
        return data

    def _safe_status(self, uid: int) -> dict:
        """读 PEV3 状态 —— 失败时降级为空 dict，不抛。"""
        try:
            raw = self._pv3.get_personality_status(uid) or {}
        except Exception:   # noqa: BLE001
            logger.warning("人格状态读取失败（已降级）", exc_info=True)
            return {}
        return raw if isinstance(raw, dict) else {}

    def _indicator_vector(self, uid: int) -> dict:
        """50 维特质向量 —— 只在内部用，**绝不进 prompt**。

        优先取「稳定特质中心」（蒸馏产物 = 真正演化出来的那份性格）。
        PEV3 对外暴露的 ``indicator_vector`` 是**瞬时**向量 = 蒸馏值 +
        每小时噪声 + 情绪调制 + 时间漂移 —— 拿它当「人格特质」会把噪声
        当成性格（刚建好的卡会莫名其妙冒出五条「略偏健谈」）。
        拿不到稳定向量时再退化到公开接口。
        """
        stable = self._stable_vector(uid)
        if stable:
            return stable
        try:
            full = self._pv3.get_personality_full(uid) or {}
        except Exception:   # noqa: BLE001
            logger.debug("人格全量状态读取失败（已忽略）", exc_info=True)
            return {}
        if not isinstance(full, dict):
            return {}
        vector = full.get("indicator_vector") or {}
        if not isinstance(vector, dict):
            return {}
        return {str(k): float(v) for k, v in vector.items()
                if isinstance(v, (int, float))}

    def _stable_vector(self, uid: int) -> dict:
        """稳定特质中心 —— 取不到就返回空 dict（走公开接口兜底）。"""
        try:
            state = getattr(self._pv3, "_state_manager", None)
            if state is None:
                return {}
            snapshot = state.get_current_snapshot(uid)
            if snapshot is None:
                return {}
            vector = getattr(snapshot, "stable_indicator_vector", None) or {}
            if not isinstance(vector, dict):
                return {}
            return {str(k): float(v) for k, v in vector.items()
                    if isinstance(v, (int, float))}
        except Exception:   # noqa: BLE001
            logger.debug("稳定特质向量读取失败（已忽略）", exc_info=True)
            return {}

    def _deviant_traits(self, uid: int, limit: int = MAX_STATUS_TRAITS) -> list[dict]:
        """偏离基线的特质维度。"""
        vector = self._indicator_vector(uid)
        if not vector:
            return []
        try:
            deviants = deviant_dimensions(vector, threshold=TRAIT_DEVIATION_THRESHOLD)
        except Exception:   # noqa: BLE001
            logger.debug("偏离特质计算失败（已忽略）", exc_info=True)
            return []
        return list(deviants)[:limit]

    def _last_updated(self, uid: int) -> str:
        """最近一次人格状态变化的时间（ISO 字符串；没有则空串）。"""
        getter = getattr(self._pv3, "get_recent_events", None)
        if not callable(getter):
            return ""
        try:
            rows = getter(uid=uid, limit=1) or []
        except Exception:   # noqa: BLE001
            logger.debug("最近事件读取失败（已忽略）", exc_info=True)
            return ""
        if not rows:
            return ""
        ts = rows[0].get("ts")
        try:
            return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
        except (TypeError, ValueError):
            return ""

    # ── 卡片管理 ──

    def cards(self) -> list[dict]:
        """可用角色卡清单（读版本化的 ``cards/`` 目录）。"""
        result: list[dict] = []
        try:
            paths = sorted(self._cards_dir.glob("*.yaml"))
        except Exception:   # noqa: BLE001
            logger.warning("角色卡目录不可读（已忽略）: %s", self._cards_dir,
                           exc_info=True)
            return result
        for path in paths:
            try:
                card = CharacterCard.from_yaml_file(path)
            except Exception:   # noqa: BLE001
                logger.warning("角色卡解析失败（已跳过）: %s", path, exc_info=True)
                continue
            result.append({
                "card_id": card.card_id or path.stem,
                "name": card.name,
                "display_name": card.display_name or card.name,
                "description": card.description,
                "version": card.version,
                "path": str(path),
            })
        return result

    def switch(self, uid: int, card_id: str) -> bool:
        """切换用户绑定的角色卡。失败返回 False（不抛）。"""
        card_id = str(card_id or "").strip()
        if not card_id:
            return False
        try:
            if self._load_card(card_id) is None:
                logger.warning("切换失败：角色卡不存在 card_id=%s", card_id)
                self._trace({"event": "persona.switch", "uid": uid,
                             "card_id": card_id, "ok": False,
                             "degraded": "card_not_found"})
                return False
            ok = bool(self._pv3.bind_user_card(uid, card_id))
            self._trace({"event": "persona.switch", "uid": uid,
                         "card_id": card_id, "ok": ok})
            return ok
        except Exception:   # noqa: BLE001
            logger.warning("角色卡切换失败（已忽略）", exc_info=True)
            self._trace({"event": "persona.switch", "uid": uid,
                         "card_id": card_id, "ok": False,
                         "degraded": "exception"})
            return False

    # ── 内部工具 ──

    def _load_card(self, card_id: str) -> Optional[CharacterCard]:
        """读角色卡 —— 先看版本化目录，再问 PEV3。"""
        if not card_id:
            return None
        try:
            path = self._cards_dir / ("%s.yaml" % card_id)
            if path.exists():
                return CharacterCard.from_yaml_file(path)
        except Exception:   # noqa: BLE001
            logger.warning("本地角色卡读取失败（转问 PEV3）card_id=%s", card_id,
                           exc_info=True)
        try:
            return self._pv3.get_card(card_id)
        except Exception:   # noqa: BLE001
            logger.warning("PEV3 角色卡读取失败 card_id=%s", card_id, exc_info=True)
            return None

    @staticmethod
    def _default_card_id() -> str:
        """默认角色卡 id —— 跟 Config.PERSONALITY_DEFAULT_CARD 走。"""
        try:
            from apps.dsn_study import config
            name = str(getattr(config.Config, "PERSONALITY_DEFAULT_CARD", "") or "")
            stem = Path(name).stem
            if stem:
                return stem
        except Exception:   # noqa: BLE001
            logger.debug("读取 Config.PERSONALITY_DEFAULT_CARD 失败（用默认值）",
                         exc_info=True)
        return DEFAULT_CARD_ID

    def _trace(self, payload: dict) -> None:
        """可观测回调 —— 回调自己挂了也不能影响主流程。"""
        sink = self._trace_sink
        if sink is None:
            return
        try:
            sink(payload)
        except Exception:   # noqa: BLE001
            logger.debug("人格 trace 回调失败（已忽略）", exc_info=True)
