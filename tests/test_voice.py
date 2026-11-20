# tests/test_voice.py
# roadmap 段 5 的验收测试：全模态交互层（开口即达）。
#
# 验收标准（roadmap 原文）：`aicf run "..."` 之外，能有一条命令让它
# **开口说话** —— 前提是交互层在框架里存在且可测。四组断言：
#   1. 流式逐句朗读：第一句合成完就开始播，不等整段
#   2. 假语音过滤：噪声不进对话史，真话不被误伤
#   3. 感知模式：沉默 = 在听，循环不退出
#   4. 心跳：空闲主动开口
# 全部用端口桩（fake），不需要任何真语音模型。

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aicf.harness.voice import (
    CompositeSpeechFilter,
    HeuristicSpeechFilter,
    SentenceSplitter,
    SentenceStreamSpeaker,
    SpeechVerdict,
    VoiceSession,
)


# ── 端口桩 ──────────────────────────────────────────────────

class FakeTTS:
    """记录调用顺序的 TTS 桩；synthesize_stream 逐块给。"""

    def __init__(self, chunks_per_sentence: int = 2, delay_sentences=None):
        self.calls: list[tuple[str, str]] = []   # (method, text)
        self.chunks_per_sentence = chunks_per_sentence
        self.stream_broken = False

    def synthesize(self, text, **params):
        self.calls.append(('synthesize', text))
        return f'<audio:{text}>'.encode()

    def synthesize_stream(self, text, **params):
        self.calls.append(('synthesize_stream', text))
        if self.stream_broken:
            return iter([])          # 不支持流式的退化实现
        for i in range(self.chunks_per_sentence):
            yield f'<chunk{i}:{text}>'.encode()


class FakeSink:
    def __init__(self):
        self.played: list[bytes] = []
        self.flushed = 0

    def play(self, data):
        self.played.append(data)

    def flush(self):
        self.flushed += 1


# ── 1. 拆句 ─────────────────────────────────────────────────

def test_splitter_cjk_and_latin():
    s = SentenceSplitter()
    assert s.split('你好。大家好！Hello world. Real?') == [
        '你好。', '大家好！', 'Hello world.', 'Real?']


def test_splitter_keeps_decimal_numbers():
    s = SentenceSplitter()
    assert s.split('圆周率是 3.14 吗') == ['圆周率是 3.14 吗']
    assert s.split('先说 3.14。再见。') == ['先说 3.14。', '再见。']


def test_splitter_hard_wraps_unpunctuated_run():
    s = SentenceSplitter(max_chars=10)
    parts = s.split('这' * 35)
    assert all(len(p) <= 10 for p in parts)
    assert ''.join(parts) == '这' * 35


# ── 2. 流式逐句朗读 ─────────────────────────────────────────

def test_speaker_plays_sentence_by_sentence_without_waiting():
    """第一句合成完就开始播 —— 播放先于第二句的合成完成。"""
    tts = FakeTTS()
    sink = FakeSink()
    events: list[str] = []
    speaker = SentenceStreamSpeaker(
        tts=tts, sink=sink,
        on_sentence_start=lambda s: events.append(f'start:{s}'),
        on_chunk=lambda s, n: events.append(f'play:{s}'),
        on_sentence_end=lambda s: events.append(f'end:{s}'),
    )
    spoken = speaker.speak('第一句。第二句。第三句。')
    assert spoken == 3
    # 逐句交错：start(i) → play(i)*2 → end(i) → start(i+1) …
    assert events[0] == 'start:第一句。'
    assert events[1:3] == ['play:第一句。', 'play:第一句。']
    assert events[3] == 'end:第一句。'
    assert events[4] == 'start:第二句。'
    # 播放的顺序是句间串行、句内成块
    assert len(sink.played) == 3 * 2


def test_speaker_falls_back_when_stream_broken():
    """流式端口一个块都不给 → 整段兜底，绝不「以为在播其实没声」。"""
    tts = FakeTTS()
    tts.stream_broken = True
    sink = FakeSink()
    speaker = SentenceStreamSpeaker(tts=tts, sink=sink)
    spoken = speaker.speak('只有一句。')
    assert spoken == 1
    assert sink.played == ['<audio:只有一句。>'.encode('utf-8')]


def test_speaker_stop_cancels_between_chunks():
    tts = FakeTTS()
    sink = FakeSink()
    speaker = SentenceStreamSpeaker(tts=tts, sink=sink)

    state = {'count': 0}

    def maybe_stop(sentence, n):
        state['count'] += 1
        # 每句 2 块：第 3 块 = 第二句的第一块 —— 第一句完整播出后停
        if state['count'] == 3:
            speaker.stop()

    speaker.on_chunk = maybe_stop
    spoken = speaker.speak('一。二。三。四。')
    assert spoken == 1          # 第一句完整，第二句被掐掉
    assert speaker.stopped
    # 第三句根本没合成（合成调用只有前两句 + 兜底检查）
    assert not any(text.startswith('三') for _method, text in tts.calls)


# ── 3. 假语音过滤 ───────────────────────────────────────────

