# apps/dsn_study_cli/tts.py
# TTS 播放 —— 把服务端合成好的语音放出来，让设备真正成为"对讲机"。
#
# 现状（补这个模块之前）：
#   服务端 SSE 里已经带了合成好的音频（audio_b64，WAV/RIFF），
#   client.py 也老实地把它塞进 client.tts_queue —— 但**队列没有任何消费者**，
#   于是音频合成完就被丢掉，设备只能"看"不能"听"。
#
# 播放后端按可用性依次尝试：pw-play → aplay → ffplay → cvlc。
# 用子进程而不是 python-vlc 绑定，原因有二：
#   1) 树莓派装了 python-vlc、开发机没装，子进程两边都在；
#   2) 子进程便于中断 —— barge-in（用户再次按 Space）要能立刻掐掉正在播的语音。
#
# 音频通路的坑（实测）：
#   - Pi 上裸 aplay 会报「设备或资源忙」——PipeWire 已持有 IQaudIODAC；
#     所以优先 pw-play 走 PipeWire。
#   - 播放期间麦克风必须让出来，否则 TTS 的声音被自己的 ASR 收进去形成自激。
#     本模块只负责播放，麦克风仲裁由 app 层通过 on_play_state 回调完成。

from __future__ import annotations

import base64
import io
import logging
import math
import os
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import wave

logger = logging.getLogger("study_cli.tts")

#: 播放后端优先级。第一个真正成功出声的会被记住，后续直接用。
#:
#: ⚠️ 顺序有讲究：**必须优先走 PipeWire(pw-play)**。
#: ffplay / cvlc 不指定协议时走**裸 ALSA 默认设备**（本机 = HDMI fallback），
#: 那里根本没接喇叭 —— 于是"播放 exit=0 但用户听不到任何声音"。
#: 所以 fallback 里的 ffplay/cvlc 一律显式加 `-f pulse`（走 pipewire-pulse，
#: 和 pw-play 落到同一个 sink），aplay 放最后（PipeWire 占用设备时它必失败）。
BACKENDS = ("pw-play", "cvlc")

#: 已知的坏后端（放在链外，只是记下来免得以后又加回去）：
#:   ffplay -f pulse —— 实测**挂死**（播放 3s 音频永不返回）。它一旦被启用，
#:   "后端失败"就会退化成"静默播放 0.28s"，比直接失败更难排查。
#:   aplay —— PipeWire 持有 IQaudIO 时报 "设备或资源忙"(524)，必然失败。
BAD_BACKENDS = ("ffplay", "aplay")

#: 单段音频最长播放时长（秒）—— 防止异常音频把设备卡死
MAX_PLAY_SECS = 180.0

#: 播放增益（线性系数）。服务端 TTS 出来是 -4.3 dBFS 峰值，实测偏响；
#: 在软件层面缩放，好过去动系统混音器 —— 换播放后端也保持一致。
#: 0.5 ≈ -6 dB，0.25 ≈ -12 dB，0.125 ≈ -18 dB，0.0625 ≈ -24 dB。
#: 默认 0.0625（实测 -28.4 dBFS 峰值）—— 由用户试听四档后选定。
TTS_GAIN = float(os.environ.get("STUDY_TTS_GAIN", "0.0625"))

#: 提示音增益。提示音只是"我听到了"的反馈，不该盖过人声。
CUE_GAIN = float(os.environ.get("STUDY_CUE_GAIN", "0.12"))


def _ensure_runtime_dir() -> None:
    """缺 XDG_RUNTIME_DIR 时按 uid 推导。

    PipeWire/PulseAudio 的 socket 在 /run/user/<uid>/ 下。
    systemd 的**系统级**单元默认不注入 XDG_RUNTIME_DIR → 客户端连不上
    PipeWire，pw-play 报 "pw_context_connect() failed: 主机已关闭"，
    音频一个都放不出来。这里补上，任何部署方式都生效。
    """
    if os.environ.get("XDG_RUNTIME_DIR"):
        return
    try:
        uid = os.getuid()
        path = "/run/user/%d" % uid
        if os.path.isdir(path):
            os.environ["XDG_RUNTIME_DIR"] = path
            logger.info("XDG_RUNTIME_DIR 缺失，已推导为 %s", path)
    except Exception:   # noqa: BLE001
        pass


def _pick_backend() -> str:
    """挑一个本机存在的播放命令。"""
    _ensure_runtime_dir()
    for name in BACKENDS:
        path = shutil.which(name)
        if path:
            return path
    return ""


def _audio_suffix(raw: bytes) -> str:
    """按文件头猜扩展名 —— 流式模式返回的是 Ogg，不是 WAV。

    GPT-SoVITS 在 ``-sm close``（默认）下回 WAV，``-sm normal``（流式）下
    回 **Ogg**。播放入口若一律写 ``.wav``，pw-play/cvlc 会按 WAV 解析
    Ogg 字节流，表现为「进程正常退出但没声音」—— 比直接报错更难查。
    """
    if not raw:
        return ".bin"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WAVE":
        return ".wav"
    if raw[:4] == b"OggS":
        return ".ogg"
    if raw[:3] == b"ID3" or raw[:2] in (b"\xff\xfb", b"\xff\xf3"):
        return ".mp3"
    if raw[:4] == b"fLaC":
        return ".flac"
    if raw[4:8] == b"ftyp":
        return ".m4a"
    return ".bin"


