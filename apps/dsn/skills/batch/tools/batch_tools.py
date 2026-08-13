# skills/batch/tools/batch_tools.py
# 批量操作工具 — 一次性提交多个 action 到线程池并行执行

import logging
from apps.dsn.tasks import TaskType

logger = logging.getLogger("skill.batch")


class BatchTools:
    _ctx = {}
    _ACTION_TYPES = frozenset({"shell", "python", "write_file", "edit_file"})

    @classmethod
    def set_context(cls, task_manager=None, db=None):
        cls._ctx["task_manager"] = task_manager
        cls._ctx["db"] = db

    def __init__(self):
        pass

    def _mgr(self):
        mgr = self._ctx.get("task_manager")
        if not mgr:
            raise RuntimeError("TaskManager 未注入")
        return mgr

    def _uid(self):
        from apps.dsn.skills.context import get_call_context
        return get_call_context()["user_id"] or self._ctx.get("_uid", 0)

    def _cid(self):
        from apps.dsn.skills.context import get_call_context
        return get_call_context()["chat_id"] or self._ctx.get("_cid", 0)

    def batch_execute(self, actions: list) -> dict:
        """一次性提交多个操作到线程池并行执行。

        每个 action 是一个 dict，包含:
          - action_type: shell/python/write_file/edit_file
          - content: 命令/代码/文件内容
          - file_path: (可选) 文件路径
          - overwrite: (可选) 是否覆盖
          - pattern: (可选) 匹配模式
          - replacement: (可选) 替换内容
          - label: (可选) 任务标签

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
                failed.append({"index": i, "error": "操作必须是对象", "label": f"batch_{i}"})
                continue
            action_type = action.get("action_type", "")
            content = action.get("content", "")
            label = action.get("label", f"batch_{i}")

            if not action_type or not content:
                failed.append({"index": i, "error": "缺少 action_type 或 content",
                               "label": label})
                continue
            if action_type not in self._ACTION_TYPES:
                failed.append({
                    "index": i,
                    "error": f"不支持的 action_type: {action_type}",
                    "label": label,
                })
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
                tid = mgr.create_task(
                    task_type=TaskType.ACTION,
                    user_id=uid, chat_id=cid,
                    params=params, priority=1)
                mgr.execute_task(tid)
                submitted.append({
                    "index": i,
                    "task_id": tid,
                    "action_type": action_type,
                    "label": label,
                })
                logger.info("batch: 提交 [%d] task_id=%s type=%s label=%s",
                            i, tid, action_type, label)
            except Exception as e:
                failed.append({"index": i, "error": str(e), "label": label})
                logger.error("batch: 提交 [%d] 失败: %s", i, e)

        return {
            "submitted": len(submitted),
            "failed": len(failed),
            "tasks": submitted,
            "errors": failed,
        }

    def batch_status(self, task_ids: list) -> dict:
        """查询批量任务的状态。

        返回每个 task_id 的当前状态和结果（如已完成）。
        """
        if not task_ids:
            return {"error": "task_ids 为空"}

        mgr = self._mgr()
        results = []

        for tid in task_ids:
            task = mgr.get_task(tid)
            if not task:
                results.append({"task_id": tid, "status": "not_found"})
                continue

            entry = {
                "task_id": tid,
                "status": task.status.value,
            }
            if task.result:
                entry["result"] = task.result
            if task.error:
                entry["error"] = task.error
            results.append(entry)

        return {"tasks": results, "count": len(results)}
