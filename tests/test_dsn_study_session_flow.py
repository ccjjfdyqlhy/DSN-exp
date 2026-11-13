# -*- coding: utf-8 -*-
"""dsn_study 会话推进相关的回归测试（第二轮修复）。

上一轮修的是「上下文进不了 prompt」；这一轮修的是**会话推不下去**：

1. **语音/流式链路根本不落记忆** ——
   CLI 语音走 /api/asr/passthrough → `chat_stream_audio` → 绕过管线的
   MODEL_INVOKE，POST_PROCESS 从不执行 ⇒ chat_rounds / 经验摘要 /
   话题原文全都不写；而 `_finish_stream_turn` 调的 `record_turn()` 方法
   根本不存在，异常被 debug 日志吞掉。
   更糟的是 TopicContextPlugin 每轮把 agent 的对话历史裁掉（指望话题块
   承载上下文），可话题块是空的 ⇒ 模型每轮从零开始。
2. **话题边界在嵌入服务挂掉时失效** ——
   LMStudio(4501) 没起 → 无语义信号 → 判定退化成「永远延续当前话题」
   ⇒ 会话卡死在一个话题里。
3. **摄像头台账按逻辑名记账** —— 同一台物理摄像头换过名字就被登记两次。
"""

from __future__ import annotations

import os

import pytest


# ── 1) 流式链路必须落记忆 ───────────────────────────────────────

@pytest.fixture(scope="module")
def study_app(tmp_path_factory):
    db = tmp_path_factory.mktemp("study") / "qb.db"
    os.environ["QUESTION_BANK_DB_PATH"] = str(db)
    os.environ["LOG_DIR"] = str(tmp_path_factory.mktemp("logs"))
    os.environ["TTS_AUTOSTART"] = "false"
    os.environ["TTS_WARMUP"] = "false"
    os.environ["MCP_ENABLED"] = "false"
    from apps.dsn_study import boot
    boot.create_application()
    return boot.engine


def _memory_plugin(study_app):
    """取管线里的记忆插件（流式收尾补跑的就是它）。"""
    plugins = study_app.pipeline_runner.pm._plugins
    return plugins["study_memory_record"]


def test_finish_stream_turn_records_memory(study_app, monkeypatch):
    """流式收尾必须把这一轮写进记忆（chat_rounds / 摘要 / 话题原文）。"""
    from harness.pipeline.base import Context

    calls = {}

    class _SpyMemory:
        _topics = None

        def record_round(self, uid, cid, ridx, user_msg, reply):
            calls["round"] = (uid, cid, ridx, user_msg, reply)

        def summarize_turn(self, uid, cid, ridx, user_msg, reply, **kw):
            calls["summary"] = (uid, cid, ridx)

        def handle_tags(self, uid, cid, reply):
            calls["tags"] = reply
            return reply

    plugin = _memory_plugin(study_app)
    monkeypatch.setattr(plugin, "_memory_system", _SpyMemory(), raising=False)

    ctx = Context(user_id=1, message="讲讲动能定理", session_id="s1", chat_id=7)
    ctx.extra["user_message"] = "讲讲动能定理"
    ctx.extra["round_index"] = 3
    study_app._finish_stream_turn(ctx, "这是回复", 1)

    assert "round" in calls, "流式路径没写 chat_rounds"
    assert calls["round"][2] == 3, "轮次号没对上"
    assert calls["round"][3] == "讲讲动能定理"
    assert "summary" in calls, "流式路径没做经验摘要"


def test_finish_stream_turn_records_topic_turn(study_app, monkeypatch):
    """话题原文也要写 —— 否则话题块是空的，模型每轮从零开始。"""
    from harness.pipeline.base import Context

    recorded = {}

    class _Topics:
        def record_turn(self, uid, cid, user_msg, assistant_msg, round_idx=0):
            recorded["turn"] = (uid, cid, user_msg, assistant_msg, round_idx)

    class _SpyMemory:
        def __init__(self):
            self._topics = _Topics()

        def record_round(self, *a, **kw):
            pass

        def summarize_turn(self, *a, **kw):
            pass

        def handle_tags(self, uid, cid, reply):
            return reply

    plugin = _memory_plugin(study_app)
    monkeypatch.setattr(plugin, "_memory_system", _SpyMemory(), raising=False)

    ctx = Context(user_id=1, message="换个话题", session_id="s2", chat_id=8)
    ctx.extra["user_message"] = "换个话题"
    ctx.extra["round_index"] = 1
    study_app._finish_stream_turn(ctx, "好", 1)

    assert "turn" in recorded, "流式路径没写话题原文"


