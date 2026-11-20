# infra/eval/sampling.py
# 线上抽样（策划案 §4.6.6 / rc2 P2）。
#
# ── 为什么必须抽样 ──
# 只测自己造的题，评测集会迅速与真实分布脱节，门禁就变成
# 「门禁永远通过」的自欺欺人（策划案 §4.6.6 的原话）。
# 所以线上 session 按比例抽样，落进 eval 队列异步重放。
#
# ── 确定性抽样 ──
# 抽样必须**可复现**：「这批样本为什么被选中」要能事后回答。
# 所以用 hash(session_id, salt) 的均匀散列而不是 random ——
# 同一 salt 下重跑结果一致，不同 salt 之间无相关。

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

#: 默认抽样比例（策划案 §4.6.6：默认 5%）
DEFAULT_SAMPLE_RATIO = 0.05


def _bucket(session_id: str, salt: str) -> float:
    """session 在 [0,1) 上的确定性散列位置。"""
    payload = f'{salt}|{session_id}'.encode()
    digest = hashlib.sha256(payload).digest()
    value = int.from_bytes(digest[:8], 'big')
    return value / float(1 << 64)


@dataclass
class SamplingDecision:
    """一次抽样判定的完整依据（审计可回答「为什么这条被抽中」）。"""

    session_id: str
    sampled: bool
    bucket: float
    ratio: float
    salt: str

    def to_dict(self) -> dict[str, Any]:
        return {
            'session_id': self.session_id,
            'sampled': self.sampled,
            'bucket': self.bucket,
            'ratio': self.ratio,
            'salt': self.salt,
        }


class SessionSampler:
    """按比例确定性抽样线上 session。"""

    def __init__(self, *, ratio: float = DEFAULT_SAMPLE_RATIO,
                 salt: str = 'default'):
        if not 0.0 <= ratio <= 1.0:
            raise ValueError(f'ratio 必须在 [0,1]: {ratio}')
        self.ratio = float(ratio)
        self.salt = str(salt)

    def should_sample(self, session_id: str) -> bool:
        """这条 session 是否进 eval 队列。"""
        return self.decide(session_id).sampled

    def decide(self, session_id: str) -> SamplingDecision:
        bucket = _bucket(str(session_id), self.salt)
        return SamplingDecision(
            session_id=str(session_id),
            sampled=bucket < self.ratio,
            bucket=bucket,
            ratio=self.ratio,
            salt=self.salt,
        )

    def pick(self, session_ids: Iterable[str]) -> list[str]:
        """从一批 session 里选出被抽中的（保序）。"""
        return [sid for sid in session_ids if self.should_sample(str(sid))]


@dataclass
class ReplayQueueItem:
    """eval 重放队列的一项。"""

    session_id: str
    trace_id: str = ''
    reason: str = 'sampling'
    enqueued_at: float = 0.0
    status: str = 'queued'           # queued | replaying | done | skipped
    dataset_hint: str = ''           # 建议重放用哪份 dataset
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            'session_id': self.session_id,
            'trace_id': self.trace_id,
            'reason': self.reason,
            'enqueued_at': self.enqueued_at,
            'status': self.status,
            'dataset_hint': self.dataset_hint,
        }


class ReplayQueue:
    """eval 异步重放队列（内存版 —— rc2 的编排还不上进程间队列）。"""

    def __init__(self) -> None:
        self._items: dict[str, ReplayQueueItem] = {}

    def enqueue(self, session_id: str, *, trace_id: str = '',
                reason: str = 'sampling', dataset_hint: str = '') -> ReplayQueueItem:
        item = ReplayQueueItem(
            session_id=str(session_id), trace_id=trace_id, reason=reason,
            dataset_hint=dataset_hint)
        self._items.setdefault(item.session_id, item)
        return self._items[item.session_id]

    def drain(self, *, limit: int = 0) -> list[ReplayQueueItem]:
        """取走队列里的待重放项（标记 replaying；真正的重放由 eval 侧做）。"""
        out = [it for it in self._items.values() if it.status == 'queued']
        if limit:
            out = out[:limit]
        for it in out:
            it.status = 'replaying'
        return out

    def mark_done(self, session_id: str, *, skipped: bool = False) -> None:
        item = self._items.get(str(session_id))
        if item is not None:
            item.status = 'skipped' if skipped else 'done'

    def pending(self) -> list[ReplayQueueItem]:
        return [it for it in self._items.values() if it.status == 'queued']

    def __len__(self) -> int:
        return len(self._items)


__all__ = [
    'DEFAULT_SAMPLE_RATIO',
    'ReplayQueue',
    'ReplayQueueItem',
    'SamplingDecision',
    'SessionSampler',
]
