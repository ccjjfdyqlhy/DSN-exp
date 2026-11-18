# tests/test_rc0_sandbox.py
# R3 沙箱后端的契约测试（策划案 §7.1 R3 / §4.4.4）。
#
# 这一层锁住的是**安全语义**，不是实现细节：
#   1. 路径逃逸（../ 穿越、符号链接逃逸）必须被拦，且 violation 非空、退出码非 0
#   2. 出网必须被拦（network=none / allowlist）
#   3. 降级必须**如实标注** —— 没有强隔离后端时 backend='restricted' + degraded=True
#   4. restricted 档：ulimit + 路径白名单 + 环境变量白名单都真的生效
#   5. namespaced 档：探测不到强隔离后端时**不报错**，由上层降级
#
# 「降级必须如实标注」是这一层最重要的断言：
# 策划案 §3.3.5 明确禁止「以为自己在沙箱里」。
# 一个「静默假装隔离」的沙箱比没有沙箱更危险 —— 它让上层以为可以放行。

from __future__ import annotations

import asyncio
import os

import pytest

from harness.tools.sandbox import (
    NamespacedSandbox,
    RestrictedSandbox,
    detect_best_backend,
    detect_capabilities,
)
from harness.tools.sandbox.base import SandboxRequest, SandboxResult
from harness.tools.sandbox.paths import (
    PathPolicy,
    is_within,
    real_path,
    scan_path_violations,
)
from harness.tools.sandbox.restricted import (
    VIOLATION_CMD_DENIED,
    VIOLATION_NET_DENY,
    VIOLATION_PATH_ESCAPE,
    check_network,
    extract_network_targets,
    host_allowed,
)


def run(coro):
    """在同步测试里跑协程。

    修复说明：**不在主线程里用 asyncio.run()**。
    asyncio.run() 结束时会把主线程的「当前事件循环」置空
    （events.set_event_loop(None)），此后任何 asyncio.get_event_loop()
    都会抛 RuntimeError: There is no current event loop in thread 'MainThread'。

    仓库里就有这样的调用：harness/approval/broker.py 的 restore_pending()
    在**协程之外**用 asyncio.get_event_loop().create_future()。
    所以只要本文件先跑过 asyncio.run()，后面那条用例就会炸 ——
    而炸的原因跟审批毫无关系，排查起来极费时间。

    改成在独立线程里跑自己的事件循环：主线程的 loop 策略完全不受影响。

    注意还要把 contextvars **复制进那个线程**：
    线程默认拿到的是空 context，current_context() 会返回另一个上下文 ——
    沙箱记进 ToolContext.violations 的违规就落到别的列表上去了（审计静默丢失）。
    contextvars.copy_context() 复制的是「变量 → 值」的映射，值本身还是同一个
    ToolContext 对象，所以 append 依然能被守卫读到。
    """
    import concurrent.futures
    import contextvars

    ctx = contextvars.copy_context()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(ctx.run, asyncio.run, coro).result()


@pytest.fixture()
def workspace(tmp_path):
    """一个工作区目录（可写）。"""
    return tmp_path


# ── 契约形状 ────────────────────────────────────────────

def test_sandbox_result_ok_property():
    """ok = 退出码为 0 且没有违规。"""
    assert SandboxResult(exit_code=0).ok is True
    assert SandboxResult(exit_code=0, violation='path:escape').ok is False
    assert SandboxResult(exit_code=1).ok is False


def test_restricted_and_namespaced_satisfy_protocol():
    """两个后端都满足 Sandbox 协议（结构化检查）。"""
    from harness.tools.sandbox.base import Sandbox

    for backend in (RestrictedSandbox(), NamespacedSandbox()):
        assert isinstance(backend, Sandbox)
        assert backend.name in ('restricted', 'namespaced')
        assert isinstance(backend.degraded, bool)


