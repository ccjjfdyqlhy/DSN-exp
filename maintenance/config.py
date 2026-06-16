# maintenance/config.py
# 服务器维护模块 — 可配置参数

SCHEDULE_STRATEGY = "predictive"       # fixed / predictive / manual
FIXED_HOUR = 4                         # fixed 策略时固定凌晨 4:00
PREDICTIVE_MIN_FREE_HOURS = 3          # predictive 需要至少 3h 连续空闲
PREDICTIVE_MAX_HOUR = 8                # predictive 不晚于早上 8:00
IDLE_TIMEOUT_MINUTES = 60              # 持续 1h 无请求→待机
PREDICTIVE_IDLE_TRIGGER_MINUTES = 60    # 预测触发：至少空闲 60 分钟
PREDICTIVE_MIN_DATA_SAMPLES = 50        # 至少 50 条请求记录才启用预测维护
RETRY_ON_FAILURE = True
RETRY_DELAY_MINUTES = 30
ESTIMATE_PER_TASK_SECONDS = 300
TASK_TIMEOUT_SECONDS = 600
SCHEDULE_CHECK_INTERVAL = 60
