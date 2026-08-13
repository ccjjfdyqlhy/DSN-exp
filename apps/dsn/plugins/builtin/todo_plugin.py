# plugins/builtin/todo_plugin.py
# Todo 插件 — 复杂问题分解 + 并行子代理 + SSE 进度

from __future__ import annotations

import json
import logging
import re
import threading

from apps.dsn.plugins.base import Plugin, HookPoint, PluginContext
from apps.dsn.plugins.builtin.todo_store import get_todo_store, TodoPlan
from apps.dsn.plugins.builtin.subagent_runner import SubAgentRunner
from apps.dsn.config import Config

logger = logging.getLogger("TodoPlugin")

# 分解任务的 LLM prompt
_DECOMPOSE_PROMPT = """你是一个任务规划专家。用户提出了一个复杂请求，请将其分解为可独立执行的子任务。

## 用户请求
{message}

## 对话上下文 (最近 5 轮)
{context}

## 输出要求

以 JSON 数组输出子任务列表，每个子任务包含:
- title: 简短标题
- description: 详细描述（给子代理的 prompt）
- priority: 优先级 (0=最高, 数字越大越低)
- dependencies: 依赖的 item 序号列表 (如 [0, 1] 表示依赖第0和1号任务)
- parallel: 是否可以并行执行 (true/false)
- needs_sub_agent: 是否需要独立子代理处理 (复杂/需要多步推理的设为 true)

对于 needs_sub_agent=true 的任务，额外提供:
- sub_agent_prompt: 给子代理的详细 system prompt
- sub_agent_model: 使用的模型 ("fast"=通用模型, "deep"=深度推理模型)

## 分解原则
1. 每个子任务应该是独立可完成的单元
2. 优先考虑可以并行的子任务
3. 需要多步推理、搜索结果整合、代码编写的任务应标记为 needs_sub_agent=true
4. 简单的信息查询、确认类任务不需要子代理

只输出 JSON 数组，不要其他文字。"""


