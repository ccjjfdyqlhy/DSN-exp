# apps/dsn_study/context/budget.py
# 上下文预算与裁剪（**纯函数层**，可独立测试）。
#
# 契约（apps/dsn_study/REBUILD_SPEC.md §2.2）逐条落地：
#   1. total_chars 是**全局**上限，所有块合计 ≤ 它（tail 也计入 —— 修 F2）；
#   2. **tail 保底**：先给 kind == 'tail' 分配 tail_chars，tail 永不丢；
#      最后一条 user 消息在任何预算下都在（红线 R9）；
#   3. 其余块按 priority 从高到低填剩余额度；
#   4. **截断保留尾部**（text[-n:]），不保留头部（修 F1）；
#   5. **禁止静默丢中段**：非 tail 块要么整体保留、要么整体丢弃并记原因，
#      不做"保留头 + 丢中间"的截断；
#   6. 截断标记长度**先预留**，实际产出恒 ≤ 上限（修 F3）；
#   7. **纯函数**：不改传入的 block（用 dataclasses.replace），同输入同输出（修 F4）；
#   8. pinned=True 的块永远保留（仍计入上限）。
#
# 优先级说明（本实现的取舍，README 有完整表述）：
#   - tail 与 pinned 是**保底**，优先于全局上限：宁可溢出也不丢最近对话 / 钉住的块；
#   - 非 tail 块**不截断**：放不下就整体丢弃并留痕（契约规则 5 明文要求）。
#
# 依赖方向：只依赖 types（types ← budget ← kernel ← {sources, store}），不反向 import。

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Optional

from .types import (
    ASSISTANT_PREFIX,
    KIND_FACTS,
    KIND_STATE,
    KIND_SUMMARY,
    KIND_TAIL,
    STATUS_DROPPED,
    STATUS_TRUNCATED,
    USER_PREFIX,
    BlockTrace,
    ContextBlock,
)

#: 截断标记（截断保留尾部，所以标记放在**前面**）
#: 长度在裁剪时**先预留**，保证实际产出 ≤ 上限。
TRUNCATE_MARKER = "…（前文已省略）\n"


@dataclass(frozen=True)
class ContextBudget:
    """上下文预算参数。

    total_chars: 全局硬上限（**含 tail**，唯一的上限）
    tail_chars:  tail 的保底额度（最近对话）
    state_chars: 学习状态类块（state）的软上限
    facts_chars: 长期事实类块（facts）的软上限
    summary_chars:会话摘要类块（summary）的软上限
    """

    total_chars: int = 6000
    tail_chars: int = 2000
    state_chars: int = 400
    facts_chars: int = 400
    summary_chars: int = 800

    def kind_limit(self, kind: str) -> Optional[int]:
        """某个 kind 的软上限；None = 不单独限，只受全局上限约束。"""
        return {
            KIND_STATE: self.state_chars,
            KIND_FACTS: self.facts_chars,
            KIND_SUMMARY: self.summary_chars,
        }.get(kind)


@dataclass
class FitResult:
    """裁剪结果（纯数据，便于断言与审计）。

    kept:      幸存的块（截断过的块是 replace 出来的**新对象**）
    dropped:   被整体丢弃的块 + 原因
    truncated: 被截断的块 + 原因
    total_chars: 最终注入的字符数
    """

    kept: list[ContextBlock]
    dropped: list[BlockTrace]
    truncated: list[BlockTrace]
    total_chars: int
    #: 被截断的块本体（与 truncated 一一对应）——
    #: 附加字段：truncated 只带元信息，kernel 需要靠它给 kept 里的块标 truncated。
    truncated_blocks: list[ContextBlock] = field(default_factory=list)


# ── 裁剪主流程 ──────────────────────────────────────────────────────────


