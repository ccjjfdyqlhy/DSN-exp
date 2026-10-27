# infra/orchestrator/local_engine.py
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
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from .base import local_probe_session

logger = logging.getLogger("LocalEngine")


class LaunchCancelled(RuntimeError):
    """启动过程中被 stop()/unload 取消（不是失败）。"""


# 全局活跃进程注册表，供 atexit 统一释放
_ACTIVE_LAUNCHERS: set[LocalServerLauncher] = set()

#: 拉起子进程专用的常驻线程（单线程池，与进程同生命周期，不主动关闭）。
#:
#: 子进程通过 PR_SET_PDEATHSIG 绑定到 fork 它的**父线程**：那条线程一退出，
#: 内核立刻给子进程发 SIGTERM。若直接用 asyncio.to_thread（事件循环的默认
#: 线程池），一旦事件循环关闭、线程池被回收，已经跑起来的模型就会莫名其妙
#: 被杀掉（表现为"刚加载好就变成未加载"）。
#: 因此所有 Popen 都交给这条专用线程执行，它的生命周期 = 进程生命周期。
_LAUNCH_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="engine-launch")


def _popen_on_launch_thread(*args, **kwargs) -> subprocess.Popen:
    """在专用常驻线程里执行 Popen（见 _LAUNCH_EXECUTOR 的说明）。"""
    return _LAUNCH_EXECUTOR.submit(subprocess.Popen, *args, **kwargs).result()


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


def _resolve_kill_pgid(pid: int) -> int | None:
    """解析「可以安全整体终止」的进程组 ID；不可信时返回 None。

    修复说明（2026-10）：原实现直接 `os.killpg(os.getpgid(pid), ...)`，
    而 `os.getpgid()` 对**内核线程**返回 0（本机 PID 99 = kworker/R-blkcg
    的 pgid 就是 0）。按 POSIX，`killpg(0, sig)` 等价于 `kill(-0, sig)`
    ——  给**调用者自己所在的进程组**发信号，而不是给目标进程组发。

    实测后果：`tests/test_harness_strata.py` 曾 mock `proc.pid = 99`，
    于是 pytest 进程被自己的 SIGTERM 打死（exit 143），日志尾部只剩
    「已终止」，连外层 shell 进程组一起带走；全量 pytest 更是在打印完
    统计之后**挂死**，直到被 timeout 杀掉。生产侧同理——若引擎子进程的
    pgid 解析出 0 或与本进程同组，`stop()` 会把整个应用进程组一起带走。

    护栏（三条任一命中即判定不可信，返回 None，由调用方退回 terminate()
    只终止目标进程本身）：

    - `pgid <= 0`：0 意味着「调用者自己的组」，负数无意义；
    - `pgid == 本进程所在组`：同样会误伤自己；
    - `getpgid()` 抛错（子进程已退出 / pid 非法）：无法定位目标。
    """
    if not hasattr(os, "getpgid"):
        return None
    try:
        pgid = os.getpgid(pid)
    except (OSError, TypeError, ValueError):
        return None
    if not isinstance(pgid, int) or pgid <= 0:
        return None
    try:
        own_pgid = os.getpgid(0)
    except OSError:
        own_pgid = None
    if own_pgid is not None and pgid == own_pgid:
        return None
    return pgid


def _kill_descendants(pid: int) -> None:
    """无法安全 killpg 时，尽力逐个终止 pid 的后代进程。

    用于「子进程与本进程同组」的退化场景：此时既不能 killpg（会误伤自己），
    又要保住「整棵树一起收干净」的语义（Strata 的 C++ 引擎是孙进程）。

    psutil 是可选依赖（`pip install -e .` 不装它），缺失时静默跳过。
    """
    try:
        import psutil
    except ImportError:
        return
    with contextlib.suppress(Exception):
        # 先收集后代再终止——否则父进程一死，子进程会被 reparent 给 init 而失联
        for child in psutil.Process(pid).children(recursive=True):
            with contextlib.suppress(Exception):
                child.terminate()


