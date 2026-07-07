# maintenance/config.py
# 服务器维护模块 — 可配置参数

import os


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


def _env_bool(key: str, default: str) -> bool:
    return os.environ.get(key, default).lower() in ("1", "true", "yes")


def _env_int(key: str, default: str) -> int:
    return int(os.environ.get(key, default))


# 主开关
MAINTENANCE_ENABLED = _env_bool("MAINTENANCE_ENABLED", "true")
HIBERNATE_MAX_QUEUE = _env_int("HIBERNATE_MAX_QUEUE", "100")

# 调度策略
SCHEDULE_STRATEGY = _env("MAINTENANCE_SCHEDULE_STRATEGY", "predictive")  # fixed / predictive / manual
FIXED_HOUR = _env_int("MAINTENANCE_FIXED_HOUR", "4")                     # fixed 策略时固定凌晨 4:00
PREDICTIVE_MIN_FREE_HOURS = _env_int("MAINTENANCE_PREDICTIVE_MIN_FREE_HOURS", "3")
PREDICTIVE_MAX_HOUR = _env_int("MAINTENANCE_PREDICTIVE_MAX_HOUR", "8")
IDLE_TIMEOUT_MINUTES = _env_int("MAINTENANCE_IDLE_TIMEOUT_MINUTES", "60")
PREDICTIVE_IDLE_TRIGGER_MINUTES = _env_int("MAINTENANCE_PREDICTIVE_IDLE_TRIGGER_MINUTES", "60")
PREDICTIVE_MIN_DATA_SAMPLES = _env_int("MAINTENANCE_PREDICTIVE_MIN_DATA_SAMPLES", "50")
RETRY_ON_FAILURE = _env_bool("MAINTENANCE_RETRY_ON_FAILURE", "true")
RETRY_DELAY_MINUTES = _env_int("MAINTENANCE_RETRY_DELAY_MINUTES", "30")
ESTIMATE_PER_TASK_SECONDS = _env_int("MAINTENANCE_ESTIMATE_PER_TASK_SECONDS", "300")
TASK_TIMEOUT_SECONDS = _env_int("MAINTENANCE_TASK_TIMEOUT_SECONDS", "600")
SCHEDULE_CHECK_INTERVAL = _env_int("MAINTENANCE_SCHEDULE_CHECK_INTERVAL", "60")