def test_engine_has_no_dead_record_turn_call():
    """旧实现在流式收尾里调 `record_turn()` —— MemorySystem 没这个方法。

    异常被 `logger.debug` 吞掉，语音链路的记忆一直是断的，且毫无痕迹。
    """
    import inspect
    from apps.dsn_study.memory.core import MemorySystem
    assert not hasattr(MemorySystem, "record_turn"), \
        "MemorySystem 没有 record_turn（流式路径不能调它）"
    assert hasattr(MemorySystem, "record_round")
    src = inspect.getsource(MemorySystem)
    assert "def record_turn" not in src


# ── 2) 无嵌入信号时的词面兜底 ───────────────────────────────────

def test_lexical_fallback_opens_new_topic(tmp_path):
    """嵌入服务不可用时，话题不相关就该开新话题（不能永远卡在一个话题）。"""
    from apps.dsn_study.memory.topics import TopicManager

    mgr = TopicManager(str(tmp_path / "topics.db"), summary_model=None,
                       embedding_client=None, judge_chat=None)
    uid, cid = 1, 1
    mgr.on_new_message(uid, cid, "讲讲动能定理第二问怎么用", round_idx=1)
    mgr.record_turn(uid, cid, "讲讲动能定理第二问怎么用", "先定初末速度", round_idx=1)
    first = mgr.current_topic(uid, cid)["topic_id"]

    mgr.on_new_message(uid, cid, "今天晚饭吃什么好", round_idx=2)
    second = mgr.current_topic(uid, cid)["topic_id"]
    assert second != first, "无关的新消息没有开出新话题（会话会卡死）"


def test_lexical_fallback_keeps_same_topic(tmp_path):
    """相关追问仍要延续当前话题（别把会话碎成片）。"""
    from apps.dsn_study.memory.topics import TopicManager

    mgr = TopicManager(str(tmp_path / "topics.db"), summary_model=None,
                       embedding_client=None, judge_chat=None)
    uid, cid = 1, 1
    mgr.on_new_message(uid, cid, "讲讲动能定理第二问怎么用", round_idx=1)
    mgr.record_turn(uid, cid, "讲讲动能定理第二问怎么用", "先定初末速度", round_idx=1)
    first = mgr.current_topic(uid, cid)["topic_id"]

    mgr.on_new_message(uid, cid, "动能定理第二问还是没懂", round_idx=2)
    assert mgr.current_topic(uid, cid)["topic_id"] == first, \
        "同一话题的追问被切成了新话题"


def test_lexical_similarity_separates_topics():
    from apps.dsn_study.memory.topics import lexical_similarity
    same = lexical_similarity("用户问第二问怎么用动能定理", "用户问第二问怎么用动能定理")
    other = lexical_similarity("用户问第二问怎么用动能定理", "今天晚饭吃什么好")
    assert same > 0.9 and other < 0.2


# ── 3) 摄像头台账按物理设备去重 ───────────────────────────────

def test_camera_ledger_dedupes_by_device_index(tmp_path):
    """同一台物理摄像头换过名字 → 台账里只能留一个。"""
    from apps.dsn_study.api.vision import VisionCoordinator

    coord = VisionCoordinator(db=None)
    coord.register_cameras([{"logical_name": "cam0", "index": 0},
                            {"logical_name": "cam1", "index": 2}])
    assert len(coord.list_cameras()) == 2

    # 客户端后来改用 camera_map 命名 → 同一个 index 又来一次
    coord.register_cameras([{"logical_name": "desk", "index": 0},
                            {"logical_name": "doc", "index": 2}])
    names = sorted(c["logical_name"] for c in coord.list_cameras())
    assert names == ["desk", "doc"], "台账里同一个物理设备留了多个名字: %s" % names


def test_camera_ledger_keeps_note_on_rename(tmp_path):
    """改名时备注要跟着物理设备走（备注描述的是那台设备）。"""
    from apps.dsn_study.api.vision import VisionCoordinator

    coord = VisionCoordinator(db=None)
    coord.register_cameras([{"logical_name": "cam0", "index": 0}])
    coord.set_camera_note("cam0", "书桌正面 — Newmine 摄像头")

    coord.register_cameras([{"logical_name": "desk", "index": 0}])
    entry = {c["logical_name"]: c for c in coord.list_cameras()}["desk"]
    assert "Newmine" in entry["note"], "改名后备注丢了: %r" % entry["note"]
