
# harness/learning/__init__.py
# 学习子系统（框架层）：把 agent 自己的经历变成可训练、可评测、可晋级的资产。
#
# 五件事，各自独立可测：
#   dataset_builder —— 取数与筛选（只收 agent 自己的轨迹）
#   teacher         —— 教师边界（改写/标注/打分，不定义行为、不外泄用户数据）
#   evaluator       —— 分层判官（规则一票否决 → 本地判官 → 远端教师）
#   promotion       —— 候选 → 暂存 → 生效 → 回滚
#   selfplay        —— 自生成数据（当前模型 + 注入的情境 → 可训练样本）
#
# 边界提醒：这一层**不含**任何具体应用的语义（情感、沙箱、混沌演练都在本地实验应用里）。
# 框架层只保证数据流与纪律，实现与应用解耦。

from .dataset_builder import BuildReport, DatasetBuilder, Trajectory
from .evaluator import EvalPolicy, EvalScore, Evaluator, RuleEvaluator
from .probes import Probe, ProbeReport, ProbeResult, ProbeRunner
from .promotion import PromotionDecision, PromotionManager, PromotionPolicy
from .selfplay import (
    SELFPLAY_SOURCE,
    SelfPlayBoundaryError,
    SelfPlayConfig,
    SelfPlayGenerator,
    SelfPlayReport,
    Situation,
)
from .teacher import (
    PROTECTED_FIELDS,
    REFINE_CONTRACT,
    ChatLike,
    TeacherBoundaryError,
    TeacherConfig,
    TeacherRefiner,
)

__all__ = [
    "BuildReport",
    "ChatLike",
    "DatasetBuilder",
    "EvalPolicy",
    "EvalScore",
    "Evaluator",
    "PROTECTED_FIELDS",
    "Probe",
    "ProbeReport",
    "ProbeResult",
    "ProbeRunner",
    "PromotionDecision",
    "PromotionManager",
    "PromotionPolicy",
    "REFINE_CONTRACT",
    "RuleEvaluator",
    "SELFPLAY_SOURCE",
    "SelfPlayBoundaryError",
    "SelfPlayConfig",
    "SelfPlayGenerator",
    "SelfPlayReport",
    "Situation",
    "TeacherBoundaryError",
    "TeacherConfig",
    "TeacherRefiner",
    "Trajectory",
]
