# tests/test_rc0_runtime.py
# R4 托管运行时（Journal + Checkpoint + 幂等 + 恢复）的测试。
#
# 这一层的价值不在于「代码跑通了」，而在于钉死三条**不可退让**的性质：
#   1. 幂等键稳定 —— 同样的参数必须得到同样的键（否则重复投递 = 重复副作用）；
#   2. journal 只追加、seq 单调 —— 真相来源不能被改写；
#   3. effectful 结果未知时**绝不自动重放** —— 这是托管运行时存在的全部理由。
#
# 交叉测试（infra 的幂等键 vs harness 的幂等键）在这里：
#   依赖规则禁止 infra → harness，所以公式只能各写一份；
#   两份实现一旦漂移，重复投递就会变成重复扣款 —— 所以必须用测试钉死。

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import threading

import pytest

from infra.runtime import (
    EFFECT_EFFECTFUL,
    EFFECT_IDEMPOTENT,
    EFFECT_PURE,
    CheckpointCorruptError,
    CheckpointStore,
    Journal,
    ManagedRuntime,
    ResultCache,
    SqliteRuntimeStore,
    StorePort,
    args_digest,
    canonical_args,
    idempotency_key,
    is_replay_safe,
    migrate_runtime,
    normalize_effect,
    recover,
)
from infra.store.sqlite import SqliteStore


# ── 夹具 ──────────────────────────────────────────────

@pytest.fixture()
def store(tmp_path):
    """文件型 sqlite：崩溃恢复要跨进程，内存库不行。"""
    st = SqliteStore(str(tmp_path / 'runtime.db'))
    migrate_runtime(st)
    yield st
    st.close()


@pytest.fixture()
def port(store):
    return SqliteRuntimeStore(store)


@pytest.fixture()
def runtime(port):
    rt = ManagedRuntime(port, session_id='s1')
    rt.start_session(tenant='t1', artifact_id='a1')
    rt.start_turn(0, input={'q': 'hello'})
    return rt


# ── 幂等键 ────────────────────────────────────────────

def test_idempotency_key_is_stable_for_reordered_args():
    """键顺序不同的等价参数必须得到同一个键。"""
    a = idempotency_key('s1', 0, 'calc', {'a': 1, 'b': 2})
    b = idempotency_key('s1', 0, 'calc', {'b': 2, 'a': 1})
    assert a == b


def test_idempotency_key_changes_with_args_or_turn_or_tool():
    base = idempotency_key('s1', 0, 'calc', {'a': 1})
    assert base != idempotency_key('s1', 0, 'calc', {'a': 2})
    assert base != idempotency_key('s1', 1, 'calc', {'a': 1})
    assert base != idempotency_key('s2', 0, 'calc', {'a': 1})
    assert base != idempotency_key('s1', 0, 'other', {'a': 1})


def test_idempotency_key_is_sha256_hex():
    import hashlib
    expected = hashlib.sha256(
        b's1|0|calc|{"a":1,"b":2}').hexdigest()
    assert idempotency_key('s1', 0, 'calc', {'a': 1, 'b': 2}) == expected


def test_canonical_args_handles_non_dict_and_unserializable():
    assert canonical_args(None) == '{}'
    assert canonical_args('x') == canonical_args('x')
    assert canonical_args({'a': object()})  # 不可序列化 → repr，不抛异常


def test_args_digest_is_stable_and_short():
    assert args_digest({'a': 1}) == args_digest({'a': 1})
    assert len(args_digest({'a': 1})) == 16


# ── 交叉测试：infra 与 harness 的幂等键必须逐字一致 ──────

def test_canonical_args_matches_harness_implementation():
    from harness.runtime_client import canonical_args as harness_canonical

    for args in (None, {}, {'a': 1, 'b': 2}, {'b': 2, 'a': 1},
                 {'x': [1, 2, {'k': 'v'}]}, 'text', 42, {'n': None}):
        assert canonical_args(args) == harness_canonical(args)


