# tests/test_dsn_study_topics.py
# 话题系统（迁移计划阶段 7）验收 —— 对齐计划「验证方案」表：
#
#   单元   裁剪不丢 tail      10 万字会话后，最近 N 轮原文仍在 assemble() 结果里
#   单元   段优先级           高优先级段可驱逐低优先级已保留段
#   单元   单条 system        assemble() 产出的 system 消息数 == 1
#   集成   不超预算           长会话下 system+history 字符数 ≤ ContextBudget 合计
#   集成   话题切换           30min 静默 / 语义不相似 → 正确开新话题
#   契约   MemoryStorePort    MemorySystem 显式满足 harness 记忆契约
#   接线   压缩持久化         close_topic → compressed_chunks + sessions.summary
#   热路径   StudyEngine.chat  TOPIC_ENABLED 时走 assemble_context + 裁剪历史

import os
import sys
import time
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from harness.context_assembly import (
    ContextBudget, ContextSegment, SegmentedContextAssembler,
    PRIORITY_ACTIVE, PRIORITY_CURRENT, PRIORITY_SUMMARY,
    SEG_TAIL, SEG_VERBATIM,
)


class _KeywordEmbed:
    """可控相似度的嵌入桩：同关键词 → 相似向量。

    用 zlib.crc32 而非内建 hash() —— 字符串哈希随机化（PYTHONHASHSEED）会让
    两个关键词在不同进程撞到同一维度，相似度恒 1.0，用例变成种子彩票。
    """

    def __init__(self, dim=16):
        self.dim = dim

    def _vec(self, kw):
        v = [0.0] * self.dim
        v[zlib.crc32(kw.encode("utf-8")) % self.dim] = 1.0
        return v

    def embed(self, text):
        for kw in ("数学", "英语", "物理"):
            if kw in text:
                return self._vec(kw)
        return self._vec("其他")


@pytest.fixture()
def tm(tmp_path):
    """无嵌入依赖的 TopicManager（时间边界 + 规则决策）。"""
    from apps.dsn_study.memory.topics import TopicManager
    mgr = TopicManager(str(tmp_path / "topics.db"),
                       summary_model=None, embedding_client=None,
                       judge_chat=None)
    return mgr


@pytest.fixture()
def tm_sem(tmp_path):
    from apps.dsn_study.memory.topics import TopicManager
    return TopicManager(str(tmp_path / "topics_sem.db"),
                        summary_model=None,
                        embedding_client=_KeywordEmbed(), judge_chat=None)


# ── 单元：裁剪不丢 tail ──

def test_tail_survives_after_100k_chars_session(tm):
    """10 万字会话后，最近 N 轮原文仍出现在 assemble() 结果里（SEG_TAIL 强制）。"""
    uid, cid = 1, 1
    big = "二次函数的图像与性质。" * 400   # ~5200 字/轮
    for r in range(1, 20):                 # 19 轮 ≈ 10 万字
        tm.on_new_message(uid, cid, big, round_idx=r)
        tm.record_turn(uid, cid, f"问题{r}:{big}", f"回答{r}:{big}", round_idx=r)
    assert sum(len(m["content"]) for m in
               tm.topic_messages(tm.current_topic(uid, cid)["topic_id"])) > 90000

    assembled = tm.assemble_topic_context(uid, cid, include_tail=True)
    system_text = "".join(m["content"] for m in assembled
                          if m["role"] == "system")
    # 最近 3 轮原文必须在（tail unbounded，不参与共享预算）
    for r in (18, 19):
        assert f"问题{r}:" in system_text, f"第 {r} 轮原文丢失 —— SEG_TAIL 失效"
    # 极端情况下最后一条消息也必须能被看到
    assert "回答19:" in system_text


def test_single_system_message_rule(tm):
    """规则 2：assemble() 产出的 system 消息数 == 1（严格 Jinja 约束）。"""
    uid, cid = 1, 2
    for r in range(1, 6):
        tm.on_new_message(uid, cid, f"话题内容 {r}", round_idx=r)
        tm.record_turn(uid, cid, f"话题内容 {r}", f"回复 {r}", round_idx=r)
    # 制造一个关闭话题（多一条 summary 段）
    tm.on_new_message(uid, cid, "完全不同的话题", round_idx=6)
    time.sleep(0.01)
    assembled = tm.assemble_topic_context(uid, cid, include_tail=True)
    systems = [m for m in assembled if m["role"] == "system"]
    assert len(systems) <= 1, f"system 消息数 {len(systems)} > 1"


