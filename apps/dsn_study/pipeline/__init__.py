# apps/dsn_study/pipeline/__init__.py
# dsn_study 的对话管线（阶段 3）—— 基于 harness/pipeline。
#
# 迁移前：能力内联在 chat_hooks.py（pre_process/post_process）+ boot.py 的
#         StudyEngine.chat 里，靠 if/else 串起来，加一个新能力要改多处。
# 迁移后：每个能力一个 Plugin，调度/优先级/短路/异常隔离交给基座。
#
# 详见 apps/dsn_study/MIGRATION_PLAN.md 阶段 3。

from .plugins import (
    AsrFilterPlugin,
    ComplexityPlugin,
    DailyReportPlugin,
    ExamSessionPlugin,
    MemoryRecordPlugin,
    ModelInvokePlugin,
    PersonalityFeedbackPlugin,
    SystemPromptPlugin,
    PlanCheckPlugin,
    TopicContextPlugin,
    TTSPlugin,
    VisionContextPlugin,
)
from .runner import StudyPipelineRunner

__all__ = [
    "StudyPipelineRunner",
    "AsrFilterPlugin",
    "SystemPromptPlugin",
    "TopicContextPlugin",
    "VisionContextPlugin",
    "ExamSessionPlugin",
    "DailyReportPlugin",
    "ComplexityPlugin",
    "ModelInvokePlugin",
    "PlanCheckPlugin",
    "MemoryRecordPlugin",
    "PersonalityFeedbackPlugin",
    "TTSPlugin",
]
