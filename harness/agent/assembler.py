# harness/agent/assembler.py
# AgentAssembler — 声明式 Agent 装配（架构创新核心）。
#
# 创新思想「配置即代码」：一个 AgentSpec（dict/YAML）即可声明一个完整的
# AI 应用——模型路由、工具集、上下文策略、提示词、预算、记忆、耗时预测。
# 与 DSH 的差异：DSH 用 cordis.yml 组装"插件"，harness 用 AgentSpec 组装
# "Agent 行为"——策略对象是一级公民，可序列化、可测试、可组合。
#
# 示例:
#     spec = {
#       "name": "code-assistant",
#       "system_prompt": "你是一名资深工程师。",
#       "router": {"flash_model": "deepseek-v4-flash", "pro_model": "deepseek-v4-pro"},
#       "tools": ["standard"],            # 或 {"standard": {"include": ["file", "text"]}}
#       "toolbox": {"enabled": True},     # 两阶段工具激活
#       "budget": {"token_cap": 200000, "cost_cap": 0.5},
#       "memory": True,                   # 会话记忆
#     }
#     agent = AgentAssembler(client).assemble(spec)
#     reply = agent.run("帮我看看这个项目")

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ..models.base import IChatClient, IEmbeddingClient
from ..runtime import Runtime
from ..tools import ToolRegistry
from ..tools.toolbox import ToolboxManager
from ..tools.standard import ToolDeps, install_standard_tools
from ..memory import InMemoryStore, MemoryEntry
from ..conversation import Conversation, ConversationManager
from ..policy import ModelRouter, ModelConfig, TokenMeter, TokenBudget, DurationPredictor
from ..prompts import PromptEngine
from .loop import AgentLoop


@dataclass
class AgentSpec:
    """Agent 声明的结构化形式。"""

    name: str = "agent"
    system_prompt: str = ""
    prompts_dir: Optional[str] = None        # 模块化提示词目录
    max_steps: int = 8
    router: Optional[dict] = None            # ModelRouter 配置
    tools: Any = None                        # None | "standard" | {"standard": {...}} | list[str]
    toolbox: Optional[dict] = None           # {"enabled": bool, ...} | None
    budget: Optional[dict] = None            # {"token_cap": .., "cost_cap": ..}
    memory: bool = False
    workspace: Optional[str] = None
    tool_deps: Optional[dict] = None         # ToolDeps 额外注入


class AssembledAgent:
    """装配完成的 Agent：聚合运行时 + 策略 + 便捷入口。"""

    def __init__(self, runtime: Runtime, loop: AgentLoop,
                 meter: Optional[TokenMeter] = None,
                 budget: Optional[TokenBudget] = None,
                 predictor: Optional[DurationPredictor] = None,
                 router: Optional[ModelRouter] = None,
                 prompts: Optional[PromptEngine] = None):
        self.runtime = runtime
        self.loop = loop
        self.meter = meter
        self.budget = budget
        self.predictor = predictor
        self.router = router
        self.prompts = prompts
        self.spec: Optional[AgentSpec] = None

    def run(self, message: str, *, task_type: str = "") -> str:
        """单轮执行：路由 → 预算压力 → AgentLoop。"""
        mode = self.router.select(task_type, self.budget.pressure()) if self.router else ""
        loop = self.loop
        if mode and hasattr(loop, "client"):
            pass  # 路由选择由调用方结合 client 工厂使用
        result = loop.run([__import__("harness.models.base", fromlist=["ChatMessage"]).ChatMessage.user(message)])
        if self.meter is not None:
            self.meter.record({}, model=mode or "flash")  # 占位：真实 usage 由 client 回填
        return result.reply

    def system_prompt(self) -> str:
        if self.prompts is not None:
            return self.prompts.build_system_prompt()
        return ""

    def __repr__(self) -> str:
        return f"<AssembledAgent name={self.spec.name if self.spec else '?'}>"


class AgentAssembler:
    """从 AgentSpec 装配完整 Agent。"""

    def __init__(self, client: IChatClient,
                 embedding_client: Optional[IEmbeddingClient] = None):
        self.client = client
        self.embedding_client = embedding_client

    def assemble(self, spec: AgentSpec) -> AssembledAgent:
        # 1) 运行时
        runtime = Runtime(name=spec.name)
        tools = ToolRegistry()
        runtime.register("tools", tools)

        # 2) 标准工具集
        deps = ToolDeps(workspace=spec.workspace or __import__("os").getcwd(),
                        **(spec.tool_deps or {}))
        if spec.tools is not None:
            if spec.tools == "standard":
                install_standard_tools(tools, deps=deps)
            elif isinstance(spec.tools, dict) and "standard" in spec.tools:
                cfg = spec.tools["standard"]
                install_standard_tools(tools, deps=deps,
                                       include=cfg.get("include"))
            elif isinstance(spec.tools, list):
                for t in spec.tools:
                    if t == "standard":
                        install_standard_tools(tools, deps=deps)

        # 3) 提示词引擎
        prompts = None
        if spec.prompts_dir:
            prompts = PromptEngine(spec.prompts_dir)
            prompts.load_all()
        elif spec.system_prompt:
            prompts = PromptEngine()
            prompts.add_fragment("core", spec.system_prompt, order=0)
        system_prompt = prompts.build_system_prompt() if prompts else spec.system_prompt

        # 4) 模型路由 + 预算 + 计量 + 预测
        router = None
        if spec.router:
            cfg = ModelConfig(**{k: v for k, v in spec.router.items()
                                 if k in ModelConfig.__dataclass_fields__})
            router = ModelRouter(cfg)
        meter = TokenMeter()
        budget = None
        if spec.budget:
            budget = TokenBudget(token_cap=spec.budget.get("token_cap"),
                                 cost_cap=spec.budget.get("cost_cap"))
            budget.bind(meter)
        predictor = DurationPredictor()

        # 5) 工具箱（两阶段激活）
        toolbox = None
        if spec.toolbox and spec.toolbox.get("enabled", True):
            from ..tools.toolbox import RegistryIndexSource
            toolbox = ToolboxManager(RegistryIndexSource(tools),
                                     enabled=True,
                                     nested=False,
                                     max_activated=spec.toolbox.get("max_activated"))

        # 6) 记忆
        memory = None
        if spec.memory:
            memory = InMemoryStore(self.embedding_client)
            runtime.register("memory", memory)

        # 7) Agent 循环
        loop = AgentLoop(self.client, tools, max_steps=spec.max_steps,
                         toolbox=toolbox)
        runtime.register("loop", loop)
        runtime.register("router", router) if router else None
        runtime.register("meter", meter)
        runtime.set_default()

        agent = AssembledAgent(runtime, loop, meter=meter, budget=budget,
                               predictor=predictor, router=router, prompts=prompts)
        agent.spec = spec
        return agent