def kill_process_tree(process: subprocess.Popen, timeout: float = 15.0) -> None:
    """优雅终止一个子进程（整进程组）：SIGTERM → 等待 → SIGKILL。

    单独抽出来是因为 Strata 的场景多一层：我们的直接子进程是
    `python serve/server.py`，而真正占显存的是它拉起的 C++ 引擎孙进程。
    两者都被放进同一个进程组，所以 killpg 能一次收干净。

    安全护栏见 `_resolve_kill_pgid`：**绝不**向「调用者自己所在的进程组」
    发信号——`killpg(0, ...)` 会误杀本进程（已修）。
    """
    if process is None or process.poll() is not None:
        return
    pid = process.pid
    pgid = _resolve_kill_pgid(pid)
    try:
        if pgid is not None:
            try:
                os.killpg(pgid, signal.SIGTERM)
            except Exception:
                process.terminate()
        else:
            # 进程组不可信：只杀目标进程本身，并尽力回收它的后代
            _kill_descendants(pid)
            process.terminate()

        start = time.time()
        while time.time() - start < timeout:
            if process.poll() is not None:
                return
            time.sleep(0.2)

        if process.poll() is None:
            logger.warning("进程 %d 未在 %ds 内响应 SIGTERM，发送 SIGKILL...", pid, timeout)
            if pgid is not None:
                try:
                    os.killpg(pgid, signal.SIGKILL)
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
        #: 最近一次 start() 使用的工作目录（供状态接口展示）
        self.last_cwd: str | None = None
        #: 启动取消信号。stop() 会置位，正在等待就绪的 start() 据此**干净退出**。
        #:
        #: 修复的现场：用户在模型加载中途点「终止」，unload 线程调用 stop() 把
        #: self._process 置为 None，而 start() 的就绪等待循环仍在下一次迭代里
        #: 调用 self._process.poll() → AttributeError: 'NoneType' object has no
        #: attribute 'poll'。该异常冒泡成 500，前端表现为「模型其实已经加载完，
        #: 界面却一直卡在加载中」。
        self._cancel_event = threading.Event()

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

    def working_dir(self) -> str | None:
        """子进程的工作目录；None = 继承父进程 cwd。

        为什么必须有这个钩子：不少本地引擎依赖 **相对路径** 启动。最典型的
        GPT-SoVITS：GPT_SoVITS/sv.py 里做
            sys.path.append(f"{os.getcwd()}/GPT_SoVITS/eres2net")
        并用相对权重路径；cwd 不对就会
            ModuleNotFoundError: No module named 'ERes2NetV2'
        历史上本类从未把 cwd 传给 Popen（HTTPServiceLauncher 收下了 cwd 参数
        却始终是空操作），导致这类引擎只能靠 argv 层的 --cwd / env -C 绕过去。
        这里补上真正的支持，让所有 launcher 都能正确设置 cwd。
        """
        return None

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

    @property
    def cancel_requested(self) -> bool:
        """最近一次启动是否被 stop() 取消（供上层区分「取消」与「失败」）。"""
        return self._cancel_event.is_set()

    def is_ready(self, timeout: float = 2.0) -> bool:
        """通过 HTTP 端点探测服务是否已完全就绪提供推理服务。"""
        headers = {}
        key = self.api_key()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        for path in self.ready_paths:
            try:
                # 必须走忽略代理的**探测专用**会话：
                #   * 忽略代理 —— ALL_PROXY 会把 localhost 请求也交给代理，
                #     代理不可用时探针 100% 失败，模型已就绪却永远判不出来；
                #   * 专用会话 —— 流式响应提前 close 会弄脏共享连接池，
                #     复用脏连接的探测会误判为"未就绪"，引发无谓的重新拉起。
                resp = local_probe_session().get(
                    f"{self.base_url}{path}", headers=headers, timeout=timeout
                )
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
        """启动引擎实例（可选等待就绪）。

        取消语义：等待就绪期间若另一线程调用 stop()（用户在 UI 上点「终止加载」，
        或 /models/unload 抢先到达），本次启动会抛出 LaunchCancelled 干净退出，
        而不是继续对已被置空的 _process 取属性。
        """
        # 每次启动都重置取消信号：stop() 会置位，本轮 start() 据此干净退出。
        self._cancel_event.clear()

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

            # 走专用常驻线程：PDEATHSIG 绑定的是 fork 线程，
            # 用事件循环的默认线程池会在 loop 关闭时把模型一起带走。
            # 工作目录：相对路径敏感型引擎（GPT-SoVITS 等）依赖它，缺了会 import 失败。
            sub_cwd = self.working_dir()
            if sub_cwd and not os.path.isdir(sub_cwd):
                raise FileNotFoundError(
                    f"{self.engine_label} 的工作目录不存在: {sub_cwd}"
                )
            self.last_cwd = sub_cwd

            self._process = _popen_on_launch_thread(
                cmd,
                stdout=stdout_dest,
                stderr=stderr_dest,
                env=sub_env,
                cwd=sub_cwd,
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

        # 就地捕获进程句柄：等待期间别的线程可能调用 stop() 把 self._process
        # 置空（用户点「终止加载」），此时不能再对 self._process 取属性。
        proc = self._process

        start_time = time.time()
        logger.info("等待 %s 服务就绪 (%s, 超时 %ds)...", self.engine_label, self.base_url, timeout)
        while time.time() - start_time < timeout:
            # 1) 已被显式取消（stop()/unload 抢在前面）
            if self._cancel_event.is_set() or self._process is not proc:
                logger.info("%s 启动被取消（进程已停止）: %s", self.engine_label, self.base_url)
                # 修复（严重）：stop() 可能在 self._process 赋值之前执行
                # （当时 process 还是 None，stop 直接返回 True）。若这里只抛
                # LaunchCancelled 而不清理，刚拉起的子进程会变成孤儿——调度器
                # 侧 mark_unloaded 认为模型未加载、永不回收，进程一直占着
                # 显存/端口直到自然退出。必须就地杀掉并清理句柄。
                if proc is not None and proc.poll() is None:
                    try:
                        kill_process_tree(proc, timeout=15.0)
                    except Exception:  # noqa: BLE001
                        logger.exception("%s 取消启动时清理子进程失败", self.engine_label)
                _ACTIVE_LAUNCHERS.discard(self)
                self._process = None
                if self._log_fp:
                    with contextlib.suppress(Exception):
                        self._log_fp.close()
                    self._log_fp = None
                raise LaunchCancelled(
                    f"{self.engine_label} 启动已取消：进程在就绪前被停止"
                )

            # 2) 子进程自己退出了（崩溃 / 参数错误 / 显存不足）
            if proc.poll() is not None:
                ret = proc.returncode
                logger.error("%s 进程异常退出，退出码: %s", self.engine_label, ret)
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

            # 用 Event.wait 代替 sleep：被取消时立即醒来，而不是再等半个周期
            self._cancel_event.wait(0.5)

        self.stop()
        raise TimeoutError(
            f"{self.engine_label} 启动超时 ({timeout}s)，服务未在 {self.base_url} 就绪"
        )

    def stop(self, timeout: float = 15.0) -> bool:
        """优雅关闭引擎进程（整进程组）并释放显存。

        同时置位取消信号：若此刻有 start() 正在等待就绪（用户在加载途中点
        「终止」），它会立刻醒来并以 LaunchCancelled 退出，而不是在下一轮循环里
        对已被置空的 self._process 调用 poll() 而抛 AttributeError。
        """
        self._cancel_event.set()

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
        on_status: "Callable[..., None] | None" = None,
    ) -> tuple[Callable[[], bool], Callable[[], bool]]:
        """生成与 ModelScheduler 对接的 (load_fn, unload_fn) 钩子回调。

        on_status: 可选状态回调（loading/loaded/failed）。加载现在可能由
        调度器租约路径触发（invoke 的 use() / 流式租约），此时尚未走到
        客户端 _ensure_launcher_running 的上报点——不在这里上报的话，
        经调度器加载时前端模型列表/显存页收不到 loading→loaded 状态。
        """
        label = self.engine_label

        def _notify(status: str, **extra: Any) -> None:
            if on_status is None:
                return
            try:
                on_status(status, **extra)
            except Exception:  # noqa: BLE001 - 状态上报失败不能影响加载
                logger.debug("%s 状态回调失败: %s", label, status, exc_info=True)

        def _load() -> bool:
            try:
                _notify("loading")
                ok = self.start(wait_ready=True, timeout=float(load_timeout))
                _notify("loaded" if ok else "failed", error=None if ok else "启动返回失败")
                return ok
            except Exception as e:  # noqa: BLE001 - 钩子不能抛，返回 False 让调度器收尾
                logger.error("ModelScheduler 调用 %s load_fn 失败: %s", label, e)
                _notify("failed", error=str(e))
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
