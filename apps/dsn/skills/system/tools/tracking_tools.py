# skills/system/tools/tracking_tools.py
# 薄封装：把独立 tracking 包（用户跟踪系统 infra）的 TrackingTools 暴露给技能系统。
# 真正的实现位于 tracking/tools.py，避免技能目录与 infra 包耦合。

from apps.dsn.tracking.tools import TrackingTools  # noqa: F401

__all__ = ["TrackingTools"]