def test_detect_best_backend_returns_usable_backend():
    """detect_best_backend 必须返回一个能跑的后端，绝不返回 None。"""
    backend = detect_best_backend()
    assert backend is not None
    assert backend.name in ('restricted', 'namespaced')


# ── 1. 路径逃逸 ──────────────────────────────────────────

def test_parent_traversal_is_blocked(workspace):
    """`../../etc/passwd` 必须在执行前被拦。"""
    result = run(RestrictedSandbox().run(SandboxRequest(
        cmd=['cat', '../../etc/passwd'], cwd=str(workspace))))
    assert result.violation == VIOLATION_PATH_ESCAPE
    assert result.exit_code != 0
    assert 'root:' not in result.stdout


def test_absolute_path_outside_workspace_is_blocked(workspace):
    """绝对路径指向工作区外也要被拦。"""
    result = run(RestrictedSandbox().run(SandboxRequest(
        cmd=['cat', '/etc/passwd'], cwd=str(workspace))))
    assert result.violation == VIOLATION_PATH_ESCAPE
    assert result.exit_code != 0
    assert 'root:' not in result.stdout


def test_symlink_escape_is_blocked(workspace):
    """符号链接逃逸必须被识别 —— 这是只做词法判定时最常见的漏网之鱼。

    `link -> /etc/passwd` 的词法路径在工作区**内**，
    只有 realpath 之后才知道它指向工作区**外**。
    """
    secret = workspace / 'secret.txt'
    secret.write_text('TOPSECRET\n', encoding='utf-8')
    outside = workspace.parent / 'outside-secret.txt'
    outside.write_text('TOPSECRET\n', encoding='utf-8')
    link = workspace / 'link'
    link.symlink_to(outside)

    result = run(RestrictedSandbox().run(SandboxRequest(
        cmd=['cat', 'link'], cwd=str(workspace))))
    assert result.violation == VIOLATION_PATH_ESCAPE
    assert result.exit_code != 0
    assert 'TOPSECRET' not in result.stdout


def test_write_to_readonly_area_is_blocked(workspace):
    """往只读区域写要被拦（path:denied）。"""
    readonly = workspace / 'ro'
    readonly.mkdir()
    result = run(RestrictedSandbox().run(SandboxRequest(
        cmd=['sh', '-c', 'echo pwned > /etc/evil'], cwd=str(workspace),
        readonly_paths=(str(readonly),), shell=True)))
    assert result.violation
    assert result.exit_code != 0
    assert not os.path.exists('/etc/evil')


def test_scan_reports_traversal_kind(workspace):
    """扫描结果要能区分「穿越」与「引用根外路径」。"""
    policy = PathPolicy(writable=(str(workspace),))
    violations = scan_path_violations(
        ['cat', '../../etc/passwd'], policy, base=str(workspace),
        cwd=str(workspace))
    assert violations
    assert violations[0].kind == 'traversal'


def test_is_within_respects_path_boundaries():
    """前缀判定不能把 /usr/local 误判成 /usr 之外，也不能把 /usrlocal 当成在 /usr 内。"""
    assert is_within('/usr', '/usr/bin/python3') is True
    assert is_within('/usr', '/usr') is True
    assert is_within('/usr', '/usrx') is False
    assert is_within('/usr', '/etc/passwd') is False


def test_real_path_resolves_symlinks(tmp_path):
    """real_path 必须真的展开符号链接。"""
    target = tmp_path / 'target.txt'
    target.write_text('x', encoding='utf-8')
    link = tmp_path / 'link.txt'
    link.symlink_to(target)
    assert real_path(str(link)) == str(target)


# ── 2. 出网拦截 ──────────────────────────────────────────

def test_network_none_blocks_explicit_target(workspace):
    """network='none' 时不许出网。"""
    result = run(RestrictedSandbox().run(SandboxRequest(
        cmd=['curl', 'http://example.com'], cwd=str(workspace),
        network='none')))
    assert result.violation == VIOLATION_NET_DENY
    assert result.exit_code != 0


