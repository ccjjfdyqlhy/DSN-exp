# apps/dsn_study/models/resource_setup.py
# 把 dsn_study 的语音资源（TTS）注册进 **infra 资源池**（infra.resources.ResourcePool）。
#
# 设计要点：
#   * 资源调度完全交给 infra —— 资源池继承 ModelScheduler，自带 FIFO 队列、
#     插槽上限、优先级驱逐、resident 常驻保护；dsn_study 只做「注册 + 取租约」。
#   * GPT-SoVITS 依赖在 **conda 环境 GPTSoVits** 里，必须用该环境的解释器启动，
#     否则会缺 fast_langdetect / split_lang / peft / opencc 等依赖而启动失败。
#     因此默认 TTS_LAUNCH_MODE=conda，由 infra 的 LaunchMode.CONDA 拼出
#     `conda run -n GPTSoVits --cwd <dir> --no-capture-output <env python> api.py ...`。
#   * TTS 是重量级长驻服务（加载 GPT+SoVITS 权重，分钟级），故 resident=True：
#     绝不能 immediate，否则每次合成都会把整个服务卸载重拉。
#   * TTS_AUTOSTART=false → adopt 模式：只接入既有服务，绝不拉起/杀进程。

from __future__ import annotations

import logging
import os
import threading
from typing import Optional

