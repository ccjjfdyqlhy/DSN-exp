# apps/dsn_study/models/resource_setup.py
# 把 dsn_study 的本地资源（TTS / ASR / VLM）注册进 **infra 资源池**（infra.resources.ResourcePool）。
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
#   * VLM（本地 Bonsai llama-server）是**按需拉起**的：第一次 OCR 时才启动，
#     闲置超过 VLM_IDLE_TIMEOUT 自动停掉释放约 12GB 显存。
#     实现细节见 apps/dsn_study/models/vlm_service.py。

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
#: VLM 资源名（本地 Bonsai llama-server，入库 OCR 用）
VLM_RESOURCE = "vlm"
#: The decision resource (the System-1 model, see
#: infra.resources.decision_service)
DECISION_RESOURCE = "decision"

#: GPT-SoVITS 服务端目录与入口（与参考实现一致）
TTS_SERVER_DIR = "/home/darkstar/TTS"
TTS_SERVER_ENTRY = "api.py"

_lock = threading.RLock()
_state: dict = {"pool": None, "tts_launcher": None, "asr_launcher": None,
                "vlm_launcher": None}


def _idle_timeout(kind: str) -> int:
    """解析某类语音资源的空闲回收阈值（秒）；0 = 不参与回收。

    规则：
      * 池级总开关（RESOURCE_IDLE_SHUTDOWN / 跟随 VOICE_IDLE_SHUTDOWN）关闭
        → 一律 0（谁都不回收）；
      * 语音级开关 VOICE_IDLE_SHUTDOWN 关闭 → 语音资源一律 0；
      * 否则取该资源的独立阈值（TTS_IDLE_TIMEOUT / ASR_IDLE_TIMEOUT），
        未单独配置时跟随统一阈值 VOICE_IDLE_TIMEOUT；
      * 显式设为 0 表示该资源常驻（不回收），可与总开关组合出
        「TTS 回收、ASR 常驻」这类组合。
    """
    from apps.dsn_study.config import resource_idle_shutdown_enabled

    if not resource_idle_shutdown_enabled():
        return 0
    if not getattr(Config, "VOICE_IDLE_SHUTDOWN", False):
        return 0
    key = "TTS_IDLE_TIMEOUT" if kind == "tts" else "ASR_IDLE_TIMEOUT"
    try:
        return max(0, int(getattr(Config, key, 0)))
    except (TypeError, ValueError):
        return 0


def _vlm_idle_timeout() -> int:
    """本地 VLM 的空闲回收阈值（秒）；0 = 常驻不回收。

    受两级开关约束：池级总开关 + VLM 自己的 VLM_IDLE_SHUTDOWN。
    VLM 常驻约 12GB 显存，默认参与回收（900s）。
    """
    from apps.dsn_study.config import resource_idle_shutdown_enabled

    if not resource_idle_shutdown_enabled():
        return 0
    if not getattr(Config, "VLM_IDLE_SHUTDOWN", True):
        return 0
    try:
        return max(0, int(getattr(Config, "VLM_IDLE_TIMEOUT", 900)))
    except (TypeError, ValueError):
        return 0


def _decision_idle_timeout() -> int:
    """The idle reclaim timeout of the decision model in seconds, 0 keeps it up.

    Two switches apply: the pool level master switch and DECISION_IDLE_SHUTDOWN.
    The decision model fills both cards (measured 9.9G plus 9.9G), so it takes
    part in the reclaim by default (900s), otherwise it holds both cards and
    squeezes out TTS and the other local models.
    """
    from apps.dsn_study.config import resource_idle_shutdown_enabled

    if not resource_idle_shutdown_enabled():
        return 0
    if not getattr(Config, "DECISION_IDLE_SHUTDOWN", True):
        return 0
    try:
        return max(0, int(getattr(Config, "DECISION_IDLE_TIMEOUT", 900)))
    except (TypeError, ValueError):
        return 0