@pytest.mark.parametrize('text,reason', [
    ('啊啊啊啊啊啊啊', 'repeated_run'),
    ('！！！！！！！', 'mostly_symbols'),
    ('。！？，', 'mostly_symbols'),
    ('bcdfghjklmnp', 'consonant_run'),
    ('', 'empty'),
])
def test_heuristic_filter_rejects_noise(text, reason):
    verdict = HeuristicSpeechFilter().classify(text)
    assert verdict.accepted is False
    assert verdict.reason == reason


@pytest.mark.parametrize('text', [
    '今天天气怎么样',
    '停',
    '嗯',
    '继续',
    '我的验证码是 8 6 7 5 3 0 9',
    'hello world, please help me',
])
def test_heuristic_filter_does_not_kill_speech(text):
    """宁可放进一句噪声，不可掐掉一句真话（单字指令也是指令）。"""
    assert HeuristicSpeechFilter().classify(text).accepted is True


def test_classifier_port_wins_and_survives_crash():
    class _OneB:
        def __init__(self, explode=False):
            self.explode = explode
            self.calls = []

        def classify(self, text, *, audio=None):
            if self.explode:
                raise RuntimeError('分类器挂了')
            self.calls.append(text)
            return SpeechVerdict.reject('classifier-says-noise')

    port = _OneB()
    combined = CompositeSpeechFilter(port=port)
    # 端口的判定就是结果（即使启发式会放行）
    assert combined.classify('今天天气怎么样').reason == 'classifier-says-noise'
    # 端口挂了 → 退化为启发式，不卡死通话
    port.explode = True
    assert combined.classify('今天天气怎么样').accepted is True


# ── 4. 感知模式 ─────────────────────────────────────────────

class FakeIO:
    """脚本化的 IO 桩：按剧本依次给「音频」（测试里就是文本）；
    回答由 reply_fn 决定。"""

    def __init__(self, script, speaker, asr_text=None):
        self.script = list(script)
        self.speaker = speaker
        self.asr = _FakeASR(asr_text or (lambda a: a.decode('utf-8')
                                         if isinstance(a, bytes) else a))

    def listen(self, *, timeout=None):
        return self.script.pop(0) if self.script else None


class _FakeASR:
    def __init__(self, fn):
        self.fn = fn

    def transcribe(self, audio):
        return self.fn(audio)


def test_perceptive_mode_survives_silence_and_filters_noise():
    """沉默（None）不是错误 —— 循环继续；假语音不进对话史。

    stop 条件用「剧本演完」—— 感知模式本来就不因沉默退出。
    """
    tts = FakeTTS()
    sink = FakeSink()
    speaker = SentenceStreamSpeaker(tts=tts, sink=sink)
    io = FakeIO(
        script=[None, '啊啊啊啊啊啊', '现在几点了', None, '谢谢'],
        speaker=speaker)
    replies: list[str] = []
    turns = []
    session = VoiceSession(io, reply_fn=lambda t: (replies.append(t), f'回答：{t}')[1],
                           on_turn=turns.append)
    rounds = session.run_forever(stop=lambda: not io.script)
    assert rounds == 2                       # 两轮真对话（噪声与沉默不算）
    assert replies == ['现在几点了', '谢谢']   # 噪声没进对话史
    assert session.rejected_turns == 1
    assert session.state.value == 'listening'


def test_heartbeat_speaks_when_idle():
    tts = FakeTTS()
    sink = FakeSink()
    speaker = SentenceStreamSpeaker(tts=tts, sink=sink)
    io = FakeIO(script=[None, None, '现在几点了'], speaker=speaker)
    session = VoiceSession(io, reply_fn=lambda t: f'回答：{t}')
    beats = {'calls': 0}

    def hook(idle_seconds):
        beats['calls'] += 1
        return '你还在吗？需要我提醒你什么吗？' if beats['calls'] == 1 else None

    session.enable_heartbeat(hook, interval=0.0, min_gap=100.0)
    session.run_forever(stop=lambda: not io.script)
    # 空闲心跳触发过一次主动开口（逐句合成 —— 同一句话的各句都到位）
    assert beats['calls'] >= 1
    spoken_texts = [text for _method, text in tts.calls]
    assert '你还在吗？' in spoken_texts
    assert '需要我提醒你什么吗？' in spoken_texts


def test_heartbeat_silent_until_interval():
    io = FakeIO(script=[None], speaker=SentenceStreamSpeaker(FakeTTS(), FakeSink()))
    session = VoiceSession(io, reply_fn=lambda t: t)
    clock = {'now': 0.0}
    session.enable_heartbeat(lambda idle: 'beat', interval=100.0)
    session.heartbeat.clock = lambda: clock['now']
    session.heartbeat.touch()                # 交互在 t=0
    clock['now'] = 50.0
    assert session.heartbeat.check() is None  # 没到点
    clock['now'] = 150.0
    assert session.heartbeat.check() == 'beat'


def test_turn_records_history_entry():
    io = FakeIO(script=['你好'], speaker=SentenceStreamSpeaker(FakeTTS(), FakeSink()))
    turns = []
    session = VoiceSession(io, reply_fn=lambda t: '你好呀', on_turn=turns.append)
    assert session.turn('你好'.encode('utf-8')) is True
    assert len(turns) == 1
    assert turns[0].heard == '你好' and turns[0].reply == '你好呀'
    assert turns[0].interrupted is False
