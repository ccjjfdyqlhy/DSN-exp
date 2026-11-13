# apps/dsn_study/context/__init__.py
# dsn_study 上下文内核 —— 公共接口出口。
#
# 依赖方向（恒定，不得反向 import、不得成环）：
#     types ← budget ← kernel ← {sources, store}
#
# 典型用法：
#     from apps.dsn_study.context import (
#         ContextKernel, ContextStore, ContextBudget,
#         StudyStateSource, MemoSource, SummarySource, TailSource,
#     )
#
#     store = ContextStore(db)
#     kernel = ContextKernel(store, [
#         StudyStateSource(plan_engine, graph_store, question_store),
#         MemoSource(store), SummarySource(store), TailSource(store),
#     ])
#     trace = kernel.build(turn)
#     text = ContextKernel.render(trace)     # 拼进 system prompt

from __future__ import annotations

from .budget import TRUNCATE_MARKER, ContextBudget, FitResult, fit
from .kernel import ContextKernel
from .sources import (
    ContextSource,
    MemoSource,
    StudyStateSource,
    SummarySource,
    TailSource,
)
from .store import ContextStore
from .types import (
    ASSISTANT_PREFIX,
    CTX_PREFIX,
    KIND_FACTS,
    KIND_LABELS,
    KIND_ORDER,
    KIND_STATE,
    KIND_SUMMARY,
    KIND_TAIL,
    KIND_TOOL_STATE,
    STATUS_DROPPED,
    STATUS_KEPT,
    STATUS_TRUNCATED,
    TAIL_HEADER,
    USER_PREFIX,
    BlockTrace,
    ContextBlock,
    ContextTrace,
    TurnContext,
)

__all__ = [
    # 类型
    "ContextBlock",
    "TurnContext",
    "BlockTrace",
    "ContextTrace",
    # 预算
    "ContextBudget",
    "FitResult",
    "fit",
    "TRUNCATE_MARKER",
    # 存储
    "ContextStore",
    # 来源
    "ContextSource",
    "StudyStateSource",
    "MemoSource",
    "SummarySource",
    "TailSource",
    # 内核
    "ContextKernel",
    # 常量
    "CTX_PREFIX",
    "TAIL_HEADER",
    "USER_PREFIX",
    "ASSISTANT_PREFIX",
    "KIND_STATE",
    "KIND_FACTS",
    "KIND_SUMMARY",
    "KIND_TAIL",
    "KIND_TOOL_STATE",
    "KIND_ORDER",
    "KIND_LABELS",
    "STATUS_KEPT",
    "STATUS_DROPPED",
    "STATUS_TRUNCATED",
]
