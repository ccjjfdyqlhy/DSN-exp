# infra/resources/__init__.py
# 资源层 —— ASR / TTS 本地资源的注册、调度与生命周期管理。
#
# 范围：只覆盖语音资源（ASR 语音识别 / TTS 语音合成）。
#   本包不涉及视觉、OCR、媒体处理等其它资源种类。
#
# 组成：
#   pool.ResourceKind / ResourceSpec / ResourceLease / ResourcePool
#       —— 资源描述与池化调度（复用 orchestrator.scheduler.ModelScheduler）
#   launchers.HTTPServiceLauncher / InProcessModelLauncher / DockerServiceLauncher
#       —— 各类资源的启动/就绪/停机适配（复用 orchestrator.local_engine）
#   launch_modes.LaunchMode / LaunchSpec
#       —— 托管型服务的启动策略（command / conda / docker）

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
    "resolve_conda_exe",
    "conda_root",
    "conda_env_dir",
    "conda_env_exists",
    "env_python",
]
