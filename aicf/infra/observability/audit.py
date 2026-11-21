# infra/observability/audit.py
# 统一审计事件（策划案 §4.4.7）。
#
# 两条硬约束：
#
#   1. **同流**：审计事件和业务事件走同一条事件总线（trace / 评估 / 成本都
#      能看见「发生过什么」），但审计方**自己独立存一份**。业务侧的日志
#      清理、trace 轮转、过期删除都动不到审计。
#   2. **不可删**：AuditStore 只暴露 append / 迭代，没有 delete / clear /
#      truncate。业务代码想删审计会直接抛 AuditImmutableError ——
#      「审计可被业务删除」等于没有审计。
#
# args_digest 只存参数的**哈希与长度**：审计必须能回答「这个工具调用带了
# 什么参数」，但明文可能是密钥 / 隐私 / 客户数据。哈希够用来比对两次调用
# 的参数是否一致（幂等键也是这么算的），长度够用来发现异常大的参数。
#
# 脱敏只有一个出口：harness.telemetry/exporter.py 的 redact()。
# 分散在各处各写一遍必然漏改一处，所以这里不自己实现，直接复用。
#
# 缺陷备忘：
#   - 审计事件**不能**带明文参数。哪怕只是「方便排查」也不行：
#     审计日志通常比业务日志留存更久，权限也更松。
#   - 拒绝原因 reason 应当取 policy/scope/sandbox/approval 四选一 ——
#     写成 'denied' 或 'error' 会让「为什么被拒」这个问题失去答案。
#     刻意**不强制**：可能还有尚未收录的新策略，宁可原样记下来，
#     也不要因为取值不在名单里就把审计丢了（丢失的审计比不规范的审计更糟）。
#   - credential_ref 是**引用**不是凭据本身：写 'vault://prod/db' 可以，
#     写实际 token 不行。

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from .redact import (  # noqa: F401  (re-export：脱敏的唯一出口)
    REDACTED,
    redact,
    redact_dict,
    write_jsonl,
)
from .span import SeqCounter, current_span_id, current_trace_id

__all__ = [
    'AUDIT_KINDS',
    'DENY_REASONS',
    'REDACTED',
    'ArgsDigest',
    'AuditImmutableError',
    'AuditLog',
    'AuditRecord',
    'AuditStore',
    'args_digest',
    'canonical_json',
    'redact',
    'redact_dict',
]

_LOGGER = logging.getLogger('aicf.infra.observability.audit')

#: 统一审计事件词表（策划案 §4.4.7）
AUDIT_KINDS = (
    'audit.tool_call',
    'audit.denied',
    'audit.secret_access',
    'audit.delegation',
    # 记忆写入也进审计轨（roadmap 段 4：愿景里「持久记忆的可审计」）。
    # 「这条记忆从哪来、谁改过、为什么被给了模型」必须能从审计里回答。
    'audit.memory_write',
)

#: 拒绝原因的合法取值 —— 回答「为什么被拒」时只允许这四种
DENY_REASONS = ('policy', 'scope', 'sandbox', 'approval')


class AuditImmutableError(RuntimeError):
    """业务侧试图删除审计记录。

    审计可被业务删除 = 没有审计。所以这里不是「记个日志然后照删」，
    而是直接拒绝。
    """


def canonical_json(value: Any) -> str:
    """参数的规范 JSON 表示（排序键、无多余空白）。

    哈希必须基于**规范**形式：同样的参数换个键序哈希就变了，
    「两次调用参数是否一致」这个问题就答不了。
    """
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), default=str)


class ArgsDigest(dict):
    """参数摘要：``{'sha256': ..., 'length': ...}``。

    用 dict 而不是裸字符串，是为了能直接塞进 JSON 审计记录；
    额外提供 .sha256 / .length 属性与可读 __str__，方便人看。
    """

    @property
    def sha256(self) -> str:
        return str(self.get('sha256', ''))

    @property
    def length(self) -> int:
        try:
            return int(self.get('length', 0))
        except (TypeError, ValueError):
            return 0

    def __str__(self) -> str:
        return f'sha256:{self.sha256};length={self.length}'


def args_digest(args: Any) -> ArgsDigest:
    """算出参数的哈希与长度（**不含明文**）。

    length 是规范 JSON 的**字节长度** —— 用来发现「参数突然大了一万倍」
    这类异常（正常不会）。
    """
    raw = canonical_json(args)
    data = raw.encode('utf-8')
    return ArgsDigest({
        'sha256': hashlib.sha256(data).hexdigest(),
        'length': len(data),
    })