def test_network_allowlist_blocks_other_domain(workspace):
    """network='allowlist' 时不在白名单的域名要被拦。"""
    sandbox = RestrictedSandbox(network_allowlist=['example.com'])
    result = run(sandbox.run(SandboxRequest(
        cmd=['curl', 'http://evil.example.net'], cwd=str(workspace),
        network='allowlist')))
    assert result.violation == VIOLATION_NET_DENY
    assert result.exit_code != 0
    assert 'evil.example.net' in result.stderr


def test_network_allowlist_permits_listed_domain(workspace):
    """白名单里的域名不该被拦（判定层放行）。"""
    sandbox = RestrictedSandbox(network_allowlist=['example.com'])
    verdict = check_network('allowlist', ['curl', 'http://example.com'],
                            sandbox.network_allowlist)
    assert verdict == ''


def test_network_full_is_not_blocked(workspace):
    """network='full' 不做判定。"""
    verdict = check_network('full', ['curl', 'http://anything.com'], ())
    assert verdict == ''


def test_host_allowlist_supports_wildcards():
    """白名单支持 '.example.com' 形式（放行子域）。"""
    assert host_allowed('a.example.com', ('.example.com',)) is True
    assert host_allowed('example.com', ('.example.com',)) is True
    assert host_allowed('evil.com', ('.example.com',)) is False
    assert host_allowed('a.example.com', ('example.com',)) is True


def test_extract_network_targets_finds_urls_and_bare_hosts():
    """网络目标抽取要认得 URL 与裸域名两种写法。"""
    assert 'example.com' in extract_network_targets(['curl', 'http://example.com/x'])
    assert 'example.com' in extract_network_targets(['curl', 'example.com'])
    assert 'example.com' not in extract_network_targets(['echo', 'hello'])


def test_local_commands_are_not_treated_as_network():
    """本地命令不该被误判成出网 —— 误杀会让沙箱变得没法用。"""
    assert check_network('none', ['git', 'status'], ()) == ''
    assert check_network('none', ['echo', 'hello'], ()) == ''


# ── 3. 降级必须如实标注 ──────────────────────────────────

def test_restricted_is_always_degraded():
    """restricted 档永远 degraded=True —— 它是判定，不是隔离。"""
    assert RestrictedSandbox().degraded is True


def test_restricted_result_marks_degraded():
    result = run(RestrictedSandbox().run(SandboxRequest(cmd=['echo', 'hi'])))
    assert result.degraded is True
    assert result.backend == 'restricted'


def test_namespaced_reports_real_backend_when_available():
    """本机有强隔离后端时，namespaced 应当自称 namespaced 且不 degraded。"""
    caps = detect_capabilities()
    result = run(NamespacedSandbox().run(SandboxRequest(cmd=['echo', 'hi'])))
    if caps.any_available:
        assert result.backend == 'namespaced'
        assert result.degraded is False
    else:
        # 没有强隔离后端 → 必须降级成 restricted 并如实标注
        assert result.backend == 'restricted'
        assert result.degraded is True


def test_namespaced_degrades_without_error(monkeypatch):
    """探测不到强隔离后端时**不报错**，而是降级并如实标注。

    这是「降级而非降智」（策划案 §3.3.5）：上层可以选择「降级即拒绝」。
    """
    import harness.tools.sandbox.namespaced as ns

    def _no_caps():
        return ns.NamespaceCapabilities()

    monkeypatch.setattr(ns.NamespacedSandbox, 'capabilities',
                        lambda self: _no_caps())
    result = run(ns.NamespacedSandbox().run(SandboxRequest(cmd=['echo', 'hi'])))
    assert result.backend == 'restricted'
    assert result.degraded is True
    assert result.exit_code == 0          # 功能没坏，只是隔离降级
    assert 'hi' in result.stdout


