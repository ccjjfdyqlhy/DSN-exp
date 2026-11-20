# infra/runtime/idempotency.py
# 幂等键 + 工具结果缓存（策划案 §4.2.3）。
#
#     idempotency_key = sha256(session_id | turn_seq | tool_name | canonical_args)
#
# 【为什么公式要一模一样地写两遍】
#   规范实现在 harness/runtime_client.py（Kernel 侧），
#   这里有一份等价实现（infra 侧）。依赖规则禁止 infra → harness，
#   所以只能各写一份；两份由 tests/test_rc0_runtime.py 的**交叉测试**钉死：
#   同一组输入，两边必须产出**完全相同**的字符串。
#   谁改了公式，那个测试就红 —— 这比「约定文档里写一遍」可靠得多。
#
# 【canonical_args 为什么要稳定序列化】
#   幂等键的意义是「同样的调用 = 同样的键」。
#   如果序列化不稳定（dict 顺序不同、str(dict) 的顺序不同），
#   同一个调用会算出两个键 → 缓存永远不命中 → 副作用重复发生。
#   所以：键排序、非字符串键转字符串、不可序列化的值退化成 repr。
#
# 【副作用分级】
#   pure        纯计算，恢复时可自由重放
#   idempotent  写操作但重复无害，恢复时可自动重放
#   effectful   发消息 / 扣款 / 改外部系统 —— **默认不自动重放**，
#               恢复时标记 unknown_outcome，交给人确认

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Optional

from .state import EFFECT_PURE, ToolResultRecord, normalize_effect
from .store import StorePort

logger = logging.getLogger('aicf.infra.runtime.idempotency')


def canonical_args(args: Any) -> str:
    """把工具参数规范化成稳定字符串。

    **与 harness/runtime_client.py 的实现逐字等价**（交叉测试保证）。

    规则：
      * None → '{}'（没有参数就是没有参数）
      * 非 dict → {'_': args}（仍然要能算出稳定的键）
      * dict → json.dumps(sort_keys=True, ensure_ascii=False, default=repr,
        separators=(',', ':'))
      * 排序失败（混合类型的键）→ 退化成 repr(sorted(items))，**绝不抛异常**
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
    """算这次工具调用的幂等键。

    sha256(session_id | turn_seq | tool_name | canonical_args)

    用 '|' 连接各段是策划案给定的公式。注意它的**已知代价**：
    如果 session_id 本身含 '|',不同切分可能撞成同一个键。
    所以 session_id 由运行时生成（不含 '|'），不要用用户输入当 session_id。
    """
    payload = '|'.join([
        str(session_id),
        str(turn_seq),
        str(tool),
        canonical_args(args),
    ])
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def args_digest(args: Any) -> str:
    """参数摘要（写进 intent 事件）。

    只存摘要、不存原文 —— 摘要足够回答「这两次调用是不是同一组参数」，
    又不会把密码/令牌写进 journal。长度取前 16 位十六进制：够用且不刺眼。
    """
    return hashlib.sha256(canonical_args(args).encode('utf-8')).hexdigest()[:16]


class ResultCache:
    """tool_result_cache 表的读写。

    它回答两个问题：
      1. 「这个幂等键之前跑过吗？结果是什么？」—— 命中就**不要**再执行；
      2. 「这个幂等键的结果是什么版本、什么副作用等级？」—— 审计用。
    """

    def __init__(self, port: StorePort):
        self._port = port

    def get(self, idempotency_key: str) -> Optional[ToolResultRecord]:
        """取缓存记录；没有则返回 None。

        注意 None 有两种含义：没缓存过 / 缓存里的结果就是 None。
        要区分请用 `get_record()`（返回记录本身）或 `contains()`。
        """
        return self._port.get_tool_result(idempotency_key)

    def get_record(self, idempotency_key: str) -> Optional[ToolResultRecord]:
        """同 get()，名字更强调「返回的是记录」。"""
        return self._port.get_tool_result(idempotency_key)

    def get_result(self, idempotency_key: str) -> Any:
        """取缓存里的**结果值**（对应 RuntimeClient.lookup_tool_result）。

        没命中返回 None —— 与 RuntimeClient 协议的语义一致。
        """
        record = self._port.get_tool_result(idempotency_key)
        if record is None:
            return None
        return record.result

    def contains(self, idempotency_key: str) -> bool:
        """这个幂等键是否已经有结果（不管结果值是不是 None）。"""
        return self._port.get_tool_result(idempotency_key) is not None

    def put(self, idempotency_key: str, result: Any, *, tool: str = '',
            version: str = '', effect: str = EFFECT_PURE) -> ToolResultRecord:
        """写入结果缓存。"""
        record = ToolResultRecord(
            idempotency_key=idempotency_key,
            tool=tool,
            version=version,
            result=result,
            effect=normalize_effect(effect),
            created_at=time.time(),
        )
        self._port.put_tool_result(record)
        return record


__all__ = ['canonical_args', 'idempotency_key', 'args_digest', 'ResultCache']
