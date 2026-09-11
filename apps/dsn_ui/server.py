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
    if engine is None:
        engine = DSNUIEngine(max_concurrent_slots=UIConfig.DEFAULT_SLOTS)

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
        yield
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
        n_ctx = 128000

        return {
            "role": "router",
            "default_generation_settings": {
                "id": 0,
                "id_task": 0,
                "n_ctx": n_ctx,
                "speculative": False,
                "is_processing": False,
                "params": {
                    "n_predict": 4096,
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
                    "n_ctx": 128000,
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
                yield "event: models_reload\ndata: {}\n\n"
                status = engine.orchestrator.status()
                for m in status.get("models", []):
                    val = "loaded" if m["loaded"] else "unloaded"
                    payload = {"model": m["name"], "event": f"status_{val}", "data": {"status": val}}
                    yield f"event: status_{val}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

                while True:
                    msg = await queue.get()
                    yield msg
            except asyncio.CancelledError:
                pass
            finally:
                await sse_broadcaster.unsubscribe(queue)

        return StreamingResponse(event_generator(), media_type="text/event-stream")

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
            if isinstance(content, list):
                text_parts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
                content = " ".join(text_parts) if text_parts else str(content)

            if role == "system":
                chat_messages.append(ChatMessage.system(str(content)))
            elif role == "user":
                chat_messages.append(ChatMessage.user(str(content)))
            elif role == "assistant":
                chat_messages.append(ChatMessage.assistant(str(content)))

        if not stream:
            resp = engine.orchestrator.invoke(
                chat_messages,
                model_name=model_name,
                temperature=temperature,
            )
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

        async def _sse_generator():
            try:
                agen = engine.orchestrator.stream(
                    chat_messages,
                    model_name=model_name,
                    temperature=temperature,
                )
                async for chunk in agen:
                    if isinstance(chunk, str):
                        payload = {
                            "choices": [{"delta": {"content": chunk}, "index": 0}]
                        }
                    elif isinstance(chunk, dict) and "reasoning_content" in chunk:
                        payload = {
                            "choices": [{"delta": {"reasoning_content": chunk["reasoning_content"]}, "index": 0}]
                        }
                    elif isinstance(chunk, dict) and "tool_calls" in chunk:
                        payload = {
                            "choices": [{"delta": {"tool_calls": chunk["tool_calls"]}, "index": 0}]
                        }
                    else:
                        continue
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                logger.error("SSE 推理异常: %s", e)
                err_payload = {"error": {"message": str(e), "type": "server_error"}}
                yield f"data: {json.dumps(err_payload, ensure_ascii=False)}\n\n"
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

    # ── 7. 本地系统资源与显存监控 API ──

    @app.get("/api/system/resources")
    async def get_system_resources_api():
        """返回 CPU、系统内存及所有显卡的显存监控数据。"""
        res = get_system_resources()
        status = engine.orchestrator.status()
        res["orchestrator"] = status
        return res

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
        """客户端挂载与聚焦时查询服务端当前活跃的后台流式会话。"""
        # 返回空列表表示当前无持久后台断点流需要重连接驳
        return []

    @app.get("/v1/stream")
    async def stream_resume(req: Request):
        raise HTTPException(status_code=404, detail="No active stream session found")

    @app.delete("/v1/stream")
    async def stream_cancel(req: Request):
        return {"status": "ok"}

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

    engine = DSNUIEngine(max_concurrent_slots=args.slots)
    app = create_app(engine)
    print(f"🚀 DSN-exp UI 正在启动: http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
