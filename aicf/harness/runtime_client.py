# harness/runtime_client.py
# Kernel → Runtime 的**唯一出口**（策划案 §5.3）。
#
# 依赖规则 3：infra/runtime → harness 是反向调用，只能通过这里暴露的端口
# 进行，禁止 infra 直接 import aicf.harness.agent.loop。所以 Kernel 永远不知道
# 自己的状态存在 sqlite 还是 postgres 里 —— 它只知道「我有一张会话、
# 一个轮次号、一次工具调用」。
#
# 这个协议承载三件事：
#   1. 事件出口（journal 追加）
#   2. 工具调用的意图 / 结果记录（幂等与 unknown_outcome 的依据）
#   3. 检查点（加速恢复）
#
# 没有 RuntimeClient 时（纯 SDK 用法），Kernel 用 NullRuntimeClient ——
# 什么都不做，而不是报错。

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


def canonical_args(args: Any) -> str:
    """把工具参数规范化成稳定字符串。

    幂等键要靠它才能稳定：同样的参数必须序列化成同样的字节序列。
    所以键要排序、非字符串键转成字符串、不可序列化的值退化成 repr。
    """
    if args is None:
        return '{}'
    if not isinstance(args, dict):
        args = {'_': args}
    try:
        return json.dumps(args, sort_keys=True, ensure_ascii=False,
                          default=repr, separators=(',', ':'))
    except (TypeError, ValueError):
        return repr(sorted(args.items(), key=lambda kv: str(kv[0])))


def idempotency_key(session_id: str, turn_seq: int, tool: str,
                     args: Any = None) -> str:
    """幂等键的**规范实现**（策划案 §4.2.3）。

    sha256(session_id | turn_seq | tool_name | canonical_args)

    注意：infra/runtime 侧有一份等价实现（infra 不能 import aicf.harness —— 
    依赖规则禁止 infra→harness）。两份实现由 tests/ 里的交叉测试钉在一起，
    任何一边改了公式都会让那个测试变红。
    """
    payload = '|'.join([
        str(session_id),
        str(turn_seq),
        str(tool),
        canonical_args(args),
    ])
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


class UnknownOutcomeError(RuntimeError):
    """试图重放一次**结果未知**的 effectful 调用。

    场景：进程在 effectful 工具执行中途崩了。journal 里只有 intent、
    没有 result —— 外部系统可能没动，也可能动了一半。
    此时**绝不能自动重放**（可能重复扣款 / 重复发消息）。

    跨层识别：infra 不能 import aicf.harness（依赖规则禁止 infra→harness），
    所以 infra 侧有一份等价实现，靠 ``unknown_outcome`` 这个标记属性
    让调用方能认出它。两份实现由 tests/ 的交叉测试钉住。
    """

    #: 跨层识别标记 —— 调用方用它判断「这是结果未知」而不是普通失败
    unknown_outcome = True

    def __init__(self, message: str = '', *, tool: str = '',
                 idempotency_key: str = '', effect: str = 'effectful'):
        super().__init__(message or
                         f'拒绝重放结果未知的副作用调用: {tool} '
                         f'(key={idempotency_key[:12]}…, effect={effect})')
        self.tool = tool
        self.idempotency_key = idempotency_key
        self.effect = effect


@dataclass(frozen=True)
class ToolIntent:
    """一次工具调用的意图记录。

    在**执行前**写入。恢复时如果只看到 intent 没有对应的 result，
    说明这次调用的结果未知（进程在中途死了）—— 对 effectful 工具必须
    标 unknown_outcome 并交给人，绝不自动重放。
    """

    session_id: str
    turn_seq: int
    tool: str
    tool_version: str
    idempotency_key: str
    effect: str = 'effectful'
    args_digest: str = ''
    created_at: float = 0.0


@runtime_checkable
class RuntimeClient(Protocol):
    """托管运行时的客户端端口。

    实现：infra/runtime/ 里的 Runtime。Kernel 只依赖这个协议。
    """

    def emit(self, kind: str, payload: dict[str, Any]) -> None:
        """追加一条事件到 journal。"""

    def record_tool_intent(self, intent: ToolIntent) -> None:
        """在执行工具前记录意图。"""

    def record_tool_result(self, idempotency_key: str, result: Any,
                          *, effect: str = 'pure') -> None:
        """在工具执行后记录结果。"""

    def lookup_tool_result(self, idempotency_key: str) -> Any | None:
        """按幂等键查上次的结果；命中表示这次调用可以跳过。"""

    def idempotency_key(self, session_id: str, turn_seq: int, tool: str,
                        args: Any = None) -> str:
        """算这次调用的幂等键。

        由 Runtime 拥有这个公式，Kernel/Guard 只管调用 —— 这样
        「同一份实现在两处各写一遍」的风险降到最低。
        """

    def checkpoint(self, state: dict[str, Any]) -> str | None:
        """写一个检查点，返回引用；不需要检查点时返回 None。"""


class NullRuntimeClient:
    """什么都不做的 RuntimeClient。

    用于纯 SDK / 单元测试场景：没有托管运行时时，Kernel 不应该因为
    「没有 journal」而拒绝工作。
    """

    def emit(self, kind: str, payload: dict[str, Any]) -> None:
        return None

    def record_tool_intent(self, intent: ToolIntent) -> None:
        return None

    def record_tool_result(self, idempotency_key: str, result: Any,
                          *, effect: str = 'pure') -> None:
        return None

    def lookup_tool_result(self, idempotency_key: str) -> Any | None:
        return None

    def idempotency_key(self, session_id: str, turn_seq: int, tool: str,
                        args: Any = None) -> str:
        return idempotency_key(session_id, turn_seq, tool, args)

    def checkpoint(self, state: dict[str, Any]) -> str | None:
        return None


__all__ = ['RuntimeClient', 'NullRuntimeClient', 'ToolIntent',
           'UnknownOutcomeError', 'idempotency_key', 'canonical_args']
