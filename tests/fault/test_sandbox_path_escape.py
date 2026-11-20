# tests/fault/test_sandbox_path_escape.py
# 策划案 §8.2 用例 4：沙箱内 `cat ../../etc/passwd` → 被拦并记审计
#
# 【这条用例证明什么】
#   沙箱存在的唯一理由：模型不能让 agent 读到工作区以外的东西。
#   `cat ../../etc/passwd` 是最朴素的那一类越界 —— 只要工作区不是根目录，
#   往上退两级就到了 /etc。密码文件、密钥、私有配置都在那儿。
#
#   这一层断言两件事：
#     1. **判定逻辑**（harness/tools/sandbox/paths.py）：
#          `../../etc/passwd` 被判成 traversal；
#          指向 /etc/passwd 的**符号链接**被判成 symlink_escape
#          （软链逃逸比 ../ 更隐蔽：词法路径还在工作区里）；
#          工作区内部的正常读取**不能**被误伤（否则工具没法用）。
#     2. **端到端**（restricted 后端落地后）：
#          命令真的跑不起来，且留下审计痕迹。
#
#   判定逻辑与后端无关 —— 后端只是把这条判定接到了进程启动参数上。
#   所以「后端还没落地」不影响本文件的核心断言成立。

from __future__ import annotations

import asyncio
import os

import pytest

from aicf.harness.tools.sandbox.base import SandboxRequest
from aicf.harness.tools.sandbox.restricted import VIOLATION_PATH_ESCAPE
from aicf.harness.tools.sandbox.paths import (
    PathPolicy,
    real_path,
    scan_path_violations,
    tokenize,
)

from faultkit import SANDBOX_MISSING_REASON, sandbox_backend

#: L4 故障注入层（策划案 §8.1 / §8.2）
pytestmark = pytest.mark.fault


@pytest.fixture()
def secret(tmp_path):
    """工作区**外面**的一份「机密」：往上退两级正好能摸到它。

    目录布局刻意做成两层深：
        <tmp>/etc/passwd          ← 越界的目标（模拟 /etc/passwd）
        <tmp>/agent/ws/           ← 工作区
    于是工作区里执行 `cat ../../etc/passwd` 解析到的正是那份机密 ——
    这正是真实场景的形状：工作区永远不是根目录。
    """
    etc = tmp_path / 'etc'
    etc.mkdir()
    target = etc / 'passwd'
    target.write_text('root:x:0:0:root:/root:/bin/bash\n', encoding='utf-8')
    return target


@pytest.fixture()
def workspace(tmp_path):
    """一个「工作区」：一个只有自己内容的临时目录（位于机密之上两层）。"""
    root = tmp_path / 'agent' / 'ws'
    root.mkdir(parents=True)
    (root / 'notes.txt').write_text('hello', encoding='utf-8')
    return root


@pytest.fixture()
def policy(workspace):
    """工作区可读写；系统目录只读；其余（/etc、/home…）一律不放行。"""
    return PathPolicy(
        readonly=(str(workspace),),
        writable=(str(workspace),),
    )


def _kinds(violations) -> set[str]:
    return {item.kind for item in violations}


# ── 4a：`cat ../../etc/passwd` 被判成穿越 ──────────────

def test_cat_dotdot_etc_passwd_is_flagged_as_traversal(workspace, policy,
                                                       secret):
    """期望：`cat ../../etc/passwd` 里的路径参数被判成 traversal。

    实际：如果只做词法前缀比较（`startswith(workdir)`），
          `../../etc/passwd` 会被**放行** —— 词法路径不以工作区开头，
          但 realpath 之后它就是 /etc/passwd 了。
    """
    tokens = tokenize('cat ../../etc/passwd')
    assert '../../etc/passwd' in tokens

    violations = scan_path_violations(tokens, policy,
                                      base=str(workspace),
                                      cwd=str(workspace))

    assert violations, '路径逃逸没有被拦住 —— 这是最严重的一类越界'
    kinds = _kinds(violations)
    assert 'traversal' in kinds, (
        f'期望 traversal 违规，实际 {kinds}（详情：{violations}）')
    flagged = [v for v in violations if v.path == '../../etc/passwd']
    assert flagged, (
        f"违规记录里应当点名 '../../etc/passwd'，实际 {violations}")
    assert real_path('../../etc/passwd', str(workspace)) == str(secret), (
        '前提假设不成立：../../etc/passwd 应当解析到工作区之外那份机密，'
        f'实际 {real_path("../../etc/passwd", str(workspace))}')