@pytest.mark.parametrize('session_id,turn_seq,tool,args', [
    ('s1', 0, 'calc', {'a': 1, 'b': 2}),
    ('s1', 0, 'calc', {'b': 2, 'a': 1}),        # 键顺序不同
    ('s1', 7, 'send_email', {'to': 'x@y.z', 'body': 'hi'}),
    ('s1', 0, 'calc', None),
    ('s1', 0, 'calc', {'nested': {'z': 1, 'a': 2}}),
])
def test_idempotency_key_matches_harness_implementation(session_id, turn_seq,
                                                        tool, args):
    """infra 与 harness 各写一份公式 —— 用交叉测试钉死它们不会漂移。"""
    from harness.runtime_client import idempotency_key as harness_key

    assert idempotency_key(session_id, turn_seq, tool, args) == \
        harness_key(session_id, turn_seq, tool, args)


def test_reordered_args_produce_identical_key_in_both_implementations():
    from harness.runtime_client import idempotency_key as harness_key

    left = idempotency_key('s1', 0, 'calc', {'a': 1, 'b': 2})
    right = harness_key('s1', 0, 'calc', {'b': 2, 'a': 1})
    assert left == right


# ── 依赖方向：infra 不得 import harness ────────────────

def test_infra_runtime_does_not_import_harness():
    """依赖规则：infra 在下、harness 在上，反向依赖被禁止。

    幂等键公式因此各写一份（靠交叉测试钉死），而不是让 infra 去 import harness。
    """
    import pathlib

    import infra.runtime as pkg

    root = pathlib.Path(pkg.__file__).parent
    for path in sorted(root.glob('*.py')):
        source = path.read_text(encoding='utf-8')
        for line in source.splitlines():
            stripped = line.strip()
            assert not stripped.startswith(('import harness', 'from harness')), \
                f'{path.name} 反向依赖了 harness: {stripped}'


# ── journal：只追加 + seq 单调 ────────────────────────

def test_journal_seq_is_monotonic_and_unique(runtime, port):
    for i in range(5):
        runtime.emit('custom', {'i': i})
    events = Journal(port).events('s1')
    seqs = [event.seq for event in events]
    assert seqs == sorted(seqs)
    assert len(seqs) == len(set(seqs))
    assert seqs == list(range(seqs[0], seqs[0] + len(seqs)))


def test_journal_has_no_update_or_delete_api(port):
    """只追加是**结构性的**：连方法都不提供，改写事实必须靠追加新事件。"""
    journal = Journal(port)
    for banned in ('update', 'delete', 'remove', 'truncate', 'rewrite'):
        assert not hasattr(journal, banned)


def test_journal_dedupe_by_seq_keeps_first(runtime, port):
    runtime.emit('custom', {'n': 1})
    events = Journal(port).events('s1')
    doubled = events + events
    deduped = Journal.dedupe(doubled)
    assert len(deduped) == len(events)
    assert [e.seq for e in deduped] == [e.seq for e in events]


def test_journal_seq_allocation_is_safe_under_threads(runtime, port):
    """并发追加不能让两个事件拿到同一个 seq。"""
    journal = Journal(port)
    errors: list[BaseException] = []

    def worker(index: int) -> None:
        try:
            for i in range(10):
                journal.append('custom', {'w': index, 'i': i}, session_id='s1')
        except BaseException as exc:      # noqa: BLE001 - 测试要看到异常
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    events = journal.events('s1')
    seqs = [event.seq for event in events]
    assert len(seqs) == len(set(seqs))
    assert seqs == sorted(seqs)


def test_events_are_scoped_per_session(runtime, port):
    other = ManagedRuntime(port, session_id='s2')
    other.emit('custom', {'x': 1})
    runtime.emit('custom', {'x': 2})
    assert len(Journal(port).events('s1')) != len(Journal(port).events('s2'))


# ── checkpoint：加速器，不是真相来源 ───────────────────

def test_checkpoint_write_and_load(port):
    store = CheckpointStore(port)
    ref = store.write('s1', 3, {'messages': ['a']}, journal_seq=42)
    assert ref == 's1@3'
    loaded = store.load('s1')
    assert loaded is not None
    assert loaded.blob == {'messages': ['a']}
    assert loaded.journal_seq == 42
    assert loaded.turn_seq == 3


