# apps/dsn_ui/bonsai_integration.py
"""~/Bonsai-demo 集成：自定义 llama.cpp 构建 + 本地多模态推理。

## 背景

`~/Bonsai-demo`（PrismML Bonsai）自带一套**自定义 llama.cpp 构建**与
**多模态投影器（mmproj）**：

    bin/cuda/llama-server              ← 自定义二进制（含 mtmd 多模态支持）
    bin/cuda/libllama.so.0 等          ← 同目录私有 .so（必须设置 LD_LIBRARY_PATH）
    models/bonsai2-gguf/27B/
        Ternary-Bonsai-2-27B-PQ2_0.gguf          ← 主模型（ternary 27B）
        Ternary-Bonsai-2-27B-mmproj-Q8_0.gguf    ← 视觉投影器（图像输入）

本模块负责**自动发现**这些资源并注册成 dsn_ui 可调度的本地模型，
使得：

  1. 用 Bonsai 自带二进制（而非系统 llama.cpp）跑推理；
  2. 支持图像输入（multimodal）—— 调用方可传 image_url 内容块；
  3. 与 DSN 的显存调度、KV offload 开关等既有能力打通。

## 发现规则

按以下顺序探测（可用环境变量覆盖）：

  * 二进制：DsnUISetting `BONSAI_BIN` → 依次尝试 bin/{cuda,vulkan,rocm,hip,cpu,mac}
  * 模型：  `models/**/*.gguf`，排除 mmproj / drafter / kv-bias 等辅助文件
  * 投影器：与主模型同目录的 *mmproj*.gguf（有则自动启用视觉）

扫描到的每个主模型注册为一个模型条目，名称形如 `bonsai:<family>:<size>`。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from harness.orchestrator import LlamaServerConfig

logger = logging.getLogger("DSNUIBonsai")

# 默认 demo 目录，可用环境变量覆盖
DEFAULT_DEMO_DIR = Path.home() / "Bonsai-demo"

# 二进制搜索顺序（与 Bonsai 官方脚本一致，优先级从前到后）
BIN_SUBDIRS = ("cuda", "vulkan", "rocm", "hip", "cpu", "mac")

# 这些文件名不是"主模型"，扫描时要排除
_AUX_PATTERNS = ("mmproj", "dspark", "dflash", "drafter", "kv-bias", "kv_bias")


@dataclass
class BonsaiModel:
    """扫描到的 Bonsai 模型条目。"""

    name: str                 # 注册名，如 bonsai:bonsai2:27B
    model_path: str           # 主 GGUF
    mmproj_path: Optional[str]  # 视觉投影器（可空 → 纯文本）
    family: str               # bonsai2 / ternary / bonsai
    size: str                 # 27B / 8B ...

    @property
    def is_multimodal(self) -> bool:
        return bool(self.mmproj_path)


def resolve_demo_dir(demo_dir: Optional[Path | str] = None) -> Path:
    """解析 Bonsai-demo 目录（参数 > 环境变量 > 默认）。"""
    if demo_dir:
        return Path(demo_dir).expanduser()
    env = os.getenv("BONSAI_DEMO_DIR") or os.getenv("DSN_BONSAI_DEMO_DIR")
    if env:
        return Path(env).expanduser()
    return DEFAULT_DEMO_DIR


def find_bonsai_binary(demo_dir: Path) -> Optional[str]:
    """定位 Bonsai 自带的 llama-server 可执行文件。

    显式指定 BONSAI_BIN 时优先使用；否则按后端目录优先级探测。
    返回绝对路径，找不到返回 None。
    """
    explicit = os.getenv("BONSAI_BIN") or os.getenv("DSN_BONSAI_BIN")
    if explicit:
        p = Path(explicit).expanduser()
        if p.is_file() and os.access(p, os.X_OK):
            logger.info("使用显式指定的 Bonsai 二进制: %s", p)
            return str(p)
        logger.warning("BONSAI_BIN 指向的路径不可执行，回退到自动探测: %s", explicit)

    for sub in BIN_SUBDIRS:
        candidate = demo_dir / "bin" / sub / "llama-server"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            logger.info("发现 Bonsai llama-server (%s): %s", sub, candidate)
            return str(candidate)

    # 兜底：官方构建目录
    for sub in ("llama.cpp/build/bin", "llama.cpp/build-cuda/bin", "llama.cpp/build-mac/bin"):
        candidate = demo_dir / sub / "llama-server"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            logger.info("发现 Bonsai llama-server (build): %s", candidate)
            return str(candidate)

    logger.info("未在 %s 找到可用的 llama-server", demo_dir)
    return None


def _is_auxiliary(path: Path) -> bool:
    """判断是否是辅助 GGUF（投影器/草稿模型/KV 偏置），非主模型。"""
    name = path.name.lower()
    return any(p in name for p in _AUX_PATTERNS)


def _family_size_from_path(demo_dir: Path, gguf: Path) -> tuple[str, str]:
    """从路径推断 (family, size)。

    典型路径：models/bonsai2-gguf/27B/xxx.gguf
             models/ternary-gguf/8B/xxx.gguf
    """
    try:
        rel = gguf.relative_to(demo_dir / "models")
        parts = rel.parts
        family_dir = parts[0] if parts else ""          # bonsai2-gguf
        size = parts[1] if len(parts) > 1 else "unknown"  # 27B
        family = family_dir.replace("-gguf", "") or "bonsai"
        return family, size
    except Exception:
        return "bonsai", "unknown"


def scan_bonsai_models(demo_dir: Optional[Path | str] = None) -> list[BonsaiModel]:
    """扫描 Bonsai-demo 下所有可用的主模型（含投影器配对）。"""
    root = resolve_demo_dir(demo_dir)
    models_root = root / "models"
    if not models_root.is_dir():
        logger.info("Bonsai models 目录不存在: %s", models_root)
        return []

    found: list[BonsaiModel] = []
    seen_paths: set[str] = set()

    # 每个"主模型目录"里选一个主 gguf，并配对同目录的 mmproj
    for gguf in sorted(models_root.rglob("*.gguf")):
        if _is_auxiliary(gguf):
            continue
        key = str(gguf.resolve())
        if key in seen_paths:
            continue
        seen_paths.add(key)

        family, size = _family_size_from_path(root, gguf)

        # 同目录下找投影器（多模态）
        mmproj = None
        for cand in gguf.parent.glob("*mmproj*.gguf"):
            mmproj = str(cand)
            break

        name = f"bonsai:{family}:{size}"
        # 同名冲突时用文件名区分
        if any(m.name == name for m in found):
            name = f"{name}:{gguf.stem[:20]}"

        found.append(BonsaiModel(
            name=name,
            model_path=str(gguf),
            mmproj_path=mmproj,
            family=family,
            size=size,
        ))

    logger.info(
        "Bonsai 扫描完成: %d 个模型 (%d 个支持视觉)",
        len(found), sum(1 for m in found if m.is_multimodal),
    )
    return found


def build_llama_config(
    model: BonsaiModel,
    binary_path: str,
    *,
    ctx_size: int = 8192,
    n_gpu_layers: int = 999,
    no_kv_offload: bool = False,
    mmproj_on_cpu: bool = False,
    image_max_tokens: Optional[int] = None,
    demo_dir: Optional[Path] = None,
) -> LlamaServerConfig:
    """为 Bonsai 模型合成 llama.cpp 启动配置。

    关键点：
      * binary_path 指向 Bonsai 自带二进制 → 自动获得其三进制量化与
        mtmd 多模态支持（系统 llamba.cpp 未必兼容这些量化）。
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


def bonsai_status(demo_dir: Optional[Path | str] = None) -> dict:
    """供 API 查询的 Bonsai 集成状态。"""
    root = resolve_demo_dir(demo_dir)
    exists = root.is_dir()
    binary = find_bonsai_binary(root) if exists else None
    models = scan_bonsai_models(root) if exists else []
    return {
        "demo_dir": str(root),
        "available": bool(binary and models),
        "binary": binary,
        "binary_backend": Path(binary).parent.name if binary else None,
        "models": [
            {
                "name": m.name,
                "family": m.family,
                "size": m.size,
                "model_path": m.model_path,
                "mmproj_path": m.mmproj_path,
                "multimodal": m.is_multimodal,
            }
            for m in models
        ],
    }
