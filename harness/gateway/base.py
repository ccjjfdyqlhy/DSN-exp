# harness/gateway/base.py
# 通用网关接口。

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class IGateway(Protocol):
    """Web 网关接口 — 注册蓝图与中间件。"""

    def register_blueprint(self, blueprint: Any, **opts: Any) -> None: ...

    def register_middleware(self, fn: Any) -> None: ...