def test_latest_checkpoint_wins(port):
    store = CheckpointStore(port)
    store.write('s1', 1, {'n': 1})
    store.write('s1', 2, {'n': 2})
    assert store.latest('s1').blob == {'n': 2}


def test_runtime_checkpoint_records_journal_watermark(runtime, port):
    runtime.emit('custom', {'n': 1})
    ref = runtime.checkpoint({'state': 'x'})
    assert ref
    loaded = CheckpointStore(port).latest('s1')
    assert loaded.journal_seq == Journal(port).last_seq('s1')


def test_corrupt_checkpoint_raises_and_recovery_falls_back_to_journal(runtime, port):
    """策划案 §8.2 用例 7：checkpoint 损坏 → 从 journal 重放恢复。"""
    runtime.emit('custom', {'n': 1})
    runtime.checkpoint({'state': 'x'})

    # 人为损坏：blob_json 不是合法 JSON
    conn = port._store.get_connection()
    conn.execute("UPDATE runtime_checkpoint SET blob_json = '{oops' WHERE session_id = 's1'")
    conn.commit()

    with pytest.raises(CheckpointCorruptError):
        CheckpointStore(port).latest('s1')

    plan = recover(port, 's1')
    assert plan.checkpoint_corrupt is True
    assert plan.checkpoint is None
    # 真相来源还在：journal 的事件一条不少
    assert len(plan.events) == len(Journal(port).events('s1'))
    assert plan.resume_turn_seq == 0


# ── 幂等执行：重复投递不产生第二次副作用 ───────────────

def test_duplicate_delivery_of_same_call_executes_once(runtime):
    """策划案 §8.2 用例 2 / R7：同一幂等键投递 3 次 → 副作用只发生 1 次。"""
    side_effects = []

    def send() -> str:
        side_effects.append(1)
        return 'sent'

    outcomes = [
        runtime.execute_tool(tool='send_email', args={'to': 'a@b.c'},
                             fn=send, effect=EFFECT_EFFECTFUL)
        for _ in range(3)
    ]
    assert [o.status for o in outcomes] == ['executed', 'reused', 'reused']
    assert len(side_effects) == 1
    assert outcomes[1].result == 'sent'


def test_lookup_tool_result_returns_cached_value(runtime):
    runtime.execute_tool(tool='calc', args={'x': 1}, fn=lambda: 42,
                         effect=EFFECT_PURE)
    key = runtime.idempotency_key('s1', 0, 'calc', {'x': 1})
    assert runtime.lookup_tool_result(key) == 42
    assert runtime.lookup_tool_result('nonexistent') is None


def test_result_cache_survives_without_cache_row(runtime, port):
    """缓存表丢了也要能从 journal 找回结果 —— 否则会重复执行。"""
    runtime.execute_tool(tool='calc', args={'x': 1}, fn=lambda: 42,
                         effect=EFFECT_PURE)
    key = runtime.idempotency_key('s1', 0, 'calc', {'x': 1})
    conn = port._store.get_connection()
    conn.execute('DELETE FROM tool_result_cache')
    conn.commit()

    assert ResultCache(port).get_result(key) == 42
    calls = []
    outcome = runtime.execute_tool(tool='calc', args={'x': 1},
                                    fn=lambda: calls.append(1),
                                    effect=EFFECT_PURE)
    assert outcome.status == 'reused'
    assert not calls


# ── effectful 的三段式与 unknown_outcome ───────────────

def test_intent_is_written_before_execution(runtime, port):
    """先写 intent → 执行 → 后写 result，顺序不可换。"""
    seen: list[str] = []

    def tool() -> str:
        seen.append('exec')
        events = Journal(port).events('s1')
        kinds = [event.kind for event in events]
        assert 'tool_intent' in kinds
        assert 'tool_result' not in kinds
        return 'ok'

    runtime.execute_tool(tool='pay', args={'amount': 1}, fn=tool,
                         effect=EFFECT_EFFECTFUL)
    kinds = [event.kind for event in Journal(port).events('s1')]
    assert kinds.index('tool_intent') < kinds.index('tool_result')
    assert seen == ['exec']


