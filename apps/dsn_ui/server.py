# apps/dsn_ui/server.py
"""DSN-exp UI 后端服务：全量对齐 temp/ui_template 前端 API 协议，接驳底层 ModelOrchestrator。

支持功能与协议点：
  1. GET /props 与 GET /props?model=...（ROUTER/MODEL 模式属性与参数返回）
  2. GET /models 与 GET /v1/models（OpenAI 兼容及 Router 模式模型列表与加载状态）
  3. POST /models/load 与 POST /models/unload（由 ModelScheduler 驱动的动态显存插槽调度）
  4. GET /models/sse（实时 Server-Sent Events 事件广播，状态变更即时推送解决卡转圈）
  5. GET /slots（并发槽位检查）
  6. POST /v1/chat/completions（支持流式 SSE、思考链思维解析、实时控制）
  7. /api/system/resources（CPU/RAM/GPU 显存实时监控）
  8. /api/settings（读取与更新 DSN Harness 全局各命名空间设置）
  9. /api/orchestrator/*（底层 Orchestrator 状态、插槽配额与模型管理）
  10. 托管 temp/ui_template 前端编译产物 (SvelteKit + Tailwind SPA)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shutil
import subprocess
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import psutil
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from apps.dsn_ui.config import UIConfig
from apps.dsn_ui.engine import DSNUIEngine
from apps.dsn_ui.stream_sessions import registry as stream_registry
from apps.dsn_ui.logging_setup import (
    get_request_id,
    log_exception,
    reset_request_id,
    set_request_id,
    setup_logging,
)
from harness.orchestrator import ChatMessage, LlamaServerConfig

logger = logging.getLogger("DSNUIServer")


class SSEBroadcaster:
    """管理 /models/sse 订阅连接并广播事件。"""

    def __init__(self):
        self._queues: Set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        async with self._lock:
            self._queues.add(q)
        return q

    async def unsubscribe(self, q: asyncio.Queue) -> None:
        async with self._lock:
            self._queues.discard(q)

    async def broadcast(self, event_type: str, model: str, data: dict) -> None:
        payload = {
            "model": model,
            "event": event_type,
            "data": data,
        }
        msg = f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        async with self._lock:
            for q in list(self._queues):
                try:
                    q.put_nowait(msg)
                except asyncio.QueueFull:
                    pass


sse_broadcaster = SSEBroadcaster()


def get_system_resources() -> dict:
    """获取 CPU、内存及 NVIDIA GPU 显存使用情况。"""
    vm = psutil.virtual_memory()
    ram_info = {
        "total_gb": round(vm.total / (1024 ** 3), 2),
        "used_gb": round(vm.used / (1024 ** 3), 2),
        "free_gb": round(vm.available / (1024 ** 3), 2),
        "percent": vm.percent,
    }

    cpu_info = {
        "percent": psutil.cpu_percent(interval=0.1),
        "cores": psutil.cpu_count(logical=True),
    }

    gpus = []
    if shutil.which("nvidia-smi"):
        try:
            cmd = [
                "nvidia-smi",
                "--query-gpu=index,name,memory.total,memory.used,memory.free,temperature.gpu,utilization.gpu",
                "--format=csv,noheader,nounits",
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=2.0)
            if res.returncode == 0:
                for line in res.stdout.strip().split("\n"):
                    if not line.strip():
                        continue
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 7:
                        total_mb = float(parts[2])
                        used_mb = float(parts[3])
                        free_mb = float(parts[4])
                        gpus.append({
                            "index": int(parts[0]),
                            "name": parts[1],
                            "total_mb": total_mb,
                            "used_mb": used_mb,
                            "free_mb": free_mb,
                            "percent": round((used_mb / total_mb) * 100, 1) if total_mb > 0 else 0,
                            "temperature": float(parts[5]),
                            "utilization": float(parts[6]),
                        })
        except Exception as e:
            logger.debug("Query nvidia-smi failed: %s", e)

    return {
        "ram": ram_info,
        "cpu": cpu_info,
        "gpus": gpus,
    }


def create_app(engine: Optional[DSNUIEngine] = None) -> FastAPI:
    def _on_topic_converged(topic_id: str, title: str):
        loop = None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            pass
        if loop and loop.is_running():
            asyncio.create_task(sse_broadcaster.broadcast("topic_converged", "", {"topic_id": topic_id, "title": title}))

    if engine is None:
        engine = DSNUIEngine(max_concurrent_slots=UIConfig.DEFAULT_SLOTS, on_topic_converged=_on_topic_converged)
    else:
        engine.agent.topic_mgr.on_topic_converged = _on_topic_converged

    # 注册 Orchestrator 状态变化回调，打通 SSE 广播
    def _on_orchestrator_status_change(model_name: str, status: str, extra: dict):
        loop = None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            pass

        data_payload = {"status": status}
        if "error" in extra:
            data_payload["exit_code"] = 1
            data_payload["error"] = extra["error"]
        if "progress" in extra:
            data_payload["progress"] = extra["progress"]

        if loop and loop.is_running():
            asyncio.create_task(sse_broadcaster.broadcast(f"status_{status}", model_name, data_payload))
            asyncio.create_task(sse_broadcaster.broadcast("status_change", model_name, data_payload))

    engine.orchestrator.add_status_listener(_on_orchestrator_status_change)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 周期性回收已结束的流会话（供重连回放的 TTL 缓冲）。
        async def _prune_loop():
            while True:
                try:
                    await asyncio.sleep(60)
                    await stream_registry.prune()
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # noqa: BLE001 - 清理失败不应拖垮服务
                    log_exception(logger, "流会话清理任务异常", e)

        prune_task = asyncio.create_task(_prune_loop())
        logger.info("流会话清理任务已启动")
        try:
            yield
        finally:
            prune_task.cancel()
            try:
                await prune_task
            except asyncio.CancelledError:
                pass
            logger.info("DSN-UI 正在关闭，释放所有模型与子进程...")
            engine.orchestrator.shutdown()

    app = FastAPI(title="DSN-exp UI & Model Orchestrator", version="1.0.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── 1. llama-ui /props 协议端点 ──

    @app.get("/props")
    async def get_server_props(model: Optional[str] = None, autoload: Optional[str] = None):
        """返回服务器配置与当前状态，使前端识别为 ROUTER 模式。"""
        status = engine.orchestrator.status()
        target_model = model or engine.orchestrator.get_default_model()
        n_ctx = engine.orchestrator.get_model_ctx_size(target_model)

        return {
            "role": "router",
            "default_generation_settings": {
                "id": 0,
                "id_task": 0,
                "n_ctx": n_ctx,
                "speculative": False,
                "is_processing": False,
                "params": {
                    # 每次回复的最大输出 tokens 规定为当前加载模型支持的上下文长度
                    "n_predict": n_ctx,
                    "seed": -1,
                    "temperature": 0.7,
                    "dynatemp_range": 0.0,
                    "dynatemp_exponent": 1.0,
                    "top_k": 40,
                    "top_p": 0.95,
                    "min_p": 0.05,
                    "top_n_sigma": -1.0,
                    "xtc_probability": 0.0,
                    "xtc_threshold": 0.1,
                    "typical_p": 1.0,
                    "repeat_last_n": 64,
                    "repeat_penalty": 1.0,
                    "presence_penalty": 0.0,
                    "frequency_penalty": 0.0,
                }
            },
            "total_slots": status.get("max_concurrent_slots", 2),
            "modalities": {
                "vision": True,
                "audio": True,
                "video": False
            },
            "ui_settings": {
                "theme": "dark",
                "showBuildVersion": True,
            }
        }

    # ── 2. llama-ui /models 及 /v1/models 端点 ──

    def _build_model_entries() -> list[dict]:
        status = engine.orchestrator.status()
        entries = []
        now = int(time.time())
        for m in status.get("models", []):
            is_loaded = m["loaded"]
            is_loading = m.get("is_loading", False)
            status_val = "loading" if is_loading else ("loaded" if is_loaded else "unloaded")
            entries.append({
                "id": m["name"],
                "name": m["name"],
                "object": "model",
                "owned_by": "llamacpp" if m["is_local"] else m["source_type"],
                "created": now,
                "in_cache": True,
                "path": m.get("command") or f"models/{m['name']}.gguf",
                "status": {
                    "value": status_val,
                    "args": [m["command"]] if m.get("command") else [],
                },
                "architecture": {
                    "input_modalities": ["text", "vision"] if "ocr" in m["name"] or "v" in m["name"] else ["text"]
                },
                "meta": {
                    "n_ctx": engine.orchestrator.get_model_ctx_size(m["name"]),
                    "priority": m["priority"],
                    "resident": m["resident"],
                    "immediate": m["immediate"],
                    "command": m.get("command"),
                }
            })
        return entries

    @app.get("/models")
    @app.get("/v1/models")
    async def list_models():
        data = _build_model_entries()
        return {"object": "list", "data": data}

    # ── 3. 模型动态加载 /models/load 与 /models/unload ──

    @app.post("/models/load")
    async def load_model(req: Request):
        body = await req.json()
        model_id = body.get("model")
        if not model_id:
            raise HTTPException(status_code=400, detail="Missing 'model' field")
        logger.info("UI 请求加载模型: %s", model_id)
        try:
            ok = await asyncio.to_thread(engine.orchestrator.load_model, model_id)
            if ok:
                await sse_broadcaster.broadcast("status_loaded", model_id, {"status": "loaded"})
                await sse_broadcaster.broadcast("status_change", model_id, {"status": "loaded"})
                return {"success": True, "model": model_id, "status": "loaded"}
            else:
                await sse_broadcaster.broadcast("status_failed", model_id, {"status": "failed", "exit_code": 1})
                return JSONResponse(status_code=500, content={"error": "Launch failed", "model": model_id})
        except Exception as e:
            logger.error("加载模型 %s 异常: %s", model_id, e)
            await sse_broadcaster.broadcast("status_failed", model_id, {"status": "failed", "exit_code": 1, "error": str(e)})
            return JSONResponse(status_code=500, content={"error": str(e), "model": model_id})

    @app.post("/models/unload")
    async def unload_model(req: Request):
        body = await req.json()
        model_id = body.get("model")
        if not model_id:
            raise HTTPException(status_code=400, detail="Missing 'model' field")
        logger.info("UI 请求卸载/终止模型: %s", model_id)
        try:
            ok = await asyncio.to_thread(engine.orchestrator.unload_model, model_id)
            await sse_broadcaster.broadcast("status_unloaded", model_id, {"status": "unloaded"})
            await sse_broadcaster.broadcast("status_change", model_id, {"status": "unloaded"})
            return {"success": ok, "model": model_id, "status": "unloaded"}
        except Exception as e:
            logger.error("卸载/终止模型 %s 异常: %s", model_id, e)
            return JSONResponse(status_code=500, content={"error": str(e), "model": model_id})

    # ── 4. /models/sse 实时状态事件流 ──

    @app.get("/models/sse")
    async def models_sse():
        """提供 /models/sse 实时事件推送，供前端 modelsStore 监听加载状态。"""
        queue = await sse_broadcaster.subscribe()

        async def event_generator():
            try:
                # 初始连接同步当前全量状态
                yield "retry: 2000\n\n"
                yield "event: models_reload\ndata: {}\n\n"
                status = engine.orchestrator.status()
                for m in status.get("models", []):
                    val = "loaded" if m["loaded"] else "unloaded"
                    payload = {"model": m["name"], "event": f"status_{val}", "data": {"status": val}}
                    yield f"event: status_{val}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

                # 同步当前情绪状态与摘要
                emo_payload = {
                    "state": engine.agent.get_emotion_state(),
                    "summary": engine.agent.get_emotion_summary(),
                }
                yield f"event: emotion_change\ndata: {json.dumps(emo_payload, ensure_ascii=False)}\n\n"

                # 周期性心跳：SSE 长连接若长时间无数据，会被中间代理/浏览器
                # 判定为停滞而中断（表现为 ERR_INCOMPLETE_CHUNKED_ENCODING）。
                # 每 15s 发一个注释帧保活。
                while True:
                    try:
                        msg = await asyncio.wait_for(queue.get(), timeout=15.0)
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"
                        continue
                    yield msg
            except asyncio.CancelledError:
                # 客户端主动断开属于正常流程
                raise
            except Exception as e:  # noqa: BLE001
                logger.warning("/models/sse 流异常终止: %s", e)
            finally:
                await sse_broadcaster.unsubscribe(queue)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # ── 5. /slots 槽位端点 ──

    @app.get("/slots")
    async def get_slots(model: Optional[str] = None):
        """返回服务器槽位并发与处理状态。"""
        status = engine.orchestrator.status()
        max_slots = status.get("max_concurrent_slots", 2)
        used_slots = status.get("used_slots", 0)
        slots = []
        for i in range(max_slots):
            slots.append({
                "id": i,
                "id_task": i,
                "n_ctx": 128000,
                "is_processing": i < used_slots,
            })
        return slots

    # ── 6. /v1/chat/completions 推理端点 ──

    @app.post("/v1/chat/completions")
    @app.post("/chat/completions")
    async def chat_completions(req: Request):
        body = await req.json()
        model_name = body.get("model") or engine.orchestrator.get_default_model()
        if not model_name:
            raise HTTPException(status_code=400, detail="未选择任何模型，无法发送对话。请先在顶部或资源管理页选择模型。")

        messages_raw = body.get("messages", [])
        stream = bool(body.get("stream", False))
        temperature = body.get("temperature")

        chat_messages = []
        for m in messages_raw:
            role = m.get("role", "user")
            content = m.get("content", "")
            # 多模态：content 为数组时必须**保留结构**（含 image_url 内容块），
            # 不能拍平成字符串 —— 否则图像在到达模型前就被丢弃，
            # 表现为"传了图但模型看不到"。
            if isinstance(content, list):
                from apps.dsn_ui.integration_api import openai_content_to_parts
                content = openai_content_to_parts(content)

            if role == "system":
                chat_messages.append(ChatMessage.system(
                    content if isinstance(content, str) else str(content)))
            elif role == "user":
                # ChatMessage.user 接受 str；多模态时直接构造以保留 parts
                chat_messages.append(ChatMessage(role="user", content=content))
            elif role == "assistant":
                chat_messages.append(ChatMessage.assistant(
                    content if isinstance(content, str) else str(content)))

        execution_mode = bool(
            body.get("execution_mode", False) or
            req.query_params.get("execution_mode") in ("true", "1") or
            req.headers.get("X-Execution-Mode") in ("true", "1")
        )

        # 自定义系统提示词超驰：用户在设置页选择自定义时，用其文本替代
        # harness 动态组装的提示词生态（话题记忆/情绪/工具箱指令不再注入）。
        system_prompt_override = bool(
            body.get("system_prompt_override", False) or
            req.headers.get("X-System-Prompt-Override") in ("true", "1")
        )
        custom_system_prompt = ""
        if system_prompt_override:
            for m in messages_raw:
                if m.get("role") == "system":
                    c = m.get("content", "")
                    if isinstance(c, list):
                        custom_system_prompt = " ".join(
                            p.get("text", "") for p in c
                            if isinstance(p, dict) and p.get("type") == "text"
                        )
                    else:
                        custom_system_prompt = str(c)
                    break

        # 每次回复的最大输出 tokens 规定为当前加载模型支持的上下文长度
        model_ctx = engine.orchestrator.get_model_ctx_size(model_name)
        req_tokens = body.get("max_tokens") or body.get("n_predict")
        if req_tokens is None or int(req_tokens) <= 0 or int(req_tokens) == 4096:
            # 不直接取满上下文：输入本身要占 token，若 max_tokens == ctx_size
            # 则 input+output > ctx，llama-server 直接 500。
            # 交给 agent 统一按比例预留（见 _resolve_max_tokens），这里传 None。
            effective_max_tokens = None
        else:
            effective_max_tokens = int(req_tokens)

        # 支持请求中透传的 Agent 最大迭代步数与工具截断字符数
        raw_max_steps = body.get("max_steps") or body.get("agent_max_steps") or body.get("agentic_max_turns")
        effective_max_steps = int(raw_max_steps) if raw_max_steps is not None and int(raw_max_steps) >= 0 else None

        raw_tool_chars = body.get("tool_max_output_chars") or body.get("dsn_tool_max_output_chars")
        if raw_tool_chars is not None and int(raw_tool_chars) > 0:
            engine.agent.set_tool_max_output_chars(int(raw_tool_chars))

        # SSE 保活心跳间隔：前端按 llama-server 协议传 sse_ping_interval（秒）。
        # 这个参数以前被后端忽略，导致长时间无输出的工具执行（如 90s 的 nmap）
        # 期间连接静默、被浏览器/代理判死，前端显示「SSE 中断」而后端仍在跑。
        try:
            ping_interval = float(body.get("sse_ping_interval") or 0) or 0.0
        except (TypeError, ValueError):
            ping_interval = 0.0
        # 限制在合理范围：太小会刷屏，太大起不到保活作用
        heartbeat_interval = (
            max(0.2, min(30.0, ping_interval)) if ping_interval > 0 else None
        )

        if not stream:
            resp = engine.agent.chat_invoke(
                messages_raw=messages_raw,
                model_name=model_name,
                temperature=temperature,
                execution_mode=execution_mode,
                system_prompt_override=custom_system_prompt if system_prompt_override else None,
                max_tokens=effective_max_tokens,
                max_steps=effective_max_steps,
            )
            emo_payload = {
                "state": engine.agent.get_emotion_state(),
                "summary": engine.agent.get_emotion_summary(),
            }
            await sse_broadcaster.broadcast("emotion_change", model_name, emo_payload)
            if engine.agent.topic_mgr.last_converged_topic:
                conv_t = engine.agent.topic_mgr.last_converged_topic
                engine.agent.topic_mgr.last_converged_topic = None
                await sse_broadcaster.broadcast("topic_converged", model_name, {"title": conv_t})

            return {
                "id": f"chatcmpl-dsn-{int(time.time())}",
                "object": "chat.completion",
                "model": model_name,
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": resp.content,
                        "reasoning_content": resp.reasoning_content,
                    },
                    "finish_reason": resp.finish_reason or "stop",
                }],
                "usage": resp.usage or {"prompt_tokens": 0, "completion_tokens": 0},
            }

        async def _produce_sse(session, conv_id: str):
            """后台生产者：消费 AgentLoop 事件并写入流会话缓冲。

            与 HTTP 连接完全解耦——客户端断开只会停止"读取"，
            本协程继续把推理结果写入 session.buffer，供后续重连回放。
            """

            def emit(raw: str) -> None:
                """把一段 SSE 文本追加进会话缓冲（同步，无 await 依赖）。"""
                session.append(raw.encode("utf-8"))

            # 请求关联 id：本次 SSE 流的每条日志都会带上它，
            # 便于在并发请求中还原「哪一次流在哪一步失败了」。
            rid = f"{int(time.time() * 1000):x}-{id(session) & 0xFFFF:04x}"
            _rid_token = set_request_id(rid)
            chunk_count = 0
            ctype_counts: Dict[str, int] = {}
            started = time.time()
            try:
                logger.info(
                    "SSE 开始: model=%s execution_mode=%s stream=%s max_steps=%s "
                    "max_tokens=%s override=%s messages=%d",
                    model_name, execution_mode, stream, effective_max_steps,
                    effective_max_tokens, system_prompt_override, len(messages_raw),
                )
                provider_sent_timings = False
                agen = engine.agent.chat_stream(
                    messages_raw=messages_raw,
                    model_name=model_name,
                    temperature=temperature,
                    execution_mode=execution_mode,
                    system_prompt_override=custom_system_prompt if system_prompt_override else None,
                    max_tokens=effective_max_tokens,
                    max_steps=effective_max_steps,
                )
                async for chunk in agen:
                    chunk_count += 1
                    ctype = chunk.get("type")
                    ctype_counts[ctype] = ctype_counts.get(ctype, 0) + 1
                    # 逐事件调试日志：能用 DSN_UI_LOG_LEVEL=DEBUG 打开，
                    # 精确定位是「哪一类事件之后」开始出问题。
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "SSE chunk #%d type=%s keys=%s",
                            chunk_count, ctype, sorted(chunk.keys()),
                        )
                    if ctype in ("timings", "usage"):
                        provider_sent_timings = True
                    if ctype == "context_stats":
                        # DSN-exp 弹性上下文统计：预算/折叠/截断，供用量指示环展示
                        payload = {"context_stats": chunk.get("stats", {})}
                        emit(f"data: {json.dumps(payload, ensure_ascii=False)}\n\n")
                        continue
                    if ctype == "timings":
                        # llama-server 回传了真实 token 用量：按前端 ChatMessageTimings
                        # 结构透传（prompt_n/prompt_ms/predicted_n/predicted_ms/cache_n）。
                        t = chunk.get("timings") or {}
                        payload = {
                            "timings": {
                                "prompt_n": t.get("prompt_n", 0),
                                "prompt_ms": t.get("prompt_ms", 0),
                                "predicted_n": t.get("predicted_n", 0),
                                "predicted_ms": t.get("predicted_ms", 0),
                                "cache_n": t.get("cache_n", 0),
                            }
                        }
                        emit(f"data: {json.dumps(payload, ensure_ascii=False)}\n\n")
                        continue
                    if ctype == "usage":
                        payload = {"usage": chunk.get("usage", {})}
                        emit(f"data: {json.dumps(payload, ensure_ascii=False)}\n\n")
                        continue
                    if ctype == "round_start":
                        # 轮次边界：前端为每一轮新建 assistant 消息，
                        # 避免多轮思考/动作被合并进同一个气泡。
                        payload = {"round_start": chunk.get("round", 1)}
                        emit(f"data: {json.dumps(payload, ensure_ascii=False)}\n\n")
                        continue
                    if ctype == "tool_result":
                        # 工具执行结果：前端据此持久化 role=tool 消息。
                        # 之前没有这个分支，工具结果被静默丢弃，导致
                        # 1) 工具调用永远显示为"未完成"
                        # 2) 多轮思考/动作无法按 思考-动作-思考-动作 展开
                        tr = chunk.get("tool_result", {}) or {}
                        payload = {
                            "tool_result": {
                                "call_id": tr.get("call_id"),
                                "name": tr.get("name"),
                                "success": tr.get("success"),
                                "status": tr.get("status"),
                                "output": tr.get("output"),
                                "error": tr.get("error"),
                            }
                        }
                        emit(f"data: {json.dumps(payload, ensure_ascii=False)}\n\n")
                        continue
                    if ctype == "done":
                        # AgentLoop 收束信号：normal=模型自然结束；
                        # max_steps=步数耗尽后由收束轮强制给出最终答复。
                        # 前端据此提示「因达到步数上限而收束」，避免误认为正常完成。
                        payload = {
                            "finish_reason": "length" if chunk.get("hit_max") else "stop",
                            "hit_max_steps": bool(chunk.get("hit_max")),
                            "round": chunk.get("round"),
                        }
                        emit(f"data: {json.dumps(payload, ensure_ascii=False)}\n\n")
                        continue
                    if ctype == "delta":
                        payload = {
                            "choices": [{"delta": {"content": chunk["content"]}, "index": 0}]
                        }
                    elif ctype == "reasoning":
                        payload = {
                            "choices": [{"delta": {"reasoning_content": chunk["content"]}, "index": 0}]
                        }
                    elif ctype == "tool_calls":
                        payload = {
                            "choices": [{"delta": {"tool_calls": chunk["tool_calls"]}, "index": 0}]
                        }
                    elif ctype == "tool_call":
                        tc = chunk.get("tool_call", {})
                        payload = {
                            "choices": [{
                                "delta": {
                                    "tool_calls": [{
                                        "index": 0,
                                        "id": tc.get("id", "call_0"),
                                        "type": "function",
                                        "function": {
                                            "name": tc.get("name"),
                                            "arguments": json.dumps(tc.get("arguments", {}), ensure_ascii=False),
                                        },
                                    }]
                                },
                                "index": 0
                            }]
                        }
                    else:
                        continue
                    emit(f"data: {json.dumps(payload, ensure_ascii=False)}\n\n")

                logger.info(
                    "SSE 模型流结束: chunks=%d types=%s elapsed=%.2fs",
                    chunk_count, ctype_counts, time.time() - started,
                )

                # 若 provider 未回传 timings（如 llama-server 关闭了 timings 输出），
                # 退化用弹性上下文的字符统计估算 prompt token，保证用量指示环仍可用。
                if not provider_sent_timings:
                    logger.debug("provider 未回传 timings，改用弹性上下文字符数估算")
                    stats = engine.agent.get_context_stats() or {}
                    injected = int(stats.get("total_injected_chars") or 0)
                    if injected > 0:
                        est_tokens = max(1, int(injected / 3.2))
                        fallback = {
                            "timings": {
                                "prompt_n": est_tokens,
                                "prompt_ms": 0,
                                "predicted_n": 0,
                                "predicted_ms": 0,
                                "cache_n": 0,
                            },
                            "estimated": True,
                        }
                        emit(f"data: {json.dumps(fallback, ensure_ascii=False)}\n\n")

                # 交互完成后推送最新情绪与收敛状态
                emo_payload = {
                    "state": engine.agent.get_emotion_state(),
                    "summary": engine.agent.get_emotion_summary(),
                }
                await sse_broadcaster.broadcast("emotion_change", model_name, emo_payload)
                if engine.agent.topic_mgr.last_converged_topic:
                    conv_t = engine.agent.topic_mgr.last_converged_topic
                    engine.agent.topic_mgr.last_converged_topic = None
                    await sse_broadcaster.broadcast("topic_converged", model_name, {"title": conv_t})

                emit("data: [DONE]\n\n")
                logger.info(
                    "SSE 正常完成: chunks=%d elapsed=%.2fs",
                    chunk_count, time.time() - started,
                )
            except asyncio.CancelledError:
                # 客户端主动断开不应被当成推理失败，但要留下痕迹便于排查"假死"。
                logger.warning(
                    "SSE 被取消(客户端断开?): chunks=%d elapsed=%.2fs types=%s",
                    chunk_count, time.time() - started, ctype_counts,
                )
                raise
            except Exception as e:
                # 关键修复：原实现只打 str(e)，栈信息全部丢失。
                # 现在记录完整 traceback，并附带失败现场的上下文快照，
                # 这样即使异常来自 harness 内部也能一眼定位到具体层。
                log_exception(logger, "SSE 推理异常", e)
                logger.error(
                    "SSE 失败现场: chunks=%d types=%s elapsed=%.2fs execution_mode=%s "
                    "max_steps=%s override=%s model=%s",
                    chunk_count, ctype_counts, time.time() - started,
                    execution_mode, effective_max_steps,
                    system_prompt_override, model_name,
                )
                try:
                    import traceback as _tb
                    frame_summary = _tb.extract_tb(e.__traceback__)[-1] if e.__traceback__ else None
                    if frame_summary is not None:
                        logger.error(
                            "SSE 异常最深层位置: %s:%s in %s",
                            frame_summary.filename, frame_summary.lineno, frame_summary.name,
                        )
                except Exception:  # noqa: BLE001 - 诊断代码绝不能再抛
                    pass
                err_payload = {"error": {"message": str(e), "type": "server_error"}}
                emit(f"data: {json.dumps(err_payload, ensure_ascii=False)}\n\n")
                emit("data: [DONE]\n\n")
                session.finish(error=str(e))
            except asyncio.CancelledError:
                # 用户点停止 / 新流顶替：结束会话并向下游广播终止。
                emit("data: [DONE]\n\n")
                session.finish(error="cancelled")
                raise
            finally:
                # 无论正常还是异常都必须 finish，否则重连方会一直等待。
                session.finish()
                logger.debug(
                    "SSE 生产者退出: conv=%s chunks=%d bytes=%d",
                    conv_id, chunk_count, session.total_bytes,
                )
                reset_request_id(_rid_token)

        # 本次请求的流身份：客户端在 X-Conversation-Id 头里给出（含 ::model 后缀）。
        # 没带该头时生成一个临时 id —— 仍走同一套会话缓冲（保证生产者/转发解耦、
        # 客户端断开不打断推理），只是没有稳定 id 因而不可被后续请求重连。
        conv_id = (
            req.headers.get("X-Conversation-Id")
            or req.headers.get("x-conversation-id")
            or ""
        ).strip()
        if not conv_id:
            conv_id = f"anon-{int(time.time() * 1000):x}-{uuid.uuid4().hex[:8]}"

        # 后台生产者 + 直通转发：先建会话并启动生产任务，
        # 再由本响应从缓冲区实时读发给当前连接。
        session = await stream_registry.create(conv_id, model=model_name)
        session.task = asyncio.create_task(_produce_sse(session, conv_id))

        # 心跳参数：前端传了 sse_ping_interval 就用它，否则用会话默认值。
        hb_kwargs: Dict[str, Any] = {}
        if heartbeat_interval is not None:
            hb_kwargs["heartbeat_interval"] = heartbeat_interval
        logger.info(
            "SSE 保活: conv=%s heartbeat=%s",
            conv_id, hb_kwargs.get("heartbeat_interval", "default"),
        )

        async def _sse_generator():
            """从会话缓冲实时转发给当前 HTTP 连接。

            客户端断开（GeneratorExit）只会终止本转发协程，
            后台的 _produce_sse 不受影响，继续写缓冲。
            """
            try:
                async for data in stream_registry.replay(
                    conv_id, 0, **hb_kwargs
                ):
                    yield data
            except KeyError:
                # 会话已被回收（极少见）：回一个明确的错误而不是挂起
                yield f"data: {json.dumps({'error': {'message': '流会话不存在或已回收', 'type': 'server_error'}}, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"

        return StreamingResponse(
            _sse_generator(),
            media_type="text/event-stream; charset=utf-8",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "Content-Type": "text/event-stream; charset=utf-8",
            },
        )

    # ── 6.5 DSN Agent 记忆、情绪与技能状态 API ──

    @app.get("/api/emotion")
    async def get_emotion():
        """获取当前 5D 情绪状态与文本摘要。"""
        return {
            "state": engine.agent.get_emotion_state(),
            "summary": engine.agent.get_emotion_summary(),
        }

    @app.post("/api/emotion/adjust")
    async def adjust_emotion(req: Request):
        """手动或事件调节情绪向量。"""
        body = await req.json()
        engine.agent.emotion_engine.apply_stimulus(
            delta_joy=float(body.get("delta_joy", 0.0)),
            delta_sorrow=float(body.get("delta_sorrow", 0.0)),
            delta_anger=float(body.get("delta_anger", 0.0)),
            delta_fear=float(body.get("delta_fear", 0.0)),
            delta_meta=float(body.get("delta_meta", 0.0)),
        )
        emo_payload = {
            "state": engine.agent.get_emotion_state(),
            "summary": engine.agent.get_emotion_summary(),
        }
        await sse_broadcaster.broadcast("emotion_change", "", emo_payload)
        return emo_payload

    @app.get("/api/agent/prompt")
    async def get_agent_prompt(execution_mode: bool = False):
        """根据是否开启执行模式，动态生成并返回完整的注入提示词。"""
        prompt = engine.agent.assemble_system_prompt(execution_mode=execution_mode)
        return {
            "execution_mode": execution_mode,
            "prompt": prompt,
        }

    @app.get("/api/topic/converged")
    async def get_topic_converged():
        """获取最新收敛闭锁的话题标题（如果有）。"""
        return {"converged_topic": engine.agent.topic_mgr.last_converged_topic}

    @app.get("/api/context/stats")
    async def get_context_stats():
        """DSN-exp 弹性上下文装配统计：预算、折叠（丢弃）、截断与占比。"""
        return engine.agent.get_context_stats()

    # ── 6.6 llama-ui 兼容的 /tools 端点 ──
    # 前端 toolsStore 会请求 GET /tools 与 POST /tools。
    # dsn_ui 不使用 llama-server 的 server-tools，工具由 harness toolbox 提供，
    # 因此这里返回 harness 工具清单；未注册就会被 SPA catch-all 吞掉并返回
    # HTML（表现为 "Unexpected token '<'" / 405），故必须显式注册。

    @app.get("/tools")
    async def list_tools_compat():
        """返回 harness 工具清单（llama-ui 的 ServerToolInfo 兼容格式）。

        前端 toolsStore.fetchServerTools() 会读取每项的：
          - tool: 工具名
          - uses_cwd: 是否依赖工作目录
          - definition.function.name: 工具名（OpenAI function 形态）
        必须返回嵌套的 definition.function，否则前端读 def.function.name
        会抛 "Cannot read properties of undefined"，导致整个聊天页崩掉。
        """
        tc = engine.agent.tool_coordinator
        cwd_aware = {"file.read", "file.write", "file.edit", "file.list",
                     "file.tree", "proc.run", "project.summary",
                     "project.snapshot", "project.todo", "batch.run",
                     "code.locate_symbol", "code.diagnose"}
        out = []
        for item in tc.tool_index():
            name = item.get("id")
            if not name:
                continue
            out.append({
                "tool": name,
                "uses_cwd": name in cwd_aware,
                "definition": {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": item.get("description", ""),
                        "parameters": tc.toolbox.source.schema_for(name) or {
                            "type": "object",
                            "properties": {},
                        },
                    },
                },
            })
        return out

    @app.post("/tools")
    async def execute_tool_compat(req: Request):
        """执行 harness 工具。

        注意：正常对话链路中工具由后端 AgentLoop 统一执行，前端不再自行调用。
        此处仅为兼容 llama-ui 协议保留入口（如调试或外部集成）。
        """
        body = await req.json()
        tool_name = body.get("tool") or body.get("name")
        params = body.get("params") or body.get("arguments") or {}
        if not tool_name:
            raise HTTPException(status_code=400, detail="Missing 'tool' field")
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="params 必须是 JSON 对象")

        tool = engine.agent.tool_coordinator.tool_reg.get(tool_name)
        if tool is None:
            raise HTTPException(status_code=404, detail=f"未知工具: {tool_name}")

        try:
            result = await tool.run_async(**params)
        except Exception as e:
            logger.error("工具执行异常 %s: %s", tool_name, e)
            return {"success": False, "error": str(e)}

        return {
            "success": result.success,
            "output": result.output,
            "error": result.error,
            "status": result.status,
        }

    @app.get("/api/agent/tools")
    async def get_agent_tools():
        """当前注册的 harness 工具清单（toolbox 两阶段激活索引）。"""
        tc = engine.agent.tool_coordinator
        return {
            "total": len(tc.tool_names()),
            "toolbox_enabled": bool(tc.toolbox.enabled),
            "tools": tc.tool_index(),
        }

    @app.get("/api/agent/settings")
    async def get_agent_settings():
        """Agent 运行时设置（步数、工具截断、上下文策略、专用摘要模型）。"""
        return {
            "max_steps": engine.agent.get_max_steps(),
            "tool_max_output_chars": engine.agent.get_tool_max_output_chars(),
            "context_overflow_strategy": engine.agent.get_context_strategy(),
            "context_trigger_ratio": engine.agent.get_context_trigger_ratio(),
            "summary_model": engine.agent.get_summary_model() or "",
            "execution_mode_default": False,
        }

    @app.get("/api/agent/context-strategies")
    async def get_context_strategies():
        """可选策略清单，供前端下拉框渲染（含说明）。"""
        return {
            "current": engine.agent.get_context_strategy(),
            "strategies": [
                {
                    "id": "drop_oldest",
                    "label": "直接丢弃最早上下文",
                    "description": "不做摘要，直接删除本会话最早的消息，只保留最近几轮。"
                                   "零延迟、零成本，但被丢弃的内容不可恢复。",
                },
                {
                    "id": "compact_all",
                    "label": "整体压缩(compact)",
                    "description": "把整个会话（含所有话题）压缩成一份摘要后替换全部原文，"
                                   "只保留最近少量消息。适合任务已结束、准备开新话题时。",
                },
                {
                    "id": "topic_merge",
                    "label": "话题合并(记忆系统)",
                    "description": "走记忆系统：把较早轮次合并为话题摘要，保留最近原文，"
                                   "历史结论仍可被检索。默认策略，信息保留最完整。",
                },
            ],
        }

    @app.post("/api/agent/settings")
    async def update_agent_settings(req: Request):
        """更新 Agent 运行时设置（如 AgentLoop 最大自主循环步数、工具截断字符数）。"""
        body = await req.json()
        logger.info("更新 Agent 运行时设置: %s", sorted(body.keys()))
        if "max_steps" in body:
            try:
                steps = int(body["max_steps"])
            except (TypeError, ValueError):
                logger.warning("max_steps 非法: %r", body.get("max_steps"))
                raise HTTPException(status_code=400, detail="max_steps 必须是整数")
            if steps < 0 or steps > 10000:
                raise HTTPException(status_code=400, detail="max_steps 需在 0..10000（0 = 不限制）")
            engine.agent.set_max_steps(steps)

        if "tool_max_output_chars" in body:
            try:
                chars = int(body["tool_max_output_chars"])
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="tool_max_output_chars 必须是整数")
            if chars < 500 or chars > 500000:
                raise HTTPException(status_code=400, detail="tool_max_output_chars 需在 500..500000 之间")
            engine.agent.set_tool_max_output_chars(chars)

        if "context_overflow_strategy" in body:
            try:
                engine.agent.set_context_strategy(str(body["context_overflow_strategy"]))
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))

        if "context_trigger_ratio" in body:
            try:
                engine.agent.set_context_trigger_ratio(float(body["context_trigger_ratio"]))
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="context_trigger_ratio 必须是数字")

        if "summary_model" in body:
            # 允许传空字符串以清除专用模型（回退到当前对话模型 / 启发式分析）
            engine.agent.set_summary_model(body.get("summary_model"))

        return {
            "status": "ok",
            "max_steps": engine.agent.get_max_steps(),
            "tool_max_output_chars": engine.agent.get_tool_max_output_chars(),
            "context_overflow_strategy": engine.agent.get_context_strategy(),
            "context_trigger_ratio": engine.agent.get_context_trigger_ratio(),
            "summary_model": engine.agent.get_summary_model() or "",
        }

    # ── 7. 本地系统资源与显存监控 API ──

    @app.get("/api/system/resources")
    async def get_system_resources_api():
        """返回 CPU、系统内存及所有显卡的显存监控数据。"""
        res = get_system_resources()
        status = engine.orchestrator.status()
        res["orchestrator"] = status
        # 显存管理开关状态，供硬件页渲染
        res["kv_offload_disabled"] = engine.orchestrator.get_kv_offload_disabled()
        return res

    @app.get("/api/system/kv-offload")
    async def get_kv_offload():
        """读取「卸载上下文(KV cache)到 CPU 内存」开关状态。"""
        return {
            "kv_offload_disabled": engine.orchestrator.get_kv_offload_disabled(),
            "description": (
                "开启后所有 llama.cpp 模型加载时会附加 --no-kv-offload，"
                "KV cache 常驻系统内存以降低显存占用；代价是注意力计算需跨 PCIe "
                "读取缓存，推理速度下降。已加载的模型需重新加载后生效。"
            ),
        }

    @app.post("/api/system/kv-offload")
    async def set_kv_offload(req: Request):
        """设置「卸载上下文(KV cache)到 CPU 内存」开关。

        参数写入所有 llama.cpp 模型的启动配置，因此**下一次加载**即生效；
        已在运行的模型需要重新加载（卸载→加载）才会应用新参数。
        """
        body = await req.json()
        if "kv_offload_disabled" not in body:
            raise HTTPException(status_code=400, detail="缺少参数 kv_offload_disabled")
        disabled = bool(body["kv_offload_disabled"])
        affected = engine.orchestrator.set_kv_offload_disabled(disabled)
        logger.info(
            "KV offload 开关更新: disabled=%s affected=%d", disabled, affected
        )
        return {
            "status": "ok",
            "kv_offload_disabled": engine.orchestrator.get_kv_offload_disabled(),
            "affected_models": affected,
            "note": "该设置对之后加载的模型生效；已加载模型需重新加载。",
        }

    # ── 8. DSN 全量设置项 API ──

    @app.get("/api/settings")
    async def get_all_settings():
        """读取 DSN 全局设置命名空间。"""
        from apps.dsn.config import Config
        return {
            "orchestrator": {
                "max_concurrent_slots": engine.orchestrator.max_concurrent_slots,
                "llamacpp_bin": Config.LLAMACPP_BIN,
                "llamacpp_base_url": Config.LLAMACPP_BASE_URL,
                "lmstudio_base_url": Config.LMSTUDIO_BASE_URL,
                "openai_api_base": Config.OPENAI_API_BASE,
                "openai_api_key_set": bool(Config.OPENAI_API_KEY),
            },
            "memory": {
                "enabled": Config.MEMORY_ENABLED,
                "embedding_enabled": Config.MEMORY_EMBEDDING_ENABLED,
                "embedding_model": Config.MEMORY_EMBEDDING_MODEL,
                "summary_backend": Config.MEMORY_SUMMARY_BACKEND,
                "context_window_size": Config.MEMORY_CONTEXT_WINDOW_SIZE,
                "search_threshold": Config.MEMORY_SEARCH_THRESHOLD,
            },
            "voice": {
                "asr_enabled": Config.ASR_ENABLED,
                "asr_device": Config.ASR_DEVICE,
                "tts_enabled": Config.TTS_ENABLED,
                "tts_base_url": Config.TTS_BASE_URL,
                "tts_process_enabled": Config.TTS_PROCESS_ENABLED,
            },
            "companion": {
                "personality_v3_enabled": Config.PERSONALITY_V3_ENABLED,
                "world_enabled": Config.WORLD_ENABLED,
                "narrative_enabled": Config.NARRATIVE_ENABLED,
            },
            "personal": {
                "task_manager_enabled": Config.TASK_MANAGER_ENABLED,
            },
            "server": {
                "host": Config.SERVER_HOST,
                "port": Config.SERVER_PORT,
                "log_level": Config.LOG_LEVEL,
            }
        }

    @app.post("/api/settings")
    async def update_settings(req: Request):
        """更新 DSN 配置项。"""
        data = await req.json()
        orch_data = data.get("orchestrator", {})
        if "max_concurrent_slots" in orch_data:
            engine.orchestrator.max_concurrent_slots = int(orch_data["max_concurrent_slots"])
        return {"status": "ok", "message": "Settings updated"}

    # ── 9. 底层 Orchestrator 专用控制 API ──

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "app": "dsn_ui"}

    # ── 模型启动参数预设（UI 右侧面板）──

    def _require_local_model(model_name: str):
        """校验模型存在且为本地 llama.cpp 模型。"""
        if not model_name:
            raise HTTPException(status_code=400, detail="缺少 model 字段")
        if model_name not in engine.orchestrator._specs:
            raise HTTPException(status_code=404, detail=f"未知模型: {model_name}")
        return model_name

    @app.get("/api/models/launch-params")
    async def get_launch_params(model: str):
        """读取某模型的当前启动参数（用于预设面板回显）。"""
        _require_local_model(model)
        try:
            params = engine.orchestrator.get_launch_params(model)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        params["has_override"] = model in engine.load_launch_overrides()
        return params

    @app.post("/api/models/launch-params/preview")
    async def preview_launch_params(req: Request):
        """预览参数合成出的命令行（不落地、不启动）。"""
        body = await req.json()
        model = _require_local_model(body.get("model") or "")
        base = engine.orchestrator.get_launch_params(model)
        merged = {**base, **(body.get("params") or {})}
        from harness.orchestrator import LlamaServerConfig
        cfg = LlamaServerConfig.from_dict(merged)
        return {"command": cfg.to_command_string()}

    @app.post("/api/models/launch-params/save")
    async def save_launch_params(req: Request):
        """★ 保存为持久化预设：覆盖当前 profile 参数，跨重启有效。

        请求体: { model, params }
        """
        body = await req.json()
        model = _require_local_model(body.get("model") or "")
        params = body.get("params") or {}
        try:
            changed = engine.orchestrator.apply_launch_params(model, params)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        saved = engine.save_launch_override(model, params)
        logger.info("保存启动参数预设: model=%s changed=%s", model, sorted(changed))
        return {
            "status": "ok",
            "model": model,
            "changed": sorted(changed),
            "saved": saved,
            "note": "已持久化；下一次加载该模型时生效",
        }

    @app.post("/api/models/launch-params/reset")
    async def reset_launch_params(req: Request):
        """清除持久化覆盖，恢复 profile 原始参数。"""
        body = await req.json()
        model = _require_local_model(body.get("model") or "")
        cleared = engine.clear_launch_override(model)
        return {"status": "ok", "model": model, "cleared": cleared}

    @app.post("/api/models/launch-once")
    async def launch_once(req: Request):
        """★ 用给定参数**启动一次**（不保存）。

        用一个临时请求体覆盖配置加载一次，加载完成后把配置恢复原样，
        因此不会影响后续的默认加载行为。
        """
        body = await req.json()
        model = _require_local_model(body.get("model") or "")
        params = body.get("params") or {}

        # 记录原值以便恢复
        original = engine.orchestrator.get_launch_params(model)
        try:
            engine.orchestrator.apply_launch_params(model, params)
            logger.info("一次性启动(自定义参数): %s", model)
            ok = await asyncio.to_thread(engine.orchestrator.load_model, model)
        except Exception as e:  # noqa: BLE001
            log_exception(logger, f"一次性启动失败: {model}", e)
            engine.orchestrator.apply_launch_params(model, original)
            return JSONResponse(
                status_code=500,
                content={"success": False, "model": model, "error": str(e)},
            )
        finally:
            # 恢复原配置：一次性启动不应污染持久设置
            try:
                restore = {k: v for k, v in original.items()
                           if k not in ("model", "has_override", "command_preview")}
                engine.orchestrator.apply_launch_params(model, restore)
            except Exception as e:  # noqa: BLE001
                logger.warning("恢复启动参数失败 %s: %s", model, e)

        return {
            "success": bool(ok),
            "model": model,
            "status": "loaded" if ok else "failed",
            "transient": True,
        }

    @app.get("/api/integration/bonsai")
    async def get_bonsai_status():
        """Bonsai-demo 集成状态：自定义二进制与多模态模型发现结果。

        供前端/集成方确认「自定义 llama.cpp + 本地多模态」是否就绪。
        """
        from apps.dsn_ui.bonsai_integration import bonsai_status
        return bonsai_status()

    @app.get("/api/orchestrator/status")
    async def get_orchestrator_status():
        return engine.orchestrator.status()

    @app.post("/api/orchestrator/slots")
    async def set_slots(req: Request):
        data = await req.json()
        slots = data.get("slots")
        if slots is None or int(slots) < 1:
            raise HTTPException(status_code=400, detail="slots must be >= 1")
        engine.orchestrator.max_concurrent_slots = int(slots)
        return {"status": "ok", "max_concurrent_slots": engine.orchestrator.max_concurrent_slots}

    @app.post("/api/orchestrator/default-model")
    async def set_default_model(req: Request):
        data = await req.json()
        name = data.get("model")
        if not name:
            raise HTTPException(status_code=400, detail="model name required")
        engine.orchestrator.set_default_model(name)
        return {"status": "ok", "default_model": name}

    # ── 9.5 可恢复流与后台推理会话探查端点 ──

    @app.post("/v1/streams/lookup")
    async def streams_lookup(req: Request):
        """客户端挂载与聚焦时查询服务端当前活跃的后台流式会话。

        返回 [{conversation_id, is_done, total_bytes, started_at, completed_at}]，
        前端据此点亮侧边栏转圈，并对当前会话执行 attach（回放重连）。
        只返回调用方显式询问的 id，不泄露其它会话。
        """
        await stream_registry.prune()
        try:
            body = await req.json()
        except Exception:  # noqa: BLE001 - 空/非法 body 视为无查询
            body = {}
        ids = body.get("conversation_ids") or body.get("stream_ids") or []
        if not isinstance(ids, list):
            ids = [ids]
        ids = [str(i) for i in ids if str(i).strip()]
        result = await stream_registry.lookup(ids)
        logger.info(
            "streams/lookup: 查询 %d 个 id → 命中 %d 个会话 %s",
            len(ids), len(result), [r["conversation_id"] for r in result][:5],
        )
        return result

    @app.get("/v1/stream")
    async def stream_resume(req: Request):
        """断线重连回放：从 from 指定的字节偏移开始，先补历史再实时续传。

        这是"重新打开页面/切回标签页后接回进行中的推理"的关键入口。
        以前这里恒返回 404，直接导致前端报
        "Stream connection lost and could not be resumed" 并卡在思考中。
        """
        await stream_registry.prune()
        conv_id = (req.query_params.get("conv_id") or "").strip()
        if not conv_id:
            raise HTTPException(status_code=400, detail="conv_id is required")
        try:
            offset = int(req.query_params.get("from") or 0)
        except (TypeError, ValueError):
            offset = 0

        session = await stream_registry.get(conv_id)
        if session is None:
            logger.info("stream_resume: 会话不存在 conv=%s", conv_id)
            raise HTTPException(status_code=404, detail="No active stream session found")

        logger.info(
            "stream_resume: 重连成功 conv=%s from=%d total=%d done=%s",
            conv_id, offset, session.total_bytes, session.is_done,
        )

        # 重连同样需要保活：断连期间后端可能正在跑耗时工具，
        # 重连后若长时间没有新字节，连接会再次被判死。
        try:
            resume_ping = float(req.query_params.get("sse_ping_interval") or 0) or 0.0
        except (TypeError, ValueError):
            resume_ping = 0.0
        resume_hb: Dict[str, Any] = {}
        if resume_ping > 0:
            resume_hb["heartbeat_interval"] = max(0.2, min(30.0, resume_ping))

        async def _replay_generator():
            try:
                async for data in stream_registry.replay(
                    conv_id, offset, **resume_hb
                ):
                    yield data
            except KeyError:
                return

        return StreamingResponse(
            _replay_generator(),
            media_type="text/event-stream; charset=utf-8",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "Content-Type": "text/event-stream; charset=utf-8",
                "X-Stream-Total-Bytes": str(session.total_bytes),
            },
        )

    @app.delete("/v1/stream")
    async def stream_cancel(req: Request):
        """取消后台流会话（用户点停止 / 前端清理）。"""
        conv_id = (req.query_params.get("conv_id") or "").strip()
        if not conv_id:
            return {"status": "ok", "cancelled": False}
        cancelled = await stream_registry.cancel(conv_id)
        logger.info("stream_cancel: conv=%s cancelled=%s", conv_id, cancelled)
        return {"status": "ok", "cancelled": cancelled}

    # ── 9.9 DSN 集成 API（OpenAI / Anthropic 兼容 + 显存管理）──
    # 关键：必须在下方 SPA catch-all (/{full_path:path}) **之前**注册。
    # FastAPI 按注册顺序匹配，catch-all 会吞掉所有在它之后注册的 GET 路由
    # （表现为返回 index.html 而不是 JSON）。
    try:
        from apps.dsn_ui.integration_api import register_integration_routes
        register_integration_routes(app, engine)
        logger.info(
            "DSN 集成 API 已启用: /v1/messages, /v1/models/load|unload, /api/integration/*"
        )
    except Exception as e:  # noqa: BLE001
        log_exception(logger, "挂载 DSN 集成 API 失败", e)

    # ── 10. 静态资源与 SPA 路由 ──

    static_dir = Path(__file__).resolve().parent / "static"
    if static_dir.exists():
        app.mount("/_app", StaticFiles(directory=str(static_dir / "_app")), name="app_assets")

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str):
            file_path = static_dir / full_path
            if file_path.is_file():
                return FileResponse(file_path)
            return FileResponse(static_dir / "index.html")

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="DSN-exp UI & Orchestrator Web Server")
    parser.add_argument("--host", default=UIConfig.HOST, help="Host to bind")
    parser.add_argument("--port", type=int, default=UIConfig.PORT, help="Port to bind")
    parser.add_argument("--slots", type=int, default=UIConfig.DEFAULT_SLOTS, help="Concurrent slots")
    args = parser.parse_args()

    # 必须最先配置日志：此前 dsn_ui 从未调用过 basicConfig，
    # 根 logger 无 handler，任何 logger.exception 都只剩一行裸消息。
    setup_logging(level=os.getenv("DSN_UI_LOG_LEVEL", "INFO"))

    engine = DSNUIEngine(max_concurrent_slots=args.slots)
    app = create_app(engine)
    logger.info("DSN-exp UI 启动中: http://%s:%s slots=%s", args.host, args.port, args.slots)
    print(f"🚀 DSN-exp UI 正在启动: http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
