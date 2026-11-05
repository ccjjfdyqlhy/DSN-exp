# apps/dsn_ui/jev_integration.py
"""~/qwen_weights/JEV-27B-VL 集成：双系统混合模型（System-1 决策 + System-2 对话）。

## 背景

JEV-27B-VL 是**双系统混合模型**，与普通 GGUF 有两点关键差异：

  1. **System 1（决策头）** —— 训练时与权重融合的 typed-decision 头。
     给出封闭选项集，它在**一次前向传播**里把答案分布直接写在下一个 token
     的概率上，不生成推理文本。dsn_ui 的 System-1 页面靠读 logprobs 拿这个分布。

  2. **qwen35 混合架构**（Gated Delta Net 线性注意力）——
     llama.cpp 的 fused GDN 算子**只在 CUDA 实现**。若 layer 0 留在 CPU，
     融合算子被禁用，每层都要跨 CPU/GPU 同步，速度掉 7 倍。

     实测（本机，双 RTX 2080 Ti 11G x2）：

         -ngl 47  →   3.79 tok/s
         -ngl 99  →  27.43 tok/s   ← 必须用 99

     因此 ``n_gpu_layers`` **不能**按"够用就行"来设，本模块固定为 99，
     不接受环境变量覆盖。

## 资源占用

JEV 的 Q4_K_M 权重 16.5G，加载后双卡各占约 10.5G / 9.7G —— 必须**独占双卡**。
它与 Bonsai-2-27B 无法共存（两者都要占满双卡），因此使用独立端口，
默认 8090（避开 Bonsai 的 8080 与 Strata 的 8081）。

## 发现规则

  * 模型根目录：``DSN_JEV_MODEL_ROOT`` → ``~/qwen_weights``（默认）
  * 主模型：``**/*.gguf``，排除 mmproj / drafter / kv-bias 等辅助文件
  * 投影器：同目录的 ``*mmproj*.gguf``（有则自动启用视觉 → System-1 可图文决策）

扫描到的每个主模型注册为一个条目，名称形如 ``jev:<目录名>``。
"""

from __future__ import annotations

import logging
import os
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from infra.orchestrator import LlamaServerConfig

logger = logging.getLogger("DSNUIJev")

#: 默认模型根目录（可用 DSN_JEV_MODEL_ROOT 覆盖）
DEFAULT_MODEL_ROOT = Path.home() / "qwen_weights"

#: 默认 llama-server 二进制（JEV 用系统 llama.cpp 构建，不用 Bonsai 自带的）
DEFAULT_BINARY = Path.home() / "llama.cpp" / "build" / "bin" / "llama-server"

#: JEV 专属默认端口。避开 Bonsai(8080) 与 Strata(8081)。
DEFAULT_PORT = 8090

#: n_gpu_layers 固定 99 —— 见模块文档：低于此值会禁用 fused GDN 算子，
#: 速度掉 7 倍。不做成可配置项，避免被误设成"够用就行"的值。
FIXED_N_GPU_LAYERS = 99

#: 默认上下文长度。32K 时 prefill 衰减仅 8%，且双卡显存可撑住。
DEFAULT_CTX_SIZE = 32768

#: 默认双卡切分。11G x2 等分。
DEFAULT_TENSOR_SPLIT = "11,11"

#: 这些文件名不是"主模型"，扫描时要排除
_AUX_PATTERNS = ("mmproj", "dspark", "dflash", "drafter", "kv-bias", "kv_bias")


@dataclass
class JevModel:
    """扫描到的 JEV 模型条目。"""

    name: str                 # 注册名，如 jev:JEV-27B-VL
    model_path: str           # 主 GGUF
    mmproj_path: Optional[str]  # 视觉投影器（可空 → 纯文本）
    directory: str            # 所属目录名

    @property
    def is_multimodal(self) -> bool:
        return bool(self.mmproj_path)


def resolve_model_root(model_root: Optional[Path | str] = None) -> Path:
    """解析模型根目录（参数 > 环境变量 > 默认）。"""
    if model_root:
        return Path(model_root).expanduser()
    env = os.getenv("DSN_JEV_MODEL_ROOT") or os.getenv("JEV_MODEL_ROOT")
    if env:
        return Path(env).expanduser()
    return DEFAULT_MODEL_ROOT