def test_effectful_with_unknown_outcome_is_not_replayed(runtime, port):
    """只有 intent 没有 result → unknown_outcome，**绝不**自动重放。"""
    key = runtime.idempotency_key('s1', 0, 'pay', {'amount': 1})
    runtime.record_tool_intent(_intent('s1', 0, 'pay', key, EFFECT_EFFECTFUL))

    plan = recover(port, 's1')
    assert plan.has_unknown_outcomes
    assert plan.requires_human_review
    assert [item.tool for item in plan.unknown_outcomes] == ['pay']
    assert plan.unknown_keys() == {key}

    resumed = ManagedRuntime(port, session_id='s1')
    resumed.resume()
    side_effects = []
    outcome = resumed.execute_tool(tool='pay', args={'amount': 1},
                                   fn=lambda: side_effects.append(1),
                                   effect=EFFECT_EFFECTFUL)
    assert outcome.status == 'unknown_outcome'
    assert outcome.needs_human
    assert not side_effects          # 副作用没有发生，也没有被擅自重放


def test_effectful_unknown_outcome_can_be_approved_explicitly(runtime, port):
    """人点头之后才允许重放 —— 而且这次重放要留痕。"""
    key = runtime.idempotency_key('s1', 0, 'pay', {'amount': 1})
    runtime.record_tool_intent(_intent('s1', 0, 'pay', key, EFFECT_EFFECTFUL))

    resumed = ManagedRuntime(port, session_id='s1')
    resumed.resume()
    side_effects = []
    outcome = resumed.execute_tool(tool='pay', args={'amount': 1},
                                   fn=lambda: side_effects.append(1) or 'paid',
                                   effect=EFFECT_EFFECTFUL, approved=True)
    assert outcome.status == 'executed'
    assert len(side_effects) == 1
    assert resumed.pending_effectful_calls() == []


def test_pure_tool_with_unknown_outcome_is_replayable(runtime, port):
    """pure / idempotent 的在途调用可以安全重放。"""
    key = runtime.idempotency_key('s1', 0, 'search', {'q': 'x'})
    runtime.record_tool_intent(_intent('s1', 0, 'search', key, EFFECT_PURE))

    plan = recover(port, 's1')
    assert not plan.has_unknown_outcomes
    assert [item.tool for item in plan.replayable] == ['search']


def test_effectful_error_is_treated_as_unknown(runtime, port):
    """effectful 抛异常 → 保守标记为结果未知（可能已经改了一半）。"""
    def boom() -> None:
        raise RuntimeError('network died after send')

    outcome = runtime.execute_tool(tool='pay', args={}, fn=boom,
                                   effect=EFFECT_EFFECTFUL)
    assert outcome.status == 'failed'
    assert runtime.pending_effectful_calls()[0].reason == 'tool_error'


def test_effect_levels_are_classified_conservatively():
    assert normalize_effect('pure') == EFFECT_PURE
    assert normalize_effect('idempotent') == EFFECT_IDEMPOTENT
    assert normalize_effect('effectful') == EFFECT_EFFECTFUL
    # 未知 / 缺失 → 按 effectful 处理（fail-safe）
    assert normalize_effect('wat') == EFFECT_EFFECTFUL
    assert normalize_effect(None) == EFFECT_EFFECTFUL
    assert normalize_effect('') == EFFECT_EFFECTFUL
    assert is_replay_safe(EFFECT_PURE) is True
    assert is_replay_safe(EFFECT_IDEMPOTENT) is True
    assert is_replay_safe(EFFECT_EFFECTFUL) is False
    assert is_replay_safe('wat') is False


# ── 与 harness 的互操作 ────────────────────────────────

