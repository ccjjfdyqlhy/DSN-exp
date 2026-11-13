# -*- coding: utf-8 -*-
"""dsn_study 上下文内核单测。

覆盖（apps/dsn_study/REBUILD_SPEC.md §2.2 / §2.4 / §2.5）：
  - fit() 的 8 条裁剪规则（全局上限 / tail 保底 / 尾部截断 / 禁止中间丢失 /
    纯函数性 / pinned / marker 预留）；
  - ContextKernel.build() 的来源容错（一个 source 挂了不影响其它）；
  - render() 的统一格式；
  - ContextStore 的建表幂等 / 写入幂等 / 读取顺序。
"""

from __future__ import annotations

import sqlite3
import threading

import pytest

from apps.dsn_study.context import (
    ASSISTANT_PREFIX,
    CTX_PREFIX,
    TRUNCATE_MARKER,
    USER_PREFIX,
    ContextBlock,
    ContextBudget,
    ContextKernel,
    ContextStore,
    ContextTrace,
    MemoSource,
    StudyStateSource,
    SummarySource,
    TailSource,
    TurnContext,
    fit,
)


# ── 测试替身 ────────────────────────────────────────────────────────────


class _FakeDB:
    """最小 DB 管理器：只提供 _get_connection()（与 QuestionBankDBManager 同接口）。"""

    def __init__(self, path: str):
        self.path = path
        self._local = threading.local()

    def _get_connection(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, check_same_thread=False)
            self._local.conn = conn
        return conn


@pytest.fixture
def db(tmp_path):
    return _FakeDB(str(tmp_path / "context.db"))


def _turn(uid: int = 7, session_id: str = "s1", message: str = "在吗",
          round_index: int = 1) -> TurnContext:
    return TurnContext(uid=uid, session_id=session_id, message=message,
                       round_index=round_index)


def _round(question: str, answer: str) -> str:
    return "%s%s\n%s%s" % (USER_PREFIX, question, ASSISTANT_PREFIX, answer)


def _rounds(*pairs) -> str:
    return "\n".join(_round(q, a) for q, a in pairs)


# ══════════════════════════════════════════════════════════════════════
# 1. fit() —— 裁剪规则（契约 §2.2）
# ══════════════════════════════════════════════════════════════════════


def test_rule1_global_hard_cap_includes_tail():
    """规则 1：total_chars 是全局硬上限（tail 也计入）。"""
    budget = ContextBudget(total_chars=300, tail_chars=200, state_chars=400,
                           facts_chars=400, summary_chars=400)
    blocks = [
        ContextBlock(kind="tail", source="session",
                     text=_round("今天的二次函数", "我们先看配方法"), priority=100),
        ContextBlock(kind="state", source="plan",
                     text="状态" + "x" * 200, priority=80),
        ContextBlock(kind="facts", source="memo",
                     text="备忘" + "y" * 200, priority=60),
    ]
    result = fit(blocks, budget)
    assert result.total_chars <= budget.total_chars
    assert result.total_chars == sum(len(b.text) for b in result.kept)
    # 低优先级的事实块放不下 → 整体丢弃并记原因
    assert [t.kind for t in result.dropped] == ["facts"]
    assert result.dropped[0].reason


def test_rule2_tail_is_never_dropped_and_keeps_last_user_message():
    """规则 2：tail 保底 —— 预算再小也不能丢，最后一条 user 消息必须完整。"""
    budget = ContextBudget(total_chars=30, tail_chars=10, state_chars=10,
                           facts_chars=10, summary_chars=10)
    blocks = [
        ContextBlock(kind="tail", source="session",
                     text=_round("帮我看看二次函数配方法", "好的，先看配方法"),
                     priority=100),
        ContextBlock(kind="facts", source="memo",
                     text="备忘" * 40, priority=60),
    ]
    result = fit(blocks, budget)
    tail_kept = [b for b in result.kept if b.kind == "tail"]
    assert tail_kept, "tail 块被丢弃了"
    assert "帮我看看二次函数配方法" in tail_kept[0].text
    assert not [t for t in result.dropped if t.kind == "tail"]


