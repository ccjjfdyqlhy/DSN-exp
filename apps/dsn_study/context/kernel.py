# apps/dsn_study/context/kernel.py
# 上下文内核：编排"采集 → 裁剪 → 留痕 → 渲染"。
#
# 一轮对话的动态层上下文由这里产出：
#     blocks = 各 source 采集（每个 source 各自兜底）
#     kept   = budget.fit(blocks)（纯函数裁剪）
#     text   = render(trace)（统一格式，禁止各处硬编码前缀）
#
# 契约（REBUILD_SPEC §2.5）：
#   - build：依次调用各 source，**每个 source 包 try/except**，失败记进 trace.degraded；
#   - render：统一格式；kind == 'tail' 的块不加 "- [标签]" 前缀；空文本的块不出现。
#
# 依赖方向：kernel 依赖 types / budget；sources / store 依赖 types；
#   **不反向 import**（kernel 不 import sources / store 的实现）。

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Callable, Optional

from .budget import ContextBudget, fit
from .types import (
    CTX_PREFIX,
    KIND_LABELS,
    KIND_ORDER,
    KIND_TAIL,
    STATUS_KEPT,
    STATUS_TRUNCATED,
    BlockTrace,
    ContextBlock,
    ContextTrace,
    TAIL_HEADER,
    TurnContext,
)

if TYPE_CHECKING:  # 只用于类型标注：不产生运行期依赖，依赖方向不会成环
    from .sources import ContextSource

logger = logging.getLogger(__name__)


class ContextKernel:
    """上下文内核。

    用法：
        kernel = ContextKernel(store, [StudyStateSource(...), MemoSource(store),
                                       SummarySource(store), TailSource(store)])
        trace = kernel.build(turn)
        text = ContextKernel.render(trace)     # 塞进 system prompt

    说明：sources 按**鸭子类型**使用（只要求 name + collect），
    kernel 不在运行期 import sources / store —— 依赖方向恒为
    types ← budget ← kernel ← {sources, store}，不会成环。
    """

    def __init__(self, store, sources: list["ContextSource"],
                 budget: Optional[ContextBudget] = None,
                 trace_sink: Optional[Callable[[ContextTrace], None]] = None):
        self._store = store
        self._sources = list(sources or [])
        self._budget = budget or ContextBudget()
        self._trace_sink = trace_sink

    # ── 组装 ────────────────────────────────────────────────────────

    def build(self, turn: TurnContext) -> ContextTrace:
        """采集 + 裁剪，产出一次完整的上下文留痕。"""
        started = time.perf_counter()
        blocks: list[ContextBlock] = []
        degraded: list[str] = []

        for source in self._sources:
            name = getattr(source, "name", None) or type(source).__name__
            try:
                produced = source.collect(turn)
            except Exception as exc:  # noqa: BLE001 - 单来源失败不影响其它来源
                logger.warning("上下文来源 %s 采集失败（已跳过）：%s", name, exc)
                degraded.append("%s: %s" % (name, exc))
                continue
            for block in produced or []:
                if not isinstance(block, ContextBlock):
                    logger.warning("上下文来源 %s 产出了非法块（已忽略）：%r", name, block)
                    continue
                blocks.append(block)

        result = fit(blocks, self._budget)

        # **每个块一条痕迹**（kept / truncated / dropped 三选一）——
        # 重复登记会让 summary() 的计数翻倍，这里按块去重。
        reasons = {id(b): t.reason for b, t in zip(result.truncated_blocks,
                                                   result.truncated)}
        traces: list[BlockTrace] = []
        for block in result.kept:
            is_truncated = id(block) in reasons
            traces.append(BlockTrace(
                kind=block.kind,
                source=block.source,
                chars=len(block.text or ""),
                status=STATUS_TRUNCATED if is_truncated else STATUS_KEPT,
                reason=reasons.get(id(block), ""),
            ))
        traces.extend(result.dropped)

        trace = ContextTrace(
            blocks=traces,
            total_chars=result.total_chars,
            budget_chars=self._budget.total_chars,
            degraded=degraded,
            collect_ms=(time.perf_counter() - started) * 1000.0,
            kept=result.kept,
        )

        if self._trace_sink is not None:
            try:
                self._trace_sink(trace)
            except Exception as exc:  # noqa: BLE001 - 落库失败不能影响本轮对话
                logger.warning("上下文 trace 落库失败（已忽略）：%s", exc)
        return trace

    # ── 渲染 ────────────────────────────────────────────────────────

    @staticmethod
    def render(trace: ContextTrace) -> str:
        """把上下文渲染成一段统一的 system 文本。

    格式（唯一口径，前缀常量集中在 types.py）：
        [系统上下文 · 供你参考，不要复述]
        - [学习状态] …
        - [长期事实] …
        - [会话摘要] …
        [最近对话]
        用户：…
        助手：…

    - kind == 'tail' 的块**不加** "- [标签]" 前缀（原样保留对话形态）；
    - 空文本的块不出现；
    - 没有任何内容时返回空串（调用方据此不拼进 prompt）。
    """
        kept = list(getattr(trace, "kept", None) or [])
        if not kept:
            return ""

        lines = [CTX_PREFIX]
        tail_header_done = False
        for kind in KIND_ORDER:
            for block in kept:
                if block.kind != kind:
                    continue
                text = (block.text or "").strip()
                if not text:
                    continue
                if kind == KIND_TAIL:
                    if not tail_header_done:
                        lines.append(TAIL_HEADER)
                        tail_header_done = True
                    lines.append(text)
                    continue
                label = KIND_LABELS.get(kind, kind)
                lines.append("- [%s] %s" % (label, text))

        if len(lines) <= 1:
            return ""
        return "\n".join(lines)