def test_probe_reports_reason_when_backend_missing(monkeypatch):
    """探测失败要能给出原因（便于排查），不是只留一个 False。"""
    import harness.tools.sandbox.namespaced as ns
    monkeypatch.setattr(ns.shutil, 'which', lambda name: None)
    probe = ns.probe_bubblewrap()
    assert probe.available is False
    assert 'not found' in probe.reason


# ── 4. restricted 档的执行层语义 ─────────────────────────

def test_env_allowlist_blocks_parent_secrets(workspace, monkeypatch):
    """父进程的环境变量**不能**泄漏进沙箱。

    这是硬要求：os.environ 里通常有 API key 与数据库口令。
    """
    monkeypatch.setenv('PARENT_SECRET_TOKEN', 'LEAKED')
    result = run(RestrictedSandbox().run(SandboxRequest(
        cmd=['sh', '-c', 'echo "v=[$PARENT_SECRET_TOKEN]"'],
        cwd=str(workspace), shell=True)))
    assert 'LEAKED' not in result.stdout
    assert 'v=[]' in result.stdout


def test_declared_env_vars_are_passed(workspace):
    """声明过的环境变量要能传进去。"""
    result = run(RestrictedSandbox().run(SandboxRequest(
        cmd=['sh', '-c', 'echo "[$DECLARED]"'], cwd=str(workspace),
        env={'DECLARED': 'yes'}, shell=True)))
    assert '[yes]' in result.stdout


def test_ulimits_are_applied(workspace):
    """ulimit 限制要真的生效（fd 上限是最容易验证的一条）。"""
    result = run(RestrictedSandbox().run(SandboxRequest(
        cmd=['sh', '-c', 'ulimit -n'], cwd=str(workspace), shell=True)))
    assert result.exit_code == 0
    assert int(result.stdout.strip()) <= 256


def test_empty_command_is_rejected(workspace):
    """空命令要被拒（violation 非空）。"""
    result = run(RestrictedSandbox().run(SandboxRequest(cmd=[], cwd=str(workspace))))
    assert result.violation == VIOLATION_CMD_DENIED
    assert result.exit_code != 0


def test_timeout_is_reported(workspace):
    """超时要被如实标记（timed_out + 非 0 退出码）。"""
    result = run(RestrictedSandbox().run(SandboxRequest(
        cmd=['sleep', '30'], cwd=str(workspace), timeout=1)))
    assert result.timed_out is True
    assert result.exit_code != 0


def test_max_output_truncation(workspace):
    """输出超长要截断并标记 truncated。"""
    result = run(RestrictedSandbox().run(SandboxRequest(
        cmd=['sh', '-c', 'printf "aaaaaaaaaaaaaaaaaaaa"'],
        cwd=str(workspace), max_output=5, shell=True)))
    assert result.truncated is True
    assert len(result.stdout) == 5


def test_stdin_is_forwarded(workspace):
    """stdin 要能送进去。"""
    result = run(RestrictedSandbox().run(SandboxRequest(
        cmd=['cat'], cwd=str(workspace), stdin=b'piped\n')))
    assert 'piped' in result.stdout


# ── 5. namespaced 档的隔离强度 ───────────────────────────

@pytest.mark.skipif(not detect_capabilities().bubblewrap.available,
                    reason='需要 bubblewrap')
def test_namespaced_hides_etc_passwd_at_runtime(workspace):
    """强隔离档下，/etc/passwd 在**运行时**也不该存在。

    这一条比判定层更重要：判定层只认命令行里写明的路径，
    运行时隔离管的是「命令自己去找」的情况。
    """
    result = run(NamespacedSandbox().run(SandboxRequest(
        cmd=['sh', '-c', 'cat /etc/passwd 2>&1 | head -1'],
        cwd=str(workspace), writable_paths=(str(workspace),), shell=True)))
    assert 'root:' not in result.stdout


@pytest.mark.skipif(not detect_capabilities().bubblewrap.available,
                    reason='需要 bubblewrap')
