# harness/gateway/__init__.py
# 通用网关层 — 把 AppBundle 声明的路由挂载到具体 Web 框架。

from .base import IGateway
from .flask_adapter import FlaskGateway

__all__ = ["IGateway", "FlaskGateway"]
