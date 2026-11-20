# infra/eval/badcase.py
# Bad Case 回流（策划案 §4.6.6 / rc2 P2）。
#
#   失败样本 + 用户负反馈 → badcase 表 → 人工/自动标注
#     → 进入 Dataset 的 hard_cases 分组 → 回归集
#
# ── 为什么「回流」而不只是「记录」 ──
# rc0 已有 record_badcase 写入通道，但写入不等于回流：
# 没有标注与晋级，坏样本只是坟场里的碑。回流的意思是：
# 坏样本最终**出现在下一轮回归集里**，任何后续发布都必须跑通它 ——
# 这才是「门禁不脱节」的闭环（§4.6.6 为什么必须回流）。
#
# 本模块补的是通道的后半段：
#   intake      把失败样本 / 负反馈记成 badcase（复用 trace_store 的表）
#   label       人工/自动标注（open → labelled → queued）
#   to_dataset  把 queued 的坏样本写成 EvalCase（hard_cases 分组）

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from .dataset import EvalCase
from .sampling import ReplayQueue

#: badcase 的生命周期
STATUS_NEW = 'new'
STATUS_LABELLED = 'labelled'
STATUS_QUEUED = 'queued'         # 已进回归集
STATUS_DISMISSED = 'dismissed'   # 标注后判定不需要回流（误报）

#: 回流样本进入的 dataset 分组（策划案 §4.6.6：hard_cases 分组）
HARD_CASE_GROUP = 'hard_cases'


@dataclass
class LabelledBadCase:
    """一条标注后的坏样本。"""

    id: str
    session_id: str
    trace_id: str
    reason: str
    label: str = ''                 # 标注内容（复现要点 / 期望行为）
    group: str = HARD_CASE_GROUP
    status: str = STATUS_LABELLED
    input_text: str = ''
    expect: list = field(default_factory=list)
    critical: bool = True           # hard case 默认进关键集（策划案：必须跑通）
    created_at: float = 0.0

    def to_case(self) -> EvalCase:
        """转成一条评测 case —— 关键集冻结只增不删（风险 R-8 的缓解）。"""
        case_id = f'hard_{self.id}'
        return EvalCase(
            id=case_id,
            group=self.group,
            critical=self.critical,
            input=self.input_text or f'replay session {self.session_id}',
            expect=list(self.expect) or [{'tool_called_any': True}],
            description=self.label or self.reason,
            tags=['hard_case', f'source_badcase:{self.id}',
                  f'session:{self.session_id}'],
        )


class BadCaseIntake:
    """坏样本回流管线：intake → label → queue → to_dataset。"""

    def __init__(self, store: Any, *,
                 queue: ReplayQueue | None = None):
        # store 是 infra/eval/trace_store.SqliteTraceStore（鸭子类型：
        # 需要 record_badcase / list_badcases / set_badcase_status）。
        self._store = store
        self.queue = queue if queue is not None else ReplayQueue()

    # ── intake ───────────────────────────────────────────
    def intake(self, *, session_id: str, trace_id: str = '', reason: str,
               source: str = 'replay', **extra: Any) -> str:
        """记一条坏样本（失败重放 / 用户负反馈都可走这里）。"""
        if not str(reason or '').strip():
            raise ValueError('badcase 必须带 reason：无因的坏样本无法标注')
        return self._store.record_badcase(
            session_id=str(session_id), trace_id=str(trace_id),
            reason=f'{source}:{reason}')

    # ── label ────────────────────────────────────────────
    def label(self, badcase_id: str, *, label: str,
              input_text: str = '',
              expect: Iterable[dict] | None = None,
              critical: bool = True) -> LabelledBadCase:
        """标注一条坏样本：补上复现要点与期望断言。"""
        rows = [r for r in self._store.list_badcases()
                if str(r.get('id')) == str(badcase_id)]
        if not rows:
            raise KeyError(f'badcase {badcase_id} 不存在')
        row = rows[0]
        record = LabelledBadCase(
            id=str(row['id']),
            session_id=str(row['session_id']),
            trace_id=str(row.get('trace_id') or ''),
            reason=str(row['reason']),
            label=str(label),
            status=STATUS_LABELLED,
            input_text=str(input_text),
            expect=list(expect or ()),
            critical=bool(critical),
            created_at=float(row.get('created_at') or 0.0),
        )
        self._set_status(badcase_id, record.status)
        return record

    def dismiss(self, badcase_id: str, *, note: str = '') -> None:
        """标注为误报 —— 留痕但不回流（ dismissing 也是一次标注）。"""
        self._set_status(badcase_id, STATUS_DISMISSED)

    # ── queue → dataset ──────────────────────────────────
    def promote_to_queue(self, record: LabelledBadCase) -> Any:
        """标注后的坏样本进重放队列（异步重放验证复现）。"""
        self._set_status(record.id, STATUS_QUEUED)
        return self.queue.enqueue(record.session_id,
                                  trace_id=record.trace_id,
                                  reason=f'badcase:{record.id}')

    def to_dataset(self, records: Iterable[LabelledBadCase]) -> list[EvalCase]:
        """把已标注的坏样本转成回归集 case（hard_cases 分组）。

        新增的 hard case 默认进入回归集（策划案 §4.6.6），
        任何后续发布都必须跑通。
        """
        cases: list[EvalCase] = []
        for record in records:
            if record.status != STATUS_LABELLED:
                raise ValueError(
                    f'badcase {record.id} 状态是 {record.status}，'
                    '只有已标注（labelled）的样本才能进回归集')
            cases.append(record.to_case())
        return cases

    def open_cases(self) -> list[dict[str, Any]]:
        return [r for r in self._store.list_badcases()
                if str(r.get('status')) == STATUS_NEW]

    # ── 内部 ─────────────────────────────────────────────
    def _set_status(self, badcase_id: str, status: str) -> None:
        setter = getattr(self._store, 'set_badcase_status', None)
        if callable(setter):
            setter(badcase_id, status)
            return
        # trace_store 还没有状态更新口时，重写一行（INSERT OR REPLACE）
        rows = [r for r in self._store.list_badcases()
                if str(r.get('id')) == str(badcase_id)]
        if rows:
            row = rows[0]
            self._store.record_badcase(
                session_id=str(row['session_id']),
                trace_id=str(row.get('trace_id') or ''),
                reason=str(row['reason']),
                status=status,
                badcase_id=badcase_id,
            )


__all__ = [
    'HARD_CASE_GROUP',
    'STATUS_DISMISSED',
    'STATUS_LABELLED',
    'STATUS_NEW',
    'STATUS_QUEUED',
    'BadCaseIntake',
    'LabelledBadCase',
]
