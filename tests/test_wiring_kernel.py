# Wiring W4: the kernel SPI stops being a third-full.
#   - the three KernelContext ports (memory/approval/context) get real values
#     on the CLI assembly path, which left them None everywhere before;
#   - the artifact publish validates spec.kernel against the registry, which
#     makes KERNEL_REGISTRY's "serves the control plane" comment true;
#   - workflow_from_dict gets its first tests.

import argparse
from pathlib import Path

import pytest

from aicf.harness.cli.runcmd import _setup_session
from aicf.harness.kernel import WorkflowValidationError, workflow_from_dict
from aicf.harness.kernel.workflow import WorkflowNode


def _args(**overrides):
    base = {'yes': True, 'deny_tool': [], 'include': [], 'db': ':memory:',
            'kernel': 'react'}
    base.update(overrides)
    return argparse.Namespace(**base)


def test_cli_setup_fills_the_three_kernel_ports(tmp_path: Path):
    collector = type('C', (), {'events': []})()
    registry, _kernel_cls, runtime, store, ports = _setup_session(
        _args(db=str(tmp_path / 'db.sqlite')), session_id='w4', collector=collector)
    try:
        assert ports['memory'] is not None
        assert ports['approval'] is not None
        assert ports['context'] is not None
        # the approval port is a working broker, not a placeholder
        import asyncio

        from aicf.harness.approval.base import ApprovalRequest

        decision = asyncio.run(ports['approval'].request(
            ApprovalRequest(tool='file.edit', args_preview='{}')))
        assert decision is not None
    finally:
        store.close()


def test_kernel_ports_end_up_on_the_context(tmp_path: Path):
    from aicf.harness.kernel import KernelContext, ReactKernel

    class C:
        events = []

    registry, kernel_cls, runtime, store, ports = _setup_session(
        _args(db=str(tmp_path / 'db.sqlite')), session_id='w4b', collector=C())
    try:
        ctx = KernelContext(tools=registry, memory=ports['memory'],
                            approval=ports['approval'], context=ports['context'])
        assert ctx.memory is not None and ctx.approval is not None
        assert ctx.context is not None
    finally:
        store.close()


def test_publish_rejects_unknown_kernel(tmp_path: Path):
    from aicf.harness.cli.artifactcmd import validate_kernel_claim

    with pytest.raises(ValueError):
        validate_kernel_claim('multi')  # documented once, never in the registry
    meta = validate_kernel_claim('react')
    assert meta['kernel'] == 'react' and meta['resumable'] is True


def test_workflow_from_dict_parses_and_validates():
    nodes = workflow_from_dict([
        {'name': 'fetch', 'kind': 'tool', 'tool': 'file.read'},
        {'name': 'summarize', 'kind': 'model', 'prompt': 'summarize',
         'depends_on': ['fetch']},
    ])
    assert [n.name for n in nodes] == ['fetch', 'summarize']
    assert nodes[1].depends_on == ['fetch']


def test_workflow_from_dict_rejects_cycles():
    with pytest.raises(WorkflowValidationError):
        workflow_from_dict([
            {'name': 'a', 'kind': 'tool', 'tool': 'file.read',
             'depends_on': ['b']},
            {'name': 'b', 'kind': 'tool', 'tool': 'file.read',
             'depends_on': ['a']},
        ])
