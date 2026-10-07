# harness/orchestrator/local_engine.py
# 本地推理引擎（自有 HTTP 服务）子进程生命周期管理基类。
#
# harness 支持两类「本地推理引擎」：
#
#   * llama.cpp     —— 直接执行 llama-server 二进制（GGUF 模型），见 llamacpp.py
#   * Strata        —— 执行 python serve/server.py --engine strata --config <run.json>，
#                      由 Strata 自己拉起它的 C++/CUDA 引擎，见 strata.py
#
# 两者在 harness 视角下完全同构：
#
#   1. 都是「一条命令行 → 一个监听 127.0.0.1:<port> 的 OpenAI 兼容 HTTP 服务」；
#   2. 都需要就绪探针轮询、优雅停机（SIGTERM → SIGKILL，整进程组）、
#      父进程死亡联动（PR_SET_PDEATHSIG）；
#   3. 都通过 ModelScheduler 的 (load_fn, unload_fn) 钩子参与显存插槽调度。
#
# 因此进程管理逻辑统一收敛到本模块；各引擎只提供
#   base_url / build_command() / preflight() / child_env() / describe_target()
# 这几个差异点。新增引擎（vLLM、ollama、自研引擎……）只需再实现一遍这几个方法。

from __future__ import annotations

import atexit
import contextlib
import ctypes
import logging
import os
import shlex
import signal
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

import requests

logger = logging.getLogger("LocalEngine")

# 全局活跃进程注册表，供 atexit 统一释放
_ACTIVE_LAUNCHERS: set[LocalServerLauncher] = set()


def _cleanup_active_launchers() -> None:
    """Python 进程退出或被终止时的兜底显存清理。"""
    for launcher in list(_ACTIVE_LAUNCHERS):
        with contextlib.suppress(Exception):
            launcher.stop()


atexit.register(_cleanup_active_launchers)


def _set_parent_death_signal() -> None:
    """Linux 平台：当父进程意外死亡时，自动向当前子进程发送 SIGTERM 终止信号。"""
    with contextlib.suppress(Exception):
        PR_SET_PDEATHSIG = 1
        libc = ctypes.CDLL("libc.so.6")
        libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM)
    if hasattr(os, "setsid"):
        with contextlib.suppress(Exception):
            os.setsid()


def kill_process_tree(process: subprocess.Popen, timeout: float = 15.0) -> None:
    """优雅终止一个子进程（整进程组）：SIGTERM → 等待 → SIGKILL。

    单独抽出来是因为 Strata 的场景多一层：我们的直接子进程是
    `python serve/server.py`，而真正占显存的是它拉起的 C++ 引擎孙进程。
    两者都被放进同一个进程组，所以 killpg 能一次收干净。
    """
    if process is None or process.poll() is not None:
        return
    pid = process.pid
    try:
        if hasattr(os, "killpg") and hasattr(os, "getpgid"):
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except Exception:
                process.terminate()
        else:
            process.terminate()

        start = time.time()
        while time.time() - start < timeout:
            if process.poll() is not None:
                return
            time.sleep(0.2)

        if process.poll() is None:
            logger.warning("进程 %d 未在 %ds 内响应 SIGTERM，发送 SIGKILL...", pid, timeout)
            if hasattr(os, "killpg") and hasattr(os, "getpgid"):
                try:
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
                except Exception:
                    process.kill()
            else:
                process.kill()
            with contextlib.suppress(Exception):
                process.wait(timeout=5.0)
    except Exception as e:  # noqa: BLE001 - 停机失败不应向上抛，只能尽力
        logger.warning("终止进程 %s 时发生异常: %s", pid, e)


