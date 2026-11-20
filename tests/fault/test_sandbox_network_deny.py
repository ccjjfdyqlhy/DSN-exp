# tests/fault/test_sandbox_network_deny.py
# 策划案 §8.2 用例 5：沙箱内出网到非 allowlist 域名 → 被拦并记 `net:deny`
#
# 【这条用例证明什么】
#   沙箱管住了文件，不等于管住了网络。
#   一个能出网的 agent 可以把工作区里的东西 POST 出去 ——
#   这是数据外泄最直接的一条路，也是 §4.4.6 把「网络」单独列成一行的原因。
#
#   期望的行为：
#     * network='allowlist' 时，指向**非白名单域名**的命令被拦；
#     * 拦截原因记成 `net:deny`（稳定契约，可追溯：想连哪、为什么不行）；
#     * 命令**没有真的执行**（不是执行了才失败）。
#
#   【restricted 档的能力边界，必须说在前面】
#   restricted 没有内核级断网（那是 namespaced 档的活）。它拦的是
#   「命令行里写明的出网目标」。命令自己 import socket 直连 IP 是拦不住的 ——
#   所以 restricted 永远 degraded=True，**不假装自己是防火墙**。
#   这条用例验的是「写明的出网目标会被拦」，不是「沙箱是道墙」。
#
#   【跳过条件】
#   沙箱后端不可用时本文件整体 skip，原因写在 SANDBOX_MISSING_REASON 里，
#   不做「悄悄跳过」；另有一条硬断言（test_restricted_backend_is_available）
#   保证「后端整个没了」这件事不会显示成绿色。

from __future__ import annotations

import asyncio

import pytest

from aicf.harness.tools.sandbox.base import SandboxRequest
from aicf.harness.tools.sandbox.restricted import VIOLATION_NET_DENY

from faultkit import SANDBOX_MISSING_REASON, sandbox_backend

pytestmark = pytest.mark.fault


#: 白名单里的域名（RFC 2606 保留域，永远不会真的连到公网）
ALLOWED_DOMAIN = 'allowed.example'
FORBIDDEN_DOMAIN = 'not-allowed.invalid'


requires_sandbox = pytest.mark.skipif(
    sandbox_backend() is None,
    reason=SANDBOX_MISSING_REASON)


def _request(cmd, network: str) -> SandboxRequest:
    workspace = _workspace()
    return SandboxRequest(
        cmd=list(cmd),
        workspace_id='ws-1',
        cwd=str(workspace),
        writable_paths=(str(workspace),),
        readonly_paths=(str(workspace),),
        network=network,
        timeout=10.0,
    )


def _workspace():
    """每次调用都新建一个空工作区（沙箱按 cwd 判定路径边界）。"""
    import tempfile
    from pathlib import Path

    path = Path(tempfile.mkdtemp(prefix='fault-net-'))
    return path


def test_restricted_backend_is_available():
    """沙箱后端必须可用 —— 不可用时这里**直接失败**（不是 skip）。

    没有这条，下面几条全跳过时整个文件会显示成绿色，
    看起来「通过」但其实什么都没验证。
    """
    backend = sandbox_backend()
    assert backend is not None, (
        '沙箱后端不可用：harness/tools/sandbox/restricted.py 应当提供 '
        'RestrictedSandbox')


# ── 5a：非白名单域名被拦 ──────────────────────────────

@requires_sandbox
def test_network_to_non_allowlisted_domain_is_denied():
    """期望：指向非白名单域名的命令被拦，violation 记成 net:deny。

    实际：如果只是「执行了但失败」（比如 DNS 解析不了），
          那不叫拦截 —— 换个能连通的域名就出去了。
          所以必须断言 **violation 是 net:deny** 且 **命令没成功**。
    """
    backend = sandbox_backend(network_allowlist=(ALLOWED_DOMAIN,))
    request = _request(['curl', '-s', '-m', '5',
                        f'http://{FORBIDDEN_DOMAIN}/collect'], 'allowlist')

    result = asyncio.run(backend.run(request))

    assert result.violation == VIOLATION_NET_DENY, (
        f'期望 violation={VIOLATION_NET_DENY}，实际 {result.violation!r} '
        f'（stderr={result.stderr!r}）')
    assert result.exit_code != 0, '被拦的命令不该是成功状态'
    assert FORBIDDEN_DOMAIN not in result.stdout
    # 拦截原因要写清楚「拦的是哪个域名」—— 否则审计记录没有可操作性
    assert FORBIDDEN_DOMAIN in result.stderr, (
        f'拦截原因里应当点名域名，实际 {result.stderr!r}')


@requires_sandbox
def test_network_none_blocks_outgoing_traffic():
    """network='none' 时任何出网都不该放行（最严格档）。

    语义是「不许出网」，不是一个域名一个域名地核 ——
    即便命令没写域名（`curl` 裸跑）也拒。
    """
    backend = sandbox_backend()
    request = _request(['curl', '-s', '-m', '5',
                        f'http://{ALLOWED_DOMAIN}/'], 'none')

    result = asyncio.run(backend.run(request))
    assert result.violation == VIOLATION_NET_DENY, (
        f'期望 violation={VIOLATION_NET_DENY}，实际 {result.violation!r}')
    assert result.exit_code != 0


