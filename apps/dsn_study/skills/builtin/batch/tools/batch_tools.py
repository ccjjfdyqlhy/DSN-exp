# apps/dsn_study/skills/builtin/batch/tools/batch_tools.py
# 批量操作工具 — 一次性提交多个 action 到线程池并行执行。
#
# 移植自参考实现 DSN-exp skills/batch/tools/batch_tools.py。
# 差异：参考版用 skills.context.get_call_context() 取 uid/cid（dsn_study 无该层），
#       改为与 study_tasks 技能一致的实例属性 + _ctx 兜底（uid 默认 1）。

from __future__ import annotations

import logging

from apps.dsn_study.tasks import TaskType

logger = logging.getLogger("skill.batch")


class BatchTools:
    _ctx = {}
    _ACTION_TYPES = frozenset({"shell", "python", "write_file", "edit_file"})

    @classmethod
    def set_context(cls, task_manager=None, db=None):
        cls._ctx["task_manager"] = task_manager
        cls._ctx["db"] = db

    def __init__(self):
        self.task_manager = None
        self.db = None

    def _mgr(self):
        mgr = getattr(self, "task_manager", None) or self._ctx.get("task_manager")
        if not mgr:
            raise RuntimeError("TaskManager 未注入")
        return mgr

    def _uid(self):
        return self._ctx.get("_uid", 1) or 1

    def _cid(self):
        return self._ctx.get("_cid", 0)

    def batch_execute(self, actions: list) -> dict:
        """一次性提交多个操作到线程池并行执行。

        每个 action: action_type / content / file_path? / overwrite? /
        pattern? / replacement? / label?

        返回所有 task_id 列表，结果通过心跳通知获取。
        """
        if not actions:
            return {"error": "actions 为空", "submitted": 0}

        mgr = self._mgr()
        uid = self._uid()
        cid = self._cid()

        submitted = []
        failed = []

        for i, action in enumerate(actions):
            if not isinstance(action, dict):
                failed.append({"index": i, "error": "操作必须是对象",
                               "label": "batch_%d" % i})
                continue
            action_type = action.get("action_type", "")
            content = action.get("content", "")
            label = action.get("label", "batch_%d" % i)

            if not action_type or not content:
                failed.append({"index": i, "error": "缺少 action_type 或 content",
                               "label": label})
                continue
            if action_type not in self._ACTION_TYPES:
                failed.append({"index": i,
                               "error": "不支持的 action_type: %s" % action_type,
                               "label": label})
                continue

            params = {
                "action_type": action_type,
                "content": content,
                "file_path": action.get("file_path", ""),
                "overwrite": action.get("overwrite", False),
                "pattern": action.get("pattern", ""),
                "replacement": action.get("replacement", ""),
                "label": label,
            }

            try:
                tid = mgr.create_task(task_type=TaskType.ACTION,
                                      user_id=uid, chat_id=cid,
                                      params=params, priority=1)
                mgr.execute_task(tid)
                submitted.append({"index": i, "task_id": tid,
                                  "action_type": action_type, "label": label})
                logger.info("batch: 提交 [%d] task_id=%s type=%s label=%s",
                            i, tid, action_type, label)
            except Exception as e:
                failed.append({"index": i, "error": str(e), "label": label})
                logger.error("batch: 提交 [%d] 失败: %s", i, e)

        return {"submitted": len(submitted), "failed": len(failed),
                "tasks": submitted, "errors": failed}

    def batch_status(self, task_ids: list) -> dict:
        """查询批量任务的状态。"""
        if not task_ids:
            return {"error": "task_ids 为空"}

        mgr = self._mgr()
        results = []
        for tid in task_ids:
            task = mgr.get_task(tid)
            if not task:
                results.append({"task_id": tid, "status": "not_found"})
                continue
            entry = {"task_id": tid,
                     "status": task.status.value}
            if task.result:
                entry["result"] = task.result
            if task.error:
                entry["error"] = task.error
            results.append(entry)
        return {"results": results}