def resolve_binary(binary: Optional[Path | str] = None) -> Optional[str]:
    """定位 llama-server 二进制。

    JEV 用系统 llama.cpp 构建（Bonsai 自带的那套是三元量化专用构建，
    不保证兼容 qwen35 架构）。找不到时返回 None。
    """
    if binary:
        p = Path(binary).expanduser()
        return str(p) if p.is_file() and os.access(p, os.X_OK) else None

    env = os.getenv("DSN_JEV_BIN")
    if env:
        p = Path(env).expanduser()
        if p.is_file() and os.access(p, os.X_OK):
            logger.info("使用显式指定的 JEV 二进制: %s", p)
            return str(p)
        logger.warning("DSN_JEV_BIN 指向的路径不可执行，回退到自动探测: %s", env)

    if DEFAULT_BINARY.is_file() and os.access(DEFAULT_BINARY, os.X_OK):
        logger.info("发现系统 llama-server: %s", DEFAULT_BINARY)
        return str(DEFAULT_BINARY)

    logger.info("未找到可用的 llama-server（JEV 需要系统 llama.cpp 构建）")
    return None


def _is_auxiliary(path: Path) -> bool:
    """判断是否是辅助 GGUF（投影器/草稿模型/KV 偏置），非主模型。"""
    name = path.name.lower()
    return any(p in name for p in _AUX_PATTERNS)


