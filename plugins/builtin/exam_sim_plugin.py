# plugins/builtin/exam_sim_plugin.py
# 考试模拟管线插件 — 超时检测 + 关键字触发标记，工具执行由 SkillRegistry 统一处理

from __future__ import annotations

import logging

from plugins.base import Plugin, HookPoint, PluginContext

logger = logging.getLogger("ExamSimPlugin")


class ExamSimPlugin(Plugin):
    name = "exam_sim"
    description = "考试模拟 - 超时检测 + 关键字触发标记"
    hooks = [HookPoint.PRE_FILTER, HookPoint.PRE_PROCESS]
    priority = 18

    def __init__(self, exam_engine=None, scorer=None):
        self._engine = exam_engine
        self._scorer = scorer

    def on_load(self) -> None:
        if self._engine is None:
            logger.warning("ExamEngine 未注入")

    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        if hook == HookPoint.PRE_FILTER:
            return self._check_timeout(ctx)
        if hook == HookPoint.PRE_PROCESS:
            return self._pre_process(ctx)
        return ctx

    def _check_timeout(self, ctx: PluginContext) -> PluginContext:
        session_id = ctx.extra.get("exam_session_id")
        if not session_id or not self._engine:
            return ctx
        if self._engine.is_timeout(session_id):
            logger.info("考试超时自动提交: session=%s", session_id[:8])
            result = self._engine.auto_submit(session_id)
            ctx.extra["exam_auto_submitted"] = result
        return ctx

    def _pre_process(self, ctx: PluginContext) -> PluginContext:
        message = ctx.message.lower()

        exam_cmds = ["开始考试", "start exam", "提交试卷", "submit exam",
                     "开始作答", "交卷", "查看成绩"]
        is_exam_cmd = any(cmd in message for cmd in exam_cmds)

        if is_exam_cmd:
            ctx.extra["exam_command"] = True

        if "submit" in message or "交卷" in message or "提交" in message:
            session_id = ctx.extra.get("exam_session_id")
            if session_id and self._engine:
                result = self._engine.submit_session(session_id)
                ctx.extra["exam_submit_result"] = result
                if result.get("success"):
                    ctx.extra["exam_session_id"] = None
                    ctx.extra["exam_filtered"] = False

        session_id = ctx.extra.get("exam_session_id")
        if session_id and self._engine:
            remaining = self._engine.get_remaining_time(session_id)
            ctx.extra["exam_remaining"] = remaining
            ctx.extra["exam_in_progress"] = True

        return ctx