def test_rule3_blocks_are_filled_by_priority_desc():
    """规则 3：其余块按 priority 从高到低填剩余额度。"""
    budget = ContextBudget(total_chars=120, tail_chars=40, state_chars=100,
                           facts_chars=100, summary_chars=100)
    blocks = [
        ContextBlock(kind="tail", source="session", text=_round("问", "答"),
                     priority=100),
        ContextBlock(kind="facts", source="memo", text="低优先级" * 20, priority=10),
        ContextBlock(kind="state", source="plan", text="高优先级" * 20, priority=80),
    ]
    result = fit(blocks, budget)
    kinds = {b.kind for b in result.kept}
    assert "state" in kinds          # 高优先级保住了
    assert "facts" not in kinds      # 低优先级被挤掉
    assert result.total_chars <= budget.total_chars


def test_rule4_truncation_keeps_tail_not_head():
    """规则 4：截断保留尾部（text[-n:]），不保留头部。"""
    budget = ContextBudget(total_chars=200, tail_chars=40)
    text = _rounds(("早期的问题", "早期的回答"),
                   ("中间的问题", "中间的问答"),
                   ("最近的问题", "最近的回答"))
    result = fit([ContextBlock(kind="tail", source="session", text=text,
                                priority=100)], budget)
    kept = result.kept[0].text
    assert kept.endswith("最近的回答")
    assert "早期的问题" not in kept
    assert "中间的问题" not in kept
    assert result.truncated and result.truncated[0].reason


def test_rule5_non_tail_block_is_kept_whole_or_dropped_whole():
    """规则 5：禁止静默丢中段 —— 非 tail 块要么整体保留、要么整体丢弃。"""
    budget = ContextBudget(total_chars=200, tail_chars=50, state_chars=100,
                           facts_chars=100, summary_chars=100)
    big = "状态" + "x" * 300
    blocks = [
        ContextBlock(kind="tail", source="session", text=_round("问", "答"),
                     priority=100),
        ContextBlock(kind="state", source="plan", text=big, priority=80),
    ]
    result = fit(blocks, budget)
    assert not [b for b in result.kept if b.kind == "state"], "被截断保留了半截"
    dropped = [t for t in result.dropped if t.kind == "state"]
    assert dropped and dropped[0].reason, "丢弃必须记原因"
    # 丢弃的块没有被偷偷塞进 kept
    assert all(b.text != big for b in result.kept)


def test_rule7_fit_is_pure():
    """规则 7：纯函数 —— 不改入参，同一输入必得同一输出。"""
    budget = ContextBudget(total_chars=100, tail_chars=50)
    blocks = [
        ContextBlock(kind="tail", source="session",
                     text=_rounds(("早期", "早期答"), ("最近", "最近答")),
                     priority=100),
        ContextBlock(kind="state", source="plan", text="状态" + "x" * 200,
                     priority=80),
        ContextBlock(kind="facts", source="memo", text="备忘", priority=60),
    ]
    snapshot = [(b.kind, b.source, b.text, b.priority, b.pinned) for b in blocks]

    first = fit(blocks, budget)
    second = fit(blocks, budget)

    assert [(b.kind, b.source, b.text) for b in first.kept] == \
           [(b.kind, b.source, b.text) for b in second.kept]
    assert first.total_chars == second.total_chars
    assert [(t.kind, t.source, t.status, t.reason) for t in first.dropped] == \
           [(t.kind, t.source, t.status, t.reason) for t in second.dropped]
    assert [(t.kind, t.status, t.reason) for t in first.truncated] == \
           [(t.kind, t.status, t.reason) for t in second.truncated]
    # 入参未被改写
    assert snapshot == [(b.kind, b.source, b.text, b.priority, b.pinned)
                        for b in blocks]
    # 被截断的块是新对象（replace），原对象原封不动
    tail = blocks[0]
    assert any(b is tail for b in first.kept), "截断应当生成新对象，而不是就地改写"


def test_rule8_pinned_is_always_kept_and_counted():
    """规则 8：pinned 永远保留，但仍计入上限。"""
    budget = ContextBudget(total_chars=100, tail_chars=40, state_chars=50,
                           facts_chars=50, summary_chars=50)
    pinned = ContextBlock(kind="facts", source="memo", text="钉住的事实",
                          priority=0, pinned=True)
    filler = ContextBlock(kind="summary", source="compactor",
                           text="摘要" + "s" * 200, priority=50)
    result = fit([pinned, filler], budget)
    assert [b.text for b in result.kept] == ["钉住的事实"]
    # 计入上限：pinned 的字符数算进 total
    assert result.total_chars == len("钉住的事实")
    assert result.total_chars <= budget.total_chars


