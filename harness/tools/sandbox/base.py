# harness/tools/sandbox/base.py
# 沙箱（隔离执行）的协议与数据结构。
#
# 现状问题（策划案 §2.3）：harness/tools/shell.py 让模型以当前用户权限
# 执行任意 shell，没有审批、没有审计、没有路径边界。沙箱就是补这一层。
#
# 降级原则（策划案 §3.3.5「降级而非降智」）：检测不到强隔离后端时
# **不报错阻断**，但必须 degraded=True 并在事件与审计里标注 ——
# 绝不允许「以为自己在沙箱里」。上层策略可以选择「降级即拒绝」。

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

#: 网络档位（与 ToolSpec.network 同名同义）
NetworkLevel = Literal['none', 'allowlist', 'full']

#: 沙箱后端名
BackendName = Literal['none', 'restricted', 'namespaced', 'isolated']


@dataclass
class SandboxRequest:
    """一次沙箱执行请求。

    cmd            命令（argv 形式；shell 模式由后端自己决定是否需要）
    workspace_id   工作区 id（后端据此定位可写根目录）
    timeout        超时秒
    env            允许透传的环境变量（后端只放行这些）
    stdin          标准输入
    network        网络档位
    readonly_paths 只读路径前缀
    writable_paths 可写路径前缀
    cwd            工作目录
    shell          是否用 shell 解释命令
    max_output     输出截断阈值（字符数）
    """

    cmd: list[str] = field(default_factory=list)
    workspace_id: str = ''
    timeout: float = 30.0
    env: dict[str, str] = field(default_factory=dict)
    stdin: bytes | None = None
    network: NetworkLevel = 'none'
    readonly_paths: tuple[str, ...] = ()
    writable_paths: tuple[str, ...] = ()
    cwd: str = ''
    shell: bool = False
    max_output: int = 100_000


@dataclass
class SandboxResult:
    """沙箱执行结果。

    degraded  是否降级执行（无强隔离）。**必须如实标注**。
    backend   实际使用的后端名
    """

    exit_code: int = 0
    stdout: str = ''
    stderr: str = ''
    duration_ms: float = 0.0
    truncated: bool = False
    degraded: bool = False
    backend: str = 'none'
    timed_out: bool = False
    violation: str = ''

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.violation

    def to_dict(self) -> dict:
        return {
            'exit_code': self.exit_code,
            'stdout': self.stdout,
            'stderr': self.stderr,
            'duration_ms': self.duration_ms,
            'truncated': self.truncated,
            'degraded': self.degraded,
            'backend': self.backend,
            'timed_out': self.timed_out,
            'violation': self.violation,
        }


@runtime_checkable
class Sandbox(Protocol):
    """隔离执行后端。

    实现：restricted（子进程 + 路径/环境白名单）、namespaced（namespace /
    bubblewrap / nsjail）、isolated（容器 / 微虚机，rc1）。
    """

    name: str

    async def run(self, req: SandboxRequest) -> SandboxResult: ...

    @property
    def degraded(self) -> bool:
        """该后端是否属于降级档（restricted 及以下视为降级）。"""
        ...


__all__ = [
    'Sandbox',
    'SandboxRequest',
    'SandboxResult',
    'NetworkLevel',
    'BackendName',
]
