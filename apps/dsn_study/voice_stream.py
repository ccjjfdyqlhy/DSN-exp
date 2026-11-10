# apps/dsn_study/voice_stream.py
# 方案 D：API 模型流式 → 分句 → 并发 TTS → 逐句下发。
#
# 为什么需要这一层（实测数据）：
#   旧链路是「LLM 全量生成完 → TTS 整段合成 → 一次性发 SSE」，
#   服务端合计 8.4s（model_invoke 6.5s + post_tts 1.5s），用户说完要等 9~10s。
#
#   本模块把两段串行改成流水线：
#       t=0    首字（API flash 实测 2.6~3.6s）
#       t=X    第一句生成完 → 立刻送 TTS（首包 1.15~1.35s）
#       t=X+1.2 第一段音频就能播
#   句子之间 TTS 并发合成，后一句的音频在前一句播放期间就已备好。
#
# 设计约束：
#   * **绝不因为 TTS 失败而丢掉文本回复** —— 语音是增强项。
#   * **顺序保证**：LLM 增量乱序到达时，TTS 结果必须按句子顺序下发，
#     否则用户会听到倒装的句子。用序号 + 有序缓冲保证。
#   * **不阻塞 LLM 读取**：TTS 在独立线程池里跑，主循环只做切句与派发。

from __future__ import annotations

import logging
import re
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Iterator, Optional

logger = logging.getLogger("VoiceStream")

#: 句子边界字符：中文句末 + 英文句末 + 换行 + 逗号。
#: 逗号也切 —— 长句在逗号处断开发音更自然，且能更早出第一段音频。
SENTENCE_END_CHARS = set("。！？!?；;\n，,")

#: 单句最小长度（字符）。太短的碎片（如「嗯。」）单独合成开销大且拼接生硬，
#: 攒到下一个句末再一起合成。
MIN_SENTENCE_CHARS = 6

#: 强制 flush 阈值：缓冲区超过这个长度就不再等标点，直接切（防止无标点长句卡住）。
MAX_BUFFER_CHARS = 80

#: TTS 并发上限。GPT-SoVITS 单实例内部是串行的，过多并发只会排队，
#: 反而抬高显存峰值；2 个足够覆盖「下一句预合成」。
TTS_WORKERS = 2


@dataclass
class Segment:
    """一个待合成的语音段。"""

    index: int
    text: str
    audio_b64: Optional[str] = None
    error: str = ""


def _has_end(text: str) -> bool:
    """文本是否以句末标点结尾。"""
    return bool(text) and text.rstrip()[-1:] in SENTENCE_END_CHARS


def split_sentences(buffer: str, *, force: bool = False) -> tuple[list[str], str]:
    """从缓冲区切出可合成的完整句子。

    返回 (完整句子列表, 剩余缓冲)。

    切分规则（**必须从左到右顺序扫描**，不能用零宽正则 split ——
    零宽匹配的 ``m.end() == m.start()`` 会让切点原地打转，
    实测把「重点。」和「它的图像」拼成了一句）：

      1. 遇到句末字符即断句；
      2. 句子短于 ``MIN_SENTENCE_CHARS`` 时**向后**并入下一句
         （而非把下一句吞进短碎片）；
      3. ``force=True``（流结束）时把剩余内容作为最后一句返回。
    """
    if not buffer:
        return [], ""

    pieces: list[str] = []
    current: list[str] = []
    for ch in buffer:
        current.append(ch)
        if ch in SENTENCE_END_CHARS:
            pieces.append("".join(current))
            current = []
    rest = "".join(current)

    # 短碎片向后合并：`pending` 攒着，直到凑够长度或遇到最后一段
    merged: list[str] = []
    pending = ""
    for piece in pieces:
        candidate = pending + piece
        if len(candidate.strip()) < MIN_SENTENCE_CHARS:
            pending = candidate
        else:
            merged.append(candidate)
            pending = ""
    if pending:
        # 所有完整句都太短：并入最后一句，或（没有）自成一句
        if merged:
            merged[-1] += pending
        else:
            rest = pending + rest
            pending = ""

    if force:
        tail = rest.strip()
        if tail:
            merged.append(rest)
        rest = ""
        return merged, rest

    # 无标点长句兜底：超长就强制切，否则 TTS 迟迟拿不到输入
    while len(rest) > MAX_BUFFER_CHARS:
        merged.append(rest[:MAX_BUFFER_CHARS])
        rest = rest[MAX_BUFFER_CHARS:]

    return merged, rest