def test_namespaced_can_write_inside_workspace(workspace):
    """隔离不能把正常工作区也弄坏。"""
    result = run(NamespacedSandbox().run(SandboxRequest(
        cmd=['sh', '-c', 'echo ok > out.txt && cat out.txt'],
        cwd=str(workspace), writable_paths=(str(workspace),), shell=True)))
    assert result.exit_code == 0
    assert 'ok' in result.stdout


# ── 6. shell 工具委派沙箱 ────────────────────────────────

def test_shell_tool_uses_sandbox_from_context(tmp_path):
    """ToolContext.sandbox 注入后，shell 工具必须走沙箱判定。"""
    from harness.tools.context import ToolContext, pop_context, push_context
    from harness.tools.shell import ShellSessions

    sessions = ShellSessions(sandbox=RestrictedSandbox())
    token = push_context(ToolContext(cwd=str(tmp_path)))
    try:
        text = sessions.execute('cat ../../etc/passwd')
    finally:
        pop_context(token)
        sessions.shutdown()
    assert '沙箱拒绝' in text
    assert 'path:escape' in text
    assert 'root:' not in text


def test_shell_tool_legacy_path_still_works(tmp_path):
    """没有沙箱时 legacy 路径仍然可用（既有行为不能破）。"""
    from harness.tools.context import ToolContext, pop_context, push_context
    from harness.tools.shell import ShellSessions

    sessions = ShellSessions()
    token = push_context(ToolContext(cwd=str(tmp_path)))
    try:
        text = sessions.execute('echo legacy-ok')
    finally:
        pop_context(token)
        sessions.shutdown()
    assert 'legacy-ok' in text


def test_shell_tool_normal_command_via_sandbox(tmp_path):
    """挂上沙箱后，正常命令照常能跑。"""
    from harness.tools.context import ToolContext, pop_context, push_context
    from harness.tools.shell import ShellSessions

    sessions = ShellSessions(sandbox=RestrictedSandbox())
    token = push_context(ToolContext(cwd=str(tmp_path)))
    try:
        text = sessions.execute('echo sandboxed-ok')
    finally:
        pop_context(token)
        sessions.shutdown()
    assert 'sandboxed-ok' in text


# ── 7. 违规的结构化通道（审计） ───────────────────────────
#
# 约定（lead 定的）：工具 append 到 ToolContext.violations，ToolGuard 读走
# 并发 tool_blocked / audit.denied。
#
# 为什么单独锁这一层：审计事件是「事后能复盘」的唯一凭据。
# 如果工具只回报一句文本，守卫就只能靠正则从文案里嗅探违规码 ——
# 那是把审计建在文案上，改一次文案就丢一次审计。

def test_shell_records_structured_violation(tmp_path):
    """沙箱拒绝时，工具要往 context.violations 里 append 结构化记录。"""
    from harness.tools.context import ToolContext, pop_context, push_context
    from harness.tools.shell import ShellSessions

    sessions = ShellSessions(sandbox=RestrictedSandbox())
    context = ToolContext(cwd=str(tmp_path), violations=[])
    token = push_context(context)
    try:
        sessions.execute('cat ../../etc/passwd')
    finally:
        pop_context(token)
        sessions.shutdown()
    assert len(context.violations) == 1
    record = context.violations[0]
    assert record['code'] == VIOLATION_PATH_ESCAPE
    assert record['kind'] == 'sandbox'
    assert record['detail']
    assert record['degraded'] is True     # restricted 档永远 degraded


def test_shell_records_network_violation(tmp_path):
    """出网被拦也要走同一条结构化通道。"""
    from harness.tools.context import ToolContext, pop_context, push_context
    from harness.tools.shell import ShellSessions

    sessions = ShellSessions(sandbox=RestrictedSandbox())
    context = ToolContext(cwd=str(tmp_path), violations=[])
    token = push_context(context)
    try:
        sessions.execute('curl http://evil.example.net')
    finally:
        pop_context(token)
        sessions.shutdown()
    assert len(context.violations) == 1
    assert context.violations[0]['code'] == VIOLATION_NET_DENY