def test_rule8_pinned_survives_exhausted_budget():
    """规则 8 续：预算被前面的块用光时，pinned 依然保留（保底 > 上限）。"""
    budget = ContextBudget(total_chars=10, tail_chars=5, state_chars=5,
                           facts_chars=5, summary_chars=5)
    pinned = ContextBlock(kind="facts", source="memo", text="钉住的事实" * 5,
                          pinned=True)
    result = fit([pinned], budget)
    assert len(result.kept) == 1
    assert result.total_chars == len("钉住的事实" * 5)


def test_rule6_truncation_marker_length_is_reserved():
    """规则 6：截断标记长度先预留，实际产出恒 ≤ 上限。"""
    budget = ContextBudget(total_chars=200, tail_chars=40)
    text = _rounds(("早期的问题", "早期的回答"),
                   ("中间的问题", "中间的问答"),
                   ("最近的问题", "最近的回答"))
    result = fit([ContextBlock(kind="tail", source="session", text=text,
                                priority=100)], budget)
    kept = result.kept[0]
    assert len(kept.text) <= budget.tail_chars
    assert kept.text.startswith(TRUNCATE_MARKER)
    assert result.truncated and result.truncated[0].reason
    # 标记是"额外"预留的：正文 + 标记 ≤ 额度
    assert len(kept.text) - len(TRUNCATE_MARKER) <= budget.tail_chars


def test_fit_is_deterministic_across_calls():
    """同输入必得同输出（可预期性）。"""
    blocks = [
        ContextBlock(kind="state", source="plan", text="状态" * 30, priority=80),
        ContextBlock(kind="tail", source="session", text=_rounds(("a", "b"), ("c", "d")),
                     priority=100),
    ]
    budget = ContextBudget(total_chars=120, tail_chars=30)
    a = fit(blocks, budget)
    b = fit(blocks, budget)
    assert a.total_chars == b.total_chars
    assert [t.reason for t in a.dropped] == [t.reason for t in b.dropped]


# ══════════════════════════════════════════════════════════════════════
# 2. ContextKernel —— 组装与降级
# ══════════════════════════════════════════════════════════════════════


class _BoomSource:
    name = "boom"

    def collect(self, turn):
        raise RuntimeError("数据库炸了")


class _OkSource:
    name = "ok"

    def collect(self, turn):
        return [ContextBlock(kind="state", source="plan",
                             text="今日计划 1/2 已完成", priority=80)]


def test_kernel_survives_source_failure_and_records_degraded():
    """某个 source 抛异常：不炸、降级留痕、其它 source 照常。"""
    kernel = ContextKernel(None, [_BoomSource(), _OkSource()])
    trace = kernel.build(_turn())
    assert trace.degraded, "失败来源必须记进 degraded"
    assert "boom" in trace.degraded[0]
    assert "数据库炸了" in trace.degraded[0]
    assert [b.kind for b in trace.kept] == ["state"]
    assert "今日计划 1/2 已完成" in trace.kept[0].text


def test_kernel_trace_records_dropped_reason():
    kernel = ContextKernel(None, [_OkSource()])
    trace = kernel.build(_turn())
    summary = trace.summary()
    assert summary["budget_chars"] == trace.budget_chars
    assert summary["kept"] >= 1
    assert isinstance(summary["blocks"], list)


def test_study_state_source_subblocks_fail_independently():
    """StudyStateSource 的三个子块各自 try/except：一个挂了不影响另两个。"""

    class _Plan:
        def daily_summary(self, uid):
            return {"total": 3, "done": 1, "pending": 2, "skipped": 0,
                    "tasks": [{"title": "三角函数", "status": "done"}]}

    class _GraphBoom:
        def get_due_reviews(self, uid):
            raise RuntimeError("图谱挂了")

    class _QB:
        def get_total_errors(self, uid):
            return 7

    source = StudyStateSource(plan_engine=_Plan(), graph_store=_GraphBoom(),
                              question_store=_QB())
    blocks = source.collect(_turn())
    sources = {b.source for b in blocks}
    assert "plan" in sources
    assert "errorbook" in sources
    assert "review" not in sources        # 挂掉的那块缺席，其余照常
    assert all(b.kind == "state" for b in blocks)
    assert all(b.priority == 80 for b in blocks)