@requires_sandbox
def test_network_command_without_resolvable_target_is_denied():
    """用了网络命令但看不出目标域名 → 拒绝。

    因为「看不出目标」就等于「没法核对白名单」——
    这时放行就是给了一条绕过白名单的旁路。
    """
    backend = sandbox_backend(network_allowlist=(ALLOWED_DOMAIN,))
    request = _request(['curl'], 'allowlist')

    result = asyncio.run(backend.run(request))
    assert result.violation == VIOLATION_NET_DENY, (
        f'期望 violation={VIOLATION_NET_DENY}，实际 {result.violation!r}')


# ── 5b：反向校验 —— 白名单内的域名不能被误伤 ──────────

@requires_sandbox
def test_allowlisted_domain_is_not_blocked():
    """白名单里的域名**不能**被拦。

    实际：一条「全拦」的策略也满足上一条用例，但等于把 agent 的
          所有联网能力都砍了 —— 安全机制变成功能缺陷，同样是缺陷。
    """
    backend = sandbox_backend(network_allowlist=(ALLOWED_DOMAIN,))
    # 用 echo 而不是 curl：域名判定照样触发，但命令本身不联网，
    # 测试就不依赖外网（CI 里通常没有外网）。
    request = _request(['echo', f'http://{ALLOWED_DOMAIN}/ok'], 'allowlist')

    result = asyncio.run(backend.run(request))
    assert result.violation == '', (
        f'白名单内的域名被误伤了：violation={result.violation!r} '
        f'stderr={result.stderr!r}')
    assert result.exit_code == 0, (
        f'期望命令成功，实际 exit_code={result.exit_code} '
        f'stderr={result.stderr!r}')


@requires_sandbox
def test_empty_allowlist_denies_everything():
    """白名单为空 = 一个域名都不放行（默认拒绝）。

    「没配白名单」最容易被实现成「不限制」—— 那正好是最危险的默认值。
    """
    backend = sandbox_backend()
    request = _request(['echo', f'http://{ALLOWED_DOMAIN}/ok'], 'allowlist')

    result = asyncio.run(backend.run(request))
    assert result.violation == VIOLATION_NET_DENY, (
        f'空白名单应当全拒，实际 violation={result.violation!r}')


# ── 5c：被拦必须留下审计痕迹 ──────────────────────────

@requires_sandbox
def test_denied_network_leaves_an_audit_trail():
    """被拦必须留下审计痕迹 —— 拦了但不记，等于没拦。

    走完整链路：ToolGuard（工具调用的唯一入口）→ 沙箱 → 审计。
    工具按契约从 ToolContext 拿沙箱（由守卫注入），
    被拒后返回失败结果，守卫必须把它记成一次 audit.tool_call。
    """
    from aicf.harness.policy.base import PolicyRule
    from aicf.harness.runtime_client import NullRuntimeClient
    from aicf.harness.tools.base import Tool, ToolResult
    from aicf.harness.tools.context import current_context
    from aicf.harness.tools.guard import ToolGuard
    from aicf.harness.tools.spec import ToolSpec
    from aicf.infra.policy.engine import RulePolicyEngine

    class Collector:
        def __init__(self):
            self.events: list[tuple[str, dict]] = []

        def emit(self, kind, payload):
            self.events.append((kind, payload))

        def of(self, kind):
            return [payload for k, payload in self.events if k == kind]

    class SandboxShell(Tool):
        """按契约使用沙箱的工具（沙箱由守卫注入到 ToolContext）。"""

        def __init__(self):
            super().__init__(name='shell', description='run a command',
                             handler=self._run,
                             spec=ToolSpec(name='shell', effect='pure',
                                           sandbox='workspace'))
            self.violation = ''

        async def _run(self, cmd):
            sandbox = current_context().sandbox
            assert sandbox is not None, '守卫没有注入沙箱'
            request = SandboxRequest(
                cmd=list(cmd), cwd=str(_workspace()),
                writable_paths=(str(_workspace()),),
                readonly_paths=(str(_workspace()),),
                network='allowlist', timeout=10.0)
            result = await sandbox.run(request)
            self.violation = result.violation
            if result.violation:
                return ToolResult.fail(
                    f'sandbox denied: {result.violation}',
                    data={'violation': result.violation})
            return ToolResult.ok(result.stdout)

    collector = Collector()
    tool = SandboxShell()
    guard = ToolGuard(
        policy=RulePolicyEngine(rules=[PolicyRule(action='allow',
                                                   tool='shell')]),
        sandbox=sandbox_backend(network_allowlist=(ALLOWED_DOMAIN,)),
        telemetry=collector,
        runtime=NullRuntimeClient(),
        session_id='s1',
    )

    result = asyncio.run(guard.execute(
        tool, {'cmd': ['curl', '-s', f'http://{FORBIDDEN_DOMAIN}/collect']}))

    assert result.result.success is False, '出网的命令不能成功'
    assert tool.violation == VIOLATION_NET_DENY, (
        f'期望 violation={VIOLATION_NET_DENY}，实际 {tool.violation!r}')

    audits = collector.of('audit.tool_call')
    assert audits, f'被拦的调用没有留下审计记录：{collector.events}'
    assert audits[0].get('outcome') == 'error', (
        f'审计里应当记成 error，实际 {audits[0]}')