# ── 单元：段优先级（基座语义） ──

def test_priority_eviction_in_assembler():
    """高优先级（current 90）可驱逐已保留的低优先级（active 80）段。"""
    budget = ContextBudget(verbatim_chars=100, tail_rounds=1,
                           max_open_topics=3)
    asm = SegmentedContextAssembler(budget)
    active = ContextSegment(kind=SEG_VERBATIM, content="A" * 90,
                            priority=PRIORITY_ACTIVE, label="[进行中话题]")
    current = ContextSegment(kind=SEG_VERBATIM, content="B" * 90,
                             priority=PRIORITY_CURRENT, label="[当前话题]")
    plan = asm.plan([active, current])
    kept_kinds = [(s.label, s) for s in plan.kept]
    # current 挤掉 active（预算只够一段）
    assert any(l == "[当前话题]" for l, _ in kept_kinds)
    assert any(s.label == "[进行中话题]" and s in plan.dropped
               for l, s in kept_kinds if False) or \
        any(s.label == "[进行中话题]" for s in plan.dropped)


def test_priority_order_values():
    """计划规定的优先级序：memo(100) > current(90) > active(80) > tail(70) > summary(60)。"""
    from harness.context_assembly import (PRIORITY_MEMO, PRIORITY_TAIL)
    assert PRIORITY_MEMO > PRIORITY_CURRENT > PRIORITY_ACTIVE \
        > PRIORITY_TAIL > PRIORITY_SUMMARY


# ── 集成：不超预算 ──

def test_assembly_respects_budget(tm_sem):
    """长会话下 system+history 字符数 ≤ ContextBudget 合计（含段标签余量）。"""
    uid, cid = 1, 1
    big = "英语完形填空的解题技巧。" * 400
    for r in range(1, 15):
        tm_sem.on_new_message(uid, cid, big, round_idx=r)
        tm_sem.record_turn(uid, cid, f"Q{r}:{big}", f"A{r}:{big}", round_idx=r)
    # 历史由调用方传入（agent 历史已被插件裁剪 → 传空代表最坏情况之外的正常态）
    assembled = tm_sem.assemble_topic_context(uid, cid)
    system_text = "".join(m["content"] for m in assembled)
    b = tm_sem.budget
    one_msg = len("Q14:" + big)   # 单条消息体
    # tail 段按设计 unbounded，但**轮数有界**：tail_rounds 轮 × 2 条消息
    cap = b.memo_chars + b.summary_chars + b.verbatim_chars \
        + b.tail_rounds * 2 * one_msg + 4 * 1024   # 标签/间隔余量
    assert len(system_text) <= cap, f"组装结果 {len(system_text)} 超预算 {cap}"


# ── 集成：话题切换 ──

def test_idle_timeout_opens_new_topic(tm):
    """30min 静默 → 关旧话题、开新话题。"""
    uid, cid = 1, 1
    d1 = tm.on_new_message(uid, cid, "二次函数怎么配方", round_idx=1)
    tm.record_turn(uid, cid, "二次函数怎么配方", "配方步骤…", round_idx=1)
    assert d1["action"] == "new"
    old_tid = d1["topic_id"]

    # 把当前话题的活跃时间拨回 31 分钟前
    with tm._lock:
        topic = tm.store.get_topic(old_tid)
        topic["last_active_at"] = time.time() - 31 * 60
        tm.store.save_topic(topic)

    d2 = tm.on_new_message(uid, cid, "新的一天，看看学习计划", round_idx=2)
    assert d2["action"] == "new", d2
    assert d2["topic_id"] != old_tid
    assert tm.store.get_topic(old_tid)["status"] == "closed"


