# apps/dsn_study/chat_hooks.py
# 对话期钩子 —— **兼容门面**（阶段 3 迁移后）。
#
# 阶段 3 之前，这里是能力实现地：pre_process()/post_process() 两个大方法
# 加上 boot.py 的 StudyEngine.chat 用 if/else 串起来。现在这些能力都迁到了
# `apps/dsn_study/pipeline/plugins.py`（harness/pipeline 的 Plugin），
# 由 `StudyPipelineRunner` 统一调度。
#
# 本文件保留为**向后兼容门面**：老调用方（既有测试、外部脚本）仍可
# `study_app.chat_hooks.pre_process(...)` / `.post_process(...)`，
# 内部转调插件实例 —— 逻辑只有一份。
#
# 新代码请直接用管线：`apps/dsn_study/pipeline/`。

from __future__ import annotations

import logging
from typing import Optional

from apps.dsn_study.pipeline.plugins import (
    ComplexityPlugin,
    DailyReportPlugin,
    ExamSessionPlugin,
    MemoryRecordPlugin,
    PersonalityFeedbackPlugin,
    PlanCheckPlugin,
    TTSPlugin,
    VisionContextPlugin,
)

logger = logging.getLogger("StudyChatHooks")

# 兼容旧代码里 `import apps.dsn_study.chat_hooks as ch; ch.datetime` 的用法：
# 门面自身保留 datetime 引用（真正的实现在 pipeline.plugins）。
from datetime import date, datetime  # noqa: F401


class StudyChatHooks:
    """学习域对话钩子集合（harness/pipeline 插件的兼容门面）。"""

    def __init__(self, *, exam_engine=None, plan_engine=None, llm=None,
                 memory_system=None, complexity_analyzer=None,
                 personality=None, voice=None, context_provider=None):
        self._exam_engine = exam_engine
        self._plan_engine = plan_engine
        self._llm = llm             # 视觉描述用（LLMService.describe_image）
        self._memory_system = memory_system
        self._complexity_analyzer = complexity_analyzer
        self._personality = personality
        self._voice = voice

        # ── 插件实例（逻辑真身）──
        self._vision = VisionContextPlugin(llm=llm)
        self._exam = ExamSessionPlugin(exam_engine=exam_engine)
        self._report = DailyReportPlugin(plan_engine=plan_engine)
        self._complexity = ComplexityPlugin(complexity_analyzer=complexity_analyzer)
        self._plan_check = PlanCheckPlugin(plan_engine=plan_engine)
        self._memory_record = MemoryRecordPlugin(memory_system=memory_system)
        self._personality_fb = PersonalityFeedbackPlugin(personality=personality)
        self._tts = TTSPlugin(voice=voice)

    # ── 日终报告状态（老代码会重置它以强制重新生成）──

    @property
    def _report_date(self) -> str:
        return self._report._report_date

    @_report_date.setter
    def _report_date(self, value: str) -> None:
        self._report._report_date = value

    @property
    def _report_user(self) -> int:
        return self._report._report_user

    @_report_user.setter
    def _report_user(self, value: int) -> None:
        self._report._report_user = value

    # ── 兼容方法（转调插件）──

    def _exam_block(self, user_id: int, message: str) -> str:
        return self._exam._exam_block(user_id, message)

    def _daily_report_block(self, user_id: int) -> str:
        return self._report._daily_report_block(user_id)

    def _vision_block(self, message: str, image: Optional[str]) -> str:
        from harness.pipeline.base import Context, HookPoint
        ctx = Context(message=message or "", image_data=image)
        ctx = self._vision.on_hook(HookPoint.PRE_PROCESS, ctx)
        # 去掉前缀，只留块本身
        out = ctx.message or ""
        prefix = "(系统上下文·仅供你参考，不要复述) "
        if out.startswith(prefix):
            out = out[len(prefix):]
        return out.strip()

    def pre_process(self, user_id: int, message: str,
                    image: Optional[str] = None) -> str:
        """对话前：返回要注入消息前缀的系统上下文（可能为空串）。

        依次跑：视觉 → 考试 → 日终报告 → 复杂度（与迁移前顺序一致）。
        """
        from harness.pipeline.base import Context, HookPoint
        ctx = Context(user_id=user_id, message=message or "", image_data=image)
        for plugin in (self._vision, self._exam, self._report, self._complexity):
            ctx = plugin.on_hook(HookPoint.PRE_PROCESS, ctx)
        out = ctx.message or ""
        prefix = "(系统上下文·仅供你参考，不要复述) "
        if out.startswith(prefix):
            out = out[len(prefix):]
        return out.strip()

    def post_process(self, reply: str) -> tuple[str, list[dict]]:
        """对话后：解析 <plan_check> 标签回写计划。

        返回 (清洗后的回复, 处理结果列表)。
        """
        from harness.pipeline.base import Context, HookPoint
        ctx = Context(message="", reply=reply or "")
        ctx = self._plan_check.on_hook(HookPoint.POST_PROCESS, ctx)
        results = ctx.outputs.get("plan_check") or []
        return ctx.reply, results