def test_escape_via_absolute_path_is_flagged(workspace, policy):
    """绝对路径越界（`cat /etc/passwd`）同样必须被拦。"""
    violations = scan_path_violations(tokenize('cat /etc/passwd'), policy,
                                      base=str(workspace),
                                      cwd=str(workspace))
    assert violations, '绝对路径越界没有被拦'
    assert 'outside_root' in _kinds(violations), (
        f'期望 outside_root，实际 {_kinds(violations)}')


def test_symlink_escape_is_flagged(workspace, policy):
    """软链逃逸：工作区里的 link -> /etc/passwd，`cat link` 必须被拦。

    这是词法判定挡不住的那一类：link 这个 token 里没有 '/'，
    词法路径 `<workspace>/link` 看着人畜无害，realpath 之后才是 /etc/passwd。
    """
    link = workspace / 'link'
    link.symlink_to('/etc/passwd')
    assert os.path.lexists(str(link))

    violations = scan_path_violations(tokenize('cat link'), policy,
                                      base=str(workspace),
                                      cwd=str(workspace))

    assert violations, '符号链接逃逸没有被拦'
    assert 'symlink_escape' in _kinds(violations), (
        f'期望 symlink_escape，实际 {_kinds(violations)}（详情：{violations}）')


# ── 4b：不能误伤正常工作区内的读取 ────────────────────

def test_reading_inside_the_workspace_is_allowed(workspace, policy):
    """期望：工作区里的文件与子目录都能正常读。

    实际：如果这里被误伤，agent 在工作区里连自己的文件都读不了 ——
          安全机制变成功能缺陷，同样是缺陷。
    """
    for command in ('cat notes.txt', 'cat ./notes.txt',
                    'cat sub/dir/file.txt'):
        violations = scan_path_violations(tokenize(command), policy,
                                          base=str(workspace),
                                          cwd=str(workspace))
        assert violations == [], (
            f'工作区内部的读取被误伤：{command} → {violations}')


def test_writing_outside_the_workspace_is_denied(workspace, policy):
    """写入越界（`> /tmp/evil`）按写判定拦截。

    读越界与写越界是两条线：只读的工具放行读越界就已经是事故了，
    但写越界更严重 —— 它能改掉系统上的东西。
    """
    violations = scan_path_violations(tokenize('echo x > /tmp/evil'), policy,
                                      base=str(workspace),
                                      cwd=str(workspace))
    assert violations, '写入越界没有被拦'
    assert 'write_denied' in _kinds(violations), (
        f'期望 write_denied，实际 {_kinds(violations)}')


def test_writing_inside_the_workspace_is_allowed(workspace, policy):
    """工作区内的写入必须放行（否则 agent 干不了活）。"""
    violations = scan_path_violations(tokenize('echo x > out.txt'), policy,
                                      base=str(workspace),
                                      cwd=str(workspace))
    assert violations == [], f'工作区内的写入被误伤：{violations}'


# ── 4c：端到端 —— 后端真的把命令拦住，且不留机密内容 ──
#
# 上面 4a/4b 测的是**判定层**（与后端无关）。
# 下面这三条测的是**执行层**：restricted 后端拿到命令之后，
# 到底拦不拦？拦了之后机密漏没漏出去？拦截原因有没有留下可审计的痕迹？
#
# violation 的取值是**稳定契约**（harness/tools/sandbox/restricted.py 里
# 明确定义），所以这里断言的是精确字符串，而不是「包含某个词」。

requires_sandbox = pytest.mark.skipif(
    sandbox_backend() is None,
    reason=SANDBOX_MISSING_REASON)


