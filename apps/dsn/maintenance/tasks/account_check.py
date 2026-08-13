# maintenance/tasks/account_check.py
# 账号状态检查任务 — 对指定 API 账号执行连通性测试（类似 /login test）

from __future__ import annotations

import logging

from .base import MaintenanceTask, TaskProgress

logger = logging.getLogger("maintenance.tasks.account")


class AccountCheckTask(MaintenanceTask):
    """检查指定 API 账号的连通性。添加时需提供 account_id。"""

    name = "账号检查"
    priority = 40
    requires_db = False

    def __init__(self, account_id: str = ""):
        super().__init__()
        self.account_id = account_id
        self.params = {"account_id": account_id}
        # 每个账号对应唯一任务名，便于多账号并存
        if account_id:
            self.name = f"账号检查:{account_id}"

    def run(self, reporter) -> dict:
        if not self.account_id:
            return {"success": False, "error": "未指定要检查的账号 (account_id)"}
        try:
            from apps.dsn.models.api_accounts import get_api_manager
            mgr = get_api_manager()
        except Exception as e:
            return {"success": False, "error": f"无法获取账号管理器: {e}"}

        reporter(TaskProgress(current=1, total=1, message=f"测试账号 '{self.account_id}'..."))
        import time
        t0 = time.time()
        ok, msg = mgr.test(self.account_id, timeout=30)
        latency_ms = (time.time() - t0) * 1000
        logger.info("账号检查 %s: %s", self.account_id, msg)

        # 记录监控观察（供 /login dynamic 学习）
        try:
            from apps.dsn.models.dynamic_router import get_dynamic_router
            get_dynamic_router().record(self.account_id, ok, latency_ms, source="check")
        except Exception as e:
            logger.warning("记录账号监控观察失败: %s", e)

        return {
            "success": ok,
            "stats": {"account": self.account_id, "detail": msg,
                      "latency_ms": round(latency_ms, 1)},
            "message": msg,
        }
