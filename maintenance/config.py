# maintenance/config.py
# 服务器维护模块 — 可配置参数

SCHEDULE_STRATEGY = "predictive"       # fixed / predictive / manual
FIXED_HOUR = 4                         # fixed 策略时固定凌晨 4:00
PREDICTIVE_MIN_FREE_HOURS = 3          # predictive 需要至少 3h 连续空闲
PREDICTIVE_MAX_HOUR = 8                # predictive 不晚于早上 8:00
IDLE_TIMEOUT_MINUTES = 60              # 持续 1h 无请求→待机
RETRY_ON_FAILURE = True                # 失败后是否重试
RETRY_DELAY_MINUTES = 30               # 重试间隔
ESTIMATE_PER_TASK_SECONDS = 300        # 每个任务预估耗时（给前端显示预计完成时间）
TASK_TIMEOUT_SECONDS = 600             # 单任务超时 10min
TRACKER_DATA_PATH = "_data/activity_tracker.dat"
SCHEDULE_CHECK_INTERVAL = 60           # 时钟 tick 间隔（秒）
