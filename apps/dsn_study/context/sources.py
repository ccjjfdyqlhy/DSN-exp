# apps/dsn_study/context/sources.py
# 上下文来源（协议 + 四个实现）。
#
# 契约（REBUILD_SPEC §2.4）：
#   - 每个来源**独立失败**：某个 store 挂了只丢自己那部分，记进 trace.degraded，
#     不影响其它来源（现状是整个 _build_preamble 一起挂）；
#   - StudyStateSource 的三个子块（今日计划 / 到期复习 / 错题本）**各自** try/except；
#   - 依赖**由构造参数注入**（plan_engine / graph_store / question_store / store），
#     本模块不 import 任何 store 实现 —— 免得测试里拉起真库。
#
# 依赖方向：只依赖 types（types ← budget ← kernel ← {sources, store}），不反向 import。

from __future__ import annotations

import logging
from typing import Optional, Protocol, runtime_checkable

from .types import (
    ASSISTANT_PREFIX,
    KIND_FACTS,
    KIND_STATE,
    KIND_SUMMARY,
    KIND_TAIL,
    USER_PREFIX,
    ContextBlock,
    TurnContext,
)

logger = logging.getLogger(__name__)


@runtime_checkable
class ContextSource(Protocol):
    """上下文来源协议。

    实现类需要提供 name 属性与 collect() 方法；
    collect 抛异常时由 kernel 兜住并记进 trace.degraded。
    """

    name: str

    def collect(self, turn: TurnContext) -> list[ContextBlock]:
        """按本轮上下文采集内容块。"""
        ...


class StudyStateSource:
    """学习状态：今日计划 / 到期复习 / 错题本。

    三个子块**各自** try/except：任一 store 异常只丢那一块，其余照常。
    （旧实现 boot.py::_build_preamble 是三段各自 try，但整段 preamble 拼装
      仍可能整体失败；这里把每一块都独立成 ContextBlock，粒度更细。）
    """

    name = "state"

    def __init__(self, plan_engine=None, graph_store=None, question_store=None):
        # 依赖注入：调用方决定给什么，本模块不去 import 任何实现
        self._plan_engine = plan_engine
        self._graph_store = graph_store
        self._question_store = question_store

    def collect(self, turn: TurnContext) -> list[ContextBlock]:
        blocks: list[ContextBlock] = []
        blocks.extend(self._plan_block(turn))
        blocks.extend(self._review_block(turn))
        blocks.extend(self._errorbook_block(turn))
        return blocks

    # ── 子块 1：今日计划 ────────────────────────────────────────────

    def _plan_block(self, turn: TurnContext) -> list[ContextBlock]:
        if self._plan_engine is None:
            return []
        try:
            summary = self._plan_engine.daily_summary(turn.uid)
        except Exception as exc:  # noqa: BLE001 - 单块降级，不影响其它块
            logger.warning("今日计划采集失败（已跳过）：%s", exc)
            return []
        if not isinstance(summary, dict):
            return []
        total = int(summary.get("total") or 0)
        if not total:
            return []
        done = int(summary.get("done") or 0)
        pending = int(summary.get("pending") or 0)
        skipped = int(summary.get("skipped") or 0)
        tasks = []
        for task in (summary.get("tasks") or [])[:8]:
            title = (task.get("title") or "").strip()
            if not title:
                continue
            status = (task.get("status") or "").strip()
            tasks.append("%s(%s)" % (title, status) if status else title)
        text = "今日计划 %d/%d 已完成，%d 待办、%d 已跳过" % (done, total, pending, skipped)
        if tasks:
            text += "；" + "、".join(tasks)
        return [_block(KIND_STATE, "plan", text, priority=80)]

    # ── 子块 2：到期复习 ────────────────────────────────────────────

    def _review_block(self, turn: TurnContext) -> list[ContextBlock]:
        if self._graph_store is None:
            return []
        try:
            due = self._graph_store.get_due_reviews(turn.uid)
        except Exception as exc:  # noqa: BLE001 - 单块降级
            logger.warning("到期复习采集失败（已跳过）：%s", exc)
            return []
        if not due:
            return []
        names = []
        for item in list(due)[:6]:
            name = (item.get("kp_name") or item.get("kp_code") or "").strip()
            if name:
                names.append(name)
        text = "%d 个知识点待复习" % len(due)
        if names:
            text += "：" + "、".join(names)
        return [_block(KIND_STATE, "review", text, priority=80)]

    # ── 子块 3：错题本 ──────────────────────────────────────────────

    def _errorbook_block(self, turn: TurnContext) -> list[ContextBlock]:
        if self._question_store is None:
            return []
        try:
            total_errors = self._question_store.get_total_errors(turn.uid)
        except Exception as exc:  # noqa: BLE001 - 单块降级
            logger.warning("错题本采集失败（已跳过）：%s", exc)
            return []
        total_errors = int(total_errors or 0)
        if not total_errors:
            return []
        return [_block(KIND_STATE, "errorbook",
                       "累计 %d 道错题待巩固" % total_errors, priority=80)]


