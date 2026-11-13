# apps/harness_lab/runner.py
"""场景执行器 —— 拉起 harness 的记忆与人格子系统，跑脚本化交互，收观测数据。"""

from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from .checks import CHECKS, CheckOutcome, LabContext
from .clients import LiveChat, ScriptedChat, StubSummaryService, build_live_client
from .config import CARDS_SRC_DIR, LabConfig
from .scenarios import SCENARIOS, Scenario

logger = logging.getLogger("HarnessLab.Runner")


@dataclass
class CheckResult:
    id: str
    domain: str
    desc: str
    passed: bool
    detail: str = ""
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "domain": self.domain, "desc": self.desc,
            "passed": self.passed, "detail": self.detail, "evidence": self.evidence,
        }


@dataclass
class ScenarioResult:
    scenario_id: str
    title: str
    direction: str
    kind: str
    ok: bool = True
    error: str = ""
    checks: list[CheckResult] = field(default_factory=list)
    data: dict = field(default_factory=dict)
    duration_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "scenario_id": self.scenario_id, "title": self.title,
            "direction": self.direction, "kind": self.kind,
            "ok": self.ok, "error": self.error,
            "checks": [c.to_dict() for c in self.checks],
            "data": self.data, "duration_ms": self.duration_ms,
        }


# ══════════════════════════════════════════════════════════════
# 工作区准备
# ══════════════════════════════════════════════════════════════

def _make_client(cfg: LabConfig):
    """按配置选客户端。真实模式拿不到凭据就直接报错 —— 绝不静默退回桩。"""
    if not cfg.is_live:
        return ScriptedChat(honor_max_tokens=cfg.honor_max_tokens)
    client = build_live_client()
    if client is None:
        raise RuntimeError(
            "--llm live 需要凭据：请设置 OPENAI_API_KEY 与 OPENAI_API_BASE"
            "（或改用默认的 --llm scripted）")
    return LiveChat(client)


def _reset_dir(path: Path) -> Path:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _prepare_cards(cards_dir: Path) -> None:
    cards_dir.mkdir(parents=True, exist_ok=True)
    for src in CARDS_SRC_DIR.glob("*.yaml"):
        shutil.copy2(src, cards_dir / src.name)


