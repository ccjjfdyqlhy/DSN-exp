# tests/test_conversation_state.py
# ManagedConversation: draft-commit history, stable prefixes, compaction.

from __future__ import annotations

import asyncio

import pytest

from harness.conversation import (
    ManagedConversation, PROMPT_VERSION, StablePrefix, TokenBudget,
    TokenBudgetExceeded, messages_need_repair, repair_messages,
    stream_compact, structured_summary,
)


# ── repair_messages ──────────────────────────────────────────────────

def test_repair_synthesizes_missing_tool_results():
    messages = [
        {'role': 'user', 'content': 'hi'},
        {'role': 'assistant', 'content': None,
         'tool_calls': [{'id': 'c1', 'type': 'function',
                         'function': {'name': 'read', 'arguments': '{}'}}]},
    ]
    repaired, changed = repair_messages(messages)
    assert changed == 1
    assert repaired[-1]['role'] == 'tool'
    assert repaired[-1]['tool_call_id'] == 'c1'
    assert 'interrupted' in repaired[-1]['content']


def test_repair_drops_orphan_tool_and_fills_missing_ids():
    messages = [
        {'role': 'tool', 'tool_call_id': 'ghost', 'content': 'x'},
        {'role': 'assistant', 'content': None,
         'tool_calls': [{'type': 'function',
                         'function': {'name': 'ls', 'arguments': '{}'}}]},
    ]
    repaired, changed = repair_messages(messages)
    # orphan dropped + id filled + synthetic result for the filled id
    assert changed == 3
    assert all(m.get('tool_call_id') != 'ghost' for m in repaired)
    assert repaired[0]['tool_calls'][0]['id'] == 'call_repair_0'
    assert repaired[-1]['tool_call_id'] == 'call_repair_0'


def test_messages_need_repair_preflight():
    ok = [{'role': 'user', 'content': 'hi'},
          {'role': 'assistant', 'content': None,
           'tool_calls': [{'id': 'c1', 'type': 'function',
                           'function': {'name': 'read', 'arguments': '{}'}}]},
          {'role': 'tool', 'tool_call_id': 'c1', 'content': 'data'}]
    assert messages_need_repair(ok) is False
    assert messages_need_repair(ok[:2]) is True


# ── StablePrefix ─────────────────────────────────────────────────────

def _prefix(**overrides):
    kwargs = dict(provider='p', endpoint='https://api.example.com/v1/',
                  model='m', system='sys', tools=[], generation=1)
    kwargs.update(overrides)
    return StablePrefix.create(**kwargs)


def test_stable_prefix_fingerprint_stable_and_sensitive():
    base = _prefix()
    assert base.fingerprint.startswith('sha256:')
    assert base.prompt_version == PROMPT_VERSION == 'harness-v1'
    # same inputs, same fingerprint (endpoint slash + system CRLF normalized)
    assert _prefix().fingerprint == base.fingerprint
    assert _prefix(system='other').fingerprint != base.fingerprint
    assert _prefix(provider='q').fingerprint != base.fingerprint
    tool = {'type': 'function', 'function': {'name': 'read', 'parameters': {}}}
    assert _prefix(tools=[tool]).fingerprint != base.fingerprint


# ── ManagedConversation ──────────────────────────────────────────────

def _conversation():
    return ManagedConversation(stable_prefix=_prefix(), committed=[])


def test_stage_commit_rollback():
    conversation = _conversation()
    conversation.stage({'role': 'user', 'content': 'hi'})
    assert conversation.request_messages()[-1]['content'] == 'hi'
    conversation.rollback()
    assert conversation.request_messages() == []
    conversation.stage({'role': 'user', 'content': 'hi'})
    conversation.commit()
    assert conversation.committed[-1]['content'] == 'hi'
    assert conversation.draft == []


def test_estimated_tokens_caches_by_revision():
    conversation = _conversation()
    conversation.stage({'role': 'user', 'content': 'x' * 40})
    first = conversation.estimated_tokens()
    assert conversation.estimated_tokens() == first    # cached
    conversation.stage({'role': 'assistant', 'content': 'y' * 40})
    assert conversation.estimated_tokens() > first     # revision bumped


def test_compaction_plan_groups_and_keeps_recent():
    conversation = _conversation()
    for turn in range(5):
        conversation.stage({'role': 'user', 'content': f'turn {turn} ' + 'x' * 50})
        conversation.stage({'role': 'assistant', 'content': f'reply {turn}'})
    conversation.commit()
    plan = conversation.compaction_plan(target_tokens=120, keep_recent_turns=2)
    assert plan is not None
    removed_users = [m['content'] for m in plan.removed if m['role'] == 'user']
    assert removed_users == [f'turn {turn} ' + 'x' * 50 for turn in (0, 1, 2)]
    kept_users = [m['content'] for m in plan.kept_messages if m['role'] == 'user']
    assert kept_users == [f'turn {turn} ' + 'x' * 50 for turn in (3, 4)]


