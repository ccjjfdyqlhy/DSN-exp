# maintenance/tasks/personality_optimize.py
# 人格蒸馏优化任务 — 导入待处理素材 + 触发 V3 蒸馏

from __future__ import annotations

import logging

from .base import MaintenanceTask, TaskProgress

logger = logging.getLogger("maintenance.tasks.personality")


class PersonalityOptimizeTask(MaintenanceTask):
    name = "人格蒸馏"
    priority = 20
    requires_db = True
    requires_llm = True

    def __init__(self, v3=None, card_id: str = "exa"):
        super().__init__()
        self._v3 = v3
        self._card_id = card_id

    def run(self, reporter) -> dict:
        if self._v3 is None:
            return {"success": False, "error": "V3 系统不可用"}

        try:
            # 1. 扫描 materials 目录导入新素材
            reporter(TaskProgress(current=1, total=3, message="扫描素材目录..."))
            imported = self._v3.import_pending_materials(self._card_id)
            reporter(TaskProgress(current=1, total=3,
                                   message=f"导入了 {imported} 个新素材"))

            # 2. 检查是否需要蒸馏
            if not self._v3.is_distillation_needed(self._card_id):
                return {
                    "success": True,
                    "stats": {"imported": imported, "distilled": False},
                    "message": "无需执行人格蒸馏",
                }

            reporter(TaskProgress(current=2, total=3, message="执行人格蒸馏..."))
            distilled = self._v3.distill(self._card_id, model_name="openai")
            if distilled:
                self._v3.mark_distillation_done(self._card_id)
                logger.info("人格蒸馏完成 version=%d", distilled.version)

            # 3. 清理
            reporter(TaskProgress(current=3, total=3, message="人格刷新完成"))
            return {
                "success": True,
                "stats": {
                    "imported": imported,
                    "distilled": True,
                    "version": distilled.version if distilled else None,
                    "dimensions": len(distilled.indicator_vector) if distilled else 0,
                },
            }
        except Exception as e:
            logger.error("人格蒸馏失败: %s", e)
            return {"success": False, "error": str(e)}
