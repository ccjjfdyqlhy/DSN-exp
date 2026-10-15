# harness/__init__.py
# AICF（Agent Infrastructure Cybernetics Framework）—— Agent 核心层
#
# 场景无关的 Agent 核心。harness 只关心"消息进、输出流/事件出"，
# 不关心语音、人格、提醒等具体应用语义 —— 这些由 apps/ 下的 AppBundle 提供。
#
# 分层: AICF 的基础设施与运行时管理位于 infra/，Agent 核心位于 harness/。
# 本包保留的 Agent 核心模块:
#   tools            工具抽象 + 注册表
#   pipeline         通用管线 (Plugin / Pipeline / EventBus / OutputRenderer)
#   agent            Agent 循环 (AgentLoop / ToolCallAdapter)
#   agent_runtime    Agent 运行时
#   personality      人格与角色卡
#   memory           记忆抽象 (IMemoryStore / VectorIndex)
#   prompts          模块化提示词引擎
#   skills           技能加载
#   codegraph        代码图谱与文件监听
#   conversation     会话管理
#   groupchat        群聊
#   context_assembly 分段上下文装配
#   context_gatherer @ 指令上下文采集
#   sdk              嵌入式 SDK (Agent / create_agent / tool)
#
# 已迁至 infra/ 的基础设施模块（其中一部分在本模块再导出，见下方 import）:
#   runtime         Runtime DI 容器 + 生命周期
#   settings        命名空间化配置
#   subapps         AppBundle 抽象基类 + 装配器
#   orchestrator    模型编排与路由调度 (ModelOrchestrator / IChatClient / 适配器)
#   models          模型层（兼容别名）
#   resources       异构资源池 (ASR / TTS)
#   tasks           任务抽象 (Task / TaskExecutorRegistry)
#   store           持久化 (IStore / Migration / SqliteStore)
#   auth            认证 (Identity / APIKey / TOTP / Session)
#   gateway         Web 网关 (IGateway / FlaskGateway)
#   cache           语义缓存
#   observability   可观测性
#   policy          策略对象（路由 / 计量 / 预测 / 保活）

from infra.runtime import Runtime
from infra.settings import Settings
from infra.subapps import AppBundle, AppBundleRegistry
from .tools import Tool, ToolResult, ToolRegistry, ToolboxManager, RegistryIndexSource
from .agent_runtime import AgentRuntime
from infra import orchestrator
from infra import models
from . import pipeline
from . import agent
from . import memory
from infra import tasks
from infra import store
from infra import auth
from infra import gateway
from . import codegraph
from . import personality
from .personality import PersonalitySystemV3, CharacterCard, random_indicator_vector
from .conversation import Conversation, ConversationManager
from infra.cache import SemanticCache
from .prompts import PromptEngine, PromptFragment
from infra import policy
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
from .sdk import Agent, create_agent, tool

__version__ = "0.5.0"

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
    "Agent",
    "create_agent",
    "tool",
    "policy",
    "orchestrator",
    "models",
    "pipeline",
    "agent",
    "memory",
    "tasks",
    "store",
    "auth",
    "gateway",
    "codegraph",
    "personality",
    "PersonalitySystemV3",
    "CharacterCard",
    "__version__",
]
