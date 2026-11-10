# apps/dsn_study_cli/client.py
# HTTP 客户端 —— Bearer 认证 + SSE 解析 + 扫题三端点 + 语音/对话。
#
# 与 dsn CLI 的差异（迁移计划 6.4）：
#   - 认证：`Authorization: Bearer <DSN_STUDY_TOKEN>`（study 的 LocalAuthManager
#     只认这个头）；不调用 /api/personality/status、/api/auth/pairing/*。
#   - **不抄 dsn CLI 的 --no-auth bug**：study_CLI 不提供 no_auth 路径，
#     未配 token 时直接不带认证头（服务端 LocalAuthManager 默认放行 uid=1）。
#   - 新增扫题三端点：select_camera / quick / finish（批量录题主链路）。

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from typing import Optional

import requests

logger = logging.getLogger("study_cli.client")

CONNECT_TIMEOUT = 10
STREAM_TIMEOUT = (10, 120)


def iter_sse_lines(response):
    """解析 SSE 流 → yield (event, data_dict)。"""
    event = ""
    for raw in response.iter_lines(decode_unicode=True):
        if raw is None:
            continue
        line = raw.strip()
        if not line:
            event = ""
            continue
        if line.startswith("event:"):
            event = line.split(":", 1)[1].strip()
            continue
        if line.startswith("data:"):
            payload = line.split(":", 1)[1].strip()
            if payload == "[DONE]":
                yield (event or "done", {})
                return
            try:
                yield (event, json.loads(payload))
            except (json.JSONDecodeError, ValueError):
                yield (event, {"raw": payload})