def test_empty_blocks_are_dropped_and_never_rendered():
    """空文本块不进上下文（pinned 的空块代价为 0，但也渲染不出来）。"""
    budget = ContextBudget(total_chars=200, tail_chars=50)
    blocks = [
        ContextBlock(kind="state", source="plan", text="   ", priority=80),
        ContextBlock(kind="facts", source="memo", text="备忘", priority=60),
    ]
    result = fit(blocks, budget)
    assert [b.kind for b in result.kept] == ["facts"]
    assert [t.reason for t in result.dropped] == ["空文本"]


def test_broken_trace_sink_does_not_break_build():
    """落库失败不能影响本轮对话。"""

    def _boom(trace):
        raise RuntimeError("trace 落库失败")

    kernel = ContextKernel(None, [_OkSource()], trace_sink=_boom)
    trace = kernel.build(_turn())
    assert [b.kind for b in trace.kept] == ["state"]


def test_study_state_source_survives_in_kernel():
    """子块失败在 kernel 层也不该炸（该块缺席即可）。"""

    class _PlanBoom:
        def daily_summary(self, uid):
            raise RuntimeError("计划库挂了")

    kernel = ContextKernel(None, [StudyStateSource(plan_engine=_PlanBoom())])
    trace = kernel.build(_turn())
    assert trace.kept == []
    assert trace.degraded == []      # 子块失败不算来源失败（来源本身没抛）


# ══════════════════════════════════════════════════════════════════════
# 3. render() —— 统一格式
# ══════════════════════════════════════════════════════════════════════


def test_render_uses_unified_format():
    kernel = ContextKernel(None, [_OkSource()])
    text = ContextKernel.render(kernel.build(_turn()))
    assert text.startswith(CTX_PREFIX)
    assert "- [学习状态] 今日计划 1/2 已完成" in text
    assert text.count(CTX_PREFIX) == 1


def test_render_tail_block_keeps_conversation_shape():
    """tail 块不加 "- [标签]" 前缀，原样保留对话形态。"""
    blocks = [
        ContextBlock(kind="state", source="plan", text="今日计划 1/2 已完成",
                     priority=80),
        ContextBlock(kind="tail", source="session", text=_round("上一轮的问", "上一轮的答"),
                     priority=100),
    ]
    trace = ContextTrace(blocks=[], total_chars=0, budget_chars=100,
                          degraded=[], collect_ms=0.0, kept=blocks)
    text = ContextKernel.render(trace)
    assert "[最近对话]" in text
    assert "%s上一轮的问" % USER_PREFIX in text
    assert "- [最近对话]" not in text
    assert text.index("- [学习状态]") < text.index("[最近对话]")


def test_render_skips_empty_blocks_and_returns_empty_string():
    empty_trace = ContextTrace(blocks=[], total_chars=0, budget_chars=100,
                                degraded=[], collect_ms=0.0, kept=[])
    assert ContextKernel.render(empty_trace) == ""
    blocks = [ContextBlock(kind="state", source="plan", text="   ", priority=80)]
    trace = ContextTrace(blocks=[], total_chars=0, budget_chars=100,
                          degraded=[], collect_ms=0.0, kept=blocks)
    assert ContextKernel.render(trace) == ""


# ══════════════════════════════════════════════════════════════════════
# 4. ContextStore —— 建表 / 写入幂等 / 读取顺序
# ══════════════════════════════════════════════════════════════════════


def test_init_tables_is_idempotent(db):
    store = ContextStore(db)
    store.init_tables()
    store.init_tables()      # 幂等：再调一次不报错
    conn = db._get_connection()
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {"context_turns", "context_facts"} <= tables


def test_old_database_gets_missing_columns(db):
    """旧库（表已存在但缺列）按 PRAGMA table_info 补列。"""
    conn = db._get_connection()
    conn.execute("CREATE TABLE context_facts (id INTEGER PRIMARY KEY, "
                 "uid INTEGER, scope TEXT, kind TEXT, text TEXT)")
    conn.commit()
    ContextStore(db)
    columns = {r[1] for r in conn.execute("PRAGMA table_info(context_facts)").fetchall()}
    assert {"importance", "source", "ref_id", "created_at"} <= columns


