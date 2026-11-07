# apps/dsn/CLI/client.py
# DSNClient — 后端 API 客户端：认证 / HTTP / SSE 流处理 / 发送与 TTS 队列。
#
# 从原 psychoscope/minimal.py 抽出（DSNClient + iter_sse_lines）。
# 两处调整：
#   - 全部 HTTP 走 requests.Session（keep-alive 连接复用，心跳等高频轮询受益）
#   - TTS 播放线程抽出为 audio.TtsPlayer（本模块只持有队列与停止信号）

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from typing import Optional

import requests

from .audio import TtsPlayer, _play_beep
from .config import CONFIG_FILE, load_config, save_config
from .env import HAS_AUDIO, log


def iter_sse_lines(response: requests.Response):
    event = ""
    for line in response.iter_lines(decode_unicode=True):
        if line is None:
            continue
        if line.startswith("event: "):
            event = line[7:].strip()
        elif line.startswith("data: "):
            data_str = line[6:]
            if data_str == "[DONE]":
                yield event, {}
                continue
            try:
                data = json.loads(data_str)
                status = data.get("status", "?")
                if status in ("line", "text_ready", "completed"):
                    log.info("[DEBUG_SSE] iter_sse_lines: 收到 status=%s, t=%.4f",
                             status, time.perf_counter())
                yield event, data
            except json.JSONDecodeError:
                yield event, {"raw": data_str}
        elif line == "":
            event = ""


# ════════════════════════════════════════════════════════════════
# DSNClient — API 客户端
# ════════════════════════════════════════════════════════════════

