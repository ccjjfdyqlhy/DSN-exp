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
            # 0. 定期 consolidate 人格演化（证据累积 → 写回蒸馏产物）
            reporter(TaskProgress(current=1, total=4, message="固化人格演化证据..."))
            ev_total = 0
            try:
                if getattr(self._v3, "_evidence", None) is not None:
                    ev_total = self._v3._evidence.get_total(self._card_id)
                    if ev_total > 0:
                        distilled_json_path = (
                            __import__("pathlib").Path(__file__).parent.parent.parent
                            / "character_cards" / f"{self._card_id}.distilled.json"
                        )
                        merged = self._v3._evidence.consolidate(self._card_id, distilled_json_path)
                        if merged:
                            self._v3._state_manager.invalidate_distillation(self._card_id)
                            self._v3._generator.invalidate_cache()
            except Exception as e:
                logger.warning("consolidate 人格证据失败: %s", e)

            # 1. 扫描 materials 目录导入新素材
            reporter(TaskProgress(current=2, total=4, message="扫描素材目录..."))
            imported = self._v3.import_pending_materials(self._card_id)
            reporter(TaskProgress(current=2, total=4,
                                   message=f"导入了 {imported} 个新素材"))

            # 2. 检查是否需要蒸馏
            if not self._v3.is_distillation_needed(self._card_id):
                return {
                    "success": True,
                    "stats": {"imported": imported, "distilled": False,
                              "evidence_consolidated": ev_total},
                    "message": "无需执行人格蒸馏",
                }

            reporter(TaskProgress(current=3, total=4, message="执行人格蒸馏..."))
            distilled = self._v3.distill(self._card_id, model_name="openai")
            if distilled:
                self._v3.mark_distillation_done(self._card_id)
                logger.info("人格蒸馏完成 version=%d", distilled.version)

            # 3. 清理
            reporter(TaskProgress(current=4, total=4, message="人格刷新完成"))
            return {
                "success": True,
                "stats": {
                    "imported": imported,
                    "distilled": True,
                    "evidence_consolidated": ev_total,
                    "version": distilled.version if distilled else None,
                    "dimensions": len(distilled.indicator_vector) if distilled else 0,
                },
            }
        except Exception as e:
            logger.error("人格蒸馏失败: %s", e)
            return {"success": False, "error": str(e)}
