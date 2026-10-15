# DSN-exp/apps/dsn/models/resource_setup.py
# 把 DSN 的语音资源（ASR / TTS）注册进 harness 资源池。
#
# 范围严格限定为 ASR + TTS 两类资源；不涉及视觉/OCR/媒体等其它种类。
#
# 两类资源的形态：
#   * ASR —— 进程内 FunASR 模型（ASREngine），用 InProcessModelLauncher 托管；
#            resident=True，常驻显存，不因插槽压力被驱逐。
#   * TTS —— GPT-SoVITS HTTP 服务（默认 127.0.0.1:9880），用 HTTPServiceLauncher：
#             TTS_AUTOSTART=True（默认）= **托管模式**，资源池负责拉起/停止；
#             TTS_AUTOSTART=False      = adopt 模式，只接入既有服务、绝不拉起。
#
# 幂等：重复调用不会重复注册，也不会重建已有资源池。

from __future__ import annotations

import logging
import os
import sys
import threading
from typing import Optional

from harness.resources import (
    HTTPServiceLauncher,
    InProcessModelLauncher,
    ResourceKind,
    ResourcePool,
    ResourceSpec,
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


def _tts_start_command() -> Optional[list[str]]:
    """合成 GPT-SoVITS 服务的启动命令行；adopt 模式返回 None。

    注意 device 语义的两层区分：
      * `-d` 传给 api.py，取值是 "cuda" / "cpu"（服务端自己的设备选择）；
      * launcher 构造参数 `device` 只用于设置 CUDA_VISIBLE_DEVICES，
        必须是物理卡号（"0"）或留空；传 "cuda" 会让 CUDA 初始化失败。
    """
    if not getattr(Config, "TTS_AUTOSTART", False):
        return None

    python_exe = getattr(Config, "TTS_PYTHON", None) or sys.executable
    server_dir = getattr(Config, "TTS_SERVER_DIR", TTS_SERVER_DIR)
    entry = os.path.join(server_dir, TTS_SERVER_ENTRY)
    return [
        python_exe,
        entry,
        "-p", str(getattr(Config, "TTS_PORT", 9880)),
        "-d", str(getattr(Config, "TTS_DEVICE", "cuda")),
    ]


def _build_tts(pool: ResourcePool) -> None:
    """注册 TTS（GPT-SoVITS HTTP 服务）。

    默认 TTS_AUTOSTART=True = **托管模式**：资源池负责拉起/停止服务，
    从而真正"可托管"。设为 false 则退化为 adopt 模式：只探测既有服务，
    绝不拉起也绝不杀死外部进程。
    """
    base_url = Config.TTS_BASE_URL
    start_command = _tts_start_command()
    managed = start_command is not None
    server_dir = getattr(Config, "TTS_SERVER_DIR", TTS_SERVER_DIR)

    # GPU 编号只用于 CUDA_VISIBLE_DEVICES；留空则不限制。
    gpu_id = (getattr(Config, "TTS_GPU_ID", "") or "").strip() or None

    launcher = HTTPServiceLauncher(
        name=TTS_RESOURCE,
        base_url=base_url,
        ready_path="/",
        start_command=start_command,
        cwd=server_dir if managed else None,
        device=gpu_id,
    )
    if managed and getattr(Config, "TTS_PREFLIGHT", True):
        # 预检入口脚本存在，给出可操作的中文错误而不是让 Popen 抛底噪。
        entry = os.path.join(server_dir, TTS_SERVER_ENTRY)
        if not os.path.isfile(entry):
            raise FileNotFoundError(
                f"TTS 入口脚本不存在: {entry}。请检查 TTS_SERVER_DIR，"
                f"或设置 TTS_AUTOSTART=false 改为只接入既有服务。"
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
            extra={"engine": "local", "managed": managed, "adopt": not managed},
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