def test_restricted_backend_is_available():
    """沙箱后端必须可用 —— 不可用时这里**直接失败**（不是 skip）。

    为什么要单独一条：下面几条都带 requires_sandbox 跳过守卫。
    如果后端整个没了，那些用例会「全跳过」并显示成绿色 ——
    看起来通过，其实什么都没验证。这条把「后端在不在」变成硬断言。
    """
    backend = sandbox_backend()
    assert backend is not None, (
        '沙箱后端不可用：harness/tools/sandbox/restricted.py 应当提供 '
        'RestrictedSandbox')


@requires_sandbox
def test_sandbox_backend_blocks_cat_dotdot_etc_passwd(workspace, secret):
    """期望：命令被拦（violation=path:escape），机密内容没出现在输出里。

    实际：如果后端只是「把命令跑一遍，失败就算了」，
          那拦住的就不是逃逸，而是文件恰好不存在 ——
          换个真实存在的目标（比如 ~/.ssh/id_rsa）就漏了。
    """
    backend = sandbox_backend()
    request = SandboxRequest(
        cmd=['cat', '../../etc/passwd'],
        workspace_id='ws-1',
        cwd=str(workspace),
        writable_paths=(str(workspace),),
        readonly_paths=(str(workspace),),
        network='none',
        timeout=10.0,
    )

    result = asyncio.run(backend.run(request))

    assert result.violation == VIOLATION_PATH_ESCAPE, (
        f'期望 violation={VIOLATION_PATH_ESCAPE}，实际 {result.violation!r} '
        f'（stderr={result.stderr!r}）')
    assert result.exit_code != 0, '被拦的命令不该是成功状态'
    assert secret.read_text(encoding='utf-8') not in result.stdout, (
        '机密内容泄漏到了输出里 —— 沙箱没起作用')
    assert 'root:x:' not in result.stdout, '机密内容泄漏到了输出里'
    # 拦截原因要写清楚「拦的是哪个路径」—— 否则审计记录没有可操作性
    assert '../../etc/passwd' in result.stderr, (
        f'拦截原因里应当点名越界的路径，实际 {result.stderr!r}')


@requires_sandbox
def test_sandbox_backend_blocks_symlink_escape(workspace):
    """软链逃逸在后端层同样被拦（判定层 4a 已经覆盖，这里验执行层）。"""
    backend = sandbox_backend()
    link = workspace / 'link'
    link.symlink_to('/etc/passwd')

    request = SandboxRequest(
        cmd=['cat', 'link'],
        workspace_id='ws-1',
        cwd=str(workspace),
        writable_paths=(str(workspace),),
        readonly_paths=(str(workspace),),
        network='none',
        timeout=10.0,
    )

    result = asyncio.run(backend.run(request))
    assert result.violation == VIOLATION_PATH_ESCAPE, (
        f'期望 violation={VIOLATION_PATH_ESCAPE}，实际 {result.violation!r}')
    assert 'root:x:' not in result.stdout


@requires_sandbox
def test_sandbox_backend_allows_reading_inside_the_workspace(workspace):
    """反向校验：工作区内部的正常读取**不能**被拦（否则沙箱没法用）。"""
    backend = sandbox_backend()
    request = SandboxRequest(
        cmd=['cat', 'notes.txt'],
        workspace_id='ws-1',
        cwd=str(workspace),
        writable_paths=(str(workspace),),
        readonly_paths=(str(workspace),),
        network='none',
        timeout=10.0,
    )

    result = asyncio.run(backend.run(request))
    assert result.violation == '', (
        f'工作区内部的读取被误伤：violation={result.violation!r}')
    assert result.exit_code == 0, (
        f'期望命令成功，实际 exit_code={result.exit_code} '
        f'stderr={result.stderr!r}')
    assert 'hello' in result.stdout


@requires_sandbox
def test_restricted_backend_always_marks_itself_degraded(workspace):
    """restricted 档必须永远 degraded=True —— 它没有假装自己是防火墙。

    策划案 §3.3.5「降级而非降智」：restricted 没有内核级隔离，
    拦的是「命令行里写明的目标」，拦不住自己写 socket 直连 IP。
    这一点如果不如实标注，上层就没法做「降级即拒绝」的决策。
    """
    backend = sandbox_backend()
    assert backend.degraded is True, (
        'restricted 档必须声明自己是降级档（它没有内核级隔离）')

    request = SandboxRequest(
        cmd=['echo', 'hello'],
        workspace_id='ws-1',
        cwd=str(workspace),
        writable_paths=(str(workspace),),
        network='none',
        timeout=10.0,
    )
    result = asyncio.run(backend.run(request))
    assert result.degraded is True, '结果里也必须带 degraded 标记'