class StreamingVoicePipeline:
    """把「文本增量流」变成「按序音频段流」。

    用法::

        pipeline = StreamingVoicePipeline(voice_service)
        for seg in pipeline.run(text_chunks):
            if seg.audio_b64:
                send(seg.audio_b64)

    ``text_chunks`` 是任意可迭代的文本增量（来自 LLM 流式输出）。
    每个 yield 出来的 :class:`Segment` 已按句子顺序排好，``audio_b64``
    为 None 表示该段合成失败（调用方应降级为纯文本）。
    """

    def __init__(self, voice=None, *, max_workers: int = TTS_WORKERS):
        self._voice = voice
        self._max_workers = max(1, int(max_workers))
        self._executor: Optional[ThreadPoolExecutor] = None
        self._lock = threading.Lock()
        self._closed = False

    # ── 生命周期 ──

    def _ensure_executor(self) -> ThreadPoolExecutor:
        with self._lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=self._max_workers,
                    thread_name_prefix="tts-stream")
            return self._executor

    def close(self) -> None:
        with self._lock:
            ex, self._executor = self._executor, None
            self._closed = True
        if ex is not None:
            try:
                ex.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    # ── 合成 ──

    @staticmethod
    def _is_speakable(text: str) -> bool:
        """该段是否有可朗读内容。

        纯空白、纯标点（如 markdown 的空行「\n\n」）不该送去 TTS ——
        GPT-SoVITS 会为它合成一段空音频，白白多花 1~2 秒。
        """
        if not text or not text.strip():
            return False
        return any(ch.isalnum() for ch in text)

    def _submit(self, seg: Segment) -> Future:
        executor = self._ensure_executor()

        def _work() -> Segment:
            try:
                chunks = list(self._voice.synthesize_stream(seg.text))
                if not chunks:
                    seg.error = getattr(self._voice, "last_error", "") or "TTS 无输出"
                    return seg
                import base64
                seg.audio_b64 = base64.b64encode(b"".join(chunks)).decode("ascii")
            except Exception as e:   # noqa: BLE001 - 单段失败不影响整体
                seg.error = str(e)
                logger.warning("分句 TTS 失败（index=%d）: %s", seg.index, e)
            return seg

        return executor.submit(_work)

    def run(self, text_chunks: Iterator[str]) -> Iterator[Segment]:
        """主流程：消费文本增量，按序产出音频段。"""
        if self._voice is None or not getattr(self._voice, "available", False):
            # TTS 不可用：仍然把全文按句切好返回（audio_b64=None），
            # 让调用方可以继续走纯文本路径而不必特判。
            buffer = ""
            index = 0
            for chunk in text_chunks:
                buffer += chunk or ""
                ready, buffer = split_sentences(buffer)
                for text in ready:
                    yield Segment(index=index, text=text, error="TTS 不可用")
                    index += 1
            ready, buffer = split_sentences(buffer, force=True)
            for text in ready:
                yield Segment(index=index, text=text, error="TTS 不可用")
                index += 1
            return

        buffer = ""
        index = 0
        pending: dict[int, Future] = {}
        next_to_yield = 0

        def _drain_ready(block: bool) -> Iterator[Segment]:
            """把已完成且顺序正确的段吐出来。"""
            nonlocal next_to_yield
            while next_to_yield in pending:
                fut = pending[next_to_yield]
                if not block and not fut.done():
                    return
                try:
                    seg = fut.result()
                except Exception as e:   # noqa: BLE001
                    seg = Segment(index=next_to_yield, text="", error=str(e))
                pending.pop(next_to_yield, None)
                next_to_yield += 1
                yield seg
                block = False   # 后续只取已完成的

        for chunk in text_chunks:
            buffer += chunk or ""
            ready, buffer = split_sentences(buffer)
            for text in ready:
                if not self._is_speakable(text):
                    continue
                seg = Segment(index=index, text=text)
                pending[index] = self._submit(seg)
                index += 1
            # 边生成边吐出已就绪的段 → 用户能尽早听到第一句
            yield from _drain_ready(block=False)

        # 流结束：把剩余文本也合成掉
        ready, buffer = split_sentences(buffer, force=True)
        for text in ready:
            if not self._is_speakable(text):
                continue
            seg = Segment(index=index, text=text)
            pending[index] = self._submit(seg)
            index += 1

        # 收尾：按序等待全部完成
        while next_to_yield < index:
            yield from _drain_ready(block=True)

    def run_text(self, text: str) -> Iterator[Segment]:
        """便利入口：把整段文本当作单个增量流。"""
        return self.run(iter([text]))
