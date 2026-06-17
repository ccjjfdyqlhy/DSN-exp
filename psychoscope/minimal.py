#!/usr/bin/env python3
# psychoscope/minimal.py
# DSN-exp 最小终端客户端 — 语音输入 + 键盘操作，无 Web UI
#
# 依赖: pip install pvrecorder numpy requests
#
# 用法:
#   python minimal.py                        # 默认连接 localhost:8010
#   python minimal.py --host 192.168.1.5     # 指定后端地址
#   python minimal.py --host 192.168.1.5 --port 8010
#
# 操作:
#   Enter     — 开始说话 / 结束说话并发送
#   t         — 手动输入文字（回退模式，调试用）
#   s         — 显示当前人格状态
#   h         — 显示帮助
#   Ctrl+C    — 退出

from __future__ import annotations

import argparse
import base64
import io
import json
import logging
import os
import queue
import re
import signal
import sys
import tempfile
import threading
import time
import wave
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import requests

import pygame

# ------ pvrecorder ------
try:
    from pvrecorder import PvRecorder
    HAS_PVRECORDER = True
except ImportError:
    HAS_PVRECORDER = False
    print("[WARN] pvrecorder 未安装, 语音输入不可用。安装: pip install pvrecorder")

# ------ 配置默认值 ------
HERE = Path(__file__).resolve().parent
DEFAULT_HOST = os.environ.get("DSN_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("DSN_PORT", 5000))
CONFIG_FILE = HERE / ".dsn_client.json"
LOG_DIR = HERE / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / f"minimal_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

SAMPLE_RATE = 16000
SILENCE_TIMEOUT = 2.0     # 秒，说话时无声音多久自动结束
MAX_RECORD_SECS = 30      # 最大录音时长
RMS_THRESHOLD = 0.008     # 音量门限


# ── 日志 ──────────────────────────────────────────────────

def setup_logging():
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname).1s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    for h in root.handlers[:]:
        root.removeHandler(h)

    fh = logging.FileHandler(str(LOG_FILE), encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.INFO)
    sh.setFormatter(fmt)
    root.addHandler(sh)

    return logging.getLogger("minimal")


log = setup_logging()
log.info("日志文件: %s", LOG_FILE)

# ------ pygame 音频播放 ------
try:
    pygame.init()
    pygame.mixer.init(frequency=44100, size=-16, channels=1, buffer=2048)
    log.info("pygame mixer 就绪")
    _HAS_AUDIO = True
except Exception as e:
    log.warning("pygame mixer 初始化失败: %s (TTS 播放不可用)", e)
    _HAS_AUDIO = False


# ── 音频工具 ──────────────────────────────────────────────

