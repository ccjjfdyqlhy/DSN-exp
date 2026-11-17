# harness/agent/team.py
# Team —— 多智能体的门面（facade）。
#
# 为什么需要它：
#   多智能体在框架里是**四件套**——ManagedToolRegistry（工具）、AgentManager（派活与邮箱）、
#   ConversationEngine（事件驱动的执行体）、以及一个事件循环。用 SDK 的 Agent 写不了子 Agent，
#   于是每个使用者都要自己拼这四件，样板代码 30~40 行。
#
#   Team 把它们收成一行：
#
#       team = Team(client, worker_tools=[search])
#       print(await team.run("把资料查清楚再总结"))
#
#   要给子 Agent 不同的系统提示词/工具集，就注册一个 worker 类型：
#
#       team.register_worker("researcher", system="你是资料研究员", tools=[search])
#
# 语义：
#   * team.run()   —— 请求-响应式：提交一句话，等到这一轮结束，返回最终回复文本。
#   * team.submit() + team.drain() —— 事件流式：给 UI / 服务用。
#
from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Iterable, Optional

from infra.models.base import IChatClient

from ..tools.base import Tool
from ..tools.function_tool import tool_from_function
from ..tools.registry import ManagedToolRegistry
from .collab import AgentManager, AgentTypeSpec
from .engine import ConversationEngine
from .engine_config import AgentSettings


class Team:
    """多智能体团队。

    用法::

        team = Team(client, worker_tools=[search])
        async with team:
            print(await team.run("查一下资料并总结"))

    参数:
        client: 模型客户端（IChatClient）
        tools: 父 Agent（队长）自己的工具
        worker_tools: 子 Agent 可用的工具（函数或 Tool 对象）
        workers: 预注册的 worker 类型，形如
                  ``{"researcher": {"system": "...", "tools": [...]}}``
        system_prompt: 队长（父 Agent）的系统提示词
        max_concurrent: 同时在跑的子 Agent 上限
        max_depth: 派生深度上限
        registry / store / cwd: 需要自己控制底层时直接传进来
    """

    def __init__(
        self,
        client: IChatClient,
        *,
        tools: Iterable[Any] = (),
        worker_tools: Iterable[Any] = (),
        workers: Optional[dict] = None,
        system_prompt: str = "",
        max_concurrent: int = 2,
        max_depth: int = 3,
        registry: Optional[ManagedToolRegistry] = None,
        store: Any = None,
        cwd: str = "",
        model: Any = None,
    ) -> None:
        self.client = client
        self.system_prompt = system_prompt
        self.store = store
        self.cwd = cwd

        self.registry = registry or ManagedToolRegistry()
        for item in tools:
            self._register(self.registry, item)
        for item in worker_tools:
            self._register(self.registry, item, namespace="worker")

        self.settings = AgentSettings(
            team_enabled=True,
            max_concurrent=max_concurrent,
            max_depth=max_depth,
        )
        self.manager = AgentManager(
            client=client, registry=self.registry,
            config=self.settings, cwd=cwd, store=store,
        )
        self.engine = ConversationEngine(
            client=client, registry=self.registry, store=store, cwd=cwd, model=model,
        )
        self._started = False
        self._reply = ""

        for name, spec in (workers or {}).items():
            if isinstance(spec, dict):
                self.register_worker(name, system=spec.get("system", ""),
                                     tools=spec.get("tools", ()))
            else:
                self.register_worker(name, system=str(spec))

    # ── 组装 ──────────────────────────────────────────────────────────

    @staticmethod
    def _register(registry: ManagedToolRegistry, item: Any,
                  namespace: str = "") -> None:
        if isinstance(item, Tool):
            registry.register(item)
        elif callable(item):
            registry.register(tool_from_function(item, namespace=namespace))
        else:
            raise TypeError(f"不能注册为工具：{item!r}")

    def register_worker(self, name: str, *, system: str = "",
                        tools: Iterable[Any] = ()) -> None:
        """注册一种子 Agent 类型（名字、系统提示词、可用工具名）。

        ``tools`` 给的是**工具名**（注册时的名字），用来限制这个子 Agent
        能看到哪些工具；留空表示继承全部。
        """
        names: list[str] = []
        for item in tools:
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, Tool):
                self._register(self.registry, item)
                names.append(item.name)
            elif callable(item):
                registered = tool_from_function(item)
                self._register(self.registry, registered)
                names.append(registered.name)
        self.manager.register_agent_type(
            AgentTypeSpec(name=name, system=system, tools=names))

    # ── 生命周期 ──────────────────────────────────────────────────────

    async def start(self) -> "Team":
        """接线并启动（attach 需要在事件循环里，所以推迟到第一次使用）。"""
        if self._started:
            return self
        self.manager.attach(self.engine)
        self.engine.start()
        self._started = True
        return self

    async def shutdown(self) -> None:
        """停掉子 Agent 与执行体。"""
        if not self._started:
            return
        self._started = False
        try:
            await self.manager.shutdown()
        finally:
            await self.engine.shutdown()

    async def __aenter__(self) -> "Team":
        return await self.start()

    async def __aexit__(self, *exc) -> bool:
        await self.shutdown()
        return False

    # ── 用法一：请求-响应 ──────────────────────────────────────────────

    async def run(self, message: str, timeout: float = 120.0) -> str:
        """跑一轮，返回最终回复文本。"""
        await self.start()
        self._reply = ""
        self.engine.submit(message)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for kind, payload in self.engine.drain():
                if kind == "text_end":
                    self._reply = payload.get("text", "") or self._reply
                elif kind == "turn_end":
                    return self._reply
            await asyncio.sleep(0.02)
        raise TimeoutError(f"团队执行超时（{timeout}s）")

    # ── 用法二：事件流（UI / 服务）────────────────────────────────────

    def submit(self, message: str) -> bool:
        """提交一句话，立即返回（不等待）。"""
        return self.engine.submit(message)

    def drain(self, limit: int = 2000) -> list[tuple[str, dict]]:
        """取走已产生的事件（事件驱动用法）。"""
        return self.engine.drain(limit)

    @property
    def reply(self) -> str:
        """最近一轮的回复文本。"""
        return self._reply

    def agents_snapshot(self) -> Optional[list[dict]]:
        """当前团队成员的状态快照（名字、状态、深度）。"""
        return self.engine.agents_snapshot()
