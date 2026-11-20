# infra/runtime/isolation.py
# 资源隔离的工作区面（策划案 §4.2.5 / rc2 P3）。
#
# ── 与沙箱的分工 ──
# harness/tools/sandbox 是**执行面**（一次工具调用跑在什么边界里），
# 这里是**状态面**（一次运行的可写状态空间是什么）——
# 策划案 §4.2.1 Workspace 的定义：一次运行的可写状态空间
# （文件系统 / 草稿 / 产物），spec 是 {fs, net, secret} 三类约束。
#
# ── 路径判定为什么再写一遍 ──
# harness/tools/sandbox/paths.py 的判定在 harness，infra 不能 import
# （依赖规则）。判定规则很小（resolve + 前缀），**两份实现由测试钉住**
# —— 这是仓库既定做法（幂等键也是这么钉的，见策划案 R-10）。
#
# 模型资源（GPU / 并发）复用 infra/resources/pool.py 的 ResourceSpec /
# ResourceLease —— 不在本模块重复；会话级并发上限复用 AgentSettings
# 的 max_concurrent / max_depth。本模块只做工作区。

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .state import WorkspaceStatus


@dataclass
class WorkspaceSpec:
    """一次运行的工作区约束（策划案 §4.2.1 的 spec{fs,net,secret}）。"""

    fs: str = 'workspace'            # none | workspace | full
    net: str = 'none'                # none | allowlist | full
    secret: str = 'none'             # none | refs（只允许凭据引用）
    #: 网络档位为 allowlist 时的域名白名单
    net_allowlist: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            'fs': self.fs,
            'net': self.net,
            'secret': self.secret,
            'net_allowlist': list(self.net_allowlist),
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> WorkspaceSpec:
        data = data or {}
        return cls(
            fs=str(data.get('fs') or 'workspace'),
            net=str(data.get('net') or 'none'),
            secret=str(data.get('secret') or 'none'),
            net_allowlist=tuple(data.get('net_allowlist') or ()),
        )


class IsolationError(RuntimeError):
    """路径越界 / 工作区不可用。"""


def contains_path(root: str | Path, target: str | Path) -> bool:
    """target 是否被 root 包含（防 ../ 与符号链接逃逸）。

    规则与 harness/tools/sandbox/paths.py 一致：先把两边都 resolve
    （真实路径），再做前缀判断 —— 只在字符串上做前缀的判断会被
    `../` 和 symlink 骗过。
    """
    try:
        root_real = Path(root).resolve()
        target_real = Path(target).resolve()
    except (OSError, ValueError):
        return False
    return target_real == root_real or root_real in target_real.parents


@dataclass
class Workspace:
    """一次运行的工作区实例。"""

    id: str
    session_id: str
    root: str
    spec: WorkspaceSpec = field(default_factory=WorkspaceSpec)
    status: str = WorkspaceStatus.READY.value
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'session_id': self.session_id,
            'root': self.root,
            'spec': self.spec.to_dict(),
            'status': self.status,
            'created_at': self.created_at,
        }


class WorkspaceManager:
    """工作区的分配、校验与生命周期。

    根目录布局：``<base>/<session_id>`` —— 一个 session 一个根，
    沙箱与工具的路径校验都锚定这个根（策划案 §4.4.6 文件面的
    「workspace_id 绑定的工作区根目录」）。
    """

    def __init__(self, base: str | os.PathLike[str] | None = None):
        if base is None:
            # 默认落在用户级状态目录（与 harness.paths.state_dir 同一约定：
            # $AICF_HOME 或 ~/.aicf）。infra 不能 import aicf.harness（依赖规则），
            # 这里按同一环境变量读一份 —— 由交叉测试钉住一致。
            override = os.environ.get('AICF_HOME')
            home = Path(override).expanduser() if override \
                else Path.home() / '.aicf'
            base = home / 'workspaces'
        self._base = Path(base)

    # ── 分配 ─────────────────────────────────────────────
    def allocate(self, session_id: str, *,
                 spec: WorkspaceSpec | None = None) -> Workspace:
        """为一个 session 分配工作区（目录不存在则创建）。"""
        if not str(session_id or '').strip():
            raise IsolationError('工作区必须绑定 session_id')
        spec = spec or WorkspaceSpec()
        root = self._base / str(session_id)
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise IsolationError(f'工作区创建失败: {error}') from error
        return Workspace(
            id=f'ws_{uuid.uuid4().hex[:12]}',
            session_id=str(session_id),
            root=str(root),
            spec=spec,
            status=WorkspaceStatus.READY.value,
        )

    # ── 路径校验 ─────────────────────────────────────────
    def check_path(self, workspace: Workspace, target: str | Path, *,
                   write: bool = False) -> Path:
        """校验一条路径是否落在这个工作区内（并按 spec 的 fs 档位放行）。

        fs=none      不允许文件访问
        fs=workspace 允许工作区内（默认）
        fs=full      允许全部（托管部署才会配；显式声明才生效）
        返回 resolve 后的真实路径 —— 调用方拿它去执行，不要拿原始串。
        """
        if workspace.spec.fs == 'none':
            raise IsolationError(f'工作区 {workspace.id} 的 fs 档位是 none：拒绝文件访问')
        resolved = Path(target).expanduser()
        if workspace.spec.fs != 'full' and                 not contains_path(workspace.root, resolved):
            raise IsolationError(
                    f'路径越界: {target} 不在工作区 {workspace.root} 内'
                    '（策划案 §4.4.6：先 resolve 再判前缀）')
        if write and workspace.status != WorkspaceStatus.READY.value:
            raise IsolationError(
                f'工作区 {workspace.id} 状态是 {workspace.status}，不可写')
        try:
            return resolved.resolve()
        except (OSError, ValueError) as error:
            raise IsolationError(f'路径解析失败: {error}') from error

    # ── 生命周期 ─────────────────────────────────────────
    def lock(self, workspace: Workspace) -> Workspace:
        workspace.status = WorkspaceStatus.LOCKED.value
        return workspace

    def release(self, workspace: Workspace) -> Workspace:
        workspace.status = WorkspaceStatus.RELEASED.value
        return workspace

    def expire(self, workspace: Workspace) -> Workspace:
        workspace.status = WorkspaceStatus.EXPIRED.value
        return workspace

    def net_check(self, workspace: Workspace, host: str) -> bool:
        """出网是否被允许（策划案 §4.4.6 网络面）。

        none      拒绝一切
        allowlist 只放行白名单域
        full      全放行（显式声明才生效）
        """
        if workspace.spec.net == 'full':
            return True
        if workspace.spec.net == 'none':
            return False
        host = str(host or '').strip().lower()
        return any(host == d or host.endswith(f'.{d}')
                   for d in (s.lower() for s in workspace.spec.net_allowlist))


__all__ = [
    'IsolationError',
    'Workspace',
    'WorkspaceManager',
    'WorkspaceSpec',
    'contains_path',
]
