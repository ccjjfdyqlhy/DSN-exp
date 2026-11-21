#!/usr/bin/env python3
# examples/minimal.py —— 最小可运行例（roadmap 段 3）。
#
# 三十行、零依赖（只装 aicf-core）、不需要 API key，直接打印结果。
#
#   python examples/minimal.py
#
# 它做两件事，对应 aicf 的两个核心动作：
#   1. 起一个 Agent 跑一轮（无 key → 桩模型回显；有 OPENAI_API_KEY → 真模型）
#   2. 让一个工具走完守卫链路（策略 → 审批 → 幂等 → 审计）真实执行一次
#
# 想要「agent 自己决定调工具」，配上真模型即可 —— 代码一行都不用改。

import asyncio
import os

from aicf.harness import create_agent, tool

# ── 1. 写一个工具：普通函数 + docstring，签名就是参数 schema ──────────


@tool
def add(a: int, b: int) -> int:
    """把两个整数相加。"""
    return a + b


# ── 2. 起一个 Agent：有 key 用真模型，没 key 用桩模型（离线可跑）──────

client = None
if not os.environ.get("OPENAI_API_KEY"):
    from aicf.infra.orchestrator.base import ChatResponse
    from aicf.infra.orchestrator.stub import StubChatClient

    def _respond(messages, tools):
        text = ""
        for message in reversed(messages or []):
            content = message.get("content") if isinstance(message, dict) else ""
            if content:
                text = str(content)
                break
        return ChatResponse(content=f"[stub] {text}")

    client = StubChatClient(model="stub", respond=_respond)
    print("(未配置 OPENAI_API_KEY，本轮用桩模型回显)\n")

agent = create_agent(model="gpt-4o-mini", client=client, tools=[add])
print("agent.chat  →", agent.chat("你好，请确认你在线"))

# ── 3. 让工具走一次完整守卫链路（这是 aicf 与「裸函数调用」的区别）────
# 声明契约：pure + readonly → 默认策略（低风险自动放行）直接执行；
# 不声明就是最严格档（effectful + 需审批）—— 忘写声明不会静默放权。

from aicf.harness.tools.guard import ToolGuard
from aicf.harness.tools.registry import ManagedToolRegistry
from aicf.harness.tools.spec import ToolSpec
from aicf.infra.policy.engine import RulePolicyEngine

add.spec = ToolSpec.read_only_default("add")
registry = ManagedToolRegistry()
registry.register(add)
registry.attach_guard(ToolGuard(policy=RulePolicyEngine()))
result = asyncio.run(registry.execute_async("add", {"a": 1, "b": 2}))
print("guard 链路   → add(1, 2) =", result.output)