class StudyClient:
    """dsn_study 服务端客户端（Bearer 认证）。"""

    def __init__(self, base: str, token: str = "", uid: int = 1):
        self.base = base.rstrip("/")
        self.token = (token or "").strip()
        self.uid = int(uid or 1)
        self.chat_id = 0
        self.session = requests.Session()
        self._send_queue: "queue.Queue[tuple]" = queue.Queue()
        self._send_thread: threading.Thread | None = None
        self._is_sending = threading.Event()
        #: 由 app 回填：异步任务轮询器
        self.async_poller = None
        #: 由 app 回填：TTS 播放队列（(text, audio_b64)）
        self.tts_queue: "queue.Queue" = queue.Queue()

    # ── 认证 ──

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def check_backend(self) -> bool:
        """连通性检查（心跳端点最轻）。"""
        try:
            r = self.session.get(f"{self.base}/api/heartbeat",
                                 headers=self._headers(), timeout=5)
            return r.status_code == 200
        except Exception:   # noqa: BLE001
            return False

    # ── 基础请求 ──

    def _post(self, path: str, body: dict, timeout=30) -> dict:
        try:
            r = self.session.post(f"{self.base}{path}", headers=self._headers(),
                                  json=body, timeout=timeout)
            if r.status_code >= 400:
                return {"success": False, "error": f"HTTP {r.status_code}",
                        "detail": r.text[:200]}
            try:
                return r.json() or {}
            except ValueError:
                return {"success": False, "error": "响应非 JSON",
                        "detail": r.text[:200]}
        except Exception as e:   # noqa: BLE001
            return {"success": False, "error": str(e)}

    def _get(self, path: str, timeout=30) -> dict:
        try:
            r = self.session.get(f"{self.base}{path}", headers=self._headers(),
                                 timeout=timeout)
            if r.status_code >= 400:
                return {"success": False, "error": f"HTTP {r.status_code}"}
            try:
                return r.json() or {}
            except ValueError:
                return {"success": False, "error": "响应非 JSON"}
        except Exception as e:   # noqa: BLE001
            return {"success": False, "error": str(e)}

    # ── 摄像头 / 扫题（批量录题主链路） ──

    def register_cameras(self, cameras: list[dict]) -> dict:
        """POST /api/vision/cameras —— 枚举结果上报。"""
        return self._post("/api/vision/cameras", {"cameras": cameras})

    def select_camera(self, frames: list[dict]) -> dict:
        """POST /api/scan/select_camera {frames:[{logical_name, image_data}]}
        → {success, logical_name}。"""
        return self._post("/api/scan/select_camera",
                          {"frames": frames}, timeout=60)

    def scan_quick(self, image_data: str, camera: str = "",
                   subject_code: str = "") -> dict:
        """POST /api/scan/quick —— 拍一张进当前批次（立即返回，后台提取）。"""
        return self._post("/api/scan/quick", {
            "image_data": image_data, "camera": camera,
            "chat_id": self.chat_id, "subject_code": subject_code,
        }, timeout=60)

    def scan_finish(self) -> dict:
        """POST /api/scan/finish —— 结束批次并汇总 → {task_id, count}。"""
        return self._post("/api/scan/finish", {"chat_id": self.chat_id})

    # ── 对话 / 语音 ──

    def send_text(self, message: str, image_data: str = "",
                  tts_enabled: bool = True) -> Optional[str]:
        """POST /api/chat/stream_send（SSE）→ 打印并返回最终回复。"""
        body = {"message": message, "chat_id": self.chat_id,
                "chat_name": "study-cli", "tts_enabled": tts_enabled,
                "is_asr_input": False}
        if image_data:
            body["image_data"] = image_data
        return self._stream_chat("/api/chat/stream_send", body)

    def send_audio(self, audio_b64: str) -> Optional[str]:
        """POST /api/asr/passthrough（SSE）→ 识别并对话。"""
        body = {"audio_b64": audio_b64, "chat_id": self.chat_id,
                "chat_name": "study-cli"}
        return self._stream_chat("/api/asr/passthrough", body)

    def send_async(self, message: str) -> dict:
        """POST /api/chat/async_send → {task_id}。"""
        out = self._post("/api/chat/async_send",
                         {"message": message, "chat_id": self.chat_id})
        task_id = out.get("task_id")
        if task_id and self.async_poller is not None:
            self.async_poller.add_task(task_id)
        return out

    def task_status(self, task_id: str) -> dict:
        return self._get(f"/api/task/status/{task_id}", timeout=10)

    def heartbeat(self) -> dict:
        return self._get("/api/heartbeat", timeout=10)

    # ── 发送队列（录音结束的发送不阻塞主循环） ──

    def start_sender(self):
        if self._send_thread is None:
            self._send_thread = threading.Thread(
                target=self._send_worker, daemon=True, name="cli-sender")
            self._send_thread.start()

    def _send_worker(self):
        while True:
            kind, payload = self._send_queue.get()
            self._is_sending.set()
            try:
                if kind == "audio":
                    self.send_audio(payload)
                else:
                    self.send_text(payload)
            finally:
                self._is_sending.clear()

    def send_text_async(self, message: str):
        self._send_queue.put(("text", message))

    def send_audio_async(self, audio_b64: str):
        self._send_queue.put(("audio", audio_b64))

    @property
    def is_sending(self) -> bool:
        return self._is_sending.is_set()

    # ── SSE 流处理 ──

    def _stream_chat(self, path: str, body: dict) -> Optional[str]:
        """发起 SSE 请求并逐事件处理，返回最终回复文本。

        延迟埋点：t_first（首个事件）/ t_audio（音频就绪）。
        服务端 ASR 路径是「LLM 全量 + TTS 全量 完成后才吐第一个事件」，
        所以这两个时间戳基本等于「用户说完话 → 声音能播出来」的延迟。
        """
        final_reply = ""
        t0 = time.perf_counter()
        t_first = None
        t_audio = None
        try:
            r = self.session.post(f"{self.base}{path}", headers=self._headers(),
                                  json=body, stream=True,
                                  timeout=STREAM_TIMEOUT)
            if r.status_code == 403:
                print("（服务端语音通道未开启）")
                return None
            if r.status_code >= 400:
                print(f"（服务端错误 HTTP {r.status_code}）")
                return None
            for event, data in iter_sse_lines(r):
                if t_first is None:
                    t_first = time.perf_counter()
                    logger.info("SSE 首包 %.3fs (path=%s)", t_first - t0, path)
                # 服务端 ASR 路径发的是 {"status": "text_ready", ...}，
                # 没有 type 键 —— 早先只认 type/event，导致文本回复被丢弃。
                etype = data.get("type") or data.get("status") or event
                if etype in ("heartbeat", "progress"):
                    continue
                if etype in ("instant_reply", "main_reply", "reply",
                             "text_ready"):
                    text = data.get("reply") or data.get("text") or ""
                    if text:
                        final_reply = text
                        print(f"\nAI: {text}")
                    cid = data.get("chat_id")
                    if cid:
                        self.chat_id = int(cid)
                elif "audio_b64" in data:
                    audio = data.get("audio_b64")
                    if audio:
                        if t_audio is None:
                            t_audio = time.perf_counter()
                            logger.info("音频就绪 %.3fs (首包后 %.3fs)",
                                        t_audio - t0, t_audio - t_first)
                        if self.tts_queue is not None:
                            self.tts_queue.put((final_reply or
                                                data.get("text", ""), audio))
                elif etype in ("tool_error", "error", "asr_error"):
                    err = data.get("error") or data.get("message") or ""
                    if err:
                        print(f"\n（错误: {err}）")
                elif etype in ("completed", "done", "cancelled"):
                    break
        except requests.exceptions.Timeout:
            print("（服务端响应超时）")
        except Exception as e:   # noqa: BLE001
            print(f"（连接失败: {e}）")
        return final_reply or None
