# engine.py — 用 DSN-exp harness 基座承载 Dekacode WebUI 的 Agent 引擎。
#
# 与 ~/dekacode 的差异：
#   - 不再依赖 dekacode 私有模块，改用 harness 的 AgentLoop / ToolRegistry /
#     SessionStore / codegraph / ContextGatherer。
#   - 保留 WebUI 前端协议（/ws + /api/*），后端换为 harness 驱动。
#   - 增加配置管理、Provider/模型切换、技能加载、上下文快照与统计。

from __future__ import annotations

import json
import os
import time
import asyncio
from collections import Counter
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from harness import (
    ContextGatherer,
    ToolDeps,
    ToolRegistry,
    install_standard_tools,
)
from harness.agent import AgentLoop, ModeState, SubAgentRunner, SubTask
from harness.codegraph import GraphBuilder
from harness.models.base import ChatMessage
from harness.models.openai import OpenAICompatClient
from harness.tools import RegistryIndexSource, ToolboxManager

from .config import DekacodeConfig
from .store import CentralSessionStore
from .tools import install_extra_tools, load_skills_from_dir

# 与前端 app.js 中 toolStatusLabel / _TOOL_STATUS_MAP 对应的可读状态。
_TOOL_STATUS_MAP = {
    "file.read": "Reading", "file.write": "Writing", "file.edit": "Editing",
    "file.list": "Listing", "file.tree": "Tree",
    "file.grep": "Grepping", "file.glob": "Globbing",
    "text.chunk": "Chunking", "text.extract_json": "Extracting JSON",
    "text.diff": "Diffing",
    "code.syntax_check": "Checking", "code.locate_symbol": "Searching",
    "code.diagnose": "Diagnosing", "code.callers": "Tracing",
    "code.read_symbol": "Reading",
    "proc.run": "Running", "web.fetch": "Fetching",
    "project.summary": "Summarizing", "project.snapshot": "Snapshotting",
    "project.todo": "Updating todo", "batch.run": "Batching",
    "git.status": "Git status", "git.diff": "Diffing", "git.commit": "Committing",
}


class TrackingClient:
    """包装 IChatClient，捕获流式/非流式调用的 usage 信息。"""

    def __init__(self, inner: Any):
        self._inner = inner
        self.model = getattr(inner, "model", "")
        self.last_usage: dict[str, Any] = {}

    async def stream(self, messages, tools=None, **kwargs):
        async for chunk in self._inner.stream(messages, tools=tools, **kwargs):
            if isinstance(chunk, dict) and chunk.get("usage"):
                self.last_usage = chunk["usage"]
            yield chunk

    def invoke(self, messages, tools=None, **kwargs):
        resp = self._inner.invoke(messages, tools=tools, **kwargs)
        if getattr(resp, "usage", None):
            self.last_usage = resp.usage
        return resp


def _tool_label(name: str, args: Optional[dict] = None) -> str:
    label = _TOOL_STATUS_MAP.get(name, "Working")
    if not args:
        return label
    detail = ""
    if name in ("file.read", "file.write", "file.edit", "code.syntax_check"):
        detail = str(args.get("path") or args.get("target") or "")
    elif name in ("proc.run",):
        detail = str(args.get("command", ""))[:80]
    elif name == "web.fetch":
        detail = str(args.get("url", ""))
    elif name in ("code.locate_symbol", "code.callers", "code.read_symbol"):
        detail = str(args.get("name") or args.get("symbol") or "")
    elif name in ("file.list", "file.tree"):
        detail = str(args.get("path", "."))
    elif name == "file.grep":
        detail = str(args.get("pattern", ""))
    elif name == "file.glob":
        detail = str(args.get("pattern", ""))
    elif name == "git.diff":
        detail = str(args.get("path", ""))
    elif name == "git.commit":
        detail = str(args.get("message", ""))[:40]
    return f"{label} {detail}".strip() if detail else label


