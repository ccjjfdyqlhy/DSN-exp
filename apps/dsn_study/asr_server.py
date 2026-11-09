#!/usr/bin/env python3
# apps/dsn_study/asr_server.py
# ASR 旁路服务（sidecar）—— FunASR 语音识别的独立 HTTP 服务。
#
# 为什么是 sidecar 而不是进程内：
#   宿主 python 没装 torch/funasr（`import torch` 直接失败），
#   而 conda 环境 GPTSoVits 里 funasr 1.4.16 / torch 2.8.0+cu128 齐备。
#   因此把模型放进**独立进程**，由 infra.resources.ResourcePool 用
#   LaunchMode.CONDA 拉起（与 GPT-SoVITS 的托管方式完全一致）。
#
# 契约（供 apps/dsn_study/models/asr_client.py 调用）：
#   GET  /health   → 200 {"ready":true,"loaded":bool,"model":...,"device":...,"error":...}
#   POST /warmup   → 200 {"loaded":true,...}（阻塞直到模型加载完或超时）
#   POST /asr      → 200 {"text":"...","segments":[...],"elapsed":0.12}
#                    body 二选一：原始音频字节（application/octet-stream）
#                               或 JSON {"audio_b64":"..."}
#
# 错误语义：**永不 500 带栈回显**。模型加载失败/OOM 一律 503 + 中文提示，
# 让上层能区分"服务没起来"与"音频有问题"。
#
# 用法：
#   conda run -n GPTSoVits --cwd <dir> --no-capture-output \
#       <env python> asr_server.py --port 9881 --device cuda:1
#
# 本模块**只依赖标准库**（funasr/torch 在加载模型时才 import），
# 因此在任何 python 下都能安全 import（便于宿主侧测试）。

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logger = logging.getLogger("ASRServer")

#: FunASR 模型版本锁定（与参考实现 apps/dsn/models/asr_engine.py:26-31 一致）
ASR_MODEL = "paraformer-zh"
ASR_MODEL_REVISION = "v2.0.4"
ASR_VAD_MODEL = "fsmn-vad"
ASR_VAD_MODEL_REVISION = "v2.0.4"
ASR_PUNC_MODEL = "ct-punc-c"
ASR_PUNC_MODEL_REVISION = "v2.0.4"

#: 单次识别的最长音频（秒），与宿主侧 ASR_BATCH_SIZE_SECONDS 对齐
DEFAULT_BATCH_SIZE_SECONDS = 60


class ASRModel:
    """懒加载的 FunASR 模型持有者。

    线程安全：首次加载用一把锁串行化，避免并发请求重复拉起模型。
    """

    def __init__(self, device: str = "cuda", batch_size_seconds: int = DEFAULT_BATCH_SIZE_SECONDS):
        self.device = device
        self.batch_size_seconds = int(batch_size_seconds)
        self._model = None
        self._lock = threading.RLock()
        self._load_error = ""
        self._loading = False

    # ── 生命周期 ──

    @property
    def loaded(self) -> bool:
        return self._model is not None

    @property
    def load_error(self) -> str:
        return self._load_error

    @property
    def loading(self) -> bool:
        return self._loading

    def ensure_loaded(self) -> bool:
        """确保模型已加载。成功返回 True；失败返回 False 并记录原因。"""
        if self._model is not None:
            return True
        with self._lock:
            if self._model is not None:
                return True
            self._loading = True
            try:
                logger.info("加载 ASR 模型 (device=%s)...", self.device)
                t0 = time.perf_counter()
                # 延迟导入：模块导入期绝不拉起 torch/funasr
                from funasr import AutoModel

                self._model = AutoModel(
                    model=ASR_MODEL, model_revision=ASR_MODEL_REVISION,
                    vad_model=ASR_VAD_MODEL, vad_model_revision=ASR_VAD_MODEL_REVISION,
                    punc_model=ASR_PUNC_MODEL, punc_model_revision=ASR_PUNC_MODEL_REVISION,
                    device=self.device,
                    disable_update=True, disable_pbar=True,
                )
                logger.info("ASR 模型加载完成 (%.1fs)", time.perf_counter() - t0)
                self._load_error = ""
                return True
            except Exception as e:  # noqa: BLE001 —— 加载失败是常态（缺依赖/OOM）
                self._load_error = "%s: %s" % (type(e).__name__, e)
                logger.error("ASR 模型加载失败: %s", self._load_error, exc_info=True)
                # 允许下次重试（显存可能已被释放）
                self._model = None
                return False
            finally:
                self._loading = False

    # ── 识别 ──

    def transcribe(self, audio_bytes: bytes) -> tuple[str, list]:
        """识别音频，返回 (text, segments)。失败抛异常由调用方兜底。"""
        if not audio_bytes:
            return "", []
        if not self.ensure_loaded():
            raise RuntimeError("ASR 模型不可用: %s" % (self._load_error or "未知原因"))
        res = self._model.generate(
            input=audio_bytes,
            use_itn=True,
            batch_size_s=self.batch_size_seconds,
            language="zh",
        )
        if not res:
            return "", []
        first = res[0] or {}
        text = (first.get("text") or "").strip()
        segments = first.get("timestamp") or first.get("segments") or []
        if not isinstance(segments, list):
            segments = []
        return text, segments


