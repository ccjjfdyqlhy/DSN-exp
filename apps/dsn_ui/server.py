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
import socket
import subprocess
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse

import psutil
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from apps.dsn_ui.config import API_MODES, UIConfig
from apps.dsn_ui.engine import DSNUIEngine
from infra.orchestrator.base import content_shape, count_image_parts
from apps.dsn_ui.stream_sessions import registry as stream_registry
from apps.dsn_ui.logging_setup import (
    get_request_id,
    log_exception,
    reset_request_id,
    set_request_id,
    setup_logging,
)
from infra.orchestrator import ChatMessage, LlamaServerConfig, ModelSourceType

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

#: 保存运行中的事件循环，供工作线程投递 SSE（见 _schedule_broadcast）
_event_loop_holder: Dict[str, Any] = {"loop": None}


#: GPU 状态缓存 {monotonic 时间戳, [gpu, ...]}。
#:
#: nvidia-smi 每次都要 fork/exec 一个新进程（实测 50~200ms）。硬件页每 2s 轮询
#: 一次 /api/system/resources，每次都起进程既慢又吵。这里按 TTL 复用结果。
_GPU_CACHE_TTL_S = 1.0
_gpu_cache: Optional[tuple] = None


def _query_gpus() -> list:
    """读取 NVIDIA GPU 状态（带 1s 缓存）。失败返回上次结果或空列表。"""
    global _gpu_cache

    now = time.monotonic()
    if _gpu_cache is not None and (now - _gpu_cache[0]) < _GPU_CACHE_TTL_S:
        return _gpu_cache[1]

    gpus: list = []
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

    _gpu_cache = (now, gpus)
    return gpus


def _cfg(*names: str, default: Any = None) -> Any:
    """安全读取配置项。

    修复说明：server.py 曾大面积引用一个**未定义的** Config 名字
    （只导入了 UIConfig），导致 /api/settings、/api/resources/start 等端点
    一被调用就 NameError → 500。这里统一走安全读取：
    依次尝试 UIConfig 属性、同名环境变量，最后回退到默认值。
    """
    for name in names:
        val = getattr(UIConfig, name, None)
        if val is not None:
            return val
    for name in names:
        val = os.getenv(name)
        if val not in (None, ""):
            return val
    return default


def get_system_resources() -> dict:
    """获取 CPU、内存及 NVIDIA GPU 显存使用情况。

    **阻塞函数**：会调用 psutil 与 nvidia-smi。调用方必须放到线程里执行
    （见 /api/system/resources 的 asyncio.to_thread），否则会卡住事件循环。
    """
    vm = psutil.virtual_memory()
    ram_info = {
        "total_gb": round(vm.total / (1024 ** 3), 2),
        "used_gb": round(vm.used / (1024 ** 3), 2),
        "free_gb": round(vm.available / (1024 ** 3), 2),
        "percent": vm.percent,
    }

    # interval=None 表示「距上次调用以来的平均占用」，立即返回。
    # 原先的 interval=0.1 会让每次轮询都**硬睡 100ms**，在事件循环上就是
    # 每 2 秒把整个服务冻结 100ms（连带拖慢会话打开、模型列表、SSE 推送）。
    cpu_info = {
        "percent": psutil.cpu_percent(interval=None),
        "cores": psutil.cpu_count(logical=True),
    }

    return {
        "ram": ram_info,
        "cpu": cpu_info,
        "gpus": _query_gpus(),
    }


# ──模型输入模态探测（供 /props 与 /models 共用）──
# 模态必须来自真实能力：优先问运行中的 llama-server /props，
# 未加载时回退到配置推断（mmproj_path 表示支持图像）。
# 历史实现用名字含 'v'/'ocr' 猜测，导致带视觉投影器的
# bonsai:bonsai2:27B 被误判为纯文本，前端会在发送前丢弃图像。
# 模态探测结果缓存：{model_name: (monotonic 时间戳, {"vision": bool, ...})}
#
# 性能要点（重要）：探测是**阻塞 HTTP 请求**，而 /models、/v1/models、/props
# 都会对每个模型调用本函数。此前缓存只在「探测成功」或「配置推断为 True」时写入，
# 于是未加载模型每次请求都要重新发一次带 2s 超时的请求 —— 6 个本地模型就是
# 最多 12s，前端表现为「打开会话 / 加载模型列表 / 同步调度状态」明显变慢。
# 现在改为：只探测确实在运行的模型 + 正负结果一律带 TTL 缓存。
_MODALITY_CACHE_TTL_S = 10.0
#: 探测超时。本地 /props 正常在毫秒级返回，2s 只会在上游卡死时白白拖慢列表。
_MODALITY_PROBE_TIMEOUT_S = 0.6

#: 「某 base_url 上有没有服务在监听」的缓存 TTL。
#:
#: 实测：本机 4501（LMStudio 未启动）**不是拒绝连接而是直接挂住** ——
#: localhost 先解析到 ::1，那条路径没有 RST，于是每次探测都要等满整个超时。
#: 一个 base_url 上往往挂着多个模型（model_profiles 里有 5 个 lmstudio 模型
#: 都指向 :4501），逐个探测就是 5 × 超时，实测首屏 /models 要 5s。
#: 因此先做一次「端口是否可达」的判断并缓存，不可达时该 base_url 下的
#: 所有模型直接走配置推断，只付一次超时代价、且在 TTL 内不再重复。
_ENDPOINT_REACHABLE_TTL_S = 30.0
#: 可达性探测（TCP connect）的超时，比 HTTP 探测更短。
_ENDPOINT_PROBE_TIMEOUT_S = 0.4
_endpoint_reachable_cache: Dict[str, tuple] = {}

_modality_cache: Dict[str, tuple] = {}


def _endpoint_reachable(base_url: str) -> bool:
    """快速判断 base_url 上是否有服务在监听（结果按 TTL 缓存）。

    用 TCP connect 而不是 HTTP 请求：只关心「端口通不通」，不需要等对方
    走完整个 HTTP 事务，因此可以用更短的超时。
    """
    if not base_url:
        return False
    now = time.monotonic()
    cached = _endpoint_reachable_cache.get(base_url)
    if cached is not None and (now - cached[0]) < _ENDPOINT_REACHABLE_TTL_S:
        return cached[1]

    ok = False
    try:
        parsed = urlparse(base_url if "//" in base_url else f"//{base_url}")
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if host:
            with socket.create_connection((host, port), timeout=_ENDPOINT_PROBE_TIMEOUT_S):
                ok = True
    except OSError:
        ok = False
    except Exception:  # noqa: BLE001 - 可达性判断失败一律按不可达处理
        ok = False

    _endpoint_reachable_cache[base_url] = (now, ok)
    return ok