@dataclass(frozen=True)
class AuditRecord:
    """一条审计记录。

    seq 在一条审计流内单调：审计也要能去重（journal 重放会重复投递）。
    """

    kind: str
    payload: dict = field(default_factory=dict)
    seq: int = 0
    ts: float = 0.0
    trace_id: str = ''
    span_id: str = ''

    def to_dict(self) -> dict[str, Any]:
        return {
            'type': 'audit',
            'kind': self.kind,
            'seq': self.seq,
            'ts': self.ts,
            'trace_id': self.trace_id,
            'span_id': self.span_id,
            'payload': dict(self.payload),
        }


class AuditStore:
    """只追加的审计存储。

    刻意**不提供** delete / clear / truncate / pop —— 审计不可被业务删除。
    唯一允许的删除路径是 purge_expired()，且必须显式给出留存策略；
    那是「按策略过期」，不是「业务想删就删」。
    """

    def __init__(self) -> None:
        self._records: list[AuditRecord] = []

    def append(self, record: AuditRecord) -> None:
        self._records.append(record)

    def records(self) -> list[AuditRecord]:
        return list(self._records)

    def of_kind(self, kind: str) -> list[AuditRecord]:
        return [r for r in self._records if r.kind == kind]

    def purge_expired(self, *, retention_seconds: float,
                     now: float | None = None) -> int:
        """按留存策略清掉过期审计，返回清掉多少条。

        这是**唯一**的删除入口，且必须显式给出正数留存时长 ——
        传 0 等于「全删」，那属于业务行为，不该从这个口子走。
        """
        if retention_seconds <= 0:
            raise ValueError('retention_seconds 必须为正：审计不能被整体清空')
        moment = time.time() if now is None else now
        keep = [r for r in self._records
                if moment - r.ts <= retention_seconds]
        removed = len(self._records) - len(keep)
        self._records = keep
        return removed

    def __iter__(self):
        return iter(list(self._records))

    def __len__(self) -> int:
        return len(self._records)


