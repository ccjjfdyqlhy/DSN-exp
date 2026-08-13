# harness/gateway/flask_adapter.py
# Flask 网关适配器 — 把通用网关接口映射到 Flask。

from __future__ import annotations

from typing import Any, Optional


class FlaskGateway:
    """包装 Flask app，提供 IGateway 接口。"""

    def __init__(self, app: Any):
        self._app = app

    @property
    def app(self) -> Any:
        return self._app

    def register_blueprint(self, blueprint: Any, **opts: Any) -> None:
        self._app.register_blueprint(blueprint, **opts)

    def register_middleware(self, fn: Any) -> None:
        self._app.before_request(fn)

    def register_blueprints(self, blueprints: list[Any]) -> None:
        for bp in blueprints:
            self.register_blueprint(bp)