def _port_is_free(port: int, host: str = "127.0.0.1") -> bool:
    """端口是否真的空闲（可绑定）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def _pick_port(preferred: int, claimed: set[int], host: str = "127.0.0.1") -> tuple[int, str]:
    """为模型挑选可用端口。

    返回 (port, reason)：
      * 首选端口未被其它已注册模型占用 → 原样使用；
      * 被占用 → 从 preferred+1 起找第一个既没被注册、也真的空闲的端口。

    与 Strata 的同名函数同策略：JEV 绝不能和 Bonsai 抢同一个端口，
    否则 System-1 的身份校验（/props 比对 model_path）会打到错的模型上。
    """
    if preferred not in claimed:
        return preferred, "配置的端口"
    port = preferred + 1
    while port < preferred + 200:
        if port not in claimed and _port_is_free(port, host):
            return port, f"原端口 {preferred} 已被其它本地模型占用，自动改用"
        port += 1
    return preferred, "未找到空闲端口，沿用原端口（可能冲突）"


def scan_jev_models(model_root: Optional[Path | str] = None) -> list[JevModel]:
    """扫描模型根目录下所有可用的主模型（含投影器配对）。"""
    root = resolve_model_root(model_root)
    if not root.is_dir():
        logger.info("JEV 模型根目录不存在: %s", root)
        return []

    found: list[JevModel] = []
    seen: set[str] = set()

    for gguf in sorted(root.rglob("*.gguf")):
        if _is_auxiliary(gguf):
            continue
        key = str(gguf.resolve())
        if key in seen:
            continue
        seen.add(key)

        # 同目录下找投影器（多模态）
        mmproj = None
        for cand in sorted(gguf.parent.glob("*mmproj*.gguf")):
            mmproj = str(cand)
            break

        directory = gguf.parent.name
        name = f"jev:{directory}"
        # 同名冲突时用文件名区分
        if any(m.name == name for m in found):
            name = f"{name}:{gguf.stem[:20]}"

        found.append(JevModel(
            name=name,
            model_path=str(gguf),
            mmproj_path=mmproj,
            directory=directory,
        ))

    logger.info(
        "JEV 扫描完成: %d 个模型 (%d 个支持视觉)",
        len(found), sum(1 for m in found if m.is_multimodal),
    )
    return found


def build_jev_config(
    model: JevModel,
    binary_path: str,
    *,
    port: int = DEFAULT_PORT,
    ctx_size: int = DEFAULT_CTX_SIZE,
    n_gpu_layers: int = FIXED_N_GPU_LAYERS,
    tensor_split: str = DEFAULT_TENSOR_SPLIT,
) -> LlamaServerConfig:
    """为 JEV 模型合成 llama-server 启动配置。

    关键点：
      * n_gpu_layers 固定 99 —— 低于此值会禁用 fused GDN 算子（见模块文档）。
      * 带 mmproj → 自动获得图像输入能力，System-1 可做图文决策。
      * jinja → 原生 OpenAI 风格多轮对话。
      * **mmproj_no_offload=True（--no-mmproj-offload）** —— 视觉投影器放到
        CPU 内存而非显存。这一点是必需的，不是可选优化：

        双卡被模型权重占满（10.8G + 9.8G / 11G 各卡），留给 clip 视觉编码器
        的显存不足。768x768 的图要编成 576 个 image token，clip_encode 会
        直接 `CUDA error: out of memory` 并**让整个 llama-server 崩溃**
        （不是返回错误，是进程死掉）。

        把投影器放到 CPU 可释放约 1.1GiB 显存，实测大图图文决策正常：
        Y 的概率 0.9969，进程稳定。代价是图像预处理变慢（CPU 编码），
        对 System-1 的单次前向场景完全可以接受。
    """
    return LlamaServerConfig(
        binary_path=binary_path,
        model_path=model.model_path,
        host="127.0.0.1",
        port=port,
        n_gpu_layers=n_gpu_layers,
        tensor_split=tensor_split,
        ctx_size=ctx_size,
        jinja=True,
        flash_attn="on",
        mmproj_path=model.mmproj_path,
        mmproj_no_offload=True,
        no_kv_offload=False,
    )


def register_jev_models(
    orchestrator,
    *,
    model_root: Optional[Path | str] = None,
    binary: Optional[Path | str] = None,
    port: Optional[int] = None,
    ctx_size: Optional[int] = None,
    priority: int = 65,
    claimed_ports: Optional[set[int]] = None,
) -> list[str]:
    """扫描并把 JEV 模型注册进 orchestrator。

    Returns:
        成功注册的模型名列表。目录不存在或没有模型时返回空列表
        （这是正常情况，不影响 dsn_ui 启动）。
    """
    root = resolve_model_root(model_root)
    binary_path = resolve_binary(binary)
    if not binary_path:
        return []

    models = scan_jev_models(root)
    if not models:
        logger.info("未发现 JEV 模型，跳过集成")
        return []

    claimed = set(claimed_ports or ())
    eff_ctx = ctx_size if ctx_size is not None else int(os.getenv("DSN_JEV_CTX", str(DEFAULT_CTX_SIZE)))
    preferred_port = port if port is not None else int(os.getenv("DSN_JEV_PORT", str(DEFAULT_PORT)))

    registered: list[str] = []
    for m in models:
        p, reason = _pick_port(preferred_port, claimed, "127.0.0.1")
        claimed.add(p)
        if reason != "配置的端口":
            logger.info("JEV 模型 %s 端口调整: %s", m.name, reason)

        cfg = build_jev_config(m, binary_path, port=p, ctx_size=eff_ctx)
        try:
            orchestrator.register_local_llamacpp(
                name=m.name,
                config=cfg,
                priority=priority,
                resident=False,
                immediate=False,
                load_timeout=300,
                request_timeout=600,
            )
            registered.append(m.name)
            logger.info(
                "已注册 JEV 模型: %s (%s%s) 端口=%d ngl=%d",
                m.name, Path(m.model_path).name,
                f" + vision({Path(m.mmproj_path).name})" if m.is_multimodal else "",
                p, FIXED_N_GPU_LAYERS,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("注册 JEV 模型 %s 失败: %s", m.name, e)

    return registered


def jev_status(model_root: Optional[Path | str] = None) -> dict:
    """供 API 查询的 JEV 集成状态。"""
    root = resolve_model_root(model_root)
    exists = root.is_dir()
    binary = resolve_binary() if exists else None
    models = scan_jev_models(root) if exists else []
    return {
        "model_root": str(root),
        "available": bool(binary and models),
        "binary": binary,
        "fixed_n_gpu_layers": FIXED_N_GPU_LAYERS,
        "default_port": DEFAULT_PORT,
        "models": [
            {
                "name": m.name,
                "directory": m.directory,
                "model_path": m.model_path,
                "mmproj_path": m.mmproj_path,
                "multimodal": m.is_multimodal,
            }
            for m in models
        ],
    }
