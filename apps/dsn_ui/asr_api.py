# apps/dsn_ui/asr_api.py
"""ASR（语音识别）HTTP API —— POST /api/asr/recognize。

语义对齐 apps/dsn/api/app.py:285-306（Flask 版），但由 dsn_ui 的 FastAPI
提供，并统一走 harness 外周资源池：

    * 首次请求时惰性 setup_dsn_resources()（幂等）：资源池把 ASR 注册为
      进程内 FunASR 资源（InProcessModelLauncher，resident=True）；
    * pool.ensure_running("asr", timeout=Config.ASR_LOAD_TIMEOUT) 触达
      调度器的加载路径（含插槽驱逐），随后取回已加载的模型对象；
    * FunASR 的 model.generate(...) 是阻塞调用，一律放线程池执行，
      绝不冻结事件循环。

错误契约（与前端冻结约定一致）：
    400 {"error": "Missing audio file"}   —— 请求里没有 audio 文件字段
    403 {"error": "ASR disabled"}         —— Config.ASR_ENABLED 为 false
    503 {"error": ...}                    —— 资源未注册 / 加载失败 / 识别异常
    200 {"text": str}                     —— 识别成功
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("DSNUIServer")


def register_asr_routes(app: FastAPI) -> None:
    """把 ASR 路由注册到 FastAPI app。

    调用方必须在 SPA catch-all（GET /{full_path:path}）**之前**调用本函数，
    否则请求会被 catch-all 吞掉、返回 index.html 而不是 JSON。
    """

    @app.post("/api/asr/recognize")
    async def asr_recognize(request: Request):
        from apps.dsn.config import Config

        # 1) 解析 multipart 表单。缺 audio 字段优先返回 400：这是「录音为空」
        #    的一等错误，前端据此提示重新录制；不能先报 ASR 未启用。
        try:
            form = await request.form()
        except Exception as e:  # noqa: BLE001 - 非表单 body / multipart 解析失败
            logger.warning("解析 ASR 上传表单失败: %s", e)
            return JSONResponse(status_code=400, content={"error": "Missing audio file"})

        upload = form.get("audio")
        if upload is None:
            return JSONResponse(status_code=400, content={"error": "Missing audio file"})

        try:
            audio_bytes = await upload.read()
        except Exception as e:  # noqa: BLE001
            logger.warning("读取 ASR 上传音频失败: %s", e)
            return JSONResponse(status_code=400, content={"error": "Missing audio file"})

        # 2) ASR 未启用（Config.ASR_ENABLED 默认即 false）。
        if not bool(getattr(Config, "ASR_ENABLED", False)):
            return JSONResponse(status_code=403, content={"error": "ASR disabled"})

        # 3) 惰性装配资源池，并确认 ASR 已注册（注册可能因依赖/显存而失败）。
        try:
            from apps.dsn.models import resource_setup

            pool = getattr(app.state, "resource_pool", None)
            if pool is None:
                pool = resource_setup.setup_dsn_resources()
                app.state.resource_pool = pool
        except Exception as e:  # noqa: BLE001
            logger.exception("初始化 ASR 资源池失败")
            return JSONResponse(
                status_code=503, content={"error": f"ASR 资源池初始化失败: {e}"}
            )

        if pool is None or pool.get_spec("asr") is None:
            return JSONResponse(
                status_code=503,
                content={"error": "ASR 资源未注册（ASR_ENABLED 已开启但模型注册失败）"},
            )

        # 4) 确保资源已加载（阻塞，放线程池）。
        timeout = int(getattr(Config, "ASR_LOAD_TIMEOUT", 300))
        try:
            loaded = await asyncio.to_thread(pool.ensure_running, "asr", timeout=timeout)
        except Exception as e:  # noqa: BLE001
            logger.exception("加载 ASR 资源失败")
            return JSONResponse(status_code=503, content={"error": f"ASR 加载失败: {e}"})
        if not loaded:
            return JSONResponse(status_code=503, content={"error": "ASR 加载失败或超时"})

        engine = resource_setup.get_asr_engine()
        model = engine.get_model() if engine is not None else None
        if model is None:
            return JSONResponse(status_code=503, content={"error": "ASR 模型未就绪"})

        # 5) 识别（阻塞调用，放线程池）。
        def _recognize() -> str:
            res = model.generate(
                input=audio_bytes,
                use_itn=True,
                batch_size_s=Config.ASR_BATCH_SIZE_SECONDS,
                language="zh",
            )
            return str(res[0].get("text", "")).strip() if res else ""

        try:
            text = await asyncio.to_thread(_recognize)
        except Exception as e:  # noqa: BLE001
            logger.exception("ASR 识别失败")
            return JSONResponse(
                status_code=503, content={"error": f"ASR processing failed: {e}"}
            )

        return {"text": text}
