# infra/runtime/checkpoint.py
# 检查点快照（策划案 §4.2.2）—— **可丢弃的加速器**，不是真相来源。
#
# 关键心智模型：
#     journal  = 事实（唯一真相，丢了就真的丢了）
#     checkpoint = 事实的快照（丢了可以从 journal 重放出来）
#
# 所以 checkpoint 损坏**不是**致命错误 —— 恢复流程必须能退化成
# 「纯 journal 重放」（策划案 §8.2 用例 7：checkpoint 损坏 → 从 journal 重放恢复）。
# 这里的 CheckpointCorruptError 就是把「这份快照不能用」这件事显式说出来，
# 让 recovery.py 去兜底，而不是让异常一路冒到用户面前。
#
# 快照里存什么由调用方决定（agent 的对话状态、变量、游标……），
# 本模块只负责：序列化、定位（session_id + turn_seq）、读回、以及**判损坏**。

from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

from .state import CheckpointRecord, checkpoint_ref
from .store import StorePort

logger = logging.getLogger('aicf.infra.runtime.checkpoint')

#: 快照里保留 journal 水位线的保留键。
#:
#: 为什么要存它：恢复时要知道「哪些事件还没被快照吃掉」。
#: 没有它就只能按 turn 粗略切分 —— 同一个 turn 内、快照之后发生的事件会被丢掉。
#: 它是**保留键**，读回时会从用户 blob 里摘掉，不污染调用方的状态。
JOURNAL_SEQ_KEY = '__journal_seq__'


class CheckpointCorruptError(RuntimeError):
    """检查点内容损坏（blob 不是合法 JSON / 不是对象）。

    语义是「这份快照不可用」，不是「整个恢复失败」——
    调用方应该退化成 journal 重放。
    """

    def __init__(self, session_id: str, turn_seq: int, detail: str = ''):
        super().__init__(
            f'检查点损坏: session={session_id} turn_seq={turn_seq} {detail}'.strip())
        self.session_id = session_id
        self.turn_seq = turn_seq
        self.detail = detail


class CheckpointStore:
    """runtime_checkpoint 表的读写。

    用法:
        store = CheckpointStore(port)
        ref = store.write(sid, turn_seq=3, blob={'messages': [...]})
        cp = store.latest(sid)      # 可能抛 CheckpointCorruptError
    """

    def __init__(self, port: StorePort):
        self._port = port

    # ── 写 ───────────────────────────────────────────────
    def write(self, session_id: str, turn_seq: int, blob: dict[str, Any], *,
              journal_seq: Optional[int] = None) -> str:
        """写一份检查点，返回引用串（`session_id@turn_seq`）。

        同一 (session_id, turn_seq) 重复写是**覆盖**语义：
        一个 turn 内多次打快照，只保留最新的那份 —— 旧快照已经没有价值，
        留着只会让「latest」选错。
        """
        payload = dict(blob or {})
        if journal_seq is not None:
            payload[JOURNAL_SEQ_KEY] = int(journal_seq)
        record = CheckpointRecord(
            session_id=session_id,
            turn_seq=turn_seq,
            blob=payload,
            created_at=time.time(),
            journal_seq=int(journal_seq or 0),
        )
        self._port.put_checkpoint(record)
        logger.debug('写入检查点 %s (journal_seq=%s)', record.ref, record.journal_seq)
        return record.ref

    # ── 读 ───────────────────────────────────────────────
    def load(self, session_id: str,
             turn_seq: Optional[int] = None) -> Optional[CheckpointRecord]:
        """读检查点。turn_seq 为 None 时取最新一份。

        损坏时抛 CheckpointCorruptError（而不是返回 None）——
        「没有快照」和「快照坏了」是两回事：前者正常重放，后者要先报警。
        """
        record = self._port.load_checkpoint(session_id, turn_seq)
        if record is None:
            return None
        return self._decode(record)

    def latest(self, session_id: str) -> Optional[CheckpointRecord]:
        """取最新一份检查点（同 load 的 None 语义）。"""
        return self.load(session_id, None)

    def list(self, session_id: str) -> list[CheckpointRecord]:
        """列出全部检查点（损坏的那份照样列出来，但会抛错让调用方知道）。"""
        return [self._decode(record)
                for record in self._port.list_checkpoints(session_id)]

    @staticmethod
    def _decode(record: CheckpointRecord) -> CheckpointRecord:
        """把存储层的 blob 还原成「用户 blob + journal 水位线」。

        blob_json 已经在存储层解析过一次；这里再校验它是不是**对象**：
        快照被写坏成数组/字符串时，它同样不可用。
        """
        blob = record.blob
        if not isinstance(blob, dict):
            raise CheckpointCorruptError(
                record.session_id, record.turn_seq,
                f'blob 不是对象而是 {type(blob).__name__}')
        journal_seq = blob.pop(JOURNAL_SEQ_KEY, None)
        try:
            journal_seq = int(journal_seq)
        except (TypeError, ValueError):
            journal_seq = 0
        return CheckpointRecord(
            session_id=record.session_id,
            turn_seq=record.turn_seq,
            blob=blob,
            created_at=record.created_at,
            journal_seq=journal_seq,
        )

    # ── 维护 ─────────────────────────────────────────────
    def prune(self, session_id: str, *, keep: int = 1) -> int:
        """只保留最近 keep 份检查点，返回被清理的份数。

        检查点是加速器，没必要无限堆积。
        保留逻辑放在存储实现里（那里才有 DELETE 权限），
        这里只表达意图 —— 所以用 store 端口的一个可选扩展方法。
        """
        pruner = getattr(self._port, 'prune_checkpoints', None)
        if pruner is None:
            return 0
        return int(pruner(session_id, keep))

    @staticmethod
    def ref(session_id: str, turn_seq: int) -> str:
        return checkpoint_ref(session_id, turn_seq)

    @staticmethod
    def encode(blob: dict[str, Any]) -> str:
        """把快照编码成 JSON 字符串（存储层一般不需要，测试与调试用）。"""
        return json.dumps(blob, ensure_ascii=False, default=repr)


__all__ = ['CheckpointStore', 'CheckpointCorruptError', 'JOURNAL_SEQ_KEY']
