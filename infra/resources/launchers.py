# infra/resources/launchers.py
# ASR / TTS 资源启动器 —— 两类本地语音资源的生命周期管理适配层。
#
# 两类资源形态迥异，但都归一到 infra.orchestrator.local_engine.LocalServerLauncher
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

import contextlib
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

import requests

from ..orchestrator.base import local_probe_session
from ..orchestrator.local_engine import LocalServerLauncher, kill_process_tree
from .launch_modes import (
    LaunchMode,
    LaunchSpec,
    conda_env_dir,
    conda_env_exists,
    resolve_conda_exe,
)

logger = logging.getLogger("ResourceLauncher")


class _HttpReadinessMixin:
    """HTTP 就绪探针的共享语义。

    默认沿用 LocalServerLauncher 的严格判定（必须 200）。但本地服务常常
    只有一个"带参数才合法"的业务端点：
      * GPT-SoVITS 的 `GET /` 是推理入口，缺 text 参数时**合法返回 400**；
      * 此时服务其实已经完全启动，严格 200 会让就绪等待一直超时。

    因此当 `ready_accept_below` 被设置（如 500）时，改为"任何响应状态
    < N 即视为就绪" —— 与仓库既有约定一致：
    apps/dsn/audio/infer.py 的 VocalExp.probe() 即 `status_code < 500`。
    """

    #: None = 严格 200；否则接受 status == 200 或 status < ready_accept_below
    ready_accept_below: int | None = None

    def is_ready(self, timeout: float = 2.0) -> bool:
        base_url = getattr(self, "base_url", "") or ""
        if not base_url:
            return False

        if self.ready_accept_below is None:
            # 严格语义：完全复用基类实现
            return super().is_ready(timeout=timeout)

        headers = {}
        key = self.api_key() if hasattr(self, "api_key") else None
        if key:
            headers["Authorization"] = f"Bearer {key}"
        for path in getattr(self, "ready_paths", ("/",)):
            try:
                # 复用忽略代理的探测专用会话（与基类一致）
                resp = local_probe_session().get(
                    f"{base_url}{path}", headers=headers, timeout=timeout
                )
                if resp.status_code == 200 or resp.status_code < self.ready_accept_below:
                    return True
            except requests.RequestException as e:
                logger.debug(
                    "%s 就绪探针 %s 未通过: %s",
                    getattr(self, "engine_label", "服务"), path, e,
                )
        return False


