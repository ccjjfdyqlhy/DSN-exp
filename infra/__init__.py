# infra/__init__.py
"""infra — AICF 基础设施与运行时管理层。

本包承载与具体 Agent 业务语义无关的基础设施：模型/引擎编排（orchestrator）、
异构资源池（resources）、运行时 DI 容器（runtime）、应用生命周期（subapps）、
配置（settings）、语义缓存（cache）、持久化（store）、可观测性（observability）、
异步任务（tasks）、Web 网关（gateway）、认证（auth）与策略（policy）。

Agent 核心（agent 循环、工具、管线、人格、记忆、提示词、技能、代码图谱、
上下文装配与 SDK）仍位于 harness/。
"""

__all__: list[str] = []