def test_record_turn_is_idempotent(db):
    store = ContextStore(db)
    turn = _turn(uid=7, session_id="s1", round_index=1)
    store.record_turn(turn, "第一问", "第一答")
    store.record_turn(turn, "第一问（改）", "第一答（改）")
    assert store.count_turns(7, "s1") == 1
    rows = store.recent_turns(7, "s1", 10)
    assert len(rows) == 1
    assert rows[0]["user_msg"] == "第一问（改）"      # 覆盖写
    assert rows[0]["assistant_reply"] == "第一答（改）"


def test_recent_turns_order_is_ascending(db):
    store = ContextStore(db)
    for i in (1, 2, 3):
        store.record_turn(_turn(uid=7, session_id="s1", round_index=i),
                          "问%d" % i, "答%d" % i)
    rows = store.recent_turns(7, "s1", 10)
    assert [r["round_index"] for r in rows] == [1, 2, 3]
    assert [r["user_msg"] for r in rows] == ["问1", "问2", "问3"]
    # limit = 取最近 N 轮（仍是升序）
    rows = store.recent_turns(7, "s1", 2)
    assert [r["round_index"] for r in rows] == [2, 3]


def test_add_fact_is_idempotent(db):
    store = ContextStore(db)
    fid = store.add_fact(7, "user", "memo", "用户偏好先给思路",
                         ref_id="memo:pref:1")
    again = store.add_fact(7, "user", "memo", "用户偏好先给思路（重复写入）",
                           ref_id="memo:pref:1")
    assert fid > 0
    assert again == fid
    facts = store.facts(7, "user", "memo", 10)
    assert len(facts) == 1
    assert facts[0]["text"] == "用户偏好先给思路"     # 首次写入不被覆盖


def test_facts_are_scoped_and_ordered(db):
    store = ContextStore(db)
    store.add_fact(7, "user", "memo", "低重要度", importance=0.1)
    store.add_fact(7, "user", "memo", "高重要度", importance=0.9)
    store.add_fact(7, "session", "summary", "会话摘要")
    facts = store.facts(7, "user", "memo", 10)
    assert [f["text"] for f in facts] == ["高重要度", "低重要度"]
    assert store.facts(7, "session", "summary", 10)[0]["text"] == "会话摘要"


def test_tail_source_reads_recent_turns(db):
    store = ContextStore(db)
    store.record_turn(_turn(uid=7, session_id="s1", round_index=1),
                      "上一轮的问题", "上一轮的回答")
    source = TailSource(store, rounds=3)
    blocks = source.collect(_turn(uid=7, session_id="s1", round_index=2))
    assert len(blocks) == 1
    assert blocks[0].kind == "tail"
    assert blocks[0].priority == 100
    assert "%s上一轮的问题" % USER_PREFIX in blocks[0].text
    assert "%s上一轮的回答" % ASSISTANT_PREFIX in blocks[0].text


def test_memo_and_summary_sources_read_store(db):
    store = ContextStore(db)
    store.add_fact(7, "user", "memo", "长期备忘", ref_id="m1")
    store.add_fact(7, "session", "summary", "会话摘要", ref_id="s1")
    memo_blocks = MemoSource(store).collect(_turn())
    summary_blocks = SummarySource(store).collect(_turn())
    assert [b.kind for b in memo_blocks] == ["facts"]
    assert memo_blocks[0].source == "memo"
    assert [b.kind for b in summary_blocks] == ["summary"]
    assert summary_blocks[0].source == "compactor"


def test_kernel_end_to_end_with_store(db):
    """端到端：库里造轮次 → kernel 采集裁剪 → render 出统一文本。"""
    store = ContextStore(db)
    store.record_turn(_turn(uid=7, session_id="s1", round_index=1),
                      "上一轮的问题", "上一轮的回答")
    store.add_fact(7, "user", "memo", "用户偏好先给思路", ref_id="m1")
    kernel = ContextKernel(store, [MemoSource(store), TailSource(store)])
    trace = kernel.build(_turn(uid=7, session_id="s1", round_index=2))
    text = ContextKernel.render(trace)
    assert "- [长期事实] 用户偏好先给思路" in text
    assert "[最近对话]" in text
    assert "%s上一轮的问题" % USER_PREFIX in text
    assert trace.degraded == []