class AuditLog:
    """审计记录器。

    每条审计做两件事：
      1. 写进**独立存储**（AuditStore）—— 业务侧删不掉；
      2. **同流**发到事件总线（TelemetryPort）—— trace / 评估能看见。

    同一个 payload 两边一致，所以「trace 里看到的审计」和「审计库里的
    审计」不会对不上。
    """

    def __init__(self,
                 *,
                 store: AuditStore | None = None,
                 telemetry: Any = None,
                 redact_values: bool = True) -> None:
        self._store = store if store is not None else AuditStore()
        self._telemetry = telemetry
        self._redact_values = redact_values
        self._seq = SeqCounter()

    # ── 存储 ────────────────────────────────────────────
    @property
    def store(self) -> AuditStore:
        return self._store

    def records(self) -> list[AuditRecord]:
        return self._store.records()

    def of_kind(self, kind: str) -> list[AuditRecord]:
        return self._store.of_kind(kind)

    def __len__(self) -> int:
        return len(self._store)

    def __iter__(self):
        return iter(self._store)

    def clear(self) -> None:
        """**拒绝**清空审计。

        保留这个方法（而不是删掉）是为了让「想清空」的人拿到一个明确的
        拒绝，而不是 AttributeError —— 后者会让人去找别的绕路。
        """
        raise AuditImmutableError(
            '审计不可被业务删除：需要清理请走 AuditStore.purge_expired(retention_seconds=…)')

    # ── 记录 ────────────────────────────────────────────
    def record(self,
               kind: str,
               payload: Mapping[str, Any] | None = None,
               *,
               trace_id: str = '',
               span_id: str = '') -> AuditRecord:
        """记一条审计（同流 + 独立存储）。"""
        if not isinstance(kind, str) or not kind.startswith('audit.'):
            raise ValueError(f'审计事件 kind 必须以 "audit." 开头：{kind!r}')
        data = dict(payload or {})
        if self._redact_values:
            data = redact_dict(data)
        record = AuditRecord(
            kind=kind,
            payload=data,
            seq=self._seq.next(),
            ts=time.time(),
            # 审计默认挂在当前上下文上：审计要能回答「这条拒绝属于哪次运行」。
            trace_id=trace_id or current_trace_id.get() or '',
            span_id=span_id or current_span_id.get() or '',
        )
        self._store.append(record)
        if self._telemetry is not None:
            try:
                self._telemetry.emit(kind, dict(data))
            except Exception as exc:  # pragma: no cover - 同流失败不该丢审计
                _LOGGER.warning('审计同流失败 kind=%s: %s', kind, exc)
        return record

    def tool_call(self,
                  *,
                  identity: Any,
                  tool: str,
                  version: str | None = None,
                  args: Any = None,
                  args_digest: Any = None,
                  effect: str | None = None,
                  sandbox: str | None = None,
                  decision: str | None = None,
                  duration: float | None = None,
                  outcome: str | None = None,
                  **extra: Any) -> AuditRecord:
        """audit.tool_call —— 一次工具调用的完整审计。

        参数只进摘要（args_digest），**不进明文**。调用方可以直接传 args
        （本模块算摘要），也可以自己算好传进来。
        """
        digest = args_digest
        if digest is None and args is not None:
            digest = _compute_args_digest(args)
        payload: dict[str, Any] = {
            'identity': identity,
            'tool': tool,
            'version': version,
            'args_digest': digest,
            'effect': effect,
            'sandbox': sandbox,
            'decision': decision,
            'duration': duration,
            'outcome': outcome,
        }
        payload.update(extra)
        return self.record('audit.tool_call', payload)

    def denied(self,
               reason: str,
               *,
               tool: str | None = None,
               identity: Any = None,
               **extra: Any) -> AuditRecord:
        """audit.denied —— 一次拒绝。

        reason 应当取 DENY_REASONS 之一；这里不强制（拒绝原因可能来自
        尚未收录的新策略），但**原样记录**，绝不吞掉。
        """
        payload: dict[str, Any] = {'reason': reason}
        if tool is not None:
            payload['tool'] = tool
        if identity is not None:
            payload['identity'] = identity
        payload.update(extra)
        return self.record('audit.denied', payload)

    def secret_access(self,
                      credential_ref: str,
                      tool: str | None = None,
                      **extra: Any) -> AuditRecord:
        """audit.secret_access —— 一次凭据访问。

        credential_ref 是**引用**（如 'vault://prod/db'），不是凭据本身。
        """
        payload: dict[str, Any] = {'credential_ref': credential_ref}
        if tool is not None:
            payload['tool'] = tool
        payload.update(extra)
        return self.record('audit.secret_access', payload)

    def delegation(self,
                   from_: str,
                   to: str,
                   scopes: Sequence[str] | Iterable[str] = (),
                   **extra: Any) -> AuditRecord:
        """audit.delegation —— 一次授权传递。

        字段名用 'from' / 'to'（策划案原文）；'from' 是 Python 关键字，
        所以形参叫 from_。
        """
        payload: dict[str, Any] = {
            'from': from_,
            'to': to,
            'scopes': list(scopes or ()),
        }
        payload.update(extra)
        return self.record('audit.delegation', payload)

    def memory_write(self,
                     *,
                     action: str,
                     artifact_id: str = '',
                     revision: int | None = None,
                     source_ids: Sequence[str] | Iterable[str] = (),
                     content_digest: str = '',
                     author: str = '',
                     **extra: Any) -> AuditRecord:
        """audit.memory_write —— 一次记忆写入 / 修订 / 撤回。

        action ∈ source_added / artifact_written / artifact_revised /
        artifact_retracted（写的人自己保证；这里不强制枚举，
        但**原样记录**）。记忆**内容不进审计**（与 tool_call 的
        args_digest 同一纪律）：只存摘要与 id —— 内容本身在
        Source 层留证据，审计回答的是「谁在什么时候动了哪条」。
        """
        payload: dict[str, Any] = {
            'action': action,
            'artifact_id': artifact_id,
            'revision': revision,
            'source_ids': list(source_ids or ()),
            'content_digest': content_digest,
            'author': author,
        }
        payload.update(extra)
        return self.record('audit.memory_write', payload)

    # ── 导出 ────────────────────────────────────────────
    def export(self, path: str | os.PathLike[str]) -> int:
        """把审计写成独立的 JSONL 文件（与业务 trace 分开存放）。"""
        return write_jsonl(path, [r.to_dict() for r in self.records()])


#: 内部别名 —— tool_call 的形参 args_digest 遮住了模块级函数名
_compute_args_digest = args_digest
