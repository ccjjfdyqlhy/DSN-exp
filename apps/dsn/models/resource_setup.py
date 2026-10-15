# DSN-exp/apps/dsn/models/resource_setup.py
# 把 DSN 的语音资源（ASR / TTS）注册进 harness 资源池。
#
# 范围严格限定为 ASR + TTS 两类资源；不涉及视觉/OCR/媒体等其它种类。
#
# 两类资源的形态：
#   * ASR —— 进程内 FunASR 模型（ASREngine），用 InProcessModelLauncher 托管；
#            resident=True，常驻显存，不因插槽压力被驱逐。
#   * TTS —— GPT-SoVITS HTTP 服务（默认 127.0.0.1:9880）：
#             TTS_AUTOSTART=True（默认）= **托管模式**，资源池负责拉起/停止；
#             TTS_AUTOSTART=False      = adopt 模式，只接入既有服务、绝不拉起。
#             托管模式由 TTS_LAUNCH_MODE 选择启动策略：
#               conda（默认）—— conda run -n GPTSoVits，依赖齐全，开箱可用；
#               command      —— 裸 argv（旧的 sys.executable 行为，易缺依赖）；
#               docker       —— detached 容器（DockerServiceLauncher）。
#
# 幂等：重复调用不会重复注册，也不会重建已有资源池。

from __future__ import annotations

import logging
import os
import sys
import threading
from typing import Optional

from infra.resources import (
    DockerServiceLauncher,
    HTTPServiceLauncher,
    InProcessModelLauncher,
    LaunchMode,
    LaunchSpec,
    ResourceKind,
    ResourcePool,
    ResourceSpec,
    conda_env_dir,
    conda_env_exists,
    env_python,
    resolve_conda_exe,
)

from apps.dsn.config import Config
from apps.dsn.models.asr_engine import ASREngine

logger = logging.getLogger(__name__)

#: 资源名（池内唯一标识）
ASR_RESOURCE = "asr"
TTS_RESOURCE = "tts"

#: TTS 服务端目录（GPT-SoVITS 的 api.py 入口）
TTS_SERVER_DIR = "/home/darkstar/TTS"
TTS_SERVER_ENTRY = "api.py"

_lock = threading.RLock()
_state: dict = {"pool": None, "asr_engine": None, "tts_launcher": None, "asr_launcher": None}


def _build_asr(pool: ResourcePool) -> None:
    """注册 ASR（进程内 FunASR 模型）。"""
    engine = ASREngine(device=Config.ASR_DEVICE, gpu_id=Config.ASR_GPU_ID)
    launcher = InProcessModelLauncher(
        name=ASR_RESOURCE,
        loader=engine.load,
        unloader=lambda _model: engine.unload(),
        device=engine.resolve_device(),
        vram_estimate_mb=1500,
    )
    load_fn, unload_fn = launcher.create_scheduler_hooks(
        load_timeout=int(getattr(Config, "ASR_LOAD_TIMEOUT", 300))
    )
    pool.register_resource(
        ASR_RESOURCE,
        ResourceSpec(
            kind=ResourceKind.ASR,
            display_name="FunASR 语音识别",
            priority=60,
            resident=True,
            base_url="",
            endpoint="",
            vram_estimate_mb=1500,
            extra={"engine": "local"},
        ),
        load_fn,
        unload_fn,
    )
    _state["asr_engine"] = engine
    _state["asr_launcher"] = launcher


def _split_args(raw: str) -> list[str]:
    """把 "--gpus all -v /x:/y" 这类字符串拆成 argv（shlex 解析）。"""
    import shlex

    return shlex.split(str(raw or ""))


def _docker_ports(port: str) -> list[str]:
    """解析 TTS_DOCKER_PORTS；留空则把服务端口原样映射到宿主。"""
    raw = str(getattr(Config, "TTS_DOCKER_PORTS", "") or "").strip()
    if not raw:
        return [f"{port}:{port}"]
    return [p.strip() for p in raw.split(",") if p.strip()]


