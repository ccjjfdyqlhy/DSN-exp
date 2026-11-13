# infra/resources/__init__.py
# 资源层 —— ASR / TTS / VLM 本地资源的注册、调度与生命周期管理。
#
# 范围：语音资源（ASR 语音识别 / TTS 语音合成）与视觉资源（VLM 多模态模型）。
#   VLM 是本地 Bonsai llama-server 这类重量级多模态服务，与语音资源在
#   「按需拉起 → 租约保活 → 空闲回收」这条链路上语义一致。
#
# 组成：
#   pool.ResourceKind / ResourceSpec / ResourceLease / ResourcePool
#       —— 资源描述与池化调度（复用 orchestrator.scheduler.ModelScheduler）
#   launchers.HTTPServiceLauncher / InProcessModelLauncher / DockerServiceLauncher
#       —— 各类资源的启动/就绪/停机适配（复用 orchestrator.local_engine）
#   launch_modes.LaunchMode / LaunchSpec
#       —— 托管型服务的启动策略（command / conda / docker）
#   idle.IdleReaper
#       —— 空闲自动关闭：闲置超阈值的资源自动卸载释放显存，下次请求再拉起

from .pool import ResourceKind, ResourcePool, ResourceLease, ResourceSpec
from .launchers import (
    DockerServiceLauncher,
    HTTPServiceLauncher,
    InProcessModelLauncher,
)
from .launch_modes import (
    LaunchMode,
    LaunchSpec,
    conda_env_dir,
    conda_env_exists,
    conda_root,
    env_python,
    resolve_conda_exe,
)
from .idle import IdleReaper

__all__ = [
    "ResourceKind",
    "ResourceSpec",
    "ResourceLease",
    "ResourcePool",
    "HTTPServiceLauncher",
    "InProcessModelLauncher",
    "DockerServiceLauncher",
    "LaunchMode",
    "LaunchSpec",
    "IdleReaper",
    "resolve_conda_exe",
    "conda_root",
    "conda_env_dir",
    "conda_env_exists",
    "env_python",
]
