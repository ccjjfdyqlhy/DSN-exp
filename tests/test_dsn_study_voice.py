"""dsn_study 语音（TTS）接入测试。

覆盖：
  1. 音色 profile 载入与参数构造（parallel / serial 两种架构）
  2. GPT-SoVITS HTTP 客户端（mock requests，不触网）
  3. VoiceService：合成 / 失败降级 / 文本清洗 / 状态视图
  4. infra 资源池注册（adopt 模式，不拉起服务）
  5. 对话链路：chat_audio 返回 {reply, audio_b64, tts_error}
  6. 真实服务联调（需 TTS_LIVE_TEST=1，会拉起 GPT-SoVITS，耗时分钟级）
"""

from __future__ import annotations

import base64
import io
import os
import wave

import pytest

# 测试期间不拉起真实 GPT-SoVITS（需 GPU + 分钟级权重加载）
os.environ.setdefault("TTS_AUTOSTART", "false")
os.environ.setdefault("TTS_WARMUP", "false")


def _wav_bytes(seconds: float = 0.5, rate: int = 16000) -> bytes:
    """构造一段最小合法 WAV。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


# ── 1. profile ──

def test_profile_manager_loads_bundled_profiles():
    from apps.dsn_study.models.tts_profile import TTSProfileManager
    mgr = TTSProfileManager()
    assert mgr.list_profiles(), "未载入任何音色 profile"
    assert mgr.default_name in mgr.profiles
    prof = mgr.get_profile()
    assert prof.ref_audio_path.endswith(".wav")
    assert os.path.isfile(prof.ref_audio_path), "参考音频不存在: %s" % prof.ref_audio_path


def test_profile_params_by_architecture():
    from apps.dsn_study.models.tts_profile import TTSProfile, TTSProfileManager
    from pathlib import Path
    mgr = TTSProfileManager()
    base = Path(mgr.config_path).parent

    serial = TTSProfile.from_dict("s", {
        "architecture": "serial", "ref_audio_path": "ref_advanced.wav",
        "prompt_text": "参考文本", "prompt_lang": "zh", "text_lang": "zh",
    }, base)
    p = serial.build_params("你好")
    assert "text_language" in p and "refer_wav_path" in p and "prompt_language" in p

    parallel = TTSProfile.from_dict("p", {
        "architecture": "parallel", "ref_audio_path": "ref.wav",
        "prompt_text": "ref", "prompt_lang": "en", "text_lang": "zh",
    }, base)
    p2 = parallel.build_params("你好")
    assert "text_lang" in p2 and "ref_audio_path" in p2 and "prompt_lang" in p2


# ── 2. 客户端 ──

def test_client_synthesize_and_probe(monkeypatch):
    from apps.dsn_study.models import tts_client as mod
    audio = _wav_bytes()

    class _Resp:
        status_code = 200
        content = audio
        text = ""

    class _Session:
        def __init__(self):
            self.posts = []

        def post(self, url, json=None, timeout=None):
            self.posts.append((url, json))
            return _Resp()

        def get(self, url, timeout=None):
            class _R:
                status_code = 400  # GPT-SoVITS 缺参数时返回 400也算就绪
            return _R()

    c = mod.TTSClient("http://127.0.0.1:9880")
    c.session = _Session()
    out = c.synthesize({"text": "你好", "text_language": "zh"}, architecture="serial")
    assert out == audio
    assert c.session.posts[0][0].endswith("/"), "serial 架构端点应为 /"
    assert c.probe() is True


def test_client_errors():
    from apps.dsn_study.models.tts_client import TTSClient, TTSRequestError
    c = TTSClient("http://127.0.0.1:9880")
    with pytest.raises(TTSRequestError):
        c.synthesize({"text": ""})

    class _BadSession:
        def post(self, url, json=None, timeout=None):
            class _R:
                status_code = 500
                content = b""
                text = "boom"
            return _R()

    c.session = _BadSession()
    with pytest.raises(TTSRequestError):
        c.synthesize({"text": "x"}, architecture="parallel")


# ── 3. VoiceService ──

class _StubVoice:
    """替身语音门面（不触真实服务）。"""

    def __init__(self, audio=None, error=""):
        self._audio = audio
        self._error = error
        self.calls = []

    def synthesize_b64(self, text):
        self.calls.append(text)
        if self._error:
            return None, self._error
        if self._audio is None:
            return None, "未就绪"
        return base64.b64encode(self._audio).decode("ascii"), ""


def test_voice_synthesize_b64(monkeypatch):
    from apps.dsn_study.voice import VoiceService
    audio = _wav_bytes()

    class _Pool:
        def lease(self, name):
            import contextlib
            @contextlib.contextmanager
            def _cm():
                yield object()
            return _cm()

    class _Client:
        def synthesize(self, params, architecture="parallel"):
            return audio

    class _Profiles:
        def list_profiles(self):
            return ["advanced"]

        def default_name(self):
            return "advanced"

        def get_profile(self, name=None):
            from apps.dsn_study.models.tts_profile import TTSProfile
            return TTSProfile(name="advanced", ref_audio_path="/x/ref.wav",
                               prompt_text="p", prompt_lang="zh", text_lang="zh",
                               architecture="serial")

    svc = VoiceService(pool=_Pool(), client=_Client(), profiles=_Profiles())
    assert svc.available
    b64, err = svc.synthesize_b64("今天复习二次函数")
    assert err == "" and b64
    assert base64.b64decode(b64) == audio


def test_voice_failure_degrades_gracefully():
    from apps.dsn_study.voice import VoiceService
    svc = VoiceService()
    assert svc.available is False
    b64, err = svc.synthesize_b64("任意文本")
    assert b64 is None and err


def test_voice_text_cleaning():
    from apps.dsn_study.voice import VoiceService
    raw = "```python\nprint(1)\n``` 这是 **重点** <b>标签</b> 🎉 结束"
    out = VoiceService._clean_text(raw)
    assert "print(1)" not in out
    assert "**" not in out and "<b>" not in out
    assert "🎉" not in out
    assert "重点" in out


# ── 4. 资源池注册 ──

def test_tts_resource_registered_in_pool(monkeypatch):
    """adopt 模式：只注册不拉起（不依赖本机 conda/GPU）。"""
    from apps.dsn_study.config import Config
    from apps.dsn_study.models import resource_setup as rs
    # 直接 patch Config 属性：Config 在导入期读 env，运行期改 env 无效
    monkeypatch.setattr(Config, "TTS_AUTOSTART", False, raising=False)
    pool = rs.ResourcePool(max_concurrent=1)
    rs._build_tts(pool)  # noqa: SLF001 —— 测试直接验证注册路径
    spec = pool.get_spec(rs.TTS_RESOURCE)
    assert spec is not None
    assert spec.kind == rs.ResourceKind.TTS
    assert spec.resident is True, "TTS 必须常驻（避免每次合成重拉服务）"
    assert spec.immediate is False
    info = [r for r in pool.list_resources() if r["name"] == rs.TTS_RESOURCE][0]
    assert info.get("adopt") is True


def test_tts_launch_spec_conda_mode(monkeypatch):
    """conda 模式：argv[0] 必须是目标环境的解释器。"""
    from apps.dsn_study.config import Config
    from apps.dsn_study.models import resource_setup as rs
    monkeypatch.setattr(Config, "TTS_AUTOSTART", True, raising=False)
    monkeypatch.setattr(Config, "TTS_LAUNCH_MODE", "conda", raising=False)
    monkeypatch.setattr(Config, "TTS_CONDA_ENV", "GPTSoVits", raising=False)
    spec = rs._tts_launch_spec()  # noqa: SLF001
    assert spec is not None
    assert spec.mode == rs.LaunchMode.CONDA
    assert spec.conda_env == "GPTSoVits"
    assert spec.command[0].endswith("python") or spec.command[0] == "python"
    assert any("api.py" in c for c in spec.command)


# ── 5. 对话链路 ──

def test_chat_audio_returns_audio(monkeypatch):
    """对话回复应自动附带语音。"""
    from apps.dsn_study import boot
    from infra.models.base import ChatResponse

    class _Fake:
        def invoke(self, messages, tools=None, **kw):
            return ChatResponse(content="这是回复内容")

    app = boot.create_application()
    engine = boot.engine
    monkeypatch.setattr(engine.agent, "chat_client", _Fake())
    audio = _wav_bytes()
    monkeypatch.setattr(engine, "voice", _StubVoice(audio=audio))

    out = engine.chat_audio("打个招呼", user_id=1)
    assert out["reply"] == "这是回复内容"
    assert out["audio_b64"] == base64.b64encode(audio).decode("ascii")
    assert out["tts_error"] == ""

    # chat() 契约不变：仍只返回文本
    assert engine.chat("再问一次", user_id=1) == "这是回复内容"


def test_chat_audio_degrades_when_tts_fails(monkeypatch):
    from apps.dsn_study import boot
    from infra.models.base import ChatResponse

    class _Fake:
        def invoke(self, messages, tools=None, **kw):
            return ChatResponse(content="文本回复")

    app = boot.create_application()
    engine = boot.engine
    monkeypatch.setattr(engine.agent, "chat_client", _Fake())
    monkeypatch.setattr(engine, "voice", _StubVoice(error="TTS 服务不可用"))

    out = engine.chat_audio("你好", user_id=1)
    assert out["reply"] == "文本回复"
    assert out["audio_b64"] is None
    assert out["tts_error"] == "TTS 服务不可用"


def test_voice_routes_registered():
    from apps.dsn_study import boot
    app = boot.create_application()
    rules = {r.rule for r in app.url_map.iter_rules()}
    assert "/api/voice/status" in rules
    assert "/api/voice/start" in rules
    assert "/api/voice/stop" in rules


# ── 6. 真实服务联调（可选） ──

@pytest.mark.skipif(os.environ.get("TTS_LIVE_TEST") != "1",
                    reason="需 TTS_LIVE_TEST=1；会真实拉起 GPT-SoVITS（加载 GPU 权重）")
def test_live_tts_synthesis():
    """真实 GPT-SoVITS 联调：经 infra 资源池拉起服务并合成语音。"""
    from apps.dsn_study.voice import VoiceService
    svc = VoiceService.create()
    assert svc.available
    b64, err = svc.synthesize_b64("今天我们复习二次函数的顶点公式。")
    assert b64, err
    raw = base64.b64decode(b64)
    w = wave.open(io.BytesIO(raw))
    assert w.getframerate() > 0 and w.getnframes() > 0