def _tts_launch_spec() -> Optional[LaunchSpec]:
    """合成 GPT-SoVITS 服务的启动策略；adopt 模式返回 None。

    三种模式的差异只在「怎么把 api.py 拉起来」：
      * conda  —— conda run -n GPTSoVits --no-capture-output <env python> api.py ...
                  （默认。GPT-SoVITS 的依赖只装在 GPTSoVits 环境里）
      * command —— 裸 argv，沿用 TTS_PYTHON / 当前解释器（旧行为）
      * docker —— detached 容器，由 DockerServiceLauncher 管理

    注意 device 语义的两层区分：
      * `-d` 传给 api.py，取值是 "cuda" / "cpu"（服务端自己的设备选择）；
      * launcher 构造参数 `device` 只用于设置 CUDA_VISIBLE_DEVICES，
        必须是物理卡号（"0"）或留空；传 "cuda" 会让 CUDA 初始化失败。
    """
    if not getattr(Config, "TTS_AUTOSTART", False):
        return None

    mode = LaunchMode.parse(getattr(Config, "TTS_LAUNCH_MODE", LaunchMode.CONDA.value))
    server_dir = getattr(Config, "TTS_SERVER_DIR", TTS_SERVER_DIR)
    entry = os.path.join(server_dir, TTS_SERVER_ENTRY)
    port = str(getattr(Config, "TTS_PORT", 9880))
    device = str(getattr(Config, "TTS_DEVICE", "cuda"))

    if mode is LaunchMode.CONDA:
        conda_env = getattr(Config, "TTS_CONDA_ENV", "GPTSoVits")
        conda_exe = getattr(Config, "TTS_CONDA_EXE", "conda") or "conda"
        # 把 argv[0] 固定为目标环境的解释器；找不到时退回 "python"，
        # 由 `conda run` 的目标环境 PATH 解析（仍然比 base env 正确）。
        python_exe = env_python(conda_env, conda_exe) or "python"
        return LaunchSpec(
            mode=LaunchMode.CONDA,
            command=[python_exe, entry, "-p", port, "-d", device],
            cwd=server_dir,
            conda_env=conda_env,
            conda_exe=conda_exe,
            conda_no_capture=bool(getattr(Config, "TTS_CONDA_NO_CAPTURE", True)),
        )

    if mode is LaunchMode.DOCKER:
        image = str(getattr(Config, "TTS_DOCKER_IMAGE", "") or "").strip()
        if not image:
            raise ValueError(
                "TTS_LAUNCH_MODE=docker 但未配置 TTS_DOCKER_IMAGE。"
                "请设置镜像名，或改用 TTS_LAUNCH_MODE=conda。"
            )
        return LaunchSpec(
            mode=LaunchMode.DOCKER,
            # 容器内命令：镜像的 WORKDIR 应包含 api.py
            command=["python", os.path.basename(entry), "-p", port, "-d", device],
            docker_image=image,
            docker_container_name=getattr(Config, "TTS_DOCKER_NAME", "dsn-tts"),
            docker_args=_split_args(getattr(Config, "TTS_DOCKER_ARGS", "")),
            docker_ports=_docker_ports(port),
            docker_pull=bool(getattr(Config, "TTS_DOCKER_PULL", False)),
            docker_rm_on_stop=bool(getattr(Config, "TTS_DOCKER_RM_ON_STOP", False)),
        )

    # COMMAND：旧行为（TTS_PYTHON 或当前解释器）
    python_exe = getattr(Config, "TTS_PYTHON", None) or sys.executable
    return LaunchSpec(
        mode=LaunchMode.COMMAND,
        command=[python_exe, entry, "-p", port, "-d", device],
        cwd=server_dir,
    )