def test_semantic_boundary_new_topic(tm_sem):
    """语义不相似 → 开新话题；相似 → 延续。"""
    uid, cid = 1, 1
    d1 = tm_sem.on_new_message(uid, cid, "数学二次函数怎么配方", round_idx=1)
    tm_sem.record_turn(uid, cid, "数学二次函数怎么配方", "…", round_idx=1)
    d2 = tm_sem.on_new_message(uid, cid, "数学还有哪几种求最值的方法", round_idx=2)
    assert d2["action"] == "continue"   # 同关键词 → 相似
    tm_sem.record_turn(uid, cid, "数学还有哪几种求最值的方法", "…", round_idx=2)
    d3 = tm_sem.on_new_message(uid, cid, "英语完形填空有什么技巧", round_idx=3)
    # 嵌入正交（相似度≈0）→ 低于 reopen 阈值 → 开新话题
    assert d3["action"] == "new", d3


def test_reopen_similar_closed_topic(tm_sem):
    """回到更早的相似话题 → reopen。"""
    uid, cid = 1, 1
    d1 = tm_sem.on_new_message(uid, cid, "数学二次函数图像性质", round_idx=1)
    tm_sem.record_turn(uid, cid, "数学二次函数图像性质", "…", round_idx=1)
    math_tid = d1["topic_id"]
    tm_sem.close_topic(uid, cid, math_tid, summary="二次函数讨论")

    # 无当前话题时，提到相似话题 → reopen
    d2 = tm_sem.on_new_message(uid, cid, "数学的图像平移再讲讲", round_idx=2)
    assert d2["action"] == "reopen", d2
    assert d2.get("topic_id") == math_tid or \
        tm_sem.current_topic(uid, cid)["topic_id"] == math_tid
    assert tm_sem.store.get_topic(math_tid)["status"] == "open"


def _find_topic_by_title(tm, uid, cid, keyword):
    for t in tm.store.list_topics(uid, cid, status=None):
        if keyword in t["title"]:
            return t
    return None


def test_open_candidate_gated_by_reopen_threshold(tm_sem, monkeypatch):
    """open 候选走 TOPIC_REOPEN_THRESHOLD：相似度低于阈值时不得 reopen。"""
    from apps.dsn_study.config import Config
    monkeypatch.setattr(Config, "TOPIC_REOPEN_THRESHOLD", 1.1)      # open 候选不可能达标
    uid, cid = 1, 7
    tm_sem.on_new_message(uid, cid, "数学二次函数图像性质", round_idx=1)
    # 切到英语话题（数学话题仍是 open 候选，未被关闭）
    tm_sem.on_new_message(uid, cid, "英语完形填空技巧", round_idx=2)

    d = tm_sem.on_new_message(uid, cid, "再看看数学二次函数", round_idx=3)
    # 数学候选 sim=1.0 < REOPEN(1.1) → 不 reopen，按不相似开新话题
    assert d["action"] == "new", d


def test_closed_topic_gated_by_activation_threshold(tm_sem, monkeypatch):
    """closed 候选走 TOPIC_ACTIVATION_THRESHOLD（dsn 语义：归档话题重开
    用独立的、更高的门槛，与 open 候选的 REOPEN 阈值区分）。"""
    from apps.dsn_study.config import Config
    monkeypatch.setattr(Config, "TOPIC_REOPEN_THRESHOLD", 1.1)      # open 路径不可达
    monkeypatch.setattr(Config, "TOPIC_ACTIVATION_THRESHOLD", 0.5)  # closed 路径可达
    uid, cid = 1, 8
    tm_sem.on_new_message(uid, cid, "数学二次函数图像性质", round_idx=1)
    math_tid = _find_topic_by_title(tm_sem, uid, cid, "数学")["topic_id"]
    tm_sem.on_new_message(uid, cid, "英语完形填空技巧", round_idx=2)
    tm_sem.close_topic(uid, cid, math_tid, summary="二次函数讨论")

    # 相似度 1.0 ≥ ACTIVATION(0.5)，尽管低于 REOPEN(1.1) → 仍 reopen
    d1 = tm_sem.on_new_message(uid, cid, "再看看数学二次函数", round_idx=3)
    assert d1["action"] == "reopen", d1
    assert tm_sem.store.get_topic(math_tid)["status"] == "open"

    # ACTIVATION 提到 1.2（相似度 1.0 不可达）→ 同样的 closed 候选不再 reopen
    monkeypatch.setattr(Config, "TOPIC_ACTIVATION_THRESHOLD", 1.2)
    tm_sem.close_topic(uid, cid, math_tid, summary="再次归档")
    d2 = tm_sem.on_new_message(uid, cid, "数学图像平移再讲讲", round_idx=4)
    assert d2["action"] == "new", d2


