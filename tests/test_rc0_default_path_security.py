# tests/test_rc0_default_path_security.py
# Default path security: the guard has to be attached where users actually run.
#
# Why this file exists: the sandbox, the policy gate and the approval broker
# were all implemented and all tested, but the paths a user takes by default
# (the SDK entry point, proc.run, batch.run) never went through them. A
# capability that only exists in a fixture is not a capability.

from __future__ import annotations

import asyncio

import pytest

from harness.approval.base import ApprovalDecision
from harness.approval.broker import LocalApprovalBroker
from harness.policy.base import PolicyRule
from harness.tools.base import Tool, ToolRegistry, ToolResult
from harness.tools.guard import ToolGuard
from harness.tools.registry import ManagedToolRegistry
from harness.tools.standard import ToolDeps, install_standard_tools


def build_registry(tmp_path, **kwargs) -> ManagedToolRegistry:
    registry = ManagedToolRegistry()
    deps = ToolDeps(workspace=str(tmp_path), **kwargs)
    install_standard_tools(registry, deps=deps)
    return registry


def approving_guard(**kwargs) -> ToolGuard:
    broker = LocalApprovalBroker(
        resolver=lambda request: ApprovalDecision.approve(by='test'),
        timeout=5.0)
    return ToolGuard(approval=broker, **kwargs)


# ── proc.run has to stay inside the workspace ──────────────────────

def test_proc_run_cannot_read_outside_the_workspace(tmp_path):
    """The exploit this file was written for.

    proc.run declared sandbox="workspace" while the handler ran a bare
    subprocess, so the declaration was a lie and any file on the host was
    readable. The guard now attaches a backend, so the boundary is real.
    """
    registry = build_registry(tmp_path)
    registry.attach_guard(approving_guard())

    secret = tmp_path.parent / "secret.txt"
    secret.write_text("classified")

    result = asyncio.run(registry.execute_async(
        "proc.run", {"command": f"cat {secret}"}))

    assert result.success is False
    assert "沙箱拒绝" in (result.error or "")
    assert "classified" not in str(result.output)


def test_proc_run_still_reads_inside_the_workspace(tmp_path):
    registry = build_registry(tmp_path)
    registry.attach_guard(approving_guard())
    (tmp_path / "note.txt").write_text("hello")

    result = asyncio.run(registry.execute_async(
        "proc.run", {"command": "cat note.txt"}))

    assert result.success is True
    assert "hello" in str(result.output)


def test_proc_run_traversal_is_blocked(tmp_path):
    registry = build_registry(tmp_path)
    registry.attach_guard(approving_guard())
    (tmp_path / "inside.txt").write_text("inside")

    result = asyncio.run(registry.execute_async(
        "proc.run", {"command": "cat ../inside.txt"}))

    assert result.success is False


def test_sandbox_denial_marks_the_call_failed(tmp_path):
    """A blocked call is not a successful call.

    The tool payload may still say success, so the guard decides what the
    caller sees.
    """
    registry = build_registry(tmp_path)
    registry.attach_guard(approving_guard())

    result = asyncio.run(registry.execute_async(
        "proc.run", {"command": "cat /etc/passwd"}))

    assert result.success is False
    assert result.status == "error"


# ── the SDK path has to be guarded too ──────────────────────────────

def test_sdk_path_attaches_a_guard(tmp_path):
    from harness import create_agent
    from infra.models.stub import StubChatClient

    agent = create_agent(client=StubChatClient(responses=[]),
                         tools="standard",
                         workspace=str(tmp_path))

    assert isinstance(agent.tools, ManagedToolRegistry)
    assert agent.tools.guard is not None
    assert agent.tools.guard.sandbox is not None


def test_sdk_path_sandboxes_proc_run(tmp_path):
    from harness import create_agent
    from infra.models.stub import StubChatClient

    agent = create_agent(client=StubChatClient(responses=[]),
                         tools="standard",
                         workspace=str(tmp_path))
    secret = tmp_path.parent / "sdk_secret.txt"
    secret.write_text("classified")

    result = asyncio.run(agent.tools.execute_async(
        "proc.run", {"command": f"cat {secret}"}))

    assert result.success is False
    assert "classified" not in str(result.output)


