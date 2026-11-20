# tests/test_rc0_cli_session.py
# The session commands are the only user facing view of the managed runtime.
#
# `aicf session resume` used to call a method that does not exist, so the
# documented way to inspect a crashed run was broken. These tests pin the
# behaviour that the docs promise.

from __future__ import annotations

import json
import sqlite3

import pytest

from aicf.harness.cli.main import main


def _run(argv, capsys):
    code = main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _runtime_with_a_half_done_call(db_path):
    """A session whose effectful tool has an intent but no result.

    That is the state a crash leaves behind: the side effect happened, the
    result was never written.
    """
    from aicf.infra.runtime import (EFFECT_EFFECTFUL, ManagedRuntime,
                               SqliteRuntimeStore, migrate_runtime)
    from aicf.infra.store.sqlite import SqliteStore

    store = SqliteStore(str(db_path))
    migrate_runtime(store)
    runtime = ManagedRuntime(SqliteRuntimeStore(store), session_id='s-crash')
    runtime.start_session(session_id='s-crash')
    runtime.start_turn(0, input={'q': 'pay the bill'})
    runtime.record_tool_intent(_intent('pay', EFFECT_EFFECTFUL))
    store.close()
    return db_path


def _intent(tool: str, effect: str):
    from aicf.harness.runtime_client import ToolIntent

    return ToolIntent(session_id='s-crash', turn_seq=0, tool=tool,
                      tool_version='1.0', idempotency_key='key-' + tool,
                      effect=effect, args_digest='sha256:x:len=1',
                      created_at=0.0)


def test_session_resume_reports_the_unknown_outcome(tmp_path, capsys):
    db_path = _runtime_with_a_half_done_call(tmp_path / 'runtime.db')

    code, out, _err = _run(['session', 'resume', 's-crash',
                             '--db', str(db_path)], capsys)

    assert code == 0
    assert '结果未知' in out
    assert 'pay' in out


def test_session_resume_json_lists_the_unknown_call(tmp_path, capsys):
    db_path = _runtime_with_a_half_done_call(tmp_path / 'runtime.db')

    code, out, _err = _run(['session', 'resume', 's-crash',
                             '--db', str(db_path), '--json'], capsys)

    assert code == 0
    payload = json.loads(out)
    assert payload['session_id'] == 's-crash'
    assert [item['tool'] for item in payload['unknown_outcomes']] == ['pay']


def test_session_resume_does_not_write_to_the_journal(tmp_path, capsys):
    """Looking at the recovery state must stay a pure read."""
    db_path = _runtime_with_a_half_done_call(tmp_path / 'runtime.db')

    before = _event_count(db_path)
    code, _out, _err = _run(['session', 'resume', 's-crash',
                              '--db', str(db_path)], capsys)
    after = _event_count(db_path)

    assert code == 0
    assert before == after


def _event_count(db_path) -> int:
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute('SELECT COUNT(*) FROM runtime_event').fetchone()[0]
    finally:
        conn.close()


def test_session_list_shows_the_session(tmp_path, capsys):
    db_path = _runtime_with_a_half_done_call(tmp_path / 'runtime.db')

    code, out, _err = _run(['session', 'list', '--db', str(db_path)], capsys)

    assert code == 0
    assert 's-crash' in out


def test_run_writes_a_session_to_the_journal(tmp_path, capsys):
    """`aicf run` has to leave a journal behind, otherwise there is
    nothing to resume and nothing to audit.
    """
    import sqlite3

    db_path = tmp_path / 'run.db'
    code, _out, _err = _run(['run', 'hello', '--db', str(db_path),
                              '--trace', str(tmp_path / 'trace.jsonl')],
                             capsys)

    assert code == 0
    conn = sqlite3.connect(str(db_path))
    try:
        sessions = conn.execute(
            'SELECT COUNT(*) FROM runtime_session').fetchone()[0]
        events = conn.execute(
            'SELECT COUNT(*) FROM runtime_event').fetchone()[0]
    finally:
        conn.close()
    assert sessions == 1
    assert events >= 2
