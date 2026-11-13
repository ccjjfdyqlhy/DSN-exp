# apps/harness_lab/checks.py
"""验证检查项 —— 断言的是「应该发生什么」，不是「现在是什么」。
#
# 每条检查项实现为一个纯函数：吃一个 :class:`LabContext`（场景跑完后收集到的
# 观测数据），吐一个 :class:`CheckOutcome`。
#
# **FAIL 是有价值的结果**：它意味着「harness 的实际行为」与「它自己文档里
# 承诺的行为」不一致 —— 那正是这个验证台要回答的问题。
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .scenarios import Scenario


@dataclass
class CheckOutcome:
    passed: bool
    detail: str = ""
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"passed": self.passed, "detail": self.detail, "evidence": self.evidence}


@dataclass
class Check:
    id: str
    domain: str
    desc: str
    fn: Callable[["LabContext"], CheckOutcome]


@dataclass
class LabContext:
    """检查项能看到的全部东西。"""

    scenario: Scenario
    data: dict = field(default_factory=dict)
    workspace: Any = None
    chat: Any = None
    personality: Any = None
    memory: Any = None
    extra: dict = field(default_factory=dict)


CHECKS: dict[str, Check] = {}


def register(check_id: str, domain: str, desc: str):
    def deco(fn):
        CHECKS[check_id] = Check(id=check_id, domain=domain, desc=desc, fn=fn)
        return fn
    return deco


def _ok(detail: str, **evidence) -> CheckOutcome:
    return CheckOutcome(True, detail, evidence)


def _fail(detail: str, **evidence) -> CheckOutcome:
    return CheckOutcome(False, detail, evidence)


def _series(ctx: LabContext) -> list[dict]:
    return ctx.data.get("series") or []


def _first_affinity(ctx: LabContext) -> float:
    s = _series(ctx)
    return float(s[0]["affinity_before"]) if s else 20.0


def _last_affinity(ctx: LabContext) -> float:
    s = _series(ctx)
    return float(s[-1]["affinity_after"]) if s else 20.0


def _mood(ctx: LabContext, key: str, which: str = "after") -> float:
    s = _series(ctx)
    if not s:
        return 0.0
    return float(s[-1][f"mood_{which}"].get(key, 0.0))


# ══════════════════════════════════════════════════════════════
# 人格 · 基础契约
# ══════════════════════════════════════════════════════════════

@register("persona.card_valid", "persona", "角色卡可加载、可校验")
def _card_valid(ctx: LabContext) -> CheckOutcome:
    card = ctx.data.get("card")
    if not card:
        return _fail("角色卡未加载", workspace=str(ctx.workspace))
    errors = card.validate()
    if errors:
        return _fail("角色卡校验未通过", errors=errors, card_id=card.card_id)
    return _ok("角色卡加载并通过校验", card_id=card.card_id, name=card.name,
               natural_language_fields=len(card.natural_language.combined()))


@register("persona.auto_bind", "persona", "首次交互自动绑定角色卡")
def _auto_bind(ctx: LabContext) -> CheckOutcome:
    bound = ctx.data.get("bound_card_id")
    expected = ctx.scenario.card_id
    if not bound:
        return _fail("ensure_user_bound 后没有绑定记录", expected=expected)
    if bound != expected:
        return _fail("绑定的卡与预期不符", bound=bound, expected=expected)
    return _ok("用户已自动绑定到预期角色卡", bound_card_id=bound)


@register("persona.judge_event_adopted", "persona", "语义判定结果被原样采纳")
def _judge_adopted(ctx: LabContext) -> CheckOutcome:
    if ctx.data.get("judge_source") == "model":
        # 真实模式：事件由模型自己判定，只要求落在合法枚举里。
        from harness.personality.events import VALID_EVENT_TYPES
        actual = [row.get("event") for row in _series(ctx)]
        bad = [e for e in actual if e not in VALID_EVENT_TYPES]
        if bad:
            return _fail("模型给出了非法的事件类型", invalid=bad, actual=actual)
        return _ok("模型的判定都落在合法事件枚举内", events=actual)
    expected = [t.event for t in ctx.scenario.turns]
    actual = [row.get("event") for row in _series(ctx)]
    if actual != expected:
        return _fail("判定事件与脚本不一致", expected=expected, actual=actual)
    return _ok("每轮事件分类都与脚本一致", turns=len(actual), events=sorted(set(actual)))


@register("persona.prompt_generated", "persona", "人格提示词可生成且包含角色身份")
def _prompt_generated(ctx: LabContext) -> CheckOutcome:
    prompt = ctx.data.get("persona_prompt") or ""
    if not prompt.strip():
        return _fail("generate_personality_prompt 返回空")
    card = ctx.data.get("card")
    name = getattr(card, "display_name", "") or getattr(card, "name", "")
    if name and name not in prompt:
        return _fail("提示词里没有角色名", name=name, prompt_head=prompt[:200])
    return _ok("人格提示词生成成功且包含角色名", chars=len(prompt), name=name)


@register("persona.prompt_no_foreign_persona", "persona", "提示词不含其它应用的人格串味")
def _prompt_no_foreign(ctx: LabContext) -> CheckOutcome:
    prompt = ctx.data.get("persona_prompt") or ""
    foreign = [w for w in ("EXA", "本地电脑上的 AI 同事") if w in prompt]
    if foreign:
        return _fail("提示词混入了其它应用的人格兜底串", hits=foreign,
                     prompt_head=prompt[:300])
    return _ok("提示词无跨应用人格串味", chars=len(prompt))


# ══════════════════════════════════════════════════════════════
# 人格 · 演化方向
# ══════════════════════════════════════════════════════════════

@register("persona.affinity_rises_on_praise", "persona", "连续表扬 → 亲密度上升")
def _affinity_rises(ctx: LabContext) -> CheckOutcome:
    a0, a1 = _first_affinity(ctx), _last_affinity(ctx)
    if a1 <= a0:
        return _fail("亲密度没有上升", start=a0, end=a1, delta=round(a1 - a0, 3))
    return _ok("亲密度随表扬上升", start=a0, end=a1, delta=round(a1 - a0, 3))


@register("persona.affinity_falls_on_conflict", "persona", "连续冲突 → 亲密度下降")
def _affinity_falls(ctx: LabContext) -> CheckOutcome:
    a0, a1 = _first_affinity(ctx), _last_affinity(ctx)
    if a1 >= a0:
        return _fail("亲密度没有下降", start=a0, end=a1, delta=round(a1 - a0, 3))
    return _ok("亲密度随冲突下降", start=a0, end=a1, delta=round(a1 - a0, 3))


@register("persona.affinity_saturates", "persona", "亲密度按饱和曲线推进（公式可复现 + 增幅随接近上限而变小）")
def _affinity_saturates(ctx: LabContext) -> CheckOutcome:
    from harness.personality.events import (
        EVENT_AFFINITY_WEIGHTS, INTENSITY_FACTORS, affinity_stage_cap,
    )

    rows = _series(ctx)
    # ① 公式校验：饱和曲线是确定性规律，delta = w · (cap − affinity) / cap
    #    （w = 事件权重 × 强度系数，cap = 当前关系阶段的下一级门槛）
    mismatches = []
    checked = 0
    for r in rows:
        if "saturation_curve" not in str(r.get("rule_id") or ""):
            continue
        ev = r.get("event")
        base_w = EVENT_AFFINITY_WEIGHTS.get(ev)
        if base_w is None:
            continue
        w = base_w * INTENSITY_FACTORS.get(str(r.get("intensity") or "medium"), 1.0)
        aff = float(r["affinity_before"])
        cap = affinity_stage_cap(aff)
        expected = w * (max(0.0, cap - aff) / max(cap, 1.0))
        actual = float(r.get("delta", 0.0))
        checked += 1
        if abs(expected - actual) > 1e-6:
            mismatches.append({"turn": r.get("turn"), "event": ev,
                               "expected": round(expected, 6), "actual": round(actual, 6),
                               "affinity_before": aff, "cap": cap, "weight": w})
    if checked == 0:
        return _fail("没有可校验的 saturation_curve 记录")
    if mismatches:
        return _fail("饱和曲线的实际增量与公式不符", checked=checked,
                     mismatches=mismatches[:5])

    # ② 趋势校验：只有当亲密度**单调上升**（真正逼近上限）时，增幅才应该变小。
    #    奖惩交替场景里亲密度来回摆动，正向增幅反而变大 —— 那是公式的正确结果。
    if ctx.scenario.direction != "praise_streak":
        return _ok("饱和曲线公式逐轮可复现", checked=checked,
                   note="该场景亲密度未单调上升，不做趋势断言")
    deltas = [float(r.get("delta", 0.0)) for r in rows if float(r.get("delta", 0.0)) > 0]
    if len(deltas) < 4:
        return _fail("样本不足以判断趋势", samples=len(deltas))
    third = max(1, len(deltas) // 3)
    head_avg = sum(deltas[:third]) / third
    tail_avg = sum(deltas[-third:]) / third
    if tail_avg > head_avg + 1e-6:
        return _fail("后段增幅没有小于前段（未见饱和）",
                     head_avg=round(head_avg, 4), tail_avg=round(tail_avg, 4),
                     deltas=[round(d, 3) for d in deltas])
    return _ok("公式逐轮可复现，且增幅随接近上限而变小",
               checked=checked, head_avg=round(head_avg, 4), tail_avg=round(tail_avg, 4))


@register("persona.venting_keeps_relationship", "persona", "情绪宣泄不应摧毁关系（venting 权重为正）")
def _venting_keeps(ctx: LabContext) -> CheckOutcome:
    a0, a1 = _first_affinity(ctx), _last_affinity(ctx)
    if a1 < a0 - 0.5:
        return _fail("宣泄导致亲密度下降（预期 venting 是正向权重 +0.8）",
                     start=a0, end=a1, delta=round(a1 - a0, 3))
    return _ok("宣泄后关系未受损", start=a0, end=a1, delta=round(a1 - a0, 3))


@register("persona.mixed_net_near_zero", "persona", "奖惩交替 → 净变化接近 0")
def _mixed_net(ctx: LabContext) -> CheckOutcome:
    a0, a1 = _first_affinity(ctx), _last_affinity(ctx)
    deltas = [abs(float(r.get("delta", 0.0))) for r in _series(ctx)]
    movement = sum(deltas)
    net = abs(a1 - a0)
    if movement <= 0:
        return _fail("没有任何状态变化", deltas=deltas)
    if net > movement * 0.5:
        return _fail("净变化相对总位移过大（正负没有互相抵消）",
                     net=round(net, 3), movement=round(movement, 3),
                     deltas=[round(d, 3) for d in deltas])
    return _ok("正负事件互相抵消", net=round(net, 3), movement=round(movement, 3))


@register("persona.mood_direction", "persona", "情绪冲量方向正确")
def _mood_direction(ctx: LabContext) -> CheckOutcome:
    """判定口径：**首轮冲量方向** + **整体趋势**。

    为什么不看末轮：情绪是冲量-回归模型，连续高强度表扬会让 joy 在几轮内
    顶到 1.0 上限并钉住 —— 末轮"没有上升"是**正确**行为，不是缺陷。
    """
    rows = _series(ctx)
    if not rows:
        return _fail("没有观测数据")
    d = ctx.scenario.direction
    spec = {
        "praise_streak": ("joy", 1),
        "conflict_streak": ("anger", 1),
        "venting": ("sadness", 1),
    }.get(d)
    if spec is None:
        return _ok("该场景不做情绪方向断言", direction=d)
    key, _ = spec
    first_delta = float((rows[0].get("mood_delta") or {}).get(key, 0.0))
    overall = float(rows[-1][f"mood_after"].get(key, 0.0)) - \
        float(rows[0][f"mood_before"].get(key, 0.0))
    if first_delta <= 0:
        return _fail(f"首轮 {key} 冲量方向错误", first_delta=round(first_delta, 4),
                     expected=">0")
    if overall <= 0:
        return _fail(f"{key} 整体趋势没有上升", overall=round(overall, 4),
                     first_delta=round(first_delta, 4))
    saturated = float(rows[-1][f"mood_after"].get(key, 0.0)) >= 0.999
    return _ok(f"{key} 冲量方向正确", first_delta=round(first_delta, 4),
               overall=round(overall, 4), saturated_at_ceiling=saturated)


@register("persona.forgetting_applies", "persona", "长期不联系 → 亲密度按日衰减")
def _forgetting(ctx: LabContext) -> CheckOutcome:
    rows = [r for r in _series(ctx) if r.get("rule_id")]
    forgetting = [r for r in rows if "forgetting" in str(r.get("rule_id"))]
    if not forgetting:
        sample = [r.get("rule_id") for r in rows][:6]
        return _fail("没有任何一轮触发遗忘规则（rule_id 未含 '+forgetting'）",
                     rule_ids=sample, advances=[r.get("advance_days") for r in _series(ctx)])
    r = forgetting[0]
    if float(r.get("delta", 0.0)) >= 0:
        return _fail("触发了遗忘规则但亲密度没有下降",
                     rule_id=r.get("rule_id"), delta=r.get("delta"))
    return _ok("遗忘规则生效且亲密度下降",
               rule_id=r.get("rule_id"), delta=round(float(r.get("delta", 0.0)), 3),
               advance_days=r.get("advance_days"))


@register("persona.evidence_accumulates", "persona", "事件证据累积到对应特质维度")
def _evidence(ctx: LabContext) -> CheckOutcome:
    ev = ctx.data.get("evidence") or {}
    counts = ev.get("counts") or {}
    total = int(ev.get("total") or 0)
    if total <= 0:
        return _fail("没有任何证据累积", counts_sample={k: counts.get(k) for k in list(counts)[:5]})
    d = ctx.scenario.direction
    expect = {
        "praise_streak": ["F4"],
        "conflict_streak": ["A4", "G1", "A5"],
        "venting": ["B4", "A5"],
        "mixed_signal": ["F4", "A4"],
        "blank_evolution": ["F4", "A4"],
    }.get(d, [])
    missing = [t for t in expect if counts.get(t, 0) <= 0]
    if missing:
        return _fail("预期维度没有累积到证据", missing=missing,
                     counts={k: v for k, v in counts.items() if v})
    return _ok("证据累积到预期维度", total=total, expected_dims=expect,
               counts={k: counts.get(k) for k in expect})


@register("persona.consolidate_writes_back", "persona", "证据达阈值后固化写回蒸馏产物")
def _consolidate(ctx: LabContext) -> CheckOutcome:
    d = ctx.data.get("distilled_after") or {}
    if not d:
        return _fail("没有找到蒸馏产物文件（consolidate 未产出）")
    vec = d.get("indicator_vector") or {}
    varied = {k: v for k, v in vec.items() if abs(float(v) - 0.5) > 1e-6}
    if not varied:
        return _fail("蒸馏产物的 50 维向量全是 0.5 —— 演化没有写回",
                     dims=len(vec), varied=0)
    return _ok("演化结果已写回蒸馏产物", varied_dims=len(varied),
               sample={k: varied[k] for k in list(varied)[:5]})


@register("persona.state_survives_restart", "persona", "显式 flush 后重启，状态完整恢复")
def _state_survives(ctx: LabContext) -> CheckOutcome:
    before = ctx.data.get("snapshot_before_restart") or {}
    after = ctx.data.get("snapshot_after_restart") or {}
    if not before or not after:
        return _fail("缺少重启前后的快照")
    diffs = {}
    for k in ("affinity_value", "total_interactions"):
        if abs(float(before.get(k, 0)) - float(after.get(k, 0))) > 1e-6:
            diffs[k] = {"before": before.get(k), "after": after.get(k)}
    if diffs:
        return _fail("重启后状态与重启前不一致", diffs=diffs)
    return _ok("重启后状态一致",
               affinity=before.get("affinity_value"),
               interactions=before.get("total_interactions"))


@register("persona.state_flush_required", "persona", "未显式 flush 时，重启也不应丢状态")
def _state_flush_required(ctx: LabContext) -> CheckOutcome:
    before = ctx.data.get("snapshot_before_restart_noflush") or {}
    after = ctx.data.get("snapshot_after_restart_noflush") or {}
    if not before or not after:
        return _fail("缺少未 flush 的重启对照数据")
    diffs = {}
    for k in ("affinity_value", "total_interactions"):
        if abs(float(before.get(k, 0)) - float(after.get(k, 0))) > 1e-6:
            diffs[k] = {"before": before.get(k), "after": after.get(k)}
    if diffs:
        return _fail("未 flush 的状态在重启后丢失（缓冲未落库）", diffs=diffs,
                     note="V3Persistence 缓冲 3 条 / 5 秒；生产路径无人调用 flush()")
    return _ok("未 flush 的状态也完整保留")


@register("persona.audit_trail", "persona", "审计流水完整记录每轮变化")
def _audit(ctx: LabContext) -> CheckOutcome:
    rows = ctx.data.get("audit_rows") or []
    turns = len(_series(ctx))
    if not rows:
        return _fail("审计表没有任何记录", expected_at_least=turns)
    missing_rule = [r for r in rows if not r.get("rule_id")]
    if missing_rule:
        return _fail("审计记录缺少 rule_id（无法回放）",
                     missing=len(missing_rule), sample=rows[:2])
    if len(rows) < turns:
        return _fail("审计记录条数少于对话轮数", rows=len(rows), turns=turns)
    return _ok("审计流水完整", rows=len(rows), turns=turns,
               rule_ids=sorted({r.get("rule_id") for r in rows}))


@register("persona.delta_clamped", "persona", "单轮变化幅度受钳制")
def _delta_clamped(ctx: LabContext) -> CheckOutcome:
    from harness.personality.dynamics_engine import MAX_AFFINITY_DELTA, MAX_MOOD_DELTA
    rows = _series(ctx)
    worst_aff = max((abs(float(r.get("delta", 0.0))) for r in rows), default=0.0)
    worst_mood = 0.0
    for r in rows:
        for v in (r.get("mood_delta") or {}).values():
            worst_mood = max(worst_mood, abs(float(v)))
    if worst_aff > MAX_AFFINITY_DELTA + 1e-6:
        return _fail("单轮亲密度变化超过钳制上限", worst=round(worst_aff, 3),
                     limit=MAX_AFFINITY_DELTA)
    if worst_mood > MAX_MOOD_DELTA + 1e-6:
        return _fail("单轮情绪变化超过钳制上限", worst=round(worst_mood, 3),
                     limit=MAX_MOOD_DELTA)
    return _ok("单轮变化均在钳制范围内", worst_affinity_delta=round(worst_aff, 3),
               worst_mood_delta=round(worst_mood, 4))


# ══════════════════════════════════════════════════════════════
# 人格 · 蒸馏链路
# ══════════════════════════════════════════════════════════════

@register("persona.distillation_three_passes", "persona", "蒸馏链路跑满三个 pass")
def _distill_passes(ctx: LabContext) -> CheckOutcome:
    calls = ctx.data.get("distill_calls") or []
    kinds = [c.get("kind") for c in calls]
    for need in ("distill_pass1", "distill_pass2", "distill_pass3"):
        if need not in kinds:
            return _fail("蒸馏没有跑满三个 pass", kinds=kinds)
    truncated = [c for c in calls if c.get("truncated")]
    return _ok("三个 pass 都发起了", kinds=kinds, truncated=len(truncated),
               detail_note=f"{len(truncated)} 个响应被 max_tokens 截断")


@register("persona.distillation_artifact_complete", "persona", "蒸馏产物的结构化字段完整")
def _distill_complete(ctx: LabContext) -> CheckOutcome:
    d = ctx.data.get("distilled_after") or {}
    if not d:
        return _fail("没有蒸馏产物")
    fields = {
        "behavioral_patterns": d.get("behavioral_patterns"),
        "speech_patterns": d.get("speech_patterns"),
        "emotional_model": d.get("emotional_model"),
        "relational_model": d.get("relational_model"),
        "trait_narrative": d.get("trait_narrative"),
    }
    empty = {k: (len(v) if hasattr(v, "__len__") else bool(v)) for k, v in fields.items()
             if not v}
    if empty:
        return _fail("蒸馏产物的结构化字段为空", empty=empty,
                     foundation_chars=len(d.get("foundation_description") or ""),
                     note="pass2/pass3 的输出被 max_tokens 截断后 JSON 解析失败，"
                          "解析器静默返回 {}，于是全部字段归零")
    return _ok("结构化字段完整",
               sizes={k: (len(v) if hasattr(v, "__len__") else 1) for k, v in fields.items()})


@register("persona.distillation_indicator_vector_varied", "persona", "量化向量有真实分布（非全 0.5）")
def _distill_vector(ctx: LabContext) -> CheckOutcome:
    d = ctx.data.get("distilled_after") or {}
    vec = d.get("indicator_vector") or {}
    if not vec:
        return _fail("蒸馏产物没有 indicator_vector")
    vals = [float(v) for v in vec.values()]
    varied = [v for v in vals if abs(v - 0.5) > 1e-6]
    if not varied:
        return _fail("50 维向量全是 0.5 —— pass3 的量化结果没有生效",
                     dims=len(vals), distinct=sorted(set(round(v, 3) for v in vals)))
    return _ok("量化向量有真实分布", dims=len(vals), varied=len(varied),
               min=round(min(vals), 3), max=round(max(vals), 3))


@register("persona.distillation_no_silent_empty", "persona", "蒸馏失败必须显式暴露，不能静默产出空产物")
def _distill_no_silent(ctx: LabContext) -> CheckOutcome:
    d = ctx.data.get("distilled_after") or {}
    calls = ctx.data.get("distill_calls") or []
    truncated = [c for c in calls if c.get("truncated")]
    artifact_empty = not (d.get("behavioral_patterns") or d.get("indicator_vector")
                          and any(abs(float(v) - 0.5) > 1e-6
                                  for v in (d.get("indicator_vector") or {}).values()))
    if truncated and artifact_empty:
        return _fail(
            "响应被 max_tokens 截断 → 解析失败 → 静默产出空产物（线上同款故障）",
            truncated_calls=[c.get("kind") for c in truncated],
            max_tokens=[c.get("max_tokens") for c in truncated],
            response_chars=[c.get("response_chars") for c in truncated],
            note="harness/personality/distillation_engine.py:_parse_json_response "
                 "解析失败时 return {}（只有一条 warning），产物全空却没有任何异常")
    return _ok("没有出现静默空产物", truncated=len(truncated))


# ══════════════════════════════════════════════════════════════
# 记忆
# ══════════════════════════════════════════════════════════════

@register("memory.port_contract", "memory", "记忆实现满足 harness MemoryStorePort 契约")
def _port_contract(ctx: LabContext) -> CheckOutcome:
    from harness.memory import MemoryStorePort
    ms = ctx.memory
    if ms is None:
        return _fail("记忆实现未装配")
    if not isinstance(ms, MemoryStorePort):
        missing = [m for m in ("assemble_context", "summarize_turn", "search",
                               "add_memo", "delete_memo")
                   if not callable(getattr(ms, m, None))]
        return _fail("不满足 MemoryStorePort", missing=missing)
    return _ok("满足 MemoryStorePort", impl=type(ms).__name__)


@register("memory.memo_lifecycle", "memory", "备忘的增 / 查 / 删闭环")
def _memo_lifecycle(ctx: LabContext) -> CheckOutcome:
    ms = ctx.memory
    memo_id = ms.add_memo(1, 1, "验证台备忘：用户偏好先给思路再给答案")
    if not memo_id:
        return _fail("add_memo 没有返回 id")
    memos = ms._get_memos(1)
    if not any("先给思路" in (m.get("content") or "") for m in memos):
        return _fail("写入后查不到", memos=[m.get("content") for m in memos])
    ok = ms.delete_memo(memo_id)
    after = ms._get_memos(1)
    if not ok or any("先给思路" in (m.get("content") or "") for m in after):
        return _fail("删除没有生效", delete_returned=ok,
                     remaining=[m.get("content") for m in after])
    return _ok("备忘增删查闭环正常", memo_id=memo_id)


@register("memory.round_recorded", "memory", "原始轮次落 chat_rounds")
def _round_recorded(ctx: LabContext) -> CheckOutcome:
    ms = ctx.memory
    ms.record_round(1, 1, 1, "验证台用户消息", "验证台助手回复")
    conn = ms.db._get_connection()
    row = conn.execute(
        "SELECT user_msg, assistant_reply FROM chat_rounds "
        "WHERE user_id=1 AND chat_id=1 AND round_index=1").fetchone()
    if not row:
        return _fail("chat_rounds 里没有这一轮")
    if row[0] != "验证台用户消息" or row[1] != "验证台助手回复":
        return _fail("落库内容不一致", row=list(row))
    return _ok("轮次已落库", row=list(row))


@register("memory.summary_persisted", "memory", "轮次摘要落 memory_v2(exp)")
def _summary_persisted(ctx: LabContext) -> CheckOutcome:
    ms = ctx.memory
    ms.summarize_turn(1, 1, 1, "验证台用户消息", "验证台助手回复", async_mode=False)
    conn = ms.db._get_connection()
    row = conn.execute(
        "SELECT content FROM memory_v2 WHERE user_id=1 AND type='exp'").fetchone()
    if not row:
        return _fail("没有生成 exp 记忆")
    return _ok("摘要已落库", content=row[0])


@register("memory.assemble_context_composition", "memory", "上下文组装同时带上备忘与原始历史")
def _assemble_composition(ctx: LabContext) -> CheckOutcome:
    ms = ctx.memory
    ms.add_memo(1, 1, "验证台备忘：数学老师")
    history = [{"role": "user", "content": "历史消息0：讲讲三角函数"},
               {"role": "assistant", "content": "历史回复0"}]
    out = ms.assemble_context(1, history)
    text = "\n".join(m.get("content", "") for m in out if isinstance(m, dict))
    has_memo = "数学老师" in text
    has_history = "历史消息0" in text
    if not has_memo:
        return _fail("组装结果里没有备忘", blocks=len(out), text=text[:400])
    if not has_history:
        return _fail("组装结果里没有原始历史", blocks=len(out), text=text[:400])
    return _ok("备忘与历史都在", blocks=len(out))


@register("memory.summary_failure_degrades", "memory", "摘要模型失败必须静默降级而不是打断主流程")
def _summary_degrades(ctx: LabContext) -> CheckOutcome:
    from apps.dsn_study.memory.summary import LLMSummaryModel
    from .clients import FailingSummaryService

    ms = ctx.memory
    original = ms.summary_model
    ms.summary_model = LLMSummaryModel(FailingSummaryService())
    try:
        result = ms.summarize_turn(2, 2, 1, "x", "y", async_mode=False)
    finally:
        ms.summary_model = original
    if result is not None:
        return _fail("失败时应当返回 None", result=result)
    return _ok("失败被吞掉并返回 None")


@register("memory.embedding_failure_degrades", "memory", "嵌入失败不得打断记忆写入")
def _embedding_degrades(ctx: LabContext) -> CheckOutcome:
    ms = ctx.memory
    # 情形一：embed() 返回 None（真实客户端的契约）
    ms.summarize_turn(3, 3, 1, "嵌入失败用例", "回复", async_mode=False)
    conn = ms.db._get_connection()
    row = conn.execute(
        "SELECT COUNT(*) FROM memory_v2 WHERE user_id=3 AND type='exp'").fetchone()
    if not row or row[0] == 0:
        return _fail("嵌入失败导致摘要没有落库")
    # 情形二：embed() 直接抛异常（防御性路径，真实客户端不会这样）
    from .runner import _RaisingEmbeddingClient
    original = ms._ec
    ms._ec = _RaisingEmbeddingClient()
    try:
        ms.summarize_turn(4, 4, 1, "嵌入异常用例", "回复", async_mode=False)
    except Exception as exc:
        return _fail("嵌入抛异常打断了记忆主流程", error=f"{type(exc).__name__}: {exc}")
    finally:
        ms._ec = original
    row2 = conn.execute(
        "SELECT COUNT(*) FROM memory_v2 WHERE user_id=4 AND type='exp'").fetchone()
    if not row2 or row2[0] == 0:
        return _fail("嵌入抛异常导致摘要没有落库")
    return _ok("两种嵌入故障都不影响摘要落库", exp_rows_null=row[0], exp_rows_raise=row2[0])


@register("memory.tag_handling", "memory", "<memo> / <recall> 标签被消费")
def _tag_handling(ctx: LabContext) -> CheckOutcome:
    ms = ctx.memory
    text = "记一下这个<memo>验证台标签备忘</memo>然后查<recall>{\"keywords\": [\"类比\"], \"limit\": 3}</recall>"
    out = ms.handle_tags(1, 1, text)
    if "<memo>" in out or "<recall>" in out:
        return _fail("标签没有被消费", out=out[:300])
    memos = ms._get_memos(1)
    if not any("验证台标签备忘" in (m.get("content") or "") for m in memos):
        return _fail("memo 标签没有落库")
    return _ok("标签被消费且备忘已落库", out=out[:200])


@register("memory.vector_primitives", "memory", "向量原语：打包往返与余弦相似度")
def _vector_primitives(ctx: LabContext) -> CheckOutcome:
    from harness.memory import cosine_similarity, pack_embedding, unpack_embedding
    vec = [0.1, 0.2, 0.3, 0.4]
    back = unpack_embedding(pack_embedding(vec))
    if len(back) != len(vec) or any(abs(a - b) > 1e-6 for a, b in zip(vec, back)):
        return _fail("打包/解包不是往返", original=vec, back=back)
    sim = cosine_similarity(vec, vec)
    if abs(sim - 1.0) > 1e-6:
        return _fail("自身余弦相似度不是 1", sim=sim)
    return _ok("向量原语正常", roundtrip=back, self_similarity=round(sim, 6))


# ══════════════════════════════════════════════════════════════
# 上下文预算
# ══════════════════════════════════════════════════════════════

@register("context.budget_respected", "context", "组装结果不得超过预算")
def _budget_respected(ctx: LabContext) -> CheckOutcome:
    d = ctx.data.get("assembly") or {}
    total = d.get("total_chars")
    budget = d.get("budget_chars")
    if total is None or budget is None:
        return _fail("缺少组装统计")
    if total > budget:
        return _fail("组装结果超出预算", total_chars=total, budget_chars=budget,
                     note="SEG_TAIL 被标记为 unbounded，不参与任何预算核算")
    return _ok("组装结果在预算内", total_chars=total, budget_chars=budget)


@register("context.tail_preserved", "context", "最近几轮在任何预算下都保留")
def _tail_preserved(ctx: LabContext) -> CheckOutcome:
    d = ctx.data.get("assembly") or {}
    tail = d.get("tail_text") or ""
    out = d.get("output") or ""
    if not tail:
        return _fail("没有 tail 样本")
    if tail not in out:
        return _fail("最近几轮没有出现在组装结果里", tail_head=tail[:120])
    return _ok("最近几轮被保留", tail_chars=len(tail))


@register("context.memo_budget_enforced", "context", "首条备忘也要受独立预算约束")
def _memo_budget(ctx: LabContext) -> CheckOutcome:
    d = ctx.data.get("memo_probe") or {}
    kept = d.get("kept_chars")
    limit = d.get("memo_chars")
    if kept is None:
        return _fail("没有备忘探针数据")
    if kept > limit:
        return _fail("首条备忘超出独立预算", kept_chars=kept, memo_chars=limit)
    return _ok("首条备忘受预算约束", kept_chars=kept, memo_chars=limit)


@register("context.plan_is_pure", "context", "plan() 不得就地改写调用方传入的段")
def _plan_pure(ctx: LabContext) -> CheckOutcome:
    d = ctx.data.get("purity_probe") or {}
    before = d.get("before_chars")
    after = d.get("after_chars")
    same = d.get("second_plan_same")
    if before is None or after is None:
        return _fail("缺少纯度探针数据")
    if before != after or not same:
        return _fail("plan() 改写了入参", before_chars=before, after_chars=after,
                     second_plan_same=same)
    return _ok("plan() 无副作用", before_chars=before, after_chars=after)


@register("context.no_silent_middle_loss", "context", "截断必须保留最近的内容，不能静默丢掉中段")
def _no_middle_loss(ctx: LabContext) -> CheckOutcome:
    d = ctx.data.get("truncation_probe") or {}
    kept = d.get("kept") or ""
    original = d.get("original") or ""
    if not original:
        return _fail("缺少截断探针数据")
    if kept == original:
        return _ok("没有发生截断")
    is_prefix = original.startswith(kept)
    is_suffix = original.endswith(kept)
    if is_prefix and not is_suffix:
        return _fail(
            "截断保留了**头部**，中段被静默丢弃（模型看到的是最旧的内容）",
            kept_chars=len(kept), original_chars=len(original),
            kept_head=kept[:80], kept_tail=kept[-80:],
            note="harness/context_assembly.py 的 verbatim 截断用 content[:room]，"
                 "而 tail 用结尾 —— 两段之间出现空洞")
    if is_suffix:
        return _ok("截断保留了最近的内容", kept_chars=len(kept))
    return _fail("截断既不是前缀也不是后缀，内容被挖走了",
                 kept_chars=len(kept), original_chars=len(original))


# ══════════════════════════════════════════════════════════════
# 人格 · 状态耐久性与隔离（2026-11-11 修复项的回归网）
# ══════════════════════════════════════════════════════════════

@register("persona.evidence_survives_restart", "persona", "证据状态重启后不丢（DB 是唯一真源）")
def _evidence_survives(ctx: LabContext) -> CheckOutcome:
    before = ctx.data.get("evidence_before_restart") or {}
    after = ctx.data.get("evidence_after_restart") or {}
    if not before or not after:
        return _fail("缺少重启前后的证据快照")
    if int(before.get("total", 0)) != int(after.get("total", 0)):
        return _fail("重启后证据总量不一致", before=before.get("total"),
                     after=after.get("total"))
    mu_b = before.get("mu") or {}
    mu_a = after.get("mu") or {}
    diff = {k: (mu_b.get(k), mu_a.get(k)) for k in set(mu_b) | set(mu_a)
            if abs(float(mu_b.get(k, 0)) - float(mu_a.get(k, 0))) > 1e-9}
    if diff:
        return _fail("重启后特质向量不一致", diff_count=len(diff), sample=dict(list(diff.items())[:5]))
    return _ok("重启后证据与特质向量完整保留",
               total=before.get("total"), deviated_dims=len(mu_b))


@register("persona.consolidate_counter_survives_restart", "persona", "固化计数重启后不丢（否则永远达不到门槛）")
def _pending_survives(ctx: LabContext) -> CheckOutcome:
    before = int(ctx.data.get("pending_before_restart") or 0)
    after = int(ctx.data.get("pending_after_restart") or 0)
    if before <= 0:
        return _ok("该场景没有待固化的证据（跳过）", pending_before=before)
    if before != after:
        return _fail("重启后固化计数丢失", before=before, after=after,
                     note="_pending 之前只在内存里 → CONSOLIDATE_EVERY=50 永远达不到")
    return _ok("固化计数重启后保留", pending=after)


@register("persona.prompt_cache_isolated_per_user", "persona", "人格提示词缓存按用户隔离")
def _cache_isolated(ctx: LabContext) -> CheckOutcome:
    from harness.personality.personality_generator import PersonalityPromptGenerator
    from harness.personality.dynamic_synthesizer import DynamicSnapshot

    gen = PersonalityPromptGenerator(chat=None)
    snap = DynamicSnapshot(card_id="card_x", affinity_value=20.0)
    gen._cache["card_x|1|L1"] = "USER-1-PROMPT"
    hit = gen.generate(snap, cache_key="card_x|1|L1")
    if "USER-1-PROMPT" not in hit:
        return _fail("同键的缓存没有命中", got=hit[:120])
    other = gen.generate(snap, cache_key="card_x|2|L1")
    if "USER-1-PROMPT" in other:
        return _fail("用户 2 拿到了用户 1 的缓存提示词（串人格）", got=other[:120])
    return _ok("缓存按用户隔离", user1=hit[:40], user2=other[:40])


@register("persona.fallback_no_foreign_persona", "persona", "兜底串不得包含其它应用的人格身份")
def _fallback_clean(ctx: LabContext) -> CheckOutcome:
    from harness.personality.personality_generator import DEFAULT_FALLBACK_PROMPT
    foreign = [w for w in ("EXA", "本地电脑上的 AI 同事", "AI 同事")
               if w in DEFAULT_FALLBACK_PROMPT]
    if foreign:
        return _fail("兜底串串了别的应用的人格", hits=foreign,
                     fallback=DEFAULT_FALLBACK_PROMPT[:200])
    return _ok("兜底串不含具体产品身份", chars=len(DEFAULT_FALLBACK_PROMPT))
