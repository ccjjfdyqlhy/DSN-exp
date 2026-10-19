# apps/dsn_ui/onboarding_api.py
"""配置新实例（onboarding）HTTP API —— 第三方 API 接入、本地引擎接入、TTS payload。

本模块把「从 0 配置一个实例」所需的全部后端能力集中在一处，由
register_onboarding_routes(app[, engine]) 挂载。**必须注册在 SPA catch-all 之前**，
否则 GET 路由会被 index.html 吞掉（与 integration_api / asr_api 同理）。

## 端点总览

  第三方 API 实例
    POST /api/onboarding/api-provider    创建/更新 provider 并即时注册其模型

  本地引擎实例（llama.cpp / Strata）
    GET  /api/onboarding/scan-models     扫描磁盘上的候选 GGUF
    GET  /api/onboarding/local-defaults  表单默认值
    POST /api/onboarding/local-model     注册本地模型并持久化 profile

  TTS 请求 payload
    GET  /api/tts/payload                读取当前默认请求体 + 音色 profile
    POST /api/tts/payload                保存默认请求体（写 dsn_ui 自己的 data 目录）
    POST /api/tts/test                   真实发起一次合成请求并返回结构化结果

## 持久化与「跨重启存活」

llama.cpp 模型的持久化直接复用现有机制：engine._init_default_profiles() 在启动时
读取 apps/dsn/model_profiles/*.yaml 并注册，因此本模块把新模型写成一个 profile YAML
（**不另造平行存储**）。Strata 则由 orchestrator.save_launch_params() 写回引擎自己的
run config。
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import socket
import time
from pathlib import Path
from typing import Any, Optional

import requests
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("DSNUIServer")

#: 从文件名里识别量化等级（Q4_K_M / IQ1_M / F16 ...），仅用于展示。
_QUANT_RE = re.compile(
    r"(?i)(IQ\d+_[A-Z0-9]+|Q\d+_[A-Z0-9]+|Q\d+|F16|FP16|BF16|F32)"
)

#: TTS 测试用的短文本（payload 里没有 text 时注入）。
_TTS_TEST_TEXT = "你好，这是一次语音合成测试。"

_http_session: Optional[requests.Session] = None


def _session() -> requests.Session:
    """本地请求专用会话：忽略代理。

    仓库里已有教训：ALL_PROXY 会把 127.0.0.1 的请求也交给代理，
    代理不可用时本地服务明明在跑却连不上。
    """
    global _http_session
    if _http_session is None:
        s = requests.Session()
        s.trust_env = False
        _http_session = s
    return _http_session


# ────────────────────────── engine 解析 ──────────────────────────

def _resolve_engine(app: FastAPI, engine: Any = None) -> Any:
    """取得 DSNUIEngine：显式参数 > app.state.engine > 惰性创建。

    推荐挂载时直接传入 engine（register_onboarding_routes(app, engine)）；
    只传 app 也能工作 —— 惰性创建的实例与主实例共享同一个
    ModelOrchestrator 单例，因此注册的模型对 /models 立即可见。
    """
    if engine is not None:
        return engine
    existing = getattr(app.state, "engine", None)
    if existing is not None:
        return existing
    cached = getattr(app.state, "_onboarding_engine", None)
    if cached is None:
        from apps.dsn_ui.config import UIConfig
        from apps.dsn_ui.engine import DSNUIEngine

        cached = DSNUIEngine(max_concurrent_slots=UIConfig.DEFAULT_SLOTS)
        app.state._onboarding_engine = cached
        logger.info("onboarding_api 未收到 engine，已惰性创建（共享 orchestrator 单例）")
    return cached


async def _json_body(request: Request) -> Optional[dict]:
    """解析 JSON body；非对象/解析失败返回 None。"""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return None
    return body if isinstance(body, dict) else None


def _bad(message: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": message})


def _expand(path_value: Any) -> str:
    return os.path.expanduser(os.path.expandvars(str(path_value or "")))


def _slug(name: str) -> str:
    """把模型名转成安全的文件名（profile YAML 用）。"""
    s = re.sub(r"[^0-9A-Za-z_\-]+", "_", str(name).strip())
    return s.strip("_") or "model"


def _profiles_dir() -> Path:
    from apps.dsn_ui.config import UIConfig

    return Path(UIConfig.MODEL_PROFILES_DIR)


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _free_port(preferred: int = 8080) -> int:
    """优先返回 preferred，被占用则让内核分配一个空闲端口。"""
    for candidate in (preferred, 0):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("127.0.0.1", candidate))
                return int(s.getsockname()[1])
        except OSError:
            continue
    return preferred

# ────────────────────────── GGUF 扫描 ──────────────────────────

def _scan_models() -> list[dict]:
    """在配置的根目录下扫描候选 GGUF 文件（阻塞，调用方放线程池）。

    限制：只看配置的根目录、限制递归深度与结果数、跳过隐藏目录，
    绝不遍历整个文件系统。
    """
    from apps.dsn_ui.config import UIConfig

    max_depth = max(0, int(UIConfig.MODEL_SCAN_MAX_DEPTH))
    max_results = max(1, int(UIConfig.MODEL_SCAN_MAX_RESULTS))

    found: list[dict] = []
    seen: set[str] = set()
    for raw_root in UIConfig.MODEL_SCAN_ROOTS:
        root = Path(_expand(raw_root))
        try:
            root = root.resolve()
        except OSError:
            continue
        if not root.is_dir():
            logger.debug("跳过不存在的模型扫描根目录: %s", root)
            continue
        base_parts = len(root.parts)
        for dirpath, dirnames, filenames in os.walk(root):
            current = Path(dirpath)
            depth = len(current.parts) - base_parts
            if depth >= max_depth:
                dirnames[:] = []
            # 跳过隐藏目录与常见缓存目录
            dirnames[:] = [
                d for d in dirnames
                if not d.startswith(".") and d not in ("__pycache__", "node_modules")
            ]
            for filename in filenames:
                if not filename.lower().endswith(".gguf"):
                    continue
                full = current / filename
                key = str(full)
                if key in seen:
                    continue
                try:
                    size = full.stat().st_size
                except OSError:
                    continue
                match = _QUANT_RE.search(filename)
                lower = filename.lower()
                found.append({
                    "path": key,
                    "name": full.stem,
                    "size_mb": round(size / (1024 * 1024), 1),
                    "quant": match.group(1).upper() if match else None,
                    # mmproj 是视觉投影器，不能作为主模型加载，前端据此区分
                    "mmproj": "mmproj" in lower,
                });
                seen.add(key)
                if len(found) >= max_results:
                    logger.info("GGUF 扫描达到上限 %d，提前结束", max_results)
                    found.sort(key=lambda r: (r["mmproj"], r["name"].lower()))
                    return found

    found.sort(key=lambda r: (r["mmproj"], r["name"].lower()))
    logger.info("GGUF 扫描完成：%d 个候选", len(found))
    return found


def _local_defaults(engine_id: str) -> dict:
    """本地引擎表单的默认值。"""
    from apps.dsn_ui.config import UIConfig

    base = {
        "host": "127.0.0.1",
        "port": _free_port(8080),
        "priority": 50,
        "resident": False,
        "immediate": False,
        "load_timeout": 180,
        "request_timeout": 300,
    }
    if engine_id == "strata":
        base.update({
            "python_path": "",
            "server_script": "",
            "config_path": "",
        });
    else:
        base.update({
            "binary_path": UIConfig.LLAMA_SERVER_BINARY,
            "model_path": "",
            "n_gpu_layers": -1,
            "ctx_size": 8192,
            "tensor_split": None,
            "flash_attn": None,
            "temp": 0.7,
            "threads": None,
            "reasoning_format": None,
            "no_kv_offload": False,
            "extra_args": [],
        });
    return base


# ────────────────────────── profile 持久化 ──────────────────────────

def _persist_local_profile(
    name: str, engine_id: str, config_dict: dict, sched: dict
) -> Path:
    """把本地模型写成一个 model_profiles/*.yaml。

    这是 engine._init_default_profiles() 启动时读取的目录，因此写完即"跨重启存活"。
    复用既有机制，不新建平行存储。
    """
    import yaml

    directory = _profiles_dir()
    directory.mkdir(parents=True, exist_ok=True)
    data: dict = {
        "model": name,
        "engine": engine_id,
        "priority": sched["priority"],
        "resident": sched["resident"],
        "immediate": sched["immediate"],
        "orchestrated": True,
        "load_timeout": sched["load_timeout"],
        "request_timeout": sched["request_timeout"],
    }
    if engine_id == "llama_cpp":
        data["llama_config"] = dict(config_dict)
    else:
        data["strata_config"] = dict(config_dict)

    path = directory / f"{_slug(name)}.yaml"
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    logger.info("已持久化本地模型 profile: %s", path)
    return path


def _unregister(orchestrator: Any, name: str) -> None:
    """回滚半注册的模型（与 engine.unregister_provider_models 同一手法）。"""
    try:
        with orchestrator._registry_lock:
            orchestrator._specs.pop(name, None)
    except Exception:  # noqa: BLE001
        logger.exception("回滚模型注册失败: %s", name)


def _schedule_fields(body: dict) -> dict:
    return {
        "priority": _as_int(body.get("priority"), 50),
        "resident": _as_bool(body.get("resident"), False),
        "immediate": _as_bool(body.get("immediate"), False),
        "load_timeout": _as_int(body.get("load_timeout"), 180),
        "request_timeout": _as_int(body.get("request_timeout"), 300),
    }

# ────────────────────────── 本地模型注册 ──────────────────────────

def _register_local_model(eng: Any, body: dict) -> Any:
    """注册一个本地引擎模型（llama.cpp / Strata）。返回 dict 或错误 JSONResponse。"""
    from infra.orchestrator.llamacpp import LlamaServerConfig
    from infra.orchestrator.strata import StrataEngineConfig

    name = str(body.get("name") or "").strip()
    if not name:
        return _bad("缺少 name：请填写模型名称")

    engine_id = str(body.get("engine") or "llama_cpp").strip().lower()
    if engine_id in ("llamacpp", "llama.cpp", "llama-cpp"):
        engine_id = "llama_cpp"
    if engine_id not in ("llama_cpp", "strata"):
        return _bad(f"不支持的 engine: {engine_id}（可选 llama_cpp / strata）")

    orchestrator = eng.orchestrator
    if orchestrator.get_model_spec(name) is not None:
        return _bad(f"同名模型已存在: {name}，请换一个名称或在模型管理中修改")

    sched = _schedule_fields(body)

    # ── 构造并校验引擎配置 ──
    if engine_id == "llama_cpp":
        try:
            cfg = LlamaServerConfig.from_dict(body)
        except (TypeError, ValueError) as e:
            return _bad(f"llama.cpp 参数非法: {e}")

        model_path = _expand(cfg.model_path)
        if not model_path:
            return _bad("缺少 model_path：请选择一个 GGUF 模型文件")
        if not Path(model_path).is_file():
            return _bad(f"模型文件不存在: {model_path}")
        cfg.model_path = model_path

        binary_path = _expand(cfg.binary_path)
        if not Path(binary_path).exists():
            return _bad(
                f"找不到 llama-server 可执行文件: {binary_path}。"
                f"请填写正确的 binary_path（默认 {_local_defaults("llama_cpp")["binary_path"]}）。"
            )
        cfg.binary_path = binary_path

        if not (1 <= int(cfg.port) <= 65535):
            return _bad(f"端口非法: {cfg.port}（应在 1-65535）")
        if cfg.ctx_size is not None and int(cfg.ctx_size) <= 0:
            return _bad(f"ctx_size 非法: {cfg.ctx_size}（应为正整数）")
    else:
        try:
            cfg = StrataEngineConfig.from_dict(body)
        except (TypeError, ValueError) as e:
            return _bad(f"Strata 参数非法: {e}")
        if not (cfg.config_path or cfg.server_script):
            return _bad("Strata 需要 config_path（run config JSON）或 server_script")
        if not (1 <= int(cfg.port) <= 65535):
            return _bad(f"端口非法: {cfg.port}（应在 1-65535）")

    # ── 注册（失败即返回，不留半注册状态）──
    try:
        if engine_id == "llama_cpp":
            orchestrator.register_local_llamacpp(name=name, config=cfg, **sched)
        else:
            orchestrator.register_local_strata(name=name, config=cfg, **sched)
    except Exception as e:  # noqa: BLE001
        logger.exception("注册本地模型失败: %s", name)
        _unregister(orchestrator, name)
        return _bad(f"注册模型失败: {e}", 500)

    # ── 持久化（失败则回滚，避免"重启后消失"的假成功）──
    profile_path: Optional[Path] = None
    try:
        if engine_id == "llama_cpp":
            profile_path = _persist_local_profile(name, engine_id, cfg.to_dict(), sched)
        else:
            # Strata 的 run config 由引擎自己读取，用既有 save_launch_params 写回
            orchestrator.save_launch_params(name, body)
    except Exception as e:  # noqa: BLE001
        logger.exception("持久化本地模型 profile 失败: %s", name)
        _unregister(orchestrator, name)
        if profile_path is not None and profile_path.exists():
            try:
                profile_path.unlink()
            except OSError:
                pass
        return _bad(f"模型已注册但持久化失败，已回滚: {e}", 500)

    spec = orchestrator.get_model_spec(name)
    if spec is None:
        _unregister(orchestrator, name)
        return _bad("注册后未能在 orchestrator 中找到该模型，已回滚", 500)

    preview: Optional[str] = None
    try:
        if spec.llama_config is not None:
            preview = spec.llama_config.to_command_string()
        elif spec.strata_config is not None:
            preview = spec.strata_config.to_command_string()
    except Exception:  # noqa: BLE001 - 预览失败不影响注册结果
        logger.debug("合成命令预览失败: %s", name, exc_info=True)

    return {
        "status": "ok",
        "name": name,
        "engine": engine_id,
        "registered": True,
        "command_preview": preview,
        "profile_file": str(profile_path) if profile_path else None,
    }


# ────────────────────────── TTS payload / 测试 ──────────────────────────

def _tts_endpoint_for(architecture: str) -> str:
    """串行架构用 /，并行架构用 /tts（与 VocalExp._resolve_endpoint 一致）。"""
    return "/" if architecture == "serial" else "/tts"


def _detect_tts_architecture(payload: dict) -> str:
    """按字段名推断架构（与 VocalExp._detect_architecture 一致）。"""
    if "refer_wav_path" in payload or "text_language" in payload:
        return "serial"
    return "parallel"


def _tts_profile_view() -> Optional[dict]:
    """当前默认音色 profile 的可序列化视图。"""
    try:
        from apps.dsn.plugins.builtin.tts_profile import TTSProfileManager

        manager = TTSProfileManager()
        prof = manager.get_profile()
        if prof is None:
            return None
        return {
            "name": prof.name,
            "description": prof.description,
            "architecture": prof.architecture,
            "ref_audio_path": prof.ref_audio_path,
            "prompt_text": prof.prompt_text,
            "prompt_lang": prof.prompt_lang,
            "text_lang": prof.text_lang,
            "media_type": prof.media_type,
            "streaming_mode": prof.streaming_mode,
            "extra_params": dict(prof.extra_params or {}),
            "default_profile": manager.default_name,
            "available": sorted(manager.list_profiles()),
        }
    except Exception:  # noqa: BLE001 - profile 读不出来不应让接口 500
        logger.exception("读取 TTS profile 失败")
        return None


def _build_default_payload() -> dict:
    """用当前默认 profile 合成一份开箱即用的请求体（含示例 text）。"""
    try:
        from apps.dsn.plugins.builtin.tts_profile import TTSProfileManager

        params = TTSProfileManager().build_params(_TTS_TEST_TEXT)
        params["streaming_mode"] = False
        return params
    except Exception:  # noqa: BLE001
        logger.exception("合成默认 TTS payload 失败，退回最小可用 payload")
        return {"text": _TTS_TEST_TEXT, "text_language": "zh", "streaming_mode": False}


def _payload_file() -> Path:
    from apps.dsn_ui.config import UIConfig

    return Path(UIConfig.TTS_PAYLOAD_FILE)


def _load_saved_payload() -> Optional[dict]:
    try:
        path = _payload_file()
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and isinstance(raw.get("default_payload"), dict):
            return dict(raw["default_payload"]);
        if isinstance(raw, dict):
            return dict(raw)
    except Exception:  # noqa: BLE001
        logger.exception("读取 TTS payload 文件失败")
    return None


def _save_payload(payload: dict) -> Path:
    path = _payload_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"default_payload": payload}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def _payload_state() -> dict:
    """GET /api/tts/payload 的完整视图。"""
    from apps.dsn.config import Config

    saved = _load_saved_payload()
    payload = saved if saved is not None else _build_default_payload()
    architecture = _detect_tts_architecture(payload)
    return {
        "base_url": Config.TTS_BASE_URL,
        "endpoint": _tts_endpoint_for(architecture),
        "architecture": architecture,
        "default_payload": payload,
        "saved": saved is not None,
        "profile": _tts_profile_view(),
    }


def _run_tts_test(payload: dict, ensure_tts: bool) -> dict:
    """真实发起一次 TTS 合成请求（阻塞，调用方放线程池）。

    返回结构化结果；**连接失败/HTTP 错误都以 status=error 表达**，
    不向上抛异常，避免前端只看到 500 而拿不到可读原因。
    """
    from apps.dsn.config import Config
    from apps.dsn_ui.config import UIConfig

    base_url = str(Config.TTS_BASE_URL or "").rstrip("/")
    architecture = _detect_tts_architecture(payload)
    endpoint = _tts_endpoint_for(architecture)

    # 可选：先确保 TTS 服务已拉起（默认不做，避免"点一下测试就起一个 GPU 服务"）
    if ensure_tts:
        try:
            from apps.dsn.models import resource_setup

            pool = resource_setup.setup_dsn_resources()
            pool.ensure_running("tts", timeout=int(getattr(Config, "TTS_LOAD_TIMEOUT", 300)))
        except Exception as e:  # noqa: BLE001
            logger.warning("测试前拉起 TTS 服务失败: %s", e)

    started = time.perf_counter()
    try:
        resp = _session().post(
            f"{base_url}{endpoint}",
            json=payload,
            timeout=float(UIConfig.TTS_REQUEST_TIMEOUT),
            headers={"Content-Type": "application/json"},
        )
    except Exception as e:  # noqa: BLE001
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        logger.warning("TTS 测试请求失败 (%s%s): %s", base_url, endpoint, e)
        return {
            "status": "error",
            "http_status": None,
            "endpoint": endpoint,
            "elapsed_ms": elapsed_ms,
            "error": (
                f"无法连接 TTS 服务 {base_url}{endpoint}: {e}。"
                "请确认 GPT-SoVITS 已在运行（或用 ensure_running=true 由资源池拉起）。"
            ),
            "payload_used": payload,
        }

    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    content_type = resp.headers.get("Content-Type")

    if resp.status_code >= 400:
        detail = (resp.text or "")[:500]
        logger.warning("TTS 测试请求返回 HTTP %s: %s", resp.status_code, detail)
        return {
            "status": "error",
            "http_status": resp.status_code,
            "endpoint": endpoint,
            "elapsed_ms": elapsed_ms,
            "content_type": content_type,
            "error": f"TTS 服务返回 HTTP {resp.status_code}: {detail}",
            "payload_used": payload,
        }

    audio = resp.content or b""
    cap = max(0, int(UIConfig.TTS_TEST_MAX_B64_BYTES))
    capped = audio[:cap] if cap else b""
    return {
        "status": "ok",
        "http_status": resp.status_code,
        "endpoint": endpoint,
        "elapsed_ms": elapsed_ms,
        "audio_bytes": len(audio),
        "audio_b64": base64.b64encode(capped).decode("ascii"),
        "audio_b64_truncated": len(audio) > len(capped),
        "content_type": content_type,
        "payload_used": payload,
    }

# ────────────────────────── 测试聊天 ──────────────────────────

#: 测试聊天默认提示词（尽量短，省 token、快返回）。
_TEST_CHAT_MESSAGE = "请只回复两个字：你好"


def _run_test_chat(
    base_url: str,
    api_key: str,
    model: str,
    message: str,
    extra_headers: dict,
) -> dict:
    """发一次最小非流式 chat completion，返回结构化结果（阻塞，放线程池）。

    成功与失败都以 status=ok|error 表达，不向上抛异常 —— 前端只需读 status。
    """
    from apps.dsn_ui.api_providers import chat_completion_url, resolve_chat_headers

    url = chat_completion_url(base_url)
    headers = resolve_chat_headers(api_key, extra_headers)
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": message}],
        "stream": False,
        "max_tokens": 64,
    }

    started = time.perf_counter()
    try:
        # 用 requests 直接发：这样能拿到真实 HTTP 状态与原始响应体，
        # 便于把"到底哪里不对"回给用户（openai SDK 会把细节包成异常）。
        resp = _session().post(url, json=payload, headers=headers, timeout=60.0)
    except Exception as e:  # noqa: BLE001
        elapsed = round((time.perf_counter() - started) * 1000, 1)
        logger.warning("测试聊天请求失败 (%s): %s", url, e)
        return {
            "ok": False, "status": "error", "url": url, "model": model,
            "elapsed_ms": elapsed, "http_status": None,
            "error": f"无法连接 {url}: {e}",
        }

    elapsed = round((time.perf_counter() - started) * 1000, 1)
    if resp.status_code >= 400:
        detail = (resp.text or "")[:500]
        return {
            "ok": False, "status": "error", "url": url, "model": model,
            "elapsed_ms": elapsed, "http_status": resp.status_code,
            "error": f"HTTP {resp.status_code}: {detail}",
        }

    try:
        data = resp.json()
        reply = (data.get("choices") or [{}])[0].get("message", {}).get("content")
    except Exception as e:  # noqa: BLE001
        return {
            "ok": False, "status": "error", "url": url, "model": model,
            "elapsed_ms": elapsed, "http_status": resp.status_code,
            "error": f"响应不是预期的 chat completion 结构: {e}",
        }

    return {
        "ok": True, "status": "ok", "url": url, "model": model,
        "elapsed_ms": elapsed, "http_status": resp.status_code,
        "reply": reply,
    }


# ────────────────────────── 路由注册 ──────────────────────────

def register_onboarding_routes(app: FastAPI, engine: Any = None) -> None:
    """把「配置新实例」相关路由注册到 FastAPI app。

    必须在 SPA catch-all（GET /{full_path:path}）**之前**调用，否则请求会被
    catch-all 吞掉、返回 index.html 而不是 JSON。

    参数 engine 可选：不传时按 app.state.engine -> 惰性创建 的顺序解析，
    因此 register_onboarding_routes(app) 也能独立工作。
    """

    # ── 1. GGUF 扫描 ──

    @app.get("/api/onboarding/scan-models")
    async def onboarding_scan_models():
        """发现磁盘上的候选 GGUF。返回 [{path, name, size_mb, quant, mmproj}]。"""
        try:
            models = await asyncio.to_thread(_scan_models)
        except Exception as e:  # noqa: BLE001
            logger.exception("扫描 GGUF 失败")
            return _bad(f"扫描模型失败: {e}", 500)
        return models

    # ── 2. 表单默认值 ──

    @app.get("/api/onboarding/local-defaults")
    async def onboarding_local_defaults(engine: str = "llama_cpp"):
        """返回本地引擎表单的默认字段值。"""
        engine_id = str(engine or "llama_cpp").strip().lower()
        if engine_id in ("llamacpp", "llama.cpp", "llama-cpp"):
            engine_id = "llama_cpp"
        if engine_id not in ("llama_cpp", "strata"):
            return _bad(f"不支持的 engine: {engine_id}（可选 llama_cpp / strata）")
        return {
            "engine": engine_id,
            "engines": [
                {"id": "llama_cpp", "label": "llama.cpp (GGUF)"},
                {"id": "strata", "label": "Strata"},
            ],
            "defaults": _local_defaults(engine_id),
            "profiles_dir": str(_profiles_dir()),
        }

    # ── 3. 注册本地模型 ──

    @app.post("/api/onboarding/local-model")
    async def onboarding_local_model(request: Request):
        """注册一个本地引擎模型（llama.cpp / Strata）并持久化 profile。"""
        body = await _json_body(request)
        if body is None:
            return _bad("请求体必须是 JSON 对象")
        try:
            eng_obj = _resolve_engine(app, engine)
        except Exception as e:  # noqa: BLE001
            logger.exception("解析 engine 失败")
            return _bad(f"引擎不可用: {e}", 500)
        try:
            return await asyncio.to_thread(_register_local_model, eng_obj, body)
        except Exception as e:  # noqa: BLE001
            logger.exception("注册本地模型异常")
            return _bad(f"注册本地模型失败: {e}", 500)

    # ── 4. 第三方 API 实例 ──

    @app.post("/api/onboarding/api-provider")
    async def onboarding_api_provider(request: Request):
        """创建/更新一个第三方 API provider，并即时注册其模型。"""
        from apps.dsn_ui.api_providers import (
            DEFAULT_BASE_URLS,
            VALID_PROTOCOLS,
            discover_models,
            discovered_model_name,
            public_view,
        )

        body = await _json_body(request)
        if body is None:
            return _bad("请求体必须是 JSON 对象")

        label = str(body.get("label") or "").strip()
        if not label:
            return _bad("缺少 label：请填写实例名称")
        protocol = str(body.get("protocol") or "chat").strip()
        if protocol not in VALID_PROTOCOLS:
            return _bad(f"不支持的协议: {protocol}（可选 {list(VALID_PROTOCOLS)}）")
        base_url = str(body.get("base_url") or "").strip() or DEFAULT_BASE_URLS.get(protocol, "")
        if not base_url:
            return _bad("缺少 base_url")
        api_key = str(body.get("api_key") or "")
        models = [str(m).strip() for m in (body.get("models") or []) if str(m).strip()]

        try:
            eng_obj = _resolve_engine(app, engine)
        except Exception as e:  # noqa: BLE001
            logger.exception("解析 engine 失败")
            return _bad(f"引擎不可用: {e}", 500)

        # 可选：留空 models 且 discover=true 时，主动向远端询问模型列表。
        # 发现失败**不再阻断保存**：很多兼容网关根本没有 /v1/models 端点，
        # 但 /v1/chat/completions 完全可用（这正是"未发现模型"的根因）。
        # 此时把原因回给前端，让用户改用手工填写模型 ID。
        discovery_error = None
        if _as_bool(body.get("discover"), False) and not models:
            try:
                models = await asyncio.to_thread(
                    discover_models,
                    protocol=protocol,
                    base_url=base_url,
                    api_key=api_key,
                    extra_headers=dict(body.get("extra_headers") or {}),
                )
            except Exception as e:  # noqa: BLE001
                discovery_error = str(e)
                logger.warning("模型发现失败（不阻断保存）: %s", e)
                if not _as_bool(body.get("allow_empty_models"), False):
                    # 除非调用方明确接受空模型列表，否则把可读原因回给前端，
                    # 由用户决定"手工填写模型 ID"还是放弃。
                    return _bad(discovery_error, 502)

        payload = {
            "label": label,
            "protocol": protocol,
            "base_url": base_url,
            "api_key": api_key,
            "models": models,
            "enabled": _as_bool(body.get("enabled"), True),
            "timeout": _as_int(body.get("timeout"), 300),
            "max_tokens": _as_int(body.get("max_tokens"), 4096),
        }
        if body.get("id"):
            payload["id"] = str(body["id"])
        if isinstance(body.get("extra_headers"), dict):
            payload["extra_headers"] = dict(body["extra_headers"])

        # 更新已有 provider 时，先清掉它旧的模型注册，否则改名/换模型列表后
        # 列表里会同时残留新旧两条（与 engine.unregister_provider_models 的注释一致）。
        existing = None
        if payload.get("id"):
            try:
                existing = eng_obj.provider_store.get(str(payload["id"]))
            except Exception:  # noqa: BLE001
                existing = None

        try:
            if existing:
                eng_obj.unregister_provider_models(str(payload["id"]), snapshot=existing)
            record = eng_obj.provider_store.upsert(payload)
            eng_obj.reload_api_providers()
        except Exception as e:  # noqa: BLE001
            logger.exception("保存 API provider 失败")
            return _bad(f"保存 API provider 失败: {e}", 500)

        names = [
            discovered_model_name(record.get("label") or label, str(m))
            for m in (record.get("models") or [])
        ]
        registered = [
            n for n in names if eng_obj.orchestrator.get_model_spec(n) is not None
        ]
        out = {
            "status": "ok",
            "provider": public_view(record),
            "registered": registered,
        }
        if discovery_error:
            out["discovery_error"] = discovery_error
        return out

    # ── 4b. 测试聊天：证明"没有 /models 也能用" ──

    @app.post("/api/onboarding/api-provider/test-chat")
    async def onboarding_api_provider_test_chat(request: Request):
        """向配置的端点发一次最小 chat completion，验证它真的可用。

        这就是 /v1/models 缺失时的"兜底验证手段"：只要这一步通过，
        用户就可以放心手工填写模型 ID 并保存。
        """
        from apps.dsn_ui.api_providers import (
            DEFAULT_BASE_URLS,
            VALID_PROTOCOLS,
            chat_completion_url,
            resolve_chat_headers,
        )

        body = await _json_body(request)
        if body is None:
            return _bad("请求体必须是 JSON 对象")

        protocol = str(body.get("protocol") or "chat").strip()
        if protocol not in VALID_PROTOCOLS:
            return _bad(f"不支持的协议: {protocol}（可选 {list(VALID_PROTOCOLS)}）")
        if protocol != "chat":
            return _bad(
                f"测试聊天目前仅支持 chat 协议（当前: {protocol}）"
            )

        base_url = str(body.get("base_url") or "").strip() or DEFAULT_BASE_URLS.get(protocol, "")
        if not base_url:
            return _bad("缺少 base_url")
        api_key = str(body.get("api_key") or "")

        model = body.get("model")
        if not model:
            # 没给模型就用该 provider 已保存的第一个模型
            pid = body.get("id")
            if pid:
                try:
                    eng_obj = _resolve_engine(app, engine)
                    saved = eng_obj.provider_store.get(str(pid)) or {}
                    saved_models = saved.get("models") or []
                    if saved_models:
                        model = saved_models[0]
                except Exception:  # noqa: BLE001
                    pass
        model = str(model or "").strip()
        if not model:
            return _bad("缺少 model：请填写要测试的模型 ID")

        message = str(body.get("message") or _TEST_CHAT_MESSAGE)

        try:
            result = await asyncio.to_thread(
                _run_test_chat,
                base_url,
                api_key,
                model,
                message,
                dict(body.get("extra_headers") or {}) if isinstance(body.get("extra_headers"), dict) else {},
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("测试聊天异常")
            return _bad(f"测试聊天异常: {e}", 500)
        return result

    # ── 5. TTS payload 读取 / 保存 ──

    @app.get("/api/tts/payload")
    async def tts_payload_get():
        """读取当前默认 TTS 请求体与音色 profile。"""
        try:
            return await asyncio.to_thread(_payload_state)
        except Exception as e:  # noqa: BLE001
            logger.exception("读取 TTS payload 失败")
            return _bad(f"读取 TTS payload 失败: {e}", 500)

    @app.post("/api/tts/payload")
    async def tts_payload_set(request: Request):
        """保存本实例的默认 TTS 请求体（写入 dsn_ui 自己的 data 目录）。"""
        body = await _json_body(request)
        if body is None:
            return _bad("请求体必须是 JSON 对象")
        payload = body.get("default_payload")
        if payload is None:
            payload = body.get("payload")
        if not isinstance(payload, dict):
            return _bad("缺少 default_payload（应为 JSON 对象）")
        try:
            path = _save_payload(payload)
        except Exception as e:  # noqa: BLE001
            logger.exception("保存 TTS payload 失败")
            return _bad(f"保存 TTS payload 失败: {e}", 500)
        logger.info("已保存 TTS 默认请求体: %s", path)
        return {"status": "ok", "payload": payload, "file": str(path)}

    # ── 6. TTS 测试请求 ──

    @app.post("/api/tts/test")
    async def tts_test(request: Request):
        """真实发起一次合成请求并返回结构化结果。

        成功/失败都以 HTTP 200 + status 字段返回（前端只需读 status）；
        只有请求体本身格式错误才 400。
        """
        body = await _json_body(request)
        if body is None:
            body = {}

        payload = body.get("payload")
        if not isinstance(payload, dict):
            payload = _load_saved_payload()
        if not isinstance(payload, dict):
            payload = _build_default_payload()
        payload = dict(payload)
        if not str(payload.get("text") or "").strip():
            payload["text"] = _TTS_TEST_TEXT

        ensure_tts = _as_bool(body.get("ensure_running"), False)
        try:
            result = await asyncio.to_thread(_run_tts_test, payload, ensure_tts)
        except Exception as e:  # noqa: BLE001
            logger.exception("TTS 测试请求异常")
            return _bad(f"TTS 测试请求异常: {e}", 500)
        return result

    logger.info(
        "配置新实例 API 已启用: /api/onboarding/* (scan-models, local-defaults, "
        "local-model, api-provider), /api/tts/* (payload, test)"
    )


__all__ = ["register_onboarding_routes"]