class MemoSource:
    """长期备忘（用户级事实）：context_facts(scope='user', kind='memo')。"""

    name = "memo"

    def __init__(self, store, limit: int = 10):
        self._store = store
        self._limit = max(1, int(limit))

    def collect(self, turn: TurnContext) -> list[ContextBlock]:
        facts = self._store.facts(turn.uid, scope="user", kind="memo",
                                  limit=self._limit)
        blocks = []
        for fact in facts or []:
            text = (fact.get("text") or "").strip()
            if not text:
                continue
            blocks.append(_block(KIND_FACTS, "memo", text, priority=60, meta={
                "importance": fact.get("importance"),
                "ref_id": fact.get("ref_id") or "",
            }))
        return blocks


class SummarySource:
    """会话摘要：context_facts(scope='session', kind='summary')。"""

    name = "summary"

    def __init__(self, store, limit: int = 5):
        self._store = store
        self._limit = max(1, int(limit))

    def collect(self, turn: TurnContext) -> list[ContextBlock]:
        facts = self._store.facts(turn.uid, scope="session", kind="summary",
                                  limit=self._limit)
        blocks = []
        for fact in facts or []:
            text = (fact.get("text") or "").strip()
            if not text:
                continue
            blocks.append(_block(KIND_SUMMARY, "compactor", text, priority=50, meta={
                "importance": fact.get("importance"),
                "ref_id": fact.get("ref_id") or "",
            }))
        return blocks


class TailSource:
    """最近 N 轮原文（保底段）。

    文本形态固定为 "用户：…\\n助手：…"，裁剪时**保留尾部**，
    保证最后一条 user 消息不被整条丢掉（红线 R9）。
    """

    name = "tail"

    def __init__(self, store, rounds: int = 3):
        self._store = store
        self._rounds = max(1, int(rounds))

    def collect(self, turn: TurnContext) -> list[ContextBlock]:
        rows = self._store.recent_turns(turn.uid, turn.session_id,
                                        limit=self._rounds)
        lines = []
        for row in rows or []:
            user_msg = (row.get("user_msg") or "").strip()
            reply = (row.get("assistant_reply") or "").strip()
            if user_msg:
                lines.append(USER_PREFIX + user_msg)
            if reply:
                lines.append(ASSISTANT_PREFIX + reply)
        if not lines:
            return []
        return [_block(KIND_TAIL, "session", "\n".join(lines), priority=100,
                       meta={"rounds": len(rows)})]


# ── 工具 ────────────────────────────────────────────────────────────────


def _block(kind: str, source: str, text: str, *, priority: int = 0,
           meta: Optional[dict] = None) -> ContextBlock:
    """造一个块（顺手去掉首尾空白）。"""
    return ContextBlock(
        kind=kind,
        source=source,
        text=(text or "").strip(),
        priority=priority,
        pinned=False,
        meta=dict(meta or {}),
    )