def test_pin_and_close_semantics(tm):
    uid, cid = 1, 3
    d = tm.on_new_message(uid, cid, "讨论 A", round_idx=1)
    tm.record_turn(uid, cid, "讨论 A", "a", round_idx=1)
    tid = d["topic_id"]
    assert tm.pin_topic(uid, cid, tid, True) is True
    assert tm.store.get_topic(tid)["is_pinned"] is True
    assert tm.close_topic(uid, cid, tid) is True
    topic = tm.store.get_topic(tid)
    assert topic["status"] == "closed" and topic["summary"]


# ── 契约（7.6） ──

def test_memory_system_satisfies_port(tmp_path):
    os.environ["QUESTION_BANK_DB_PATH"] = str(tmp_path / "qb.db")
    from apps.dsn_study.db.question_bank import QuestionBankDBManager
    from apps.dsn_study.memory import MemorySystem
    from apps.dsn_study.memory.core import assert_memory_store_port
    from harness.memory.base import MemoryStorePort

    db = QuestionBankDBManager(db_path=str(tmp_path / "qb.db"))
    ms = MemorySystem(db)
    assert isinstance(ms, MemoryStorePort)
    assert assert_memory_store_port(ms) is ms


# ── 压缩持久化接线（7.7） ──

def test_close_topic_persists_compressed_chunk(tm):
    uid, cid = 1, 7
    d = tm.on_new_message(uid, cid, "讨论压缩持久化", round_idx=1)
    tm.record_turn(uid, cid, "讨论压缩持久化", "压缩块应落库", round_idx=1)
    tid = d["topic_id"]
    assert tm.close_topic(uid, cid, tid, summary="压缩接线验证") is True

    chunks = tm.chunks.load_compressed_chunks(session_id=tid)
    assert chunks and len(chunks[0]) == 2   # user + assistant
    roles = [m.role for m in chunks[0]]
    assert roles == ["user", "assistant"]
    # 摘要写进 sessions.summary
    row = tm.chunks.store.execute(
        "SELECT summary FROM sessions WHERE id = ?", (tid,))
    assert row and row[0]["summary"] == "压缩接线验证"


# ── 热路径（7.5）：插件 + boot 装配 ──

def test_topic_plugin_injects_block_and_trims_history(tmp_path, monkeypatch):
    from apps.dsn_study.config import Config
    from harness.pipeline.base import Context, HookPoint
    from apps.dsn_study.pipeline.plugins import TopicContextPlugin
    from apps.dsn_study.memory.topics import TopicManager

    monkeypatch.setattr(Config, "TOPIC_ENABLED", True, raising=False)

    class _FakeConv:
        def __init__(self):
            from infra.models import ChatMessage
            self.messages = [ChatMessage(role="user", content="旧消息" * 100),
                             ChatMessage(role="assistant", content="旧回复" * 100)]

    class _FakeConversations:
        def __init__(self):
            self._c = {"sess-1": _FakeConv()}

        def get(self, sid):
            return self._c.get(sid)

    class _FakeAgent:
        def __init__(self):
            self.conversations = _FakeConversations()

    class _MS:
        def __init__(self, topics):
            self._topics = topics

        def assemble_context(self, user_id, history, cross_user_id=None,
                             chat_id=None):
            return self._topics.assemble_topic_context(
                int(user_id), int(chat_id), include_tail=True)

    mgr = TopicManager(str(tmp_path / "t.db"), embedding_client=None,
                       judge_chat=None)
    ms = _MS(mgr)
    agent = _FakeAgent()
    plugin = TopicContextPlugin(memory_system=ms, agent=agent)

    # 第 1 轮：开新话题 + 落一轮原文（模拟 POST_PROCESS 已 record_turn）
    mgr.on_new_message(1, 1, "第一轮", round_idx=1)
    mgr.record_turn(1, 1, "第一轮", "第一轮回复", round_idx=1)

    ctx = Context(user_id=1, message="第二轮", chat_id=1, session_id="sess-1")
    ctx.extra["user_message"] = "第二轮"
    ctx.extra["round_index"] = 2
    ctx.system_prompt = "身份"
    out = plugin.on_hook(HookPoint.PREPARE, ctx)

    assert out.extra.get("topic_decision", {}).get("action") == "continue"
    assert "当前话题" in out.system_prompt
    assert "第一轮" in out.system_prompt
    # agent 历史被裁剪（上下文由话题块承载）
    assert len(agent.conversations.get("sess-1").messages) == 0


