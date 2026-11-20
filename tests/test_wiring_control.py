# Wiring W5: the control plane's second half finally has consumers.
#   - identity reaches the audit trail (guard emits agent_id, not just uid);
#   - the decision gate slot refuses before execution when it says no;
#   - cost ledger rows land on every run and `aicf artifact cost` reads them;
#   - gate FAIL feeds the badcase intake, and --from-badcases turns labelled
#     rows back into a regression dataset.

import asyncio
import json
from pathlib import Path

from aicf.harness.cli.main import main as cli_main


def make_guard(tmp_path: Path, *, identity=None, decision_gate=None):
    from aicf.harness.tools.base import ToolRegistry
    from aicf.harness.tools.guard import ToolGuard
    from aicf.harness.tools.registry import ManagedToolRegistry
    from aicf.infra.observability.audit import AuditLog
    from aicf.infra.policy.engine import RulePolicyEngine

    registry = ManagedToolRegistry()
    guard = ToolGuard(policy=RulePolicyEngine(), identity=identity,
                      decision_gate=decision_gate, audit=AuditLog(),
                      session_id='w5')
    registry.attach_guard(guard)
    return registry, guard


def test_identity_reaches_the_audit_trail(tmp_path: Path):
    from aicf.harness.tools.function_tool import tool_from_function
    from aicf.harness.tools.spec import ToolSpec
    from aicf.infra.control.identity import AgentIdentity

    t = tool_from_function(lambda: 'ok', name='fs.read')
    t.spec = ToolSpec(name='fs.read', effect='pure')
    registry, guard = make_guard(tmp_path,
                              identity=AgentIdentity(agent_id='bot-1',
                                                     delegated_by='user'))
    registry.attach_guard(guard)
    registry.register(t)
    result = asyncio.run(registry.execute_async('fs.read', {}))
    assert result.success

    store = guard.audit.store  # the same append-only store the guard wrote to
    records = [r for r in store.of_kind('audit.tool_call')
               if getattr(r, 'payload', {}).get('identity') == 'bot-1']
    assert records, 'the audit record must carry the agent identity'


def test_decision_gate_refuses_before_execution():
    calls = []

    class RefusingGate:
        def check(self, *, tool, args, spec=None):
            return {'allow': False, 'reason': 'not right now'}

    t = _note_tool(calls)
    registry, guard = make_guard(Path('/tmp'), decision_gate=RefusingGate())
    registry.attach_guard(guard)
    registry.register(t)
    result = asyncio.run(registry.execute_async('note_something', {'text': 'x'}))
    assert not result.success
    assert calls == []  # refused before the tool ran


def _note_tool(calls):
    from aicf.harness.tools.function_tool import tool_from_function
    from aicf.harness.tools.spec import ToolSpec

    def note_something(text: str) -> str:
        """Record a note."""
        calls.append(text)
        return 'noted'
    t = tool_from_function(note_something)
    t.spec = ToolSpec(name='note_something', effect='idempotent')
    return t


def test_sdk_decision_gate_blocks_the_tool(tmp_path: Path):
    from aicf.harness import create_agent
    from aicf.harness.cli.common import build_model
    from aicf.infra.orchestrator.base import ChatResponse
    from aicf.infra.orchestrator.stub import StubChatClient

    consults = []

    class Gate:
        def check(self, *, tool, args, spec=None):
            consults.append(tool)
            return {'allow': False, 'reason': 'policy says no'}

    scripted = StubChatClient(responses=[
        ChatResponse(content='', tool_calls=[
            __import__('aicf.infra.orchestrator.base', fromlist=['ToolCall'])
            .ToolCall(id='a', name='note_something', arguments={'text': 'x'})]),
        ChatResponse(content='done'),
    ])
    calls = []
    agent = create_agent(model='stub', client=scripted,
                         tools=[_note_tool(calls)], decision_gate=Gate())
    agent.run('note it')
    assert consults == ['note_something']  # the gate was consulted
    assert calls == []  # and the refusal held


def test_cost_ledger_row_and_artifact_cost_query(tmp_path: Path):
    db = tmp_path / 'db.sqlite'
    code = cli_main(['run', 'cost attribution', '--run-id', 'w5cost',
                     '--db', str(db)])
    assert code == 0
    from aicf.infra.eval.trace_store import TraceStore

    conn = TraceStore(str(db)).get_connection()
    rows = conn.execute(
        "SELECT tokens, cost FROM control_cost_ledger WHERE session_id = 'w5cost'"
    ).fetchall()
    assert rows and rows[0]['tokens'] > 0  # the row exists with real tokens
    code = cli_main(['artifact', 'cost', '--session', 'w5cost', '--db', str(db)])
    assert code == 0


def test_gate_fail_feeds_badcase_and_from_badcases(tmp_path: Path):
    db = tmp_path / 'db.sqlite'
    run_path = tmp_path / 'run.json'
    failing = {
        'run_id': 'r1', 'run_version_id': 'v1', 'dataset_id': 'd',
        'dataset_hash': 'h', 'status': 'failed',
        'started_at': 0.0, 'ended_at': 0.0,
        'results': [{'case_id': 'c1', 'group': 'g', 'critical': True,
                     'passed': False, 'score': 0.0, 'metrics': {},
                     'failed_rules': ['output_nonempty'], 'violations': [],
                     'trace_id': 't1'}],
        'aggregate': {},
    }
    run_path.write_text(json.dumps(failing), encoding='utf-8')
    code = cli_main(['gate', '--run', str(run_path), '--db', str(db)])
    assert code == 1  # the gate failed

    from aicf.infra.eval.trace_store import TraceStore

    store = TraceStore(str(db))
    rows = store.list_badcases(status='new')
    assert len(rows) == 1 and rows[0]['reason'].startswith('gate:c1:')
    store.label_badcase(rows[0]['id'], label='repro',
                        input_text='make this case fail',
                        expect=[{'assert_fn': 'output_nonempty'}])

    out_path = tmp_path / 'run2.json'
    code = cli_main(['eval', '--from-badcases', str(db), '--out', str(out_path)])
    assert code != 0  # no traces yet: the case counts as missing, not passing
    run2 = json.loads(out_path.read_text(encoding='utf-8'))
    assert run2['results'], 'the labelled badcase became a case'
    assert run2['results'][0]['case_id'].startswith('hard_bc_t1_')
