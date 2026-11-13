# infra/orchestrator/bonsai.py
# Bonsai（PrismML）本地模型资源的**自动发现**。
#
# 背景
# ----
# `~/Bonsai-demo`（PrismML Bonsai）自带一套**自定义 llama.cpp 构建**与
# **多模态投影器（mmproj）**：
#
#     bin/cuda/llama-server              ← 自定义二进制（含 mtmd 多模态支持）
#     bin/cuda/libllama.so.0 等          ← 同目录私有 .so（必须设置 LD_LIBRARY_PATH）
#     models/bonsai2-gguf/27B/
#         Ternary-Bonsai-2-27B-PQ2_0.gguf          ← 主模型（ternary 27B）
#         Ternary-Bonsai-2-27B-mmproj-Q8_0.gguf    ← 视觉投影器（图像输入）
#
# 为什么要上提到 infra
# ------------------
# 此前这段发现逻辑只存在于 apps/dsn_ui/bonsai_integration.py，但**两个应用
# 都要用**它：
#   * dsn_ui  —— 把 Bonsai 注册成可调度的本地模型（多轮对话 / 图片输入）；
#   * dsn_study —— 把同一个 llama-server 挂进资源池，作为**入库 OCR 的 VLM**，
#                  按需拉起、空闲回收。
# 两边各写一份必然分叉（这正是本仓库反复出现的问题类型），因此唯一实现在
# 这里，apps/dsn_ui/bonsai_integration.py 改为薄封装转发。
#
# 发现规则
# --------
# 按以下顺序探测（可用环境变量覆盖）：
#
#   * 二进制：显式 BONSAI_BIN → 依次尝试 bin/{cuda,vulkan,rocm,hip,cpu,mac}
#   * 模型：  `models/**/*.gguf`，排除 mmproj / drafter / kv-bias 等辅助文件
#   * 投影器：与主模型同目录的 *mmproj*.gguf（有则自动启用视觉）
#
# 扫描到的每个主模型注册为一个模型条目，名称形如 `bonsai:<family>:<size>`。

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger("infra.bonsai")

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


def pick_multimodal_model(
    demo_dir: Optional[Path | str] = None,
    prefer: str = "",
) -> Optional[BonsaiModel]:
    """挑一个**支持视觉**的 Bonsai 模型。

    选择顺序：
      1. 名字/路径里含 prefer 关键词的（大小写不敏感）；
      2. 其余多模态模型里体积最大（GGUF 字节数）的那个 ——
         「能看图 + 尽量大」是 OCR 场景的默认诉求。

    找不到带投影器的模型时返回 None（纯文本模型无法做 OCR）。
    """
    candidates = [m for m in scan_bonsai_models(demo_dir) if m.is_multimodal]
    if not candidates:
        return None
    if prefer:
        key = prefer.strip().lower()
        if key:
            hit = [m for m in candidates if key in m.name.lower()
                   or key in m.model_path.lower()]
            if hit:
                return hit[0]
    # 体积优先
    def _size(m: BonsaiModel) -> int:
        try:
            return os.path.getsize(m.model_path)
        except OSError:
            return 0
    return sorted(candidates, key=_size, reverse=True)[0]


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