@requires_sandbox
def test_denied_escape_leaves_an_audit_trail(workspace, secret):
    """被拦必须留下审计痕迹 —— 拦了但不记，等于没拦。

    这一条走完整链路：ToolGuard（工具调用的唯一入口）→ 沙箱 → 审计。
    工具按契约从 ToolContext 拿沙箱（由守卫注入），
    被拒后返回一个失败结果，守卫必须把它记成一次 audit.tool_call。
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
                cmd=list(cmd), cwd=str(workspace),
                writable_paths=(str(workspace),),
                readonly_paths=(str(workspace),),
                network='none', timeout=10.0)
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
        sandbox=sandbox_backend(),
        telemetry=collector,
        runtime=NullRuntimeClient(),
        session_id='s1',
    )

    result = asyncio.run(
        guard.execute(tool, {'cmd': ['cat', '../../etc/passwd']}))

    assert result.result.success is False, '越界的命令不能成功'
    assert tool.violation == VIOLATION_PATH_ESCAPE, (
        f'期望 violation={VIOLATION_PATH_ESCAPE}，实际 {tool.violation!r}')
    assert secret.read_text(encoding='utf-8') not in str(result.result.to_dict())

    audits = collector.of('audit.tool_call')
    assert audits, f'被拦的调用没有留下审计记录：{collector.events}'
    assert audits[0].get('outcome') == 'error', (
        f'审计里应当记成 error，实际 {audits[0]}')


# ── 4d：沙箱拒绝要冒泡成独立的 audit.denied ─────────────
#
# 契约（lead 定的）：工具把结构化违规记录 append 到
# ``ToolContext.violations``，ToolGuard 执行完读走，
# 据此发 ``audit.denied{reason: 'sandbox'}``。
#
# 为什么用结构化通道，而不是抛异常、也不是从返回文本里正则嗅探：
#   - 抛异常会破坏「工具失败仍然是 ToolResult」的约定，模型拿不到可读反馈
#   - 从文本嗅探等于把审计建在文案上，改一次文案就丢一次审计
#   - 塞进 ToolResult.data 会被回喂给模型，把内部违规码泄漏进 prompt


def test_sandbox_denial_is_audited_as_audit_denied_with_reason_sandbox(
        workspace, secret):
    """期望：沙箱拒绝 → 一条 audit.denied，reason='sandbox'。

    这样复盘时才能一眼分清「被策略拦」「被审批拒」「被沙箱拦」。
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
        def __init__(self):
            super().__init__(name='shell', description='run a command',
                             handler=self._run,
                             spec=ToolSpec(name='shell', effect='pure',
                                           sandbox='workspace'))

        async def _run(self, cmd):
            sandbox = current_context().sandbox
            request = SandboxRequest(
                cmd=list(cmd), cwd=str(workspace),
                writable_paths=(str(workspace),),
                readonly_paths=(str(workspace),),
                network='none', timeout=10.0)
            result = await sandbox.run(request)
            if result.violation:
                return ToolResult.fail(f'sandbox denied: {result.violation}')
            return ToolResult.ok(result.stdout)

    collector = Collector()
    guard = ToolGuard(
        policy=RulePolicyEngine(rules=[PolicyRule(action='allow',
                                                   tool='shell')]),
        sandbox=sandbox_backend(),
        telemetry=collector,
        runtime=NullRuntimeClient(),
        session_id='s1',
    )

    result = asyncio.run(guard.execute(
        SandboxShell(), {'cmd': ['cat', '../../etc/passwd']}))
    assert result.result.success is False

    denials = collector.of('audit.denied')
    assert denials, (
        f'沙箱拒绝没有产生 audit.denied 记录：{collector.events}')
    assert denials[0].get('reason') == 'sandbox', (
        f'拒绝原因应当是 sandbox，实际 {denials[0]}')
