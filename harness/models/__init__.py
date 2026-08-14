# harness/models/__init__.py
# 通用模型抽象层 — 与具体厂商/场景解耦。

from .base import (
    ChatMessage,
    ToolCall,
    ChatResponse,
    IChatClient,
    IEmbeddingClient,
    IModelProvider,
    ChatClientAdapter,
)
from .provider import ModelProviderRegistry
# ModelRouter/TierConfig 唯一实现在 policy.router（旧 models/router.py 已合并删除）
from ..policy.router import ModelRouter, TierConfig
# 多模型编排广义实现（从 DSN 应用广义化移植）
from .scheduler import ModelScheduler, ModelProfile, list_loaded_models
from .failover import FailoverChat, FailoverEndpoint
from .lmstudio import (
    LMStudioChat,
    load_lmstudio_model,
    unload_lmstudio_model,
)
from .dynamic_router import (
    DynamicRouter,
    MonitorStore,
    ManagedAccount,
    AccountProvider,
)

__all__ = [
    "ChatMessage",
    "ToolCall",
    "ChatResponse",
    "IChatClient",
    "IEmbeddingClient",
    "IModelProvider",
    "ChatClientAdapter",
    "ModelProviderRegistry",
    "ModelRouter",
    "TierConfig",
    # 多模型编排
    "ModelScheduler",
    "ModelProfile",
    "list_loaded_models",
    "FailoverChat",
    "FailoverEndpoint",
    "LMStudioChat",
    "load_lmstudio_model",
    "unload_lmstudio_model",
    "DynamicRouter",
    "MonitorStore",
    "ManagedAccount",
    "AccountProvider",
]