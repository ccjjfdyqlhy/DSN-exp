# plugins/builtin/distill_plugin.py
# 自动蒸馏触发器插件 — POST_PROCESS (priority 100, 最后执行)

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta

from plugins.base import Plugin, HookPoint, PluginContext

logger = logging.getLogger("DistillPlugin")


class DistillPlugin(Plugin):
    """
    自动蒸馏触发插件。

    POST_PROCESS 阶段 (priority 100):
    - 检查距离上次蒸馏是否达到间隔
    - 如果触发条件满足，异步启动蒸馏流程
    - 也监听对话中的蒸馏触发关键词

    依赖: distillation_engine (DistillationEngine 实例)
    """

    name = "distill"
    description = "自动蒸馏 — 定时触发 + 对话关键词触发 DistillationEngine"
    hooks = [HookPoint.POST_PROCESS]
    priority = 100  # 在所有其他 POST_PROCESS 插件之后

    # 蒸馏触发关键词
    _TRIGGER_KEYWORDS = [
        "总结学到了什么",
        "你学到了什么",
        "蒸馏技能",
        "分析对话模式",
        "生成技能草案",
    ]

    def __init__(self, distillation_engine=None, interval_hours: int = 24):
        self._engine = distillation_engine
        self._interval_hours = interval_hours
        self._last_run: datetime | None = None
        self._lock = threading.Lock()

    def on_load(self) -> None:
        if self._engine is None:
            logger.warning("distillation_engine 未注入，DistillPlugin 将跳过蒸馏")

    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        if self._engine is None:
            return ctx
        if hook != HookPoint.POST_PROCESS:
            return ctx

        # 检查是否需要定时蒸馏
        should_run = self._check_timed_trigger()

        # 检查对话关键词触发
        if not should_run and ctx.message:
            for keyword in self._TRIGGER_KEYWORDS:
                if keyword in ctx.message:
                    should_run = True
                    logger.info("检测到蒸馏触发关键词: %s", keyword)
                    break

        if should_run:
            self._run_distillation_async(ctx.user_id, ctx.chat_id)

        return ctx

    def _check_timed_trigger(self) -> bool:
        with self._lock:
            if self._last_run is None:
                self._last_run = datetime.now()
                return False

            elapsed = datetime.now() - self._last_run
            if elapsed >= timedelta(hours=self._interval_hours):
                self._last_run = datetime.now()
                return True
        return False

    def _run_distillation_async(self, user_id: int, chat_id: int) -> None:
        def _run():
            try:
                logger.info("开始自动蒸馏 (user=%s, chat=%s)", user_id, chat_id)
                report = self._engine.run(user_id=user_id)
                drafts_count = report.get("drafts_created", 0)
                patterns_count = report.get("patterns_found", 0)
                if drafts_count > 0:
                    logger.info(
                        "蒸馏完成: 发现 %d 个模式, 生成 %d 个草案",
                        patterns_count, drafts_count
                    )
                else:
                    logger.info("蒸馏完成: 未生成新草案 (模式=%d)", patterns_count)
            except Exception:
                logger.exception("蒸馏执行异常")

        t = threading.Thread(target=_run, daemon=True, name="distill-worker")
        t.start()
        # 非阻塞 — 蒸馏在后台线程执行
