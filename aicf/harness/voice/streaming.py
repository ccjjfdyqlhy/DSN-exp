# harness/voice/streaming.py
# 流式逐句朗读（roadmap 段 5）：不等整段生成完，第一句合成完就开始播。
#
# ── 为什么是「逐句」而不是「逐 token」 ──
# TTS 按句合成才自然（韵律、停顿都由标点承载）；逐 token 送 TTS 会把
# 「你好」和「，大家好」切成两段怪调。所以拆句边界选在标点上 ——
# 中西文都认，数字里的小数点不认（3.14 不是两句）。
#
# 依赖方向：本模块只定义**端口**（TTS / 播放器），不 import infra ——
# 真正的 TTS 进程在应用层（infra/resources 池管理），应用把客户端
# 适配成 TTSClientPort 塞进来。这样交互逻辑可以离线测试，
# 不用起一个真的 GPT-SoVITS。

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Callable, Iterator, Optional, Protocol

__all__ = [
    'AudioSinkPort',
    'SentenceSplitter',
    'SentenceStreamSpeaker',
    'TTSClientPort',
]

# 句末标点：中西文一起认。ASCII '.' 也在内 —— 但小数点由
# SentenceSplitter 的数字守卫排除（3.14 不是两句）。
_TERMINAL = re.compile(r'([。！？；!?;…\n.])')


class TTSClientPort(Protocol):
    """TTS 客户端端口 —— 应用层把真客户端适配成这个形状。

    synthesize_stream 逐块产出音频字节；不支持流式的客户端可以只实现
    synthesize（扬声器会整段合成后播放，退化但不失效）。
    """

    def synthesize(self, text: str, **params) -> bytes:
        ...

    def synthesize_stream(self, text: str, **params) -> Iterator[bytes]:
        ...


class AudioSinkPort(Protocol):
    """音频播放端口 —— sounddevice / 文件 / 测试桩都算。"""

    def play(self, data: bytes) -> None:
        ...

    def flush(self) -> None:
        ...


@dataclass
class SentenceSplitter:
    """把一段文本拆成可独立合成的句子。

    规则（刻意保守）：
      - 在句末标点后切（标点跟随前句）；
      - 数字中的点不切（3.14、1.5 万）；小数点前后都是数字就不算句末；
      - 超长的无标点段落按 max_chars 硬切（TTS 输入有长度上限）；
      - 空白句丢弃。
    """

    max_chars: int = 120

    def split(self, text: str) -> list[str]:
        if not text:
            return []
        parts: list[str] = []
        buffer: list[str] = []
        tokens = _TERMINAL.split(text)
        # split 带捕获组：奇数位是标点本身，偶数位是标点之间的内容
        for i, token in enumerate(tokens):
            if not token:
                continue
            if i % 2 == 0:
                buffer.append(token)
                continue
            # 标点：小数点例外 —— 前后都是数字就不是句末
            if token == '.' and buffer and _endswith_digit(buffer) \
                    and i + 1 < len(tokens) and tokens[i + 1][:1].isdigit():
                buffer.append(token)
                continue
            buffer.append(token if token != '\n' else '')
            sentence = ''.join(buffer).strip()
            buffer = []
            if sentence:
                parts.extend(self._hard_wrap(sentence))
        tail = ''.join(buffer).strip()
        if tail:
            parts.extend(self._hard_wrap(tail))
        return parts

    def _hard_wrap(self, sentence: str) -> list[str]:
        if len(sentence) <= self.max_chars:
            return [sentence]
        chunks = []
        for i in range(0, len(sentence), self.max_chars):
            chunk = sentence[i:i + self.max_chars].strip()
            if chunk:
                chunks.append(chunk)
        return chunks


def _endswith_digit(buffer: list[str]) -> bool:
    joined = ''.join(buffer).rstrip()
    return bool(joined) and joined[-1].isdigit()


@dataclass
class SentenceStreamSpeaker:
    """流式逐句扬声器：合成一句、播放一句，不等整段。

    事件钩子（可选）给测试和应用观测用：
      on_sentence_start(sentence)   开始合成第 N 句时
      on_chunk(sentence, n)         每个音频块送进播放器时
      on_sentence_end(sentence)     一句播完时

    stop() 是协作式取消：音频块之间检查，正在阻塞的播放由底层端口自己处理。
    """

    tts: TTSClientPort
    sink: AudioSinkPort
    splitter: SentenceSplitter = field(default_factory=SentenceSplitter)
    stream: Optional[bool] = None        # None = 自动探测（尝试流式，失败退化）
    on_sentence_start: Optional[Callable[[str], None]] = None
    on_sentence_end: Optional[Callable[[str], None]] = None
    on_chunk: Optional[Callable[[str, int], None]] = None

    def __post_init__(self) -> None:
        self._stop = threading.Event()

    # ── 对外 ────────────────────────────────────────────
    @property
    def stopped(self) -> bool:
        """最近一次朗读是否被 stop() 打断。"""
        return self._stop.is_set()

    def stop(self) -> None:
        """请求停止当前朗读（协作式：下一个音频块边界生效）。"""
        self._stop.set()

    def reset(self) -> None:
        self._stop.clear()

    def speak(self, text: str, **params) -> int:
        """朗读一段文本，返回完整播出的句子数（被 stop 掐掉的不算）。"""
        self._stop.clear()
        spoken = 0
        for sentence in self.splitter.split(text):
            if self._stop.is_set():
                break
            if self.on_sentence_start is not None:
                self.on_sentence_start(sentence)
            self._synth_and_play(sentence, **params)
            if self._stop.is_set():
                break
            spoken += 1
            if self.on_sentence_end is not None:
                self.on_sentence_end(sentence)
        self.sink.flush()
        return spoken

    # ── 内部 ────────────────────────────────────────────
    def _synth_and_play(self, sentence: str, **params) -> None:
        if self.stream is False:
            audio = self.tts.synthesize(sentence, **params)
            self._play(sentence, audio)
            return
        try:
            chunks = self.tts.synthesize_stream(sentence, **params)
            played = 0
            for chunk in chunks:
                if self._stop.is_set():
                    break
                self._play(sentence, chunk)
                played += 1
            if played == 0 and not self._stop.is_set():
                # 流式端口一个块都没给 —— 可能是「不支持流式」的退化实现，
                # 整段兜底一次。绝不允许「以为在播但其实没声」。
                self._play(sentence, self.tts.synthesize(sentence, **params))
        except (NotImplementedError, AttributeError):
            self._play(sentence, self.tts.synthesize(sentence, **params))

    def _play(self, sentence: str, data: bytes) -> None:
        if not data:
            return
        self.sink.play(data)
        if self.on_chunk is not None:
            self.on_chunk(sentence, len(data))
