# harness/sdk.py
# Agent Harness SDK — 嵌入式高层接口
#
# 提供给外部 Python 项目直接嵌入使用的极简 API，支持：
# 1. create_agent(model=..., api_key=..., system_prompt=..., tools=...) 快速创建 Agent
# 2. Agent / ChatAgent 高层封装对象：
#    - agent.chat("你好") -> str (自动管理多轮历史)
#    - agent.chat_stream("你好") -> AsyncIterator[StreamEvent]
#    - agent.run("单次任务") -> AgentRunResult
# 3. 装饰器定义工具: @tool
# 4. 会话上下文与预算控制集成

from __future__ import annotations

import asyncio
from typing import Any, AsyncGenerator, Callable, Iterator, List, Optional, Union

from .agent.assembler import AgentAssembler, AgentSpec, AssembledAgent
from .agent.loop import AgentLoop, AgentRunResult, StreamEvent
from .conversation import Conversation
from .models.base import ChatMessage, IChatClient
from .models.openai import OpenAICompatClient
from .models.lmstudio import LMStudioChat
from .models.dynamic_router import DynamicRouter
from .models.failover import FailoverChat
from .tools.base import Tool, ToolRegistry
from .tools.function_tool import tool_from_function
from .tools.standard import ToolDeps, install_standard_tools


def tool(fn: Optional[Callable] = None, *, name: Optional[str] = None,
         description: Optional[str] = None,
         namespace: str = "") -> Union[Tool, Callable[[Callable], Tool]]:
    """将普通 Python 函数快速转为可供 Agent 使用的 Tool 对象。

    示例:
        @tool
        def get_weather(city: str) -> str:
            '''获取城市天气'''
            return f"{city} 天气晴"
    """
    def decorator(func: Callable) -> Tool:
        return tool_from_function(func, name=name, description=description,
                                  namespace=namespace)

    if fn is not None:
        return decorator(fn)
    return decorator


class Agent:
    """SDK 嵌入式 Agent 客户端封装。

    支持单次执行、流式输出与带历史的多轮对话。
    """

    def __init__(
        self,
        client: IChatClient,
        *,
        system_prompt: str = "",
        tools: Optional[Union[List[Union[Tool, Callable]], str, dict]] = None,
        max_steps: int = 8,
        workspace: Optional[str] = None,
        router_config: Optional[dict] = None,
        budget_config: Optional[dict] = None,
        enable_toolbox: bool = False,
        enable_memory: bool = False,
    ):
        self.client = client
        self.system_prompt_text = system_prompt
        self.conversation = Conversation()

        # 构建 ToolRegistry
        self.tool_registry = ToolRegistry()
        tool_spec: Any = None

        if isinstance(tools, str) or isinstance(tools, dict):
            tool_spec = tools
        elif isinstance(tools, list):
            for item in tools:
                if isinstance(item, Tool):
                    self.tool_registry.register(item)
                elif callable(item):
                    self.tool_registry.register(tool_from_function(item))
                elif isinstance(item, str) and item == "standard":
                    tool_spec = "standard"

        toolbox_spec = {"enabled": True} if enable_toolbox else None

        self.spec = AgentSpec(
            name="embedded-agent",
            system_prompt=system_prompt,
            max_steps=max_steps,
            workspace=workspace,
            router=router_config,
            tools=tool_spec,
            toolbox=toolbox_spec,
            budget=budget_config,
            memory=enable_memory,
        )

        assembler = AgentAssembler(self.client)
        self._assembled: AssembledAgent = assembler.assemble(self.spec)

        # 如果手动注册了自定义工具函数，合并到 assembled.loop.tools 中
        for t in self.tool_registry.tools():
            if self._assembled.loop.tools:
                self._assembled.loop.tools.register(t, replace=True)

    @property
    def tools(self) -> ToolRegistry:
        """访问当前 Agent 注册的工具表。"""
        return self._assembled.loop.tools or self.tool_registry

    def add_tool(self, tool_or_fn: Union[Tool, Callable]) -> "Agent":
        """动态添加工具。"""
        t = tool_or_fn if isinstance(tool_or_fn, Tool) else tool_from_function(tool_or_fn)
        if self._assembled.loop.tools:
            self._assembled.loop.tools.register(t, replace=True)
        else:
            self.tool_registry.register(t, replace=True)
        return self

    def reset(self) -> None:
        """重置当前对话历史。"""
        self.conversation.clear()

    # ── 对话接口（带多轮会话记忆） ──

    def chat(self, message: str) -> str:
        """同步多轮对话：追加用户输入，运行 Agent 循环，追加助手回复，返回结果文本。"""
        self.conversation.add(ChatMessage.user(message))
        msgs = list(self.conversation.messages)
        result: AgentRunResult = self._assembled.loop.run(msgs, system_prompt=self.system_prompt_text)
        self.conversation.add(ChatMessage.assistant(result.reply))
        return result.reply

    async def chat_async(self, message: str) -> str:
        """异步多轮对话。"""
        self.conversation.add(ChatMessage.user(message))
        msgs = list(self.conversation.messages)
        result: AgentRunResult = await self._assembled.loop.run_async(msgs, system_prompt=self.system_prompt_text)
        self.conversation.add(ChatMessage.assistant(result.reply))
        return result.reply

    async def chat_stream(self, message: str) -> AsyncGenerator[StreamEvent, None]:
        """异步流式多轮对话：yield 实时事件（round_start, delta, tool_call, tool_result, reply, done）。"""
        self.conversation.add(ChatMessage.user(message))
        msgs = list(self.conversation.messages)
        final_reply = ""
        async for event in self._assembled.loop.run_stream(msgs, system_prompt=self.system_prompt_text):
            if event.kind == "done":
                final_reply = event.reply
            yield event
        if final_reply:
            self.conversation.add(ChatMessage.assistant(final_reply))

    # ── 单次任务执行（无状态） ──

    def run(self, message: str) -> AgentRunResult:
        """单次执行模式（不计入多轮历史）。"""
        msgs = [ChatMessage.user(message)]
        return self._assembled.loop.run(msgs, system_prompt=self.system_prompt_text)

    async def run_async(self, message: str) -> AgentRunResult:
        """异步单次执行模式。"""
        msgs = [ChatMessage.user(message)]
        return await self._assembled.loop.run_async(msgs, system_prompt=self.system_prompt_text)