def _scale_pcm16(wav_bytes: bytes, gain: float) -> bytes:
    """WAV（PCM16）整体缩放增益，不改采样率/声道。

    增益 ≥1 时做软限幅，避免削顶产生爆音。
    """
    if not wav_bytes or abs(gain - 1.0) < 1e-3:
        return wav_bytes
    try:
        import io
        import wave
        buf = io.BytesIO(wav_bytes)
        with wave.open(buf, "rb") as wf:
            params = wf.getparams()
            frames = wf.readframes(wf.getnframes())
        if params.sampwidth != 2:
            return wav_bytes
        n = len(frames) // 2
        samples = struct.unpack("<%dh" % n, frames[: n * 2])
        out = []
        for s in samples:
            v = int(s * gain)
            if v > 32767:
                v = 32767
            elif v < -32768:
                v = -32768
            out.append(v)
        nb = io.BytesIO()
        with wave.open(nb, "wb") as wf:
            wf.setnchannels(params.nchannels)
            wf.setsampwidth(params.sampwidth)
            wf.setframerate(params.framerate)
            wf.writeframes(struct.pack("<%dh" % n, *out))
        return nb.getvalue()
    except Exception:   # noqa: BLE001
        return wav_bytes


def make_tone_wav(freq: int = 880, ms: int = 120, rate: int = 16000,
                  amplitude: int = 12000) -> bytes:
    """生成一段单音提示音（WAV 字节）—— 无屏模式下代替屏幕提示。"""
    n = int(rate * ms / 1000)
    frames = b"".join(
        struct.pack("<h", int(amplitude * math.sin(2 * math.pi * freq * i / rate)))
        for i in range(n))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(frames)
    return buf.getvalue()


