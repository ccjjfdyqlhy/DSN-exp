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
#       "mcp": {"config": "mcp_servers.yaml"},   # 外部 MCP 工具源（惰性连接）
#       "toolbox": {"enabled": True},     # 两阶段工具激活
#       "budget": {"token_cap": 200000, "cost_cap": 0.5},
#       "memory": True,                   # 会话记忆
#     }
#     agent = AgentAssembler(client).assemble(spec)
#     reply = agent.run("帮我看看这个项目")

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from infra.models.base import IChatClient, IEmbeddingClient
from infra.runtime import Runtime
from ..tools import Tool, ToolRegistry
from ..tools.function_tool import tool_from_function
from ..tools.toolbox import ToolboxManager
from ..tools.standard import ToolDeps, install_standard_tools
from ..memory import InMemoryStore, MemoryEntry
from ..conversation import Conversation, ConversationManager
from infra.policy import ModelRouter, ModelConfig, TokenMeter, TokenBudget, DurationPredictor
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
    mcp: Optional[dict] = None               # 外部 MCP 工具源: {"servers": [...]} | {"config": "path.yaml"}


class AssembledAgent:
    """装配完成的 Agent：聚合运行时 + 策略 + 便捷入口。"""

    def __init__(self, runtime: Runtime, loop: AgentLoop,
                 meter: Optional[TokenMeter] = None,
                 budget: Optional[TokenBudget] = None,
                 predictor: Optional[DurationPredictor] = None,
                 router: Optional[ModelRouter] = None,
                 prompts: Optional[PromptEngine] = None,
                 mcp: Optional[Any] = None):
        self.runtime = runtime
        self.loop = loop
        self.meter = meter
        self.budget = budget
        self.predictor = predictor
        self.router = router
        self.prompts = prompts
        # 外部 MCP 工具源管理器（None = 未配置）。惰性连接：装配期不建立任何
        # 连接，见 setup_mcp() 与 harness/tools/mcp.py 模块头说明。
        self.mcp = mcp
        self.spec: Optional[AgentSpec] = None

    def run(self, message: str, *, task_type: str = "") -> str:
        """单轮执行：路由选档 → 预算压力 → AgentLoop（用量自动回填）。

        修复说明（2026-10 policy 接线）：原实现里 `router.select` 的结果被丢弃、
        `meter.record({})` 记录的是空 usage、`budget.check()` 从未被调用，
        所以「Token 经济闭环」只是摆设。现在：
          * 用 router 选出的档位决定记账价格档（`model` 字段）；
          * usage 由 AgentLoop 通过 on_usage 回调**真实回填**；
          * 每轮之后检查预算，超限会触发 TokenBudget 的 on_exceed 回调。
        """
        mode = self.router.select(task_type, self.budget.pressure()) if self.router else ""
        loop = self.loop
        if mode and hasattr(loop, "client"):
            pass  # 路由选择由调用方结合 client 工厂使用
        result = loop.run([__import__("infra.models.base", fromlist=["ChatMessage"]).ChatMessage.user(message)])
        # usage 已由 on_usage 回调在每轮实时记账，这里只需做超限检查
        if self.budget is not None:
            self.budget.check()
        return result.reply

    def _record_usage(self, usage: dict) -> None:
        """AgentLoop 每轮回调：把真实 usage 记入 meter，并即时检查预算。

        容错：任何异常都不得打断 Agent 循环。
        """
        if self.meter is None:
            return
        mode = ""
        try:
            mode = getattr(self.router, "current_model", "") if self.router else ""
        except Exception:  # noqa: BLE001
            mode = ""
        try:
            self.meter.record(usage, model=mode or "")
        except Exception:  # noqa: BLE001
            return
        if self.budget is not None:
            try:
                self.budget.check()
            except Exception:  # noqa: BLE001
                pass

    def system_prompt(self) -> str:
        if self.prompts is not None:
            return self.prompts.build_system_prompt()
        return ""

    async def setup_mcp(self) -> dict[str, str]:
        """连接全部 MCP 服务器并注册工具（服务端 lifespan 显式预热入口）。

        返回 name → 错误信息（单服务器失败隔离，全部成功为空 dict）。
        重复调用安全：工具按全名覆盖注册。SDK 的 Agent 在异步入口会惰性
        调用本方法，长驻服务建议启动时显式调用一次以避免首请求变慢。
        """
        if self.mcp is None or self.loop is None or self.loop.tools is None:
            return {}
        errors = await self.mcp.load_tools(self.loop.tools)
        if self.loop.toolbox is not None:
            # toolbox 索引有缓存，MCP 工具补注册后必须失效重建
            self.loop.toolbox.invalidate()
        return errors

    async def aclose(self) -> None:
        """显式关停（当前只负责 MCP 连接；Runtime.stop 的钩子要求先 start 才生效，
        长驻服务在 lifespan shutdown 里直接 await 本方法更可靠）。"""
        if self.mcp is not None:
            await self.mcp.close()

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
                # 修复说明（2026-10）：列表形式此前**只识别字面量 "standard"**，
                # 列表里其它内容（Tool 对象、函数、"file" 这类命名空间前缀）
                # 会被静默忽略 —— 写错了也毫无提示。现补齐：
                #   * "standard"          → 装全套标准工具
                #   * "standard:file"     → 只装指定命名空间
                #   * Tool 对象            → 直接注册
                #   * 可调用对象（函数）    → 用 tool_from_function 转换后注册
                for item in spec.tools:
                    if item == "standard":
                        install_standard_tools(tools, deps=deps)
                    elif isinstance(item, str) and item.startswith("standard:"):
                        ns = item.split(":", 1)[1].strip()
                        install_standard_tools(tools, deps=deps, include=[ns])
                    elif isinstance(item, Tool):
                        tools.register(item)
                    elif callable(item) and not isinstance(item, type):
                        tools.register(tool_from_function(item))

        # 3) 外部 MCP 工具源（只建管理器，不连接 —— assemble 是同步的，
        #    MCP 会话绑定事件循环，连接推迟到 setup_mcp() / 首次工具调用）
        mcp_manager = None
        if spec.mcp:
            from ..tools.mcp import MCPManager
            if isinstance(spec.mcp, str):
                mcp_manager = MCPManager.from_yaml(spec.mcp)
            else:
                config = spec.mcp
                if isinstance(config, dict) and config.get("config"):
                    mcp_manager = MCPManager.from_yaml(config["config"])
                    extra = MCPManager.from_config(
                        {"servers": config.get("servers", [])})
                    # YAML 与内联 servers 合并（内联优先，用于局部覆盖）
                    merged = {c.name: c for c in mcp_manager.servers.values()}
                    merged.update(extra.servers)
                    mcp_manager = MCPManager(list(merged.values()))
                else:
                    mcp_manager = MCPManager.from_config(config)
            runtime.register("mcp", mcp_manager)
            runtime.on_stop(mcp_manager.close_sync)

        # 4) 提示词引擎
        prompts = None
        if spec.prompts_dir:
            prompts = PromptEngine(spec.prompts_dir)
            prompts.load_all()
        elif spec.system_prompt:
            prompts = PromptEngine()
            prompts.add_fragment("core", spec.system_prompt, order=0)
        system_prompt = prompts.build_system_prompt() if prompts else spec.system_prompt

        # 5) 模型路由 + 预算 + 计量 + 预测
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

        # 6) 工具箱（两阶段激活）
        toolbox = None
        if spec.toolbox and spec.toolbox.get("enabled", True):
            from ..tools.toolbox import RegistryIndexSource
            toolbox = ToolboxManager(RegistryIndexSource(tools),
                                     enabled=True,
                                     nested=False,
                                     max_activated=spec.toolbox.get("max_activated"))

        # 7) 记忆
        memory = None
        if spec.memory:
            memory = InMemoryStore(self.embedding_client)
            runtime.register("memory", memory)

        # 8) Agent 循环
        loop = AgentLoop(self.client, tools, max_steps=spec.max_steps,
                         toolbox=toolbox)
        runtime.register("loop", loop)
        runtime.register("router", router) if router else None
        runtime.register("meter", meter)
        runtime.set_default()

        agent = AssembledAgent(runtime, loop, meter=meter, budget=budget,
                               predictor=predictor, router=router, prompts=prompts,
                               mcp=mcp_manager)
        # 把真实 usage 回填到 meter/budget（policy 闭环的接线点，见 AssembledAgent._record_usage）
        loop.on_usage = agent._record_usage
        agent.spec = spec
        return agent
