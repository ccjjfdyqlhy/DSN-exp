# harness/memory/layers.py
# 分层记忆（策划案 §4.3.2 / D3）。
#
#   L0  Working   当前 turn 的工作记忆（scratchpad）      单 turn
#   L1  Episodic  会话内的历史事件摘要                    单 session
#   L2  Semantic  跨 session 的向量记忆                  长期
#   L3  Profile   用户/Agent 的稳定偏好与身份            长期、需授权
#
# 每次上下文装配按「预算占比 + 层级淘汰策略」裁剪：
#
#   层   默认预算占比   淘汰策略
#   L0   40%           先丢最旧
#   L1   30%           超预算时摘要压缩（复用 compaction，经压缩器注入）
#   L2   25%           按相关度 + 时效打分
#   L3   5%            不淘汰（但需显式授权才可注入）
#
# 为什么淘汰策略写死在层里：淘汰策略是**层的语义**的一部分
# （L3 不淘汰 = 偏好是身份的一部分，不是缓存），让调用方逐层各写一套
# 就会出现「某个调用点忘了 L3 不淘汰」这种静默丢身价的 bug。

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .base import MemoryEntry

#: 各层的默认预算占比（策划案 §4.3.2 的表）
DEFAULT_LAYER_BUDGETS: dict[str, float] = {
    'L0': 0.40,
    'L1': 0.30,
    'L2': 0.25,
    'L3': 0.05,
}

#: 层的淘汰策略（写死 —— 它是层的语义）
LAYER_POLICIES: dict[str, str] = {
    'L0': 'drop_oldest',
    'L1': 'compact',
    'L2': 'relevance_recency',
    'L3': 'keep',
}

#: 层的生命周期
LAYER_SCOPE: dict[str, str] = {
    'L0': 'turn',
    'L1': 'session',
    'L2': 'long_term',
    'L3': 'long_term_authorized',
}

KNOWN_LAYERS: tuple[str, ...] = ('L0', 'L1', 'L2', 'L3')

logger = logging.getLogger('harness.memory.layers')

#: L3 注入必须先有显式授权（策划案 §4.3.4：只存用户显式授权的偏好）
ProfileAuthorizer = Callable[[str], bool]


@dataclass
class LayerEntry:
    """一条带层的记忆。"""

    text: str
    layer: str = 'L0'
    score: float = 0.0           # 相关度（L2 用；检索方给）
    timestamp: float = 0.0
    citation: str = ''

    def chars(self) -> int:
        return len(self.text)


def _layer_of(entry: Any) -> str:
    """从既有记忆对象里认出层标记（meta.layer 或 dataclass 的 layer）。"""
    layer = getattr(entry, 'layer', None)
    if layer is None:
        meta = getattr(entry, 'meta', None) or {}
        if isinstance(meta, dict):
            layer = meta.get('layer')
    return str(layer or 'L2').upper() if layer else 'L2'


