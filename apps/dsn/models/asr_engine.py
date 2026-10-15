# DSN-exp/apps/dsn/models/asr_engine.py
# ASR 引擎 —— FunASR 语音识别模型的一等生命周期封装。
#
# 背景：此前 ASR 模型是 boot.py 里一段裸的 AutoModel 构造（构建时即常驻显存，
# 且没有任何释放路径）。本模块把它抽成可加载/可卸载的引擎对象，使其能够作为
# 一种「进程内资源」接入 harness 资源池（infra/resources）。
#
# 关键约定（不可破坏）：
#   load() 返回的必须是 **FunASR 原始模型对象本身**，绝不能是包装器/代理。
#   下游代码直接把它当作存量模型使用：
#     - apps/dsn/api/app.py:23      asr_model.generate(...)  (:297/:347/:470)
#     - apps/dsn/api/checkin.py:66  _asr_model.generate(...) (:72)
#     - apps/dsn/boot.py:743        init_checkin_api(..., asr_model=asr_model)
#   因此本类只托管「句柄与生命周期」，不改变对象形态。

from __future__ import annotations

import logging
import sys
import threading
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: 与 boot.py 原有行为完全一致的模型配置（版本号不可随意改动）
ASR_MODEL = "paraformer-zh"
ASR_MODEL_REVISION = "v2.0.4"
ASR_VAD_MODEL = "fsmn-vad"
ASR_VAD_MODEL_REVISION = "v2.0.4"
ASR_PUNC_MODEL = "ct-punc-c"
ASR_PUNC_MODEL_REVISION = "v2.0.4"


class ASREngine:
    """FunASR 语音识别引擎（懒加载 + 幂等 + 可卸载）。

    与 infra.orchestrator.local_engine.InProcessModelLauncher 配合使用：
    launcher 负责线程与调度，本类只负责「如何构造 / 如何丢弃」模型对象。
    """

    def __init__(self, device: Optional[str] = None, gpu_id: Optional[str] = None):
        self.device = device
        self.gpu_id = gpu_id
        #: FunASR 原始模型对象（未加载为 None）
        self._model: Any = None
        self._lock = threading.RLock()

    # ── 设备解析 ──

    def resolve_device(self) -> str:
        """解析设备字符串，镜像 boot.py 原有逻辑：cuda + ASR_GPU_ID -> cuda:N。"""
        device = self.device or "cuda"
        gpu_id = self.gpu_id
        if gpu_id:
            device = f"cuda:{gpu_id}"
        return device

    # ── 生命周期 ──

    def load(self) -> Any:
        """构造并缓存 FunASR 模型（幂等；返回原始对象，非包装器）。

        funasr 在函数内部导入 —— 模块导入期绝不拉起 torch/funasr。
        """
        with self._lock:
            if self._model is not None:
                return self._model

            from funasr import AutoModel  # 延迟导入：避免模块导入期副作用

            _device = self.resolve_device()
            logger.info("加载 ASR 模型 (device=%s)...", _device)
            self._model = AutoModel(
                model=ASR_MODEL, model_revision=ASR_MODEL_REVISION,
                vad_model=ASR_VAD_MODEL, vad_model_revision=ASR_VAD_MODEL_REVISION,
                punc_model=ASR_PUNC_MODEL, punc_model_revision=ASR_PUNC_MODEL_REVISION,
                device=_device,
                disable_update=True, disable_pbar=True,
            )
            return self._model

    def unload(self) -> None:
        """丢弃模型引用；若 torch 已导入且设备为 CUDA，尽力清一次显存缓存。"""
        with self._lock:
            self._model = None
        self._empty_cuda_cache()

    def _empty_cuda_cache(self) -> None:
        """best-effort 释放 CUDA 缓存（不硬导入 torch）。"""
        if "cuda" not in str(self.resolve_device()).lower():
            return
        torch = sys.modules.get("torch")
        if torch is None:
            return
        try:
            cuda = getattr(torch, "cuda", None)
            if cuda is not None and hasattr(cuda, "empty_cache"):
                cuda.empty_cache()
        except Exception:  # noqa: BLE001 - 显存清理失败无关紧要
            logger.debug("ASR CUDA 缓存清理失败", exc_info=True)

    # ── 查询 ──

    def get_model(self) -> Any:
        """返回**原始** FunASR 模型对象；未加载为 None（不触发加载）。"""
        return self._model

    def is_loaded(self) -> bool:
        return self._model is not None

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        state = "loaded" if self.is_loaded() else "unloaded"
        return f"<ASREngine {state} device={self.resolve_device()}>"
