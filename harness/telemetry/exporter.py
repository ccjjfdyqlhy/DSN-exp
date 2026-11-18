# harness/telemetry/exporter.py
# JSONL trace 导出（内核侧）+ 脱敏原语的再导出。
#
# 依赖方向：harness → infra，单向。脱敏与 JSONL 读写住在
# infra/observability/redact.py —— 它们是所有落盘路径共用的原语
# （trace / 审计 / 评测样本都要过同一道门），放在 infra 才不用逼着
# infra 反向依赖 harness。这里只做再导出，保证「脱敏只有一份实现」。
#
# 为什么用 JSONL 而不是 JSON 数组：一次 run 的 trace 是**流式**写出来的
# （run 还在跑的时候就要能看、能 tail）。JSON 数组必须等整个 run 结束才能写，
# 崩溃就全没了；JSONL 天然可以 append，崩了也保留已写下的部分。
#
# 缺陷备忘：
#   - 写文件用 UTF-8 + ensure_ascii=False：中文 payload 不该变成 \uXXXX。
#   - 落盘前统一脱敏（redact_values=True）：「写的时候没脱敏、事后想起来
#     再改一遍」是事故的常见来源。

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

from infra.observability.redact import (
    REDACTED,
    REFERENCE_KEY_SUFFIXES,
    SECRET_VALUE_PREFIXES,
    SENSITIVE_KEYS,
    SENSITIVE_KEY_PARTS,
    read_jsonl,
    redact,
    redact_dict,
    write_jsonl,
)

#: 一次 run 的标准 trace 文件名
TRACE_FILENAME = 'trace.jsonl'


class TraceExporter:
    """把 trace 记录写到一个 JSONL 文件。

    一个 run 一个文件：``TraceExporter(path)`` 写完 ``close()`` 即可。
    打开时 ``redact_values=True`` —— **落盘前**统一脱敏，
    避免「写的时候没脱敏、事后想起来再改一遍」。
    """

    def __init__(self,
                 path: str | os.PathLike[str],
                 *,
                 append: bool = False,
                 redact_values: bool = True,
                 secrets: Iterable[str] = ()) -> None:
        self.path = Path(path)
        self.redact_values = redact_values
        self._secrets = tuple(s for s in (secrets or ()) if s)
        self._count = 0
        self._fh = None
        self._open(append)

    def _open(self, append: bool) -> None:
        if self.path.parent and str(self.path.parent) not in ('', '.'):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, 'a' if append else 'w', encoding='utf-8')

    # ── 写 ──────────────────────────────────────────────
    def write(self, record: Mapping[str, Any]) -> None:
        if self._fh is None:
            raise RuntimeError('TraceExporter 已关闭')
        payload = dict(record)
        if self.redact_values:
            payload = redact_dict(payload, secrets=self._secrets)
        self._fh.write(json.dumps(payload, ensure_ascii=False, default=str))
        self._fh.write('\n')
        self._fh.flush()
        self._count += 1

    def write_span(self, span: Any) -> None:
        """写一个 span（接受 infra.observability.span.Span 或已转好的 dict）。"""
        if hasattr(span, 'to_dict'):
            record = span.to_dict()
            record.setdefault('type', 'span')
        else:
            record = dict(span)
        self.write(record)

    def write_event(self, kind: str, payload: Mapping[str, Any] | None = None) -> None:
        record = dict(payload or {})
        record['type'] = 'event'
        record['kind'] = kind
        self.write(record)

    def export(self, records: Iterable[Mapping[str, Any]]) -> int:
        for record in records:
            self.write(record)
        return self._count

    # ── 收尾 ────────────────────────────────────────────
    @property
    def count(self) -> int:
        return self._count

    def close(self) -> None:
        if self._fh is not None:
            self._fh.flush()
            self._fh.close()
            self._fh = None

    def __enter__(self) -> 'TraceExporter':
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False


def export_trace(path: str | os.PathLike[str],
                 records: Iterable[Mapping[str, Any]],
                 *,
                 append: bool = False,
                 redact_values: bool = True) -> int:
    """一次性写出整份 trace（便捷函数；返回写出的行数）。"""
    exporter = TraceExporter(path, append=append, redact_values=redact_values)
    try:
        return exporter.export(records)
    finally:
        exporter.close()


__all__ = [
    'REDACTED',
    'REFERENCE_KEY_SUFFIXES',
    'SECRET_VALUE_PREFIXES',
    'SENSITIVE_KEYS',
    'SENSITIVE_KEY_PARTS',
    'TRACE_FILENAME',
    'TraceExporter',
    'export_trace',
    'read_jsonl',
    'redact',
    'redact_dict',
    'write_jsonl',
]
