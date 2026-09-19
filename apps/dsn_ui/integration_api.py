# apps/dsn_ui/integration_api.py
"""DSN 集成 API：对外暴露 OpenAI Chat Completions 与 Anthropic Messages 兼容端点。

## 目的

让外部工具（Open WebUI、Continue、Cline、LangChain、Anthropic SDK 等）把
dsn_ui 当作一个标准的本地推理服务来用，同时提供 dsn_ui 特有的
**显式模型加载/卸载** 能力 —— 这是普通 OpenAI 兼容服务没有的。

## 端点总览

OpenAI 兼容（`/v1/...`）：
  GET  /v1/models                     列出模型（含加载状态与能力）
  POST /v1/chat/completions           Chat Completions（流式/非流式，支持多模态）
  POST /v1/embeddings                 （占位，返回明确的不支持错误）
  POST /v1/models/load                ★ DSN 特有：加载到显存
  POST /v1/models/unload              ★ DSN 特有：从显存卸载

Anthropic 兼容（`/v1/messages`）：
  POST /v1/messages                   Anthropic Messages API（含 SSE 事件流）

DSN 专有管理端点（`/api/integration/...`）：
  GET  /api/integration/models        模型 + 能力 + 显存状态总览
  POST /api/integration/models/load   加载（支持 keep_alive / wait 语义）
  POST /api/integration/models/unload 卸载
  POST /api/integration/models/reload 卸载后重新加载（应用新参数）
  GET  /api/integration/capabilities  服务能力自描述

设计取舍：
  * 复用现有 engine.agent.chat_stream / chat_invoke，因此记忆、情绪、
    工具箱两阶段激活等 dsn_ui 特性对集成调用方同样生效。
  * Anthropic 的 content block 结构与 OpenAI 不同，这里做双向转换：
    text / image（base64 与 url）/ tool_use / tool_result。
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
import uuid
from typing import Any, AsyncGenerator, Optional

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

logger = logging.getLogger("DSNUIIntegration")


# ────────────────────────── 消息格式转换 ──────────────────────────

def openai_content_to_parts(content: Any) -> Any:
    """把 OpenAI 风格的 content 归一化。

    - 字符串 → 原样返回（纯文本）
    - 数组   → 保留 text / image_url 结构（多模态必须原样透传给 llama-server，
               一旦拍平成字符串，图像就丢了）
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[dict] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            ptype = part.get("type")
            if ptype in ("text", "input_text"):
                parts.append({"type": "text", "text": part.get("text", "")})
            elif ptype == "image_url":
                # 直接透传，llama-server 的 mtmd 支持 image_url（含 data: base64）
                parts.append({"type": "image_url", "image_url": part.get("image_url", {})})
            # 其它类型（如 audio）原样保留，交给后端决定是否支持
            else:
                parts.append(part)
        return parts or ""
    return str(content)


def anthropic_messages_to_openai(
    system: Any,
    messages: list[dict],
) -> list[dict]:
    """Anthropic Messages 请求 → OpenAI messages。

    Anthropic 的结构：
      system:   string 或 [{type:text, text:...}]
      messages: [{role: user|assistant, content: string | [block, ...]}]
      block:    {type:text|image|tool_use|tool_result, ...}
    """
    out: list[dict] = []

    # 1) system 归一化为一条 system 消息
    sys_text = ""
    if isinstance(system, str):
        sys_text = system
    elif isinstance(system, list):
        sys_text = "\n\n".join(
            b.get("text", "") for b in system
            if isinstance(b, dict) and b.get("type") == "text"
        )
    if sys_text.strip():
        out.append({"role": "system", "content": sys_text})

    # 2) 逐条转换消息
    for msg in messages or []:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue

        parts: list[dict] = []
        for block in content or []:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")

            if btype == "text":
                parts.append({"type": "text", "text": block.get("text", "")})

            elif btype == "image":
                source = block.get("source") or {}
                stype = source.get("type")
                if stype == "base64":
                    media = source.get("media_type", "image/png")
                    data = source.get("data", "")
                    parts.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{media};base64,{data}"},
                    })
                elif stype == "url":
                    parts.append({
                        "type": "image_url",
                        "image_url": {"url": source.get("url", "")},
                    })

            elif btype == "tool_use":
                # Anthropic 的 assistant tool_use → OpenAI tool_calls
                out.append({
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": block.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                        "type": "function",
                        "function": {
                            "name": block.get("name", ""),
                            "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
                        },
                    }],
                })
                continue

            elif btype == "tool_result":
                # Anthropic 的 tool_result → OpenAI role=tool
                tr_content = block.get("content", "")
                if isinstance(tr_content, list):
                    tr_content = "\n".join(
                        b.get("text", "") for b in tr_content
                        if isinstance(b, dict) and b.get("type") == "text"
                    )
                out.append({
                    "role": "tool",
                    "tool_call_id": block.get("tool_use_id", ""),
                    "content": str(tr_content),
                })
                continue

        if parts:
            # 只有单个纯文本块时退化成字符串，兼容性更好
            if len(parts) == 1 and parts[0].get("type") == "text":
                out.append({"role": role, "content": parts[0]["text"]})
            else:
                out.append({"role": role, "content": parts})
    return out