def create_agent(
    model: str = "gpt-4o-mini",
    *,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    client: Optional[IChatClient] = None,
    system_prompt: str = "You are a helpful assistant.",
    tools: Optional[Union[List[Union[Tool, Callable]], str, dict]] = None,
    max_steps: int = 8,
    workspace: Optional[str] = None,
    budget_cap: Optional[float] = None,
    token_cap: Optional[int] = None,
    enable_toolbox: bool = False,
    enable_memory: bool = False,
    **kwargs: Any,
) -> Agent:
    """SDK 快速工厂函数：一行代码创建嵌入式 Agent。

    参数:
        model: 模型名称（如 deepseek-chat, gpt-4o, 或本地 LMStudio 上的模型名）
        api_key: 模型 API Key（若为空，默认读取环境变量 OPENAI_API_KEY）
        base_url: 模型服务 Base URL（如 https://api.deepseek.com/v1 或 http://localhost:1234/v1）
        client: 自定义 IChatClient 实例（提供时优先使用，忽略 model/api_key/base_url）
        system_prompt: 系统提示词
        tools: 工具列表（可传标准工具名 "standard"、自定义函数列表、或 Tool 对象列表）
        max_steps: 单次任务工具调用最大循环步数
        workspace: 工作目录路径（用于标准文件工具等）
        budget_cap: 预算花费上限（美元）
        token_cap: Token 数量上限
        enable_toolbox: 是否开启两阶段工具动态激活
        enable_memory: 是否开启向量记忆检索

    示例:
        from harness import create_agent, tool

        @tool
        def add(a: int, b: int) -> int:
            return a + b

        agent = create_agent(model="deepseek-chat", api_key="sk-...", tools=[add])
        print(agent.chat("计算 123 + 456"))
    """
    if client is None:
        client = OpenAICompatClient(
            model=model,
            api_key=api_key or "",
            base_url=base_url or "",
            **kwargs,
        )

    budget_config = None
    if budget_cap is not None or token_cap is not None:
        budget_config = {
            "cost_cap": budget_cap,
            "token_cap": token_cap,
        }

    return Agent(
        client=client,
        system_prompt=system_prompt,
        tools=tools,
        max_steps=max_steps,
        workspace=workspace,
        budget_config=budget_config,
        enable_toolbox=enable_toolbox,
        enable_memory=enable_memory,
    )