def test_apply_compaction_bumps_generation_and_archives():
    conversation = _conversation()
    conversation.stage({'role': 'user', 'content': 'old task'})
    conversation.stage({'role': 'assistant', 'content': 'old answer'})
    conversation.stage({'role': 'user', 'content': 'newer task'})
    conversation.stage({'role': 'assistant', 'content': 'newer answer'})
    conversation.commit()
    generation = conversation.stable_prefix.generation
    # a tiny budget with keep_recent_turns=0 still backfills the newest group,
    # so exactly the oldest turn is removed
    plan = conversation.compaction_plan(target_tokens=10, keep_recent_turns=0)
    assert plan is not None and plan.removed
    assert [m['content'] for m in plan.removed if m['role'] == 'user'] == ['old task']
    removed_count = conversation.apply_compaction(
        plan, {'role': 'user',
               'content': '<conversation_summary>\nsummary\n</conversation_summary>'})
    assert removed_count == 2
    assert conversation.stable_prefix.generation == generation + 1
    assert len(conversation.archived) == 2
    assert conversation.committed[0]['content'].startswith('<conversation_summary>')
    # the summary is not a transcript turn (turn_starts skips it), but the
    # kept turn still starts cleanly after it
    from harness.transcript import SessionStore
    assert SessionStore.turn_starts(conversation.committed) == [1]


def test_enforce_budget_trims_then_raises():
    conversation = _conversation()
    conversation.stage({'role': 'user', 'content': 'task'})
    conversation.stage({'role': 'assistant', 'content': None,
                        'tool_calls': [{'id': 'c1', 'type': 'function',
                                        'function': {'name': 'bash',
                                                     'arguments': '{}'}}]})
    conversation.stage({'role': 'tool', 'tool_call_id': 'c1',
                        'content': 'o' * 40_000})
    conversation.commit()
    # this window makes the single turn over budget but not impossible: the
    # oversized tool output gets trimmed, not rejected
    report = conversation.enforce_budget(TokenBudget(context_window=9_000,
                                                     reserved_output=1_000,
                                                     safety_margin=100,
                                                     stable_tokens=0))
    assert report['draft_tokens'] <= 1    # the estimate floors at 1
    trimmed = [m for m in conversation.committed if m.get('role') == 'tool'][0]
    assert '<tool output compacted>' in trimmed['content']
    # an impossible budget raises
    with pytest.raises(TokenBudgetExceeded):
        conversation.enforce_budget(TokenBudget(context_window=10,
                                                reserved_output=5_000,
                                                safety_margin=100))
    conversation.rollback()


# ── compaction via model stream ──────────────────────────────────────

def _stream(texts, fail=False):
    def factory(messages, *, system='', max_tokens=0, tools=None):
        async def gen():
            if fail:
                raise RuntimeError('stream broke')
            for text in texts:
                yield text
        return gen()
    return factory


def test_stream_compact_uses_model_summary():
    conversation = _conversation()
    for turn in range(2):    # two user turns: the newest one is kept
        conversation.stage({'role': 'user', 'content': f'old task {turn} ' + 'x' * 100})
        conversation.stage({'role': 'assistant', 'content': f'old reply {turn}'})
    conversation.commit()
    deltas: list[str] = []
    removed = asyncio.run(stream_compact(
        conversation, 60, _stream(['a durable ', 'summary']),
        emit=deltas.append, keep_recent_turns=0))
    assert removed == 2
    assert deltas == ['a durable ', 'summary']
    assert ('<conversation_summary>\na durable summary\n</conversation_summary>'
            == conversation.committed[0]['content'])


def test_stream_compact_falls_back_deterministically():
    conversation = _conversation()
    for turn in range(2):
        conversation.stage({'role': 'user', 'content': f'the real task {turn}'})
        conversation.stage({'role': 'assistant', 'content': 'progress made'})
    conversation.commit()
    removed = asyncio.run(stream_compact(conversation, 60, _stream([], fail=True),
                                         keep_recent_turns=0))
    assert removed == 2
    body = conversation.committed[0]['content']
    assert body.startswith('<conversation_summary>')
    assert 'the real task 0' in body


def test_stream_compact_without_plan_is_noop():
    conversation = _conversation()
    assert asyncio.run(stream_compact(conversation, 200, _stream(['x']))) == 0


def test_structured_summary_wraps_and_keeps_goal():
    summary = structured_summary([{'role': 'user', 'content': 'build the thing'},
                                  {'role': 'tool', 'content': 'ok tests pass'}])
    assert summary['role'] == 'user'
    assert summary['content'].startswith('<conversation_summary>')
    assert 'build the thing' in summary['content']
    assert 'tests pass' in summary['content']