from infra.resources import (
    HTTPServiceLauncher,
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

from apps.dsn_study.config import Config

logger = logging.getLogger("StudyResources")

#: 资源名（池内唯一标识）
TTS_RESOURCE = "tts"
#: ASR 资源名（FunASR 旁路服务，进程外）
ASR_RESOURCE = "asr"

#: GPT-SoVITS 服务端目录与入口（与参考实现一致）
TTS_SERVER_DIR = "/home/darkstar/TTS"
TTS_SERVER_ENTRY = "api.py"

_lock = threading.RLock()
_state: dict = {"pool": None, "tts_launcher": None, "asr_launcher": None}


def _tts_launch_spec() -> Optional[LaunchSpec]:
    """合成 GPT-SoVITS 的启动策略；adopt 模式返回 None。"""
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
        # argv[0] 固定为目标环境的解释器（"独立 Python"），避免 PATH 歧义；
        # 找不到时退回 "python"，由 conda run 的目标环境 PATH 解析。
        python_exe = env_python(conda_env, conda_exe) or "python"
        return LaunchSpec(
            mode=LaunchMode.CONDA,
            command=[python_exe, entry, "-p", port, "-d", device],
            cwd=server_dir,
            conda_env=conda_env,
            conda_exe=conda_exe,
            conda_no_capture=bool(getattr(Config, "TTS_CONDA_NO_CAPTURE", True)),
        )

    # COMMAND：用显式解释器直接拉起（不再依赖 conda）
    python_exe = getattr(Config, "TTS_PYTHON", None) or os.sys.executable
    return LaunchSpec(
        mode=LaunchMode.COMMAND,
        command=[python_exe, entry, "-p", port, "-d", device],
        cwd=server_dir,
    )


def _asr_device() -> str:
    """解析推理设备。

    ASR_GPU_ID 的作用**只是** CUDA_VISIBLE_DEVICES（见下方 launcher 的
    device=gpu_id，注释也写明"必须是物理卡号"）。子进程被钉到单卡之后，
    进程内可见的序号是 0 —— 再把物理卡号拼进 --device（如 cuda:1），
    就会 "CUDA error: invalid device ordinal"，模型根本加载不了。

    所以：ASR_GPU_ID 有值 → --device 只给 "cuda"（进程内第 0 张就是那一张）；
    ASR_GPU_ID 为空而 ASR_DEVICE 自带序号 → 原样透传（进程能看到全部卡）。
    （TTS 侧一直是对的：TTS_GPU_ID 为空，--device 只传 "cuda"。）
    """
    device = getattr(Config, "ASR_DEVICE", "cuda") or "cuda"
    gpu_id = (getattr(Config, "ASR_GPU_ID", "") or "").strip()
    if gpu_id and device.startswith("cuda") and ":" not in device:
        device = "cuda"   # 卡号由 CUDA_VISIBLE_DEVICES 负责，此处不再带序号
    return device


def _asr_port() -> str:
    """sidecar 监听端口。

    **以 ASR_BASE_URL 为准**（从 URL 里解析端口），只在解析不出时才回退 ASR_PORT。
    原因：base_url 与实际监听端口必须一致 —— 否则资源池会去探测一个
    根本没人在监的端口，ensure_running 一直等到加载超时。
    （ASR_PORT 仅在 ASR_BASE_URL 未指定端口时作为兜底。）
    """
    base_url = getattr(Config, "ASR_BASE_URL", "") or ""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(base_url)
        if parsed.port:
            return str(parsed.port)
    except Exception:  # noqa: BLE001 —— 解析失败就退回配置项
        pass
    return str(getattr(Config, "ASR_PORT", 9881))


def _asr_launch_spec() -> Optional[LaunchSpec]:
    """合成 ASR sidecar 的启动策略；adopt 模式返回 None。"""
    if not getattr(Config, "ASR_AUTOSTART", False):
        return None

    mode = LaunchMode.parse(getattr(Config, "ASR_LAUNCH_MODE", LaunchMode.CONDA.value))
    server_dir = getattr(Config, "ASR_SERVER_DIR", "")
    entry = os.path.join(server_dir, getattr(Config, "ASR_SERVER_ENTRY", "asr_server.py"))
    port = _asr_port()
    device = _asr_device()

    if mode is LaunchMode.CONDA:
        conda_env = getattr(Config, "ASR_CONDA_ENV", "GPTSoVits")
        conda_exe = getattr(Config, "ASR_CONDA_EXE", "conda") or "conda"
        # argv[0] 固定为目标环境的解释器（"独立 Python"），避免 PATH 歧义；
        # 找不到时退回 "python"，由 conda run 的目标环境 PATH 解析。
        python_exe = env_python(conda_env, conda_exe) or "python"
        return LaunchSpec(
            mode=LaunchMode.CONDA,
            command=[python_exe, entry, "--port", port, "--device", device],
            cwd=server_dir,
            conda_env=conda_env,
            conda_exe=conda_exe,
            conda_no_capture=bool(getattr(Config, "ASR_CONDA_NO_CAPTURE", True)),
        )

    # COMMAND：用显式解释器直接拉起（不再依赖 conda）
    python_exe = getattr(Config, "ASR_PYTHON", None) or os.sys.executable
    return LaunchSpec(
        mode=LaunchMode.COMMAND,
        command=[python_exe, entry, "--port", port, "--device", device],
        cwd=server_dir,
    )


def _build_asr(pool: ResourcePool) -> None:
    """把 ASR sidecar 注册进资源池。

    与 TTS 同构：sidecar 是独立进程（FunASR 的 torch 依赖只在 conda 环境里），
    由 infra 的 HTTPServiceLauncher + LaunchSpec 拉起并探活。
    """
    base_url = getattr(Config, "ASR_BASE_URL", "http://127.0.0.1:9881")
    spec = _asr_launch_spec()
    managed = spec is not None
    server_dir = getattr(Config, "ASR_SERVER_DIR", "")

    # 只用于 CUDA_VISIBLE_DEVICES；必须是物理卡号，留空则不限制。
    gpu_id = (getattr(Config, "ASR_GPU_ID", "") or "").strip() or None

    launcher = HTTPServiceLauncher(
        name=ASR_RESOURCE,
        base_url=base_url,
        ready_path="/health",
        launch_spec=spec,
        cwd=server_dir if managed else None,
        device=gpu_id,
    )

    if managed and getattr(Config, "ASR_PREFLIGHT", True):
        entry = os.path.join(server_dir, getattr(Config, "ASR_SERVER_ENTRY", "asr_server.py"))
        if not os.path.isfile(entry):
            raise FileNotFoundError(
                "ASR 入口脚本不存在: %s。请检查 ASR_SERVER_DIR，"
                "或设置 ASR_AUTOSTART=false 改为只接入既有服务。" % entry)
        if spec.mode is LaunchMode.CONDA and not conda_env_exists(
                spec.conda_env, spec.conda_exe):
            logger.warning(
                "ASR conda 环境 %r 不存在（期望目录: %s）。启动时会报错；"
                "请用 conda env list 确认，或设置 ASR_CONDA_ENV / "
                "ASR_LAUNCH_MODE=command。conda=%s",
                spec.conda_env,
                conda_env_dir(spec.conda_env, spec.conda_exe),
                resolve_conda_exe(spec.conda_exe))

    load_fn, unload_fn = launcher.create_scheduler_hooks(
        load_timeout=int(getattr(Config, "ASR_LOAD_TIMEOUT", 600)))
    pool.register_resource(
        ASR_RESOURCE,
        ResourceSpec(
            kind=ResourceKind.ASR,
            display_name="FunASR 语音识别",
            base_url=base_url,
            endpoint="/asr",
            priority=60,
            # resident=True：重量级长驻服务（torch + 模型权重），绝不 immediate
            # —— immediate 会在归还租约时立刻卸载，每次识别都重拉整个服务。
            resident=True,
            immediate=False,
            vram_estimate_mb=1500,
            extra={
                "engine": "sidecar",
                "managed": managed,
                "adopt": not managed,
                "launch_mode": spec.mode.value if managed else "adopt",
            },
        ),
        load_fn,
        unload_fn,
    )
    _state["asr_launcher"] = launcher
    logger.info("ASR 资源已注册: %s（模式=%s）", base_url,
                spec.mode.value if managed else "adopt")


def _build_tts(pool: ResourcePool) -> None:
    """把 TTS 注册进资源池。"""
    base_url = getattr(Config, "TTS_BASE_URL", "http://127.0.0.1:9880")
    spec = _tts_launch_spec()
    managed = spec is not None
    server_dir = getattr(Config, "TTS_SERVER_DIR", TTS_SERVER_DIR)

    # GPU 编号只用于 CUDA_VISIBLE_DEVICES；必须是物理卡号，留空则不限制。
    gpu_id = (getattr(Config, "TTS_GPU_ID", "") or "").strip() or None

    # 就绪判定：GPT-SoVITS 的 GET / 缺参数时合法返回 400，需放宽为 <500。
    ready_below = int(getattr(Config, "TTS_READY_ACCEPT_BELOW", 500) or 0) or None

    launcher = HTTPServiceLauncher(
        name=TTS_RESOURCE,
        base_url=base_url,
        ready_path="/",
        launch_spec=spec,
        cwd=server_dir if managed else None,
        device=gpu_id,
        ready_accept_below=ready_below,
    )

    if managed and getattr(Config, "TTS_PREFLIGHT", True):
        entry = os.path.join(server_dir, TTS_SERVER_ENTRY)
        if not os.path.isfile(entry):
            raise FileNotFoundError(
                "TTS 入口脚本不存在: %s。请检查 TTS_SERVER_DIR，"
                "或设置 TTS_AUTOSTART=false 改为只接入既有服务。" % entry)
        if spec.mode is LaunchMode.CONDA and not conda_env_exists(
            spec.conda_env, spec.conda_exe):
            logger.warning(
                "TTS conda 环境 %r 不存在（期望目录: %s）。启动时会报错；"
                "请用 conda env list 确认，或设置 TTS_CONDA_ENV / "
                "TTS_LAUNCH_MODE=command。conda=%s",
                spec.conda_env,
                conda_env_dir(spec.conda_env, spec.conda_exe),
                resolve_conda_exe(spec.conda_exe))

    load_fn, unload_fn = launcher.create_scheduler_hooks(
        load_timeout=int(getattr(Config, "TTS_LOAD_TIMEOUT", 600)))
    pool.register_resource(
        TTS_RESOURCE,
        ResourceSpec(
            kind=ResourceKind.TTS,
            display_name="GPT-SoVITS 语音合成",
            base_url=base_url,
            endpoint="/",
            priority=70,
            # resident=True：重量级长驻服务，绝不能 immediate —— immediate 会在
            # 临时取用归还时立刻卸载，导致每次合成都重拉整个服务。
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
    logger.info("TTS 资源已注册: %s（模式=%s）", base_url,
                spec.mode.value if managed else "adopt")


def setup_study_resources(pool: Optional[ResourcePool] = None) -> ResourcePool:
    """创建（或复用）资源池并注册 TTS。幂等。"""
    with _lock:
        if pool is None:
            pool = _state.get("pool")
        if pool is None:
            pool = ResourcePool(
                max_concurrent=int(getattr(Config, "TTS_MAX_CONCURRENT", 1)),
                default_request_timeout=float(
                    getattr(Config, "TTS_LOAD_TIMEOUT", 600)),
            )
            _state["pool"] = pool
        if TTS_RESOURCE not in [r.get("name") for r in pool.list_resources()]:
            try:
                _build_tts(pool)
            except Exception as e:
                logger.warning("TTS 资源注册失败（语音合成将不可用）: %s", e)
        if ASR_RESOURCE not in [r.get("name") for r in pool.list_resources()]:
            try:
                _build_asr(pool)
            except Exception as e:
                logger.warning("ASR 资源注册失败（语音输入将不可用）: %s", e)
        return pool


def get_study_pool() -> Optional[ResourcePool]:
    """返回当前资源池（未初始化时为 None）。"""
    return _state.get("pool")


def get_tts_launcher():
    """返回 TTS launcher（用于显式 start/stop）。"""
    return _state.get("tts_launcher")


def get_asr_launcher():
    """返回 ASR launcher（用于显式 start/stop）。"""
    return _state.get("asr_launcher")
