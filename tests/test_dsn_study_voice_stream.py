# tests/test_dsn_study_voice_stream.py
# 方案 D（LLM 流式 → 分句 → 并发 TTS）的回归测试。
#
# 覆盖：
#   1. 分句器边界（增量累积 / 短碎片 / 逗号 / 无标点长句 / force）
#   2. 有序保证（后一句先完成也必须按序下发）
#   3. 降级路径（TTS 不可用 / 单段失败都不能丢文本）
#   4. TTS 客户端流式请求体（cut_punc 必须携带）
#   5. 客户端音频格式探测（流式回 Ogg，不能一律当 WAV）

from __future__ import annotations

import time

import pytest


# ── 1. 分句器 ──

def test_split_basic_sentences():
    from apps.dsn_study.voice_stream import split_sentences
    ready, rest = split_sentences("第一句内容够长。第二句也够长。")
    assert ready == ["第一句内容够长。", "第二句也够长。"]
    assert rest == ""


def test_split_incremental_does_not_merge_across_boundary():
    """增量累积时，前半句不能被后面的完整句吞掉。

    回归：早期实现用零宽 lookbehind 正则 split，切点原地打转，
    把「重点。」和「它的图像」拼成了一句。
    """
    from apps.dsn_study.voice_stream import split_sentences
    buf = ""
    ready, buf = split_sentences(buf + "二次函数是")
    assert ready == [] and buf == "二次函数是"

    ready, buf = split_sentences(buf + "重点。它的图像")
    assert ready == ["二次函数是重点。"]
    assert buf == "它的图像"


def test_split_short_fragment_merges_forward():
    """短碎片向后并，而不是把下一句吞进来。"""
    from apps.dsn_study.voice_stream import split_sentences
    ready, buf = split_sentences("嗯。")
    assert ready == [] and buf == "嗯。"
    ready, buf = split_sentences(buf + "我觉得二次函数要先配方。")
    assert ready == ["嗯。我觉得二次函数要先配方。"]


def test_split_comma_cuts():
    from apps.dsn_study.voice_stream import split_sentences
    ready, _ = split_sentences("首先看一般式，然后化成顶点式，最后求最值。")
    assert len(ready) >= 2


def test_split_force_flushes_tail():
    from apps.dsn_study.voice_stream import split_sentences
    ready, rest = split_sentences("最后一句没标点", force=True)
    assert ready == ["最后一句没标点"] and rest == ""


def test_split_long_text_without_punct_is_chunked():
    from apps.dsn_study.voice_stream import MAX_BUFFER_CHARS, split_sentences
    ready, rest = split_sentences("a" * (MAX_BUFFER_CHARS * 2 + 10))
    assert len(ready) >= 2
    assert all(len(x) <= MAX_BUFFER_CHARS for x in ready)
    assert len(rest) < MAX_BUFFER_CHARS


# ── 2. 有序保证 ──

def test_pipeline_preserves_order_when_later_segment_finishes_first():
    """后一句先合成完也必须按序下发 —— 否则用户听到倒装句。"""
    from apps.dsn_study.voice_stream import StreamingVoicePipeline

    class Voice:
        available = True
        last_error = ""

        def synthesize_stream(self, text):
            # 越长的句子越快返回，制造乱序完成
            time.sleep(max(0.01, 0.3 - len(text) * 0.01))
            yield b"A"

    p = StreamingVoicePipeline(Voice(), max_workers=3)
    try:
        segs = list(p.run(iter([
            "这是第一句比较长的话。",
            "第二句。",
            "第三句更更长一些的内容。",
        ])))
    finally:
        p.close()
    assert [s.index for s in segs] == sorted(s.index for s in segs)
    assert all(s.audio_b64 for s in segs)


# ── 3. 降级路径 ──

def test_pipeline_degrades_when_tts_unavailable():
    from apps.dsn_study.voice_stream import StreamingVoicePipeline

    class Dead:
        available = False
        last_error = "TTS disabled"

    p = StreamingVoicePipeline(Dead())
    try:
        segs = list(p.run(iter(["你好。", "今天。"])))
    finally:
        p.close()
    assert segs, "TTS 不可用时仍须返回文本分段"
    assert all(s.audio_b64 is None for s in segs)
    assert any(s.error for s in segs)


def test_pipeline_keeps_text_when_synthesis_raises():
    """单段 TTS 抛异常不能连累文本。"""
    from apps.dsn_study.voice_stream import StreamingVoicePipeline

    class Broken:
        available = True
        last_error = ""

        def synthesize_stream(self, text):
            raise RuntimeError("boom")

    p = StreamingVoicePipeline(Broken())
    try:
        segs = list(p.run(iter(["第一句内容够长。"])))
    finally:
        p.close()
    assert len(segs) == 1
    assert segs[0].audio_b64 is None
    assert segs[0].text


# ── 4. TTS 客户端流式请求体 ──

