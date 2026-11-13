# tests/test_dsn_study_voice_latency.py
# 语音链路（对讲机）相关的回归测试。
#
# 背景：语音场景的体感延迟 = 静音等待 + 上传/ASR + LLM + TTS。
# 这几条链路上踩过的坑都在这里钉住。

import os

import pytest


# ── 静音等待 ────────────────────────────────────────────────

def test_silence_timeout_default_is_short():
    """默认静音等待应为 0.9s（原 2.0s 直接计入对讲机体感延迟）。"""
    from apps.dsn_study_cli import audio
    assert audio.SILENCE_TIMEOUT <= 1.0, "静音等待过长，用户说完还要干等"


def test_silence_timeout_env_override():
    """可用 STUDY_SILENCE_TIMEOUT 覆盖。"""
    from apps.dsn_study_cli import audio
    assert audio.SILENCE_TIMEOUT == float(
        os.environ.get("STUDY_SILENCE_TIMEOUT", "0.9"))


# ── ASR 设备号（invalid device ordinal）────────────────────────

def test_asr_device_does_not_carry_physical_gpu_ordinal(monkeypatch):
    """ASR_GPU_ID 是物理卡号（给 CUDA_VISIBLE_DEVICES 用），不能进 --device。

    子进程被钉到单卡后进程内序号是 0；再传 cuda:1 会
    "CUDA error: invalid device ordinal"，模型根本加载不了。
    """
    from apps.dsn_study.config import Config
    from apps.dsn_study.models import resource_setup

    monkeypatch.setattr(Config, "ASR_DEVICE", "cuda", raising=False)
    monkeypatch.setattr(Config, "ASR_GPU_ID", "1", raising=False)
    assert resource_setup._asr_device() == "cuda", \
        "带了物理卡号 → 进程内越界，ASR 模型加载不了"


def test_asr_device_passes_through_explicit_ordinal(monkeypatch):
    """ASR_DEVICE 自带序号且不钉卡时，原样透传。"""
    from apps.dsn_study.config import Config
    from apps.dsn_study.models import resource_setup

    monkeypatch.setattr(Config, "ASR_DEVICE", "cuda:1", raising=False)
    monkeypatch.setattr(Config, "ASR_GPU_ID", "", raising=False)
    assert resource_setup._asr_device() == "cuda:1"


# ── 语音模式的 system prompt ──────────────────────────────────

def test_voice_mode_uses_light_prompt(monkeypatch):
    """语音轮要用轻量 prompt：不含 17KB 技能说明。

    「短回复指令（40 字上限）」现在是**可选**的（Config.VOICE_SHORT_REPLY）：
    默认关闭 —— 它会把主AI 钉死在「只回一两句话」，讲题都讲不开。
    """
    from harness.pipeline.base import Context, HookPoint
    from apps.dsn_study.config import Config
    from apps.dsn_study.pipeline import plugins
    from apps.dsn_study.prompts.builder import StudyPromptBuilder

    b = StudyPromptBuilder()
    p = plugins.SystemPromptPlugin(prompt_builder=b)

    voice = Context(user_id=1, message="在吗", session_id="t",
                    is_asr_input=True)
    out = p.on_hook(HookPoint.PREPARE, voice)
    text_out = Context(user_id=1, message="在吗", session_id="t",
                        is_asr_input=False)
    out2 = p.on_hook(HookPoint.PREPARE, text_out)

    # 默认：语音轮**不**注入 40 字上限（主AI 可以完整回答）
    assert "语音对话模式" not in (out.system_prompt or ""), \
        "语音轮不该被强制压成短回复"
    assert "语音对话模式" not in (out2.system_prompt or ""), \
        "文本轮不该被塞语音指令"

    # 开关打开时：短回复指令回来（要「快答」的场景用）
    monkeypatch.setattr(Config, "VOICE_SHORT_REPLY", True, raising=False)
    out3 = p.on_hook(HookPoint.PREPARE, voice)
    assert "语音对话模式" in (out3.system_prompt or ""), \
        "开关打开后语音轮应有短回复指令"


def test_voice_prompt_tags_exclude_skills():
    """语音模式保留的标签里不能有 skills（那是 17KB 的说明书）。"""
    from apps.dsn_study.pipeline.plugins import VOICE_PROMPT_TAGS
    assert "skills" not in VOICE_PROMPT_TAGS
    assert "core" in VOICE_PROMPT_TAGS


def test_compact_skill_index_is_much_smaller():
    """紧凑索引应远小于完整技能说明。"""
    from apps.dsn_study.boot import get_engine
    eng = get_engine()
    builder = getattr(eng, "_prompt_builder", None) or \
        getattr(eng, "prompt_builder", None)
    if builder is None:
        pytest.skip("引擎未装配")
    full = builder.build(uid=1)
    idx = builder.compact_skill_index()
    assert idx, "紧凑索引为空"
    assert len(idx) < len(full) / 2, \
        f"紧凑索引 {len(idx)} 字 vs 完整 {len(full)} 字，没起到瘦身作用"


# ── 语音模式指令内容 ──────────────────────────────────────────

def test_voice_instruction_mentions_length_limit():
    from apps.dsn_study.pipeline.plugins import VOICE_MODE_INSTRUCTION
    assert "40" in VOICE_MODE_INSTRUCTION, "必须给出字数上限，否则模型会写长"
    assert "语音对话模式" in VOICE_MODE_INSTRUCTION


# ── 录音帧类型兼容 ────────────────────────────────────────────

def test_frame_to_bytes_handles_list_and_bytes():
    """pvrecorder 1.2.7 的 read() 返回 int16 列表，不是 bytes。

    `bytes(bytearray(list))` 会抛 "byte must be in range(0, 256)"。
    """
    from apps.dsn_study_cli.audio import frame_to_bytes, rms_of

    samples = [100, -200, 3000, -4000]
    as_list = frame_to_bytes(samples)
    assert len(as_list) == len(samples) * 2
    assert frame_to_bytes(as_list) == as_list
    assert abs(rms_of(samples) - rms_of(as_list)) < 1e-9


def test_recorder_accepts_list_frames():
    """录音循环遇到 list 帧不能崩。"""
    from apps.dsn_study_cli.audio import VoiceRecorder

    rec = VoiceRecorder(device_index=-1)
    samples = [0] * 512
    rec._samples.append(__import__("apps.dsn_study_cli.audio",
                                   fromlist=["frame_to_bytes"]
                                   ).frame_to_bytes(samples))
    assert rec._samples and isinstance(rec._samples[0], bytes)