# ────────────────────────── 模型能力描述 ──────────────────────────

def describe_model(spec, loaded: bool) -> dict:
    """把 ModelSpec 转成集成 API 的模型描述。

    包含 OpenAI 兼容字段（id/object/created/owned_by）与 DSN 扩展字段
    （loaded/loading/source_type/context/command），便于调用方决定是否加载。
    """
    cfg = getattr(spec, "llama_config", None)
    is_local = spec.source_type.value == "local_llamacpp"
    is_loading = getattr(spec, "name", "") in set()

    ctx = None
    if cfg is not None and getattr(cfg, "ctx_size", None):
        ctx = cfg.ctx_size

    return {
        "id": spec.name,
        "object": "model",
        "created": int(time.time()),
        "owned_by": "dsn-exp",
        # DSN 扩展
        "loaded": bool(loaded),
        "source_type": spec.source_type.value,
        "local": is_local,
        "orchestrated": bool(getattr(spec.profile, "orchestrated", False)),
        "priority": getattr(spec.profile, "priority", 50),
        "context_size": ctx,
        # 多模态能力：本地模型带 mmproj 才能处理图像
        "capabilities": {
            "vision": bool(getattr(cfg, "mmproj_path", None)) if cfg is not None else False,
            "tools": True,
            "streaming": True,
        },
    }


def build_model_descriptors(orchestrator) -> list[dict]:
    """汇总所有模型描述（含加载中状态）。"""
    status = orchestrator.status()
    loaded = {m["name"]: bool(m.get("loaded")) for m in status.get("models", [])}
    loading = {
        m["name"]: bool(m.get("is_loading") or m.get("status") == "loading")
        for m in status.get("models", [])
    }
    out: list[dict] = []
    for name, spec in sorted(orchestrator._specs.items()):
        d = describe_model(spec, loaded.get(name, False))
        d["loading"] = loading.get(name, False)
        out.append(d)
    return out


# ────────────────────────── Anthropic SSE 事件流 ──────────────────────────