class ASRHandler(BaseHTTPRequestHandler):
    """HTTP 处理器。model 由 main() 注入到类属性上。"""

    server_version = "DSNStudyASR/1.0"
    #: 由 main() 设置
    model: ASRModel = None  # type: ignore[assignment]

    # 静音默认的 stderr 日志（我们自己有 logger）
    def log_message(self, fmt, *args):  # noqa: A003
        logger.debug("%s - %s", self.address_string(), fmt % args)

    # ── 响应helper ──

    def _send_json(self, code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _send_error_json(self, code: int, message: str, **extra):
        payload = {"error": message}
        payload.update(extra)
        self._send_json(code, payload)

    # ── 路由 ──

    def do_GET(self):  # noqa: N802
        if self.path.split("?")[0] == "/health":
            self._send_json(200, {
                "ready": True,
                "loaded": bool(self.model and self.model.loaded),
                "loading": bool(self.model and self.model.loading),
                "model": ASR_MODEL,
                "device": self.model.device if self.model else "",
                "error": self.model.load_error if self.model else "",
            })
            return
        self._send_error_json(404, "未知路径")

    def do_POST(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path == "/asr":
            self._handle_asr()
            return
        if path == "/warmup":
            self._handle_warmup()
            return
        self._send_error_json(404, "未知路径")

    def _handle_warmup(self):
        ok = self.model.ensure_loaded() if self.model else False
        if not ok:
            self._send_error_json(503, "ASR 模型加载失败",
                                  error_detail=self.model.load_error if self.model else "")
            return
        self._send_json(200, {
            "loaded": True, "model": ASR_MODEL, "device": self.model.device,
        })

    def _handle_asr(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            length = 0
        raw = self.rfile.read(length) if length > 0 else b""

        content_type = (self.headers.get("Content-Type") or "").lower()
        audio_bytes = b""
        if "application/json" in content_type:
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except Exception:
                self._send_error_json(400, "请求体不是合法 JSON")
                return
            b64 = data.get("audio_b64") or data.get("audio") or ""
            if not b64:
                self._send_error_json(400, "缺少 audio_b64")
                return
            try:
                audio_bytes = base64.b64decode(b64)
            except Exception:
                self._send_error_json(400, "Invalid base64")
                return
        else:
            audio_bytes = raw

        if not audio_bytes:
            self._send_error_json(400, "缺少音频数据")
            return

        t0 = time.perf_counter()
        try:
            text, segments = self.model.transcribe(audio_bytes)
        except RuntimeError as e:
            # 模型不可用（加载失败/OOM）→ 503，不是 500
            self._send_error_json(503, "ASR 服务不可用: %s" % e)
            return
        except Exception as e:  # noqa: BLE001
            logger.error("ASR 识别异常: %s", e, exc_info=True)
            self._send_error_json(500, "ASR 识别失败: %s" % e)
            return

        self._send_json(200, {
            "text": text,
            "segments": segments,
            "elapsed": round(time.perf_counter() - t0, 3),
        })


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="asr_server.py",
        description="DSN-Study ASR 旁路服务（FunASR paraformer-zh）")
    p.add_argument("--host", default="127.0.0.1", help="监听地址（默认仅本机）")
    p.add_argument("--port", type=int, default=9881, help="监听端口")
    p.add_argument("--device", default="cuda", help="推理设备，如 cuda / cuda:1 / cpu")
    p.add_argument("--batch-size-seconds", type=int, default=DEFAULT_BATCH_SIZE_SECONDS,
                   help="单次识别的最长音频（秒）")
    p.add_argument("--preload", action="store_true",
                   help="启动即加载模型（默认懒加载：首次 /asr 请求时加载）")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    model = ASRModel(device=args.device,
                     batch_size_seconds=args.batch_size_seconds)
    ASRHandler.model = model

    if args.preload:
        threading.Thread(target=model.ensure_loaded, daemon=True,
                         name="asr-preload").start()

    httpd = ThreadingHTTPServer((args.host, args.port), ASRHandler)
    httpd.daemon_threads = True
    logger.info("ASR 服务启动: http://%s:%d (device=%s, 模型懒加载)",
                args.host, args.port, args.device)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("ASR 服务收到中断，退出")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
