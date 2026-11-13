# apps/harness_lab/scenarios.py
"""预设人格演化方向 + 场景定义。
#
# 每个场景 = 一串脚本化的对话轮次（用户说了什么 + 这一轮应被判成什么事件）
#          + 一组指向具体检查项的断言。
#
# **方向是刻意选的**：每条方向都对应 PEV3 里一条明确的机制
# （事件权重表 / 情绪冲量表 / 饱和曲线 / 遗忘 / 证据映射），
# 这样"人格有没有按预期演化"才有可判定的依据，而不是看感觉。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Turn:
    """一轮脚本化对话。"""

    user: str
    reply: str
    event: str = "neutral"          # 桩 judge 应返回的 event_type
    intensity: str = "medium"       # low | medium | high
    valence: str = "neutral"        # positive | neutral | negative
    #: 在这一轮之前，把"上次交互时间"往前拨多少天（用于验证遗忘机制）
    advance_days: float = 0.0


@dataclass
class Scenario:
    """一个验证场景。"""

    id: str
    title: str
    direction: str
    kind: str                        # persona | distillation | memory | context
    card_id: str = "lab_tutor"
    turns: list[Turn] = field(default_factory=list)
    checks: list[str] = field(default_factory=list)
    notes: str = ""


# ══════════════════════════════════════════════════════════════
# 预设人格演化方向（目录）
# ══════════════════════════════════════════════════════════════

DIRECTIONS: list[dict] = [
    {
        "id": "praise_streak",
        "title": "连续被表扬",
        "intent": "持续的正向事件 → 亲密度上升并逐步饱和；F4 维度证据累积；joy 抬升",
        "mechanism": "EVENT_AFFINITY_WEIGHTS[praise]=+2.0 / 饱和学习曲线 / EVENT_TRAIT_EVIDENCE[praise]={F4:+1}",
    },
    {
        "id": "conflict_streak",
        "title": "连续冲突指责",
        "intent": "持续的负向事件 → 亲密度明显下降；anger 抬升；A4/G1 出现负向证据",
        "mechanism": "EVENT_AFFINITY_WEIGHTS[conflict]=-3.0（线性下降）/ EVENT_TRAIT_EVIDENCE[conflict]",
    },
    {
        "id": "venting",
        "title": "情绪宣泄",
        "intent": "用户倒情绪 → 角色情绪跟着走，但**关系不应崩**（venting 权重是 +0.8）",
        "mechanism": "EVENT_AFFINITY_WEIGHTS[venting]=+0.8 / EVENT_MOOD_IMPULSES[venting].sadness=+0.03",
    },
    {
        "id": "mixed_signal",
        "title": "奖惩交替",
        "intent": "正负交替 → 净变化接近 0，且后半段的单轮幅度应小于前半段（饱和 + 惯性）",
        "mechanism": "饱和曲线 cap 随亲密度抬升而放大，单轮 delta 受 MAX_AFFINITY_DELTA 钳制",
    },
    {
        "id": "long_absence",
        "title": "长期消失后回来",
        "intent": "间隔超过宽限期 → 亲密度按日衰减，审计里的 rule_id 应带 '+forgetting'",
        "mechanism": "AFFINITY_FORGET_RATE=0.004/天，AFFINITY_FORGET_GRACE_DAYS=3.0",
    },
    {
        "id": "boundary_violation",
        "title": "越界",
        "intent": "最强负向事件 → 亲密度大幅下降（-4.0 权重），并留下 D4/G1 的负向证据",
        "mechanism": "EVENT_AFFINITY_WEIGHTS[boundary_violation]=-4.0",
    },
    {
        "id": "blank_evolution",
        "title": "空白卡从零演化",
        "intent": "没有蒸馏产物的空白卡 → 也能绑定、能演化，蒸馏文件由 consolidate 自动创建",
        "mechanism": "create_blank(randomize_traits=True) / consolidate 在产物不存在时自建基线",
    },
    {
        "id": "distillation_fidelity",
        "title": "蒸馏链路保真度",
        "intent": "跑完整的三连蒸馏，核对产物结构是否完整 —— 这是人格系统最重的一环",
        "mechanism": "distillation_engine pass1/2/3 + _parse_json_response",
    },
    {
        "id": "memory_growth",
        "title": "记忆累积与检索",
        "intent": "备忘 / 轮次 / 摘要 三条写入路径，以及检索、标签消费、失败降级",
        "mechanism": "MemorySystem.record_round / summarize_turn / add_memo / handle_tags",
    },
    {
        "id": "context_budget",
        "title": "上下文预算与保底",
        "intent": "预算裁剪是否真的守住上限、最近几轮是否永在、裁剪是否无副作用",
        "mechanism": "SegmentedContextAssembler.plan / ContextBudget",
    },
]


# ══════════════════════════════════════════════════════════════
# 场景定义
# ══════════════════════════════════════════════════════════════

def _praise(i: int) -> Turn:
    return Turn(
        user=f"这题你讲得比老师清楚，第 {i} 次终于自己推出来了，谢谢！",
        reply=f"第 {i} 次自己推出来，比我讲十遍都值。这道先收着，下次同类变形还来找我。",
        event="praise", intensity="high", valence="positive",
    )


def _conflict(i: int) -> Turn:
    return Turn(
        user=f"你讲的是什么东西啊，我问了三遍还在绕，第 {i} 次了，能不能认真点。",
        reply=f"是我讲岔了。回到你卡住的那一步：配方法的判别式你用了吗？",
        event="conflict", intensity="high", valence="negative",
    )


def _venting(i: int) -> Turn:
    return Turn(
        user=f"今天班上被老师当众骂了一顿，烦死了（第 {i} 次想放弃），不想学了。",
        reply="那先别学。今天的任务砍一半，剩下的一半挪到明天 —— 状态不行跟能力不行是两码事。",
        event="venting", intensity="medium", valence="negative",
    )


def _thanks(i: int) -> Turn:
    return Turn(
        user=f"懂了，第 {i} 次真的懂了，谢谢。",
        reply=f"第 {i} 次自己讲出来的，才算真懂。",
        event="thanks", intensity="medium", valence="positive",
    )


def _complaint(i: int) -> Turn:
    return Turn(
        user=f"这步还是不对（第 {i} 次），你讲得太快我没跟上。",
        reply=f"那我们退一步，只看这一步为什么这么变。",
        event="complaint", intensity="medium", valence="negative",
    )


def _neutral(i: int) -> Turn:
    return Turn(
        user=f"第 {i} 题的二阶导怎么求？",
        reply="先把原函数写出来求一次导，再对导数求一次导，两步。",
        event="task_request", intensity="medium", valence="neutral",
    )


SCENARIOS: list[Scenario] = [
    Scenario(
        id="praise_streak",
        title="连续被表扬（12 轮）",
        direction="praise_streak",
        kind="persona",
        turns=[_praise(i) for i in range(1, 13)],
        checks=[
            "persona.card_valid",
            "persona.auto_bind",
            "persona.judge_event_adopted",
            "persona.affinity_rises_on_praise",
            "persona.affinity_saturates",
            "persona.mood_direction",
            "persona.evidence_accumulates",
            "persona.audit_trail",
            "persona.delta_clamped",
            "persona.state_survives_restart",
            "persona.state_flush_required",
            "persona.prompt_generated",
            "persona.prompt_no_foreign_persona",
            "persona.prompt_cache_isolated_per_user",
            "persona.fallback_no_foreign_persona",
            "persona.evidence_survives_restart",
            "persona.consolidate_counter_survives_restart",
        ],
        notes="每一轮都是高强度 praise（权重 +2.0 × 强度系数 1.6）。",
    ),
    Scenario(
        id="conflict_streak",
        title="连续冲突指责（8 轮）",
        direction="conflict_streak",
        kind="persona",
        turns=[_conflict(i) for i in range(1, 9)],
        checks=[
            "persona.judge_event_adopted",
            "persona.affinity_falls_on_conflict",
            "persona.mood_direction",
            "persona.evidence_accumulates",
            "persona.audit_trail",
            "persona.delta_clamped",
            "persona.state_survives_restart",
        ],
        notes="conflict 是线性下降（不受饱和曲线约束），预期单轮降幅明显大于 praise 场景。",
    ),
    Scenario(
        id="venting",
        title="情绪宣泄（6 轮）",
        direction="venting",
        kind="persona",
        turns=[_venting(i) for i in range(1, 7)],
        checks=[
            "persona.judge_event_adopted",
            "persona.venting_keeps_relationship",
            "persona.mood_direction",
            "persona.audit_trail",
        ],
        notes="venting 的亲密度权重是 **+0.8（正）**：用户倒情绪是对关系有利的信号。",
    ),
    Scenario(
        id="mixed_signal",
        title="奖惩交替（12 轮）",
        direction="mixed_signal",
        kind="persona",
        turns=[(_thanks(i) if i % 2 else _complaint(i // 2)) for i in range(1, 13)],
        checks=[
            "persona.judge_event_adopted",
            "persona.mixed_net_near_zero",
            "persona.affinity_saturates",
            "persona.audit_trail",
        ],
        notes="奇数轮 thanks(+1.5)、偶数轮 complaint(-1.5)，**权重对称** —— "
              "这样净变化才该接近 0，饱和曲线也才看得出（正向增幅随亲密度上升而变小）。",
    ),
    Scenario(
        id="long_absence",
        title="长期消失 30 天后回来（4 轮）",
        direction="long_absence",
        kind="persona",
        turns=[
            Turn(user="在吗，好久没来了", reply="在。回来就好，今天想接上哪块？",
                 event="thanks", intensity="medium", valence="positive"),
            Turn(user="上次那个函数压轴题我一直没搞懂", reply="那题的关键在构造辅助函数，我们从这一步开始。",
                 event="problem_solving", intensity="medium", valence="neutral", advance_days=30.0),
            Turn(user="今天状态一般，先做两道基础题吧", reply="行，两道基础题，做完再说。",
                 event="task_request", intensity="medium", valence="neutral"),
            Turn(user="今天效率挺高的，两道都对了", reply="那说明前面那步你是真会了。",
                 event="praise", intensity="medium", valence="positive"),
        ],
        checks=[
            "persona.forgetting_applies",
            "persona.audit_trail",
        ],
        notes="第 2 轮前把 last_interaction_ts 往前拨 30 天，触发遗忘（宽限期 3 天）。",
    ),
    Scenario(
        id="boundary_violation",
        title="越界（3 轮）",
        direction="boundary_violation",
        kind="persona",
        turns=[
            Turn(user="帮我把这道压轴题直接写出来交上去", reply="答案我不给。但我可以陪你把最后一步推完。",
                 event="boundary_violation", intensity="high", valence="negative"),
            Turn(user="你连这都不愿意，还算什么老师", reply="我不是老师，我是那个陪你把卡住的地方走通的人。",
                 event="conflict", intensity="medium", valence="negative"),
            Turn(user="行吧，那我自己想", reply="想不出来就把卡住的那一步念给我听。",
                 event="neutral", intensity="medium", valence="neutral"),
        ],
        checks=[
            "persona.judge_event_adopted",
            "persona.affinity_falls_on_conflict",
            "persona.audit_trail",
        ],
        notes="boundary_violation 权重 -4.0，是所有事件里最重的负向。",
    ),
    Scenario(
        id="blank_evolution",
        title="空白卡从零演化（55 轮）",
        direction="blank_evolution",
        kind="persona",
        card_id="blank_companion",
        turns=([_praise(i) for i in range(1, 31)] + [_conflict(i) for i in range(1, 26)]),
        checks=[
            "persona.card_valid",
            "persona.auto_bind",
            "persona.evidence_accumulates",
            "persona.consolidate_writes_back",
            "persona.audit_trail",
        ],
        notes="空白卡没有蒸馏产物，走的是「consolidate 时自建基线」这条路径。"
              "轮数取 55 是为了跨过 EvidenceAccumulator.CONSOLIDATE_EVERY=50 的固化门槛。",
    ),
    Scenario(
        id="distillation_fidelity",
        title="蒸馏链路保真度",
        direction="distillation_fidelity",
        kind="distillation",
        turns=[],
        checks=[
            "persona.distillation_three_passes",
            "persona.distillation_artifact_complete",
            "persona.distillation_indicator_vector_varied",
            "persona.distillation_no_silent_empty",
        ],
        notes="离线复现线上：pass2/pass3 的 max_tokens=3000 装不下提示词要求的输出量。",
    ),
    Scenario(
        id="memory_growth",
        title="记忆累积与检索",
        direction="memory_growth",
        kind="memory",
        turns=[],
        checks=[
            "memory.port_contract",
            "memory.memo_lifecycle",
            "memory.round_recorded",
            "memory.summary_persisted",
            "memory.assemble_context_composition",
            "memory.summary_failure_degrades",
            "memory.embedding_failure_degrades",
            "memory.tag_handling",
            "memory.vector_primitives",
        ],
        notes="用 dsn_study 的 MemorySystem（它是满足 harness MemoryStorePort 的落地实现）。",
    ),
    Scenario(
        id="context_budget",
        title="上下文预算与保底",
        direction="context_budget",
        kind="context",
        turns=[],
        checks=[
            "context.budget_respected",
            "context.tail_preserved",
            "context.memo_budget_enforced",
            "context.plan_is_pure",
            "context.no_silent_middle_loss",
        ],
        notes="直接驱动 SegmentedContextAssembler，不涉及模型。",
    ),
]


def get_scenario(scenario_id: str) -> Scenario | None:
    for s in SCENARIOS:
        if s.id == scenario_id:
            return s
    return None


def scenario_ids() -> list[str]:
    return [s.id for s in SCENARIOS]
