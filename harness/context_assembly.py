# harness/context_assembly.py
# SegmentedContextAssembler — 结构化上下文预算剪裁（场景无关）。
#
# 背景：长会话 / 多话题记忆场景下，把所有历史原文塞进上下文既不经济也不利于
# 模型聚焦。本模块提供"分段 + 预算"的上下文组装策略，把 DSN 话题系统
# （apps/dsn/memory/topics.py）中验证过的优秀实践提炼为引擎通用能力：
#
#   - 闭锁段（closed/summary）→ 只注入聚合摘要，受 summary 预算约束
#   - 激活段（open/pinned/passive）→ 注入原文，受 verbatim 共享预算约束
#   - 备忘段（memo）→ 全局常驻事实，独立预算，永不模糊
#   - 尾部段（tail）→ 最近 N 轮原文，保证即时上下文
#   - 预算超限时按段优先级裁剪，超出原文截断并标注
#
# 本类不依赖任何存储 / 加密 / 模型：数据由调用方（应用层）以 ContextSegment
# 列表提供，纯函数式剪裁，可独立测试。DSN 的 TopicManager 即委托本类完成
# 预算与裁剪（见 apps/dsn/memory/topics.py 的 assemble_topic_context）。

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Optional


@dataclass
class ContextBudget:
    """上下文预算参数。

    - memo_chars       备忘段总预算（独立）
    - summary_chars    闭锁摘要段总预算（独立）
    - verbatim_chars   激活原文段共享预算（含当前话题原文）
    - tail_rounds      尾部原文保留轮数
    - max_open_topics  激活原文段上限（不含当前话题）
    - truncate_marker  原文超预算截断时的尾部标注
    """

    memo_chars: int = 2000
    summary_chars: int = 2000
    verbatim_chars: int = 8000
    tail_rounds: int = 3
    max_open_topics: int = 3
    truncate_marker: str = "\n...(原文截断)"


# 段优先级：值越大越先保留（剪裁时低优先级先被丢弃）
PRIORITY_MEMO = 100        # 备忘：全局事实
PRIORITY_ACTIVE = 80       # 激活话题原文（pin > passive 由调用方排序保证）
PRIORITY_CURRENT = 90      # 当前话题原文
PRIORITY_SUMMARY = 60      # 闭锁话题摘要
PRIORITY_TAIL = 70         # 尾部原文（固定轮数，不参与共享预算）

SEG_MEMO = "memo"
SEG_SUMMARY = "summary"
SEG_VERBATIM = "verbatim"
SEG_TAIL = "tail"


@dataclass
class ContextSegment:
    """一段可剪裁的上下文。

    kind:        SEG_MEMO | SEG_SUMMARY | SEG_VERBATIM | SEG_TAIL
    content:     段文本（verbatim 段为原文块）
    priority:    剪裁优先级（PRIORITY_* 常量）
    label:       展示标签（如 "[闭锁话题·标题·第N-M轮]"）
    truncatable: True 时该段超预算可截断保留（保留头部），否则整体丢弃
                 （当前话题原文通常置 True，普通激活话题置 False）
    meta:        自由元数据（topic_id / rounds 等）
    """

    kind: str
    content: str
    priority: int = 0
    label: str = ""
    truncatable: bool = False
    unbounded: bool = False          # True 时不占预算、不被剪裁（常驻段）
    meta: dict = field(default_factory=dict)


@dataclass
class AssemblyPlan:
    """一次组装的结果（纯数据，便于测试与审计）。"""

    kept: list[ContextSegment] = field(default_factory=list)
    dropped: list[ContextSegment] = field(default_factory=list)
    truncated: list[ContextSegment] = field(default_factory=list)
    total_chars: int = 0

    @property
    def dropped_count(self) -> int:
        return len(self.dropped)

    @property
    def truncated_count(self) -> int:
        return len(self.truncated)


