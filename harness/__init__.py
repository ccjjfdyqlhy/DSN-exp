# harness/__init__.py
# DSN-exp Agent Harness 核心层
#
# 场景无关的框架核心。harness 只关心"消息进、输出流/事件出"，
# 不关心语音、人格、提醒等具体应用语义 —— 这些由 apps/ 下的 AppBundle 提供。
#
# 分层:
#   runtime         Runtime DI 容器 + 生命周期
#   settings        命名空间化配置
#   subapps         AppBundle 抽象基类 + 装配器
#   tools           工具抽象 + 注册表
#   models          模型抽象 (IChatClient / IEmbeddingClient / 适配器)
#   pipeline        通用管线 (Plugin / Pipeline / EventBus / OutputRenderer)
#   agent           Agent 循环 (AgentLoop / ToolCallAdapter)
#   memory          记忆抽象 (IMemoryStore / VectorIndex)
#   tasks           任务抽象 (Task / TaskExecutorRegistry)
#   store           持久化 (IStore / Migration / SqliteStore)
#   auth            认证 (Identity / APIKey / TOTP / Session)
#   gateway         Web 网关 (IGateway / FlaskGateway)
#   conversation    会话管理
#   cache           语义缓存
#   observability   可观测性

from .runtime import Runtime
from .settings import Settings
from .subapps import AppBundle, AppBundleRegistry
from .tools import Tool, ToolResult, ToolRegistry, ToolboxManager, RegistryIndexSource
from .agent_runtime import AgentRuntime
from . import models
from . import pipeline
from . import agent
from . import memory
from . import tasks
from . import store
from . import auth
from . import gateway
from . import codegraph
from .conversation import Conversation, ConversationManager
from .cache import SemanticCache
from .prompts import PromptEngine, PromptFragment
from . import policy
from .tools.standard import ToolDeps, install_standard_tools
from .context_gatherer import ContextGatherer, ParseResult
from .context_assembly import (
    ContextBudget,
    ContextSegment,
    SegmentedContextAssembler,
    SEG_MEMO,
    SEG_SUMMARY,
    SEG_VERBATIM,
    SEG_TAIL,
)

__version__ = "0.4.0"

__all__ = [
    "Runtime",
    "Settings",
    "AppBundle",
    "AppBundleRegistry",
    "Tool",
    "ToolResult",
    "ToolRegistry",
    "AgentRuntime",
    "Conversation",
    "ConversationManager",
    "SemanticCache",
    "ContextBudget",
    "ContextSegment",
    "SegmentedContextAssembler",
    "PromptEngine",
    "PromptFragment",
    "ToolDeps",
    "install_standard_tools",
    "ContextGatherer",
    "ParseResult",
    "policy",
    "models",
    "pipeline",
    "agent",
    "memory",
    "tasks",
    "store",
    "auth",
    "gateway",
    "codegraph",
    "__version__",
]
