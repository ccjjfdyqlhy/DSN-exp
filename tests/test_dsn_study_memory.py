# tests/test_dsn_study_memory.py
# dsn_study 记忆系统（apps/dsn_study/memory）移植验收（阶段 2，FEATURE_GAP.md）。
# 不依赖真实 LLM：摘要用 FakeLLM，检索走关键词路径。

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from apps.dsn_study.db.question_bank import QuestionBankDBManager
from apps.dsn_study.memory import MemorySystem, LLMSummaryModel, OpenAIEmbeddingClient
from apps.dsn_study.config import Config


@pytest.fixture(scope="module")
def db():
    return QuestionBankDBManager(
        db_path=tempfile.mkdtemp(prefix="dsn_study_mem_") + "/qb.db")


class FakeLLM:
    """摘要桩：回显可断言的固定格式。"""

    def send_message(self, prompt):
        return "用户测试了记忆，助手确认可用。"


@pytest.fixture(scope="module")
def ms(db):
    system = MemorySystem(db, summary_model=LLMSummaryModel(FakeLLM()))
    return system


# ── memo CRUD ──

def test_memo_crud(ms):
    mid = ms.add_memo(1, 0, "用户在备考高考数学")
    memos = ms._get_memos(1)
    assert any(m["id"] == mid and m["content"] == "用户在备考高考数学" for m in memos)
    assert ms.delete_memo(mid) is True
    assert all(m["id"] != mid for m in ms._get_memos(1))


# ── 轮次记录 + 摘要 ──

def test_record_round_and_summarize(ms, db):
    ms.record_round(1, 0, 1, "我今天学了函数", "很好，函数是高考重点")
    mid = ms.summarize_turn(1, 0, 1, "我今天学了函数", "很好，函数是高考重点",
                            async_mode=False)
    assert mid is not None
    exps = ms._get_exp_memories(1)
    assert any("用户测试了记忆" in e["content"] for e in exps)
    # <recall> detail 能还原原始轮次
    detail = ms.get_detail(1, 0, [1])
    assert 1 in detail
    assert detail[1][0]["content"] == "我今天学了函数"
    assert detail[1][1]["role"] == "assistant"


def test_handle_tags_memo_and_recall(ms):
    text = "好的<memo>用户偏好先看结论</memo>，已记录。"
    cleaned = ms.handle_tags(1, 0, text)
    assert "<memo>" not in cleaned and "已记录" in cleaned
    assert any("用户偏好先看结论" in m["content"] for m in ms._get_memos(1))

    recall_text = '查一下<recall>{"keywords": ["偏好"]}</recall>'
    out = ms.handle_tags(1, 0, recall_text)
    # 标签被消费：正文只剩"查一下"，检索结果作为附录追加
    # （附录末尾含 dsn 原版自带的 <recall> 用法提示文本，属预期）
    assert out.split("\n\n")[0] == "查一下"
    assert "记忆检索结果" in out


def test_search_keyword(ms):
    ms.add_memo(2, 0, "用户喜欢用类比理解概念")
    hits = ms.search(2, ["类比"], limit=3)
    assert hits and "类比" in hits[0]["content"]
    assert ms.search(2, ["不存在的词xyzzy"], limit=3) == []


# ── 上下文装配 ──

def test_assemble_context(ms):
    history = [{"role": "user", "content": f"消息{i}"} for i in range(3)]
    ctx = ms.assemble_context(2, history)
    joined = " ".join(m["content"] for m in ctx)
    assert "类比" in joined
    assert any(m["content"] == "消息0" for m in ctx)


# ── 摘要模型接口 ──

def test_summary_model():
    m = LLMSummaryModel(FakeLLM())
    out = m.summarize_dialog([{"role": "user", "content": "a"},
                              {"role": "assistant", "content": "b"}], max_length=100)
    assert out == "用户测试了记忆，助手确认可用。"
    assert m.summarize_text("x", max_length=10)

    unbound = LLMSummaryModel()
    # 未注入客户端 → 静默降级返回 None（摘要失败不得打断记忆主流程）
    assert unbound.summarize_dialog([{"role": "user", "content": "a"}]) is None
    assert unbound.summarize_text("a") is None


def test_summary_model_failure_returns_none():
    class Boom:
        def send_message(self, prompt):
            raise RuntimeError("down")

    m = LLMSummaryModel(Boom())
    assert m.summarize_dialog([{"role": "user", "content": "a"}]) is None


# ── 嵌入客户端（不联网，仅验证降级路径） ─---

def test_embedding_client_degrades():
    client = OpenAIEmbeddingClient(base_url="http://127.0.0.1:1", timeout=1)
    assert client.embed("hello") is None
    assert client.embed("") is None


# ── 装配冒烟：boot 后 engine 挂记忆 + 技能工具在位 ──

@pytest.fixture(scope="module")
def study_app():
    import os
    os.environ["QUESTION_BANK_DB_PATH"] = (
        tempfile.mkdtemp(prefix="dsn_study_mem_boot_") + "/qb.db")
    from apps.dsn_study.boot import create_application
    return create_application()


def test_boot_wires_memory(study_app):
    engine = study_app.config["ENGINE"]
    assert engine.memory_system is not None
    tools = engine.skill_registry.list_active_tools()
    assert "study_memory.recall" in tools
    assert "study_memory.save_memo" in tools
    # AgentLoop 工具表也同步桥接了记忆工具
    assert study_app.config["MEMORY_SYSTEM"] is engine.memory_system
