# apps/dsn_study/models/vlm_service.py
# 本地 VLM（Bonsai llama-server）服务 —— 按需拉起 + 资源池托管 + OCR 客户端。
#
# 这个模块解决什么问题：
#   整卷入库的 OCR 以前打的是云端视觉 API（newapi.gay / deepseek-v4.1-flash）。
#   对照评测（/tmp/ocr_bench/REPORT.md）显示本地 Bonsai-2-27B 的精准度与在线
#   模型基本打平（相似度 0.894），且**页码更稳、结构保留更好**（选项独立成行
#   更利于切题）。批量入库用本地既省钱又不外传试卷。
#
# 生命周期沿用仓库里已经跑通的语音资源范式（infra.resources.ResourcePool）：
#   按需拉起  →  第一次 OCR 时才启动 llama-server（约 40s 冷启动）
#   租约保活  →  OCR 期间持有租约，资源不会被调度器驱逐
#   空闲回收  →  闲置超过 VLM_IDLE_TIMEOUT 自动停掉，释放约 12GB 显存
#
# 三种模式：
#   * 托管（VLM_AUTOSTART=true）—— 池负责拉起/停掉 llama-server 子进程；
#   * 接入（VLM_AUTOSTART=false）—— 只连已在跑的同一个服务，绝不杀进程；
#   * 不可用（VLM_ENABLED=false 或本机没有 Bonsai）—— 明确报错，不静默回退云端
#     （回退会把试卷内容外传，而且用户以为在用本地）。

from __future__ import annotations

import logging
import os
import threading
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from infra.orchestrator import LlamaServerConfig, LlamaServerLauncher
from infra.orchestrator.bonsai import (
    BonsaiModel,
    find_bonsai_binary,
    pick_multimodal_model,
    resolve_demo_dir,
)
from infra.resources import ResourceKind, ResourceSpec

logger = logging.getLogger("StudyVLM")

#: 资源名（池内唯一标识）
VLM_RESOURCE = "vlm"

_lock = threading.RLock()
_state: dict[str, Any] = {"launcher": None, "model": None}


class VLMUnavailable(RuntimeError):
    """本地 VLM 不可用（没装 Bonsai / 配置缺失 / 拉起失败）。"""


# ─────────────────────────────────────────────────────────────
# 资源发现
# ─────────────────────────────────────────────────────────────

def resolve_vlm_model(demo_dir: str = "") -> BonsaiModel:
    """定位要用的 Bonsai 多模态模型（主模型 + 视觉投影器）。

    优先级：
      1. 配置里显式给了 VLM_MODEL_PATH → 直接用它，自己找同目录的 mmproj；
      2. 否则自动扫描 Bonsai-demo，挑带投影器且体积最大的那个。
    """
    from apps.dsn_study.config import Config

    demo = demo_dir or getattr(Config, "VLM_DEMO_DIR", "") or ""
    root = resolve_demo_dir(demo or None)

    explicit = (getattr(Config, "VLM_MODEL_PATH", "") or "").strip()
    if explicit:
        model_path = os.path.abspath(os.path.expanduser(explicit))
        if not os.path.isfile(model_path):
            raise VLMUnavailable(
                f"VLM_MODEL_PATH 指向的模型文件不存在: {model_path}")
        mmproj = (getattr(Config, "VLM_MMPROJ_PATH", "") or "").strip()
        if not mmproj:
            for cand in os.listdir(os.path.dirname(model_path)):
                if "mmproj" in cand.lower() and cand.lower().endswith(".gguf"):
                    mmproj = os.path.join(os.path.dirname(model_path), cand)
                    break
        else:
            mmproj = os.path.abspath(os.path.expanduser(mmproj))
            if not os.path.isfile(mmproj):
                raise VLMUnavailable(
                    f"VLM_MMPROJ_PATH 指向的投影器不存在: {mmproj}")
        return BonsaiModel(
            name=os.path.basename(model_path),
            model_path=model_path,
            mmproj_path=mmproj or None,
            family="configured",
            size="?",
        )

    if not root.is_dir():
        raise VLMUnavailable(
            f"找不到 Bonsai 目录: {root}。本地 OCR 依赖 ~/Bonsai-demo，"
            f"可用 VLM_DEMO_DIR 指定其它路径。")

    model = pick_multimodal_model(root)
    if model is None:
        raise VLMUnavailable(
            f"{root}/models 下没有带 mmproj 投影器的模型 —— "
            f"纯文本模型无法做 OCR。请确认已下载 *mmproj*.gguf。")
    return model


def resolve_vlm_binary(demo_dir: str = "") -> str:
    """定位 Bonsai 自带的 llama-server 可执行文件。"""
    from apps.dsn_study.config import Config

    demo = demo_dir or getattr(Config, "VLM_DEMO_DIR", "") or ""
    root = resolve_demo_dir(demo or None)
    binary = find_bonsai_binary(root)
    if not binary:
        raise VLMUnavailable(
            f"在 {root} 下找不到可执行的 llama-server（找过 bin/cuda 等目录）。"
            f"请确认 Bonsai-demo 已完整下载。")
    return binary


