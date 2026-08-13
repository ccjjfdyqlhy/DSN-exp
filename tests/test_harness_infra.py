# tests/test_harness_infra.py
# store / auth / memory / tasks / conversation / cache / observability

from __future__ import annotations

import time

from harness.auth import APIKeyManager, SessionManager, TOTP
from harness.cache import SemanticCache
from harness.conversation import Conversation, ConversationManager
from harness.memory import InMemoryStore, MemoryEntry
from harness.models.stub import StubEmbeddingClient
from harness.store import Migration, MigrationRunner, SqliteStore
from harness.tasks import Task, TaskExecutorRegistry, TaskStatus


# ── store ──

def test_sqlite_store_execute_and_migration():
    store = SqliteStore(":memory:")
    runner = MigrationRunner(store)
    ran = runner.migrate([
        Migration("001_init", lambda c: c.execute(
            "CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")),
    ])
    assert ran == ["001_init"]
    store.execute("INSERT INTO items (name) VALUES (?)", ("apple",))
    rows = store.execute("SELECT name FROM items")
    assert rows[0]["name"] == "apple"


def test_migration_idempotent():
    store = SqliteStore(":memory:")
    runner = MigrationRunner(store)
    migs = [Migration("001", lambda c: c.execute("CREATE TABLE t (x)"))]
    assert runner.migrate(migs) == ["001"]
    assert runner.migrate(migs) == []  # 已应用


# ── auth ──

def test_api_key_generate_verify_revoke():
    mgr = APIKeyManager()
    key = mgr.generate()
    assert key.startswith("apk_")
    assert mgr.verify(key)
    assert mgr.revoke(key)
    assert not mgr.verify(key)


def test_session_roundtrip_and_expiry():
    sm = SessionManager("secret", ttl_seconds=10)
    token = sm.sign({"uid": "u1"})
    assert sm.verify(token) == {"uid": "u1"}
    assert sm.verify("garbage") is None


def test_session_expired():
    sm = SessionManager("secret", ttl_seconds=-1)
    token = sm.sign({"uid": "u1"})
    assert sm.verify(token) is None


def test_totp_generate_and_verify():
    totp = TOTP()
    secret = totp.generate_secret()
    code = totp.current_code(secret)
    assert totp.verify(code, secret)
    assert not totp.verify("000000", secret)


# ── memory ──

def test_in_memory_store_keyword_and_vector():
    store = InMemoryStore(StubEmbeddingClient())
    store.add_text("我喜欢喝咖啡", role="memo")
    store.add_text("今天天气不错", role="memo")
    hits = store.search("咖啡")
    assert hits and "咖啡" in hits[0].text
    assert store.count() == 2


def test_in_memory_store_no_embedding_fallback():
    store = InMemoryStore()
    store.add_text("hello world")
    assert store.search("hello")[0].text == "hello world"


# ── tasks ──

def test_task_executor_registry_sync():
    reg = TaskExecutorRegistry()
    reg.register_type("echo", lambda **p: p["msg"])
    task = reg.execute(Task(type="echo", params={"msg": "hi"}))
    assert task.ok and task.result == "hi"


def test_task_unknown_type_fails():
    reg = TaskExecutorRegistry()
    task = reg.execute(Task(type="nope"))
    assert task.status == TaskStatus.FAILED


# ── conversation ──

def test_conversation_history_trimming():
    conv = Conversation()
    for i in range(10):
        conv.add_text("user", f"msg{i}")
    hist = conv.history(max_messages=3)
    assert [m.content for m in hist] == ["msg7", "msg8", "msg9"]


def test_conversation_manager():
    mgr = ConversationManager()
    conv = mgr.create()
    assert mgr.get(conv.session_id) is conv
    assert mgr.require(conv.session_id) is conv
    assert mgr.delete(conv.session_id)


# ── cache / observability ──

def test_semantic_cache_exact_and_vector():
    cache = SemanticCache(StubEmbeddingClient(), similarity_threshold=0.5)
    cache.put("把提醒设到3点", "answer-A")
    hit, val = cache.get("把提醒设到3点")
    assert hit and val == "answer-A"
    # 相似查询命中 L2
    hit2, _ = cache.get("把提醒设到 3 点")
    assert hit2


def test_metrics_collector():
    from harness.observability import MetricsCollector
    mc = MetricsCollector()
    mc.incr("requests")
    with mc.timer_start("llm"):
        pass
    snap = mc.snapshot()
    assert snap["counters"]["requests"] == 1
    assert "llm" in snap["timings"]