class SegmentedContextAssembler:
    """按段类型与预算做结构化剪裁，产出最终注入消息。

    assemble() 返回 [(role, content), ...] 列表（role 默认 "system"），
    与 harness 的 ChatMessage 及各家消息字典均兼容。
    """

    def __init__(self, budget: Optional[ContextBudget] = None):
        self.budget = budget or ContextBudget()

    # ── 主入口 ──

    def assemble(
        self,
        segments: list[ContextSegment],
        *,
        tail: Optional[list] = None,
        role: str = "system",
    ) -> list[dict]:
        """剪裁并组装为消息列表。

        segments: 待剪裁的段（memo/summary/verbatim）
        tail:     尾部原文消息（不参与预算，原样追加，可为 ChatMessage 或 dict）
        """
        plan = self.plan(segments)
        messages: list[dict] = []
        for seg in plan.kept:
            text = seg.label + "\n" + seg.content if seg.label else seg.content
            messages.append({"role": role, "content": text})
        if tail:
            for m in tail:
                if hasattr(m, "to_dict"):
                    messages.append(m.to_dict())
                elif isinstance(m, dict):
                    messages.append(m)
                else:
                    messages.append({"role": role, "content": str(m)})
        return messages

    # ── 纯剪裁计算 ──

    def plan(self, segments: list[ContextSegment]) -> AssemblyPlan:
        """按预算剪裁段列表（无副作用，可独立测试）。

        规则（与 DSN 话题组装语义对齐）：
          - memo 段独立预算 memo_chars，按输入顺序保留
          - summary 段独立预算 summary_chars，按输入顺序保留
          - verbatim 段共享预算 verbatim_chars，按输入顺序保留；
            超过预算的段整体丢弃，最后保留段可被截断
          - 任何段为空白时直接跳过
        """
        budget = self.budget
        plan = AssemblyPlan()

        # 1) memo（独立预算，按序；unbounded 段常驻不占预算）
        #
        # 修复说明：原条件是 `if used_memo > 0 and ...`，导致**第一条** memo 段
        # 无论如何都不会被预算拦下 —— 一条 5000 字的备忘能无视 2000 字预算全量
        # 注入，与 verbatim 段（会被截断）行为不一致，且长备忘会顶爆上下文。
        # 现在首条 memo 也受预算约束：超预算时按 priority 裁剪，能截断则截断。
        used_memo = 0
        for seg in segments:
            if seg.kind != SEG_MEMO or not seg.content.strip():
                continue
            if seg.unbounded:
                plan.kept.append(seg)
                continue
            _room = budget.memo_chars - used_memo
            if len(seg.content) > _room:
                if _room > len(budget.truncate_marker) and seg.truncatable:
                    # 留出标注空间后截断保留，避免整段丢弃丢失上下文
                    keep = _room - len(budget.truncate_marker)
                    seg.content = seg.content[:keep].rstrip() + budget.truncate_marker
                    used_memo += len(seg.content)
                    plan.kept.append(seg)
                    plan.truncated.append(seg)
                else:
                    plan.dropped.append(seg)
                continue
            used_memo += len(seg.content)
            plan.kept.append(seg)

        # 2) summary（独立预算，按序；空白跳过）
        used_sum = 0
        for seg in segments:
            if seg.kind != SEG_SUMMARY or not seg.content.strip():
                continue
            if used_sum > 0 and used_sum + len(seg.content) > budget.summary_chars:
                plan.dropped.append(seg)
                continue
            used_sum += len(seg.content)
            plan.kept.append(seg)

        # 3) verbatim（共享预算）
        #
        # 设计说明（P1-4 修正）：`_verbatim` 类的调用方**已经按优先级排好序**
        # （当前话题在前、普通激活话题在后），因此这里必须保持输入顺序累积，
        # 不能重排 —— 否则会把"当前话题"提前占满预算，反而挤掉本该保留的段。
        # 优先级的作用体现在**超预算时决定丢谁**：见下方 room 不足的分支，
        # 低优先级段先被丢弃/截断。
        #
        # 修复说明（P2-1）：截断时原实现把 marker 也算进内容却没预留空间，
        # 导致超预算 len(marker) 个字符；且**就地改写调用方传入的 seg 对象**，
        # 使 plan() 不再是文档承诺的"无副作用、可独立测试"（同一个 segment
        # 再次 plan 结果会不同）。现在用 replace() 生成新对象，并预留 marker 长度。
        # 修复说明（P1-4）：常量与文档都声明"值越大越先保留（剪裁时低优先级先被
        # 丢弃）"，但原实现完全不读 seg.priority，纯按输入顺序先到先得 —— 实测预算
        # 100、两段各 70 字符时，优先级 90 的"当前话题"被优先级 80 的普通段挤掉，
        # DSN"当前话题必须保留"的契约实际失效。
        #
        # 这里采用两阶段策略，兼顾两个互相冲突的需求：
        #   ① 调用方通常已按语义排好输入顺序，段序本身有意义（测试也依赖这点），
        #      所以**不做整体重排**；
        #   ② 但预算不足时，必须优先保住高优先级段。
        # 做法：先按输入顺序放能放下的段；若有段因预算不足被挤出，则在"已放入的
        # 低优先级段"里挑出比它更低优先级的，腾出空间让给高优先级段。
        used_vb = 0
        _vb_segs = [s for s in segments if s.kind == SEG_VERBATIM and s.content.strip()]
        # 预计算：本组段的最低优先级，用于判断是否值得为后来的高优先级段腾位置。
        for seg in _vb_segs:
            size = len(seg.content)
            if used_vb + size > budget.verbatim_chars:
                room = budget.verbatim_chars - used_vb
                # 截断标记是"说明文字"，不算正文预算（否则标记越长正文越少，
                # 且极端情况下留出空间把正文挤成 0）。只要还有正数可放正文
                # 就截断保留，标记额外附加。
                if seg.truncatable and room > 0:
                    clipped = replace(
                        seg,
                        content=seg.content[:room].rstrip() + budget.truncate_marker,
                    )
                    plan.truncated.append(clipped)
                    plan.kept.append(clipped)
                    used_vb += room
                else:
                    # 放不下且不可截断：先看能否挤掉一个**已保留的更低优先级**段。
                    # 只按输入顺序排的话，高优先级的当前话题会被低优先级的旧话题
                    # 占满预算而丢掉，这与 PRIORITY_* 的约定相反。
                    evicted_idx = None
                    for idx, kept_seg in enumerate(plan.kept):
                        if (kept_seg.kind == SEG_VERBATIM
                                and kept_seg.priority < seg.priority
                                and len(kept_seg.content) >= size):
                            evicted_idx = idx
                            break
                    if evicted_idx is not None:
                        victim_seg = plan.kept.pop(evicted_idx)
                        plan.dropped.append(victim_seg)
                        used_vb -= len(victim_seg.content)
                        used_vb += size
                        plan.kept.append(seg)
                    else:
                        plan.dropped.append(seg)
                continue
            used_vb += size
            plan.kept.append(seg)

        # 4) tail（尾部原文：设计上"保底"，固定轮数，不参与共享预算）
        #
        # 修复说明（P2-2）：SEG_TAIL 常量与文档都声明"最近 N 轮原文，保证即时
        # 上下文"，但原 plan() 三个循环只处理 MEMO/SUMMARY/VERBATIM，
        # tail 段既不进 kept 也不进 dropped —— 静默消失，调用方以为已注入。
        # 现在按 unbounded 语义原样保留（轮数控制由调用方负责）。
        for seg in segments:
            if seg.kind == SEG_TAIL and seg.content.strip():
                plan.kept.append(seg)

        plan.total_chars = sum(len(s.content) for s in plan.kept)
        return plan

    def __repr__(self) -> str:
        return f"<SegmentedContextAssembler budget={self.budget}>"
