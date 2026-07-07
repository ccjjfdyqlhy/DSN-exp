"""
ASR 独立服务 — 基于 ASRStep 的 Flask HTTP API

提供两个端点:
  POST /api/asr/recognize     接收音频文件 → 返回识别文本
  POST /api/asr/recognize_b64 接收 base64 音频 → 返回识别文本

用法:
    python asr_server.py [--port 5001] [--device cuda]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import flask
from flask import Flask, jsonify, request

# 确保上级目录在 sys.path 中，以便导入 steps.ASR
_HERE = Path(__file__).resolve().parent
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))

from steps.ASR import ASRStep

logger = logging.getLogger("asr_server")

app = Flask(__name__)
asr: ASRStep | None = None


@app.route("/api/asr/recognize", methods=["POST"])
def recognize():
    """接收音频文件 (multipart/form-data)，返回识别文本。

    请求:
        audio: 音频文件字段

    响应 (JSON):
        {"text": "..."}  或  {"error": "..."}
    """
    global asr
    if asr is None:
        return jsonify({"error": "ASR 模型未加载"}), 503

    if "audio" not in request.files:
        return jsonify({"error": "缺少 audio 字段"}), 400

    audio_bytes = request.files["audio"].read()
    if not audio_bytes:
        return jsonify({"error": "音频内容为空"}), 400

    text = asr.recognize(audio_bytes, use_filter=False)
    return jsonify({"text": text})


@app.route("/api/asr/recognize_b64", methods=["POST"])
def recognize_b64():
    """接收 base64 编码的音频 (JSON)，返回识别文本。

    请求 (JSON):
        {"audio_b64": "base64..."}

    响应 (JSON):
        {"text": "..."}  或  {"error": "..."}
    """
    global asr
    if asr is None:
        return jsonify({"error": "ASR 模型未加载"}), 503

    data = request.get_json(silent=True)
    if not data or "audio_b64" not in data:
        return jsonify({"error": "缺少 audio_b64 字段"}), 400

    text = asr.recognize_b64(data["audio_b64"], use_filter=False)
    return jsonify({"text": text})


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "model_loaded": asr is not None})


def main():
    parser = argparse.ArgumentParser(description="ASR 独立服务")
    parser.add_argument("--port", type=int, default=5001)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s [%(levelname).1s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    global asr
    logger.info("正在加载 FunASR 模型 (device=%s)...", args.device)
    asr = ASRStep(device=args.device)
    logger.info("ASR 服务就绪 → http://%s:%d", args.host, args.port)

    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)


if __name__ == "__main__":
    main()