# ── batch.run must not be a way around the guard ───────────────────

def test_batch_run_goes_through_the_guard(tmp_path):
    """batch.run used to call the tool handler directly.

    That skipped the policy, the approval, the sandbox and the audit, so
    batch.run(fn='proc.run') was a side door into the host.
    """
    from infra.policy.engine import RulePolicyEngine

    registry = ManagedToolRegistry()
    deps = ToolDeps(workspace=str(tmp_path), tool_registry=registry)
    install_standard_tools(registry, deps=deps)

    engine = RulePolicyEngine(rules=[
        PolicyRule(action='deny', tool='file.read', id='deny-read')])
    registry.attach_guard(approving_guard(policy=engine))

    result = asyncio.run(registry.execute_async(
        "batch.run", {"items": [{"path": "a.txt"}], "fn": "file.read"}))

    payload = result.output
    assert payload["ok"] == 0
    assert payload["results"][0]["success"] is False


# ── the guard has to carry the contract into the tool ──────────────

def test_guard_injects_the_tool_spec(tmp_path):
    """A tool can only honour its declared network level if it can read it.

    The spec travels in the tool context, otherwise every backend saw
    network='none' and the allowlist never applied.
    """
    seen: list = []

    class Probe(Tool):
        def __init__(self):
            super().__init__(name="probe", description="reads its spec",
                             handler=self._run)

        async def _run(self):
            from harness.tools.context import current_context
            spec = getattr(current_context(), "tool_spec", None)
            seen.append(getattr(spec, "network", None))
            return ToolResult.ok("done")

    registry = ManagedToolRegistry()
    registry.register(Probe())
    registry.attach_guard(approving_guard())

    asyncio.run(registry.execute_async("probe", {}))

    assert seen and seen[0] is not None


def test_audit_digest_describes_the_real_arguments(tmp_path):
    """The digest used to be a constant, so the audit could not tell two
    calls apart.
    """
    events: list = []

    class Collector:
        def emit(self, kind, payload):
            events.append((kind, payload))

    registry = build_registry(tmp_path)
    registry.attach_guard(approving_guard(telemetry=Collector()))

    asyncio.run(registry.execute_async("file.write",
                                        {"path": "a.txt", "content": "one"}))
    asyncio.run(registry.execute_async("file.write",
                                        {"path": "b.txt", "content": "two"}))

    digests = [payload.get("args_digest")
               for kind, payload in events if kind == "audit.tool_call"]
    assert len(digests) == 2
    assert digests[0] != digests[1]


# ── the sync entry points have to carry async handlers ─────────────

def test_tool_run_bridges_an_async_handler():
    """Tool.run used to refuse an async handler.

    The synchronous entry points (registry.execute, batch.run) are part of
    the public surface, so a tool that needs the event loop broke them.
    """
    async def handler(value: int) -> int:
        return value * 2

    tool = Tool(name="double", description="doubles", handler=handler)

    result = tool.run(value=21)

    assert result.success is True
    assert result.output == 42


def test_registry_execute_runs_an_async_handler():
    registry = ManagedToolRegistry()

    async def handler(value: int) -> int:
        return value + 1

    registry.register(Tool(name="inc", description="d", handler=handler))

    text, _, failed = registry.execute("inc", {"value": 1})

    assert failed is False
    assert "2" in text


@pytest.mark.parametrize("mode", ["strict", "legacy"])
def test_security_mode_reads_the_environment(mode, monkeypatch):
    from harness.tools.guard import default_security_mode

    monkeypatch.setenv("AICF_SECURITY_MODE", mode)
    assert default_security_mode() == mode

    monkeypatch.setenv("AICF_SECURITY_MODE", "nonsense")
    assert default_security_mode() == "strict"
