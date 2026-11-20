# infra/control/cost.py
# 成本账本（策划案 §4.5.3 / §5.1 的 control_cost_ledger 表）。
#
# ── 为什么要有独立账本 ──
# 「这次改动变贵了还是变便宜了」是评测四闸门之一（成本闸门），
# 「这个 Agent 这个月烧了多少钱」是控制面的经营问题。
# 两者都要按 session / agent / tool / model **归因**，而 token 计量
# （infra/policy/token_meter.py）只知道「用了多少 token」，不知道「值多少钱」。
# 账本 = 计量 × 单价，单价来自 artifact 的 cost_model（一种声明多处消费）。
#
# ── 与实时预算的关系 ──
# infra/policy/budget.py 的预算是**实时拦截**（超了就拒），账本是**事后归因**
# （复盘、对比、分摊）。账本暴露 session_total() / budget.py 联动由调用方做：
# 归因要全量准确，拦截要低延迟 —— 两类读路径不该共享一张大表的高频查询。

from __future__ import annotations

import time
import uuid
from typing import Any


class CostLedger:
    """成本账本：只追加、按维度归因。

    存储走 IStore（sqlite 起步），表是 control_cost_ledger
    （策划案 §5.1 原样）。单独使用时会自建表 —— 账本不该要求
    调用方记得先跑控制面迁移。
    """

    def __init__(self, store: Any, *, migrate: bool = True) -> None:
        self._store = store
        if migrate:
            from .store import migrate_control
            migrate_control(store)

    def record(self, *, session_id: str, agent_id: str = '',
               tool: str = '', model: str = '',
               tokens: int = 0, cost: float = 0.0,
               ts: float | None = None) -> str:
        """记一条成本。cost 是**钱**（不是 token 数），由调用方按
        artifact.cost_model 折算；tokens 单独存，便于事后重算。"""
        entry_id = f'cost_{uuid.uuid4().hex[:16]}'
        conn = self._store.get_connection()
        conn.execute(
            'INSERT INTO control_cost_ledger (id, session_id, agent_id, tool,'
            ' model, tokens, cost, ts) VALUES (?,?,?,?,?,?,?,?)',
            (entry_id, session_id, agent_id, tool, model,
             int(tokens), float(cost), ts if ts is not None else time.time()))
        conn.commit()
        return entry_id

    def session_total(self, session_id: str) -> float:
        """一个 session 的总成本。"""
        conn = self._store.get_connection()
        row = conn.execute(
            'SELECT COALESCE(SUM(cost), 0) FROM control_cost_ledger'
            ' WHERE session_id = ?', (session_id,)).fetchone()
        return float(row[0] if row else 0.0)

    def by_agent(self, agent_id: str) -> dict[str, Any]:
        """按 agent 归因的合计。"""
        return self._aggregate('agent_id', agent_id)

    def by_tool(self, tool: str) -> dict[str, Any]:
        return self._aggregate('tool', tool)

    def by_model(self, model: str) -> dict[str, Any]:
        return self._aggregate('model', model)

    def breakdown(self, *, session_id: str = '', agent_id: str = '',
                  tool: str = '', model: str = '') -> list[dict[str, Any]]:
        """按 (agent_id, tool, model) 分组的明细 —— 经营报表的原料。"""
        sql = ('SELECT agent_id, tool, model, COUNT(*), SUM(tokens), SUM(cost)'
               ' FROM control_cost_ledger')
        clauses: list[str] = []
        params: list[Any] = []
        for column, value in (('session_id', session_id),
                              ('agent_id', agent_id),
                              ('tool', tool), ('model', model)):
            if value:
                clauses.append(f'{column} = ?')
                params.append(value)
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        sql += ' GROUP BY agent_id, tool, model ORDER BY SUM(cost) DESC'
        conn = self._store.get_connection()
        rows = conn.execute(sql, params).fetchall()
        return [
            {
                'agent_id': str(r[0] or ''),
                'tool': str(r[1] or ''),
                'model': str(r[2] or ''),
                'calls': int(r[3] or 0),
                'tokens': int(r[4] or 0),
                'cost': float(r[5] or 0.0),
            }
            for r in rows
        ]

    # ── 内部 ─────────────────────────────────────────────
    def _aggregate(self, column: str, value: str) -> dict[str, Any]:
        conn = self._store.get_connection()
        row = conn.execute(
            f'SELECT COUNT(*), COALESCE(SUM(tokens), 0), COALESCE(SUM(cost), 0)'
            f' FROM control_cost_ledger WHERE {column} = ?',
            (value,)).fetchone()
        return {
            'dimension': column,
            'value': value,
            'calls': int(row[0] if row else 0),
            'tokens': int(row[1] if row else 0),
            'cost': float(row[2] if row else 0.0),
        }


def price_tokens(per_1k_tokens: dict, input_tokens: int,
                 output_tokens: int) -> float:
    """按 artifact.cost_model 的单价折算成本。

    单价是「每 1k token 多少钱」；没有声明单价时返回 0 ——
    记账要全量（tokens 照记），折价允许缺声明，但不允许猜。
    """
    input_price = float(per_1k_tokens.get('input') or 0.0)
    output_price = float(per_1k_tokens.get('output') or 0.0)
    return (input_tokens / 1000.0 * input_price
            + output_tokens / 1000.0 * output_price)


__all__ = ['CostLedger', 'price_tokens']