def sse_event(event: str, data: dict) -> str:
    """构造一条 Anthropic 风格的 SSE 事件。"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def anthropic_stream(
    engine,
    *,
    model_name: str,
    messages: list[dict],
    temperature: Optional[float],
    max_tokens: Optional[int],
    execution_mode: bool,
) -> AsyncGenerator[str, None]:
    """把 dsn_ui 的流式事件翻译成 Anthropic Messages 的 SSE 事件序列。

    事件顺序（遵循 Anthropic 规范）：
      message_start
      content_block_start (text)
      content_block_delta ... (可多条)
      content_block_stop
      message_delta (stop_reason)
      message_stop
    """
    msg_id = f"msg_{uuid.uuid4().hex[:24]}"

    yield sse_event("message_start", {
        "type": "message_start",
        "message": {
            "id": msg_id,
            "type": "message",
            "role": "assistant",
            "model": model_name,
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        },
    })

    block_index = 0
    text_started = False
    tool_blocks: dict[str, int] = {}
    output_chars = 0
    stop_reason = "end_turn"

    def open_text() -> str:
        return sse_event("content_block_start", {
            "type": "content_block_start",
            "index": block_index,
            "content_block": {"type": "text", "text": ""},
        })

    try:
        async for chunk in engine.agent.chat_stream(
            messages_raw=messages,
            model_name=model_name,
            temperature=temperature,
            execution_mode=execution_mode,
            max_tokens=max_tokens,
        ):
            ctype = chunk.get("type")

            if ctype == "delta" and chunk.get("content"):
                if not text_started:
                    text_started = True
                    yield open_text()
                text = chunk["content"]
                output_chars += len(text)
                yield sse_event("content_block_delta", {
                    "type": "content_block_delta",
                    "index": block_index,
                    "delta": {"type": "text_delta", "text": text},
                })

            elif ctype == "tool_call":
                # 工具调用作为独立的 tool_use 内容块
                tc = chunk.get("tool_call", {})
                if text_started:
                    yield sse_event("content_block_stop", {
                        "type": "content_block_stop", "index": block_index,
                    })
                    block_index += 1
                    text_started = False
                call_id = tc.get("id") or f"call_{uuid.uuid4().hex[:8]}"
                tool_blocks[call_id] = block_index
                yield sse_event("content_block_start", {
                    "type": "content_block_start",
                    "index": block_index,
                    "content_block": {
                        "type": "tool_use",
                        "id": call_id,
                        "name": tc.get("name", ""),
                        "input": {},
                    },
                })
                yield sse_event("content_block_delta", {
                    "type": "content_block_delta",
                    "index": block_index,
                    "delta": {
                        "type": "input_json_delta",
                        "partial_json": json.dumps(tc.get("arguments", {}), ensure_ascii=False),
                    },
                })
                yield sse_event("content_block_stop", {
                    "type": "content_block_stop", "index": block_index,
                })
                block_index += 1
                stop_reason = "tool_use"

            elif ctype == "done" and chunk.get("hit_max"):
                stop_reason = "max_tokens"

        if text_started:
            yield sse_event("content_block_stop", {
                "type": "content_block_stop", "index": block_index,
            })

        yield sse_event("message_delta", {
            "type": "message_delta",
            "delta": {"stop_reason": stop_reason, "stop_sequence": None},
            "usage": {"output_tokens": max(1, output_chars // 4)},
        })
        yield sse_event("message_stop", {"type": "message_stop"})
    except Exception as e:  # noqa: BLE001
        logger.exception("Anthropic 流式转换失败")
        yield sse_event("error", {
            "type": "error",
            "error": {"type": "api_error", "message": str(e)},
        })


def register_integration_routes(app, engine) -> None:
    """把所有集成 API 路由挂载到 FastAPI app 上。"""

    # ─────────── OpenAI: 模型清单 ───────────

    @app.get("/v1/integration/models")
    async def integration_models():
        """模型清单 + 加载状态 + 多模态能力（DSN 扩展版）。"""
        return {"object": "list", "data": build_model_descriptors(engine.orchestrator)}

    # ─────────── OpenAI: 显式加载 / 卸载 ───────────

    @app.post("/v1/models/load")
    @app.post("/api/integration/models/load")
    async def integration_load(req: Request):
        """★ DSN 特有：把模型加载到显存。

        请求体：
          model       (必填) 模型 id
          wait        (可选，默认 true) 是否等待加载完成
          timeout     (可选) 等待秒数上限

        与普通 OpenAI 兼容服务的区别：这里能**显式控制显存**，
        配合 /v1/models/unload 可实现多模型轮换而不触发自动调度排队。
        """
        body = await req.json()
        model_id = body.get("model") or body.get("model_id") or body.get("id")
        if not model_id:
            raise HTTPException(status_code=400, detail="缺少 model 字段")
        if model_id not in engine.orchestrator._specs:
            raise HTTPException(status_code=404, detail=f"未知模型: {model_id}")

        wait = body.get("wait", True)
        logger.info("集成 API 加载模型: %s (wait=%s)", model_id, wait)

        if not wait:
            # 异步加载：立刻返回，客户端可轮询状态
            async def _bg():
                try:
                    await asyncio.to_thread(engine.orchestrator.load_model, model_id)
                except Exception:
                    logger.exception("后台加载模型失败: %s", model_id)

            asyncio.create_task(_bg())
            return {"success": True, "model": model_id, "status": "loading", "waited": False}

        try:
            ok = await asyncio.to_thread(engine.orchestrator.load_model, model_id)
        except Exception as e:  # noqa: BLE001
            logger.exception("加载模型异常: %s", model_id)
            return JSONResponse(
                status_code=500,
                content={"success": False, "model": model_id, "error": str(e)},
            )
        if not ok:
            return JSONResponse(
                status_code=500,
                content={"success": False, "model": model_id, "error": "启动失败"},
            )
        return {"success": True, "model": model_id, "status": "loaded", "waited": True}

    @app.post("/v1/models/unload")
    @app.post("/api/integration/models/unload")
    async def integration_unload(req: Request):
        """★ DSN 特有：从显存卸载模型，释放槽位与显存。"""
        body = await req.json()
        model_id = body.get("model") or body.get("model_id") or body.get("id")
        if not model_id:
            raise HTTPException(status_code=400, detail="缺少 model 字段")
        if model_id not in engine.orchestrator._specs:
            raise HTTPException(status_code=404, detail=f"未知模型: {model_id}")
        logger.info("集成 API 卸载模型: %s", model_id)
        try:
            ok = await asyncio.to_thread(engine.orchestrator.unload_model, model_id)
        except Exception as e:  # noqa: BLE001
            logger.exception("卸载模型异常: %s", model_id)
            return JSONResponse(
                status_code=500,
                content={"success": False, "model": model_id, "error": str(e)},
            )
        return {"success": bool(ok), "model": model_id, "status": "unloaded"}

    @app.post("/api/integration/models/reload")
    async def integration_reload(req: Request):
        """★ DSN 特有：卸载后重新加载（用于让新的启动参数生效）。

        典型用途：切换 KV cache 卸载开关、显存分层等启动参数后，
        用本端点一次性重建模型实例。
        """
        body = await req.json()
        model_id = body.get("model") or body.get("model_id")
        if not model_id:
            raise HTTPException(status_code=400, detail="缺少 model 字段")
        if model_id not in engine.orchestrator._specs:
            raise HTTPException(status_code=404, detail=f"未知模型: {model_id}")
        logger.info("集成 API 重新加载模型: %s", model_id)

        def _reload() -> bool:
            try:
                engine.orchestrator.unload_model(model_id)
            except Exception:
                logger.warning("重新加载前卸载失败（忽略继续）: %s", model_id)
            return engine.orchestrator.load_model(model_id)

        ok = await asyncio.to_thread(_reload)
        return {"success": bool(ok), "model": model_id,
                "status": "loaded" if ok else "failed"}

    # ─────────── DSN 能力自描述 ───────────

    @app.get("/api/integration/capabilities")
    async def integration_capabilities():
        """服务能力自描述，供集成方探测支持的特性。"""
        status = engine.orchestrator.status()
        return {
            "service": "dsn-exp",
            "api_version": "1.0",
            "protocols": {
                "openai_chat_completions": "/v1/chat/completions",
                "openai_models": "/v1/models",
                "anthropic_messages": "/v1/messages",
                "dsn_models_load": "/v1/models/load",
                "dsn_models_unload": "/v1/models/unload",
                "dsn_models_reload": "/api/integration/models/reload",
            },
            "features": {
                "streaming": True,
                "tool_calling": True,
                "vision": any(
                    d["capabilities"]["vision"]
                    for d in build_model_descriptors(engine.orchestrator)
                ),
                "explicit_model_management": True,
                "agent_execution_mode": True,
                "memory_and_emotion": True,
            },
            "slots": {
                "max": status.get("max_concurrent_slots"),
                "used": status.get("used_slots"),
            },
            "default_model": engine.orchestrator.get_default_model(),
        }

    # ─────────── Anthropic Messages ───────────

    @app.post("/v1/messages")
    async def anthropic_messages(req: Request):
        """Anthropic Messages API 兼容端点。

        支持：
          - 文本、图像（base64 / url）、tool_use / tool_result 内容块
          - 流式（stream=true）与非流式
          - system 字符串或内容块数组
        """
        body = await req.json()
        model_name = body.get("model") or engine.orchestrator.get_default_model()
        if not model_name:
            raise HTTPException(status_code=400, detail="未指定模型且无默认模型")

        messages = anthropic_messages_to_openai(body.get("system"), body.get("messages") or [])
        stream = bool(body.get("stream", False))
        max_tokens = body.get("max_tokens")
        temperature = body.get("temperature")
        execution_mode = bool(body.get("execution_mode", False))

        logger.info(
            "Anthropic /v1/messages: model=%s stream=%s messages=%d max_tokens=%s",
            model_name, stream, len(messages), max_tokens,
        )

        if stream:
            return StreamingResponse(
                anthropic_stream(
                    engine,
                    model_name=model_name,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    execution_mode=execution_mode,
                ),
                media_type="text/event-stream; charset=utf-8",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        # 非流式
        try:
            resp = await asyncio.to_thread(
                engine.agent.chat_invoke,
                messages,
                model_name,
                temperature,
                execution_mode,
                None,
                max_tokens,
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("Anthropic 非流式调用失败")
            return JSONResponse(
                status_code=500,
                content={"type": "error",
                         "error": {"type": "api_error", "message": str(e)}},
            )

        return {
            "id": f"msg_{uuid.uuid4().hex[:24]}",
            "type": "message",
            "role": "assistant",
            "model": model_name,
            "content": [{"type": "text", "text": resp.content or ""}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {
                "input_tokens": 0,
                "output_tokens": max(1, len(resp.content or "") // 4),
            },
        }

    logger.info("DSN 集成 API 路由已挂载（OpenAI / Anthropic / 显存管理）")
