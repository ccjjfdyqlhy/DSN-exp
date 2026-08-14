# apps/dsn/models/dynamic_router.py
# DSN 侧 DynamicRouter — harness 广义实现的薄封装。
#
# harness/models/dynamic_router.py 提供端点可用性学习路由（MonitorStore /
# reliability 加权 / 时段写入）；本模块只负责接线：
#   - 监控数据落在 apps/dsn/.dsn/api_monitor.json
#   - 端点来源 = dsn 的 APIManager（api_accounts）
#   - 全局手动时段规则 = api_accounts._current_manual_schedule

from __future__ import annotations

import os
import threading
from typing import Optional

from harness.models.dynamic_router import (
    DynamicRouter as _HarnessDynamicRouter,
    MonitorStore as _HarnessMonitorStore,
)

_MONITOR_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".dsn", "api_monitor.json",
)


class MonitorStore(_HarnessMonitorStore):
    def __init__(self, path: str | None = None):
        super().__init__(path or _MONITOR_FILE)


class DynamicRouter(_HarnessDynamicRouter):
    def __init__(self, store: Optional[MonitorStore] = None, api_manager=None):
        from apps.dsn.models.api_accounts import _current_manual_schedule
        super().__init__(
            store=store or MonitorStore(),
            provider=api_manager,
            manual_schedule=_current_manual_schedule,
        )

    def _manager(self):
        """DSN 兼容：未注入 provider 时惰性加载全局 APIManager。"""
        if self._provider is None:
            from apps.dsn.models.api_accounts import get_api_manager
            self._provider = get_api_manager()
        return self._provider


# ── 全局单例（DSN 兼容） ──

_instance: DynamicRouter | None = None
_instance_lock = threading.Lock()


def get_dynamic_router() -> DynamicRouter:
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = DynamicRouter()
        return _instance


def reset_dynamic_router() -> None:
    """测试/重载用：清空单例"""
    global _instance
    with _instance_lock:
        _instance = None