def _timestamp_of(entry: Any) -> float:
    ts = getattr(entry, 'timestamp', None)
    if ts is None:
        meta = getattr(entry, 'meta', None) or {}
        if isinstance(meta, dict):
            ts = meta.get('timestamp')
    try:
        return float(ts or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _text_of(entry: Any) -> str:
    text = getattr(entry, 'text', None)
    if text is None:
        text = getattr(entry, 'content', '')
    return str(text or '')


class LayeredMemoryView:
    """把一**批**记忆按 L0–L3 分层并按预算装配。

    它不是存储 —— 存储仍是 IMemoryStore / vector store（策划案：复用，
    不重造）。它是**装配策略**：拿着检索回来的记忆列表，按层裁剪，
    输出可直接进 prompt 的有序内容。
    """

    def __init__(self, *,
                 budgets: dict[str, float] | None = None,
                 compactor: Callable[[list[str], int], str] | None = None,
                 profile_authorized: ProfileAuthorizer | None = None,
                 now: float | None = None):
        #: 预算占比可覆盖，但**总和必须 = 1** —— 不留默认加和漂移的空间
        merged = dict(DEFAULT_LAYER_BUDGETS)
        for key, value in (budgets or {}).items():
            key = str(key).upper()
            if key not in DEFAULT_LAYER_BUDGETS:
                raise ValueError(f'未知记忆层: {key!r}（可选: {KNOWN_LAYERS}）')
            merged[key] = float(value)
        total = sum(merged.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f'记忆层预算占比之和必须是 1.0，现在是 {total}（{merged}）')
        self.budgets = merged
        #: 压缩器注入 L1 的摘要（复用 context_assembly 的 compaction 由调用方做）
        self.compactor = compactor
        #: L3 授权判定；None = 全部拒（没有授权器 = 没有授权）
        self.profile_authorized = profile_authorized
        self._now = now if now is not None else time.time()

    # ── 装配 ─────────────────────────────────────────────
    def assemble(self, memories: list[Any], total_budget: int, *,
                 query: str = '') -> list[tuple[str, str]]:
        """按层裁剪，返回 [(layer, text), ...]（层序 L0→L3）。

        各层先各拿自己的预算裁到符合淘汰策略，再按层顺序拼接 ——
        层顺序即策划案 §4.3.2 的优先级（L3 偏好最贴近人设，放最后）。
        """
        buckets: dict[str, list[Any]] = {k: [] for k in KNOWN_LAYERS}
        for m in memories or []:
            buckets[_layer_of(m)].append(m)

        out: list[tuple[str, str]] = []
        for layer in KNOWN_LAYERS:
            layer_budget = int(total_budget * self.budgets[layer])
            kept = self._evict(layer, buckets[layer], layer_budget,
                               query=query)
            for item in kept:
                out.append((layer, _text_of(item)))
        return out

    # ── 各层淘汰策略 ─────────────────────────────────────
    def _evict(self, layer: str, entries: list[Any],
               budget_chars: int, *, query: str = '') -> list[Any]:
        if budget_chars <= 0:
            return []
        policy = LAYER_POLICIES[layer]
        if policy == 'keep':
            # L3 不淘汰，但要**显式授权**才可注入（§4.3.4）
            if self.profile_authorized is None:
                return []
            allowed = []
            for e in entries:
                who = self._profile_subject(e)
                try:
                    if self.profile_authorized(who):
                        allowed.append(e)
                except Exception:
                    # 授权器故障按「未授权」处理（fail-closed），但留痕可查
                    logger.exception('L3 授权判定失败 subject=%s', who)
            return self._cap(allowed, budget_chars)
        if policy == 'drop_oldest':
            # L0：先丢最旧（scratchpad 的价值随时间衰减得最快）
            ordered = sorted(entries, key=_timestamp_of, reverse=True)
            return self._cap(ordered, budget_chars)
        if policy == 'compact':
            # L1：超预算时摘要压缩
            ordered = sorted(entries, key=_timestamp_of, reverse=True)
            texts = [_text_of(e) for e in ordered]
            total = sum(len(t) for t in texts)
            if total <= budget_chars:
                return ordered
            if self.compactor is None:
                # 没有压缩器也要保底：保住最新的若干条（绝不静默清空）
                return self._cap(ordered, budget_chars)
            budget_for_summary = budget_chars
            recent: list[Any] = []
            kept_chars = 0
            # 最新的条目原文保留（最近的事最不值得摘要）
            for e in ordered:
                n = len(_text_of(e)) + 2
                if kept_chars + n > budget_chars * 0.5:
                    break
                recent.append(e)
                kept_chars += n
            rest = [e for e in ordered if e not in recent]
            if rest:
                summary = self.compactor([_text_of(e) for e in rest],
                                         budget_for_summary - kept_chars)
                head = MemoryEntry(
                    text=f'（会话摘要）{summary}',
                    role='system',
                    meta={'layer': 'L1', 'compact': True},
                    timestamp=self._now,
                )
                return [head, *recent]
            return recent
        if policy == 'relevance_recency':
            # L2：按相关度 + 时效打分（策划案 §4.3.2：相关度为主，时效为辅）
            def score(e: Any) -> float:
                rel = float(getattr(e, 'score', 0.0) or 0.0)
                ts = _timestamp_of(e)
                age_hours = max(0.0, (self._now - ts) / 3600.0) if ts else 0.0
                # 半衰期 24h：时效是乘数不是主项
                return rel * (0.5 ** (age_hours / 24.0))
            ordered = sorted(entries, key=score, reverse=True)
            return self._cap(ordered, budget_chars)
        return []

    def _cap(self, entries: list[Any], budget_chars: int) -> list[Any]:
        kept: list[Any] = []
        used = 0
        for e in entries:
            n = len(_text_of(e))
            if used + n > budget_chars and kept:
                break
            kept.append(e)
            used += n
        return kept

    def _profile_subject(self, entry: Any) -> str:
        meta = getattr(entry, 'meta', None) or {}
        if isinstance(meta, dict):
            return str(meta.get('subject') or '')
        return str(getattr(entry, 'subject', '') or '')


__all__ = [
    'DEFAULT_LAYER_BUDGETS',
    'KNOWN_LAYERS',
    'LAYER_POLICIES',
    'LAYER_SCOPE',
    'LayerEntry',
    'LayeredMemoryView',
]
