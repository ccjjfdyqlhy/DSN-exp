# harness/resources/launchers.py
# ASR / TTS 资源启动器 —— 两类本地语音资源的生命周期管理适配层。
#
# 两类资源形态迥异，但都归一到 harness.orchestrator.local_engine.LocalServerLauncher
# 的既有机制上（就绪探针 / 优雅停机 / (load_fn, unload_fn) 调度钩子）：
#
#   * HTTPServiceLauncher  —— TTS 场景（如 GPT-SoVITS @ 127.0.0.1:9880）。
#     服务本身通常**不由 harness 拉起**，harness 只是接入并复用；因此存在
#     「adopt 既有服务」模式：只探测不启动、只登记不杀进程。
#
#   * InProcessModelLauncher —— ASR 场景（FunASR AutoModel）。
#     模型加载在本进程内，没有 HTTP 端点，is_ready() 的语义是「模型对象存在」。
#
# 本模块**不重复实现**进程拉起、探针轮询、SIGTERM→SIGKILL 停机等逻辑，
# 全部复用 LocalServerLauncher 的既有实现，只覆盖差异点。

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Optional

from ..orchestrator.local_engine import LocalServerLauncher, kill_process_tree

logger = logging.getLogger("ResourceLauncher")


class HTTPServiceLauncher(LocalServerLauncher):
    """已存在的 HTTP 服务（TTS 等）的接入器。

    两种运行模式：

    1. **adopt 模式**（未配置 start_command）——服务由外部拉起，harness 只接入：
         * is_ready() 探测配置的 URL；
         * start() 在服务已应答时直接成功，**不会**因为没有命令可跑而报错；
         * stop() **绝不**杀死外部进程（除非配置了 stop_command）。
       这是 TTS 的常态：GPT-SoVITS 往往由用户自己启动并长期驻留。

    2. **托管模式**（配置了 start_command）——由本 launcher 拉起子进程：
         * start() 走基类的子进程拉起 + 就绪等待；
         * stop() 先执行 stop_command（若有），随后仍会终止本进程持有的子进程。
    """

    engine_label: str = "HTTP 语音服务"

    def __init__(
        self,
        name: str,
        base_url: str,
        ready_path: str = "/",
        start_command: list[str] | None = None,
        stop_command: list[str] | None = None,
        cwd: str | None = None,
        device: str | None = None,
        env: dict | None = None,
        log_file=None,
    ):
        super().__init__(log_file=log_file)
        self.name = name
        self._base_url = (base_url or "").rstrip("/")
        self.ready_path = ready_path or "/"
        self.start_command = list(start_command) if start_command else None
        self.stop_command = list(stop_command) if stop_command else None
        self.cwd = cwd
        self.device = device
        #: 额外环境变量（如 CUDA_VISIBLE_DEVICES）
        self._extra_env: dict = dict(env) if env else {}
        #: 就绪探针路径必须包含配置的 ready_path
        self.ready_paths: tuple[str, ...] = (self.ready_path,)

    # ── 模式判定 ──

    @property
    def adopt_mode(self) -> bool:
        """是否处于「接入既有服务」模式（无可执行命令）。"""
        return not self.start_command

    # ── 子类差异点 ──

    @property
    def base_url(self) -> str:
        return self._base_url

    def build_command(self) -> list[str]:
        """返回待执行的命令行；adopt 模式下为空列表。"""
        return list(self.start_command) if self.start_command else []

    def preflight(self) -> None:
        """校验 start_command 的可执行文件是否存在。

        adopt 模式无事可做（没有命令要跑）。托管模式下解析第一个参数
        （支持 ~ 与环境变量展开），不存在则抛 FileNotFoundError。
        """
        if self.adopt_mode:
            logger.info(
                "%s: adopt 模式（无 start_command），仅接入既有服务 %s",
                self.name, self.base_url,
            )
            return
        exe = self.start_command[0]
        resolved = shutil.which(os.path.expanduser(os.path.expandvars(exe)))
        if not resolved:
            raise FileNotFoundError(
                f"找不到可执行文件: {exe}（资源 {self.name}）。"
                f"请检查 start_command，或改为 adopt 模式只接入既有服务。"
            )

    def child_env(self) -> dict:
        """子进程额外环境变量：仅托管模式注入 device，adopt 模式不碰环境。"""
        extra = dict(self._extra_env)
        if not self.adopt_mode and self.device:
            extra.setdefault("CUDA_VISIBLE_DEVICES", str(self.device))
        return extra

    def describe_target(self) -> str:
        mode = "adopt" if self.adopt_mode else "managed"
        return f"{self.engine_label} {self.name} ({mode}) {self.base_url}"

    # ── 生命周期 ──

    def is_ready(self, timeout: float = 2.0) -> bool:
        """HTTP 就绪探针（继承基类实现：按 ready_paths 依次 GET）。

        进程内资源不适用；本类的资源一定有 URL，因此直接复用基类探针。
        """
        if not self.base_url:
            return False
        return super().is_ready(timeout=timeout)

    def start(
        self,
        wait_ready: bool = True,
        timeout: float = 180.0,
        progress_callback: Optional[Callable[[float], None]] = None,
    ) -> bool:
        """启动或接入服务。

        adopt 模式：服务已应答即成功；未应答则返回 False（不抛异常，
        因为「没有命令可跑」是合法配置，不是错误）。
        托管模式：委托基类拉起子进程并等待就绪。
        """
        if self.adopt_mode:
            if self.is_ready(timeout=min(timeout, 3.0)):
                logger.info("%s: 已接入既有服务 %s", self.name, self.base_url)
                return True
            logger.warning(
                "%s: adopt 模式下服务 %s 未就绪（需由外部先行启动）",
                self.name, self.base_url,
            )
            return False

        self._cancel_event.clear()
        logger.info("%s: 以托管模式启动 %s", self.name, self.describe_target())
        return super().start(
            wait_ready=wait_ready, timeout=timeout, progress_callback=progress_callback
        )

    def stop(self, timeout: float = 15.0) -> bool:
        """停止服务。

        adopt 模式：**默认不动外部进程**（它不是我们拉起的）。仅当显式配置了
        stop_command 时才执行它，并且只做「请求停止」，不 kill 任何未知 PID。
        托管模式：先执行 stop_command（若有），再走基类的整进程组优雅停机。
        """
        if self.adopt_mode:
            if not self.stop_command:
                logger.info(
                    "%s: adopt 模式下未配置 stop_command，保持外部服务 %s 运行",
                    self.name, self.base_url,
                )
                return True
            try:
                logger.info("%s: 执行 stop_command 请求停止外部服务", self.name)
                subprocess.run(
                    self.stop_command,
                    cwd=self.cwd,
                    timeout=timeout,
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return True
            except Exception as e:  # noqa: BLE001 - 停外部服务失败不应向上抛
                logger.warning("%s: stop_command 执行失败: %s", self.name, e)
                return False

        if self.stop_command:
            try:
                subprocess.run(
                    self.stop_command,
                    cwd=self.cwd,
                    timeout=timeout,
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("%s: stop_command 执行失败: %s", self.name, e)

        return super().stop(timeout=timeout)

    def describe(self) -> dict:
        """资源视图（供 ResourcePool 状态接口使用）。"""
        return {
            "name": self.name,
            "base_url": self.base_url,
            "ready_path": self.ready_path,
            "mode": "adopt" if self.adopt_mode else "managed",
            "running": self.is_running(),
            "command": self.command_string(),
        }


class InProcessModelLauncher(LocalServerLauncher):
    """进程内模型（ASR：FunASR AutoModel）的生命周期管理器。

    与 HTTP 服务不同，本类管理的模型：
      * 没有 base_url，is_ready() 的语义是「模型对象已存在且非 None」；
      * load() 必须在线程中执行（模型加载是分钟级的阻塞操作，不能占住事件循环）；
      * 卸载时若 torch 已导入且设备是 CUDA，顺手清一次显存缓存。
    """

    engine_label: str = "进程内语音模型"

    def __init__(
        self,
        name: str,
        loader: Callable[[], Any],
        unloader: Optional[Callable[[Any], None]] = None,
        device: Optional[str] = None,
        vram_estimate_mb: int = 0,
        log_file=None,
    ):
        super().__init__(log_file=log_file)
        self.name = name
        self.loader = loader
        self.unloader = unloader
        self.device = device
        self.vram_estimate_mb = int(vram_estimate_mb)
        #: 已加载的模型对象（None 表示未加载）
        self._model: Any = None
        #: 加载互斥：保证并发 load() 只真正执行一次
        self._load_lock = threading.RLock()
        #: 序列化对象以便日志展示
        self._loading = False

    # ── 子类差异点 ──

    @property
    def base_url(self) -> str:
        """进程内模型没有 HTTP 端点，恒为空串。"""
        return ""

    def build_command(self) -> list[str]:
        """进程内模型没有命令行。"""
        return []

    def preflight(self) -> None:
        """进程内模型没有可执行文件校验；loader 必须可调用。"""
        if not callable(self.loader):
            raise ValueError(f"资源 {self.name} 的 loader 不可调用")

    # ── 模型访问 ──

    @property
    def model(self) -> Any:
        """已加载的模型对象（未加载为 None）。"""
        return self._model

    def get_model(self) -> Any:
        """返回已加载的模型对象；未加载则为 None（不会触发加载）。"""
        return self._model

    def is_running(self) -> bool:
        """进程内模型「在运行」等价于「模型对象存在」。"""
        return self._model is not None

    def is_ready(self, timeout: float = 2.0) -> bool:
        """就绪语义：模型对象已存在且非 None（不是 HTTP 探针）。"""
        return self._model is not None

    @property
    def cancel_requested(self) -> bool:
        """进程内模型不可取消加载，恒为 False。"""
        return False

    # ── 生命周期 ──

    def load(self) -> Any:
        """加载模型（幂等，线程安全）。

        真正的 loader 在**工作线程**中执行，避免阻塞 asyncio 事件循环。
        已有模型对象时直接返回，不重复加载。
        """
        with self._load_lock:
            if self._model is not None:
                return self._model
            self.preflight()
            logger.info("%s: 开始加载模型 %s (device=%s)", self.engine_label, self.name,
                        self.device or "auto")
            box: dict = {}

            def _run() -> None:
                try:
                    box["model"] = self.loader()
                except BaseException as e:  # noqa: BLE001 - 传回主线程重新抛出
                    box["error"] = e

            worker = threading.Thread(
                target=_run, name=f"load-{self.name}", daemon=True
            )
            worker.start()
            worker.join()
            if "error" in box:
                raise box["error"]
            model = box.get("model")
            if model is None:
                raise RuntimeError(f"资源 {self.name} 的 loader 返回 None，加载失败")
            self._model = model
            logger.info("%s: 模型已加载 %s", self.engine_label, self.name)
            return self._model

    def unload(self) -> bool:
        """卸载模型：调用 unloader、丢弃引用、尽力清 CUDA 缓存。"""
        with self._load_lock:
            model = self._model
            if model is None:
                return True
            if self.unloader is not None:
                try:
                    self.unloader(model)
                except Exception:  # noqa: BLE001 - 卸载异常不应阻断引用清理
                    logger.exception("%s: unloader 执行失败 %s", self.engine_label, self.name)
            self._model = None
            self._empty_cuda_cache()
            logger.info("%s: 模型已卸载 %s", self.engine_label, self.name)
            return True

    def _empty_cuda_cache(self) -> None:
        """best-effort 释放 CUDA 缓存。

        仅在 torch **已经被导入**（sys.modules 命中）且设备为 CUDA 时执行；
        绝不在此处硬导入 torch，避免为未使用 CUDA 的场景引入依赖。
        """
        if not self.device or "cuda" not in str(self.device).lower():
            return
        torch = sys.modules.get("torch")
        if torch is None:
            return
        try:
            cuda = getattr(torch, "cuda", None)
            if cuda is not None and hasattr(cuda, "empty_cache"):
                cuda.empty_cache()
                logger.debug("%s: 已清理 CUDA 缓存 (%s)", self.engine_label, self.name)
        except Exception:  # noqa: BLE001 - 清理失败无关紧要
            logger.debug("%s: CUDA 缓存清理失败", self.name, exc_info=True)

    def start(
        self,
        wait_ready: bool = True,
        timeout: float = 180.0,
        progress_callback: Optional[Callable[[float], None]] = None,
    ) -> bool:
        """映射到 load()，可重复调用（已加载直接返回 True）。"""
        model = self.load()
        if model is None:
            return False
        if progress_callback:
            try:
                progress_callback(1.0)
            except Exception:  # noqa: BLE001
                pass
        return True

    def stop(self, timeout: float = 15.0) -> bool:
        """映射到 unload()，可重复调用（未加载直接返回 True）。"""
        return self.unload()

    def create_scheduler_hooks(
        self, load_timeout: int = 180,
    ) -> tuple[Callable[[], bool], Callable[[], bool]]:
        """生成适用于 ResourcePool.register_resource 的 (load_fn, unload_fn)。

        load_fn 不能抛异常（调度器据此收尾），失败一律返回 False。
        """
        def _load() -> bool:
            try:
                return self.start(wait_ready=True, timeout=float(load_timeout))
            except Exception as e:  # noqa: BLE001
                logger.error("%s: load_fn 失败 %s: %s", self.engine_label, self.name, e)
                return False

        def _unload() -> bool:
            try:
                return self.stop()
            except Exception as e:  # noqa: BLE001
                logger.error("%s: unload_fn 失败 %s: %s", self.engine_label, self.name, e)
                return False

        return _load, _unload

    def describe(self) -> dict:
        """资源视图（供 ResourcePool 状态接口使用）。"""
        return {
            "name": self.name,
            "device": self.device,
            "loaded": self._model is not None,
            "vram_estimate_mb": self.vram_estimate_mb,
        }