def raw_pcm_to_wav_b64(samples: np.ndarray, sr: int = SAMPLE_RATE) -> str:
    """将 float32 [-1,1] 的 PCM 采样数组转为 WAV 格式的 base64 字符串"""
    int_samples = np.clip(samples * 32767, -32768, 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(int_samples.tobytes())
    return base64.b64encode(buf.getvalue()).decode("utf-8")


# ── SSE 解析 ──────────────────────────────────────────────

def iter_sse_lines(response: requests.Response):
    """迭代 SSE 响应的每一行事件数据。返回 (event_type, data_dict) 生成器。"""
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
                yield event, json.loads(data_str)
            except json.JSONDecodeError:
                log.debug("SSE 非 JSON 数据: %s", data_str[:80])
                yield event, {"raw": data_str}
        elif line == "":
            event = ""


# ── 配置持久化 ───────────────────────────────────────────

def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_config(cfg: dict):
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("配置已保存到 %s", CONFIG_FILE)


# ── 后端 API 客户端 ──────────────────────────────────────

class DSNClient:
    """与 DSN-exp 后端通信的最小 HTTP 客户端。

    认证流程 (API Key 方案):
      首次: 配对码 → session → 创建 API Key → 加密存储本地
      后续: 直接读本地 API Key → X-DSN-API-Key 认证
      API Key 永不过期, 不依赖 cookie/session 恢复。
    """

    def __init__(self, host: str, port: int):
        self.base = f"http://{host}:{port}"
        self.api_key: Optional[str] = None
        self.uid: int = 0
        self.chat_id: Optional[int] = None
        self.display_name: str = ""
        log.info("DSNClient 初始化: backend=%s:%d", host, port)

    # ── 认证 ──

    def authenticate(self, code: str = "", name: str = "") -> bool:
        """
        认证流程:
        1) 本地有 api_key → 直接用
        2) 无 api_key → 配对码注册 → 创建 API Key → 保存到本地
        """
        cfg = load_config()
        self.display_name = name or cfg.get("display_name", "")
        self.uid = cfg.get("uid", 0)
        self.chat_id = cfg.get("chat_id")

        # Step 1: 已有 API Key → 直接认证
        api_key = cfg.get("api_key", "")
        if api_key:
            print(f"  🔑 检测到本地 API Key, 尝试验证 (用户: {self.display_name})...")
            self.api_key = api_key
            if self._verify_api_key():
                self.uid = cfg.get("uid", 0)
                self.display_name = cfg.get("display_name", "")
                print(f"  ✅ API Key 有效 (uid={self.uid})")
                return True
            print(f"  ⚠️  API Key 已失效, 需要重新注册")
            self.api_key = None
            cfg.pop("api_key", None)
            cfg.pop("uid", None)
            save_config(cfg)

        # Step 2: 无 API Key → 配对码注册 + 创建 API Key
        if not code:
            log.info("无 API Key 且无配对码")
            return False

        if not self.display_name:
            self.display_name = input("  你的名字: ").strip() or "minimal"

        # 2a: 检查配对码状态
        has_pairing = False
        try:
            r = requests.get(f"{self.base}/api/auth/pairing/status", timeout=5)
            if r.status_code == 200:
                has_pairing = r.json().get("active", False)
        except Exception:
            pass

        if not has_pairing:
            print("  ⚠️  服务端无活跃配对码")
            print("  请在 DSN-exp 服务器控制台输入: /newbind")
            return False

        # 2b: 配对注册
        print(f"  提交配对码 (code={code}, name={self.display_name})...")
        try:
            resp = requests.post(
                f"{self.base}/api/auth/pairing/verify",
                json={"code": code, "display_name": self.display_name, "is_admin": True},
                timeout=30,
            )
            if resp.status_code != 200:
                data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                err = data.get("error", resp.text[:100])
                if resp.status_code == 401:
                    print("  ❌ 配对码无效或已过期 (有效期5分钟)")
                elif resp.status_code == 403:
                    print("  ❌ 配对仅限内网使用")
                else:
                    print(f"  ❌ 配对失败: {err}")
                return False

            data = resp.json()
            session_id = data["session_id"]
            self.uid = data["uid"]
            self.display_name = data.get("display_name", self.display_name)
            log.info("配对成功 uid=%d", self.uid)

        except Exception as e:
            log.error("配对失败: %s", e)
            print(f"  ❌ 连接错误: {e}")
            return False

        # 2c: 用 session 创建 API Key
        print("  创建 API Key...")
        try:
            resp = requests.post(
                f"{self.base}/api/auth/api-key/create",
                headers={"Authorization": f"Session {session_id}"},
                json={"name": "minimal-cli", "scopes": "read write"},
                timeout=30,
            )
            if resp.status_code != 200:
                log.error("创建 API Key 失败 HTTP %d", resp.status_code)
                print("  ❌ 创建 API Key 失败")
                return False

            data = resp.json()
            self.api_key = data["key"]
            cfg["api_key"] = self.api_key
            cfg["uid"] = self.uid
            cfg["display_name"] = self.display_name
            save_config(cfg)
            print(f"  💾 API Key 已保存到 {CONFIG_FILE}")
            log.info("API Key 创建成功 uid=%d", self.uid)
            return True

        except Exception as e:
            log.error("创建 API Key 失败: %s", e)
            print(f"  ❌ 创建 API Key 错误: {e}")
            return False

    def _verify_api_key(self) -> bool:
        """用当前 API Key 调 GET /api/personality/status 验证有效性"""
        if not self.api_key:
            return False
        try:
            resp = requests.get(
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
            log.warning("API Key 验证失败 HTTP %d: %s", resp.status_code, resp.text[:100])
            return False
        except Exception as e:
            log.warning("API Key 验证网络错误: %s", e)
            return False

    def _headers(self) -> dict:
        """X-DSN-API-Key 认证 (最简单, 永不过期)"""
        if self.api_key:
            return {"X-DSN-API-Key": self.api_key}
        return {}

    def _http_get(self, path: str, **kwargs) -> requests.Response:
        return requests.get(f"{self.base}{path}", headers=self._headers(),
                            timeout=kwargs.pop("timeout", 30), **kwargs)

    def _http_post(self, path: str, **kwargs) -> requests.Response:
        return requests.post(f"{self.base}{path}", headers=self._headers(),
                             timeout=kwargs.pop("timeout", 30), **kwargs)

    def _http_post_stream(self, path: str, **kwargs) -> requests.Response:
        return requests.post(f"{self.base}{path}", headers=self._headers(),
                             stream=True, timeout=(10, 120), **kwargs)

    # ── 语音消息 ──

    def send_audio(self, audio_b64: str) -> Optional[str]:
        """
        发送 base64 编码的 WAV 音频到 /api/asr/passthrough。
        返回 AI 回复文本，或 None。
        """
        if not self.api_key:
            log.error("未认证，无法发送消息")
            return None

        log.info("发送音频 (len=%d chars)...", len(audio_b64))
        t0 = time.perf_counter()
        self._tts_chunks: list[str] = []

        try:
            resp = self._http_post_stream(
                "/api/asr/passthrough",
                json={
                    "audio_b64": audio_b64,
                    "chat_id": self.chat_id,
                    "chat_name": "minimal",
                },
            )
            if resp.status_code != 200:
                log.error("asr/passthrough 失败 HTTP %d: %s", resp.status_code, resp.text[:200])
                return None

            reply_text = self._handle_sse_stream(resp)
            elapsed = time.perf_counter() - t0
            log.info("语音对话完成 (%.1fs)", elapsed)

            # 播放收集到的 TTS 音频
            if self._tts_chunks:
                self._play_tts()
                self._tts_chunks = []

            return reply_text
        except Exception as e:
            log.error("语音发送失败: %s", e)
            return None

    def _play_tts(self):
        """每个 TTS chunk 是独立 WAV → 逐个写入临时文件 → 顺序播放 → 删掉"""
        if not _HAS_AUDIO:
            return
        chunks = list(self._tts_chunks)
        if not chunks:
            return
        log.info("TTS 开始播放, 共 %d 个音频块", len(chunks))

        def _run():
            import base64 as _b64, tempfile as _tmp
            tmp_files = []

            # 写入所有 chunk 到独立临时文件
            for i, b64 in enumerate(chunks):
                try:
                    raw = _b64.b64decode(b64)
                    with _tmp.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                        f.write(raw)
                        tmp_files.append((f.name, raw))
                except Exception as e:
                    log.warning("TTS chunk %d 解码失败: %s", i, e)

            # 顺序播放
            for path, _raw in tmp_files:
                try:
                    with wave.open(path, 'rb') as wf:
                        sr = wf.getframerate()
                        ch = wf.getnchannels()
                    pygame.mixer.quit()
                    pygame.mixer.init(frequency=sr, size=-16, channels=ch, buffer=2048)

                    sound = pygame.mixer.Sound(file=path)
                    sound.play()
                    while pygame.mixer.get_busy():
                        time.sleep(0.05)
                except Exception as e:
                    log.warning("TTS 播放 %s 失败: %s", path, e)

            # 删除所有临时文件
            for path, _ in tmp_files:
                try:
                    os.unlink(path)
                except Exception:
                    pass

            log.info("TTS 播放完成 (%d 块)", len(tmp_files))

        t = threading.Thread(target=_run, daemon=True, name="tts-player")
        t.start()

    def _handle_sse_stream(self, resp: requests.Response) -> Optional[str]:
        """处理 SSE 流，在终端实时显示状态和回复"""
        reply = ""
        got_text = False

        for _evt_type, data in iter_sse_lines(resp):
            status = data.get("status", "")

            if status == "text_ready":
                reply = data.get("reply", "")
                got_text = True
                self.chat_id = data.get("chat_id", self.chat_id)
                log.info("[reply] %s", reply[:120])

            elif status == "narrative_update":
                text = data.get("text", "")
                speaker = data.get("speaker", "")
                if speaker == "narrator":
                    print(f"\n  🎬 {text}")
                elif text:
                    print(f"\n  {text}")

            elif status == "line":
                idx = data.get("index", 0) + 1
                total = data.get("total", 1)
                text = data.get("text", "")
                audio_b64 = data.get("audio_b64", "")
                if audio_b64:
                    self._tts_chunks.append(audio_b64)
                    bar = "▊"
                else:
                    bar = "▁"
                print(f"\r  🔊 TTS [{idx}/{total}] {text[:50]}", end="", flush=True)

            elif status == "completed":
                timing = data.get("timing", {})
                tts_lines = data.get("audio_b64")
                msgs = []
                if tts_lines:
                    msgs.append("audio")
                if timing:
                    phases = []
                    for k, v in timing.items():
                        if k != "total_ms" and v > 0:
                            phases.append(f"{k}={v}ms")
                    if phases:
                        msgs.append(" ".join(phases))
                extra = f"  ({', '.join(msgs)})" if msgs else ""
                print(f"\n  ✅ 完成{extra}")
                break

            elif status == "thinking":
                text = data.get("text", "")
                log.debug("[thinking] %s", text)

            elif status == "task_result":
                tid = data.get("task_id", "")
                ok = data.get("success", False)
                log.info("[task_result] %s success=%s", tid, ok)

            elif status in ("filtering", "parsing", "request", "execution", "tts"):
                log.debug("[%s]", status)

            elif "error" in data:
                log.error("[SSE error] %s", data.get("error", str(data)))

            elif data.get("raw"):
                pass  # non-JSON line, skip

        if got_text:
            return reply

        if not reply:
            log.warning("SSE 流未收到 text_ready 事件")
        return reply if got_text else None


# ── 语音录制 ──────────────────────────────────────────────

class VoiceRecorder:
    """基于 pvrecorder 的语音录制器，支持自动 VAD 和手动启停"""

    def __init__(self, client: DSNClient):
        self.client = client
        self._recording = False
        self._frames: list[np.ndarray] = []
        self._sent_frames = None  # 防止重复发送
        self._last_speech_time = 0.0
        self._start_time = 0.0
        self._recorder: Optional[PvRecorder] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def duration(self) -> float:
        if not self._start_time:
            return 0.0
        return time.time() - self._start_time

    def start(self):
        if self._recording:
            return
        if not HAS_PVRECORDER:
            print("  ❌ pvrecorder 未安装，无法录音")
            return

        try:
            self._recorder = PvRecorder(device_index=-1, frame_length=512)
        except Exception as e:
            log.error("麦克风初始化失败: %s", e)
            print(f"  ❌ 无法打开麦克风: {e}")
            print("  提示: 检查麦克风是否被其他程序占用")
            return

        self._recording = True
        self._frames = []
        self._sent_frames = None
        self._last_speech_time = time.time()
        self._start_time = time.time()
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._capture_loop, daemon=True, name="voice-capture")
        self._thread.start()
        log.info("录音开始")

    def stop_and_send(self):
        if not self._recording:
            return

        self._recording = False
        self._stop_event.set()

        # 中断阻塞的 recorder.read(): stop() 从主线程调用是安全的
        if self._recorder:
            try:
                self._recorder.stop()
            except Exception:
                pass

        # 等待捕获线程退出
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)

        # 线程已退出，安全删除 recorder
        if self._recorder:
            try:
                self._recorder.delete()
            except Exception:
                pass
            self._recorder = None

        dur = time.time() - self._start_time
        log.info("录音结束: %.1fs, %d 帧", dur, len(self._frames))

        if not self._frames or dur < 0.5:
            print("  ⏭  太短，已忽略")
            return

        audio = np.concatenate(self._frames)
        b64 = raw_pcm_to_wav_b64(audio)
        self._sent_frames = self._frames  # 标记已发送，防止重复
        self.client.send_audio(b64)

    def _capture_loop(self):
        try:
            self._recorder.start()
            while self._recording and not self._stop_event.is_set():
                frame = self._recorder.read()
                samples = np.array(frame, dtype=np.int16).astype(np.float32) / 32768.0
                energy = float(np.sqrt(np.mean(samples ** 2)))

                self._frames.append(samples)

                if energy > RMS_THRESHOLD:
                    self._last_speech_time = time.time()

                dur = time.time() - self._start_time
                sil = time.time() - self._last_speech_time

                bar_len = min(int(energy * 200), 30)
                bar = "█" * bar_len + "░" * (30 - bar_len)
                status = "● 录音中" if energy > RMS_THRESHOLD else "○ 静音"
                print(f"\r  {status}  [{bar}]  {dur:.1f}s  (静音 {sil:.1f}s)  ", end="", flush=True)

                if sil > SILENCE_TIMEOUT:
                    log.info("静音 %.1fs 自动结束", sil)
                    self._recording = False
                    break

                if dur > MAX_RECORD_SECS:
                    log.info("达到最大录音时长 %ds", MAX_RECORD_SECS)
                    self._recording = False
                    break
        except Exception:
            pass  # read() 被主线程 stop() 中断 — 正常
        finally:
            try:
                self._recorder.stop()
            except Exception:
                pass


