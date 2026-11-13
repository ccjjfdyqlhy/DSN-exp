# apps/dsn_ui/bonsai_integration.py
"""~/Bonsai-demo 集成：自定义 llama.cpp 构建 + 本地多模态推理。

## 定位

本模块现在是 **infra 层唯一实现的薄封装**。

发现逻辑（目录探测、二进制定位、模型/投影器配对）此前只写在这里，但
`apps/dsn_study` 现在也需要同一套发现能力 —— 它把同一个 llama-server
挂进资源池，作为**入库 OCR 的本地 VLM**（按需拉起、空闲回收）。
两边各留一份必然分叉，因此唯一实现上提到 `infra/orchestrator/bonsai.py`，
本模块只保留 dsn_ui 特有的部分（注册成可调度的本地模型）。

## 发现规则

按以下顺序探测（可用环境变量覆盖）：

  * 二进制：DsnUISetting `BONSAI_BIN` → 依次尝试 bin/{cuda,vulkan,rocm,hip,cpu,mac}
  * 模型：  `models/**/*.gguf`，排除 mmproj / drafter / kv-bias 等辅助文件
  * 投影器：与主模型同目录的 *mmproj*.gguf（有则自动启用视觉）

扫描到的每个主模型注册为一个模型条目，名称形如 `bonsai:bonsai2:27B`。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from infra.orchestrator import LlamaServerConfig
from infra.orchestrator.bonsai import (
    BIN_SUBDIRS,
    DEFAULT_DEMO_DIR,
    BonsaiModel,
    bonsai_status,
    find_bonsai_binary,
    pick_multimodal_model,
    resolve_demo_dir,
    scan_bonsai_models,
)

logger = logging.getLogger("DSNUIBonsai")

__all__ = [
    "DEFAULT_DEMO_DIR",
    "BIN_SUBDIRS",
    "BonsaiModel",
    "resolve_demo_dir",
    "find_bonsai_binary",
    "scan_bonsai_models",
    "pick_multimodal_model",
    "bonsai_status",
    "build_llama_config",
    "register_bonsai_models",
]


def build_llama_config(
    model: BonsaiModel,
    binary_path: str,
    *,
    ctx_size: int = 8192,
    n_gpu_layers: int = 999,
    no_kv_offload: bool = False,
    mmproj_on_cpu: bool = False,
    image_max_tokens: Optional[int] = None,
    demo_dir: Optional[Path | str] = None,
) -> LlamaServerConfig:
    """为 Bonsai 模型合成 llama.cpp 启动配置。

    关键点：
      * binary_path 指向 Bonsai 自带二进制 → 自动获得其三进制量化与
        mtmd 多模态支持（系统 llama.cpp 未必兼容这些量化）。
      * mmproj_path 存在时自动启用图像输入。
      * env 注入 LD_LIBRARY_PATH，因为该二进制依赖同目录的私有 .so。
    """
    root = resolve_demo_dir(demo_dir)
    bin_dir = str(Path(binary_path).parent)

    env: dict[str, str] = {}
    # 显式设置，双保险（launcher 也会自动注入）
    env["LD_LIBRARY_PATH"] = (
        f"{bin_dir}:{os.environ.get('LD_LIBRARY_PATH', '')}".rstrip(":")
    )

    return LlamaServerConfig(
        binary_path=binary_path,
        model_path=model.model_path,
        host="127.0.0.1",
        port=8080,
        n_gpu_layers=n_gpu_layers,
        ctx_size=ctx_size,
        jinja=True,                     # 原生 OpenAI 风格工具调用
        no_kv_offload=no_kv_offload,
        mmproj_path=model.mmproj_path,
        mmproj_no_offload=mmproj_on_cpu,
        image_max_tokens=image_max_tokens,
        env=env,
    )


def _default_n_gpu_layers() -> int:
    """默认 GPU 分层数。

    999（全部卸载）在多模型共存时会直接 CUDA OOM —— 尤其 Bonsai 27B
    在 11GB 卡上本就吃紧。这里改为读取环境变量 DSN_BONSAI_NGL，
    默认 999（尊重用户显式配置），但在注册时给出提示。
    """
    raw = os.getenv("DSN_BONSAI_NGL") or os.getenv("BONSAI_NGL")
    if raw:
        try:
            return int(raw)
        except ValueError:
            logger.warning("DSN_BONSAI_NGL 非法: %r，回退默认值", raw)
    return 999


def register_bonsai_models(
    orchestrator,
    *,
    demo_dir: Optional[Path | str] = None,
    ctx_size: Optional[int] = None,
    n_gpu_layers: Optional[int] = None,
    priority: int = 60,
) -> list[str]:
    """扫描并把 Bonsai 模型注册进 orchestrator。

    Returns:
        成功注册的模型名列表。Bonsai-demo 不存在或没有模型时返回空列表
        （这是正常情况，不影响 dsn_ui 启动）。
    """
    root = resolve_demo_dir(demo_dir)
    if not root.is_dir():
        logger.info("未检测到 Bonsai-demo 目录(%s)，跳过集成", root)
        return []

    binary = find_bonsai_binary(root)
    if not binary:
        logger.warning("Bonsai-demo 存在但未找到 llama-server，跳过集成")
        return []

    models = scan_bonsai_models(root)
    if not models:
        logger.info("Bonsai-demo 中没有可用主模型，跳过集成")
        return []

    # 默认值：上下文 8192（27B 在消费级卡上较稳妥）；ngl 走环境变量或 999。
    eff_ctx = ctx_size if ctx_size is not None else int(os.getenv("DSN_BONSAI_CTX", "8192"))
    eff_ngl = n_gpu_layers if n_gpu_layers is not None else _default_n_gpu_layers()

    registered: list[str] = []
    for m in models:
        cfg = build_llama_config(
            m, binary,
            ctx_size=eff_ctx,
            n_gpu_layers=eff_ngl,
            demo_dir=root,
        )
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
                "已注册 Bonsai 模型: %s (%s%s)",
                m.name, Path(m.model_path).name,
                f" + vision({Path(m.mmproj_path).name})" if m.is_multimodal else "",
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("注册 Bonsai 模型 %s 失败: %s", m.name, e)

    return registered
