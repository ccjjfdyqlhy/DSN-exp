# tests/test_dsn_study_cache.py
# dsn_study 语义缓存（apps/dsn_study/semantic_cache）移植验收（阶段 3，FEATURE_GAP.md）。
# 嵌入用 FakeEmbedder（确定性向量），不联网。

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from apps.dsn_study.db.question_bank import QuestionBankDBManager
from apps.dsn_study.semantic_cache import CacheStore, L1PragmaticCache, CacheEngine
from apps.dsn_study.semantic_cache.engine import INTENT_KEYWORDS


class FakeEmbedder:
    """确定性嵌入：按关键词给向量，相似文本 → 相近向量。"""

    def __init__(self):
        self.calls = 0

    def embed(self, text: str):
        self.calls += 1
        vec = [0.0] * 8
        for i, ch in enumerate(text[:8]):
            vec[i] = (ord(ch) % 97) / 97.0
        return vec


@pytest.fixture(scope="module")
def db():
    return QuestionBankDBManager(
        db_path=tempfile.mkdtemp(prefix="dsn_study_cache_") + "/qb.db")


@pytest.fixture()
def engine(db):
    store = CacheStore(db=db, cache_dir=tempfile.mkdtemp(prefix="dsn_study_cache_dir_"),
                       dims=8)
    l1 = L1PragmaticCache(store=store)
    l1.init_builtin_phrases()
    return CacheEngine(store=store, l1_cache=l1, embedding_client=FakeEmbedder(),
                       similarity_threshold=0.5)


# ── 意图分类（study 裁剪版） ──

def test_classify_intent_study_scopes():
    bare = CacheEngine(store=None, l1_cache=None)   # classify_intent 不依赖 store
    assert bare.classify_intent("帮我组一份函数测试卷") == "compose_exam"
    assert bare.classify_intent("搜索一下二次函数顶点公式") == "search_web"
    assert bare.classify_intent("今天有什么安排") == "check_schedule"
    assert bare.classify_intent("提醒我三点交作业") == "set_reminder"
    # dsn 专属意图已移除：天气/音乐/扫描不再单独分类
    assert bare.classify_intent("今天天气怎么样") == "general_question"
    assert "play_music" not in INTENT_KEYWORDS
    assert "check_weather" not in INTENT_KEYWORDS


def test_build_cache_key_deterministic():
    k1 = CacheEngine.build_cache_key("compose_exam", "出5道题")
    k2 = CacheEngine.build_cache_key("compose_exam", "出 5 道题")   # 空白归一
    assert k1 == k2


# ── 缓存写入 + 语义命中 ──

def test_cache_response_and_semantic_serve(engine):
    key = engine.cache_response(1, "帮我出一份函数测试卷",
                                "好的，已生成 5 道函数题（第 1 题……）")
    assert key is not None

    # 相同问题 → build_cache_key 一致 → search 命中该条目
    hits = engine.search("帮我出一份函数测试卷", intent_class="compose_exam")
    assert hits and hits[0].cache_key == key
    assert "函数题" in hits[0].reply_text

    # record_hit / score
    engine.record_hit(key)
    entry = engine._store.get_entry(key)
    assert entry["score"] >= 1.0


def test_cache_no_embedder_no_write(db):
    store = CacheStore(db=db, cache_dir=tempfile.mkdtemp(prefix="dsn_study_cache_dir_"))
    eng = CacheEngine(store=store, l1_cache=L1PragmaticCache(store),
                      embedding_client=None)
    assert eng.cache_response(1, "q", "a") is None
    assert eng.serve_l2("q") is None
    assert eng.search("q") == []


def test_negative_signal_and_decay(engine):
    assert engine.is_negative_signal("不对，这不是我要的")
    assert not engine.is_negative_signal("很好，谢谢")
    key = engine.cache_response(1, "出题：函数", "回复A")
    base = engine._store.get_entry(key)["score"]
    engine.decay_score(key)
    assert engine._store.get_entry(key)["score"] < base
    engine.boost_score(key)


# ── L1 语用短语（内置短语初始化） ──

def test_l1_builtin_phrases(engine):
    engine._l1.init_builtin_phrases()
    assert engine._l1.lookup("greeting", "greeting") is not None
    # general_question 不在 SPEECH_ACT_ONLY 集合，serve_l1 不命中
    assert engine.serve_l1("general_question") is None


# ── boot 装配冒烟（默认关闭 → engine.cache_engine 为 None，chat 不受影响） ──

@pytest.fixture(scope="module")
def study_app():
    import os
    os.environ["QUESTION_BANK_DB_PATH"] = (
        tempfile.mkdtemp(prefix="dsn_study_cache_boot_") + "/qb.db")
    from apps.dsn_study.boot import create_application
    return create_application()


def test_boot_cache_gate(study_app):
    engine = study_app.config["ENGINE"]
    # 默认 SEMANTIC_CACHE_ENABLED=false → 未装配，chat 路径不受影响
    assert engine.cache_engine is None
    assert engine._cache_serve("任意问题") == ""