# ── 键盘输入处理 ──────────────────────────────────────────

class KeyboardHandler:
    """非阻塞键盘输入监听（仅 Unix）"""

    def __init__(self):
        self._queue: queue.Queue[str] = queue.Queue()
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="keyboard")
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=1)

    def get(self, timeout: float = 0.1) -> Optional[str]:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def _loop(self):
        # 使用 termios 实现非阻塞按键读取
        try:
            import termios
            import tty
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            tty.setcbreak(fd)
            try:
                while self._running:
                    import select
                    if select.select([sys.stdin], [], [], 0.1)[0]:
                        ch = sys.stdin.read(1)
                        if ch:
                            self._queue.put(ch)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
        except (ImportError, AttributeError):
            # Windows fallback — 使用 msvcrt
            try:
                import msvcrt
                while self._running:
                    if msvcrt.kbhit():
                        ch = msvcrt.getch().decode("utf-8", errors="replace")
                        self._queue.put(ch)
                    time.sleep(0.05)
            except ImportError:
                log.warning("无法启用非阻塞键盘输入（不支持的平台）")
                while self._running:
                    time.sleep(0.1)


# ── UI 渲染 ───────────────────────────────────────────────

def print_header(cfg: dict):
    os.system("cls" if os.name == "nt" else "clear")
    print("╔══════════════════════════════════════════╗")
    print("║        DSN-exp  Minimal Client          ║")
    print("╠══════════════════════════════════════════╣")
    uid = cfg.get("uid", "?")
    name = cfg.get("display_name", "?")
    host = cfg.get("host", f"{DEFAULT_HOST}:{DEFAULT_PORT}")
    print(f"║  Backend : {host:<30} ║")
    print(f"║  User    : uid={uid} ({name})".ljust(43) + "║")
    print("╠══════════════════════════════════════════╣")
    print("║  [Enter]  开始 / 结束说话                ║")
    print("║  [p]      查看当前人格状态               ║")
    print("║  [s]      切换待机 / 唤醒               ║")
    print("║  [h]      显示帮助                      ║")
    print("║  [q/Ctrl+C]  退出                       ║")
    print("╚══════════════════════════════════════════╝")
    print()