def test_record_tool_intent_accepts_harness_tool_intent(runtime, port):
    """Kernel 侧传 harness.runtime_client.ToolIntent，运行时照样能记。"""
    from harness.runtime_client import ToolIntent

    key = idempotency_key('s1', 0, 'pay', {'amount': 1})
    intent = ToolIntent(session_id='s1', turn_seq=0, tool='pay',
                        tool_version='2.0', idempotency_key=key,
                        effect='effectful', args_digest='abc', created_at=1.0)
    runtime.record_tool_intent(intent)

    events = [e for e in Journal(port).events('s1') if e.kind == 'tool_intent']
    assert len(events) == 1
    assert events[0].payload['tool'] == 'pay'
    assert events[0].payload['tool_version'] == '2.0'
    assert events[0].payload['effect'] == 'effectful'
    assert events[0].idempotency_key == key


def test_recovery_after_restart_does_not_reexecute_pure_tool(runtime, port):
    """恢复后再次投递同一个 pure 调用 → 复用结果，**不重复执行**。"""
    side_effects = []

    def calc() -> int:
        side_effects.append(1)
        return 42

    runtime.execute_tool(tool='calc', args={'x': 1}, fn=calc, effect=EFFECT_PURE)

    # 模拟进程重启：换一个运行时实例，内存里什么都没有
    resumed = ManagedRuntime(port, session_id='s1')
    plan = resumed.resume()
    assert plan.unknown_outcomes == []
    assert plan.replayable == []

    outcome = resumed.execute_tool(tool='calc', args={'x': 1}, fn=calc,
                                   effect=EFFECT_PURE)
    assert outcome.status == 'reused'
    assert outcome.result == 42
    assert len(side_effects) == 1


def test_checkpoint_prune_keeps_latest(store, port):
    store_cps = CheckpointStore(port)
    for turn_seq in range(4):
        store_cps.write('s1', turn_seq, {'n': turn_seq})
    removed = store_cps.prune('s1', keep=1)
    assert removed == 3
    assert len(store_cps.list('s1')) == 1


def test_checkpoint_prune_is_optional_for_ports_without_it():
    """端口没实现可选扩展时，prune 只是什么都不做（不能抛）。"""
    class _Bare:
        def put_checkpoint(self, checkpoint): ...
        def load_checkpoint(self, session_id, turn_seq=None): return None
        def list_checkpoints(self, session_id): return []

    assert CheckpointStore(_Bare()).prune('s1') == 0


def test_record_tool_intent_refuses_pending_effectful_replay(runtime, port):
    """即使调用方绕过 execute_tool，执行前那道门也会拦住重复副作用。"""
    from infra.runtime import UnknownOutcomeError

    key = runtime.idempotency_key('s1', 0, 'pay', {'amount': 1})
    runtime.record_tool_intent(_intent('s1', 0, 'pay', key, EFFECT_EFFECTFUL))

    with pytest.raises(UnknownOutcomeError) as excinfo:
        runtime.record_tool_intent(_intent('s1', 0, 'pay', key, EFFECT_EFFECTFUL))
    assert excinfo.value.unknown.tool == 'pay'


def test_record_tool_intent_allows_pending_pure_replay(runtime, port):
    """pure / idempotent 的在途调用可以安全重放 —— 不拦。"""
    key = runtime.idempotency_key('s1', 0, 'search', {'q': 'x'})
    runtime.record_tool_intent(_intent('s1', 0, 'search', key, EFFECT_PURE))
    runtime.record_tool_intent(_intent('s1', 0, 'search', key, EFFECT_PURE))
    intents = [e for e in Journal(port).events('s1') if e.kind == 'tool_intent']
    assert len(intents) == 2      # 重放会留下第二条 intent（事实不可改写）


def test_record_tool_intent_after_completed_call_is_allowed(runtime, port):
    """已经完成的调用再写一次 intent 不该被拦（结果存在 → 不算在途）。"""
    key = runtime.idempotency_key('s1', 0, 'pay', {'amount': 1})
    runtime.execute_tool(tool='pay', args={'amount': 1}, fn=lambda: 'paid',
                         effect=EFFECT_EFFECTFUL)
    # 结果已落 journal + 缓存 → 没有在途 intent → 不抛
    runtime.record_tool_intent(_intent('s1', 0, 'pay', key, EFFECT_EFFECTFUL))


