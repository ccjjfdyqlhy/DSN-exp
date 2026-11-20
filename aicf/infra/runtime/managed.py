# infra/runtime/managed.py
# 托管运行时的对外实现 —— 实现 harness.runtime_client.RuntimeClient 协议。
#
# Kernel / Guard 只认那个协议（事件出口 / 工具意图与结果 / 检查点），
# 所以这里是「Kernel 能看见的全部世界」：它把三件事收敛到一个可持久化的实现上：
#
#   1. 事件出口（journal 追加）
#   2. 工具调用的意图 / 结果记录（幂等与 unknown_outcome 的依据）
#   3. 检查点（加速恢复）
#
# 【为什么这里不 import aicf.harness】
#   依赖规则：harness 在上、infra 在下，反向依赖被禁止。
#   所以 ToolIntent 用**鸭子类型**接收（字段同名即可，harness 的实例照样能用），
#   幂等键公式各写一份（由 tests/test_rc0_runtime.py 的交叉测试钉死）。
#
# 【effectful 的三段式】
#   intent → 执行 → result，**顺序不可换**：
#     * 先写 intent：崩溃时我们至少知道「它开始干了」；
#     * 后写 result：崩溃时只剩 intent → 结果未知 → 交给人，绝不擅自重放。
#   如果反过来（先执行后写 intent），崩溃窗口里这次调用在 journal 里**根本不存在**，
#   恢复会把它当成「从没发生过」→ 重复执行 → 重复扣款。
#
# 【重复投递不产生第二次副作用】
#   execute_tool() 先查结果缓存（缓存未命中则回落到 journal 事件），
#   命中就直接复用结果 —— 同一幂等键投递 3 次，副作用只发生 1 次。

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .checkpoint import CheckpointStore
from .idempotency import ResultCache, args_digest, idempotency_key
from .journal import Journal
from .recovery import RecoveryPlan, UnknownOutcome, recover
from .state import (
    EFFECT_EFFECTFUL,
    EFFECT_PURE,
    EventKind,
    SessionRecord,
    SessionStatus,
    ToolIntentLike,
    TurnRecord,
    TurnStatus,
    checkpoint_ref,
    normalize_effect,
)
from .store import StorePort

logger = logging.getLogger('aicf.infra.runtime.managed')


class UnknownOutcomeError(RuntimeError):
    """试图重放一次**结果未知**的 effectful 调用。

    抛出点：ManagedRuntime.record_tool_intent —— 也就是「准备执行」的那一刻。
    为什么在那里抛：有些调用方（比如 harness/tools/guard.py）自己实现了
    「查缓存 → 写 intent → 执行 → 写结果」的流程，不经过 execute_tool。
    如果保护只放在 execute_tool 里，这条路径就会绕过它 → 重复副作用。
    所以保护必须落在**执行前的那道门**上。

    人确认过之后的重放走 execute_tool(..., approved=True)。
    """

    #: 跨层识别标记。infra 不能 import aicf.harness（依赖规则），所以 harness
    #: 侧的调用方靠这个属性认出「结果未知」，而不是当成普通失败。
    #: 靠 hasattr 判断 —— 认不出来时**不放行**（安全默认）。
    unknown_outcome = True

    def __init__(self, unknown: UnknownOutcome):
        super().__init__(
            f'拒绝重放结果未知的副作用调用: {unknown.tool} '
            f'(key={unknown.idempotency_key[:12]}…, effect={unknown.effect})')
        self.unknown = unknown


@dataclass
class ToolOutcome:
    """一次受管工具调用的结果。

    status:
      * executed       —— 真的执行了
      * reused         —— 命中幂等缓存，**没有**执行（重复投递）
      * unknown_outcome—— 结果未知，等人确认（**没有**执行）
      * failed         —— 执行抛异常
    """

    status: str
    tool: str = ''
    idempotency_key: str = ''
    effect: str = EFFECT_PURE
    result: Any = None
    error: Optional[BaseException] = None
    unknown: Optional[UnknownOutcome] = None

    @property
    def executed(self) -> bool:
        return self.status == 'executed'

    @property
    def reused(self) -> bool:
        return self.status == 'reused'

    @property
    def needs_human(self) -> bool:
        return self.status == 'unknown_outcome'

    def to_dict(self) -> dict[str, Any]:
        return {
            'status': self.status,
            'tool': self.tool,
            'idempotency_key': self.idempotency_key,
            'effect': self.effect,
        }


