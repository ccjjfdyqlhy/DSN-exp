# harness/voice/session.py
# 感知模式 + 心跳（roadmap 段 5）：连续通话、沉默 = 在听、空闲主动开口。
#
# ── 这两个东西为什么在框架层 ──
# 它们在私有应用里已经跑通过（aicf-dsn），但每次要做新应用都得重写一遍。
# 沉默检测、轮次状态机、空闲计时这些是**交互逻辑**，不是业务逻辑 ——
# 抽成框架件，应用只提供 IO 端口（ASR / TTS / 播放器）和一个回复函数。
#
# 状态机（VoiceSession）：
#   listening → （听到语音）→ filtering → processing → speaking → listening
#                └─ 假语音/噪声 → 丢弃，回 listening（不进对话史）
#   沉默（listen 返回 None）不是错误 —— 感知模式的意义就是「沉默 = 在听」，
#   循环继续，不退出、不报错。
#
# 心跳（Heartbeat）：空闲超过间隔 → 调用应用的 hook，
# hook 返回一段话就朗读出来（提醒 / 场景变化），返回 None 就继续等。
# 心跳与空闲回收（infra/resources/idle.py）的关系见 roadmap 段 6：
# 常驻档（resident）让 ASR 常驻，心跳才不会「开口前先等模型加载」。

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional, Protocol

from .filter import CompositeSpeechFilter, SpeechVerdict
from .streaming import SentenceStreamSpeaker

__all__ = [
    'ASRPort',
    'Heartbeat',
    'SessionState',
    'VoiceIO',
    'VoiceSession',
    'VoiceTurn',
]


class ASRPort(Protocol):
    """语音识别端口：一段音频 → 文本。"""

    def transcribe(self, audio: bytes) -> str:
        ...


class VoiceIO(Protocol):
    """语音交互的 IO 端口 —— 应用层实现（麦克风 / 扬声器 / TTS）。"""

    asr: ASRPort
    speaker: SentenceStreamSpeaker

    def listen(self, *, timeout: float | None = None) -> bytes | None:
        """等一段语音。None = 超时没等到（沉默），不是错误。"""
        ...


class SessionState(str, Enum):
    IDLE = 'idle'
    LISTENING = 'listening'
    PROCESSING = 'processing'
    SPEAKING = 'speaking'


@dataclass
class VoiceTurn:
    """一轮语音交互的记录（应用的对话史自己消费）。"""

    heard: str
    reply: str
    verdict: SpeechVerdict
    interrupted: bool = False     # 播放被打断（用户插话）


@dataclass
class Heartbeat:
    """空闲心跳：超过 interval 秒没交互 → 问应用的 hook 要一句话。

    hook 返回 str 就朗读（主动开口），返回 None 就继续沉默。
    重复的主动发言之间有 min_gap 兜底 —— hook 每次都返回话也不至于
    变成机关枪。
    """

    interval: float = 300.0
    min_gap: float = 60.0
    hook: Optional[Callable[[float], Optional[str]]] = None
    clock: Callable[[], float] = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self._last_activity = self.clock()
        self._last_spoke: float | None = None

    def touch(self) -> None:
        """任何真实交互（听到语音 / 说过话）都算活动。"""
        self._last_activity = self.clock()

    def check(self) -> Optional[str]:
        """到点了吗？到了就问 hook 要一句话（并记录开口时间）。"""
        if self.hook is None:
            return None
        now = self.clock()
        idle = now - self._last_activity
        if idle < self.interval:
            return None
        if self._last_spoke is not None and now - self._last_spoke < self.min_gap:
            return None
        message = self.hook(idle)
        if message:
            self._last_spoke = now
            self._last_activity = now   # 开口本身就是一次活动
        return message


class VoiceSession:
    """感知模式的语音会话循环。

    reply_fn 是应用的「听到话之后怎么答」—— 框架不管对话史、不管模型，
    只管：听到 → 过滤 → 交给应用 → 把回答逐句读出去。
    """

    def __init__(self, io: VoiceIO, *, reply_fn: Callable[[str], str],
                 speech_filter: CompositeSpeechFilter | None = None,
                 on_turn: Callable[[VoiceTurn], None] | None = None):
        self.io = io
        self.reply_fn = reply_fn
        self.filter = speech_filter or CompositeSpeechFilter()
        self.on_turn = on_turn
        self.state = SessionState.IDLE
        self.heartbeat: Heartbeat | None = None
        self.rejected_turns = 0

    def enable_heartbeat(self, hook: Callable[[float], Optional[str]],
                         *, interval: float = 300.0,
                         min_gap: float = 60.0) -> Heartbeat:
        self.heartbeat = Heartbeat(interval=interval, min_gap=min_gap,
                                   hook=hook, clock=self.heartbeat_clock())
        return self.heartbeat

    def heartbeat_clock(self) -> Callable[[], float]:
        return time.time

    # ── 主循环 ──────────────────────────────────────────
    def run_forever(self, *, max_rounds: int | None = None,
                    listen_timeout: float = 5.0,
                    stop: Callable[[], bool] | None = None) -> int:
        """感知模式主循环：沉默 = 在听，永不退出直到 max_rounds / stop。

        返回完成的轮数（被过滤掉的假语音不算一轮）。
        """
        rounds = 0
        while max_rounds is None or rounds < max_rounds:
            if stop is not None and stop():
                break
            self._maybe_beat()
            audio = self.io.listen(timeout=listen_timeout)
            if audio is None:
                continue        # 沉默 = 在听 —— 感知模式的核心语义
            if self.turn(audio):
                rounds += 1
        return rounds

    def turn(self, audio: bytes) -> bool:
        """处理一段已捕获的音频，返回是否完成了一轮真对话。"""
        heard = self.io.asr.transcribe(audio)
        verdict = self.filter.classify(heard, audio=audio)
        if not verdict.accepted:
            self.rejected_turns += 1
            self.state = SessionState.LISTENING
            return False
        self.state = SessionState.PROCESSING
        if self.heartbeat is not None:
            self.heartbeat.touch()
        reply = self.reply_fn(heard)
        self.state = SessionState.SPEAKING
        self.io.speaker.speak(reply)
        interrupted = self.io.speaker.stopped
        self.state = SessionState.LISTENING
        turn = VoiceTurn(heard=heard, reply=reply, verdict=verdict,
                         interrupted=interrupted)
        if self.on_turn is not None:
            self.on_turn(turn)
        return True

    # ── 心跳 ────────────────────────────────────────────
    def _maybe_beat(self) -> None:
        if self.heartbeat is None:
            return
        message = self.heartbeat.check()
        if message:
            self.state = SessionState.SPEAKING
            self.io.speaker.speak(message)
            self.state = SessionState.LISTENING