def test_shell_does_not_record_violation_when_allowed(tmp_path):
    """正常执行不该产生违规记录（否则审计里全是噪音）。"""
    from harness.tools.context import ToolContext, pop_context, push_context
    from harness.tools.shell import ShellSessions

    sessions = ShellSessions(sandbox=RestrictedSandbox())
    context = ToolContext(cwd=str(tmp_path), violations=[])
    token = push_context(context)
    try:
        sessions.execute('echo fine')
    finally:
        pop_context(token)
        sessions.shutdown()
    assert context.violations == []


def test_sandbox_denial_reaches_audit_denied(tmp_path):
    """端到端：沙箱拒绝 → ToolGuard 发 audit.denied{reason:'sandbox'}。

    这是策划案 §8.2 用例 4「被拦并记审计」的完整链路。
    """
    from harness.approval.base import ApprovalDecision
    from harness.tools.context import ToolContext, pop_context, push_context
    from harness.tools.guard import ToolGuard
    from harness.tools.registry import ManagedToolRegistry
    from harness.tools.shell import session_shell_tool

    class _AutoApprove:
        async def request(self, request):
            return ApprovalDecision.approve(by='test', reason='auto')

    events: list[tuple[str, dict]] = []
    guard = ToolGuard(sandbox=RestrictedSandbox(), approval=_AutoApprove())
    guard._emit = lambda kind, payload: events.append((kind, payload))

    tool = session_shell_tool(name='shell', sandbox=RestrictedSandbox())
    registry = ManagedToolRegistry()
    registry.register(tool)
    registry.attach_guard(guard)

    token = push_context(ToolContext(cwd=str(tmp_path)))
    try:
        run(registry.execute_async(
            'shell', {'sub': 'execute', 'command': 'cat ../../etc/passwd'}))
    finally:
        pop_context(token)

    denied = [payload for kind, payload in events if kind == 'audit.denied']
    assert denied, '沙箱拒绝必须产生一条 audit.denied'
    assert denied[0]['reason'] == 'sandbox'
    assert denied[0]['violation'] == VIOLATION_PATH_ESCAPE
    assert 'root:' not in denied[0].get('detail', '')


def test_namespaced_denial_records_violation(tmp_path):
    """namespaced 档的拒绝路径也要走结构化通道。

    这条曾经是个**盲区**：namespaced 的拒绝分支没有跑过，
    导致里面的一个未定义名字（record_violation 没导入）没被发现。
    「每个分支都得有人走过」比「代码看起来对」可靠。
    """
    from harness.tools.context import ToolContext, pop_context, push_context
    from harness.tools.shell import ShellSessions

    sessions = ShellSessions(sandbox=NamespacedSandbox())
    context = ToolContext(cwd=str(tmp_path), violations=[])
    token = push_context(context)
    try:
        text = sessions.execute('cat ../../etc/passwd')
    finally:
        pop_context(token)
        sessions.shutdown()
    assert '沙箱拒绝' in text
    assert len(context.violations) == 1
    assert context.violations[0]['code'] == VIOLATION_PATH_ESCAPE


def test_namespaced_denial_via_run_records_violation(tmp_path):
    """直接用 run() 也要记违规（不能只有 shell 工具这条路记）。"""
    from harness.tools.context import ToolContext, pop_context, push_context

    context = ToolContext(cwd=str(tmp_path), violations=[])
    token = push_context(context)
    try:
        result = run(NamespacedSandbox().run(SandboxRequest(
            cmd=['curl', 'http://evil.example.net'], cwd=str(tmp_path),
            network='none')))
    finally:
        pop_context(token)
    assert result.violation == VIOLATION_NET_DENY
    assert len(context.violations) == 1
    assert context.violations[0]['code'] == VIOLATION_NET_DENY
