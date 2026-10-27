# apps/dsn_study/tracking_lite/__init__.py
# 学习跟踪 lite（dsn_study 功能补齐阶段 4）。
#
# 分天事件存储（自 apps/dsn/tracking/store.py 移植）+ 学习日志门面：
#   - record_session / record_note：学习时段与备注事件
#   - daily_report：聚合打卡 + 学习时段 + 计划完成度的每日报告
# dsn 版的音频聆听/视觉捕捉/媒体库不移植（硬件依赖，见 FEATURE_GAP.md）。

from .store import TrackingStore
from .studylog import StudyLog

__all__ = ["TrackingStore", "StudyLog"]
