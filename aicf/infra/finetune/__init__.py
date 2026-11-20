
# infra/finetune/__init__.py
# 训练子系统（框架层）。
#
# 对外只暴露稳定契约：
#   submit / status / list_jobs / promote / rollback —— 都在 FinetuneManager 上；
#   JobState / TrainSpec / TrainJob / FinetuneError —— 状态与参数类型。
#
# 约束（本地应用与 harness 都必须遵守）：
#   1. **主进程不 import torch**。训练在独立解释器里跑独立脚本，
#      本包只负责体检、排队、等卡、拉进程、收结果。
#   2. **训练期不开 thinking**。见 TrainSpec.validate()。
#   3. **教师只能改写agent自己的轨迹**，且任何用户数据出机器前必须取得同意
#      （该约束属于 harness/learning 层，不在这里实现）。

from .base import (
    EnvironmentUnavailable,
    FinetuneError,
    JobState,
    SpecError,
    TrainJob,
    TrainingFailed,
    TrainSpec,
    new_job_id,
)
from .env import check_model_support, environment, require_environment, resolve_python
from .runner import FinetuneManager
from .store import FinetuneStore

__all__ = [
    "EnvironmentUnavailable",
    "FinetuneError",
    "FinetuneManager",
    "FinetuneStore",
    "JobState",
    "SpecError",
    "TrainJob",
    "TrainSpec",
    "TrainingFailed",
    "check_model_support",
    "environment",
    "new_job_id",
    "require_environment",
    "resolve_python",
]