def fit(blocks: list[ContextBlock], budget: ContextBudget) -> FitResult:
    """按预算裁剪上下文块（**纯函数**：不改入参，同输入必同输出）。"""
    budget = budget or ContextBudget()
    kept: list[tuple[int, ContextBlock]] = []   # (原始下标, 块)
    dropped: list[BlockTrace] = []
    truncated: list[BlockTrace] = []
    truncated_blocks: list[ContextBlock] = []

    # ── 0) 清洗：空文本块不进上下文（pinned 的空块保留，代价为 0）──
    usable: list[tuple[int, ContextBlock]] = []
    for idx, block in enumerate(blocks or []):
        if not isinstance(block, ContextBlock):
            continue
        if block.is_empty() and not block.pinned:
            dropped.append(_trace(block, STATUS_DROPPED, "空文本"))
            continue
        usable.append((idx, block))

    tail_items = [it for it in usable if it[1].kind == KIND_TAIL]
    other_items = [it for it in usable if it[1].kind != KIND_TAIL]

    # ── 1) tail 保底：先占额度（契约规则 2）──
    tail_allowance = _tail_allowance(tail_items, budget)
    used_tail = 0
    used_total = 0
    kind_used: dict[str, int] = {}
    for idx, block in tail_items:
        size = len(block.text or "")
        room = tail_allowance - used_tail
        if size <= room or block.pinned:
            # pinned 的 tail 块也**不截断**（规则 8：永远保留）
            kept.append((idx, block))
            used_total += size
            used_tail += size
            continue
        # 放不下 → 截断，但**保留尾部**（规则 4），标记长度先预留（规则 6）
        new_text, reason = _truncate_tail(block.text or "", room)
        clipped = replace(block, text=new_text)
        kept.append((idx, clipped))
        truncated.append(_trace(clipped, STATUS_TRUNCATED, reason))
        truncated_blocks.append(clipped)
        used_total += len(new_text)
        used_tail += len(new_text)

    # ── 2) pinned 永远保留（规则 8），仍计入全局上限 ──
    pinned_items = [it for it in other_items if it[1].pinned]
    rest_items = [it for it in other_items if not it[1].pinned]
    for idx, block in pinned_items:
        kept.append((idx, block))
        size = len(block.text or "")
        used_total += size
        kind_used[block.kind] = kind_used.get(block.kind, 0) + size

    # ── 3) 其余块按 priority 从高到低填剩余额度（规则 3）──
    remaining = budget.total_chars - used_total
    ordered = sorted(rest_items, key=lambda item: (-item[1].priority, item[0]))
    for idx, block in ordered:
        size = len(block.text or "")
        limit = budget.kind_limit(block.kind)
        used_kind = kind_used.get(block.kind, 0)
        if limit is not None and used_kind + size > limit:
            # 非 tail 块**不截断**：放不下就整体丢弃并留痕（规则 5）
            dropped.append(_trace(block, STATUS_DROPPED,
                                  "超出 %s 预算（上限 %d 字）" % (block.kind, limit)))
            continue
        if size > remaining:
            dropped.append(_trace(block, STATUS_DROPPED,
                                  "超出全局预算（剩余 %d 字）" % max(0, remaining)))
            continue
        kept.append((idx, block))
        remaining -= size
        kind_used[block.kind] = used_kind + size

    # 恢复输入顺序（稳定输出，便于断言与渲染）
    kept.sort(key=lambda item: item[0])
    kept_blocks = [block for _, block in kept]
    return FitResult(
        kept=kept_blocks,
        dropped=dropped,
        truncated=truncated,
        total_chars=sum(len(b.text or "") for b in kept_blocks),
        truncated_blocks=truncated_blocks,
    )


# ── 内部工具 ────────────────────────────────────────────────────────────


def _trace(block: ContextBlock, status: str, reason: str = "") -> BlockTrace:
    """给块生成一条痕迹。"""
    return BlockTrace(
        kind=block.kind,
        source=block.source,
        chars=len(block.text or ""),
        status=status,
        reason=reason,
    )


def _round_starts(text: str) -> list[int]:
    """tail 文本里每一轮对话的起点（"用户：" 的位置，升序）。

    截断点对齐到轮次边界 —— 宁可少留一轮，也不要留半句话。
    """
    starts: list[int] = []
    pos = 0
    while True:
        idx = text.find(USER_PREFIX, pos)
        if idx < 0:
            break
        starts.append(idx)
        pos = idx + len(USER_PREFIX)
    return starts


def _last_user_segment(text: str) -> str:
    """最后一条 user 消息（"用户：…" 到下一条 "助手：" 之前；没有则到结尾）。

    保底用：无论预算多小，这条消息都不能整条消失（红线 R9）。
    """
    pos = (text or "").rfind(USER_PREFIX)
    if pos < 0:
        return ""
    end = text.find(ASSISTANT_PREFIX, pos)
    return text[pos:end] if end > 0 else text[pos:]


def _tail_allowance(tail_items: list[tuple[int, ContextBlock]],
                    budget: ContextBudget) -> int:
    """tail 的可用额度。

    - 默认 `budget.tail_chars`，但不超过全局上限；
    - **至少**要放得下最后一条 user 消息（保底）：宁可略超上限也不丢它。
    """
    need = 0
    for _, block in tail_items:
        need = max(need, len(_last_user_segment(block.text or "")))
    allowance = min(budget.tail_chars, budget.total_chars)
    return max(allowance, need)


def _truncate_tail(text: str, room: int) -> tuple[str, str]:
    """把 tail 文本裁到 `room` 以内，**保留尾部**（最近的内容）。

    返回 (新正文, 原因)：
    - 标记长度**先预留** → 正文只留 room - len(marker) 个字符，产出恒 ≤ room；
    - 截断点对齐**轮次边界**：优先保留尽量多的完整轮次，不留半句话；
    - 最后一条 user 消息**保底**：连一轮都放不下时，宁可只留它
      （红线 R9：最近的用户消息不能整条消失）。
    """
    room = max(0, room)
    if len(text) <= room:
        return text, ""

    marker = TRUNCATE_MARKER
    keep_room = room - len(marker)
    if keep_room < 0:
        # 额度连标记都放不下 → 只留正文尾部，不加标记
        marker = ""
        keep_room = room

    # ① 保留尽量多的**完整轮次**（截断点对齐轮次边界）
    for start in reversed(_round_starts(text)):
        if len(text) - start <= keep_room:
            kept = text[start:]
            reason = "保留尾部（丢弃前文 %d 字，截断点对齐轮次边界）" % start
            return marker + kept, reason

    # ② 保底：只留最后一条 user 消息
    last_user = _last_user_segment(text)
    if last_user and len(last_user) <= room:
        if len(marker) + len(last_user) <= room:
            reason = "预算不足：保底保留最后一条用户消息"
            return marker + last_user, reason
        reason = "预算不足：保底保留最后一条用户消息（省略标记）"
        return last_user, reason

    # ③ 连一条 user 消息都放不下 → 纯尾部裁剪（最后 room 个字符）
    kept = text[-room:] if room > 0 else ""
    reason = "保留尾部（预算不足，丢弃前文 %d 字）" % (len(text) - len(kept))
    if len(marker) + len(kept) <= room:
        return marker + kept, reason
    return kept, reason