class TodoPlugin(Plugin):
    """
    Todo 分解与跟踪插件。

    POST_PROCESS 阶段 (priority=33，在 memory=30 后、skills=35 前):
    1. 检查 ComplexityAnalyzer 评分是否超过阈值
    2. 若超过，调用 LLM 将请求分解为子任务列表
    3. 将分解结果存入 TodoStore，通过 SSE 推送
    4. 为 needs_sub_agent=true 的子任务启动后台子代理
    5. 跟踪子代理进度，同步更新 TodoStore → SSE

    依赖:
    - models_plugin (ModelsPlugin) — LLM 调用
    - complexity_analyzer (ComplexityAnalyzer) — 复杂度评估
    - skill_registry (SkillRegistry) — 子代理可能需要工具
    - db (ChatDBManager) — 保存结果
    """

    name = "todo"
    description = "Todo 分解 — 复杂问题拆分 + 并行子代理 + SSE 进度跟踪"
    hooks = [HookPoint.POST_PROCESS]
    priority = 33

    # 复杂度阈值：超过这个分数才触发 todo 分解
    _COMPLEXITY_THRESHOLD = 0.5
    # 最小消息长度才触发
    _MIN_MESSAGE_LENGTH = 30
    # 子代理最大并发数
    _MAX_PARALLEL_SUBAGENTS = 5

    def __init__(
        self,
        models_plugin=None,
        complexity_analyzer=None,
        skill_registry=None,
        db=None,
        task_manager=None,
    ):
        self._models = models_plugin
        self._complexity = complexity_analyzer
        self._skill_registry = skill_registry
        self._db = db
        self._task_mgr = task_manager
        self._store = get_todo_store()
        self._active_sub_agents: dict[str, threading.Thread] = {}
        self._runner = SubAgentRunner(
            models_plugin=models_plugin,
            skill_registry=skill_registry,
            db=db,
            task_manager=task_manager,
            max_steps=getattr(Config, "SUBAGENT_MAX_STEPS", 3),
        )

    def on_load(self) -> None:
        if self._models is None:
            logger.warning("models_plugin 未注入，TodoPlugin 将跳过分解")

    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        if self._models is None:
            return ctx
        if hook != HookPoint.POST_PROCESS:
            return ctx

        # 检查是否应该触发 todo 分解
        if not self._should_decompose(ctx):
            return ctx

        # 启动后台分解流程（不阻塞主回复）
        self._start_decomposition(ctx)
        return ctx

    # ── 触发判断 ──

    def _should_decompose(self, ctx: PluginContext) -> bool:
        message = ctx.message or ""
        if len(message) < self._MIN_MESSAGE_LENGTH:
            return False

        # 复杂度分析
        if self._complexity:
            try:
                context_len = len(ctx.history) if ctx.history else 0
                result = self._complexity.analyze_complexity(message, context_len)
                if not result.get("is_complex", False):
                    return False
                score = result.get("score", 0)
                logger.info("Todo 复杂度评分: %.2f (阈值=%.2f)", score, self._COMPLEXITY_THRESHOLD)
                if score < self._COMPLEXITY_THRESHOLD:
                    return False
            except Exception as e:
                logger.warning("复杂度分析失败: %s，使用启发式判断", e)
                if not self._heuristic_check(message):
                    return False
        else:
            if not self._heuristic_check(message):
                return False

        return True

    @staticmethod
    def _heuristic_check(message: str) -> bool:
        """启发式判断：消息是否足够复杂"""
        keywords = [
            "设计", "项目", "多个", "模块", "系统", "架构",
            "批量", "全部", "所有", "整套", "方案", "实现",
            "包含", "同时", "并且", "以及",
        ]
        msg_lower = message.lower()
        matched = sum(1 for kw in keywords if kw in msg_lower)
        return matched >= 3 and len(message) > 50

    # ── 分解流程 ──

    def _start_decomposition(self, ctx: PluginContext) -> None:
        """在后台线程中执行 todo 分解"""
        user_id = ctx.user_id
        chat_id = ctx.chat_id or 0
        message = str(ctx.message)
        history = list(ctx.history) if ctx.history else []

        def _run():
            try:
                plan = self._store.create_plan(chat_id, user_id)
                logger.info("Todo 分解开始: todo_id=%s, chat=%d, user=%d",
                            plan.todo_id, chat_id, user_id)

                items = self._decompose(message, history)
                if not items:
                    self._store.set_failed(plan.todo_id, "未能分解出子任务")
                    return

                self._store.set_items(plan.todo_id, items)
                logger.info("Todo 分解完成: %d 个子任务", len(items))

                # 启动子代理
                self._spawn_sub_agents(plan.todo_id, ctx)

            except Exception as e:
                logger.exception("Todo 分解异常: %s", e)

        t = threading.Thread(target=_run, daemon=True, name=f"todo-decompose-{chat_id}")
        t.start()

    def _decompose(self, message: str, history: list) -> list[dict] | None:
        """调用 LLM 分解任务"""
        # 构建上下文
        context_text = ""
        for msg in history[-10:]:
            role = "用户" if msg.get("role") == "user" else "EXA"
            context_text += f"{role}: {msg.get('content', '')[:300]}\n"

        prompt = _DECOMPOSE_PROMPT.format(message=message, context=context_text)

        try:
            response = self._models.invoke(
                [{"role": "system", "content": prompt}],
                None,  # ctx not needed for todo decomposition
            )
            return self._parse_decomposition(response)
        except Exception as e:
            logger.error("Todo 分解 LLM 调用失败: %s", e)
            return None

    @staticmethod
    def _parse_decomposition(response: str) -> list[dict] | None:
        """解析 LLM 返回的任务分解 JSON"""
        json_match = re.search(r"\[.*\]", response, re.DOTALL)
        if not json_match:
            return None
        try:
            items = json.loads(json_match.group())
            if not isinstance(items, list) or len(items) == 0:
                return None
            return items
        except json.JSONDecodeError:
            return None

    # ── 子代理孵化 ──

    def _spawn_sub_agents(self, todo_id: str, ctx: PluginContext) -> None:
        """为 needs_sub_agent=true 的 item 启动后台子代理"""
        plan = self._store.get_plan(todo_id)
        if not plan:
            return

        pending = [it for it in plan.items if it.status == "pending"]
        # 按优先级排序，按依赖排序
        pending.sort(key=lambda it: (it.priority, it.id))

        spawned = 0
        for item in pending:
            # 优先采纳主模型(assigner)的 needs_sub_agent 决策，缺失时用启发式兜底
            if item.needs_sub_agent is None:
                needs_sub = any(
                    kw in item.title.lower() + item.description.lower()
                    for kw in ("设计", "编写", "分析", "搜索", "审查", "实现", "构建")
                )
            else:
                needs_sub = item.needs_sub_agent

            if not needs_sub:
                # 简单任务直接标记完成（由主回答覆盖）
                self._store.update_item(todo_id, item.id, status="completed",
                                        result="由主回答覆盖")
                continue

            if spawned >= self._MAX_PARALLEL_SUBAGENTS:
                break

            spawned += 1
            self._launch_sub_agent(todo_id, item, ctx)

        # 检查是否所有项都完成了
        self._check_plan_complete(todo_id)

    def _launch_sub_agent(self, todo_id: str, item, ctx: PluginContext) -> None:
        """启动单个子代理 — 隔离上下文 + 工具小循环，完成后即释放"""
        self._store.update_item(todo_id, item.id, status="in_progress")

        def _run():
            try:
                logger.info("子代理启动: %s (item=%s)", todo_id, item.id)
                # system prompt 优先使用主模型(assigner)书写的 sub_agent_prompt
                system_prompt = (
                    item.sub_agent_prompt
                    if item.sub_agent_prompt
                    else (
                        f"你是一个专注的子任务执行代理。你的唯一任务是：{item.description}\n\n"
                        f"任务标题：{item.title}\n"
                        "请直接给出结果，不要询问用户更多信息。"
                    )
                )
                result = self._runner.run(
                    system_prompt=system_prompt,
                    task=item.title,
                    user_id=ctx.user_id,
                    chat_id=ctx.chat_id or 0,
                    model_type=item.sub_agent_model or None,
                )
                if result.error:
                    self._store.update_item(
                        todo_id, item.id, status="failed", error=result.error)
                else:
                    self._store.update_item(
                        todo_id, item.id, status="completed", result=result.output)
                logger.info("子代理完成: %s (item=%s, steps=%d, tools=%d)",
                            todo_id, item.id, result.steps, len(result.tool_trace))

            except Exception as e:
                logger.error("子代理失败: %s (item=%s): %s", todo_id, item.id, e)
                self._store.update_item(todo_id, item.id, status="failed", error=str(e))

            self._check_plan_complete(todo_id)
            # 用完即释放：移除引用，让子代理线程随结束被回收
            self._active_sub_agents.pop(item.id, None)

        t = threading.Thread(target=_run, daemon=True, name=f"subagent-{item.id}")
        t.start()
        self._active_sub_agents[item.id] = t
        self._store.update_item(todo_id, item.id, sub_agent_id=t.name)

    def _check_plan_complete(self, todo_id: str) -> None:
        plan = self._store.get_plan(todo_id)
        if not plan:
            return

        if plan.status == "completed":
            # 收集所有结果，调用 LLM 做最终总结
            self._finalize_plan(todo_id)

    def _finalize_plan(self, todo_id: str) -> None:
        """收集子代理结果，生成最终总结"""
        plan = self._store.get_plan(todo_id)
        if not plan:
            return

        results = []
        for item in plan.items:
            if item.result:
                results.append(f"[{item.title}]\n{item.result[:2000]}")
            elif item.status == "failed":
                results.append(f"[{item.title}] 失败: {item.error or '未知错误'}")
        if not results:
            self._store.set_completed(todo_id, "所有子任务已完成。")
            logger.info("Todo 计划完成: %s", todo_id)
            return

        try:
            summary_prompt = (
                "你是任务的分配者(assigner)。以下是分派给子代理的任务及其输出，"
                "请整合为一个简洁的总结告知用户完成情况：\n\n"
                + "\n\n".join(results)
            )
            summary = self._models.invoke(
                [{"role": "system", "content": summary_prompt}], None
            )
            self._store.set_completed(todo_id, summary)
        except Exception:
            self._store.set_completed(todo_id, "\n".join(results))

        logger.info("Todo 计划完成: %s", todo_id)