def test_stream_request_carries_cut_punc():
    """不传 cut_punc 时服务端不切句，流式形同虚设。"""
    from apps.dsn_study.models.tts_client import TTSClient

    class Resp:
        status_code = 200
        text = ""

        def iter_content(self, chunk_size=None):
            yield b"a"
            yield b"b"

        def close(self):
            pass

    class Session:
        def __init__(self):
            self.captured = None

        def post(self, url, json=None, timeout=None, stream=False):
            self.captured = {"url": url, "json": json, "stream": stream}
            return Resp()

    c = TTSClient("http://127.0.0.1:1")
    c.session = Session()
    chunks = list(c.synthesize_stream(
        {"text": "你好。今天。", "text_lang": "zh",
         "ref_audio_path": "/r.wav", "prompt_lang": "zh", "prompt_text": "p"},
        "serial"))
    assert chunks == [b"a", b"b"]
    assert c.session.captured["json"]["cut_punc"]
    assert c.session.captured["stream"] is True
    # serial 架构要转成 GPT-SoVITS 原生键名
    assert "text_language" in c.session.captured["json"]
    assert "refer_wav_path" in c.session.captured["json"]


def test_probe_streaming_requires_real_params():
    """空参数探测会恒定 False（服务端返回「未指定参考音频」）。"""
    from apps.dsn_study.models.tts_client import TTSClient
    c = TTSClient("http://127.0.0.1:1")
    assert c.probe_streaming({}) is False


# ── 5. 客户端音频格式探测 ──

@pytest.mark.parametrize("raw,expected", [
    (b"RIFF\x00\x00\x00\x00WAVEfmt ", ".wav"),
    (b"OggS\x00\x02", ".ogg"),
    (b"ID3\x04", ".mp3"),
    (b"fLaC\x00\x00", ".flac"),
    (b"", ".bin"),
])
def test_audio_suffix_detection(raw, expected):
    """流式模式回 Ogg：一律当 WAV 会让播放器静默失败。"""
    from apps.dsn_study_cli.tts import _audio_suffix
    assert _audio_suffix(raw) == expected


# ── 6. 纯空白/纯标点段 ──

def test_pipeline_skips_unspeakable_segments():
    """纯空白/纯标点段不该送 TTS（会合成一段空音频白等 1~2 秒）。"""
    from apps.dsn_study.voice_stream import StreamingVoicePipeline

    class Voice:
        available = True
        last_error = ""
        calls = 0

        def synthesize_stream(self, text):
            Voice.calls += 1
            yield b"A"

    p = StreamingVoicePipeline(Voice())
    try:
        segs = list(p.run(iter(["你好。", "\n\n", "今天。"])))
    finally:
        p.close()
    assert all(s.text.strip() for s in segs)
    assert all(any(c.isalnum() for c in s.text) for s in segs)


# ── 7. 流式 AgentLoop 的原生 tool call ──

def test_runtime_stream_executes_native_tool_call():
    """流式路径必须保留原生 tool call：调用 → 执行 → 回喂 → 继续生成。

    回归：早期方案 D 走的是「直连模型流式」，绕过了 AgentLoop，
    模型吐的 <tool> 标签没人解析，JSON 被当正文念出来。
    """
    import asyncio
    from harness import AgentRuntime

    class Stub:
        def __init__(self):
            self.rounds = 0

        async def stream(self, messages, tools=None, **kw):
            self.rounds += 1
            if self.rounds == 1:
                yield {"tool_calls": [{
                    "index": 0, "id": "c1", "name": "demo__echo",
                    "arguments": '{"x":"hi"}'}]}
            else:
                yield "工具返回："
                yield "hi"

        def invoke(self, messages, tools=None, **kw):
            from infra.models import ChatResponse
            return ChatResponse(content="fallback")

    rt = AgentRuntime(Stub(), name="t")
    rt.register_tool("demo.echo", "回显", lambda x="": {"echo": x},
                     parameters={"type": "object",
                                 "properties": {"x": {"type": "string"}}})

    async def collect():
        kinds, calls, results, text = [], [], [], []
        async for ev in rt.run_stream_with_tools("测试工具"):
            kinds.append(ev.kind)
            if ev.kind == "tool_call":
                calls.append(ev.tool_call["name"])
            elif ev.kind == "tool_result":
                results.append(ev.tool_result["success"])
            elif ev.kind == "delta" and ev.content:
                text.append(ev.content)
        return kinds, calls, results, "".join(text)

    kinds, calls, results, text = asyncio.run(collect())
    assert "tool_call" in kinds and "tool_result" in kinds
    assert calls == ["demo.echo"]
    assert results == [True]
    assert text == "工具返回：hi"


def test_runtime_stream_writes_history_once():
    """流结束时写一次助手历史（不能重复写）。"""
    import asyncio
    from harness import AgentRuntime

    class Stub:
        async def stream(self, messages, tools=None, **kw):
            yield "好的。"

        def invoke(self, messages, tools=None, **kw):
            from infra.models import ChatResponse
            return ChatResponse(content="x")

    rt = AgentRuntime(Stub(), name="t")

    async def run():
        async for _ in rt.run_stream_with_tools("你好", session_id="s1"):
            pass

    asyncio.run(run())
    conv = rt.conversations.get("s1")
    roles = [m.role for m in conv.messages]
    assert roles.count("assistant") == 1
    assert roles.count("user") == 1