def _with_asr_warmup(load_fn, base_url: str):
    """包装 ASR 的 load_fn：sidecar 拉起后补一次模型预热。

    FunASR 模型是**懒加载**的：sidecar 进程起来了、/health 也返回 200，
    但权重直到第一次识别才真正读进显存（/health 里的 loaded 仍是 false）。
    原先这步由 systemd 单元的 ExecStartPost 负责；改为池托管后必须在这里
    补上，否则冷启动后的首个识别请求要独自承担全部加载耗时。

    预热失败不阻断加载：服务本身已就绪，模型会在首次识别时懒加载。
    """
    def _load() -> bool:
        ok = load_fn()
        if not ok:
            return False
        try:
            from apps.dsn_study.models.asr_client import ASRClient

            timeout = float(getattr(Config, "ASR_LOAD_TIMEOUT", 600))
            client = ASRClient(base_url, timeout=timeout)
            loaded = client.warmup(timeout=timeout)
            logger.info("ASR 拉起后预热模型: %s", "已加载" if loaded else "未加载")
        except Exception:  # noqa: BLE001 - 预热失败不影响服务可用性
            logger.exception("ASR 拉起后预热失败（服务仍可用，将懒加载）")
        return True

    return _load


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
    if getattr(Config, "ASR_WARMUP_ON_LOAD", True):
        load_fn = _with_asr_warmup(load_fn, base_url)
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
            idle_timeout=_idle_timeout("asr"),
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
            idle_timeout=_idle_timeout("tts"),
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


def _build_vlm(pool: ResourcePool) -> None:
    """把本地 VLM（Bonsai llama-server）注册进资源池。

    与 ASR/TTS 同构，但有两个不同点：
      * 它是 **llama-server**（不是 python sidecar），因此用 infra 的
        LlamaServerLauncher 而不是 HTTPServiceLauncher —— 前者自带
        mmproj / LD_LIBRARY_PATH / /health 探针等 llama.cpp 专属处理。
      * 它是**按需**的：注册时不启动，第一次取租约时才拉起（约 40s 冷启动）。
    """
    from apps.dsn_study.models.vlm_service import (
        get_vlm_launcher,
        register_vlm_resource,
    )

    if not getattr(Config, "VLM_ENABLED", True):
        logger.info("VLM 已禁用（VLM_ENABLED=false），跳过注册")
        return
    register_vlm_resource(pool)
    _state["vlm_launcher"] = get_vlm_launcher()


def _build_decision(pool: ResourcePool) -> None:
    """Register the System-1 decision model (JEV) in the resource pool.

    It has the same shape as ASR, TTS and the VLM, but it is a **llama-server**
    (not a python sidecar), so it uses the LlamaServerLauncher of infra. It
    also starts **on demand**: registering does not start it, the first
    decision does (a cold start of about 17s), and the idle timeout stops it
    again and returns the VRAM.
    """
    from apps.dsn_study.models.decision_service import register_study_decision

    if not getattr(Config, "DECISION_ENABLED", True):
        logger.info("the decision model is disabled (DECISION_ENABLED=false), not registered")
        return
    register_study_decision(pool)


def setup_study_resources(pool: Optional[ResourcePool] = None) -> ResourcePool:
    """创建（或复用）资源池并注册 TTS / ASR / VLM。幂等。"""
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
        if VLM_RESOURCE not in [r.get("name") for r in pool.list_resources()]:
            try:
                _build_vlm(pool)
            except Exception as e:
                logger.warning(
                    "VLM 资源注册失败（本地 OCR 将不可用）: %s", e)
        if DECISION_RESOURCE not in [r.get("name") for r in pool.list_resources()]:
            try:
                _build_decision(pool)
            except Exception as e:
                logger.warning(
                    "the decision resource is not registered (System-1 is unavailable): %s", e)

        # ── 空闲自动关闭 ──
        # 回收器挂在池上且是单例：只要**池级总开关打开**且有资源设了空闲阈值
        # 就启用。语音资源的阈值由 VOICE_IDLE_SHUTDOWN 决定（见 _idle_timeout），
        # VLM 的阈值由 VLM_IDLE_SHUTDOWN 独立决定（见 _vlm_idle_timeout），
        # the decision model works the same way (see _decision_idle_timeout).
        # 重复启动只会更新检查周期，不会起多个线程。
        from apps.dsn_study.config import resource_idle_shutdown_enabled

        if resource_idle_shutdown_enabled():
            targets = []
            for row in pool.list_resources():
                spec = pool.get_spec(row.get("name"))
                if spec is not None and int(spec.idle_timeout or 0) > 0:
                    targets.append("%s=%ss" % (row.get("name"), spec.idle_timeout))
            if targets:
                interval = float(getattr(Config, "VOICE_IDLE_CHECK_INTERVAL", 60))
                pool.enable_idle_shutdown(interval=interval)
                logger.info(
                    "空闲自动关闭已启用：%s（检查周期 %ss）", ", ".join(targets), interval)
            else:
                logger.info("空闲自动关闭已开启，但没有资源设置空闲阈值，保持常驻")
        else:
            logger.info("资源池空闲自动关闭总开关关闭，所有资源保持常驻")
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


def get_vlm_launcher():
    """返回 VLM（llama-server）launcher（用于显式 start/stop）。"""
    return _state.get("vlm_launcher")