class ManagedRuntime:
    """实现 RuntimeClient 协议的托管运行时。

    用法:
        runtime = ManagedRuntime(store, session_id='s1')
        runtime.emit('run_started', {'run_id': 'r1'})
        outcome = runtime.execute_tool(
            tool='send_email', args={'to': 'x@y.z'}, fn=do_send,
            version='1.0', effect='effectful')
        if outcome.needs_human:
            ...  # 交给人确认，绝不自动重放
    """

    def __init__(self, port: StorePort, *, session_id: str,
                 turn_seq: int = 0, turn_id: str = '',
                 store_args: bool = True):
        """
        store_args:
            intent 事件里要不要存参数原文。
            存了才能在恢复时**自动重放** pure/idempotent 工具；
            不存则只能靠上层重新规划（安全但要多走一步）。
            默认存 —— 但注意参数里可能有敏感值，
            生产环境应当传一个脱敏后的 args 或把 store_args 关掉。
        """
        self._port = port
        self._journal = Journal(port)
        self._checkpoints = CheckpointStore(port)
        self._cache = ResultCache(port)
        self.session_id = session_id
        self.turn_seq = turn_seq
        self.turn_id = turn_id
        self.store_args = store_args
        #: 恢复后待人工确认的调用（幂等键 → 详情）
        self._unknown: dict[str, UnknownOutcome] = {}
        #: 最近一次 intent 的元信息（写 result 时补上 tool/version）
        self._intents: dict[str, dict[str, Any]] = {}

    # ── RuntimeClient 协议 ───────────────────────────────
    def emit(self, kind: str, payload: dict[str, Any]) -> None:
        """追加一条事件到 journal。"""
        self._journal.append(kind, payload, session_id=self.session_id,
                             turn_id=self.turn_id)

    def record_tool_intent(self, intent: ToolIntentLike, *,
                           args: Optional[dict[str, Any]] = None) -> None:
        """在执行工具前记录意图。

        接受鸭子类型（harness.runtime_client.ToolIntent 即可）。

        args 是可选的：只有**可重放**的工具（pure / idempotent）才值得把参数
        原文写进 journal —— 恢复时没有参数就没法自动重放。
        effectful 的参数原文不进 journal（既用不上，又可能含敏感值）。
        """
        key = str(getattr(intent, 'idempotency_key', '') or '')
        effect = normalize_effect(getattr(intent, 'effect', ''))
        payload: dict[str, Any] = {
            'tool': str(getattr(intent, 'tool', '') or ''),
            'tool_version': str(getattr(intent, 'tool_version', '') or ''),
            'idempotency_key': key,
            'effect': effect,
            'args_digest': str(getattr(intent, 'args_digest', '') or ''),
            'turn_seq': int(getattr(intent, 'turn_seq', self.turn_seq) or 0),
            'created_at': float(getattr(intent, 'created_at', 0.0) or 0.0) or time.time(),
        }
        if args is not None and self.store_args and effect != EFFECT_EFFECTFUL:
            payload['args'] = args

        # 执行前的门：**effectful 的在途调用（只有 intent、没有 result）不许重放**。
        # 抛异常而不是静默跳过 —— 静默跳过会让调用方以为「执行过了」，
        # 而实际上外部系统可能根本没动，也可能动了一半。
        if effect == EFFECT_EFFECTFUL and self._pending_intent(key) is not None:
            unknown = self._unknown.get(key) or UnknownOutcome(
                session_id=self.session_id,
                turn_seq=int(payload.get('turn_seq', 0) or 0),
                tool=payload['tool'],
                tool_version=payload['tool_version'],
                idempotency_key=key,
                effect=effect,
                args_digest=payload['args_digest'],
            )
            self._unknown.setdefault(key, unknown)
            self.emit(EventKind.TOOL_EFFECT_UNKNOWN, {
                'tool': payload['tool'],
                'idempotency_key': key,
                'effect': effect,
            })
            raise UnknownOutcomeError(unknown)

        self._write_intent(payload, key)

    def _write_intent(self, payload: dict[str, Any], key: str) -> None:
        """真正把 intent 事件写进 journal（不做任何判定）。"""
        self._intents[key] = payload
        self._journal.append(EventKind.TOOL_INTENT, payload,
                             session_id=self.session_id, turn_id=self.turn_id,
                             idempotency_key=key)

    def record_tool_result(self, idempotency_key: str, result: Any,
                           *, effect: str = EFFECT_PURE) -> None:
        """在工具执行后记录结果（事件 + 幂等缓存）。"""
        intent = self._intents.get(idempotency_key, {})
        payload = {
            'idempotency_key': idempotency_key,
            'tool': intent.get('tool', ''),
            'tool_version': intent.get('tool_version', ''),
            'effect': normalize_effect(effect),
            'result': result,
        }
        self._journal.append(EventKind.TOOL_RESULT, payload,
                             session_id=self.session_id, turn_id=self.turn_id,
                             idempotency_key=idempotency_key)
        self._cache.put(idempotency_key, result, tool=intent.get('tool', ''),
                        version=intent.get('tool_version', ''), effect=effect)

    def lookup_tool_result(self, idempotency_key: str) -> Any:
        """按幂等键查上次的结果；命中表示这次调用可以跳过。"""
        return self._cache.get_result(idempotency_key)

    def idempotency_key(self, session_id: str, turn_seq: int, tool: str,
                        args: Any = None) -> str:
        """算这次调用的幂等键（与 harness.runtime_client.idempotency_key 等价）。"""
        return idempotency_key(session_id, turn_seq, tool, args)

    def checkpoint(self, state: dict[str, Any]) -> Optional[str]:
        """写一个检查点，返回引用。

        顺序：先写 checkpoint_written 事件，**再**取 journal 水位线。
        这样水位线覆盖了这条事件本身，恢复时不会把它重放一遍
        （重放本身无害，但水位线的语义要清楚：<= 水位线 = 已被快照吃掉）。
        """
        if not self.session_id:
            return None
        ref = checkpoint_ref(self.session_id, self.turn_seq)
        self.emit(EventKind.CHECKPOINT_WRITTEN,
                  {'session_id': self.session_id, 'turn_seq': self.turn_seq, 'ref': ref})
        self._checkpoints.write(self.session_id, self.turn_seq, state,
                                journal_seq=self._journal.last_seq(self.session_id))
        return ref

    # ── 受管执行（幂等 + 三段式）────────────────────────
    def execute_tool(self, *, tool: str, fn: Callable[[], Any],
                     args: Any = None, version: str = '1.0',
                     effect: str = EFFECT_EFFECTFUL,
                     approved: bool = False) -> ToolOutcome:
        """执行一次工具调用，并把「不重复副作用」这件事做实。

        流程:
            1. 算幂等键
            2. 已有结果？→ 复用，**不执行**
            3. 结果未知（只有 intent）且是 effectful？→ 拒绝自动重放，等人确认
            4. 写 intent 事件
            5. 执行
            6. 写 result 事件 + 幂等缓存

        approved=True 表示「人已经点头了」，此时允许重放一次 result 未知的
        effectful 调用（并把这次重放记进 journal，留痕）。
        """
        effect = normalize_effect(effect)
        key = self.idempotency_key(self.session_id, self.turn_seq, tool, args)

        # 2. 命中幂等缓存 → 复用（重复投递不产生第二次副作用）
        cached = self._cache.get_record(key)
        if cached is not None:
            self.emit(EventKind.TOOL_REUSED, {
                'tool': tool,
                'idempotency_key': key,
                'effect': effect,
            })
            return ToolOutcome(status='reused', tool=tool, idempotency_key=key,
                               effect=effect, result=cached.result)

        # 3. 结果未知？→ effectful 一律停下
        pending = self._pending_intent(key)
        if pending is not None:
            unknown = self._unknown.get(key) or UnknownOutcome(
                session_id=self.session_id,
                turn_seq=self.turn_seq,
                tool=tool,
                tool_version=version,
                idempotency_key=key,
                effect=effect,
                args_digest=args_digest(args),
            )
            if effect == EFFECT_EFFECTFUL and not approved:
                self._unknown.setdefault(key, unknown)
                self.emit(EventKind.TOOL_EFFECT_UNKNOWN, {
                    'tool': tool,
                    'idempotency_key': key,
                    'effect': effect,
                })
                logger.warning(
                    '拒绝自动重放 effectful 工具（结果未知）: %s key=%s', tool, key)
                return ToolOutcome(status='unknown_outcome', tool=tool,
                                   idempotency_key=key, effect=effect,
                                   unknown=unknown)

        # 4. 先写 intent（effectful 不写参数原文：用不上，还可能含敏感值）
        #    走 _write_intent 而不是 record_tool_intent：pending 判定已经在第 3 步
        #    做过了（approved=True 时这里就是「人点头后的重放」）。
        intent_payload: dict[str, Any] = {
            'tool': tool,
            'tool_version': version,
            'idempotency_key': key,
            'effect': effect,
            'args_digest': args_digest(args),
            'turn_seq': self.turn_seq,
            'created_at': time.time(),
        }
        if isinstance(args, dict) and self.store_args and effect != EFFECT_EFFECTFUL:
            intent_payload['args'] = args
        self._write_intent(intent_payload, key)

        # 5. 执行
        try:
            result = fn()
        except (KeyboardInterrupt, SystemExit):
            # 进程要退出了：留一条错误事实，然后**原样抛出**。
            # 吞掉 Ctrl-C 会让上层以为这次调用正常结束 —— 那比崩溃更糟。
            self.emit(EventKind.TOOL_ERROR, {
                'tool': tool,
                'idempotency_key': key,
                'effect': effect,
                'error': 'interrupted',
            })
            raise
        except BaseException as exc:
            self.emit(EventKind.TOOL_ERROR, {
                'tool': tool,
                'idempotency_key': key,
                'effect': effect,
                'error': f'{type(exc).__name__}: {exc}',
            })
            if effect == EFFECT_EFFECTFUL:
                # 抛异常不代表「什么都没发生」—— 外部系统可能已经改了一半。
                # 保守处理：标记结果未知，等人确认。
                self._unknown.setdefault(key, UnknownOutcome(
                    session_id=self.session_id,
                    turn_seq=self.turn_seq,
                    tool=tool,
                    tool_version=version,
                    idempotency_key=key,
                    effect=effect,
                    args_digest=args_digest(args),
                    reason='tool_error',
                ))
            return ToolOutcome(status='failed', tool=tool, idempotency_key=key,
                               effect=effect, error=exc)

        # 6. 写 result
        self.record_tool_result(key, result, effect=effect)
        self._unknown.pop(key, None)
        return ToolOutcome(status='executed', tool=tool, idempotency_key=key,
                           effect=effect, result=result)

    # ── 恢复 ────────────────────────────────────────────
    def resume(self, *, turn_seq: Optional[int] = None) -> RecoveryPlan:
        """从 journal/checkpoint 恢复，并落恢复事件。

        恢复后：
          * 结果未知的 effectful 调用被登记进 `_unknown`，
            之后 execute_tool 会拒绝自动重放它们；
          * 已完成的结果从 journal 回灌进幂等缓存（缓存丢了也能复用）；
          * turn_seq 指向要继续的轮次。
        """
        plan = recover(self._port, self.session_id)

        for key, result in plan.tool_results.items():
            if self._cache.get_record(key) is None:
                self._cache.put(key, result)

        self._unknown = {item.idempotency_key: item for item in plan.unknown_outcomes}
        self.turn_seq = plan.resume_turn_seq if turn_seq is None else turn_seq

        self.emit(EventKind.SESSION_RESUMED, {
            'session_id': self.session_id,
            'turn_seq': self.turn_seq,
            'checkpoint': plan.checkpoint.ref if plan.checkpoint else None,
            'checkpoint_corrupt': plan.checkpoint_corrupt,
            'unknown_outcomes': len(plan.unknown_outcomes),
            'replayable': len(plan.replayable),
        })
        for item in plan.unknown_outcomes:
            self.emit(EventKind.TOOL_EFFECT_UNKNOWN, {
                'tool': item.tool,
                'idempotency_key': item.idempotency_key,
                'effect': item.effect,
            })
        return plan

    def pending_effectful_calls(self) -> list[UnknownOutcome]:
        """当前待人工确认的调用列表。"""
        return list(self._unknown.values())

    # ── 会话 / 轮次 ─────────────────────────────────────
    def start_session(self, *, session_id: Optional[str] = None, tenant: str = '',
                      artifact_id: str = '', artifact_version: str = '',
                      deployment_id: str = '', workspace_id: str = '',
                      budget: Optional[dict[str, Any]] = None) -> SessionRecord:
        """登记一个会话（幂等：重复登记只更新可变字段）。"""
        if session_id:
            self.session_id = session_id
        record = SessionRecord(
            id=self.session_id,
            tenant=tenant,
            artifact_id=artifact_id,
            artifact_version=artifact_version,
            deployment_id=deployment_id,
            workspace_id=workspace_id,
            status=SessionStatus.ACTIVE.value,
            budget=dict(budget or {}),
        )
        self._port.upsert_session(record)
        return record

    def start_turn(self, seq: Optional[int] = None, *,
                   input: Optional[dict[str, Any]] = None,
                   turn_id: str = '') -> TurnRecord:
        """开一个新轮次（seq 缺省 = 上一轮 +1）。"""
        if seq is None:
            existing = self._port.list_turns(self.session_id)
            seq = (existing[-1].seq + 1) if existing else 0
        record = TurnRecord(
            id=turn_id or f'{self.session_id}:{seq}',
            session_id=self.session_id,
            seq=seq,
            status=TurnStatus.RUNNING.value,
            input=dict(input or {}),
        )
        self._port.upsert_turn(record)
        self.turn_seq = seq
        self.turn_id = record.id
        self.emit(EventKind.TURN_STARTED, {'turn_seq': seq, 'turn_id': record.id})
        return record

    def finish_turn(self, *, status: str = TurnStatus.SUCCEEDED.value,
                    stop_reason: str = '',
                    usage: Optional[dict[str, Any]] = None,
                    cost: Optional[dict[str, Any]] = None) -> None:
        """结束当前轮次。"""
        turns = self._port.list_turns(self.session_id)
        current = None
        for turn in turns:
            if turn.seq == self.turn_seq:
                current = turn
                break
        if current is None:
            current = TurnRecord(id=f'{self.session_id}:{self.turn_seq}',
                                 session_id=self.session_id, seq=self.turn_seq)
        current.status = status
        current.stop_reason = stop_reason
        if usage:
            current.usage.update(usage)
        if cost:
            current.cost.update(cost)
        current.updated_at = time.time()
        self._port.upsert_turn(current)
        self.emit(EventKind.TURN_FINISHED, {
            'turn_seq': current.seq, 'status': status, 'stop_reason': stop_reason})

    # ── 内部 ────────────────────────────────────────────
    def _pending_intent(self, idempotency_key: str) -> Optional[dict[str, Any]]:
        """这个幂等键是否「开始过但没做完」。

        查 journal 而不是只查内存：进程重启后内存是空的，
        但 journal 里那条 intent 还在 —— 那正是我们要认出来的「在途调用」。
        """
        event = self._port.find_tool_event(self.session_id, idempotency_key,
                                           EventKind.TOOL_INTENT)
        if event is None:
            return None
        if self._cache.get_record(idempotency_key) is not None:
            return None      # 已经有结果 → 不算在途
        return event.payload

#: 兼容别名 —— 托管运行时在策划案语境里就叫「Runtime」。
#:
#: 但包级 `infra.runtime.Runtime` 已经是 DI 容器（历史 API，rc0 冻结，
#: harness/__init__.py 依赖它），所以这个别名只在本模块内提供：
#:     from aicf.infra.runtime.managed import Runtime   # 托管运行时
#:     from aicf.infra.runtime import Runtime            # DI 容器
Runtime = ManagedRuntime

__all__ = ['ManagedRuntime', 'ToolOutcome', 'Runtime', 'UnknownOutcomeError']