class TtsPlayer:
    """消费 (text, audio_b64) 队列并逐段播放。

    :param tts_queue:  (text, b64) 元组队列；放入 None 作为停止哨兵
    :param on_play_state: 可选回调 (state: "start"|"end", text: str)，
                          app 层用它来关麦/开麦、打印状态
    """

    def __init__(self, tts_queue, on_play_state=None):
        self._queue = tts_queue
        self._on_play_state = on_play_state
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._interrupt = threading.Event()   # barge-in：只掐当前这段
        self._proc: subprocess.Popen | None = None
        self._playing = threading.Event()
        self._backend: str = _pick_backend()
        self._backend_locked = False

    # ── 生命周期 ──

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._worker, daemon=True,
                                        name="tts-player")
        self._thread.start()
        logger.info("TTS 播放器就绪，后端=%s", self._backend or "(无可用后端)")

    def stop(self):
        """整体停止（进程退出时调用）。"""
        self._stop.set()
        self._interrupt.set()
        self._kill_proc()

    def interrupt(self):
        """barge-in：掐掉当前正在播的这一段（队列里剩余的保留）。"""
        self._interrupt.set()
        self._kill_proc()

    def clear_queue(self):
        """清空待播队列（barge-in 时用：用户要说话就别再念旧回复了）。"""
        dropped = 0
        while True:
            try:
                self._queue.get_nowait()
                dropped += 1
            except Exception:   # noqa: BLE001 - 队列空
                break
        if dropped:
            logger.info("TTS 队列已清空，丢弃 %d 段", dropped)

    @property
    def is_playing(self) -> bool:
        return self._playing.is_set()

    # ── 工作线程 ──

    def _worker(self):
        while not self._stop.is_set():
            try:
                item = self._queue.get(timeout=0.5)
            except Exception:   # noqa: BLE001 - 空队列，继续等
                continue
            if item is None:
                break
            try:
                text, b64 = item
                self._play_one(text or "", b64 or "")
            except Exception:   # noqa: BLE001 - 单段失败不能拖垮线程
                logger.warning("TTS 播放失败", exc_info=True)
            finally:
                try:
                    self._queue.task_done()
                except Exception:   # noqa: BLE001
                    pass

    def _play_one(self, text: str, b64: str):
        if not b64:
            return
        try:
            raw = base64.b64decode(b64)
        except Exception:   # noqa: BLE001
            logger.warning("TTS base64 解码失败")
            return
        if not raw:
            return

        self._interrupt.clear()
        self._playing.set()
        t0 = time.perf_counter()
        if self._on_play_state:
            try:
                self._on_play_state("start", text)
            except Exception:   # noqa: BLE001
                pass
        tmp_path = None
        try:
            # 只有 WAV 能做软件增益；Ogg 等压缩格式原样播放
            suffix = _audio_suffix(raw)
            scaled = _scale_pcm16(raw, TTS_GAIN) if suffix == ".wav" else raw
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(scaled)
                tmp_path = tmp.name
            ok = self._spawn(tmp_path)
            if not ok:
                logger.warning("TTS 无可用播放后端，跳过播放")
            else:
                logger.info("TTS 播放结束 %.2fs 后端=%s 文本=%r",
                            time.perf_counter() - t0, self._backend, text[:40])
        finally:
            self._playing.clear()
            if self._on_play_state:
                try:
                    self._on_play_state("end", text)
                except Exception:   # noqa: BLE001
                    pass
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    # ── 后端 ──

    def _spawn(self, path: str) -> bool:
        """起一个播放进程并等它结束。返回是否成功出声。"""
        backends = [self._backend] if self._backend_locked else \
            [b for b in ([self._backend] + list(BACKENDS)) if b]
        last_err = ""
        for backend in backends:
            exe = shutil.which(backend) if backend else ""
            if not exe:
                continue
            cmd = self._build_cmd(exe, path)
            # stderr 走临时文件而不是 PIPE：管道缓冲写满时子进程会卡在
            # write 上永不退出，wait() 一直超时，最后被当成"播放失败"。
            # 注意：errf 必须**保持打开**直到子进程结束 ——
            # 提前 close() 会让 fd 失效，子进程写 stderr 时报
            # "I/O operation on closed file"，于是每个后端都被判为失败、
            # 一个字都放不出来（踩过）。
            errf = tempfile.NamedTemporaryFile(delete=False, suffix=".err")
            err_path = errf.name
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                        stderr=errf)
            except Exception as e:   # noqa: BLE001
                last_err = str(e)
                try:
                    errf.close()
                except Exception:
                    pass
                try:
                    os.unlink(err_path)
                except OSError:
                    pass
                continue
            self._proc = proc
            deadline = time.time() + MAX_PLAY_SECS
            while True:
                if self._stop.is_set() or self._interrupt.is_set():
                    self._kill_proc()
                    return True
                try:
                    proc.wait(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    if time.time() > deadline:
                        logger.warning("TTS 播放超时，强制停止")
                        self._kill_proc()
                        break
            err = ""
            try:
                errf.flush()
                errf.close()
            except Exception:   # noqa: BLE001
                pass
            try:
                with open(err_path, "rb") as fh:
                    err = fh.read().decode("utf-8", "ignore").strip()
            except Exception:   # noqa: BLE001
                pass
            try:
                os.unlink(err_path)
            except OSError:
                pass
            self._proc = None
            rc = proc.returncode
            if rc == 0:
                # 记住这个能用的后端，后续不再逐个试
                self._backend = exe
                self._backend_locked = True
                return True
            last_err = err or f"exit={rc}"
            # INFO 级：后端降级是"用户听不到声音"的直接原因，必须看得见
            logger.warning("播放后端 %s 失败: %s（尝试下一个）", exe, last_err)
        logger.warning("所有播放后端均失败，最后错误: %s", last_err)
        return False

    def _build_cmd(self, exe: str, path: str) -> list:
        name = os.path.basename(exe)
        if name == "pw-play":
            return [exe, path]
        if name == "cvlc":
            # --aout=pulse：同上，别落到裸 ALSA。
            return [exe, "--intf", "dummy", "--play-and-exit", "--quiet",
                    "--aout=pulse", path]
        return [exe, path]

    def _kill_proc(self):
        proc = self._proc
        if proc is None:
            return
        try:
            proc.terminate()
            try:
                proc.wait(timeout=1.5)
            except subprocess.TimeoutExpired:
                proc.kill()
        except Exception:   # noqa: BLE001
            pass
        finally:
            self._proc = None


class CuePlayer:
    """提示音播放器（无屏模式的状态反馈）。

    与 TtsPlayer 共用后端探测，但更轻量：一次性小 WAV + 短进程。
    """

    def __init__(self, backend: str = ""):
        self._backend = backend or _pick_backend()
        self._lock = threading.Lock()

    def beep(self, freq: int = 880, ms: int = 120):
        """发一声提示音。失败不影响主流程。"""
        exe = self._backend
        if not exe:
            return False
        data = make_tone_wav(freq=freq, ms=ms)
        data = _scale_pcm16(data, CUE_GAIN)
        tmp_path = None
        try:
            with self._lock:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
                    tmp.write(data)
                    tmp_path = tmp.name
                subprocess.Popen(self._cue_cmd(exe, tmp_path),
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:   # noqa: BLE001
            logger.debug("提示音播放失败", exc_info=True)
            return False
        finally:
            if tmp_path:
                def _del(p=tmp_path):
                    time.sleep(2)
                    try:
                        os.unlink(p)
                    except OSError:
                        pass
                threading.Thread(target=_del, daemon=True).start()

    @staticmethod
    def _cue_cmd(exe: str, path: str) -> list:
        name = os.path.basename(exe)
        if name == "pw-play":
            return [exe, path]
        if name == "aplay":
            return [exe, "-q", path]
        if name == "ffplay":
            return [exe, "-nodisp", "-autoexit", "-loglevel", "quiet", path]
        if name == "cvlc":
            return [exe, "--intf", "dummy", "--play-and-exit", "--quiet", path]
        return [exe, path]
