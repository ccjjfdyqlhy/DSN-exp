# harness/resources/__init__.py
# 资源层 —— ASR / TTS 本地资源的注册、调度与生命周期管理。
#
# 范围：只覆盖语音资源（ASR 语音识别 / TTS 语音合成）。
#   本包不涉及视觉、OCR、媒体处理等其它资源种类。
#
# 组成：
#   pool.ResourceKind / ResourceSpec / ResourceLease / ResourcePool
#       —— 资源描述与池化调度（复用 orchestrator.scheduler.ModelScheduler）
#   launchers.HTTPServiceLauncher / InProcessModelLauncher
#       —— 两类资源的启动/就绪/停机适配（复用 orchestrator.local_engine）

from .pool import ResourceKind, ResourcePool, ResourceLease, ResourceSpec
from .launchers import HTTPServiceLauncher, InProcessModelLauncher

__all__ = [
    "ResourceKind",
    "ResourceSpec",
    "ResourceLease",
    "ResourcePool",
    "HTTPServiceLauncher",
    "InProcessModelLauncher",
]