class DekacodeEngine:
    """基于 harness 的 Dekacode WebUI 后端引擎。"""

    def __init__(self, project_root: Optional[str] = None, *, max_steps: Optional[int] = None):
        self.config = DekacodeConfig.from_env(project_root)
        if max_steps is not None:
            self.config.max_steps = max_steps
        self.project_root = self.config.project_root
        self.max_steps = self.config.max_steps

        self._providers = self._load_providers()
        self.active_provider_id = self.config.active_provider
        if not any(p.get("id") == self.active_provider_id for p in self._providers):
            self.active_provider_id = self._providers[0]["id"]
        self.model_mode = self.config.model_mode
        self._apply_active_provider()

        # 项目符号图 + 标准工具集（harness 基座）
        self.graph = GraphBuilder(self.project_root).build()
        self.tools = ToolRegistry()
        deps = ToolDeps(
            workspace=self.project_root,
            codegraph=self.graph,
            tool_registry=self.tools,
            max_output_chars=self.config.max_output_chars,
        )
        install_standard_tools(self.tools, deps=deps)
        install_extra_tools(self.tools, workspace=self.project_root, graph=self.graph)
        self.skill_report: dict[str, Any] = {"loaded": [], "errors": []}
        if self.config.enable_skills:
            self.skill_report = load_skills_from_dir(
                self.tools, self.config.skills_dir, deps=deps
            )
        self._register_subagent_tool()

        # 会话持久化（全局 ~/.dekacode，按 workspace 分组）
        self.store = CentralSessionStore(db_path=self.config.db_path)
        self.workspace_id = self.store.ensure_workspace(self.project_root)

        self.gatherer = ContextGatherer(self.project_root, graph=self.graph)
        self.load_prompts()

    def set_workspace(self, path: str) -> str:
        """切换到指定工作区，并重建该工作区的符号图/工具集。"""
        new_root = str(Path(path).resolve())
        if new_root == self.project_root and self.workspace_id:
            return self.workspace_id
        self.project_root = new_root
        self.config.project_root = new_root
        self.graph = GraphBuilder(new_root).build()
        self.tools = ToolRegistry()
        deps = ToolDeps(
            workspace=new_root,
            codegraph=self.graph,
            tool_registry=self.tools,
            max_output_chars=self.config.max_output_chars,
        )
        install_standard_tools(self.tools, deps=deps)
        install_extra_tools(self.tools, workspace=new_root, graph=self.graph)
        self._register_subagent_tool()
        self.skill_report = {"loaded": [], "errors": []}
        if self.config.enable_skills:
            self.skill_report = load_skills_from_dir(
                self.tools, self.config.skills_dir, deps=deps
            )
        self.gatherer = ContextGatherer(new_root, graph=self.graph)
        self.load_prompts()
        self.workspace_id = self.store.ensure_workspace(new_root)
        return self.workspace_id

    def load_prompts(self) -> None:
        """从 prompts 目录加载 .md 提示词片段，拼成 system_prompt。"""
        prompt_dir = Path(self.config.prompts_dir)
        parts: list[str] = []
        if prompt_dir.is_dir():
            for f in sorted(prompt_dir.glob("*.md")):
                try:
                    parts.append(f.read_text(encoding="utf-8").strip())
                except OSError:
                    continue
        env_prompt = os.getenv("DEKACODE_SYSTEM_PROMPT", "").strip()
        if env_prompt:
            parts.insert(0, env_prompt)
        self.system_prompt = "\n\n".join(parts) or (
            "你是一名资深软件工程师助手，运行在 DSN-exp harness 之上。"
            f"工作区: {self.project_root}"
        )

    def reload_prompts(self) -> list[dict[str, str]]:
        self.load_prompts()
        prompt_dir = Path(self.config.prompts_dir)
        files = []
        if prompt_dir.is_dir():
            for f in sorted(prompt_dir.glob("*.md")):
                try:
                    files.append({"name": f.name, "content": f.read_text(encoding="utf-8")})
                except OSError:
                    continue
        return files

    def list_prompts(self) -> list[dict[str, str]]:
        return self.reload_prompts()

    def save_prompt(self, name: str, content: str) -> None:
        prompt_dir = Path(self.config.prompts_dir)
        prompt_dir.mkdir(parents=True, exist_ok=True)
        if not name.endswith(".md"):
            name += ".md"
        target = prompt_dir / name
        target.write_text(content, encoding="utf-8")
        self.load_prompts()

    def _register_subagent_tool(self) -> None:
        """注册 task.split：用 harness SubAgentRunner 并行执行子任务。"""
        async def split_task(tasks: list[dict], max_concurrency: int = 3) -> str:
            subtasks = [
                SubTask(title=str(t.get("title", "")), prompt=str(t.get("prompt", "")))
                for t in tasks
            ]
            if not subtasks:
                return "(未提供 tasks)"
            runner = SubAgentRunner(
                self.client,
                self.tools,
                max_steps=self.max_steps,
                system_prompt=self.system_prompt,
            )
            result = await runner.run(subtasks, max_concurrency=max_concurrency)
            return result.summary()

        self.tools.register_tool(
            "task.split",
            "把一个大任务拆成多个子任务并发执行，返回每个子任务的结果摘要。"
            "参数 tasks 为 [{title, prompt}]。",
            split_task,
            parameters={
                "type": "object",
                "properties": {
                    "tasks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "prompt": {"type": "string"},
                            },
                            "required": ["title", "prompt"],
                        },
                    },
                    "max_concurrency": {"type": "integer", "default": 3},
                },
                "required": ["tasks"],
            },
            async_mode=True,
        )

    # ── Provider / 模型管理 ──

    def _default_provider(self) -> dict[str, Any]:
        return {
            "id": "default",
            "name": self.config.provider_name,
            "base_url": self.config.base_url,
            "api_key": self.config.api_key,
            "protocol": "chat",
            "models": {
                "flash": self.config.flash_model,
                "pro": self.config.pro_model,
                "openai": self.config.openai_model,
            },
        }

    def _load_providers(self) -> list[dict[str, Any]]:
        pf = Path(self.config.providers_file)
        if pf.is_file():
            try:
                data = json.loads(pf.read_text(encoding="utf-8"))
                if isinstance(data, list) and data:
                    return data
            except (OSError, json.JSONDecodeError):
                pass
        return [self._default_provider()]

    def _save_providers(self) -> None:
        Path(self.config.providers_file).write_text(
            json.dumps(self._providers, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _active_provider(self) -> dict[str, Any]:
        for p in self._providers:
            if p.get("id") == self.active_provider_id:
                return p
        return self._providers[0]

    def _apply_active_provider(self) -> None:
        p = self._active_provider()
        self.client = TrackingClient(OpenAICompatClient(
            api_key=p.get("api_key", "") or "",
            base_url=p.get("base_url", self.config.base_url),
            model=self._model_for(self.model_mode),
            timeout=120,
            protocol=p.get("protocol", "chat"),
        ))

    def _model_for(self, mode: str) -> str:
        p = self._active_provider()
        models = p.get("models", {}) or {}
        return models.get(mode or "flash") or models.get("flash") or self.config.flash_model

    def new_session(self) -> "DekacodeSession":
        return DekacodeSession(self)

    def switch_model(self, mode: str) -> str:
        mode = (mode or "flash").lower()
        if mode not in ("flash", "pro", "openai"):
            raise ValueError(f"未知模型: {mode}")
        self.config.model_mode = mode
        self.model_mode = mode
        self.client.model = self._model_for(mode)
        return self.client.model

    def list_models(self) -> list[dict]:
        p = self._active_provider()
        models = p.get("models", {}) or {}
        result = [
            {"id": mid, "label": mid.capitalize(), "model": mname}
            for mid, mname in models.items()
        ]
        for m in result:
            m["active"] = m["id"] == self.model_mode
        return result

    def get_config(self) -> dict[str, Any]:
        return self.config.to_dict(masked=True)

    def update_config(self, key: str, value: Any) -> dict[str, Any]:
        old_value = getattr(self.config, key)
        new_value = self.config.update(key, value)
        DekacodeConfig.write_env(self.project_root, key, new_value)
        if key in ("api_key", "base_url", "provider_name", "flash_model", "pro_model", "openai_model", "model_mode"):
            p = self._active_provider()
            if key == "model_mode":
                self.switch_model(new_value)
            else:
                if key == "api_key" and str(new_value).startswith("*"):
                    pass
                else:
                    if key == "provider_name":
                        p["name"] = new_value
                    elif key in ("flash_model", "pro_model", "openai_model"):
                        p.setdefault("models", {})[key.split("_")[0]] = new_value
                    else:
                        p[key] = new_value
                    self._save_providers()
                self._apply_active_provider()
        return {"key": key, "old_value": str(old_value), "new_value": str(new_value)}

    def providers(self) -> list[dict]:
        result = []
        for p in self._providers:
            d = dict(p)
            if d.get("api_key"):
                key = str(d["api_key"])
                d["api_key"] = ("*" * 4) + key[-4:] if len(key) > 8 else "*" * len(key)
            d["active"] = p.get("id") == self.active_provider_id
            d["models"] = [
                {"id": mid, "label": mid.capitalize(), "model": mname}
                for mid, mname in (p.get("models", {}) or {}).items()
            ]
            d["active_model"] = self.model_mode
            result.append(d)
        return result

    def update_provider(self, data: dict[str, Any]) -> dict[str, Any]:
        provider_id = data.get("id") or "default"
        target = next((p for p in self._providers if p.get("id") == provider_id), None)
        if target is None:
            target = self._default_provider()
            target["id"] = provider_id
            self._providers.append(target)
        for key in ("name", "base_url", "api_key", "protocol"):
            if key in data and data[key] is not None:
                if key == "api_key" and str(data[key]).startswith("*"):
                    continue
                target[key] = data[key]
        models = target.setdefault("models", {})
        for key in ("flash_model", "pro_model", "openai_model"):
            if key in data and data[key] is not None:
                models[key.split("_")[0]] = data[key]
        if data.get("active"):
            self.active_provider_id = provider_id
            self.config.active_provider = provider_id
            DekacodeConfig.write_env(self.project_root, "active_provider", provider_id)
        if "active_model" in data and data["active_model"]:
            self.switch_model(data["active_model"])
        self._save_providers()
        self._apply_active_provider()
        return next(p for p in self.providers() if p["id"] == provider_id)

    def delete_provider(self, provider_id: str) -> None:
        if len(self._providers) <= 1:
            raise ValueError("至少保留一个 Provider")
        before = len(self._providers)
        self._providers = [p for p in self._providers if p.get("id") != provider_id]
        if len(self._providers) == before:
            raise KeyError(provider_id)
        if self.active_provider_id == provider_id:
            self.active_provider_id = self._providers[0]["id"]
            self.config.active_provider = self.active_provider_id
            DekacodeConfig.write_env(self.project_root, "active_provider", self.active_provider_id)
        self._save_providers()
        self._apply_active_provider()

    def reload_skills(self) -> dict[str, Any]:
        """重新构建工具注册表并加载技能（配置变更后调用）。"""
        self.tools = ToolRegistry()
        deps = ToolDeps(
            workspace=self.project_root,
            codegraph=self.graph,
            tool_registry=self.tools,
            max_output_chars=self.config.max_output_chars,
        )
        install_standard_tools(self.tools, deps=deps)
        install_extra_tools(self.tools, workspace=self.project_root, graph=self.graph)
        self.skill_report = {"loaded": [], "errors": []}
        if self.config.enable_skills:
            self.skill_report = load_skills_from_dir(
                self.tools, self.config.skills_dir, deps=deps
            )
        self._register_subagent_tool()
        return self.skill_report

    def compute_stats(self) -> dict[str, Any]:
        sessions = self.store.list_sessions(limit=1000)
        total_messages = sum(s.get("message_count", 0) for s in sessions)
        total_cost = sum(float(s.get("total_cost", 0) or 0) for s in sessions)
        total_input = sum(int(s.get("total_input", 0) or 0) for s in sessions)
        tool_messages = 0
        tool_calls = 0
        for s in sessions[:100]:
            for m in self.store.load_messages(s["id"]):
                if m.role == "tool":
                    tool_messages += 1
                if m.tool_calls:
                    tool_calls += len(m.tool_calls)
        return {
            "sessions": len(sessions),
            "messages": total_messages,
            "tool_messages": tool_messages,
            "tool_calls": tool_calls,
            "total_cost": round(total_cost, 4),
            "total_input_tokens": total_input,
            "symbols": self.graph.total_symbols() if self.graph else 0,
            "files": len(self.graph.files) if self.graph else 0,
            "tools": len(self.tools),
            "skills": len(self.skill_report.get("loaded", [])),
            "model": self.model_display,
        }

    @property
    def model_display(self) -> str:
        return self.client.model


class DekacodeSession:
    """一个 WebSocket 会话：消息历史 + 模式 + 持久化游标。"""

    def __init__(self, engine: DekacodeEngine):
        self.engine = engine
        self.messages: list[ChatMessage] = []
        self.mode = ModeState()
        self.session_id: Optional[str] = None
        self.workspace_id: Optional[str] = engine.workspace_id
        self._saved_len = 0
        self._stop_requested = False
        self._last_input = ""
        self._turn_index = 0
        self._turn_start_time = 0.0
        self.toolbox = ToolboxManager(
            RegistryIndexSource(engine.tools),
            enabled=True,
            max_activated=30,
        )

    # ── 控制 ──

    def stop(self) -> None:
        self._stop_requested = True

    # ── 持久化 ──

    def load_session(self, session_id: str) -> bool:
        hist = self.engine.store.load_messages(session_id)
        if not hist:
            return False
        self.engine.store.set_session(session_id)
        self.session_id = session_id
        self.workspace_id = self.engine.store.get_session_workspace(session_id)
        self.messages = hist
        self._saved_len = len(hist)
        mode = self.engine.store.get_mode(session_id)
        if mode:
            try:
                self.mode.switch(mode)
            except ValueError:
                pass
        return True

    def _persist(self) -> None:
        if not self.session_id:
            self.session_id = self.engine.store.create_session(workspace_id=self.workspace_id)
            self._saved_len = 0
        elif self.workspace_id:
            self.engine.store.update_workspace(self.workspace_id, self.session_id)
        unsaved = self.messages[self._saved_len:]
        if unsaved:
            self.engine.store.save_messages(unsaved, session_id=self.session_id)
            self._saved_len = len(self.messages)
        if self.session_id:
            self.engine.store.set_mode(self.mode.mode.value, self.session_id)

    def _persist_usage(self) -> None:
        if not self.session_id:
            return
        usage = getattr(self.engine.client, "last_usage", {}) or {}
        input_tokens = int(usage.get("prompt_tokens", 0) or 0)
        output_tokens = int(usage.get("completion_tokens", 0) or 0)
        cache_hit = int(usage.get("prompt_cache_hit_tokens", 0) or 0)
        cost = (
            input_tokens / 1_000_000 * self.engine.config.input_price_per_mtok
            + output_tokens / 1_000_000 * self.engine.config.output_price_per_mtok
        )
        self.engine.store.save_usage(
            self._turn_index,
            tier=self.engine.model_mode,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_hit_input=cache_hit,
            cost=round(cost, 6),
            session_id=self.session_id,
        )
        self._turn_index += 1

    async def _send_summary(self, send: Callable[..., Awaitable[bool]]) -> None:
        usage = getattr(self.engine.client, "last_usage", {}) or {}
        input_tokens = int(usage.get("prompt_tokens", 0) or 0)
        output_tokens = int(usage.get("completion_tokens", 0) or 0)
        cache_hit = int(usage.get("prompt_cache_hit_tokens", 0) or 0)
        elapsed = time.time() - self._turn_start_time if self._turn_start_time else 0.0
        if input_tokens == 0 and output_tokens == 0:
            await send(type="summary", elapsed=round(elapsed, 1), usage_supported=False)
            return
        cost = (
            input_tokens / 1_000_000 * self.engine.config.input_price_per_mtok
            + output_tokens / 1_000_000 * self.engine.config.output_price_per_mtok
        )
        await send(
            type="summary",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_hit=cache_hit,
            cache_miss=max(0, input_tokens - cache_hit),
            cost=round(cost, 4),
            elapsed=round(elapsed, 1),
            ctx_pct=round(input_tokens / 1_000_000 * 100, 1),
            cache_pct=round(cache_hit / input_tokens * 100, 0) if input_tokens else 0,
            out_pct=round(output_tokens / 128_000 * 100, 1),
            usage_supported=True,
        )

    # ── 上下文快照 / 统计 ──

    def context_snapshot(self) -> dict[str, Any]:
        roles = Counter(m.role for m in self.messages)
        tool_calls = sum(len(m.tool_calls or []) for m in self.messages)
        total_chars = sum(len(m.content or "") for m in self.messages)
        return {
            "history": len(self.messages),
            "roles": dict(roles),
            "tool_calls": tool_calls,
            "total_chars": total_chars,
            "system_prompt": self.engine.system_prompt,
            "session_id": self.session_id,
            "workspace_id": self.workspace_id,
        }

    @property
    def context_stats(self) -> dict[str, int]:
        snap = self.context_snapshot()
        return {"history": snap["history"], "total": snap["history"]}

    # ── 消息处理 ──

    async def process_message(
        self,
        user_input: str,
        send: Callable[..., Awaitable[bool]],
    ) -> None:
        self._last_input = user_input
        self._stop_requested = False
        self._turn_start_time = time.time()
        try:
            # 整轮处理加超时安全网：模型/DB 万一无限挂起时能恢复而不是永久卡死
            turn_timeout = getattr(self.engine.config, "turn_timeout", 300)
            if self.mode.is_oneshot:
                await asyncio.wait_for(
                    self._process_oneshot(user_input, send), timeout=turn_timeout)
            else:
                await asyncio.wait_for(
                    self._process_agent(user_input, send), timeout=turn_timeout)
        except asyncio.TimeoutError:
            await send(
                type="trace", event="error",
                t=round(time.time() - self._turn_start_time, 3),
                error="处理超时，已中止本轮",
            )
            await send(type="error", content=f"处理超时（>{turn_timeout}s），已中止")
            await send(type="thinking_done")
        except Exception as e:  # noqa: BLE001
            await send(
                type="trace", event="error",
                t=round(time.time() - self._turn_start_time, 3),
                error=f"{type(e).__name__}: {e}",
            )
            await send(type="error", content=f"处理失败: {e}")
            await send(type="thinking_done")

    async def _process_agent(
        self,
        user_input: str,
        send: Callable[..., Awaitable[bool]],
    ) -> None:
        self.messages.append(ChatMessage.user(user_input))
        await send(type="thinking_start", status="Thinking...")
        try:
            await self._run_harness_loop(send)
        finally:
            # 即使流式中途异常/超时取消，也要先把已产生的消息持久化。
            # SQLite 已设 busy_timeout=10s，不会无限阻塞；同步执行保证一定会写库。
            self._persist()
        if self.session_id:
            await send(type="session_id", session_id=self.session_id)
        self._persist_usage()
        await self._send_summary(send)
        await self._trace_turn_end(send)
        await send(type="thinking_done")

    async def _trace_turn_end(self, send: Callable[..., Awaitable[bool]]) -> None:
        """turn 结束的 trace 事件：持久化结果 + 用量，收尾时间轴。"""
        usage = getattr(self.engine.client, "last_usage", {}) or {}
        await send(
            type="trace", event="turn_end",
            t=round(time.time() - self._turn_start_time, 3)
            if self._turn_start_time else 0.0,
            session_id=self.session_id or "",
            saved_messages=self._saved_len,
            input_tokens=int(usage.get("prompt_tokens", 0) or 0),
            output_tokens=int(usage.get("completion_tokens", 0) or 0),
        )

    async def _process_oneshot(
        self,
        user_input: str,
        send: Callable[..., Awaitable[bool]],
    ) -> None:
        parsed = self.engine.gatherer.parse(user_input)
        clean = parsed.clean_input or user_input
        if parsed.directives_found and parsed.context_block:
            self.messages.append(ChatMessage.system(parsed.context_block))
            await send(type="thinking_status", status="Gathered @context")
        self.messages.append(ChatMessage.user(clean))
        await send(type="thinking_start", status="One-shot thinking...")
        try:
            await self._run_harness_loop(send)
        finally:
            self._persist()
        if self.session_id:
            await send(type="session_id", session_id=self.session_id)
        self._persist_usage()
        await self._send_summary(send)
        await self._trace_turn_end(send)
        await send(type="thinking_done")

    @staticmethod
    def _safe_context_start(msgs: list[ChatMessage], start: int) -> int:
        """把起始下标向前扩展，避免以 tool 消息开头或拆散 tool_calls 组。"""
        start = max(0, start)
        while True:
            first_tool = None
            for i in range(start, len(msgs)):
                if msgs[i].role == "tool":
                    first_tool = i
                    break
            if first_tool is None:
                return start
            j = first_tool - 1
            while j >= 0 and msgs[j].role != "assistant":
                j -= 1
            if j >= 0 and msgs[j].tool_calls and j < start:
                start = j
                continue
            return start

    def _build_run_context(self) -> list[ChatMessage]:
        """按配置剪裁送入模型的上下文（不修改持久化历史），并保证 tool 组完整。

        剪裁策略：从头开始逐步丢弃最旧消息；assistant(tool_calls) + 其后连续
        tool 消息作为一个不可分割的"单元"，要丢就整组丢，从而保证：
          - 不会以 tool 消息开头 / 拆散 tool_calls 组；
          - start 单调前进（_drop_group_start 严格返回更大下标），
            不会像旧实现那样被 _safe_context_start 拉回造成死循环。
        """
        msgs = list(self.messages)
        max_msgs = self.engine.config.max_history_messages
        budget = self.engine.config.context_budget

        # 1) 消息条数剪裁，避免从 tool 消息开头（宁可多保留一点也要保证组完整）
        if max_msgs > 0 and len(msgs) > max_msgs:
            start = self._safe_context_start(msgs, len(msgs) - max_msgs)
            msgs = msgs[start:]

        # 2) 字符预算剪裁，同样保证 tool 组完整（单调推进，绝不死循环）
        start = self._safe_context_start(msgs, 0)
        total = sum(len(m.content or "") for m in msgs[start:])
        while total > budget and start < len(msgs):
            start = self._drop_group_start(msgs, start)
            total = sum(len(m.content or "") for m in msgs[start:])

        # 3) 兜底：剪裁后若片段以 assistant(tool_calls) / tool 开头（其前置
        #    user 消息已被丢弃），继续整组丢弃，保证送回模型的上下文以
        #    user/system 开头，避免被 API 拒绝。
        while start < len(msgs) and msgs[start].role in ("assistant", "tool"):
            start = self._drop_group_start(msgs, start)
        return msgs[start:]

    @staticmethod
    def _drop_group_start(msgs: list[ChatMessage], start: int) -> int:
        """预算剪裁的单调推进：返回"丢弃 start 处单元"后的新起始下标。

        单元定义：一条普通消息；或 assistant(tool_calls) + 其后连续的 tool 消息。
        start 若恰好落在 tool 组中间（历史以 tool 开头等异常数据），则整组丢弃。
        返回值恒 > start（start >= len(msgs) 时返回 len(msgs)），保证外层循环终止。
        """
        n = len(msgs)
        if start >= n:
            return n
        m = msgs[start]
        if m.role == "assistant" and m.tool_calls:
            j = start + 1
            while j < n and msgs[j].role == "tool":
                j += 1
            return j
        if m.role == "tool":
            j = start
            while j < n and msgs[j].role == "tool":
                j += 1
            return j
        return start + 1

    async def _run_harness_loop(
        self,
        send: Callable[..., Awaitable[bool]],
    ) -> None:
        loop = AgentLoop(
            self.engine.client,
            self.engine.tools,
            max_steps=self.engine.max_steps,
            toolbox=self.toolbox,
        )
        pending: Optional[dict[str, Any]] = None
        final_sent = False
        # trace: 每个工具调用的开始时间，用于计算单步耗时
        call_started: dict[str, float] = {}
        reasoning_chars = 0
        text_chars = 0

        async def trace(kind: str, **fields: Any) -> None:
            """向前端推送一条 trace 事件（时间轴 + 可折叠日志的数据源）。"""
            await send(
                type="trace",
                event=kind,
                t=round(time.time() - self._turn_start_time, 3)
                if self._turn_start_time else 0.0,
                **fields,
            )

        await trace("turn_start", model=self.engine.model_display,
                    mode=self.mode.mode.value,
                    max_steps=self.engine.max_steps,
                    activated=list(self.toolbox.activated) if self.toolbox else [],
                    history=len(self.messages))

        async for ev in loop.run_stream(
            self._build_run_context(),
            system_prompt=self.engine.system_prompt,
        ):
            if self._stop_requested:
                await trace("stopped")
                break
            kind = ev.kind

            if kind == "round_start":
                if pending is not None:
                    self._commit_round(pending)
                pending = {"content": "", "tool_calls": [], "results": [], "reasoning_content": ""}
                reasoning_chars = 0
                text_chars = 0
                await trace("round_start", round=ev.round,
                            activated=list(self.toolbox.activated) if self.toolbox else [])

            elif kind == "reasoning":
                if ev.content:
                    if pending is None:
                        pending = {"content": "", "tool_calls": [], "results": [], "reasoning_content": ""}
                    reasoning_chars += len(ev.content)
                    pending["reasoning_content"] = pending.get("reasoning_content", "") + ev.content
                    await send(type="reasoning_delta", content=ev.content)

            elif kind == "delta":
                if pending is None:
                    pending = {"content": "", "tool_calls": [], "results": [], "reasoning_content": ""}
                pending["content"] += ev.content
                text_chars += len(ev.content)
                await send(type="text_delta", content=ev.content)

            elif kind == "tool_call":
                if pending is None:
                    pending = {"content": "", "tool_calls": [], "results": [], "reasoning_content": ""}
                tc = ev.tool_call or {}
                pending["tool_calls"].append(tc)
                call_id = tc.get("id", "")
                call_started[call_id] = time.time()
                args_json = json.dumps(tc.get("arguments") or {}, ensure_ascii=False)
                calls = [{
                    "id": call_id,
                    "name": tc.get("name", ""),
                    "args": args_json,
                }]
                await send(type="tool_calls", calls=calls)
                await send(
                    type="thinking_status",
                    status=_tool_label(tc.get("name", ""), tc.get("arguments") or {}),
                )
                await trace("tool_call", round=ev.round, id=call_id,
                            name=tc.get("name", ""), args=args_json[:4000])

            elif kind == "tool_result":
                if pending is None:
                    pending = {"content": "", "tool_calls": [], "results": [], "reasoning_content": ""}
                tr = ev.tool_result or {}
                pending["results"].append(tr)
                content = tr.get("output") or tr.get("error") or ""
                call_id = tr.get("call_id", "")
                await send(
                    type="tool_result",
                    id=call_id,
                    name=tr.get("name", ""),
                    success=bool(tr.get("success", False)),
                    content=str(content)[:2000],
                )
                started = call_started.pop(call_id, None)
                await trace("tool_result", round=ev.round, id=call_id,
                            name=tr.get("name", ""),
                            success=bool(tr.get("success", False)),
                            status=tr.get("status", ""),
                            error=tr.get("error") or "",
                            hint=tr.get("hint") or "",
                            elapsed=round(time.time() - started, 3) if started else None,
                            content=str(content)[:4000])

            elif kind == "reply":
                reasoning = pending.get("reasoning_content") if pending else None
                if pending is not None and pending["tool_calls"]:
                    self._commit_round(pending)
                pending = None
                await trace("model_output", round=ev.round,
                            reasoning_chars=reasoning_chars, text_chars=text_chars)
                if ev.reply and not final_sent:
                    self.messages.append(ChatMessage.assistant(ev.reply, reasoning_content=reasoning))
                    await send(type="text", content=ev.reply)
                    final_sent = True

            elif kind == "done":
                reasoning = pending.get("reasoning_content") if pending else None
                if pending is not None and pending["tool_calls"]:
                    self._commit_round(pending)
                pending = None
                if ev.reply and not final_sent:
                    self.messages.append(ChatMessage.assistant(ev.reply, reasoning_content=reasoning))
                    await send(type="text", content=ev.reply)
                    final_sent = True
                await trace("done", round=ev.round, hit_max=bool(ev.hit_max))

        # 极端情况：stop 或异常导致没有任何最终文本，也补一条可见反馈。
        if not final_sent and self.messages and self.messages[-1].role == "user":
            note = "已停止生成。" if self._stop_requested else "（未收到模型最终回复）"
            self.messages.append(ChatMessage.assistant(note))
            await send(type="text", content=note)

    def _commit_round(self, pending: dict[str, Any]) -> None:
        content = pending.get("content", "") or None
        tool_calls = pending.get("tool_calls", [])
        results = pending.get("results", [])
        reasoning = pending.get("reasoning_content") or None

        if tool_calls:
            tc_schema = []
            for tc in tool_calls:
                tc_schema.append({
                    "id": tc.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": tc.get("name", ""),
                        "arguments": json.dumps(tc.get("arguments") or {}, ensure_ascii=False),
                    },
                })
            self.messages.append(ChatMessage.assistant(
                content, tool_calls=tc_schema, reasoning_content=reasoning))
            for tr in results:
                payload = {
                    "success": bool(tr.get("success", False)),
                    "status": tr.get("status", "ok" if tr.get("success", False) else "error"),
                    "output": tr.get("output"),
                    "error": tr.get("error"),
                    "hint": tr.get("hint"),
                }
                self.messages.append(
                    ChatMessage.tool_result(
                        tr.get("call_id", "unknown"),
                        json.dumps(payload, ensure_ascii=False, default=str),
                    )
                )
        elif content:
            self.messages.append(ChatMessage.assistant(
                content, reasoning_content=reasoning))