class DSNClient:
    def __init__(self, host: str, port: int):
        self.base = f"http://{host}:{port}"
        self.api_key: Optional[str] = None
        self.uid: int = 0
        self.chat_id: Optional[int] = None
        self.display_name: str = ""
        self._session = requests.Session()   # keep-alive：心跳/轮询复用连接
        self._tts_queue: queue.Queue = queue.Queue()
        self._send_queue: queue.Queue = queue.Queue()
        self._volume = 1.0
        self.async_poller = None
        self._player = None  # MusicPlayer，由 app 装配后回填
        self._tts_stop = threading.Event()
        self._sending = threading.Event()
        if HAS_AUDIO:
            self._tts = TtsPlayer(self._tts_queue, self._tts_stop,
                                  music_lookup=lambda: self._player)
            self._tts.start()
        self._send_thread = threading.Thread(target=self._send_worker, daemon=True)
        self._send_thread.start()

    def stop_tts(self):
        self._tts_stop.set()
        while not self._tts_queue.empty():
            try:
                self._tts_queue.get_nowait()
                self._tts_queue.task_done()
            except queue.Empty:
                break

    def authenticate(self, code: str = "", name: str = "") -> bool:
        cfg = load_config()
        self.display_name = name or cfg.get("display_name", "")
        self.uid = cfg.get("uid", 0)
        self.chat_id = cfg.get("chat_id")

        api_key = cfg.get("api_key", "")
        if api_key:
            print(f"  Checking local API Key (User: {self.display_name})...")
            self.api_key = api_key
            if self._verify_api_key():
                self.uid = cfg.get("uid", 0)
                self.display_name = cfg.get("display_name", "")
                print(f"  API Key OK (uid={self.uid})")
                return True
            print("  API Key invalid, need re-registration")
            self.api_key = None
            cfg.pop("api_key", None)
            cfg.pop("uid", None)
            save_config(cfg)

        if not code:
            return False

        if not self.display_name:
            self.display_name = input("  Your Name: ").strip() or "edge-cli"

        has_pairing = False
        try:
            r = self._session.get(f"{self.base}/api/auth/pairing/status", timeout=5)
            if r.status_code == 200:
                has_pairing = r.json().get("active", False)
        except Exception:
            logging.getLogger(__name__).warning("Parse operation failed", exc_info=True)

        if not has_pairing:
            print("  No active pairing code on server.")
            print("  Type /newbind in server console.")
            return False

        print(f"  Submitting pairing code (code={code}, name={self.display_name})...")
        try:
            resp = self._session.post(
                f"{self.base}/api/auth/pairing/verify",
                json={"code": code, "display_name": self.display_name, "is_admin": True},
                timeout=30,
            )
            if resp.status_code != 200:
                print("  Pairing failed")
                return False

            data = resp.json()
            session_id = data["session_id"]
            self.uid = data["uid"]
            self.display_name = data.get("display_name", self.display_name)
        except Exception as e:
            print(f"  Connection error: {e}")
            return False

        print("  Creating API Key...")
        try:
            resp = self._session.post(
                f"{self.base}/api/auth/api-key/create",
                headers={"Authorization": f"Session {session_id}"},
                json={"name": "edge-cli", "scopes": "read write"},
                timeout=30,
            )
            if resp.status_code != 200:
                print("  Failed to create API Key")
                return False

            data = resp.json()
            self.api_key = data["key"]
            cfg["api_key"] = self.api_key
            cfg["uid"] = self.uid
            cfg["display_name"] = self.display_name
            save_config(cfg)
            print(f"  API Key saved to {CONFIG_FILE}")
            return True
        except Exception as e:
            print(f"  Error creating API Key: {e}")
            return False

    def _verify_api_key(self) -> bool:
        if not self.api_key:
            return False
        try:
            resp = self._session.get(
                f"{self.base}/api/personality/status",
                headers={"X-DSN-API-Key": self.api_key},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                uid = data.get("uid", 0)
                if uid > 0:
                    self.uid = uid
                    return True
            return False
        except Exception:
            return False

    def _headers(self) -> dict:
        if self.api_key:
            return {"X-DSN-API-Key": self.api_key}
        return {}

    def _http_get(self, path: str, **kwargs) -> requests.Response:
        return self._session.get(f"{self.base}{path}", headers=self._headers(),
                                 timeout=kwargs.pop("timeout", 30), **kwargs)

    def _http_post(self, path: str, **kwargs) -> requests.Response:
        return self._session.post(f"{self.base}{path}", headers=self._headers(),
                                  timeout=kwargs.pop("timeout", 30), **kwargs)

    def _http_post_stream(self, path: str, **kwargs) -> requests.Response:
        return self._session.post(f"{self.base}{path}", headers=self._headers(),
                                  stream=True, timeout=(10, 120), **kwargs)

    def _set_chat_id(self, chat_id):
        """更新并持久化 chat_id：一旦从服务端学到就写回配置文件，
        避免重启后配置丢失 chat_id 导致服务端新建聊天、割裂跨天记忆。"""
        chat_id = chat_id or None
        if chat_id and chat_id != self.chat_id:
            self.chat_id = chat_id
            try:
                cfg = load_config()
                cfg["chat_id"] = chat_id
                save_config(cfg)
            except Exception:
                log.warning("保存 chat_id=%s 到配置失败", chat_id, exc_info=True)

    def send_async(self, message: str) -> Optional[str]:
        if not self.api_key or not message.strip():
            return None
        try:
            resp = self._http_post("/api/chat/async_send", json={
                "message": message,
                "chat_id": self.chat_id,
            })
            if resp.status_code == 202:
                data = resp.json()
                return data.get("task_id")
            log.warning("Async send HTTP %d: %s", resp.status_code, resp.text[:200])
            return None
        except Exception as e:
            log.error("Async send failed: %s", e)
            return None

    def send_audio(self, audio_b64: str) -> Optional[str]:
        if not self.api_key:
            return None

        t0 = time.perf_counter()
        log.info("[DEBUG_CLI] send_audio: 开始 SSE 请求, t=%.4f", t0)

        try:
            resp = self._http_post_stream(
                "/api/asr/passthrough",
                json={
                    "audio_b64": audio_b64,
                    "chat_id": self.chat_id,
                    "chat_name": "edge-cli",
                },
            )
            if resp.status_code != 200:
                return None

            reply_text, t_first_audio = self._handle_sse_stream(resp, self._tts_queue, t0, async_poller=self.async_poller)
            elapsed = time.perf_counter() - t0
            log.info("[DEBUG_CLI] send_audio: SSE 流结束, t=%.4f, 总耗时=%.1fs", time.perf_counter(), elapsed)

            if t_first_audio is not None:
                first_audio_ms = (t_first_audio - t0) * 1000
                print(f"\n  \U0001f50a 首条音频: {first_audio_ms:.0f}ms")

            minutes = int(elapsed) // 60
            seconds = int(elapsed) % 60
            if minutes > 0:
                print(f"\n  \u23f1  {minutes}分{seconds}秒")
            else:
                print(f"\n  \u23f1  {seconds}秒")

            return reply_text
        except Exception as e:
            log.error("Audio send failed: %s", e)
            return None

    def send_text(self, message: str) -> Optional[str]:
        if not self.api_key or not message.strip():
            return None

        t0 = time.perf_counter()
        log.info("[DEBUG_CLI] send_text: 开始 SSE 请求, t=%.4f", t0)

        try:
            resp = self._http_post_stream(
                "/api/chat/stream_send",
                json={
                    "message": message,
                    "chat_id": self.chat_id,
                    "chat_name": "edge-cli",
                    "tts_enabled": True,
                    "is_asr_input": False,
                },
            )
            if resp.status_code != 200:
                log.warning("Text send HTTP %d: %s", resp.status_code, resp.text[:200])
                return None

            reply_text, t_first_audio = self._handle_sse_stream(
                resp, self._tts_queue, t0, async_poller=self.async_poller)
            elapsed = time.perf_counter() - t0
            log.info("[DEBUG_CLI] send_text: SSE 流结束, 总耗时=%.1fs", elapsed)

            if t_first_audio is not None:
                first_audio_ms = (t_first_audio - t0) * 1000
                print(f"\n  \U0001f50a 首条音频: {first_audio_ms:.0f}ms")

            return reply_text
        except Exception as e:
            log.error("Text send failed: %s", e)
            return None

    @property
    def is_sending(self) -> bool:
        return self._sending.is_set()

    def send_audio_async(self, audio_b64: str):
        self._send_queue.put(("audio", audio_b64))

    def send_text_async(self, message: str):
        self._send_queue.put(("text", message))

    def _send_worker(self):
        while True:
            item = self._send_queue.get()
            if item is None:
                self._send_queue.task_done()
                continue
            kind, payload = item
            self._sending.set()
            try:
                if kind == "audio":
                    self.send_audio(payload)
                elif kind == "text":
                    self.send_text(payload)
            except Exception:
                log.exception("Send worker error")
            finally:
                self._sending.clear()
                self._send_queue.task_done()

    def _handle_sse_stream(self, resp: requests.Response,
                           tts_queue: queue.Queue | None = None,
                           t_start: float = None,
                           async_poller=None) -> tuple[Optional[str], float]:
        reply = ""
        got_text = False
        t_first_audio = None
        _last_event = time.time()
        _SSE_WATCHDOG = 60  # 秒，距上次事件超过此值强制退出
        _saw_completed = False
        _saw_cancelled = False

        for _evt_type, data in iter_sse_lines(resp):
            # 看门狗：太久没收到事件 → 放弃
            if time.time() - _last_event > _SSE_WATCHDOG:
                log.warning("SSE 看门狗触发: %d 秒无事件，强制退出", _SSE_WATCHDOG)
                break
            _last_event = time.time()
            status = data.get("status", "")

            if status == "async_task":
                task_id = data.get("task_id", "")
                if task_id and async_poller:
                    async_poller.add_task(task_id)
                continue

            if status == "instant_reply":
                reply = data.get("reply", "")
                if reply:
                    print(f"\n  \U0001f4ac {reply}")
                audio_b64 = data.get("audio_b64", "")
                if audio_b64 and HAS_AUDIO and tts_queue is not None:
                    if t_first_audio is None:
                        t_first_audio = time.perf_counter()
                    tts_queue.put((reply, audio_b64))
                continue

            if status == "main_started":
                tid = data.get("task_id", "")
                desc = data.get("description", "")
                print(f"\n  \u2699\ufe0f 主模型启动 [{tid[:8]}] {desc}")
                continue

            if status == "progress":
                text = data.get("text", "")
                tid = data.get("task_id", "")
                if text:
                    print(f"\n  \U0001f504 [{tid[:8]}] {text}")
                audio_b64 = data.get("audio_b64", "")
                if audio_b64 and HAS_AUDIO and tts_queue is not None:
                    tts_queue.put((text, audio_b64))
                continue

            if status == "main_reply":
                reply = data.get("reply", "")
                tid = data.get("task_id", "")
                got_text = True
                self._set_chat_id(data.get("chat_id"))
                if reply:
                    print(f"\n  \U0001f4ac [{tid[:8]}] {reply}")
                audio_b64 = data.get("audio_b64", "")
                if audio_b64 and HAS_AUDIO and tts_queue is not None:
                    tts_queue.put((reply, audio_b64))
                continue

            if status == "cancelled":
                tid = data.get("task_id", "")
                _saw_cancelled = True
                _play_beep(self, 220)
                print(f"\n  \u26d4 任务已取消 [{tid[:8]}]")
                continue

            if status == "tool_error":
                # 工具调用失败 → 经 VLC 播报错误提示音（低音×2），盲打可感知
                tool = data.get("tool", "")
                err = data.get("error", "")
                _play_beep(self, 220)
                _play_beep(self, 220)
                print(f"\n  \u26a0\ufe0f 工具出错: {tool} — {err}")
                continue

            if status == "heartbeat":
                continue

            if status == "text_ready":
                reply = data.get("reply", "")
                got_text = True
                self._set_chat_id(data.get("chat_id"))
                log.info("[DEBUG_CLI] text_ready 收到, reply[:60]=%r, t=%.4f",
                         reply[:60], time.perf_counter())
                if reply:
                    print(f"\n  \U0001f4ac {reply}")

            elif status == "narrative_update":
                text = data.get("text", "")
                speaker = data.get("speaker", "")
                if speaker == "narrator":
                    print(f"\n  [Narrator] {text}")
                elif text:
                    print(f"\n  {text}")

            elif status == "line":
                idx = data.get("index", 0) + 1
                total = data.get("total", 1)
                text = data.get("text", "")
                audio_b64 = data.get("audio_b64", "")
                log.info("[DEBUG_CLI] line %d/%d 收到, 推入 tts_queue, queue_size=%d, t=%.4f",
                         idx, total, tts_queue.qsize() if tts_queue else -1, time.perf_counter())
                if audio_b64 and HAS_AUDIO and tts_queue is not None:
                    if t_first_audio is None:
                        t_first_audio = time.perf_counter()
                    tts_queue.put((text, audio_b64))
                print(f"\r  \U0001f3b5 TTS [{idx}/{total}]", end="", flush=True)

            elif status == "completed":
                log.info("[DEBUG_CLI] completed 收到, t=%.4f", time.perf_counter())
                _saw_completed = True
                _play_beep(self, 660)
                break
        if not _saw_completed and not _saw_cancelled:
            # 流在没有收到 completed/cancelled 的情况下结束（中断/超时/连接断开）→ 低音提示
            log.info("[DEBUG_CLI] SSE 流未收到 completed 即结束，播放停止提示音")
            _play_beep(self, 220)
        return reply if got_text else None, t_first_audio
