# harness/orchestrator/__init__.py
# 模型抽象层 + 多引擎编排（llama.cpp / Strata / LMStudio / 外部 API）。

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
# 本地引擎公共基类（子进程生命周期 / OpenAI 兼容协议）
from .local_chat import OpenAICompatChat, OpenAICompatEmbeddingClient
from .local_engine import LocalServerLauncher
from .llamacpp import (
    LlamaServerConfig,
    LlamaServerLauncher,
    LlamaCppChat,
    LlamaCppEmbeddingClient,
)
from .strata import (
    StrataEngineConfig,
    StrataServerLauncher,
    StrataChat,
    StrataEmbeddingClient,
    StrataRun,
    build_engine_config,
    default_python_for_script,
    discover_runs,
    find_strata_root,
)
from .openai import OpenAICompatClient
from .anthropic import AnthropicCompatClient
from .router import (
    ModelSourceType,
    ModelSpec,
    ModelOrchestrator,
)
from .dynamic_router import (
    DynamicRouter,
    MonitorStore,
    ManagedAccount,
    AccountProvider,
)
from .stub import (
    StubChatClient,
    StubEmbeddingClient,
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
    "OpenAICompatClient",
    "AnthropicCompatClient",
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
    # 本地引擎公共基类
    "LocalServerLauncher",
    "OpenAICompatChat",
    "OpenAICompatEmbeddingClient",
    # 本地 llama.cpp 自部署推理引擎支持
    "LlamaServerConfig",
    "LlamaServerLauncher",
    "LlamaCppChat",
    "LlamaCppEmbeddingClient",
    # 本地 Strata 推理引擎支持（run config JSON + serve/server.py）
    "StrataEngineConfig",
    "StrataServerLauncher",
    "StrataChat",
    "StrataEmbeddingClient",
    "StrataRun",
    "discover_runs",
    "build_engine_config",
    "find_strata_root",
    "default_python_for_script",
    # 双轨制全局模型编排系统
    "ModelSourceType",
    "ModelSpec",
    "ModelOrchestrator",
    "DynamicRouter",
    "MonitorStore",
    "ManagedAccount",
    "AccountProvider",
    "StubChatClient",
    "StubEmbeddingClient",
]