def print_personality(client: DSNClient):
    """获取并显示当前人格状态"""
    try:
        resp = client._http_get("/api/personality/status")
        if resp.status_code != 200:
            print(f"  ❌ 获取人格状态失败 HTTP {resp.status_code}")
            return
        data = resp.json()
        mood = data.get("mood", {})
        aff = data.get("affinity_value", 0)
        lvl = data.get("affinity_level", {})
        interactions = data.get("total_interactions", 0)
        card = data.get("card_id", "")

        joy = mood.get("joy", 0.5)
        sad = mood.get("sadness", 0.2)
        ang = mood.get("anger", 0.1)
        fear = mood.get("fear", 0.15)

        print(f"\n  ┌─ 人格状态 ─────────────────────────────")
        print(f"  │ 角色卡    : {card}")
        print(f"  │ 互动次数  : {interactions}")
        print(f"  │ 亲密度    : {aff:.0f}/100 ({lvl.get('label', '?')})")
        print(f"  │ 情绪      :")
        print(f"  │   joy={joy:.2f} sad={sad:.2f} ang={ang:.2f} fear={fear:.2f}")
        print(f"  │   {'█'*int(joy*20)}{'░'*(20-int(joy*20))}")
        print(f"  └────────────────────────────────────────")
        log.info("获取人格状态成功 card=%s aff=%.0f", card, aff)
    except Exception as e:
        log.error("获取人格状态失败: %s", e)
        print(f"  ❌ 错误: {e}")