def _probe_server_modalities(model_name: str, spec) -> Optional[dict]:
    """向**正在运行**的本地引擎询问它真实支持的输入模态。

    llama.cpp 的 /props 在启用 mmproj 后返回:
        {"modalities": {"vision": true, "video": true, "audio": false}}
    这是最权威的信号 —— 比任何名字/配置推断都可靠。

    只有本模型自己的子进程存活时才探测：本地模型共用端口（如都指向 8080），
    未加载时去探测会命中「恰好加载在同一个端口上的**别的**模型」，
    既拿到错误的模态，又要为一个明知不存在的服务白等一个超时。
    """
    if spec is None:
        return None
    launcher = getattr(spec, "launcher", None)
    if launcher is None:
        return None
    try:
        if not launcher.is_running():
            return None
    except Exception:  # noqa: BLE001 - 探测失败不是错误，回退到配置推断
        return None
    base_url = getattr(spec, "base_url", None)
    if not base_url:
        return None
    try:
        from infra.orchestrator.base import local_probe_session
        headers = {}
        api_key = getattr(spec, "api_key", None)
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        # 走忽略代理的会话：本地引擎在 127.0.0.1，被 ALL_PROXY 接管会直接失败
        resp = local_probe_session().get(
            f"{base_url.rstrip('/')}/props",
            headers=headers,
            timeout=_MODALITY_PROBE_TIMEOUT_S,
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        mods = data.get("modalities")
        if isinstance(mods, dict):
            return {
                "vision": bool(mods.get("vision")),
                "audio": bool(mods.get("audio")),
                "video": bool(mods.get("video")),
            }
    except Exception:  # noqa: BLE001 - 探测失败不是错误，回退到配置推断
        return None
    return None

def _lmstudio_vision(spec) -> Optional[bool]:
    """向 LMStudio 询问该模型是否支持图像输入。

    LMStudio 的 /props 返回 architecture.input_modalities，例如
        ["text", "image"]  → 支持视觉
    探测失败返回 None（交由后续回退决定）。
    """
    base_url = getattr(spec, "base_url", None)
    target = getattr(spec, "remote_model_name", None) or getattr(spec, "name", None)
    if not base_url or not target:
        return None
    # 该 base_url 上没有服务时直接跳过：否则同一端口下的每个模型都要各等一次超时
    if not _endpoint_reachable(base_url):
        return None
    try:
        from infra.orchestrator.base import local_probe_session
        resp = local_probe_session().get(
            f"{base_url.rstrip('/')}/props",
            params={"model": target},
            timeout=_MODALITY_PROBE_TIMEOUT_S,
        )
        if resp.status_code != 200:
            return None
        arch = (resp.json() or {}).get("architecture") or {}
        mods = arch.get("input_modalities")
        if isinstance(mods, list):
            return any(str(x).lower() in ("image", "vision") for x in mods)
    except Exception:  # noqa: BLE001
        return None
    return None


def _configured_vision(spec) -> bool:
    """从模型配置/上游推断是否支持视觉输入。

    依据（按可靠性排序）：
      1. llama.cpp 配置里有 mmproj_path → 挂了视觉投影器，必然支持图像；
      2. LMStudio 上游 /props 的 input_modalities（真实上报）；
      3. provider 显式声明（x-dsn-vision）——用于无法探测的远端 API；
      4. 其它情况视为纯文本。
    """
    cfg = getattr(spec, "llama_config", None)
    if cfg is not None and getattr(cfg, "mmproj_path", None):
        return True

    source_type = getattr(getattr(spec, "source_type", None), "value", "")
    if source_type == "api_lmstudio":
        probe = _lmstudio_vision(spec)
        if probe is not None:
            return probe

    extra = getattr(spec, "extra_headers", None)
    if isinstance(extra, dict) and extra.get("x-dsn-vision") == "true":
        return True
    return False

def _modalities_dict(model_name: Optional[str], orchestrator) -> dict:
    """把输入模态转成前端需要的 {"vision","audio","video"} 结构。"""
    mods = _input_modalities(model_name or "", orchestrator) if model_name else ["text"]
    return {
        "vision": "vision" in mods,
        "audio": "audio" in mods,
        "video": "video" in mods,
    }


def _normalize_request_tools(raw: Any) -> Optional[list]:
    """把请求里的 OpenAI tools 归一化成 harness 需要的 function 结构。

    接受两种写法：
      [{"type": "function", "function": {...}}]   ← OpenAI 标准
      [{"name": ..., "description": ..., "parameters": ...}]  ← 裸 function

    返回 None 表示没有可用工具（保持"未传 tools"的语义，避免空列表
    把调用方误判成"声明了 0 个工具"）。
    """
    if not isinstance(raw, (list, tuple)) or not raw:
        return None

    out: list = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        fn = item.get("function") if item.get("type") == "function" else item
        if isinstance(fn, dict) and fn.get("name"):
            out.append(fn)
    return out or None


def _normalize_tool_call_deltas(raw: Any) -> list:
    """把上游的扁平工具调用增量转成标准 OpenAI 形状。

    上游（llama-server / Strata）流式给出的是：
        {"index": 0, "id": "...", "name": "get_weather", "arguments": "{\"city\":"}
    而标准 OpenAI 增量要求：
        {"index": 0, "id": "...", "type": "function",
         "function": {"name": "get_weather", "arguments": "{\"city\":"}}

    按协议解析的消费方（OpenAI SDK / LangChain / Cline / Continue，以及本仓库
    自己的前端 mergeToolCallDeltas）只读 delta.function.name / .arguments，
    扁平结构会被静默忽略 —— 这正是"模型调不了工具"的直接原因。
    """
    out: list = []
    for tc in raw or []:
        if not isinstance(tc, dict):
            continue
        item: dict = {"index": tc.get("index", 0) or 0}
        if tc.get("id"):
            item["id"] = tc["id"]
            item["type"] = "function"
        fn: dict = {}
        if tc.get("name"):
            fn["name"] = tc["name"]
        fn["arguments"] = tc.get("arguments", "") or ""
        item["function"] = fn
        out.append(item)
    return out


def _timing_totals(t: dict) -> tuple[int, int, int, int, float, float]:
    """拆解 llama-server 的 timings，返回 (prompt_n, cache_n, total, predicted_n, prompt_ms, predicted_ms)。

    **关键语义**（容易搞错）：llama.cpp 的 timings 里
        prompt_n  是本轮**实际评估**的 token 数（缓存未命中的部分）
        cache_n   是**复用前缀缓存**的 token 数
    因此完整 prompt 长度 = prompt_n + cache_n。
    直接拿 cache_n / prompt_n 当命中率会得到 >100% 的荒谬值
    （实测 cache_n=79、prompt_n=4 → 1975%）。
    """
    t = t or {}
    prompt_n = int(t.get("prompt_n") or 0)
    cache_n = int(t.get("cache_n") or 0)
    predicted_n = int(t.get("predicted_n") or 0)
    prompt_ms = float(t.get("prompt_ms") or 0)
    predicted_ms = float(t.get("predicted_ms") or 0)
    return prompt_n, cache_n, prompt_n + cache_n, predicted_n, prompt_ms, predicted_ms


def _openai_usage_from_timings(t: dict) -> dict:
    """llama-server 的 timings → 标准 OpenAI usage（含缓存命中）。

    字段对应关系：
        完整 prompt = prompt_n + cache_n  → prompt_tokens
        predicted_n                       → completion_tokens
        cache_n                           → prompt_tokens_details.cached_tokens

    另外附 cache_hit_rate —— 标准字段里没有"命中百分比"，客户端想显示就得自己算。
    """
    prompt_n, cache_n, total_prompt, predicted_n, _, _ = _timing_totals(t)

    usage: dict = {
        "prompt_tokens": total_prompt,
        "completion_tokens": predicted_n,
        "total_tokens": total_prompt + predicted_n,
    }
    if total_prompt > 0:
        usage["prompt_tokens_details"] = {
            "cached_tokens": cache_n,
            # 缓存命中率（0~1）：复用部分 / 完整 prompt
            "cache_hit_rate": round(cache_n / total_prompt, 4),
        }
    return usage


def _dsn_usage_extras(t: dict) -> dict:
    """DSN 扩展用量块：缓存命中百分比 + 读写耗时（标准 usage 放不下）。

    百分比口径与前端 context-stats 保持一致：
        完整 prompt = prompt_n + cache_n
        cache_hit_rate  = cache_n / 完整 prompt     （复用比例）
        prompt_read_rate = prompt_n / 完整 prompt   （真正需要读取/预填充的比例）
    """
    prompt_n, cache_n, total_prompt, predicted_n, prompt_ms, predicted_ms = _timing_totals(t)
    return {
        "prompt_tokens": total_prompt,
        "prompt_evaluated_tokens": prompt_n,
        "predicted_tokens": predicted_n,
        "cached_tokens": cache_n,
        "cache_hit_rate": round(cache_n / total_prompt, 4) if total_prompt else 0.0,
        "prompt_read_rate": round(prompt_n / total_prompt, 4) if total_prompt else 0.0,
        "prompt_ms": prompt_ms,
        "predicted_ms": predicted_ms,
        "prompt_tokens_per_second": round(prompt_n / (prompt_ms / 1000), 2) if prompt_ms > 0 else 0.0,
        "predicted_tokens_per_second": round(predicted_n / (predicted_ms / 1000), 2) if predicted_ms > 0 else 0.0,
    }


def _modalities_from_flags(flags: dict) -> list[str]:
    """{"vision":..,"audio":..,"video":..} → ["text", ...]（顺序稳定）。"""
    out = ["text"]
    if flags.get("vision"):
        out.append("vision")
    if flags.get("audio"):
        out.append("audio")
    if flags.get("video"):
        out.append("video")
    return out


def _input_modalities(model_name: str, orchestrator) -> list[str]:
    """返回模型的输入模态列表（供前端判断能否发送图片）。

    **热路径**：/models、/v1/models、/props 都会逐模型调用它，因此这里必须
    避免每次都发阻塞 HTTP 探测。策略：
      1. 命中 TTL 缓存直接返回（正负结果都缓存，未加载模型不再反复探测）；
      2. 只对**确实在运行**的本地引擎探测其 /props（最权威）；
      3. 其余情况用配置推断（mmproj_path / x-dsn-vision / LMStudio 上报）。
    """
    now = time.monotonic()
    cached = _modality_cache.get(model_name)
    if cached is not None and (now - cached[0]) < _MODALITY_CACHE_TTL_S:
        return _modalities_from_flags(cached[1])

    spec = orchestrator.get_model_spec(model_name)

    # 1) 优先用运行中服务的真实上报（最可靠）
    probed = _probe_server_modalities(model_name, spec)
    if probed is not None:
        _modality_cache[model_name] = (now, probed)
        return _modalities_from_flags(probed)

    # 2) 回退到配置推断。无论结果如何都写入缓存 —— 负结果同样要缓存，
    #    否则「探测失败 → 不缓存 → 下次再探测」会让列表接口每次都变慢。
    flags = {"vision": bool(_configured_vision(spec)), "audio": False, "video": False}
    _modality_cache[model_name] = (now, flags)
    return _modalities_from_flags(flags)


def _extract_last_user_text(messages_raw: Optional[list]) -> str:
    """取最后一条 user 消息的纯文本（多模态 content parts 时拼接 text 部分）。"""
    for m in reversed(messages_raw or []):
        if not isinstance(m, dict) or m.get("role") != "user":
            continue
        content = m.get("content")
        if isinstance(content, list):
            return " ".join(
                str(p.get("text") or "") for p in content
                if isinstance(p, dict) and p.get("type") == "text"
            ).strip()
        return str(content or "").strip()
    return ""


def _apply_thought_cache_recommendation(engine, messages_raw: list) -> Optional[str]:
    """生成「思路模板推荐」块（按逐字匹配百分比排序的 top-N 缓存结果）。

    用户要求：不要依赖模型主动调用 cache.recall —— 每轮直接把缓存结果推给 AI。
    服务不可用 / 关闭 / 无命中时返回 None，请求路径与今天完全一致。
    """
    try:
        svc = getattr(engine, "thought_cache", None)
        if svc is None:
            return None
        query = _extract_last_user_text(messages_raw)
        if not query:
            return None
        return svc.build_recommendation_block(query) or None
    except Exception as e:  # noqa: BLE001 - 推荐失败绝不能影响对话
        logger.warning("生成思路模板推荐失败（忽略）: %s", e)
        return None


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

    # ── 外周资源池（ASR / TTS）──
    # 资源池此前只在 apps/dsn/boot.py（Flask 进程）里创建，而本页面由另一个
    # FastAPI 进程服务 —— 该进程从不导入 apps.dsn.models.resource_setup，
    # 于是「外周任务槽」永远是空的。这里幂等地装配一次（setup_dsn_resources
    # 可安全重复调用），并把池挂到 engine 上供各 /api/resources/* 接口使用。
    # try/except 兜底：装配失败（缺依赖 / TTS 预检不过）绝不能阻塞 UI 启动。
    try:
        from apps.dsn.models import resource_setup

        engine.resource_pool = resource_setup.setup_dsn_resources()
        logger.info(
            "外周资源池已装配: %s",
            [r.get("name") for r in engine.resource_pool.list_resources()],
        )
    except Exception as e:  # noqa: BLE001
        engine.resource_pool = None
        log_exception(logger, "装配外周资源池失败（外周功能不可用）", e)

    # 注册 Orchestrator 状态变化回调，打通 SSE 广播
    def _schedule_broadcast(event: str, model: str, payload: dict) -> None:
        """把一次 SSE 广播投递到事件循环（可在任意线程调用）。

        模型加载有两条路：
          * UI 点「加载」→ 走 asyncio.to_thread；
          * 请求时自动拉起（重试历史消息等）→ 也在工作线程里。
        两者都不在事件循环线程上，直接 asyncio.create_task 会失败，
        状态事件就会静默丢失，前端永远等不到 loading/loaded。
        """
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None

        if running is not None:
            asyncio.create_task(sse_broadcaster.broadcast(event, model, payload))
            return

        target = _event_loop_holder.get("loop")
        if target is not None and target.is_running():
            asyncio.run_coroutine_threadsafe(
                sse_broadcaster.broadcast(event, model, payload), target
            )

    def _on_orchestrator_status_change(model_name: str, status: str, extra: dict):
        data_payload = {"status": status}
        if "error" in extra:
            data_payload["exit_code"] = 1
            data_payload["error"] = extra["error"]
        if "progress" in extra:
            data_payload["progress"] = extra["progress"]

        logger.info(
            "模型状态变更: %s → %s%s",
            model_name, status,
            f" ({extra['error']})" if extra.get("error") else "",
        )
        _schedule_broadcast(f"status_{status}", model_name, data_payload)
        _schedule_broadcast("status_change", model_name, data_payload)

    engine.orchestrator.add_status_listener(_on_orchestrator_status_change)

    # ── 思考链缓存（思路模板）──
    # 单后台守护线程串行蒸馏；/v1/chat/completions 在轮次结束后只做入队，
    # 不阻塞/不延迟 HTTP 响应。服务失败绝不能阻塞 UI 启动。
    try:
        from apps.dsn_ui.thought_cache import ThoughtCacheService

        engine.thought_cache = ThoughtCacheService(
            orchestrator=engine.orchestrator, settings=engine.agent,
        )

        #: 正在进行中的聊天流（conv_id -> 同步 emit 回调）。
        #: 缓存蒸馏在工作线程里跑，因此这里必须是线程安全 + 非阻塞的。
        _chat_stream_sinks: Dict[str, Any] = {}
        _chat_stream_sinks_lock = threading.Lock()

    except Exception as e:  # noqa: BLE001
        engine.thought_cache = None
        log_exception(logger, "初始化思考链缓存失败（功能不可用）", e)
        _chat_stream_sinks = {}                      # noqa: F841 - 兜底占位
        _chat_stream_sinks_lock = threading.Lock()   # noqa: F841

    if getattr(engine, "thought_cache", None) is not None:
        def _emit_thought_cache(payload: dict) -> None:
            """把 {state,message_id,conv_id,count,queue_depth} 同时投递到：

              1) **本轮聊天 SSE 流**（/v1/chat/completions）—— UI 在对话期间正
                 在消费这条流，因此「缓存思路中」能立刻可见（BUG 3 的修复）；
              2) /models/sse 状态流 —— 作为兜底（对话流已关闭时仍然可见）。

            可能来自工作线程，因此两路都必须线程安全且绝不阻塞。
            """
            data = dict(payload)
            try:
                conv_id = str(data.get("conv_id") or "")
                with _chat_stream_sinks_lock:
                    sink = _chat_stream_sinks.get(conv_id)
                if sink is not None:
                    sink(data)
            except Exception as e:  # noqa: BLE001 - 聊天流投递失败不应影响其它订阅者
                logger.debug("投递 thought_cache 到聊天流失败: %s", e)
            try:
                _schedule_broadcast(
                    "thought_cache", str(data.get("message_id") or ""), data
                )
            except Exception as e:  # noqa: BLE001
                log_exception(logger, "广播 thought_cache 事件失败", e)

        # emitter 必须**在 start() 之前**装好：否则 worker 可能在第一件任务上
        # 抢跑，导致首个 queued/running 事件丢失。
        engine.thought_cache.set_emitter(_emit_thought_cache)
        engine.thought_cache.start()
        # 把服务注入工具系统，使 cache.recall 能检索本服务。
        try:
            engine.agent.tool_coordinator.set_thought_cache(engine.thought_cache)
        except Exception as e:  # noqa: BLE001
            log_exception(logger, "注入思考链缓存到工具系统失败", e)

    def _enqueue_thought_cache(*, conv_id: str, message_id: str, user_text: str,
                               tool_calls: list, tool_results: list, reply: str,
                               model: str) -> None:
        """轮次结束后把上下文 + 工具链交给思考链缓存蒸馏（仅入队，立即返回）。"""
        try:
            svc = getattr(engine, "thought_cache", None)
            if svc is None or not tool_calls:
                return
            by_call = {
                str(r.get("call_id")): r
                for r in (tool_results or []) if isinstance(r, dict)
            }
            chain_lines: List[str] = []
            for i, call in enumerate(tool_calls):
                if not isinstance(call, dict):
                    continue
                name = call.get("name") or "?"
                args = call.get("arguments")
                if not isinstance(args, str):
                    try:
                        args = json.dumps(args, ensure_ascii=False)
                    except Exception:  # noqa: BLE001
                        args = str(args)
                chain_lines.append(f"[tool] {name}({args})")
                res = by_call.get(str(call.get("id"))) or (
                    tool_results[i] if i < len(tool_results or []) else None
                )
                if isinstance(res, dict):
                    out = res.get("output")
                    if not isinstance(out, str):
                        try:
                            out = json.dumps(out, ensure_ascii=False)
                        except Exception:  # noqa: BLE001
                            out = str(out)
                    chain_lines.append(
                        f"[result] success={res.get('success')} {str(out)[:800]}"
                    )
            context = f"用户请求: {user_text or '(未知)'}\n\n最终回复: {reply or ''}"
            job_id = svc.enqueue_distill(
                conv_id=conv_id,
                message_id=message_id,
                context=context,
                chain="\n".join(chain_lines),
                model=model,
            )
            if job_id:
                logger.info(
                    "已入队思路蒸馏: conv=%s job=%s tools=%d",
                    conv_id, job_id, len(tool_calls),
                )
        except Exception as e:  # noqa: BLE001 - 入队失败绝不能影响对话
            logger.warning("入队思路蒸馏失败: %s", e)

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

        # 记录事件循环：状态回调可能来自工作线程（自动拉起模型），
        # 需要用 run_coroutine_threadsafe 才能把 SSE 投递回来。
        _event_loop_holder["loop"] = asyncio.get_running_loop()

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
            try:
                if getattr(engine, "thought_cache", None) is not None:
                    engine.thought_cache.shutdown()
            except Exception as e:  # noqa: BLE001 - 关闭失败不得阻塞退出
                log_exception(logger, "关闭思考链缓存失败", e)
            engine.orchestrator.shutdown()

    app = FastAPI(title="DSN-exp UI & Model Orchestrator", version="1.0.0", lifespan=lifespan)
    # 与 engine.resource_pool 指向同一实例，供 asr_api 等独立模块取用。
    app.state.resource_pool = getattr(engine, "resource_pool", None)

    # CORS 策略。
    #
    # 修复说明：原先是 allow_origins=["*"] 且 allow_credentials=True。
    # 这是浏览器安全模型下的危险组合——服务默认监听 0.0.0.0，同网段任意
    # 网页都能跨域调用本机接口（含 /tools 的工具执行）。而且带凭据的 "*"
    # 在 CORSMiddleware 里会被回显成请求方 Origin，等同于完全放开。
    #
    # 现在默认只允许本机来源；确需远程访问时用
    # DSN_UI_CORS_ORIGINS 显式列出（逗号分隔），并保持凭据关闭。
    _cors_env = (os.getenv("DSN_UI_CORS_ORIGINS") or "").strip()
    if _cors_env:
        _cors_origins = [o.strip() for o in _cors_env.split(",") if o.strip()]
    else:
        _cors_origins = [
            "http://127.0.0.1", "http://localhost",
            "http://127.0.0.1:8888", "http://localhost:8888",
        ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=False,
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
            # 模态来自目标模型的真实能力，不能写死：
            # 之前恒为 vision/audio=true，会让前端以为所有模型都能收图，
            # 从而把图片发给纯文本模型（或反向误判）。
            "modalities": _modalities_dict(target_model, engine.orchestrator),
            "ui_settings": {
                "theme": "dark",
                "showBuildVersion": True,
            }
        }

    # ── 2. llama-ui /models 及 /v1/models 端点 ──

    def _provider_id_for(label: Optional[str]) -> Optional[str]:
        """按 provider 展示名反查其 id（供前端从模型行跳转到「管理」面板）。

        provider 的明文名单里 label 是唯一的展示名；重名时取第一个。
        查不到（provider 已被删除但注册残留）返回 None。
        """
        if not label:
            return None
        try:
            for p in engine.provider_store.list():
                if (p.get("label") or "") == label:
                    return p.get("id")
        except Exception as e:  # noqa: BLE001 - 反查失败不应影响模型列表
            logger.debug("反查 provider id 失败 label=%s: %s", label, e)
        return None

    def _build_model_entries() -> list[dict]:
        status = engine.orchestrator.status()
        entries = []
        now = int(time.time())
        for m in status.get("models", []):
            is_loaded = m["loaded"]
            is_loading = m.get("is_loading", False)
            status_val = "loading" if is_loading else ("loaded" if is_loaded else "unloaded")
            # source_type 已由 orchestrator.status() 导出；provider_label 只在
            # ModelSpec 上（status() 未导出它，router.py 不在本任务写范围内），
            # 因此这里从 spec 防御性读取：本地模型得到 None，第三方 API 模型
            # 得到其 provider 展示名，供前端加来源徽标。
            _model_spec = engine.orchestrator.get_model_spec(m["name"])
            # 第三方 API 模型：前端需要 provider_id 才能从资源页跳到「管理」
            # 面板去编辑（载入显存/释放显存对它毫无意义）。
            _provider_label = getattr(_model_spec, "provider_label", None)
            _is_api_model = m.get("source_type") == "api_openai"
            _provider_id = _provider_id_for(_provider_label) if _is_api_model else None
            entries.append({
                "id": m["name"],
                "name": m["name"],
                "object": "model",
                "source_type": m.get("source_type"),
                "provider_label": _provider_label,
                # API 模型没有「本地加载」的概念：显式告诉前端，避免资源页
                # 渲染出「载入显存 / 释放显存」这种对云端模型没有意义的按钮。
                "is_api_model": _is_api_model,
                "always_ready": _is_api_model,
                "provider_id": _provider_id,
                # owned_by 直接取引擎名：llama.cpp 与 Strata 都是本地托管引擎，
                # 前端/客户端靠它区分是哪一套引擎在跑这个模型。
                "owned_by": (m.get("engine") or m["source_type"]) if m["is_local"] else m["source_type"],
                "created": now,
                "in_cache": True,
                "path": m.get("command") or f"models/{m['name']}.gguf",
                "status": {
                    "value": status_val,
                    "args": [m["command"]] if m.get("command") else [],
                },
                "architecture": {
                    # 输入模态必须来自**模型真实配置**，不能靠名字猜。
                    # 历史实现用 'ocr' in name or 'v' in name 判断，
                    # 于是 bonsai:bonsai2:27B（带 mmproj 视觉投影器）被误判为
                    # 纯文本 → 前端在发送前把 image_url 内容块全部剥离，
                    # 表现为"模型说没收到图片附件"。
                    "input_modalities": _input_modalities(m["name"], engine.orchestrator)
                },
                "meta": {
                    "n_ctx": engine.orchestrator.get_model_ctx_size(m["name"]),
                    "priority": m["priority"],
                    "resident": m["resident"],
                    "immediate": m["immediate"],
                    "engine": m.get("engine"),
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

    def _reject_if_api_model(model_id: str, action: str) -> Optional[JSONResponse]:
        """第三方 API 模型不接受本地装载/卸载。

        它们运行在远端，永远可用：既没有本地子进程，也不占显存。
        历史实现会一路走到 orchestrator.load_model 的兜底分支，返回
        "loaded" —— 而卸载则返回 "unloaded" 却什么都没做。前端据此把模型
        标记成未加载，于是模型名与发送键变红显示 not available，
        但请求其实完全能用。这里直接回 409 + 明确原因，让前端知道这是
        无意义操作而不是失败。
        """
        spec = engine.orchestrator.get_model_spec(model_id)
        if spec is None:
            return None
        if getattr(spec, "source_type", None) == ModelSourceType.API_OPENAI:
            return JSONResponse(
                status_code=409,
                content={
                    "error": f"第三方 API 模型不支持{action}：它运行在远端，始终可用",
                    "model": model_id,
                    "status": "loaded",
                    "always_ready": True,
                },
            )
        return None

    @app.post("/models/load")
    async def load_model(req: Request):
        body = await req.json()
        model_id = body.get("model")
        if not model_id:
            raise HTTPException(status_code=400, detail="Missing 'model' field")
        _rejected = _reject_if_api_model(model_id, "载入显存")
        if _rejected is not None:
            return _rejected
        logger.info("UI 请求加载模型: %s", model_id)
        try:
            ok = await asyncio.to_thread(engine.orchestrator.load_model, model_id)
            if ok:
                await sse_broadcaster.broadcast("status_loaded", model_id, {"status": "loaded"})
                await sse_broadcaster.broadcast("status_change", model_id, {"status": "loaded"})
                return {"success": True, "model": model_id, "status": "loaded"}
            else:
                # 区分「用户主动终止」与「真的启动失败」：前者不是错误，必须以
                # unloaded 收尾，否则前端会一直停在 loading 转圈上。
                cancelled = False
                try:
                    _spec = engine.orchestrator.get_model_spec(model_id)
                    _launcher = getattr(_spec, "launcher", None)
                    cancelled = bool(_launcher is not None and _launcher.cancel_requested)
                except Exception:  # noqa: BLE001 - 判定失败按普通失败处理
                    cancelled = False

                if cancelled:
                    logger.info("模型 %s 的加载已被用户终止", model_id)
                    await sse_broadcaster.broadcast("status_unloaded", model_id, {"status": "unloaded"})
                    await sse_broadcaster.broadcast("status_change", model_id, {"status": "unloaded"})
                    return JSONResponse(
                        status_code=409,
                        content={
                            "error": "加载已取消",
                            "model": model_id,
                            "status": "unloaded",
                            "cancelled": True,
                        },
                    )

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
        # 对 API 模型「释放显存」会广播 status_unloaded，前端随即把它判为
        # 不可用（模型名与发送键变红）。云端模型没有显存可释放，直接拒绝。
        _rejected = _reject_if_api_model(model_id, "释放显存")
        if _rejected is not None:
            return _rejected
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

        # ── 思路模板自动推荐（用户要求：直接推 top-3 给 AI，不等模型调用工具）──
        # 作为**最高层 system 消息**注入：话题记忆装配、超驰、passthrough 与
        # 客户端工具模式都会把它放在上下文最前。只读缓存一次，绝不阻塞。
        _tc_block = _apply_thought_cache_recommendation(engine, messages_raw)
        if _tc_block:
            messages_raw = [{"role": "system", "content": _tc_block}] + list(messages_raw)
            logger.info(
                "已注入思路模板推荐: %d chars, 模板数=%d",
                len(_tc_block), _tc_block.count("(相似度"),
            )

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

        # ── 多模态入口追踪 ──
        # 这里是浏览器 → 后端的第一个落点。若这里就看不到 image_url，
        # 说明问题在前端（附件没被序列化进 content parts）；
        # 若这里看得到、下游某层变成 0，问题就在那一层。
        _inbound_images = count_image_parts(messages_raw)
        if _inbound_images or any(
            isinstance(m.get("content"), (list, tuple)) for m in messages_raw
        ):
            logger.info(
                "多模态入站: model=%s messages=%d images=%d 形状=%s",
                model_name,
                len(messages_raw),
                _inbound_images,
                [f"{m.get('role')}:{content_shape(m.get('content'))}" for m in messages_raw],
            )
            logger.debug(
                "多模态入站原始 content 类型: %s",
                [type(m.get("content")).__name__ for m in messages_raw],
            )

        # ── 请求方声明的工具（标准 OpenAI function calling）──
        # body.tools 形如 [{"type":"function","function":{name,description,parameters}}]，
        # harness 内部只需要里面的 function 对象。历史实现完全没有读取它，
        # 于是 API 客户端（以及本仓库 UI 的 MCP 工具）声明的工具模型根本看不到。
        client_tools = _normalize_request_tools(body.get("tools"))

        # ── API 模式：dsn（完整 DSN-exp）| passthrough（完全交给请求方）──
        # 由应用配置决定；配置里锁定时忽略请求方覆盖。
        api_mode = UIConfig.resolve_api_mode(
            body.get("api_mode")
            or req.query_params.get("api_mode")
            or req.headers.get("X-DSN-Api-Mode")
        )

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
        # 修复说明：以下三处参数原先直接 int()，字符串/布尔值（如
        # {"max_tokens": "abc"} 或 {"max_tokens": true}）会抛 ValueError/TypeError
        # 一路冒泡成 500。统一改为宽容解析：非法值退回默认行为，不再打挂服务。
        def _coerce_int(value: Any) -> Optional[int]:
            """把请求里的数值参数宽容地转成 int；无法解析返回 None。"""
            if value is None or isinstance(value, bool):
                return None
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        req_tokens = _coerce_int(body.get("max_tokens") or body.get("n_predict"))
        # 不再把 4096 当"未指定"的哨兵：那是魔法值，调用方显式要求 4096 会被
        # 静默改成 None。现在只有 None/非正数才走按比例预留。
        if req_tokens is None or req_tokens <= 0:
            # 不直接取满上下文：输入本身要占 token，若 max_tokens == ctx_size
            # 则 input+output > ctx，llama-server 直接 500。
            # 交给 agent 统一按比例预留（见 _resolve_max_tokens），这里传 None。
            effective_max_tokens = None
        else:
            effective_max_tokens = req_tokens

        # 支持请求中透传的 Agent 最大迭代步数与工具截断字符数
        raw_max_steps = _coerce_int(
            body.get("max_steps") or body.get("agent_max_steps") or body.get("agentic_max_turns")
        )
        effective_max_steps = raw_max_steps if raw_max_steps is not None and raw_max_steps >= 0 else None

        raw_tool_chars = _coerce_int(
            body.get("tool_max_output_chars") or body.get("dsn_tool_max_output_chars")
        )
        if raw_tool_chars is not None and raw_tool_chars > 0:
            engine.agent.set_tool_max_output_chars(raw_tool_chars)

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
                api_mode=api_mode,
                client_tools=client_tools,
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

            # 工具调用必须按标准 OpenAI 形状回传，否则客户端不知道要执行什么。
            tool_calls = [
                {
                    "id": tc.id or f"call_{i}",
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments or {}, ensure_ascii=False),
                    },
                }
                for i, tc in enumerate(getattr(resp, "tool_calls", None) or [])
            ]
            message: dict = {
                "role": "assistant",
                "content": resp.content,
                "reasoning_content": resp.reasoning_content,
            }
            if tool_calls:
                message["tool_calls"] = tool_calls
            finish_reason = resp.finish_reason or ("tool_calls" if tool_calls else "stop")

            # 本地引擎通常只回 timings 不回 usage，这里补一次映射，
            # 让非流式客户端同样能拿到 token 数与缓存命中。
            usage = resp.usage or {}
            if not usage.get("prompt_tokens"):
                try:
                    _client = engine.orchestrator.get_client(model_name)
                    _t = getattr(_client, "last_timings", None)
                    if isinstance(_t, dict) and _t:
                        usage = _openai_usage_from_timings(_t)
                except Exception:  # noqa: BLE001 - 取不到用量不影响正常返回
                    usage = {}
            if not usage:
                usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

            return {
                "id": f"chatcmpl-dsn-{int(time.time())}",
                "object": "chat.completion",
                "model": model_name,
                "choices": [{
                    "index": 0,
                    "message": message,
                    "finish_reason": finish_reason,
                }],
                "usage": usage,
            }

        async def _produce_sse(session, conv_id: str):
            """后台生产者：消费 AgentLoop 事件并写入流会话缓冲。

            与 HTTP 连接完全解耦——客户端断开只会停止"读取"，
            本协程继续把推理结果写入 session.buffer，供后续重连回放。
            """

            def emit(raw: str) -> None:
                """把一段 SSE 文本追加进会话缓冲（同步，无 await 依赖）。

                蒸馏/缓存事件来自其它线程（工作线程），因此这里加锁：session
                的缓冲是共享对象，必须避免与事件循环线程并发写坏。
                """
                with _emit_lock:
                    session.append(raw.encode("utf-8"))

            #: 缓存事件推送用的锁（工作线程也会调用 emit）。
            _emit_lock = threading.Lock()
            #: 本流的缓存事件接收器状态：
            #:   active —— 是否仍属于当前正在运行的流（旧的接收器必须失效，
            #:             否则后续轮次的事件会写进已关闭的会话，UI 永远看不到）；
            #:   seal_requested —— 推理已结束，等待把 done/error 一起封口；
            #:   sealed —— 会话已 finish()，之后一律不再尝试写入。
            _sink_state = {"active": True, "seal_requested": False, "sealed": False}
            #: 封口前暂存的缓存帧（工作线程可能随时写入）。
            _cache_pending: list = []
            _cache_pending_lock = threading.Lock()

            def _cache_frame(payload: dict) -> str:
                """把缓存事件编码成显式 type 的 SSE 帧（字段冻结）。"""
                frame = {
                    "type": "thought_cache",
                    "state": payload.get("state"),
                    "message_id": payload.get("message_id", ""),
                    "conv_id": payload.get("conv_id", ""),
                    "count": payload.get("count", 0),
                    "queue_depth": payload.get("queue_depth", 0),
                }
                return "data: " + json.dumps(frame, ensure_ascii=False) + "\n\n"

            def _emit_thought_cache_frame(payload: dict) -> None:
                """把缓存生命周期作为显式 type 的帧写进本轮聊天流（非阻塞）。"""
                if not _sink_state["active"]:
                    return
                try:
                    line = _cache_frame(payload)
                except Exception as e:  # noqa: BLE001 - 事件失败不得影响推理
                    logger.debug("构造 thought_cache 帧失败: %s", e)
                    return
                with _cache_pending_lock:
                    if _sink_state["sealed"]:
                        logger.debug(
                            "会话已封口，跳过聊天流缓存帧 state=%s（改由 /models/sse 送达）",
                            payload.get("state"),
                        )
                        return
                    if _sink_state["seal_requested"]:
                        _cache_pending.append(line)
                        logger.debug("缓存帧暂存待补发: state=%s", payload.get("state"))
                        return
                    emit(line)

            with _chat_stream_sinks_lock:
                _chat_stream_sinks[conv_id] = _emit_thought_cache_frame

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
                #: 最近一次真实用量（llama-server timings / usage），
                #: 用于在终态块里给出标准 OpenAI usage + 缓存命中信息。
                last_timings: Dict[str, Any] = {}
                #: 终态块里是否已经带上了 usage（避免重复下发）
                terminal_carried_usage = False
                agen = engine.agent.chat_stream(
                    messages_raw=messages_raw,
                    model_name=model_name,
                    temperature=temperature,
                    execution_mode=execution_mode,
                    system_prompt_override=custom_system_prompt if system_prompt_override else None,
                    max_tokens=effective_max_tokens,
                    max_steps=effective_max_steps,
                    api_mode=api_mode,
                    client_tools=client_tools,
                )
                # 标准 OpenAI chunk 信封。所有 delta 都必须包在
                # {"choices":[{"index":0,"delta":{...}}]} 里，且带 object/created/model，
                # 否则严格客户端无法解析（部分库直接报错或丢弃整个流）。
                _chunk_seq = 0
                # 是否已下发过标准终态块（choices[0].finish_reason）。
                # 循环结束后若仍为 False，会补发一个 stop 终态块兜底。
                terminal_sent = False

                def emit_openai_delta(delta: dict, finish_reason=None) -> None:
                    nonlocal _chunk_seq
                    _chunk_seq += 1
                    emit("data: " + json.dumps({
                        "id": f"chatcmpl-dsn-{int(time.time() * 1000)}-{_chunk_seq}",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": model_name,
                        "choices": [{
                            "index": 0,
                            "delta": delta,
                            "finish_reason": finish_reason,
                        }],
                    }, ensure_ascii=False) + "\n\n")

                # 思考链缓存采集：本轮的最终文本 + 工具调用/结果，仅供轮次结束后
                # 异步入队蒸馏（见下方 _enqueue_thought_cache）。
                tc_reply_parts: List[str] = []
                tc_tool_calls: List[dict] = []
                tc_tool_results: List[dict] = []

                async for chunk in agen:
                    chunk_count += 1
                    ctype = chunk.get("type")
                    ctype_counts[ctype] = ctype_counts.get(ctype, 0) + 1
                    if ctype == "delta":
                        tc_reply_parts.append(chunk.get("content") or "")
                    elif ctype == "tool_call":
                        tc_tool_calls.append(chunk.get("tool_call") or {})
                    elif ctype == "tool_result":
                        tc_tool_results.append(chunk.get("tool_result") or {})
                    # 逐事件调试日志：能用 DSN_UI_LOG_LEVEL=DEBUG 打开，
                    # 精确定位是「哪一类事件之后」开始出问题。
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "SSE chunk #%d type=%s keys=%s",
                            chunk_count, ctype, sorted(chunk.keys()),
                        )
                    if ctype in ("timings", "usage"):
                        provider_sent_timings = True
                        # 记下最近一次真实用量：终态块要用它生成标准 OpenAI
                        # usage（含缓存命中），供 API 客户端读取。
                        _t = chunk.get("timings") or chunk.get("usage") or {}
                        if isinstance(_t, dict) and _t:
                            last_timings.update(_t)
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
                        # agent 侧无论 timings 还是 usage 事件都把负载放在
                        # "timings" 键下，历史实现只取 chunk["usage"]，于是这里
                        # 永远发出一个空的 {"usage": {}}。
                        raw_usage = chunk.get("usage") or chunk.get("timings") or {}
                        payload = {
                            "usage": _openai_usage_from_timings(raw_usage),
                            "dsn_usage": _dsn_usage_extras(raw_usage),
                        }
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
                        # 终态块：必须用 **标准 OpenAI chunk 形状**下发
                        # choices[0].finish_reason，否则严格客户端（OpenAI SDK、
                        # LangChain、Continue、Cline…）会报
                        # "Stream ended without finish_reason"。
                        #
                        # 历史实现把 finish_reason 放在**顶层**，不符合协议
                        # ——客户端只读 choices[0].finish_reason，因此永远拿不到。
                        #
                        # 同时补上 object/created/model/id 等标准字段，并把
                        # DSN 扩展（步数收束提示）放进 delta 之外的自定义键，
                        # 不影响严格客户端解析。
                        hit_max = bool(chunk.get("hit_max"))
                        terminal_sent = True
                        # 模型返回过工具调用时必须以 tool_calls 收尾，否则客户端
                        # 会当成普通回复，永远不去执行工具。
                        finish_reason = (
                            chunk.get("finish_reason")
                            or ("length" if hit_max else "stop")
                        )
                        payload = {
                            "id": f"chatcmpl-dsn-{int(time.time() * 1000)}",
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": model_name,
                            "choices": [{
                                "index": 0,
                                "delta": {},
                                "finish_reason": finish_reason,
                            }],
                            # DSN 扩展（非标准字段，放在顶层，严格客户端会忽略）
                            "hit_max_steps": hit_max,
                            "round": chunk.get("round"),
                        }
                        # 把用量挂在终态块上：这样**所有**客户端都能直接拿到，
                        # 不需要额外的 choices:[] 块（llama-server 也是这么做的）。
                        if last_timings:
                            payload["usage"] = _openai_usage_from_timings(last_timings)
                            payload["dsn_usage"] = _dsn_usage_extras(last_timings)
                            payload["timings"] = last_timings
                            terminal_carried_usage = True
                        emit(f"data: {json.dumps(payload, ensure_ascii=False)}\n\n")
                        continue
                    # 以下全部经由 emit_openai_delta 生成**标准 OpenAI chunk**，
                    # 保证 object/created/model/id 与 choices[].delta 结构完整。
                    if ctype == "delta":
                        emit_openai_delta({"content": chunk["content"]})
                    elif ctype == "reasoning":
                        # reasoning_content 是 DeepSeek 风格扩展字段，
                        # 放在 delta 内是业界通行做法（llama-server 亦如此）。
                        emit_openai_delta({"reasoning_content": chunk["content"]})
                    elif ctype == "tool_calls":
                        # 上游给的是**扁平**结构 {index,id,name,arguments}，
                        # 而标准 OpenAI 增量要求
                        #   {index,id,type,function:{name,arguments}}
                        # 历史实现直接原样透传，于是所有按协议解析的消费方
                        # （OpenAI SDK / LangChain / Cline，以及本仓库自己的前端
                        # mergeToolCallDeltas）都读不到工具名与参数 ——
                        # 表现为"模型调不了工具"。
                        emit_openai_delta({
                            "tool_calls": _normalize_tool_call_deltas(chunk["tool_calls"]),
                        })
                    elif ctype == "tool_call":
                        tc = chunk.get("tool_call", {})
                        emit_openai_delta({"tool_calls": [{
                            "index": 0,
                            "id": tc.get("id", "call_0"),
                            "type": "function",
                            "function": {
                                "name": tc.get("name"),
                                "arguments": json.dumps(tc.get("arguments", {}), ensure_ascii=False),
                            },
                        }]})
                    else:
                        continue

                logger.info(
                    "SSE 模型流结束: chunks=%d types=%s elapsed=%.2fs",
                    chunk_count, ctype_counts, time.time() - started,
                )

                # 兜底：无论上游是否发出 done，都必须补一个标准终态块
                # （choices[0].finish_reason），否则严格 OpenAI 客户端会报
                # "Stream ended without finish_reason" 并丢弃整次响应。
                if not terminal_sent:
                    logger.warning(
                        "上游未发出 done 事件（types=%s），补发标准 finish_reason=stop",
                        ctype_counts,
                    )
                    emit("data: " + json.dumps({
                        "id": f"chatcmpl-dsn-{int(time.time() * 1000)}",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": model_name,
                        "choices": [{
                            "index": 0,
                            "delta": {},
                            "finish_reason": "stop",
                        }],
                    }, ensure_ascii=False) + "\n\n")

                # 若 provider 未回传 timings（如 llama-server 关闭了 timings 输出），
                # 退化用弹性上下文的字符统计估算 prompt token，保证用量指示环仍可用。
                estimated_usage = False
                if not provider_sent_timings:
                    logger.debug("provider 未回传 timings，改用弹性上下文字符数估算")
                    stats = engine.agent.get_context_stats() or {}
                    injected = int(stats.get("total_injected_chars") or 0)
                    if injected > 0:
                        est_tokens = max(1, int(injected / 3.2))
                        last_timings.update({
                            "prompt_n": est_tokens,
                            "prompt_ms": 0,
                            "predicted_n": 0,
                            "predicted_ms": 0,
                            "cache_n": 0,
                        })
                        estimated_usage = True
                        fallback = {
                            "timings": dict(last_timings),
                            "usage": _openai_usage_from_timings(last_timings),
                            "dsn_usage": _dsn_usage_extras(last_timings),
                            "estimated": True,
                        }
                        emit(f"data: {json.dumps(fallback, ensure_ascii=False)}\n\n")

                # ── 标准 OpenAI 用量块 ──
                # 协议：当 stream_options.include_usage 为真时，在 [DONE] 之前补一个
                # choices 为空、只带 usage 的收尾块。另外，如果终态块没能带上用量
                # （例如 timings 比 done 晚到、或用了估算值），也在这里补齐，
                # 保证任何客户端都能拿到 prompt/completion 与缓存命中信息。
                want_usage_chunk = False
                _so = body.get("stream_options")
                if isinstance(_so, dict):
                    want_usage_chunk = bool(_so.get("include_usage"))

                if last_timings and (want_usage_chunk or not terminal_carried_usage):
                    usage_payload = {
                        "id": f"chatcmpl-dsn-{int(time.time() * 1000)}",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": model_name,
                        "choices": [],
                        "usage": _openai_usage_from_timings(last_timings),
                        "dsn_usage": _dsn_usage_extras(last_timings),
                        "timings": dict(last_timings),
                    }
                    if estimated_usage:
                        usage_payload["estimated"] = True
                    emit(f"data: {json.dumps(usage_payload, ensure_ascii=False)}\n\n")

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

                # 轮次完成 → 异步入队思路蒸馏。execution_mode 下才有工具链；
                # 只入队：不等待蒸馏、不延迟响应收尾。
                if execution_mode and tc_tool_calls:
                    _enqueue_thought_cache(
                        conv_id=conv_id,
                        message_id=str(
                            body.get("message_id")
                            or body.get("client_message_id")
                            or f"turn-{uuid.uuid4().hex[:12]}"
                        ),
                        user_text=_extract_last_user_text(messages_raw),
                        tool_calls=tc_tool_calls,
                        tool_results=tc_tool_results,
                        reply="".join(tc_reply_parts),
                        model=model_name,
                    )
            except asyncio.CancelledError:
                # 用户点「停止」、新流顶替、或客户端断开都会走到这里。
                #
                # 修复说明：本分支必须排在 except Exception 之前。Python 按顺序
                # 匹配 handler，原先这里之后还有一个 except asyncio.CancelledError
                # （在 except Exception 之后）——它永远不可达，导致取消事件被
                # 宽泛的 Exception 分支吞掉，会话以 error="推理失败" 结束，
                # 前端弹出错误框、日志里也没有取消痕迹。
                logger.warning(
                    "SSE 被取消(客户端断开?): chunks=%d elapsed=%.2fs types=%s",
                    chunk_count, time.time() - started, ctype_counts,
                )
                emit("data: [DONE]\n\n")
                session.finish(error="cancelled")
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
                _sink_state["seal_requested"] = True
                with _cache_pending_lock:
                    for _line in _cache_pending:
                        emit(_line)
                    _cache_pending.clear()
                    _sink_state["sealed"] = True
                emit("data: [DONE]\n\n")
                session.finish(error=str(e))
            finally:
                # 封口缓存帧：蒸馏在 [DONE] 之后仍会推 running/done，而
                # StreamSession.append() 在 is_done 之后拒收写入。这里给工作线程
                # 一个短窗口（仅毫秒级等待，且只在有在途任务时）收集 done/error，
                # 然后一次性补发，UI 才能看到 queued -> running -> done 全链路。
                _sink_state["seal_requested"] = True
                try:
                    _cache_svc = getattr(engine, "thought_cache", None)
                    _tc_active = False
                    if _cache_svc is not None:
                        _st = _cache_svc.status() or {}
                        _tc_active = bool(_st.get("running")) or int(_st.get("queue_depth") or 0) > 0
                    # 修复说明：本函数是 asyncio.create_task 起的协程，运行在事件循环
                    # 线程上。原实现用 time.sleep() 轮询，会把**整个事件循环**阻塞最多
                    # 30 秒 —— 期间所有 SSE 推送、其他对话、/models、心跳全部停摆。
                    # 必须用 await asyncio.sleep() 让出控制权。
                    #
                    # 同时把等待上限从 30s 大幅收紧：这里只是为了给后台蒸馏线程一个
                    # 补发 done 帧的机会，不该让它拖住当前对话的收尾。没等到就由
                    # UI 侧轮询兜底，不会丢数据。
                    _deadline = time.monotonic() + (5.0 if _tc_active else 0.6)
                    while time.monotonic() < _deadline:
                        with _cache_pending_lock:
                            _done_seen = any(
                                "\"state\": \"done\"" in _l or "\"state\": \"error\"" in _l
                                for _l in _cache_pending
                            )
                        if _done_seen:
                            break
                        await asyncio.sleep(0.05)
                except asyncio.CancelledError:
                    raise
                except Exception as _e:  # noqa: BLE001
                    logger.debug("等待缓存封口失败: %s", _e)
                with _cache_pending_lock:
                    _pending_to_flush = list(_cache_pending)
                    _cache_pending.clear()
                    _sink_state["sealed"] = True
                for _line in _pending_to_flush:
                    try:
                        emit(_line)
                    except Exception as _e:  # noqa: BLE001
                        logger.debug("补发缓存帧失败: %s", _e)
                if _pending_to_flush:
                    logger.info(
                        "已补发 %d 条缓存帧到聊天流: conv=%s states=%s",
                        len(_pending_to_flush), conv_id,
                        [json.loads(_l[6:]).get("state") for _l in _pending_to_flush if _l.startswith("data: ")],
                    )
                # 注销本轮接收器：此后缓存状态只由 /models/sse 兜底。
                _sink_state["active"] = False
                try:
                    with _chat_stream_sinks_lock:
                        _chat_stream_sinks.pop(conv_id, None)
                except Exception:  # noqa: BLE001
                    pass
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
        # 会话可能被规范化（::model 后缀 / 去重）：缓存事件必须挂在**真实**会话 id 上，
        # 否则接收器永远匹配不到 emitter 投递的 conv_id。
        session_conv_id = getattr(session, "conversation_id", None) or conv_id
        session.task = asyncio.create_task(_produce_sse(session, session_conv_id))

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
        # 安全护栏：该端点能执行全部 harness 工具（含 file.write / proc.run 等
        # 有副作用的工具），而正常对话链路里工具由后端 AgentLoop 统一执行，
        # 前端根本不需要它。默认关闭，仅调试/外部集成时用
        # DSN_UI_ENABLE_TOOL_ENDPOINT=1 显式打开。
        if not (os.getenv("DSN_UI_ENABLE_TOOL_ENDPOINT") or "").strip().lower() in ("1", "true", "yes", "on"):
            raise HTTPException(
                status_code=403,
                detail="工具执行端点已关闭（设置 DSN_UI_ENABLE_TOOL_ENDPOINT=1 可开启）",
            )

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
        # 修复说明：params 若是 list / 数字 / null，**params 会直接 TypeError → 500。
        # 合法输入只应是 JSON 对象（工具参数按关键字展开）。
        if not isinstance(params, dict):
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

    # ── 6.7 思考链缓存（思路模板）API ──
    # 全部 handler 都薄：async + 委托 to_thread 调用服务，绝不阻塞事件循环。

    def _thought_cache_service():
        return getattr(engine, "thought_cache", None)

    def _thought_cache_down():
        return JSONResponse(status_code=503, content={"error": "思考链缓存不可用"})

    async def _thought_cache_body(req: Request) -> dict:
        try:
            body = await req.json()
        except Exception:  # noqa: BLE001
            return {}
        return body if isinstance(body, dict) else {}

    @app.get("/api/thought-cache/status")
    async def thought_cache_status():
        svc = _thought_cache_service()
        if svc is None:
            return _thought_cache_down()
        return await asyncio.to_thread(svc.status)

    @app.get("/api/thought-cache/templates")
    async def thought_cache_templates(limit: int = 50, offset: int = 0, q: Optional[str] = None):
        svc = _thought_cache_service()
        if svc is None:
            return _thought_cache_down()
        total, items = await asyncio.to_thread(svc.list_templates, limit, offset, q)
        return {"total": total, "items": items}

    @app.delete("/api/thought-cache/templates/{template_id}")
    async def thought_cache_delete_template(template_id: str):
        svc = _thought_cache_service()
        if svc is None:
            return _thought_cache_down()
        ok = await asyncio.to_thread(svc.delete_template, template_id)
        if not ok:
            raise HTTPException(status_code=404, detail="思路模板不存在")
        return {"status": "ok"}

    @app.post("/api/thought-cache/config")
    async def thought_cache_update_config(req: Request):
        svc = _thought_cache_service()
        if svc is None:
            return _thought_cache_down()
        body = await _thought_cache_body(req)
        cfg = await asyncio.to_thread(svc.update_config, **body)
        return {"status": "ok", "config": cfg}

    @app.post("/api/thought-cache/distill")
    async def thought_cache_manual_distill(req: Request):
        """手动触发一次蒸馏（force=True 跳过 min_tool_calls 门槛）。"""
        svc = _thought_cache_service()
        if svc is None:
            return _thought_cache_down()
        body = await _thought_cache_body(req)
        context = str(body.get("context") or "")
        chain = str(body.get("chain") or "")
        if not context.strip() and not chain.strip():
            raise HTTPException(status_code=400, detail="context 与 chain 至少提供一个")
        model = str(body.get("model") or "").strip() or None
        job_id = await asyncio.to_thread(
            svc.enqueue_distill,
            str(body.get("conv_id") or ""),
            str(body.get("message_id") or f"manual-{uuid.uuid4().hex[:12]}"),
            context,
            chain,
            model,
            True,
        )
        return {"status": "ok", "queued": bool(job_id), "job_id": job_id}

    @app.post("/api/thought-cache/recall")
    async def thought_cache_recall(req: Request):
        svc = _thought_cache_service()
        if svc is None:
            return _thought_cache_down()
        body = await _thought_cache_body(req)
        query = str(body.get("query") or "").strip()
        if not query:
            raise HTTPException(status_code=400, detail="缺少 query")
        limit = body.get("limit")
        templates = await asyncio.to_thread(svc.recall, query, limit)
        return {"hits": len(templates), "templates": templates}

    # ── 7. 本地系统资源与显存监控 API ──

    @app.get("/api/system/resources")
    async def get_system_resources_api():
        """返回 CPU、系统内存及所有显卡的显存监控数据。

        硬件页每 2s 轮询一次（SSE 状态变更时还会额外触发）。采集过程包含
        psutil 采样与 nvidia-smi 子进程，都是阻塞调用；如果直接写在 async
        处理函数里，就会把整个事件循环冻结 —— 同一时刻的 /v1/streams/lookup
        （打开会话）、/models（模型列表）与正在进行的 SSE 推理推送全部被拖住。
        因此这里统一丢到线程池执行。
        """
        def _peripheral_status() -> dict:
            """外周资源池（ASR / TTS）状态 —— 契约字段固定，池不可用时给空结构。"""
            pool = getattr(engine, "resource_pool", None)
            if pool is None:
                return {
                    "max_concurrent_slots": 0,
                    "used_slots": 0,
                    "registered": 0,
                    "loaded": 0,
                    "resources": [],
                }
            try:
                slots = pool.slot_status()
                resources = pool.status().get("resources", [])
                return {
                    "max_concurrent_slots": int(slots.get("max_concurrent_slots", 0)),
                    "used_slots": int(slots.get("used_slots", 0)),
                    "registered": int(slots.get("registered", len(resources))),
                    "loaded": int(slots.get("loaded", 0)),
                    "resources": resources,
                }
            except Exception as e:  # noqa: BLE001 - 状态接口不能因资源池失败而 500
                log_exception(logger, "读取外周资源池状态失败", e)
                return {
                    "max_concurrent_slots": 0,
                    "used_slots": 0,
                    "registered": 0,
                    "loaded": 0,
                    "resources": [],
                }

        def _collect() -> dict:
            data = get_system_resources()
            orch = engine.orchestrator.status()
            # 硬件页需要对第三方 API 模型区别对待：它们运行在远端，既没有本地
            # 进程也不占显存，因此不该出现「载入显存 / 释放显存」按钮。
            # orchestrator.status() 只导出 source_type，这里补上派生标志 ——
            # 否则前端拿到 is_api_model=undefined，会一路落到本地模型的分支，
            # 表现为资源页对云端模型只剩一个「释放显存」。
            for _m in orch.get("models", []):
                _is_api = _m.get("source_type") == "api_openai"
                _m["is_api_model"] = _is_api
                _m["always_ready"] = _is_api
                if _is_api:
                    _spec = engine.orchestrator.get_model_spec(_m.get("name"))
                    _label = getattr(_spec, "provider_label", None)
                    _m["provider_label"] = _label
                    _m["provider_id"] = _provider_id_for(_label)
            data["orchestrator"] = orch
            # 显存管理开关状态，供硬件页渲染
            data["kv_offload_disabled"] = engine.orchestrator.get_kv_offload_disabled()
            # 外周资源池（ASR / TTS）与任务槽状态，供「外周任务槽」卡片。
            data["peripherals"] = _peripheral_status()
            return data

        return await asyncio.to_thread(_collect)

    # ── 7.5 外周资源（ASR / TTS）生命周期 API ──

    def _resource_pool():
        """已装配的外周资源池；未装配时为 None。"""
        return getattr(engine, "resource_pool", None)

    async def _json_body(req: Request) -> dict:
        """尽力解析 JSON body；非 JSON / 非法 body 返回空 dict。"""
        try:
            body = await req.json()
        except Exception:  # noqa: BLE001
            return {}
        return body if isinstance(body, dict) else {}

    @app.post("/api/resources/start")
    async def start_peripheral_resource(req: Request):
        """加载（启动）一个外周资源，如 asr / tts。"""
        pool = _resource_pool()
        name = str((await _json_body(req)).get("name") or "").strip()
        if pool is None:
            return JSONResponse(status_code=500, content={"error": "资源池不可用"})
        if not name or pool.get_spec(name) is None:
            return JSONResponse(
                status_code=400, content={"error": f"未知或未注册的资源: {name or '(empty)'}"}
            )
        from apps.dsn.config import Config

        timeout = int(
            Config.ASR_LOAD_TIMEOUT
            if name == "asr"
            else getattr(Config, "TTS_LOAD_TIMEOUT", 300)
        )
        try:
            loaded = await asyncio.to_thread(pool.ensure_running, name, timeout=timeout)
        except Exception as e:  # noqa: BLE001
            log_exception(logger, f"启动外周资源失败: {name}", e)
            return JSONResponse(status_code=500, content={"error": str(e)})
        if not loaded:
            return JSONResponse(
                status_code=500, content={"error": f"资源启动失败或超时: {name}"}
            )
        return {"status": "ok", "name": name, "loaded": True}

    @app.post("/api/resources/stop")
    async def stop_peripheral_resource(req: Request):
        """卸载（停止）一个外周资源，如 asr / tts。"""
        pool = _resource_pool()
        name = str((await _json_body(req)).get("name") or "").strip()
        if pool is None:
            return JSONResponse(status_code=500, content={"error": "资源池不可用"})
        if not name or pool.get_spec(name) is None:
            return JSONResponse(
                status_code=400, content={"error": f"未知或未注册的资源: {name or '(empty)'}"}
            )
        try:
            ok = await asyncio.to_thread(pool.stop_resource, name)
        except Exception as e:  # noqa: BLE001
            log_exception(logger, f"停止外周资源失败: {name}", e)
            return JSONResponse(status_code=500, content={"error": str(e)})
        if not ok:
            return JSONResponse(status_code=500, content={"error": f"资源停止失败: {name}"})
        return {"status": "ok", "name": name, "loaded": False}

    @app.post("/api/resources/slots")
    async def set_peripheral_slots(req: Request):
        """调整外周任务槽数量（与 LLM 显存插槽配额相互独立）。"""
        body = await _json_body(req)
        try:
            slots = int(body.get("slots"))
        except (TypeError, ValueError):
            return JSONResponse(
                status_code=400, content={"error": "slots 必须是 >= 1 的整数"}
            )
        if slots < 1:
            return JSONResponse(status_code=400, content={"error": "slots must be >= 1"})
        pool = _resource_pool()
        if pool is None:
            return JSONResponse(status_code=500, content={"error": "资源池不可用"})
        try:
            applied = await asyncio.to_thread(pool.set_max_concurrent, slots)
        except Exception as e:  # noqa: BLE001
            log_exception(logger, "调整外周任务槽失败", e)
            return JSONResponse(status_code=500, content={"error": str(e)})
        return {"status": "ok", "max_concurrent_slots": int(applied)}

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
            # 对外 API 模式：dsn（完整 DSN-exp）| passthrough（完全交给请求方）。
            # 供 UI / 集成方确认当前实例是否注入提示词、是否启用情绪与记忆。
            "api": {
                "mode": UIConfig.resolve_api_mode(),
                "locked": UIConfig.API_MODE_LOCKED,
                "available_modes": list(API_MODES),
                "note": (
                    "passthrough 不注入任何提示词、不跑情绪与记忆系统，"
                    "请求方 messages 原样送进模型"
                ),
            },
            # 修复说明（致命）：本函数原先整段引用 `Config.*`，但 server.py 只
            # 导入了 `UIConfig`，模块里**根本没有 Config 这个名字** —— 调用
            # GET /api/settings 必然抛 NameError → 500。同一问题也出现在
            # POST /api/resources/start（Config.ASR_LOAD_TIMEOUT）。
            #
            # 这里改用 _cfg() 安全读取：优先 UIConfig 属性，其次同名环境变量，
            # 最后返回默认值。缺项不再打挂接口，也让配置来源可追溯。
            "orchestrator": {
                "max_concurrent_slots": engine.orchestrator.max_concurrent_slots,
                "llamacpp_bin": _cfg("LLAMA_SERVER_BINARY", "LLAMACPP_BIN",
                                     default=UIConfig.LLAMA_SERVER_BINARY),
                "llamacpp_base_url": _cfg("LLAMACPP_BASE_URL", default="http://127.0.0.1:8080"),
                "lmstudio_base_url": _cfg("LMSTUDIO_BASE_URL", default="http://localhost:4501"),
                "openai_api_base": _cfg("OPENAI_API_BASE", default="https://api.openai.com/v1"),
                "openai_api_key_set": bool(_cfg("OPENAI_API_KEY", default="")),
            },
            "memory": {
                "enabled": _cfg("MEMORY_ENABLED", default=True),
                "embedding_enabled": _cfg("MEMORY_EMBEDDING_ENABLED", default=False),
                "embedding_model": _cfg("MEMORY_EMBEDDING_MODEL", default=""),
                "summary_backend": _cfg("MEMORY_SUMMARY_BACKEND", default="llm"),
                "context_window_size": _cfg("MEMORY_CONTEXT_WINDOW_SIZE", default=128000),
                "search_threshold": _cfg("MEMORY_SEARCH_THRESHOLD", default=0.5),
            },
            "voice": {
                "asr_enabled": _cfg("ASR_ENABLED", default=False),
                "asr_device": _cfg("ASR_DEVICE", default="cpu"),
                "tts_enabled": _cfg("TTS_ENABLED", default=False),
                "tts_base_url": _cfg("TTS_BASE_URL", default=""),
                "tts_process_enabled": _cfg("TTS_PROCESS_ENABLED", default=False),
            },
            "companion": {
                "personality_v3_enabled": _cfg("PERSONALITY_V3_ENABLED", default=False),
                "world_enabled": _cfg("WORLD_ENABLED", default=False),
                "narrative_enabled": _cfg("NARRATIVE_ENABLED", default=False),
            },
            "personal": {
                "task_manager_enabled": _cfg("TASK_MANAGER_ENABLED", default=False),
            },
            "server": {
                "host": UIConfig.HOST,
                "port": UIConfig.PORT,
                "log_level": _cfg("LOG_LEVEL", default="INFO"),
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
        """校验模型存在且为**本地托管引擎**（llama.cpp / Strata）模型。"""
        if not model_name:
            raise HTTPException(status_code=400, detail="缺少 model 字段")
        spec = engine.orchestrator._specs.get(model_name)
        if spec is None:
            raise HTTPException(status_code=404, detail=f"未知模型: {model_name}")
        if not getattr(spec, "llama_config", None) and not getattr(spec, "strata_config", None):
            raise HTTPException(
                status_code=400,
                detail=f"模型 {model_name} 不是本地托管引擎模型（无可编辑的启动参数）",
            )
        return model_name

    @app.get("/api/models/launch-params")
    async def get_launch_params(model: str):
        """读取某模型的当前启动参数（用于预设面板回显）。

        返回体带 `engine` 字段：llama_cpp 走 llama-server 开关表单，
        strata 走 run config（args / gpu / lib_dirs / server 开关）表单。
        """
        _require_local_model(model)
        try:
            params = engine.orchestrator.get_launch_params(model)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        # 覆盖持久化只针对 llama.cpp 的 profile（Strata 的参数写在它自己的
        # run config 里，由 /api/models/launch-params/save 直接回写）。
        params["has_override"] = (
            model in engine.load_launch_overrides() if params.get("engine") == "llama_cpp" else False
        )
        return params

    @app.post("/api/models/launch-params/preview")
    async def preview_launch_params(req: Request):
        """预览参数合成出的命令行（不落地、不启动）。"""
        body = await req.json()
        model = _require_local_model(body.get("model") or "")
        try:
            return engine.orchestrator.preview_launch_params(model, body.get("params") or {})
        except (KeyError, ValueError) as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/api/models/launch-params/save")
    async def save_launch_params(req: Request):
        """★ 保存启动参数。

        * llama.cpp：写入 profile 覆盖（跨重启生效，持久化由应用负责）；
        * Strata：直接回写它的 run config JSON（原子替换 + .bak），
          使 harness 与用户的 `run-<model>.sh` 保持一致。

        请求体: { model, params }
        """
        body = await req.json()
        model = _require_local_model(body.get("model") or "")
        params = body.get("params") or {}
        try:
            changed = engine.orchestrator.apply_launch_params(model, params)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        is_strata = engine.orchestrator._specs[model].strata_config is not None
        if is_strata:
            try:
                written = engine.orchestrator.save_launch_params(model, params)
            except (OSError, ValueError) as e:
                raise HTTPException(status_code=500, detail=f"写入 run config 失败: {e}")
            logger.info("保存 Strata run config: model=%s changed=%s", model, sorted(changed))
            return {
                "status": "ok",
                "model": model,
                "engine": "strata",
                "changed": sorted(changed),
                "saved": written,
                "note": "已写入 run config；下一次加载该模型时生效",
            }

        saved = engine.save_launch_override(model, params)
        logger.info("保存启动参数预设: model=%s changed=%s", model, sorted(changed))
        return {
            "status": "ok",
            "model": model,
            "engine": "llama_cpp",
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

    @app.get("/api/models/launch-params/default")
    async def default_launch_params(model: str):
        """返回该模型**未经覆盖**的默认参数（用于「恢复默认」对比）。

        Strata：重新读取磁盘上的 run config；
        llama.cpp：返回当前配置（应用层的覆盖记录在 overrides 文件里，
        由 /reset 清除后重新拉取即可见）。
        """
        model = _require_local_model(model)
        spec = engine.orchestrator._specs[model]
        if spec.strata_config is not None:
            from infra.orchestrator import StrataEngineConfig
            try:
                fresh = StrataEngineConfig.load(spec.strata_config.resolved_config_path())
            except (OSError, ValueError) as e:
                raise HTTPException(status_code=500, detail=str(e))
            fresh.server_script = spec.strata_config.server_script
            fresh.python_path = spec.strata_config.python_path
            fresh.port = spec.strata_config.port
            return {"engine": "strata", "model": model, **fresh.to_dict()}
        params = engine.orchestrator.get_launch_params(model)
        params["engine"] = "llama_cpp"
        params["model"] = model
        return params

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
            # 恢复原配置：一次性启动不应污染持久设置。
            # 与 get_launch_params() 的导出键对应（含两种引擎的外壳字段与
            # Strata 的只读预览字段），这些不参与回写。
            skipped = {
                "model", "engine", "has_override", "config_path",
                "command_preview", "run_script_preview",
            }
            try:
                restore = {k: v for k, v in original.items() if k not in skipped}
                engine.orchestrator.apply_launch_params(model, restore)
            except Exception as e:  # noqa: BLE001
                logger.warning("恢复启动参数失败 %s: %s", model, e)

        return {
            "success": bool(ok),
            "model": model,
            "status": "loaded" if ok else "failed",
            "transient": True,
        }

    # ── 远程 API Provider 管理（设置页「API 模型管理」）──

    @app.get("/api/providers")
    async def list_providers():
        """列出所有已配置的 API provider（API Key 已脱敏）。"""
        from apps.dsn_ui.api_providers import public_view
        return {
            "providers": [public_view(p) for p in engine.provider_store.list()],
            "protocols": [
                {"id": "chat", "label": "OpenAI Chat Completions",
                 "endpoint": "/v1/chat/completions"},
                {"id": "responses", "label": "OpenAI Responses",
                 "endpoint": "/v1/responses"},
                {"id": "anthropic", "label": "Anthropic Messages",
                 "endpoint": "/v1/messages"},
            ],
        }

    @app.post("/api/providers")
    async def upsert_provider(req: Request):
        """新增或更新一个 provider，并立即重建其模型注册。"""
        from apps.dsn_ui.api_providers import public_view
        body = await req.json()

        # 更新前先取快照：unregister 必须基于**旧**模型列表，
        # 否则旧模型名会残留成僵尸注册（列表里同时出现新旧两条）。
        snapshot = None
        if body.get("id"):
            snapshot = engine.provider_store.get(str(body["id"]))
            # 前端不回传 api_key（脱敏为空）时沿用已保存的 key
            if not body.get("api_key") and snapshot:
                body["api_key"] = snapshot.get("api_key") or ""

        try:
            record = engine.provider_store.upsert(body)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # 用旧快照清理，再按新配置重建
        if snapshot:
            engine.unregister_provider_models(record["id"], snapshot=snapshot)
        engine.reload_api_providers()
        logger.info("Provider 已保存并注册: %s", record.get("label"))
        return {"status": "ok", "provider": public_view(record)}

    @app.delete("/api/providers/{provider_id}")
    async def delete_provider(provider_id: str):
        """删除 provider 并注销其全部模型。"""
        removed = engine.unregister_provider_models(provider_id)
        ok = engine.provider_store.delete(provider_id)
        if not ok:
            raise HTTPException(status_code=404, detail="provider 不存在")
        engine.reload_api_providers()
        return {"status": "ok", "removed_models": removed}

    @app.post("/api/providers/test")
    async def test_provider(req: Request):
        """测试连通性并向远端询问可用模型。

        请求体可给 {protocol, base_url, api_key}，或给 {id} 复用已存 provider
        （api_key 留空表示沿用已保存的 key）。成功后把发现的模型写回。
        """
        from apps.dsn_ui.api_providers import (
            ANTHROPIC_FALLBACK_MODELS, discover_models, public_view,
        )
        body = await req.json()

        provider = None
        if body.get("id"):
            provider = engine.provider_store.get(str(body["id"]))
            if provider is None:
                raise HTTPException(status_code=404, detail="provider 不存在")

        protocol = str(body.get("protocol") or (provider or {}).get("protocol") or "chat")
        base_url = str(body.get("base_url") or (provider or {}).get("base_url") or "")
        api_key = str(body.get("api_key") or (provider or {}).get("api_key") or "")

        if not base_url:
            raise HTTPException(status_code=400, detail="缺少 base_url")
        if not api_key:
            # 给出可操作的提示，而不是一句干巴巴的「缺少 api_key」：
            # 新建 provider 时用户往往以为探测不需要 key。
            raise HTTPException(
                status_code=400,
                detail="缺少 api_key：请输入 API Token，或先保存该 provider 再点探测（可复用已保存的 Token）",
            )

        try:
            models = await asyncio.to_thread(
                discover_models,
                protocol=protocol,
                base_url=base_url,
                api_key=api_key,
            )
            warning = None
        except Exception as e:  # noqa: BLE001
            # Anthropic 的 /v1/models 并非所有端点都支持：退回内置列表，
            # 让用户仍可手动挑选模型，而不是完全卡死。
            if protocol == "anthropic":
                models = list(ANTHROPIC_FALLBACK_MODELS)
                warning = f"远端模型列表不可用（{e}），已提供常用模型名供手动选择"
                logger.warning("Anthropic 模型发现失败，使用兜底列表: %s", e)
            else:
                logger.warning("模型发现失败: %s", e)
                return JSONResponse(
                    status_code=502,
                    content={"status": "error", "error": str(e)},
                )

        # 探测是**只读**操作：只把远端可用模型列表回给前端，由用户在界面上
        # 勾选后再保存。
        #
        # 历史行为：探测成功就直接 provider["models"] = models 写回存储并重注册。
        # 这有两个后果：
        #   1. 用户只是在面板里点了「探测」，尚未保存，已启用的模型集合就被
        #      悄悄替换成远端的全量列表；
        #   2. 探测走的是**已保存**的 key 与地址，与用户正在表单里改的内容无关，
        #      写回的是旧配置，进一步造成「改了没生效」的困惑。
        # 前端 save() 才是唯一负责落盘的地方。

        logger.info("Provider 测试成功: %s -> %d 个模型", base_url, len(models))
        return {
            "status": "ok",
            "models": models,
            "count": len(models),
            "warning": warning,
            "provider": public_view(provider) if provider else None,
        }

    @app.get("/api/providers/models")
    async def list_provider_models():
        """所有 provider 贡献的、已注册进 orchestrator 的模型清单。"""
        out = []
        status = engine.orchestrator.status()
        by_name = {m["name"]: m for m in status.get("models", [])}
        for p in engine.provider_store.list():
            label = p.get("label") or "Provider"
            for model in p.get("models") or []:
                name = f"{label} / {model}"
                out.append({
                    "provider_id": p.get("id"),
                    "provider_label": label,
                    "protocol": p.get("protocol"),
                    "model": model,
                    "registered_name": name,
                    "registered": name in by_name,
                    "base_url": p.get("base_url"),
                })
        return {"models": out, "total": len(out)}

    @app.get("/api/integration/bonsai")
    async def get_bonsai_status():
        """Bonsai-demo 集成状态：自定义二进制与多模态模型发现结果。

        供前端/集成方确认「自定义 llama.cpp + 本地多模态」是否就绪。
        """
        from apps.dsn_ui.bonsai_integration import bonsai_status
        return bonsai_status()

    @app.get("/api/integration/strata")
    async def get_strata_status():
        """Strata 集成状态：检出目录、run config 与启动命令行预览。

        供前端/集成方确认「本地 Strata 引擎」是否就绪（与 llama.cpp 同构，
        但由 serve/server.py + run config JSON 拉起）。
        """
        from apps.dsn_ui.strata_integration import strata_status
        return strata_status()

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

    # ── 9.9b System-1 决策 API（JEV 双系统混合模型的「一次前向给概率」）──
    # System 2 = 常规生成（/v1/chat/completions，已在上面挂载）
    # System 1 = 决策头（logprobs 读概率分布），见 system1_api.py 的模块注释。
    # 同样必须在 SPA catch-all 之前注册。
    try:
        from apps.dsn_ui.system1_api import register_system1_routes
        register_system1_routes(app, engine)
    except Exception as e:  # noqa: BLE001
        log_exception(logger, "挂载 System-1 决策 API 失败", e)

    # ── 9.10 ASR 语音识别 API ──
    # 与上一条同理：必须注册在 SPA catch-all 之前，否则请求会落到 index.html。
    try:
        from apps.dsn_ui.asr_api import register_asr_routes

        register_asr_routes(app)
        logger.info("ASR API 已启用: POST /api/asr/recognize")
    except Exception as e:  # noqa: BLE001
        log_exception(logger, "挂载 ASR API 失败", e)

    # ── 9.11 实例接入 API（配置新实例：模型 / API Provider / TTS 载荷与测试）──
    # 同样必须在 SPA catch-all 之前注册。
    try:
        from apps.dsn_ui.onboarding_api import register_onboarding_routes

        register_onboarding_routes(app, engine)
        logger.info("实例接入 API 已启用: /api/onboarding/*, /api/tts/*")
    except Exception as e:  # noqa: BLE001
        log_exception(logger, "挂载实例接入 API 失败", e)

    # ── 9.12 Agent 运行时面板 API ──
    try:
        from apps.dsn_ui.agent_runtime_api import register_agent_runtime_routes

        register_agent_runtime_routes(app, engine)
        logger.info("Agent 运行时 API 已启用: /api/agent-runtime/*")
    except Exception as e:  # noqa: BLE001
        log_exception(logger, "挂载 Agent 运行时 API 失败", e)

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
