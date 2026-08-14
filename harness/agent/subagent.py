# harness/agent/subagent.py
# SubAgent — 子任务委派与并发执行（场景无关）。
#
# 从 dekacode sub_agent.py 提炼并引擎化：
#   - SubTask：子任务（title/prompt/status/output/result）
#   - SubAgentRunner：把复杂任务拆为子任务，每个子任务用独立 AgentLoop
#     执行（fresh context），并发运行，回收结果
#   - 支持 max_concurrency / 超时 / 单任务失败不拖垮整体
#
# 架构位置：harness 的"层级智能体"原语——swarm 是平级黑板协作，
# subagent 是主控→子代理委派（主管-工人模式）。

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ..models.base import ChatMessage, IChatClient
from ..tools import ToolRegistry
from .loop import AgentLoop

logger = logging.getLogger("harness.subagent")


@dataclass
class SubTask:
    """一个可独立执行的子任务。"""

    title: str
    prompt: str
    status: str = "pending"          # pending | running | done | error
    output: str = ""
    error: str = ""
    elapsed: float = 0.0
    result: Any = None


@dataclass
class SubAgentRunResult:
    """一次子代理运行的汇总。"""

    tasks: list[SubTask] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)

    @property
    def done_count(self) -> int:
        return sum(1 for t in self.tasks if t.status == "done")

    @property
    def error_count(self) -> int:
        return sum(1 for t in self.tasks if t.status == "error")

    @property
    def all_done(self) -> bool:
        return all(t.status in ("done", "error") for t in self.tasks)

    def summary(self) -> str:
        lines = [f"子任务 {len(self.tasks)} 个: done={self.done_count} error={self.error_count}"]
        for t in self.tasks:
            icon = {"done": "✓", "error": "✗", "running": "⏳", "pending": " "}[t.status]
            lines.append(f"  {icon} {t.title} ({t.status}) {t.elapsed:.1f}s")
            if t.output:
                lines.append(f"      {t.output[:200]}")
        return "\n".join(lines)


class SubAgentRunner:
    """主控 Agent 的子代理执行器。

    用法:
        runner = SubAgentRunner(client, tools, max_steps=6)
        tasks = [SubTask(title="A", prompt="..."), ...]
        result = await runner.run(tasks, max_concurrency=3)
    """

    def __init__(
        self,
        client: IChatClient,
        tools: Optional[ToolRegistry] = None,
        *,
        max_steps: int = 6,
        system_prompt: str = "",
        on_progress: Optional[Callable[[SubTask], None]] = None,
    ):
        self.client = client
        self.tools = tools
        self.max_steps = max_steps
        self.system_prompt = system_prompt
        self.on_progress = on_progress

    async def run_one(self, task: SubTask) -> SubTask:
        """执行单个子任务（fresh AgentLoop，独立上下文）。"""
        t0 = time.time()
        task.status = "running"
        if self.on_progress:
            self.on_progress(task)
        try:
            loop = AgentLoop(self.client, self.tools, max_steps=self.max_steps)
            result = await loop.run_async(
                [ChatMessage.user(task.prompt)],
                system_prompt=self.system_prompt,
            )
            task.output = result.reply or ""
            task.status = "done"
            task.result = result
        except Exception as e:
            task.error = str(e)
            task.status = "error"
            logger.exception("子任务 %s 失败", task.title)
        task.elapsed = time.time() - t0
        if self.on_progress:
            self.on_progress(task)
        return task

    async def run(self, tasks: list[SubTask], *,
                  max_concurrency: int = 3) -> SubAgentRunResult:
        """并发执行子任务；单任务失败不影响其他。"""
        result = SubAgentRunResult(tasks=tasks)
        sem = asyncio.Semaphore(max_concurrency)

        async def guarded(task: SubTask) -> SubTask:
            async with sem:
                return await self.run_one(task)

        await asyncio.gather(*(guarded(t) for t in tasks))
        return result

    def split(self, main_prompt: str, n: int = 3) -> list[SubTask]:
        """规则版任务拆分：按段落/句切分为 n 个子任务（无 LLM 依赖）。

        供应用层在无模型预算时使用；LLM 版拆分由应用自行实现。
        """
        paragraphs = [p.strip() for p in main_prompt.split("\n\n") if p.strip()]
        if len(paragraphs) < n:
            chunks = [main_prompt]
        else:
            size = (len(paragraphs) + n - 1) // n
            chunks = ["\n\n".join(paragraphs[i:i + size])
                      for i in range(0, len(paragraphs), size)]
        return [SubTask(title=f"子任务{i + 1}", prompt=c)
                for i, c in enumerate(chunks)]