def toggle_standby(client: DSNClient):
    try:
        resp = requests.post(
            f"{client.base}/api/maintenance/toggle_standby",
            timeout=10,
        )
        data = resp.json()
        state = data.get("state", "?")
        print(f"  🔄 服务器状态: {state}")
        log.info("切换待机 → %s", state)
    except Exception as e:
        log.error("切换待机失败: %s", e)
        print(f"  ❌ 错误: {e}")


# ── 主循环 ───────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="DSN-exp 最小终端客户端")
    parser.add_argument("--host", default=DEFAULT_HOST, help="后端地址")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="后端端口")
    parser.add_argument("--pairing", default="", help="配对码（首次使用时提供）")
    args = parser.parse_args()

    cfg = load_config()
    cfg["host"] = f"{args.host}:{args.port}"

    client = DSNClient(args.host, args.port)

    # ── 连接检查 ──
    print(f"  后端: http://{args.host}:{args.port}")
    try:
        r = requests.get(f"http://{args.host}:{args.port}/api/auth/status", timeout=5)
        if r.status_code == 200:
            st = r.json()
            methods = [k for k, v in st.get("methods", {}).items() if v]
            print(f"  已连接, 可用认证方式: {', '.join(methods)}")
        else:
            print(f"  ⚠️  /api/auth/status → HTTP {r.status_code}")
    except requests.ConnectionError:
        print(f"\n❌ 无法连接后端 http://{args.host}:{args.port}")
        print("  请确保 DSN-exp 主服务器已启动:")
        print("    python app.py")
        print(f"  或用 --port 指定正确端口 (当前: {args.port})")
        sys.exit(1)
    except Exception as e:
        print(f"  ⚠️  连接检查异常: {e}")

    # ── 认证 (API Key 方案: 首次配对注册 + 创建 Key, 后续直接读 Key) ──
    display_name = cfg.get("display_name", "")
    pairing_code = args.pairing

    while True:
        ok = client.authenticate(code=pairing_code, name=display_name)
        if ok:
            break

        # 认证失败 → 提示重新配对
        print()
        print("  ╔══════════════════════════════════════╗")
        print("  ║          DSN-exp 设备注册           ║")
        print("  ╠══════════════════════════════════════╣")
        print("  ║  请在服务器控制台输入: /newbind      ║")
        print("  ║  然后在此输入配对码和你的名字        ║")
        print("  ╚══════════════════════════════════════╝")
        print()
        pairing_code = input("  配对码 (8位): ").strip()
        if not display_name:
            display_name = input("  你的名字: ").strip()
        if not pairing_code:
            print("  ❌ 需要配对码才能继续")
            sys.exit(1)

    # 认证成功后刷新配置
    cfg = load_config()
    cfg["uid"] = client.uid
    cfg["display_name"] = client.display_name
    if client.chat_id:
        cfg["chat_id"] = client.chat_id
    save_config(cfg)

    print_header(cfg)
    print("  ✅ 认证成功! 按 Enter 开始说话...\n")

    recorder = VoiceRecorder(client)
    keyboard = KeyboardHandler()
    keyboard.start()

    def on_sigint(sig, frame):
        log.info("收到 SIGINT，正在退出...")
        if recorder.is_recording:
            recorder.stop_and_send()
        keyboard.stop()
        save_config(cfg)
        print("\n  再见 👋")
        sys.exit(0)

    signal.signal(signal.SIGINT, on_sigint)

    buffer = ""
    try:
        while True:
            ch = keyboard.get(timeout=0.15)
            if ch is None:
                # 检测自然结束 (静音超时 / 最长时长)
                if recorder._frames and not recorder.is_recording and not recorder._sent_frames is recorder._frames:
                    print()
                    recorder.stop_and_send()
                    print()
                continue

            # Enter
            if ch in ("\r", "\n"):
                if recorder.is_recording:
                    print()
                    recorder.stop_and_send()
                    print()
                else:
                    print("\n  🎤 开始说话... (按 Enter 结束)")
                    recorder.start()

            # Exit
            elif ch.lower() == "q":
                if recorder.is_recording:
                    recorder.stop_and_send()
                break

            # Personality
            elif ch.lower() == "p":
                print_personality(client)

            # Standby toggle
            elif ch.lower() == "s":
                toggle_standby(client)

            # Help
            elif ch.lower() == "h":
                print_header(cfg)

            # Debug: text fallback
            elif ch.lower() == "t":
                text = input("  输入文字: ").strip()
                if text:
                    log.info("手动文字输入: %s", text[:50])
                    try:
                        resp = client._http_post("/api/chat/send", json={
                            "message": text,
                            "chat_id": client.chat_id,
                            "chat_name": "minimal",
                            "tts_enabled": False,
                        })
                        if resp.status_code == 200:
                            data = resp.json()
                            reply = data.get("reply", "")
                            print(f"\n  💬 {reply}")
                            log.info("[reply] %s", reply[:120])
                        else:
                            print(f"  ❌ HTTP {resp.status_code}")
                    except Exception as e:
                        log.error("文字发送失败: %s", e)

            else:
                buffer += ch

    except KeyboardInterrupt:
        pass
    finally:
        if recorder.is_recording:
            recorder.stop_and_send()
        keyboard.stop()
        cfg["chat_id"] = client.chat_id
        save_config(cfg)
        print("\n  再见 👋")


if __name__ == "__main__":
    main()