def test_unknown_outcome_error_carries_cross_layer_marker(runtime, port):
    """跨层识别标记：两侧的异常类都必须带 ``unknown_outcome``。

    infra 不能 import harness（依赖规则），所以跨层只能靠**属性标记**互相认出。
    认不出时上层按「拒绝」处理（安全默认）—— 所以这个标记必须两侧都在。
    """
    from infra.runtime import UnknownOutcomeError
    from harness.runtime_client import UnknownOutcomeError as HarnessUnknownOutcomeError

    assert getattr(UnknownOutcomeError, 'unknown_outcome', False) is True
    assert getattr(HarnessUnknownOutcomeError, 'unknown_outcome', False) is True

    key = runtime.idempotency_key('s1', 0, 'pay', {'amount': 1})
    runtime.record_tool_intent(_intent('s1', 0, 'pay', key, EFFECT_EFFECTFUL))
    with pytest.raises(UnknownOutcomeError) as excinfo:
        runtime.record_tool_intent(_intent('s1', 0, 'pay', key, EFFECT_EFFECTFUL))
    assert getattr(excinfo.value, 'unknown_outcome', False) is True
    assert excinfo.value.unknown.tool == 'pay'


# ── 恢复流程 ──────────────────────────────────────────

def test_recovery_resumes_the_unfinished_turn(runtime, port):
    runtime.start_turn(1, input={'q': 'second'})
    plan = recover(port, 's1')
    assert plan.resume_turn_seq == 1
    assert plan.pending_turn is not None
    assert plan.pending_turn.seq == 1


def test_recovery_keeps_awaiting_approval_turn(runtime, port):
    """策划案 §8.2 用例 3：审批期间进程退出 → 重启后仍是 awaiting_approval。"""
    from infra.runtime import TurnStatus

    turn = runtime.start_turn(2, input={'q': 'needs approval'})
    turn.status = TurnStatus.AWAITING_APPROVAL.value
    port.upsert_turn(turn)

    plan = recover(port, 's1')
    assert plan.resume_turn_seq == 2
    assert plan.pending_turn.status == TurnStatus.AWAITING_APPROVAL.value


def test_recovery_replays_journal_after_checkpoint(runtime, port):
    runtime.emit('custom', {'n': 1})
    runtime.checkpoint({'state': 'x'})
    runtime.emit('custom', {'n': 2})
    runtime.emit('custom', {'n': 3})

    plan = recover(port, 's1')
    replayed = [event.payload.get('n') for event in plan.events
                if event.kind == 'custom']
    assert replayed == [2, 3]          # 检查点之前的不重放
    assert plan.checkpoint is not None


def test_resume_emits_session_resumed_event(runtime, port):
    resumed = ManagedRuntime(port, session_id='s1')
    resumed.resume()
    kinds = [event.kind for event in Journal(port).events('s1')]
    assert 'session_resumed' in kinds


def test_resume_reseeds_cache_from_journal(runtime, port):
    """缓存表整个丢了，恢复后仍然复用旧结果（不重复副作用）。"""
    runtime.execute_tool(tool='calc', args={'x': 1}, fn=lambda: 42,
                         effect=EFFECT_PURE)
    key = runtime.idempotency_key('s1', 0, 'calc', {'x': 1})
    conn = port._store.get_connection()
    conn.execute('DELETE FROM tool_result_cache')
    conn.commit()

    resumed = ManagedRuntime(port, session_id='s1')
    resumed.resume()
    assert resumed.lookup_tool_result(key) == 42


# ── 端口与协议 ────────────────────────────────────────

def test_sqlite_runtime_store_implements_store_port(port):
    assert isinstance(port, StorePort)


def test_managed_runtime_implements_runtime_client_protocol(runtime):
    from harness.runtime_client import RuntimeClient

    assert isinstance(runtime, RuntimeClient)


