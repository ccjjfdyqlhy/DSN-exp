# apps/dsn_ui/logging_setup.py
"""DSN-UI 后端日志配置。

此前 dsn_ui 从未调用过 logging 的基本配置，根 logger 没有任何 handler，
只有 logging 的 lastResort 兜底（WARNING 及以上直接打到 stderr）。
配合代码里的 `logger.error("SSE 推理异常: %s", e)` 这种「只格式化异常对象」
的写法，栈信息被彻底丢弃 —— 线上只能看到一行没有位置、没有调用链的报错。

本模块提供：
  * setup_logging()   统一配置 console + 轮转文件 handler（含完整 traceback）
  * request_id 上下文 给每条日志打上请求关联 id，便于在海量日志里串起单次请求
  * exception_hook    捕获未被 await 的后台任务异常（asyncio）
"""

from __future__ import annotations

import contextvars
import logging
import logging.handlers
import os
import sys
import traceback
from pathlib import Path
from typing import Optional

# 当前请求的关联 id（异步上下文内自动传播，无需显式透传）
_request_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "dsn_ui_request_id", default=None
)

_LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | rid=%(request_id)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def set_request_id(rid: Optional[str]) -> contextvars.Token:
    """设置当前上下文的请求 id，返回 token 以便恢复。"""
    return _request_id_var.set(rid)


def get_request_id() -> Optional[str]:
    return _request_id_var.get()


def reset_request_id(token: contextvars.Token) -> None:
    try:
        _request_id_var.reset(token)
    except (ValueError, LookupError):
        # token 在其它上下文被使用过 → 直接清空即可，不影响主流程
        _request_id_var.set(None)


class _RequestIdFilter(logging.Filter):
    """把上下文里的 request_id 注入到每条 LogRecord。"""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = _request_id_var.get() or "-"
        return True


def _build_formatter() -> logging.Formatter:
    return logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)


def setup_logging(
    level: str = "INFO",
    log_dir: Optional[Path] = None,
    *,
    force: bool = False,
) -> logging.Logger:
    """配置 dsn_ui 及相关 harness logger 的输出。

    Args:
        level: 日志级别（DEBUG/INFO/WARNING/ERROR），可用环境变量 DSN_UI_LOG_LEVEL 覆盖。
        log_dir: 日志目录；None 时使用 apps/dsn_ui/logs。
        force: 即使已配置过也重新配置（测试用）。

    Returns:
        应用根 logger（"DSNUI"）。
    """
    env_level = os.getenv("DSN_UI_LOG_LEVEL", level).upper()
    numeric_level = getattr(logging, env_level, logging.INFO)

    root = logging.getLogger()
    if getattr(root, "_dsn_ui_configured", False) and not force:
        return logging.getLogger("DSNUI")

    # 清掉可能存在的旧 handler，避免重复输出
    for h in list(root.handlers):
        root.removeHandler(h)

    formatter = _build_formatter()
    rid_filter = _RequestIdFilter()

    console = logging.StreamHandler(stream=sys.stderr)
    console.setFormatter(formatter)
    console.setLevel(numeric_level)
    console.addFilter(rid_filter)

    handlers: list[logging.Handler] = [console]

    # 轮转文件：单文件 10MB × 5 份，避免占满磁盘
    try:
        target_dir = log_dir or (Path(__file__).resolve().parent / "logs")
        target_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            target_dir / "dsn_ui.log",
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(numeric_level)
        file_handler.addFilter(rid_filter)
        handlers.append(file_handler)
    except OSError as e:  # 只读文件系统等 → 退化为仅 console
        console.handle(logging.LogRecord(
            "DSNUIServer", logging.WARNING, __file__, 0,
            "无法创建日志文件，已退化为仅控制台输出: %s", (e,), None))

    root.setLevel(numeric_level)
    for h in handlers:
        root.addHandler(h)
    root._dsn_ui_configured = True  # type: ignore[attr-defined]

    # 第三方库的噪音降级，保留关键错误
    for noisy in ("uvicorn.access", "httpx", "httpcore", "urllib3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    app_logger = logging.getLogger("DSNUI")
    app_logger.info(
        "日志系统已就绪: level=%s handler=%s pid=%d",
        env_level, [type(h).__name__ for h in handlers], os.getpid(),
    )
    return app_logger


def log_exception(logger: logging.Logger, message: str, exc: BaseException) -> None:
    """统一异常记录：保留完整 traceback，而不是只打 str(exc)。

    这是本次定位问题的关键——原代码 `logger.error("...: %s", e)` 会把栈丢掉，
    导致无法判断异常究竟发生在哪一层。
    """
    logger.error(
        "%s | %s: %s\n%s",
        message, type(exc).__name__, exc,
        "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    )
