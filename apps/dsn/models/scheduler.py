# apps/dsn/models/scheduler.py
# DSN 侧 ModelScheduler — harness 广义实现的薄封装。
#
# harness/models/scheduler.py 提供通用多模型编排（FIFO 队列 / 优先级驱逐 /
# immediate 位移 / resident 常驻）；本模块只负责接线：
#   - 从 DSN Config 读取插槽数 / 请求超时
#   - 指向 DSN 的 model_profiles/ YAML 目录
#   - 自动注册 embedding 常驻模型（DSN 专属）

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from harness.models.scheduler import (
    ModelProfile,
    ModelScheduler as _HarnessModelScheduler,
    list_loaded_models as _get_loaded_models,
)

logger = logging.getLogger("ModelScheduler")


class ModelScheduler(_HarnessModelScheduler):
    def __init__(self, max_concurrent: Optional[int] = None):
        from apps.dsn.config import Config
        from apps.dsn.models.clients import _load_lmstudio_model, _unload_lmstudio_model

        profiles_dir = Path(__file__).resolve().parent.parent / "model_profiles"
        super().__init__(
            max_concurrent=max_concurrent or Config.MAX_CONCURRENT_LM_MODELS,
            default_request_timeout=Config.MODEL_REQUEST_TIMEOUT,
            profiles_dir=profiles_dir,
        )

        # 自动扫描并注册 profiles 目录中的 llama_cpp 引擎模型
        self._auto_register_llama_profiles()

        # embedding 常驻模型（DSN 专属，不被调度器卸载）
        emb_model = Config.MEMORY_EMBEDDING_MODEL
        if emb_model and Config.MEMORY_EMBEDDING_ENABLED:
            self.register(
                model_name=emb_model,
                base_url=Config.LMSTUDIO_BASE_URL,
                load_fn=lambda: _load_lmstudio_model(Config.LMSTUDIO_BASE_URL, emb_model, "embedding"),
                unload_fn=lambda: _unload_lmstudio_model(Config.LMSTUDIO_BASE_URL, emb_model),
                resident=True,
                orchestrated=False,
            )

    def _auto_register_llama_profiles(self) -> None:
        """为 YAML profiles 中声明 engine: llama_cpp 的模型自动绑定 LlamaServerLauncher 进程钩子。"""
        from harness.models.llamacpp import LlamaServerConfig, LlamaServerLauncher
        for name, profile in self._profiles_by_name.items():
            if profile.engine in ("llama_cpp", "llamacpp") and profile.llama_config:
                cfg = LlamaServerConfig.from_dict(profile.llama_config)
                launcher = LlamaServerLauncher(cfg)
                load_fn, unload_fn = launcher.create_scheduler_hooks(
                    load_timeout=profile.load_timeout or 180
                )
                self.register(
                    model_name=name,
                    base_url=launcher.base_url,
                    load_fn=load_fn,
                    unload_fn=unload_fn,
                    priority=profile.priority,
                    resident=profile.resident,
                    immediate=profile.immediate,
                    orchestrated=profile.orchestrated,
                    engine=profile.engine,
                    llama_config=profile.llama_config,
                )


# 兼容导出（原 dsn 模块的公开名）
ModelProfile = ModelProfile
_get_loaded_models = _get_loaded_models