# ─────────────────────────────────────────────────────────────
# 启动配置
# ─────────────────────────────────────────────────────────────

def build_vlm_config() -> LlamaServerConfig:
    """合成 llama-server 的启动配置（模型 + 投影器 + 私有 so 路径）。"""
    from apps.dsn_study.config import Config

    model = resolve_vlm_model()
    binary = resolve_vlm_binary()

    # Bonsai 的二进制依赖同目录的私有 .so（libllama.so 等）。
    # LocalServerLauncher 会自动把 cmd[0] 所在目录塞进 LD_LIBRARY_PATH，
    # 这里再显式写一份，双保险（也覆盖 config.env 被别处覆盖的情况）。
    bin_dir = os.path.dirname(binary)
    env = {
        "LD_LIBRARY_PATH": (
            f"{bin_dir}:{os.environ.get('LD_LIBRARY_PATH', '')}").rstrip(":"),
    }

    with _lock:
        _state["model"] = model

    return LlamaServerConfig(
        binary_path=binary,
        model_path=model.model_path,
        host=getattr(Config, "VLM_HOST", "127.0.0.1"),
        port=int(getattr(Config, "VLM_PORT", 4503)),
        n_gpu_layers=int(getattr(Config, "VLM_NGL", 99)),
        ctx_size=int(getattr(Config, "VLM_CTX_SIZE", 8192)),
        threads=int(getattr(Config, "VLM_THREADS", 8)),
        mmproj_path=model.mmproj_path,
        env=env,
    )


def build_vlm_launcher() -> LlamaServerLauncher:
    """构造 llama-server 的生命周期管理器。"""
    from apps.dsn_study.config import Config

    log_file = (getattr(Config, "VLM_LOG_FILE", "") or "").strip()
    if log_file:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)
        except OSError:
            log_file = ""
    launcher = LlamaServerLauncher(build_vlm_config(), log_file=log_file or None)
    with _lock:
        _state["launcher"] = launcher
    return launcher


# ─────────────────────────────────────────────────────────────
# 资源池注册
# ─────────────────────────────────────────────────────────────

def register_vlm_resource(pool) -> None:
    """把本地 VLM 注册进资源池。

    VLM_AUTOSTART=false → adopt 模式：只接入已在跑的服务，绝不拉起/杀进程。
    """
    from apps.dsn_study.config import Config
    from apps.dsn_study.models.resource_setup import _vlm_idle_timeout

    base_url = getattr(Config, "VLM_BASE_URL", "") or \
        f"http://{getattr(Config, 'VLM_HOST', '127.0.0.1')}:{getattr(Config, 'VLM_PORT', 4503)}/v1"

    managed = bool(getattr(Config, "VLM_AUTOSTART", True))
    launcher = build_vlm_launcher()
    model = _state.get("model")

    load_fn, unload_fn = launcher.create_scheduler_hooks(
        load_timeout=int(getattr(Config, "VLM_LOAD_TIMEOUT", 900)))

    pool.register_resource(
        VLM_RESOURCE,
        ResourceSpec(
            kind=ResourceKind.VLM,
            display_name="Bonsai 本地视觉模型",
            base_url=base_url,
            endpoint="",          # base_url 已是 OpenAI 兼容根（.../v1）
            priority=80,
            # resident=True：27B 常驻约 12GB 显存，**绝不能**被槽位压力驱逐 ——
            # 驱逐会让正在跑的 OCR 打到别的模型上。空闲释放交给 IdleReaper。
            resident=True,
            # immediate=False：归还租约时不能立刻卸载（每页 OCR 一次租约）。
            immediate=False,
            load_timeout=int(getattr(Config, "VLM_LOAD_TIMEOUT", 900)),
            request_timeout=int(getattr(Config, "VLM_REQUEST_TIMEOUT", 600)),
            vram_estimate_mb=int(getattr(Config, "VLM_VRAM_ESTIMATE_MB", 12000)),
            idle_timeout=_vlm_idle_timeout(),
            extra={
                "engine": "llama.cpp",
                "managed": managed,
                "adopt": not managed,
                "launch_mode": "command" if managed else "adopt",
                "model": getattr(model, "model_path", ""),
                "mmproj": getattr(model, "mmproj_path", "") or "",
                "port": int(getattr(Config, "VLM_PORT", 4503)),
            },
        ),
        load_fn,
        unload_fn,
    )
    logger.info("VLM 资源已注册: %s（模式=%s）", base_url,
                "managed" if managed else "adopt")


def get_vlm_launcher() -> Optional[LlamaServerLauncher]:
    """返回当前 VLM launcher（未构建时为 None）。"""
    return _state.get("launcher")