def test_managed_runtime_idempotency_key_matches_protocol(runtime):
    assert runtime.idempotency_key('s1', 0, 'calc', {'a': 1}) == \
        idempotency_key('s1', 0, 'calc', {'a': 1})


def test_di_container_still_importable_from_package():
    """infra/runtime.py → infra/runtime/di.py 迁移后，历史 API 不能变。"""
    from infra.runtime import Runtime

    container = Runtime(name='x')
    container.register('svc', 1)
    assert container.resolve('svc') == 1


def test_multiple_processes_append_without_seq_collision(tmp_path):
    """多个进程同时往同一个 journal 追加，seq 不能撞车。"""
    db = str(tmp_path / 'multi.db')
    writer = textwrap.dedent(f'''
        import os, sys
        sys.path.insert(0, {os.getcwd()!r})
        from infra.store.sqlite import SqliteStore
        from infra.runtime import ManagedRuntime, SqliteRuntimeStore, migrate_runtime
        store = SqliteStore({db!r})
        migrate_runtime(store)
        rt = ManagedRuntime(SqliteRuntimeStore(store), session_id='s1')
        for i in range(10):
            rt.emit('custom', {{'pid': os.getpid(), 'i': i}})
        store.close()
    ''')
    procs = [subprocess.Popen([sys.executable, '-c', writer],
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL)
             for _ in range(3)]
    for proc in procs:
        assert proc.wait(timeout=60) == 0

    store = SqliteStore(db)
    events = Journal(SqliteRuntimeStore(store)).events('s1')
    seqs = [event.seq for event in events]
    assert len(seqs) == 30
    assert len(set(seqs)) == 30          # 没有撞车
    assert seqs == sorted(seqs)           # 单调
    store.close()


# ── 跨进程崩溃（真正的 kill -9 等价物）──────────────────

def test_process_crash_leaves_intent_and_recovery_refuses_to_replay(tmp_path):
    """子进程写到 intent 就被硬杀（os._exit，不做清理）→ 重启后 effectful 不重放。"""
    db = str(tmp_path / 'crash.db')
    child = textwrap.dedent(f'''
        import os, sys
        sys.path.insert(0, {os.getcwd()!r})
        from infra.store.sqlite import SqliteStore
        from infra.runtime import (ManagedRuntime, SqliteRuntimeStore,
                                   migrate_runtime, idempotency_key)
        store = SqliteStore({db!r})
        migrate_runtime(store)
        rt = ManagedRuntime(SqliteRuntimeStore(store), session_id='s1')
        rt.start_turn(0)
        key = idempotency_key('s1', 0, 'pay', {{'amount': 1}})
        rt.record_tool_intent(type('I', (), dict(
            session_id='s1', turn_seq=0, tool='pay', tool_version='1.0',
            idempotency_key=key, effect='effectful', args_digest='d',
            created_at=0.0))())
        os._exit(9)          # 模拟 kill -9：不做任何清理
    ''')
    proc = subprocess.run([sys.executable, '-c', child], capture_output=True)
    assert proc.returncode == 9, proc.stderr.decode('utf-8', 'replace')

    store = SqliteStore(db)
    port = SqliteRuntimeStore(store)
    plan = recover(port, 's1')
    assert [item.tool for item in plan.unknown_outcomes] == ['pay']

    resumed = ManagedRuntime(port, session_id='s1')
    resumed.resume()
    side_effects = []
    outcome = resumed.execute_tool(tool='pay', args={'amount': 1},
                                   fn=lambda: side_effects.append(1),
                                   effect=EFFECT_EFFECTFUL)
    assert outcome.status == 'unknown_outcome'
    assert not side_effects
    store.close()


# ── 辅助 ──────────────────────────────────────────────

def _intent(session_id: str, turn_seq: int, tool: str, key: str,
            effect: str):
    """构造一个鸭子类型的工具意图（字段与 harness 的 ToolIntent 一致）。"""
    return type('Intent', (), dict(
        session_id=session_id, turn_seq=turn_seq, tool=tool,
        tool_version='1.0', idempotency_key=key, effect=effect,
        args_digest='deadbeef', created_at=0.0))()