class HTTPServiceLauncher(_HttpReadinessMixin, LocalServerLauncher):
    """已存在的 HTTP 服务（TTS 等）的接入器。

    两种运行模式：

    1. **adopt 模式**（未配置 start_command / launch_spec 无命令）——服务由外部
       拉起，本 launcher 只接入：
         * is_ready() 探测配置的 URL；
         * start() 在服务已应答时直接成功，**不会**因为没有命令可跑而报错；
         * stop() **绝不**杀死外部进程（除非配置了 stop_command）。
       这是"服务已在跑"的常态：GPT-SoVITS 往往由用户自己启动并长期驻留。

    2. **托管模式**（提供了 launch_spec 或旧的 start_command）——由本 launcher 拉起
       子进程。启动策略由 LaunchSpec.mode 决定：
         * COMMAND —— 裸 argv；
         * CONDA   —— `conda run -n <env> --cwd <dir> --no-capture-output <argv>`，
                      即"在指定 conda 环境里运行"；
       （DOCKER 模式请用 DockerServiceLauncher。）
         * start() 走基类的子进程拉起 + 就绪等待；
         * stop() 先执行 stop_command（若有），随后仍会终止本进程持有的子进程。

    关于 cwd：LocalServerLauncher 不会把 cwd 传给 Popen，因此本类在 build_command()
    里通过 `conda run --cwd` / `env -C` 让工作目录真正生效（见 LaunchSpec.build_argv）。
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
        launch_spec: LaunchSpec | None = None,
        ready_accept_below: int | None = None,
    ):
        super().__init__(log_file=log_file)
        self.name = name
        self._base_url = (base_url or "").rstrip("/")
        self.ready_path = ready_path or "/"
        #: 就绪判定放宽上限（None = 严格 200；500 = 接受任何 <500 的响应）
        self.ready_accept_below = ready_accept_below

        # 启动策略：显式 launch_spec 优先；否则把旧的 start_command 关键字
        # 归一成一个 COMMAND 模式的 LaunchSpec —— 老调用方无需改动。
        if launch_spec is not None:
            if not isinstance(launch_spec, LaunchSpec):
                raise TypeError(
                    f"launch_spec 必须是 LaunchSpec，收到 {type(launch_spec).__name__}"
                )
            if launch_spec.mode is LaunchMode.DOCKER:
                raise ValueError(
                    f"资源 {name}: DOCKER 模式请使用 DockerServiceLauncher，"
                    f"而非 HTTPServiceLauncher"
                )
            spec = launch_spec
            if spec.command is None and start_command:
                spec.command = [str(c) for c in start_command]
        else:
            spec = LaunchSpec(
                mode=LaunchMode.COMMAND,
                command=[str(c) for c in start_command] if start_command else None,
                cwd=cwd,
                env=dict(env) if env else {},
            )
        self.launch_spec = spec

        self.start_command = list(spec.command) if spec.command else None
        self.stop_command = list(stop_command) if stop_command else None
        self.cwd = cwd if cwd is not None else spec.cwd
        self.device = device
        #: 额外环境变量（如 CUDA_VISIBLE_DEVICES）
        self._extra_env: dict = dict(spec.env) if spec.env else {}
        if env:
            self._extra_env.update({str(k): str(v) for k, v in env.items()})
        #: 就绪探针路径必须包含配置的 ready_path
        self.ready_paths: tuple[str, ...] = (self.ready_path,)

    # ── 模式判定 ──

    @property
    def adopt_mode(self) -> bool:
        """是否处于「接入既有服务」模式（无需拉起的命令/镜像）。"""
        return not self.launch_spec.is_managed()

    @property
    def launch_mode(self) -> LaunchMode:
        """当前启动模式（command / conda / docker）。"""
        return self.launch_spec.mode

    # ── 子类差异点 ──

    @property
    def base_url(self) -> str:
        return self._base_url

    def build_command(self) -> list[str]:
        """返回待执行的完整命令行；adopt 模式下为空列表。

        COMMAND 模式即原样 argv；CONDA 模式为
        `conda run -n <env> --no-capture-output <argv>`。
        """
        if self.adopt_mode:
            return []
        return self.launch_spec.build_argv()

    def preflight(self) -> None:
        """启动前校验：可执行文件存在、CONDA 环境可用。

        adopt 模式无事可做（没有命令要跑）。任何失败都抛带中文提示的
        FileNotFoundError，让调用方看到「缺什么、怎么修」。
        """
        if self.adopt_mode:
            logger.info(
                "%s: adopt 模式（无启动命令），仅接入既有服务 %s",
                self.name, self.base_url,
            )
            return

        spec = self.launch_spec

        if spec.mode is LaunchMode.CONDA:
            resolved_conda = resolve_conda_exe(spec.conda_exe)
            if not resolved_conda:
                raise FileNotFoundError(
                    f"资源 {self.name}: 找不到 conda 可执行文件 {spec.conda_exe!r}。"
                    f"请安装 conda，或用 TTS_CONDA_EXE 指定绝对路径，"
                    f"或改用 TTS_LAUNCH_MODE=command。"
                )
            if not conda_env_exists(spec.conda_env, spec.conda_exe):
                env_dir = conda_env_dir(spec.conda_env, spec.conda_exe)
                raise FileNotFoundError(
                    f"资源 {self.name}: conda 环境 {spec.conda_env!r} 不存在"
                    f"（期望目录: {env_dir}）。请用 `conda env list` 确认环境名，"
                    f"或设置 TTS_CONDA_ENV 指向正确环境。"
                )
            logger.info(
                "%s: conda 模式 env=%s conda=%s",
                self.name, spec.conda_env, resolved_conda,
            )

        argv = spec.build_argv()
        if not argv:
            raise ValueError(f"资源 {self.name}: 启动命令为空")
        exe = argv[0]
        resolved = shutil.which(os.path.expanduser(os.path.expandvars(exe)))
        if not resolved and not os.path.exists(os.path.expanduser(exe)):
            raise FileNotFoundError(
                f"资源 {self.name}: 找不到可执行文件 {exe!r}。"
                f"请检查启动命令，或改为 adopt 模式只接入既有服务。"
            )

    def child_env(self) -> dict:
        """子进程额外环境变量：仅托管模式注入 device，adopt 模式不碰环境。"""
        extra = dict(self._extra_env)
        if not self.adopt_mode and self.device:
            extra.setdefault("CUDA_VISIBLE_DEVICES", str(self.device))
        return extra

    def working_dir(self) -> str | None:
        """把配置的 cwd 真正交给 Popen（基类钩子）。

        历史上 cwd 参数只被写进 argv 层的 --cwd / env -C，Popen 本身从不带
        cwd；这里补上，保证无论用哪种启动模式，子进程的工作目录都正确。
        """
        return self.cwd or None

    def describe_target(self) -> str:
        mode = "adopt" if self.adopt_mode else "managed"
        return f"{self.engine_label} {self.name} ({mode}) {self.base_url}"

    # ── 生命周期 ──

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
            "launch_mode": self.launch_mode.value,
            "running": self.is_running(),
            "command": self.command_string(),
        }


class DockerServiceLauncher(_HttpReadinessMixin, LocalServerLauncher):
    """以 detached 容器托管的 HTTP 服务。

    与 HTTPServiceLauncher 的根本差异：`docker run -d` **不会**留下一个可供
    监管的子进程，因此本类**不复用** LocalServerLauncher 的 Popen 生命周期，
    而是用 `docker` CLI 管理容器。仅复用其 HTTP 就绪探针与调度钩子外壳。

    生命周期：
      * 容器已在运行        -> adopt（直接返回 True）
      * 容器存在但已停止    -> `docker start <name>`
      * 容器不存在          -> （可选 pull 后）`docker run -d --name ...`
      * stop                -> `docker stop -t <timeout> <name>`（除非配置否则不 rm）

    所有 docker 调用都带 subprocess 超时，缺 docker 可执行文件或命令失败时
    抛带中文提示的异常，绝不挂死。
    """

    engine_label: str = "Docker 服务"

    def __init__(
        self,
        name: str,
        base_url: str,
        ready_path: str = "/",
        launch_spec: LaunchSpec | None = None,
        docker_image: str | None = None,
        docker_container_name: str | None = None,
        docker_args: list[str] | None = None,
        docker_ports: list[str] | None = None,
        docker_pull: bool = False,
        docker_rm_on_stop: bool = False,
        command: list[str] | None = None,
        docker_exe: str = "docker",
        log_file=None,
        ready_accept_below: int | None = None,
    ):
        super().__init__(log_file=log_file)
        if launch_spec is not None:
            if not isinstance(launch_spec, LaunchSpec):
                raise TypeError(
                    f"launch_spec 必须是 LaunchSpec，收到 {type(launch_spec).__name__}"
                )
            spec = launch_spec
        else:
            spec = LaunchSpec(
                mode=LaunchMode.DOCKER,
                command=list(command) if command else None,
                docker_image=docker_image,
                docker_container_name=docker_container_name,
                docker_args=list(docker_args or []),
                docker_ports=list(docker_ports or []),
                docker_pull=docker_pull,
                docker_rm_on_stop=docker_rm_on_stop,
            )
        if spec.mode is not LaunchMode.DOCKER:
            raise ValueError(
                f"资源 {name}: DockerServiceLauncher 需要 DOCKER 模式的 LaunchSpec，"
                f"收到 {spec.mode.value!r}"
            )
        self.name = name
        self.launch_spec = spec
        self._base_url = (base_url or "").rstrip("/")
        self.ready_path = ready_path or "/"
        self.ready_paths: tuple[str, ...] = (self.ready_path,)
        #: 就绪判定放宽上限（None = 严格 200）
        self.ready_accept_below = ready_accept_below
        self._docker_exe = docker_exe or "docker"
        #: 单条 docker 命令的默认超时（秒）—— 保证任何调用都不会挂死
        self.command_timeout = 60.0

    # ── 基础信息 ──

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def container_name(self) -> str | None:
        return self.launch_spec.docker_container_name

    @property
    def adopt_mode(self) -> bool:
        """DOCKER 模式没有 adopt 概念，恒为 False。"""
        return False

    def build_command(self) -> list[str]:
        """docker run 的完整命令行（供展示；实际由 _docker 执行）。"""
        return self.launch_spec.build_argv()

    # ── docker CLI ──

    def docker_available(self) -> bool:
        """本机是否有可用的 docker 可执行文件。"""
        return self._resolve_docker() is not None

    def _resolve_docker(self) -> str | None:
        exe = self._docker_exe
        expanded = os.path.expanduser(os.path.expandvars(str(exe)))
        if os.path.isabs(expanded) or os.sep in expanded:
            return expanded if os.path.exists(expanded) else None
        return shutil.which(expanded)

    def _docker(
        self, args: list[str], timeout: float | None = None, check: bool = True
    ) -> subprocess.CompletedProcess:
        """执行一条 docker 命令；带超时与清晰的中文错误。"""
        exe = self._resolve_docker()
        if not exe:
            raise FileNotFoundError(
                f"资源 {self.name}: 找不到 docker 可执行文件 {self._docker_exe!r}。"
                f"请安装 docker，或改用 TTS_LAUNCH_MODE=conda / command。"
            )
        cmd = [exe, *[str(a) for a in args]]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout if timeout is not None else self.command_timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(
                f"资源 {self.name}: docker 命令超时（{timeout or self.command_timeout}s）: "
                f"{' '.join(cmd)}"
            ) from e
        if check and proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip().splitlines()
            hint = detail[-1] if detail else f"exit={proc.returncode}"
            raise RuntimeError(
                f"资源 {self.name}: docker 命令失败: {' '.join(cmd)} -> {hint}"
            )
        return proc

    def container_exists(self) -> bool:
        """容器（同名）是否存在。"""
        if not self.container_name:
            return False
        proc = self._docker(
            ["inspect", "-f", "{{.State.Running}}", self.container_name],
            check=False,
        )
        return proc.returncode == 0

    def is_running(self) -> bool:
        """容器是否处于运行状态（`docker inspect` 语义）。"""
        if not self.container_name:
            return False
        proc = self._docker(
            ["inspect", "-f", "{{.State.Running}}", self.container_name],
            check=False,
        )
        if proc.returncode != 0:
            return False
        return proc.stdout.strip().lower() == "true"

    # ── 生命周期 ──

    def preflight(self) -> None:
        """校验 docker 可执行文件、镜像名与容器名。"""
        if not self._resolve_docker():
            raise FileNotFoundError(
                f"资源 {self.name}: 找不到 docker 可执行文件 {self._docker_exe!r}。"
                f"DOCKER 模式需要本机安装并可达 docker。"
            )
        spec = self.launch_spec
        if not spec.docker_image:
            raise ValueError(
                f"资源 {self.name}: DOCKER 模式必须配置 docker_image"
                f"（例如 TTS_DOCKER_IMAGE）。"
            )
        if not spec.docker_container_name:
            raise ValueError(
                f"资源 {self.name}: DOCKER 模式必须配置 docker_container_name，"
                f"否则无法可靠地 start/stop。"
            )

    def start(
        self,
        wait_ready: bool = True,
        timeout: float = 180.0,
        progress_callback: Optional[Callable[[float], None]] = None,
    ) -> bool:
        """确保容器在运行，并在 wait_ready 时就绪探测通过后返回 True。"""
        self.preflight()
        spec = self.launch_spec
        name = spec.docker_container_name

        if self.is_running():
            logger.info("%s: 容器 %s 已在运行，直接接入", self.engine_label, name)
        elif self.container_exists():
            logger.info("%s: 容器 %s 存在但已停止，执行 docker start", self.engine_label, name)
            self._docker(["start", name])
        else:
            if spec.docker_pull:
                logger.info("%s: 拉取镜像 %s ...", self.engine_label, spec.docker_image)
                self._docker(["pull", spec.docker_image], timeout=max(timeout, 600.0))
            argv = spec.docker_run_args()
            logger.info("%s: 创建容器: docker %s", self.engine_label, " ".join(argv))
            self._docker(argv, timeout=max(timeout, 120.0))

        if not wait_ready:
            return True

        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.is_ready(timeout=1.5):
                logger.info(
                    "%s: 容器 %s 已就绪 (耗时 %.1fs)",
                    self.engine_label, name, time.time() - start_time,
                )
                if progress_callback:
                    with contextlib.suppress(Exception):
                        progress_callback(1.0)
                return True
            if progress_callback:
                elapsed = time.time() - start_time
                with contextlib.suppress(Exception):
                    progress_callback(min(0.95, round(1.0 - (1.0 / (1.0 + elapsed / 10.0)), 2)))
            time.sleep(0.5)

        raise TimeoutError(
            f"{self.engine_label} 容器 {name} 启动超时 ({timeout}s)，"
            f"{self.base_url} 未就绪"
        )

    def stop(self, timeout: float = 15.0) -> bool:
        """停止容器（默认不删除）。"""
        spec = self.launch_spec
        name = spec.docker_container_name
        if not name or not self.container_exists():
            logger.info("%s: 容器 %s 不存在，无需停止", self.engine_label, name)
            return True
        logger.info("%s: 停止容器 %s", self.engine_label, name)
        self._docker(["stop", "-t", str(int(timeout)), name], timeout=timeout + 30.0)
        if spec.docker_rm_on_stop:
            logger.info("%s: 删除容器 %s", self.engine_label, name)
            self._docker(["rm", "-f", name], check=False)
        return True

    def describe(self) -> dict:
        """资源视图（供 ResourcePool 状态接口使用）。"""
        spec = self.launch_spec
        return {
            "name": self.name,
            "base_url": self.base_url,
            "ready_path": self.ready_path,
            "mode": "docker",
            "launch_mode": LaunchMode.DOCKER.value,
            "image": spec.docker_image,
            "container": spec.docker_container_name,
            "running": self.is_running(),
            "command": self.launch_spec.describe_argv(),
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