def ensure_pool(pool=None):
    """拿到可用的资源池；没有就建一个（并注册 VLM）。"""
    from apps.dsn_study.models.resource_setup import (
        get_study_pool,
        setup_study_resources,
    )

    if pool is not None:
        return pool
    existing = get_study_pool()
    if existing is not None:
        return existing
    return setup_study_resources()


# ─────────────────────────────────────────────────────────────
# 使用
# ─────────────────────────────────────────────────────────────

@contextmanager
def vlm_lease(pool=None, timeout: Optional[float] = None) -> Iterator[Any]:
    """租借本地 VLM —— **按需拉起**就发生在这里。

    进入时若服务未运行，池会在这里把它拉起来（冷启动约 40s）；
    退出时归还租约，服务保持运行（要等空闲回收才停）。

    :raises VLMUnavailable: 本地 VLM 不可用（没装 Bonsai / 配置缺失 / 拉起失败）
    """
    from apps.dsn_study.config import Config

    if not getattr(Config, "VLM_ENABLED", True):
        raise VLMUnavailable(
            "本地 VLM 已被禁用（VLM_ENABLED=false）。"
            "整卷入库的 OCR 现在只走本地模型，不回退云端。")

    p = ensure_pool(pool)
    names = [r.get("name") for r in p.list_resources()]
    if VLM_RESOURCE not in names:
        raise VLMUnavailable(
            "本地 VLM 未注册进资源池。请检查 VLM_ENABLED / VLM_AUTOSTART 配置。")

    wait = timeout if timeout is not None else \
        float(getattr(Config, "VLM_REQUEST_TIMEOUT", 600))
    try:
        handle = p.acquire(VLM_RESOURCE, timeout=wait)
    except TimeoutError as e:
        raise VLMUnavailable(
            f"等待本地 VLM 就绪超时（{wait:.0f}s）：{e}") from e
    except Exception as e:  # noqa: BLE001
        raise VLMUnavailable(f"拉起本地 VLM 失败: {e}") from e
    try:
        yield handle
    finally:
        handle.release()


def local_vision_model(timeout: Optional[int] = None):
    """构造指向本地 Bonsai 的视觉模型客户端。

    注意两点：
      1. 调用方**必须**已经在 vlm_lease() 里，否则服务可能还没起来。
      2. 这里直接用 infra 的基类而不是 apps.dsn_study.models.clients.VisionModel
         —— 后者用 ``api_key or Config.VISION_API_KEY`` 兜底，传空串会被
         「或」短路成云端密钥，于是本地服务也会收到 Authorization 头。
         本地 llama-server 不校验密钥，所以显式给空。
    """
    from infra.orchestrator.vision import VisionModel as _BaseVisionModel

    from apps.dsn_study.config import Config

    return _BaseVisionModel(
        api_key="",     # llama-server 默认不校验密钥
        base_url=getattr(Config, "VLM_BASE_URL", "") or
        f"http://{getattr(Config, 'VLM_HOST', '127.0.0.1')}:{getattr(Config, 'VLM_PORT', 4503)}/v1",
        model_name=getattr(Config, "VLM_MODEL_NAME", "bonsai2-27b"),
        timeout=int(timeout or getattr(Config, "VLM_REQUEST_TIMEOUT", 600)),
    )


# ─────────────────────────────────────────────────────────────
# 状态
# ─────────────────────────────────────────────────────────────

def vlm_status(pool=None) -> dict:
    """本地 VLM 的状态视图（供 Web 管理页 / 技能工具展示）。"""
    from apps.dsn_study.config import Config

    info: dict[str, Any] = {
        "enabled": bool(getattr(Config, "VLM_ENABLED", True)),
        "autostart": bool(getattr(Config, "VLM_AUTOSTART", True)),
        "base_url": getattr(Config, "VLM_BASE_URL", ""),
        "port": int(getattr(Config, "VLM_PORT", 4503)),
        "registered": False,
        "loaded": False,
        "managed": False,
        "model": "",
        "mmproj": "",
    }
    try:
        p = ensure_pool(pool)
    except Exception as e:  # noqa: BLE001
        info["error"] = str(e)
        return info

    rows = {r.get("name"): r for r in p.list_resources()}
    row = rows.get(VLM_RESOURCE)
    if row is not None:
        info["registered"] = True
        info["loaded"] = bool(row.get("loaded"))
        info["managed"] = bool(row.get("managed"))
        spec = p.get_spec(VLM_RESOURCE)
        if spec is not None:
            extra = spec.extra if isinstance(spec.extra, dict) else {}
            info["model"] = extra.get("model", "")
            info["mmproj"] = extra.get("mmproj", "")
    launcher = _state.get("launcher")
    if launcher is not None:
        info["running"] = launcher.is_running()
        info["command"] = launcher.command_string()
    return info
