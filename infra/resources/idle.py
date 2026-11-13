# infra/resources/idle.py
# 空闲回收器 —— 后台线程把「闲置过久」的计算资源自动卸载掉（释放显存/端口）。
#
# 定位：
#   本模块只做**判定与触发**，不关心资源怎么启停 —— 真正停资源的是
#   ResourcePool.reclaim_idle_resource()，它复用资源池登记的 unload_fn。
#
# 为什么要它：
#   ASR/TTS 这类本地 GPU 服务是重量级常驻进程（合计约 3.8GB 显存）。
#   它们挂在资源池上，resident=True 意味着**永远不会被调度器驱逐**，
#   于是「用户一天只用两次语音」也会一直占着显存。
#   本回收器补上这条缺失的策略：闲置超过阈值 → 停掉；下次请求 → 由资源池
#   的加载路径重新拉起（见 ModelScheduler._ensure_loaded_for_task）。
#
# 安全约束（三条，缺一不可）：
#   1. 只回收「无人使用且无人排队」的资源 —— refcount == 0 且队列为空；
#   2. 只回收**池能控制**的资源 —— 即 managed 模式（池自己拉起/停掉进程）。
#      adopt 模式（只接入外部服务）没有 unload 能力，回收它毫无意义；
#   3. 回收动作走 ResourcePool 的排他路径，回收期间到达的请求会等待，
#      不会撞上「正在被杀」的服务。
#
# 本模块无副作用导入，不依赖 torch/funasr/docker。

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger("IdleReaper")


class IdleReaper:
    """按空闲阈值自动卸载资源的后台线程。

    使用方式::

        reaper = IdleReaper(pool, interval=60.0)
        reaper.start()
        ...
        reaper.stop()
    """

    def __init__(
        self,
        pool,
        interval: float = 60.0,
        clock: Optional[Callable[[], float]] = None,
    ):
        """
        :param pool: 目标资源池（需实现 list_resources / reclaim_idle_resource）
        :param interval: 检查周期（秒）。太小会徒增 CPU 占用，太大则回收不准。
        :param clock: 时间源（可注入，便于测试）。默认 time.time。
        """
        self._pool = pool
        self._interval = max(1.0, float(interval))
        self._clock = clock or time.time
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        #: 统计信息（供状态接口展示）
        self._stats: dict = {
            "total_reclaimed": 0,
            "last_reclaimed_at": 0.0,
            "last_reclaimed": [],
            "running": False,
        }

    # ── 生命周期 ──

    def start(self) -> "IdleReaper":
        """启动后台线程（幂等：已在运行则直接返回自身）。"""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return self
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="dsn-idle-reaper",
                daemon=True,   # 守护线程：主进程退出时随之退出，不阻塞退出
            )
            self._thread.start()
            self._stats["running"] = True
            logger.info(
                "空闲回收器已启动：检查周期 %ss", self._interval)
            return self

    def stop(self, timeout: float = 5.0) -> None:
        """停止后台线程（幂等）。"""
        with self._lock:
            thread = self._thread
            self._thread = None
            self._stats["running"] = False
        self._stop_event.set()
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        logger.info("空闲回收器已停止")

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── 回收判定 ──

    def _run(self) -> None:
        """线程主体：按周期检查，收到停止信号即退出。"""
        while not self._stop_event.wait(self._interval):
            try:
                self.reap_once()
            except Exception:  # noqa: BLE001 - 后台线程不能因单次异常退出
                logger.exception("空闲回收检查异常")

    def reap_once(self) -> list[str]:
        """执行一轮检查，返回本次被回收的资源名列表。

        单独暴露出来是为了可测：不启线程也能直接驱动一轮判定。
        """
        now = self._clock()
        reclaimed: list[str] = []

        for row in self._pool.list_resources():
            name = row.get("name")
            if not name:
                continue

            # 1) 未设置空闲阈值 → 不回收
            timeout = float(row.get("idle_timeout") or 0)
            if timeout <= 0:
                continue
            # 2) 未加载 → 本来就没占资源，无需回收
            if not row.get("loaded"):
                continue
            # 3) 正被使用或有人排队 → 绝不回收
            if int(row.get("refcount") or 0) > 0 or int(row.get("queue") or 0) > 0:
                continue
            # 4) 池控制不了（adopt：外部服务）→ 无从停起，跳过
            if not row.get("managed"):
                continue

            last_used = float(row.get("last_used") or 0)
            idle_seconds = max(0.0, now - last_used)
            if idle_seconds < timeout:
                continue

            logger.info(
                "资源 %s 已空闲 %.0f 秒（阈值 %ss），自动关闭以释放显存",
                name, idle_seconds, timeout,
            )
            try:
                ok = bool(self._pool.reclaim_idle_resource(name))
            except Exception:  # noqa: BLE001 - 单个资源回收失败不影响其余
                logger.exception("回收空闲资源失败: %s", name)
                continue
            if ok:
                reclaimed.append(name)

        if reclaimed:
            with self._lock:
                self._stats["total_reclaimed"] += len(reclaimed)
                self._stats["last_reclaimed_at"] = now
                self._stats["last_reclaimed"] = reclaimed
            logger.info("空闲回收完成: %s", ", ".join(reclaimed))
        return reclaimed

    # ── 状态 ──

    def status(self) -> dict:
        """回收器状态（供 REST / 前端展示）。"""
        with self._lock:
            stats = dict(self._stats)
        stats["interval"] = self._interval
        stats["running"] = self.running
        return stats

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return "<IdleReaper running=%s interval=%ss>" % (self.running, self._interval)