class LocalServerLauncher:
    """本地推理引擎子进程生命周期管理器（harness 通用实现）。

    提供：
      - 启动子进程并合成命令行（build_command 由子类提供）
      - 健康检查探测与就绪等待（默认探测 /health，llama-server 与 Strata 都提供）
      - 优雅停机与显存释放（SIGTERM → SIGKILL，作用于整个进程组）
      - 生成适用于 ModelScheduler 的 (load_fn, unload_fn) 钩子
    """

    #: 日志与报错里显示的引擎名（子类覆盖，例如 "llama-server" / "Strata"）
    engine_label: str = "本地推理引擎"
    #: 就绪探针：按顺序尝试，任一返回 200 即认为就绪
    ready_paths: tuple[str, ...] = ("/health", "/v1/models")

    def __init__(self, log_file: str | Path | None = None):
        self.log_file = Path(log_file) if log_file else None
        self._process: subprocess.Popen | None = None
        self._log_fp = None
        #: 最近一次 start() 实际使用的命令行（供状态接口展示）
        self.last_command: list[str] | None = None
        #: 子进程额外环境变量（子类在 child_env() 里补充）
        self.last_env: dict | None = None

    # ── 子类差异点 ──

    @property
    def base_url(self) -> str:
        """服务根 URL，例如 http://127.0.0.1:8080。"""
        raise NotImplementedError

    def build_command(self) -> list[str]:
        """合成要执行的命令行（列表形式）。"""
        raise NotImplementedError

    def preflight(self) -> None:
        """启动前的校验（二进制/模型/配置文件是否存在）。

        实现应当抛出 FileNotFoundError 或 ValueError，附带可操作的中文提示。
        """

    def child_env(self) -> dict:
        """子进程需要的额外环境变量（如 LD_LIBRARY_PATH / CUDA_VISIBLE_DEVICES）。"""
        return {}

    def describe_target(self) -> str:
        """日志里用于标识“启动的是什么”的一句话。"""
        return self.base_url

    def api_key(self) -> str | None:
        """服务要求的 API key（探针要带上），没有则 None。"""
        return None

    # ── 状态 ──

    def is_running(self) -> bool:
        """检查内部托管的子进程是否存活。"""
        if self._process is None:
            return False
        return self._process.poll() is None

    def is_ready(self, timeout: float = 2.0) -> bool:
        """通过 HTTP 端点探测服务是否已完全就绪提供推理服务。"""
        headers = {}
        key = self.api_key()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        for path in self.ready_paths:
            try:
                resp = requests.get(f"{self.base_url}{path}", headers=headers, timeout=timeout)
                if resp.status_code == 200:
                    return True
            except requests.RequestException as e:
                # 未就绪时连接被拒绝是常态，只在 debug 级别留痕
                logger.debug("%s 就绪探针 %s 未通过: %s", self.engine_label, path, e)
        return False

    # ── 生命周期 ──

    def start(
        self,
        wait_ready: bool = True,
        timeout: float = 180.0,
        progress_callback: Callable[[float], None] | None = None,
    ) -> bool:
        """启动引擎实例（可选等待就绪）。"""
        if self.is_running() and self.is_ready():
            logger.info("%s 已在运行并就绪: %s", self.engine_label, self.base_url)
            return True

        # 端口占用检测：本 launcher 自己没有子进程，但端口已有服务在响应，
        # 说明该端口被**外部/其它模型**的服务占用（常见于用户手动跑了
        # 同一引擎或另一套服务）。此时若继续启动，新进程会 bind 失败，
        # 而就绪探测又会命中那个外部服务，造成“看起来加载成功、实际用的是
        # 别的模型”的静默错配 —— 必须显式告警。
        if not self.is_running() and self.is_ready(timeout=1.0):
            logger.warning(
                "端口 %s 已被其它服务占用（非本进程托管）。"
                "本次加载不会真正拉起新实例，后续请求将命中该外部服务。"
                "如需 harness 独立托管，请改用其它端口或先停止外部服务。",
                self.base_url,
            )

        self.preflight()

        cmd = self.build_command()
        self.last_command = list(cmd)
        logger.info("正在启动 %s: %s", self.engine_label, " ".join(shlex.quote(c) for c in cmd))

        stdout_dest = subprocess.DEVNULL
        stderr_dest = subprocess.DEVNULL

        if self.log_file:
            try:
                self.log_file.parent.mkdir(parents=True, exist_ok=True)
                # 有意长期持有句柄（与子进程同生命周期），由 stop() 关闭
                self._log_fp = self.log_file.open("a", encoding="utf-8")
            except OSError as e:
                raise RuntimeError(f"无法写入引擎日志 {self.log_file}: {e}") from e
            stdout_dest = self._log_fp
            stderr_dest = self._log_fp

        try:
            sub_env = os.environ.copy()
            sub_env["LANG"] = "C.UTF-8"
            sub_env["LC_ALL"] = "C.UTF-8"
            sub_env["PYTHONIOENCODING"] = "utf-8"
            # 自定义构建（如 ~/Bonsai-demo/bin/cuda、Strata 的 CUDA 运行库目录）
            # 把 .so 放在二进制同目录，必须把该目录加入 LD_LIBRARY_PATH，
            # 否则启动时会报 "error while loading shared libraries"。
            # 这里自动注入，并允许子类/配置覆盖。
            bin_dir = os.path.dirname(cmd[0]) if cmd and cmd[0] else ""
            if bin_dir and os.path.isdir(bin_dir):
                existing = sub_env.get("LD_LIBRARY_PATH", "")
                parts = [p for p in existing.split(":") if p]
                if bin_dir not in parts:
                    sub_env["LD_LIBRARY_PATH"] = bin_dir + (":" + existing if existing else "")
            extra = self.child_env() or {}
            if extra:
                sub_env.update({str(k): str(v) for k, v in extra.items()})
                logger.info("%s 额外环境变量: %s", self.engine_label, sorted(extra))
            self.last_env = dict(extra)

            self._process = subprocess.Popen(
                cmd,
                stdout=stdout_dest,
                stderr=stderr_dest,
                env=sub_env,
                preexec_fn=_set_parent_death_signal if os.name != "nt" else None,  # noqa: PLW1509
            )
            _ACTIVE_LAUNCHERS.add(self)
        except OSError as e:
            logger.error("启动 %s 失败: %s", self.engine_label, e)
            if self._log_fp:
                self._log_fp.close()
                self._log_fp = None
            raise

        if not wait_ready:
            return True

        start_time = time.time()
        logger.info("等待 %s 服务就绪 (%s, 超时 %ds)...", self.engine_label, self.base_url, timeout)
        while time.time() - start_time < timeout:
            if self._process.poll() is not None:
                ret = self._process.returncode
                logger.error("%s 进程异常退出，退出码: %d", self.engine_label, ret)
                self.stop()
                raise RuntimeError(
                    f"{self.engine_label} 启动后立即退出，返回码: {ret}"
                    + (f"（详见日志 {self.log_file}）" if self.log_file else "")
                )

            if self.is_ready(timeout=1.5):
                elapsed = time.time() - start_time
                if progress_callback:
                    with contextlib.suppress(Exception):
                        progress_callback(1.0)
                logger.info(
                    "%s 启动成功并就绪 (耗时 %.1fs): %s",
                    self.engine_label, elapsed, self.base_url,
                )
                return True

            if progress_callback:
                elapsed = time.time() - start_time
                # 预估平滑进度曲线: 前 10 秒到 75%，后渐进到 95%
                calc_val = min(0.95, round(1.0 - (1.0 / (1.0 + elapsed / 10.0)), 2))
                with contextlib.suppress(Exception):
                    progress_callback(calc_val)

            time.sleep(0.5)

        self.stop()
        raise TimeoutError(
            f"{self.engine_label} 启动超时 ({timeout}s)，服务未在 {self.base_url} 就绪"
        )

    def stop(self, timeout: float = 15.0) -> bool:
        """优雅关闭引擎进程（整进程组）并释放显存。"""
        if self._process is None:
            return True

        pid = self._process.pid
        logger.info("正在停止 %s 进程 (PID %d)...", self.engine_label, pid)
        try:
            kill_process_tree(self._process, timeout=timeout)
        finally:
            _ACTIVE_LAUNCHERS.discard(self)
            self._process = None
            if self._log_fp:
                with contextlib.suppress(Exception):
                    self._log_fp.close()
                self._log_fp = None

        logger.info("%s 已完全停止", self.engine_label)
        return True

    def create_scheduler_hooks(
        self, load_timeout: int = 180,
    ) -> tuple[Callable[[], bool], Callable[[], bool]]:
        """生成与 ModelScheduler 对接的 (load_fn, unload_fn) 钩子回调。"""
        label = self.engine_label

        def _load() -> bool:
            try:
                return self.start(wait_ready=True, timeout=float(load_timeout))
            except Exception as e:  # noqa: BLE001 - 钩子不能抛，返回 False 让调度器收尾
                logger.error("ModelScheduler 调用 %s load_fn 失败: %s", label, e)
                return False

        def _unload() -> bool:
            try:
                return self.stop()
            except Exception as e:  # noqa: BLE001
                logger.error("ModelScheduler 调用 %s unload_fn 失败: %s", label, e)
                return False

        return _load, _unload

    # ── 供状态接口使用的快照 ──

    def command_string(self) -> str | None:
        """最近一次启动使用的命令行（shell 可复现形式）。"""
        if not self.last_command:
            return None
        return " ".join(shlex.quote(str(a)) for a in self.last_command)