def _seed_baseline_distillation(cards_dir: Path, card_id: str) -> None:
    """预置一份"基线蒸馏产物"。

    为什么要有它：生产线上 `study_tutor.distilled.json` 存在（内容已退化），
    所以 `ensure_user_bound` 不会触发后台蒸馏；验证台若从零开始，
    `warmup_distillation` 会在后台线程里抢桩客户端、污染观测。
    这里复刻线上那份**退化产物**的形态，保证人格场景的初始条件与线上一致。
    """
    from harness.personality.traits import TRAIT_IDS

    card_path = cards_dir / f"{card_id}.yaml"
    foundation = ""
    if card_path.exists():
        try:
            from harness.personality.character_card import CharacterCard
            card = CharacterCard.from_yaml_file(card_path)
            foundation = card.natural_language.combined()
        except Exception:
            foundation = ""
    payload = {
        "distillation_id": f"distill_{card_id}_baseline",
        "card_id": card_id,
        "version": 1,
        "content_fingerprint": "sha256:labbaseline",
        "model_used": "lab-baseline",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "foundation_description": foundation,
        "behavioral_patterns": [],
        "speech_patterns": [],
        "emotional_model": {},
        "relational_model": {},
        "indicator_vector": {tid: 0.5 for tid in TRAIT_IDS},
        "trait_narrative": {},
    }
    (cards_dir / f"{card_id}.distilled.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _redirect_distill_logs(workspace: Path):
    """把蒸馏日志重定向到场景工作区。

    顺带记录一个事实：harness 把蒸馏日志硬编码到**仓库根**的 `logs/distill/`
    （`distillation_engine.py:246`），与部署目录无关，打包即失效。
    """
    from harness.personality import distillation_engine as de

    log_dir = workspace / "logs" / "distill"
    log_dir.mkdir(parents=True, exist_ok=True)

    def _patched(self, card_id, pass_name, prompt, reply):
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            (log_dir / f"{card_id}_{ts}_{pass_name}_prompt.txt").write_text(prompt, encoding="utf-8")
            (log_dir / f"{card_id}_{ts}_{pass_name}_reply.txt").write_text(reply, encoding="utf-8")
        except Exception:
            pass

    de.DistillationEngine._log_distill_pass = _patched
    return log_dir


def _rewind_last_interaction(db, uid: int, days: float) -> None:
    """把用户的 last_interaction_ts 往前拨 —— 验证台的"时间旅行"。"""
    conn = db.get_connection()
    ts = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    conn.execute(
        "UPDATE user_character_cards SET last_interaction_ts=? WHERE uid=?", (ts, uid))
    conn.commit()


# ══════════════════════════════════════════════════════════════
# 人格场景
# ══════════════════════════════════════════════════════════════

def run_persona_scenario(sc: Scenario, cfg: LabConfig) -> tuple[dict, LabContext]:
    from harness.personality import PersonalitySystemV3
    from infra.store.sqlite import SqliteStore

    ws = _reset_dir(cfg.scenario_dir(sc.id))
    cards_dir = ws / "cards"
    _prepare_cards(cards_dir)
    db_path = ws / "persona.db"

    chat = _make_client(cfg)
    judge_source = "model" if cfg.is_live else "scripted"
    store = SqliteStore(str(db_path))
    _redirect_distill_logs(ws)

    pv3 = PersonalitySystemV3(
        db=store,
        personality_model_chat=chat,
        distillation_chat=chat,
        fast_distillation_chat=chat,
        cards_dir=cards_dir,
        default_card_path=str(cards_dir / f"{sc.card_id}.yaml"),
    )
    pv3.init_tables()

    # 空白卡：走 create_blank（随机初始向量 + 从零演化）
    if sc.card_id == "blank_companion":
        card = pv3.create_blank_card(card_id="blank_companion", name="空白伙伴",
                                     seed=20261111, randomize_traits=True)
        data_card = card
    else:
        _seed_baseline_distillation(cards_dir, sc.card_id)
        data_card = pv3.get_card(sc.card_id)

    uid = cfg.uid
    pv3.ensure_user_bound(uid)
    bound = pv3._state_manager.get_or_create_binding(uid)
    bound_card_id = getattr(bound, "card_id", "") if bound else ""

    series: list[dict] = []
    for i, turn in enumerate(sc.turns, start=1):
        if turn.advance_days:
            # 先 flush：pending 缓冲里的 last_interaction_ts 会以 read-your-writes
            # 的方式盖住 DB 里的值（V3Persistence.get_user_active_card），不回拨就白拨。
            pv3.flush()
            _rewind_last_interaction(store, uid, turn.advance_days)
        if judge_source == "scripted":
            chat.push_judge(turn.event, turn.intensity, turn.valence)
        before = pv3._state_manager.get_current_snapshot(uid)
        result = pv3.analyze_interaction(uid, turn.user, turn.reply, judge_chat=chat)
        after = pv3._state_manager.get_current_snapshot(uid)
        series.append({
            "turn": i,
            "event": result.analysis and None or None,   # 占位，下面用 audit 补
            "affinity_before": float(before.affinity_value if before else 20.0),
            "affinity_after": float(result.new_affinity),
            "delta": float(result.affinity_delta),
            "mood_before": dict(result.old_mood),
            "mood_after": dict(result.new_mood),
            "mood_delta": dict(result.mood_delta),
            "rule_id": result.rule_id,
            "advance_days": turn.advance_days,
            "scripted_event": turn.event,
        })

    # 审计表里取真实判定的事件类型（分析文本不可靠，用 event_type 列）
    conn = store.get_connection()
    audit_rows = []
    try:
        rows = conn.execute(
            "SELECT event_type, intensity, signal, rule_id, old_affinity, new_affinity, "
            "affinity_delta, analysis FROM personality_audit WHERE uid=? ORDER BY id",
            (uid,)).fetchall()
        for r in rows:
            audit_rows.append({
                "event_type": r["event_type"], "intensity": r["intensity"],
                "signal": r["signal"], "rule_id": r["rule_id"],
                "old_affinity": r["old_affinity"], "new_affinity": r["new_affinity"],
                "affinity_delta": r["affinity_delta"], "analysis": (r["analysis"] or "")[:120],
            })
    except Exception as exc:
        logger.warning("读取审计表失败: %s", exc)

    for idx, row in enumerate(series):
        if idx < len(audit_rows):
            series[idx]["event"] = audit_rows[idx]["event_type"]
            series[idx]["intensity"] = audit_rows[idx]["intensity"]
        else:
            series[idx]["event"] = series[idx]["scripted_event"]
            series[idx]["intensity"] = next(
                (t.intensity for t in sc.turns if t.event == series[idx]["event"]), "medium")

    # 证据状态
    ev = pv3._evidence
    evidence = {
        "total": ev.get_total(sc.card_id),
        "counts": {k: v for k, v in (ev._counts.get(sc.card_id) or {}).items() if v},
        "mu": {k: v for k, v in (ev.get_mu(sc.card_id) or {}).items()
               if abs(float(v) - 0.5) > 1e-6},
    }

    # 人格提示词
    prompt = ""
    try:
        prompt = pv3.generate_personality_prompt(uid) or ""
    except Exception as exc:
        logger.warning("生成人格提示词失败: %s", exc)

    # ── 重启演练 1：显式 flush 后重启 ──
    evidence_before_restart = {
        "total": ev.get_total(sc.card_id),
        "mu": {k: v for k, v in ev.get_mu(sc.card_id).items()
               if abs(float(v) - 0.5) > 1e-6},
        "pending": ev.get_pending(sc.card_id),
    }
    pv3.flush()
    snap_before = pv3._state_manager.get_current_snapshot(uid)
    store_b = SqliteStore(str(db_path))
    pv3_b = PersonalitySystemV3(db=store_b, personality_model_chat=chat,
                                distillation_chat=chat, fast_distillation_chat=chat,
                                cards_dir=cards_dir,
                                default_card_path=str(cards_dir / f"{sc.card_id}.yaml"))
    pv3_b.init_tables()
    snap_after = pv3_b._state_manager.get_current_snapshot(uid)
    ev_b = pv3_b._evidence
    evidence_after_restart = {
        "total": ev_b.get_total(sc.card_id),
        "mu": {k: v for k, v in ev_b.get_mu(sc.card_id).items()
               if abs(float(v) - 0.5) > 1e-6},
        "pending": ev_b.get_pending(sc.card_id),
    }

    # ── 重启演练 2：不 flush 直接重启（换一个 uid 保证 pending 计数可控）──
    uid2 = uid + 900
    pv3.ensure_user_bound(uid2)
    chat.push_judge("praise", "medium", "positive")
    pv3.analyze_interaction(uid2, "验证台：一次不经 flush 的交互", "收到", judge_chat=chat)
    nf_before = pv3._state_manager.get_current_snapshot(uid2)
    store_c = SqliteStore(str(db_path))
    pv3_c = PersonalitySystemV3(db=store_c, personality_model_chat=chat,
                                distillation_chat=chat, fast_distillation_chat=chat,
                                cards_dir=cards_dir,
                                default_card_path=str(cards_dir / f"{sc.card_id}.yaml"))
    pv3_c.init_tables()
    nf_after = pv3_c._state_manager.get_current_snapshot(uid2)

    distilled_path = cards_dir / f"{sc.card_id}.distilled.json"
    distilled_after = {}
    if distilled_path.exists():
        try:
            distilled_after = json.loads(distilled_path.read_text(encoding="utf-8"))
        except Exception:
            distilled_after = {}

    def _snap(s):
        if s is None:
            return {}
        return {
            "affinity_value": float(s.affinity_value),
            "total_interactions": int(s.total_interactions),
            "mood": {k: round(float(v), 4) for k, v in (s.mood_state or {}).items()},
        }

    data = {
        "card": data_card,
        "judge_source": judge_source,
        "bound_card_id": bound_card_id,
        "series": series,
        "audit_rows": audit_rows,
        "evidence": evidence,
        "persona_prompt": prompt,
        "snapshot_before_restart": _snap(snap_before),
        "snapshot_after_restart": _snap(snap_after),
        "snapshot_before_restart_noflush": _snap(nf_before),
        "snapshot_after_restart_noflush": _snap(nf_after),
        "distilled_after": distilled_after,
        "evidence_before_restart": evidence_before_restart,
        "evidence_after_restart": evidence_after_restart,
        "pending_before_restart": evidence_before_restart.get("pending", 0),
        "pending_after_restart": evidence_after_restart.get("pending", 0),
        "calls": chat.summary(),
        "workspace": str(ws),
    }
    ctx = LabContext(scenario=sc, data=data, workspace=ws, chat=chat, personality=pv3)
    return data, ctx


# ══════════════════════════════════════════════════════════════
# 蒸馏场景
# ══════════════════════════════════════════════════════════════

def run_distillation_scenario(sc: Scenario, cfg: LabConfig) -> tuple[dict, LabContext]:
    from harness.personality import PersonalitySystemV3
    from infra.store.sqlite import SqliteStore

    ws = _reset_dir(cfg.scenario_dir(sc.id))
    cards_dir = ws / "cards"
    _prepare_cards(cards_dir)
    db_path = ws / "persona.db"

    chat = _make_client(cfg)
    store = SqliteStore(str(db_path))
    _redirect_distill_logs(ws)

    pv3 = PersonalitySystemV3(
        db=store,
        personality_model_chat=chat,
        distillation_chat=chat,
        fast_distillation_chat=chat,
        cards_dir=cards_dir,
        default_card_path=str(cards_dir / f"{sc.card_id}.yaml"),
    )
    pv3.init_tables()

    before_calls = len(chat.calls)
    error = ""
    traits = None
    try:
        traits = pv3.distill(sc.card_id)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        logger.warning("蒸馏失败: %s", error)

    distill_calls = [c.brief() for c in chat.calls[before_calls:]]
    # 响应正文单独留着做证据
    for brief, call in zip(distill_calls, chat.calls[before_calls:]):
        brief["response_head"] = call.response[:180]
        brief["response_tail"] = call.response[-120:]

    distilled_path = cards_dir / f"{sc.card_id}.distilled.json"
    distilled_after = {}
    if distilled_path.exists():
        try:
            distilled_after = json.loads(distilled_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("读取蒸馏产物失败: %s", exc)

    data = {
        "distill_calls": distill_calls,
        "distilled_after": distilled_after,
        "distill_error": error,
        "traits_present": traits is not None,
        "calls": chat.summary(),
        "workspace": str(ws),
    }
    ctx = LabContext(scenario=sc, data=data, workspace=ws, chat=chat, personality=pv3)
    return data, ctx


# ══════════════════════════════════════════════════════════════
# 记忆场景
# ══════════════════════════════════════════════════════════════

class _NullEmbeddingClient:
    """忠实复刻真实嵌入客户端的失败语义：**返回 None**，不抛异常。

    `OpenAIEmbeddingClient.embed` 的契约就是「失败返回 None（不抛异常）」。
    桩若抛异常，验证的就是线上不存在的行为 —— 那会制造假故障。
    """

    def __init__(self):
        self.calls = 0

    def embed(self, text: str):
        self.calls += 1
        return None


class _RaisingEmbeddingClient:
    """极端嵌入客户端：直接抛异常。用于验证记忆写入路径的**防御性**。"""

    def __init__(self):
        self.calls = 0

    def embed(self, text: str):
        self.calls += 1
        raise RuntimeError("验证台注入的嵌入异常")


def run_memory_scenario(sc: Scenario, cfg: LabConfig) -> tuple[dict, LabContext]:
    from apps.dsn_study.db.question_bank import QuestionBankDBManager
    from apps.dsn_study.memory.core import MemorySystem
    from apps.dsn_study.memory.summary import LLMSummaryModel

    ws = _reset_dir(cfg.scenario_dir(sc.id))
    db_path = ws / "memory.db"

    db = QuestionBankDBManager(db_path=str(db_path))
    summary = LLMSummaryModel(StubSummaryService())
    embedding = _NullEmbeddingClient()
    ms = MemorySystem(db, summary_model=summary, embedding_client=embedding)
    # 强制打开嵌入路径：线上由 MEMORY_EMBEDDING_ENABLED 控制，默认关闭，
    # 这里显式打开才能验证"嵌入失败也不打断写入"。
    ms._embedding_enabled = True

    data = {"workspace": str(ws), "embedding_calls": 0}
    ctx = LabContext(scenario=sc, data=data, workspace=ws, memory=ms)
    return data, ctx


# ══════════════════════════════════════════════════════════════
# 上下文场景
# ══════════════════════════════════════════════════════════════

def run_context_scenario(sc: Scenario, cfg: LabConfig) -> tuple[dict, LabContext]:
    from harness.context_assembly import (
        ContextBudget, ContextSegment, SegmentedContextAssembler,
        PRIORITY_ACTIVE, PRIORITY_CURRENT, PRIORITY_MEMO, PRIORITY_TAIL,
        SEG_MEMO, SEG_TAIL, SEG_VERBATIM,
    )

    ws = _reset_dir(cfg.scenario_dir(sc.id))

    budget = ContextBudget(memo_chars=2000, summary_chars=2000,
                           verbatim_chars=6000, tail_rounds=3, max_open_topics=3)
    assembler = SegmentedContextAssembler(budget)

    # 1) 备忘段：一条超长的备忘，探"首条 memo 是否受独立预算约束"
    memo_seg = ContextSegment(kind=SEG_MEMO, content="备" * 5000,
                              priority=PRIORITY_MEMO, label="[备忘]",
                              truncatable=True)
    plan_memo = assembler.plan([memo_seg])
    memo_kept = sum(len(s.content) for s in plan_memo.kept)

    # 2) 纯度探针：同一个段对象 plan 两次，看入参有没有被改
    purity_seg = ContextSegment(kind=SEG_MEMO, content="纯" * 5000,
                                 priority=PRIORITY_MEMO, label="[纯度]",
                                 truncatable=True)
    before_len = len(purity_seg.content)
    assembler.plan([purity_seg])
    after_len = len(purity_seg.content)
    plan2 = assembler.plan([purity_seg])
    purity_second = sum(len(s.content) for s in plan2.kept)

    # 3) 截断方向探针：一段长原文
    original = "".join(f"[第{i}轮] 这是一段中段内容，用来验证截断到底保住了哪一头。" for i in range(60))
    verbatim_seg = ContextSegment(kind=SEG_VERBATIM, content=original,
                                  priority=PRIORITY_CURRENT, label="[当前话题]",
                                  truncatable=True)
    tail_text = "用户：最后一句\n助手：最后一句回复"
    tail_seg = ContextSegment(kind=SEG_TAIL, content=tail_text,
                              priority=PRIORITY_TAIL, label="[最近对话]",
                              truncatable=False, unbounded=True)

    segments = [memo_seg, verbatim_seg, tail_seg]
    plan = assembler.plan(segments)
    messages = assembler.assemble(segments)
    output = "\n".join(m.get("content", "") for m in messages if isinstance(m, dict))
    total_chars = sum(len(m.get("content", "")) for m in messages if isinstance(m, dict))

    truncated_seg = None
    for seg in plan.truncated:
        if seg.kind == SEG_VERBATIM:
            truncated_seg = seg
            break
    if truncated_seg is None:
        truncated_seg = next((s for s in plan.kept if s.kind == SEG_VERBATIM), None)

    data = {
        "workspace": str(ws),
        "assembly": {
            "total_chars": total_chars,
            "budget_chars": budget.memo_chars + budget.summary_chars + budget.verbatim_chars,
            "tail_text": tail_text,
            "output": output,
            "kept": len(plan.kept), "dropped": len(plan.dropped),
            "truncated": len(plan.truncated),
            "plan_total_chars": plan.total_chars,
        },
        "memo_probe": {"kept_chars": memo_kept, "memo_chars": budget.memo_chars},
        "purity_probe": {"before_chars": before_len, "after_chars": after_len,
                          "second_plan_same": purity_second == memo_kept},
        "truncation_probe": {
            "kept": truncated_seg.content if truncated_seg else "",
            "original": original,
        },
    }
    ctx = LabContext(scenario=sc, data=data, workspace=ws)
    return data, ctx


# ══════════════════════════════════════════════════════════════
# 调度
# ══════════════════════════════════════════════════════════════

_RUNNERS = {
    "persona": run_persona_scenario,
    "distillation": run_distillation_scenario,
    "memory": run_memory_scenario,
    "context": run_context_scenario,
}


def run_scenario(sc: Scenario, cfg: LabConfig) -> ScenarioResult:
    t0 = time.time()
    result = ScenarioResult(scenario_id=sc.id, title=sc.title,
                             direction=sc.direction, kind=sc.kind)
    try:
        data, ctx = _RUNNERS[sc.kind](sc, cfg)
        result.data = {k: v for k, v in data.items() if k not in ("card",)}
    except Exception as exc:
        result.ok = False
        result.error = f"{type(exc).__name__}: {exc}"
        logger.exception("场景 %s 执行失败", sc.id)
        result.duration_ms = (time.time() - t0) * 1000
        return result

    for check_id in sc.checks:
        check = CHECKS.get(check_id)
        if check is None:
            result.checks.append(CheckResult(id=check_id, domain="?", desc="检查项未注册",
                                             passed=False, detail="检查项未注册"))
            continue
        try:
            outcome = check.fn(ctx)
        except Exception as exc:
            outcome = CheckOutcome(False, f"检查项执行异常：{type(exc).__name__}: {exc}")
        result.checks.append(CheckResult(
            id=check.id, domain=check.domain, desc=check.desc,
            passed=outcome.passed, detail=outcome.detail, evidence=outcome.evidence))

    result.duration_ms = (time.time() - t0) * 1000
    return result


def run_all(cfg: LabConfig) -> list[ScenarioResult]:
    cfg.ensure_dirs()
    selected = [s for s in SCENARIOS if not cfg.only or s.id in cfg.only]
    results = []
    for sc in selected:
        logger.info("运行场景: %s", sc.id)
        results.append(run_scenario(sc, cfg))
    return results
