# apps/dsn_study/pipeline/runner.py
"""StudyPipelineRunner —— harness/pipeline 的同步门面。

`harness/pipeline` 的 `Pipeline.process()` 是 **async**，而 dsn_study 的对话主链
（`StudyEngine.chat`、HTTP API）是**同步**的。两条路：

A) 每轮 new 一个事件循环跑 —— 慢、且和 Flask 的线程模型打架；
B) 持有一个**常驻事件循环线程**，用 `run_coroutine_threadsafe` 跨线程调用 —— ✅

选 B，与 `apps/dsn_study/mcp_bridge.py` 完全同构（MCP 会话也必须活在自己的
事件循环里，否则「工具列出来了但调用永远失败」）。

插件本身可以是同步的：PluginManager 会用 `run_in_executor` 把同步插件挪到
线程池，不阻塞事件循环。
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Optional

from harness.pipeline.base import Context, HookPoint
from harness.pipeline.manager import PluginManager
from harness.pipeline.pipeline import Pipeline

logger = logging.getLogger("StudyPipeline")


class StudyPipelineRunner:
    """管线运行器：常驻事件循环 + 插件管理器。"""

    def __init__(self, plugins=None, hook_order=None):
        self.pm = PluginManager()
        self._plugins = list(plugins or [])
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        # 只跑 dsn_study 需要的钩子：不需要 PRE_FILTER（ASR 过滤在 ASR 阶段做）
        # 与 OUTPUT（渲染由 Flask 层负责）。
        self.pipeline = Pipeline(
            self.pm,
            hook_order=hook_order or [
                HookPoint.PRE_FILTER,
                HookPoint.PREPARE,
                HookPoint.PRE_PROCESS,
                HookPoint.MODEL_INVOKE,
                HookPoint.POST_PROCESS,
                HookPoint.POST_TTS,
            ],
        )

    # ── 生命周期 ──

    def start(self) -> bool:
        """启动常驻事件循环线程。"""
        if self._thread is not None:
            return True

        def _loop_main():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            self._ready.set()
            try:
                loop.run_forever()
            finally:
                try:
                    loop.close()
                except Exception:
                    pass

        self._thread = threading.Thread(target=_loop_main, daemon=True,
                                        name="study-pipeline")
        self._thread.start()
        self._ready.wait(timeout=5.0)
        for plugin in self._plugins:
            self.pm.register(plugin)
        logger.info("管线已启动：%d 个插件", len(self._plugins))
        return True

    def stop(self) -> None:
        """停止事件循环。"""
        loop = self._loop
        if loop is not None:
            try:
                loop.call_soon_threadsafe(loop.stop)
            except Exception:
                pass
        self._loop = None
        self._thread = None
        self._ready.clear()

    # ── 调用 ──

    def run(self, ctx: Context) -> Context:
        """同步跑一遍管线。管线不可用时原样返回 ctx（不阻断对话）。"""
        if self._loop is None:
            logger.warning("管线未启动（跳过）")
            return ctx
        try:
            future = asyncio.run_coroutine_threadsafe(
                self.pipeline.process(ctx), self._loop)
            return future.result(timeout=Config_TIMEOUT)
        except Exception:
            logger.warning("管线执行失败（已跳过）", exc_info=True)
            return ctx

    def __repr__(self) -> str:
        return "<StudyPipelineRunner plugins=%d running=%s>" % (
            len(self._plugins), self._loop is not None)


#: 单轮管线执行超时（秒）
Config_TIMEOUT = 300