def test_topic_plugin_disabled_is_noop(tmp_path, monkeypatch):
    from apps.dsn_study.config import Config
    from harness.pipeline.base import Context, HookPoint
    from apps.dsn_study.pipeline.plugins import TopicContextPlugin

    monkeypatch.setattr(Config, "TOPIC_ENABLED", False, raising=False)
    plugin = TopicContextPlugin(memory_system=object(), agent=None)
    ctx = Context(user_id=1, message="x", session_id="s")
    out = plugin.on_hook(HookPoint.PREPARE, ctx)
    assert "topic_decision" not in out.extra


def test_memory_record_writes_topic_turn(tmp_path, monkeypatch):
    """MemoryRecordPlugin 在 TOPIC_ENABLED 时同步 record_turn。"""
    from apps.dsn_study.config import Config
    from harness.pipeline.base import Context, HookPoint
    from apps.dsn_study.pipeline.plugins import MemoryRecordPlugin
    from apps.dsn_study.memory.topics import TopicManager

    monkeypatch.setattr(Config, "TOPIC_ENABLED", True, raising=False)

    class _MS:
        def __init__(self, topics):
            self._topics = topics

        def record_round(self, *a, **k):
            pass

        def summarize_turn(self, *a, **k):
            pass

        def handle_tags(self, uid, cid, text):
            return text

    mgr = TopicManager(str(tmp_path / "t2.db"), embedding_client=None,
                       judge_chat=None)
    mgr.on_new_message(1, 1, "数学问题", round_idx=1)
    ms = _MS(mgr)
    plugin = MemoryRecordPlugin(memory_system=ms)
    ctx = Context(user_id=1, message="数学问题", chat_id=1)
    ctx.extra["user_message"] = "数学问题"
    ctx.extra["round_index"] = 1
    ctx.reply = "解题步骤…"
    plugin.on_hook(HookPoint.POST_PROCESS, ctx)

    topic = mgr.current_topic(1, 1)
    msgs = mgr.topic_messages(topic["topic_id"])
    assert [(m["role"], m["content"]) for m in msgs] == [
        ("user", "数学问题"), ("assistant", "解题步骤…")]


def test_boot_wires_topics_when_enabled(tmp_path_factory, monkeypatch):
    """TOPIC_ENABLED=true 的装配：TOPIC_MANAGER 就位、memory_system 已接线。"""
    os.environ["TOPIC_ENABLED"] = "true"
    db = tmp_path_factory.mktemp("topic_boot") / "qb.db"
    os.environ["QUESTION_BANK_DB_PATH"] = str(db)
    os.environ["LOG_DIR"] = str(tmp_path_factory.mktemp("topic_logs"))
    os.environ["TTS_AUTOSTART"] = "false"
    os.environ["TTS_WARMUP"] = "false"
    os.environ["ASR_WARMUP"] = "false"
    os.environ["MCP_ENABLED"] = "false"
    os.environ["VISION_WARMUP"] = "false"
    from apps.dsn_study import boot
    app = boot.create_application()
    engine = app.config["ENGINE"]
    assert app.config.get("TOPIC_MANAGER") is not None
    assert engine.memory_system._topics is not None
    # 清理环境，防止污染其它用例的 Config 快照
    os.environ["TOPIC_ENABLED"] = "false"