def _build_tts(pool: ResourcePool) -> None:
    """注册 TTS（GPT-SoVITS HTTP 服务）。

    默认 TTS_AUTOSTART=True = **托管模式**：资源池负责拉起/停止服务，
    从而真正"可托管"。设为 false 则退化为 adopt 模式：只探测既有服务，
    绝不拉起也绝不杀死外部进程。
    """
    base_url = Config.TTS_BASE_URL
    spec = _tts_launch_spec()
    managed = spec is not None
    server_dir = getattr(Config, "TTS_SERVER_DIR", TTS_SERVER_DIR)

    # GPU 编号只用于 CUDA_VISIBLE_DEVICES；留空则不限制。
    # 注意：绝不传 "cuda" —— 只有物理卡号才合法。
    gpu_id = (getattr(Config, "TTS_GPU_ID", "") or "").strip() or None

    # 就绪判定：GPT-SoVITS 的 GET / 缺参数时合法返回 400，需放宽为 <500。
    _ready_below = int(getattr(Config, "TTS_READY_ACCEPT_BELOW", 500) or 0) or None

    if managed and spec.mode is LaunchMode.DOCKER:
        launcher = DockerServiceLauncher(
            name=TTS_RESOURCE,
            base_url=base_url,
            ready_path="/",
            launch_spec=spec,
            ready_accept_below=_ready_below,
        )
    else:
        launcher = HTTPServiceLauncher(
            name=TTS_RESOURCE,
            base_url=base_url,
            ready_path="/",
            launch_spec=spec,
            cwd=server_dir if managed else None,
            device=gpu_id,
            ready_accept_below=_ready_below,
        )

    if managed and getattr(Config, "TTS_PREFLIGHT", True):
        # 预检入口脚本存在，给出可操作的中文错误而不是让 Popen 抛底噪。
        entry = os.path.join(server_dir, TTS_SERVER_ENTRY)
        if not os.path.isfile(entry):
            raise FileNotFoundError(
                f"TTS 入口脚本不存在: {entry}。请检查 TTS_SERVER_DIR，"
                f"或设置 TTS_AUTOSTART=false 改为只接入既有服务。"
            )
        # conda 模式：环境缺失时提前给出清晰的中文告警（真正的硬失败在
        # launcher.preflight()，此处只让问题更早暴露）。
        if spec.mode is LaunchMode.CONDA and not conda_env_exists(
            spec.conda_env, spec.conda_exe
        ):
            logger.warning(
                "TTS conda 环境 %r 不存在（期望目录: %s）。启动时会报错；"
                "请用 conda env list 确认，或设置 TTS_CONDA_ENV / "
                "TTS_LAUNCH_MODE=command。conda=%s",
                spec.conda_env,
                conda_env_dir(spec.conda_env, spec.conda_exe),
                resolve_conda_exe(spec.conda_exe),
            )

    load_fn, unload_fn = launcher.create_scheduler_hooks(
        load_timeout=int(getattr(Config, "TTS_LOAD_TIMEOUT", 300))
    )
    pool.register_resource(
        TTS_RESOURCE,
        ResourceSpec(
            kind=ResourceKind.TTS,
            display_name="GPT-SoVITS 语音合成",
            base_url=base_url,
            endpoint="/",
            priority=70,
            # resident=True：TTS 是重量级长驻服务（启动需加载 GPT+SoVITS 权重，
            # 分钟级）。绝不能 immediate —— immediate 会在 ensure_running 的
            # 临时取用归还时立刻把它卸载，导致每次合成都重新拉起整个服务。
            # 常驻语义 = 启动一次后保持运行，由用户显式 stop_resource 关闭。
            resident=True,
            immediate=False,
            vram_estimate_mb=2048,
            extra={
                "engine": "local",
                "managed": managed,
                "adopt": not managed,
                "launch_mode": spec.mode.value if managed else "adopt",
            },
        ),
        load_fn,
        unload_fn,
    )
    _state["tts_launcher"] = launcher


def setup_dsn_resources(pool: Optional[ResourcePool] = None) -> ResourcePool:
    """幂等地注册 DSN 的 ASR / TTS 资源，返回资源池。

    只有 Config.ASR_ENABLED / Config.TTS_ENABLED 为真时才注册对应资源；
    两者都关闭时仍会返回一个（空的）资源池，调用方可安全持有。
    """
    with _lock:
        if pool is None:
            pool = _state.get("pool")
            if pool is None:
                # 外周任务专用任务槽：与 LLM 插槽隔离的独立配额。
                pool = ResourcePool(
                    max_concurrent=int(
                        getattr(Config, "PERIPHERAL_TASK_SLOTS", None)
                        or getattr(Config, "RESOURCE_POOL_SLOTS", 2)
                    )
                )
                _state["pool"] = pool
        else:
            _state["pool"] = pool

        if Config.ASR_ENABLED and pool.get_spec(ASR_RESOURCE) is None:
            try:
                _build_asr(pool)
            except Exception:  # noqa: BLE001 - ASR 注册失败不应中断启动
                logger.exception("ASR 资源注册失败")
        if Config.TTS_ENABLED and pool.get_spec(TTS_RESOURCE) is None:
            try:
                _build_tts(pool)
            except Exception:  # noqa: BLE001
                logger.exception("TTS 资源注册失败")
        return pool


def get_dsn_pool() -> Optional[ResourcePool]:
    """返回已初始化的资源池（未初始化则 None）。"""
    return _state.get("pool")


def get_asr_engine() -> Optional[ASREngine]:
    """返回已注册的 ASR 引擎（供 boot.py 取原始模型对象）。"""
    return _state.get("asr_engine")


def reset_dsn_resources() -> None:
    """清空内部状态（测试用）。"""
    with _lock:
        _state.update({"pool": None, "asr_engine": None, "tts_launcher": None, "asr_launcher": None})
