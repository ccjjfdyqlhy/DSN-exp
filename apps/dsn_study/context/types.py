# apps/dsn_study/context/types.py
# 上下文内核的数据类型（零依赖层）。
#
# 定位：
#   依赖链的最底层 —— types ← budget ← kernel ← {sources, store}。
#   本文件**不 import 任何其它模块**（只用标准库 dataclasses），
#   保证任何一层都能单独引用它而不产生环。
#
# 设计要点：
#   1. 全部是纯数据；块对象 frozen —— 裁剪函数 fit() 只用 dataclasses.replace()
#      生成新对象，**不改调用方传进来的块**（契约 §2.2 规则 7：纯函数）。
#   2. 呈现口径（前缀 / 标签 / 顺序）集中在这里，渲染时不再各处硬编码
#      —— 消灭旧实现里"5 处 2 版前缀"的问题。
#   3. ContextTrace 额外带一个 kept 字段：BlockTrace 按契约只带元信息
#      （kind/source/chars/status/reason），而 render(trace) 需要正文，
#      所以正文另存一份（详见 ContextTrace.kept 的注释）。

from __future__ import annotations

from dataclasses import dataclass, field

# ── 呈现口径常量 ────────────────────────────────────────────────────────

#: 动态层整段的固定前缀（所有块共用同一句，禁止各处硬编码）
CTX_PREFIX = "[系统上下文 · 供你参考，不要复述]"

#: tail（最近对话）段的标题
TAIL_HEADER = "[最近对话]"

#: tail 文本里用户/助手轮次的前缀
#: （同时是"最后一条 user 消息"的识别依据 —— 裁剪保底要用）
USER_PREFIX = "用户："
ASSISTANT_PREFIX = "助手："

# ── kind 常量（契约 §2.1）──────────────────────────────────────────────

KIND_STATE = "state"
KIND_FACTS = "facts"
KIND_SUMMARY = "summary"
KIND_TAIL = "tail"
KIND_TOOL_STATE = "tool_state"

#: 渲染顺序：学习状态 → 长期事实 → 会话摘要 → 工具状态 → 最近对话
KIND_ORDER = (KIND_STATE, KIND_FACTS, KIND_SUMMARY, KIND_TOOL_STATE, KIND_TAIL)

#: kind → 展示标签（tail 不加标签，原样保留对话形态）
KIND_LABELS = {
    KIND_STATE: "学习状态",
    KIND_FACTS: "长期事实",
    KIND_SUMMARY: "会话摘要",
    KIND_TOOL_STATE: "工具状态",
}

# ── 块状态（契约 §2.1）─────────────────────────────────────────────────

STATUS_KEPT = "kept"
STATUS_DROPPED = "dropped"
STATUS_TRUNCATED = "truncated"


@dataclass(frozen=True)
class ContextBlock:
    """上下文里的一段内容。

    kind:      'state' | 'facts' | 'summary' | 'tail' | 'tool_state'
    source:    'plan' | 'review' | 'errorbook' | 'memo' | 'compactor' | 'session'
    text:      正文
    priority:  越大越先保留（裁剪时低优先级先被丢）
    pinned:    True = 永远保留（仍计入全局上限）
    meta:      自由元数据（importance / ref_id / rounds …），**不得原地改写**
    """

    kind: str
    source: str
    text: str
    priority: int = 0
    pinned: bool = False
    meta: dict = field(default_factory=dict)

    def is_empty(self) -> bool:
        """正文是否为空（空块不进 prompt）。"""
        return not (self.text or "").strip()


@dataclass(frozen=True)
class TurnContext:
    """一轮对话的显式上下文（取代 contextvars 传递，见 D5）。

    uid:         用户 id
    session_id:  会话 id（UUID，跨进程稳定）
    message:     本轮用户消息
    round_index: 本会话第几轮（由 DB 分配，跨进程稳定）
    is_asr:      是否语音轮
    chat_id:     旧整数会话号（兼容字段，新链路可留 0）
    """

    uid: int
    session_id: str
    message: str
    round_index: int
    is_asr: bool = False
    chat_id: int = 0


@dataclass(frozen=True)
class BlockTrace:
    """单个块的裁剪痕迹（只带元信息，不带正文 —— 正文在 ContextTrace.kept）。"""

    kind: str
    source: str
    chars: int
    status: str
    reason: str = ""


@dataclass
class ContextTrace:
    """一次上下文组装的完整留痕（可观测性：任何降级都留痕）。

    blocks:      每个块的痕迹（kept / dropped / truncated）
    total_chars: 实际注入的字符数
    budget_chars:本轮全局硬上限
    degraded:    缺席/失败的来源（"source: 原因"）
    collect_ms:  采集 + 裁剪耗时（**毫秒**）
    kept:        裁剪后幸存的块（含正文）—— render(trace) 的数据来源
    """

    blocks: list[BlockTrace]
    total_chars: int
    budget_chars: int
    degraded: list[str]
    collect_ms: float
    kept: list[ContextBlock] = field(default_factory=list)

    def summary(self) -> dict:
        """可落库的摘要（不含正文，避免把上下文再存一份）。"""
        return {
            "total_chars": self.total_chars,
            "budget_chars": self.budget_chars,
            "collect_ms": round(self.collect_ms, 3),
            "degraded": list(self.degraded),
            "kept": sum(1 for b in self.blocks if b.status == STATUS_KEPT),
            "dropped": sum(1 for b in self.blocks if b.status == STATUS_DROPPED),
            "truncated": sum(1 for b in self.blocks if b.status == STATUS_TRUNCATED),
            "blocks": [
                {
                    "kind": b.kind,
                    "source": b.source,
                    "chars": b.chars,
                    "status": b.status,
                    "reason": b.reason,
                }
                for b in self.blocks
            ],
        }
