# tests/test_onboarding_phases.py
# onboarding.py AI 分阶段引导 状态机测试（mock 模型回复 + mock 用户输入）

import os
import sys
import tempfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import onboarding


class _MockChat:
    """模拟 OpenAIChat：按顺序返回预设回复。"""

    def __init__(self, replies: list[str]):
        self._replies = list(replies)
        self.messages = []
        self.max_history = 0

    def send_message(self, message: str, **kwargs) -> str:
        return self._next()

    def continue_conversation(self, **kwargs) -> str:
        return self._next()

    def _next(self) -> str:
        if not self._replies:
            return "[CONFIG_COMPLETE]"
        return self._replies.pop(0)


def _run_flow(replies: list[str], user_inputs: list[str]) -> bool:
    chat = _MockChat(replies)
    env_info = {
        "python": {"version": "3.12", "ok": True},
        "services": {
            "tts": {"name": "GPT-SoVITS (TTS)", "running": False},
            "2md": {"name": "2md (文档解析)", "running": False},
            "lmstudio": {"name": "LMStudio (本地模型)", "running": True},
        },
    }
    inputs = iter(user_inputs + ["n"] * 50)  # 兜底输入
    with mock.patch.object(onboarding, "_create_chat", return_value=chat), \
         mock.patch.object(onboarding, "_safe_input", side_effect=lambda *a, **k: next(inputs)), \
         mock.patch.object(onboarding, "_render_markdown", lambda *a, **k: None), \
         mock.patch.object(onboarding, "_recheck_services", return_value="- TTS: 运行中\n- 2md: 运行中\n- LMStudio: 运行中"), \
         mock.patch.object(onboarding.os, "system", lambda *a, **k: None), \
         mock.patch.object(onboarding, "_env_write", lambda *a, **k: None), \
         mock.patch.object(onboarding, "_create_character_card", lambda *a, **k: "custom_test"):
        return onboarding._ai_guided_configure("sk-test", env_info)


def test_full_flow_with_deep():
    print("=== 全流程: 依赖 → 基础 → 询问(同意) → 深度 → 完成 ===")
    replies = [
        "GPT-SoVITS 未运行，请安装后告诉我。",
        "好的，我来重新探测。[RECHECK_DEPS]",
        "依赖已就位！[DEPS_DONE]",
        "推荐用默认 EXA 角色卡。配置好了。[BASIC_DONE]",
        "是否继续深度配置？",
        "好的，开始深度配置。[DEEP_YES]",
        "[CONFIG]WORLD_ENABLED=true[/CONFIG]\n世界功能已启用。[CONFIG_COMPLETE]",
    ]
    inputs = ["已安装", "用EXA", "要", "世界开吧"]
    result = _run_flow(replies, inputs)
    assert result is True, f"flow should complete, got {result}"
    print("  PASSED")


def test_skip_deep():
    print("=== 全流程: 询问阶段用户拒绝深度配置 → 直接完成 ===")
    replies = [
        "所有依赖已就位，跳过安装。[DEPS_DONE]",
        "基础配置完成。[BASIC_DONE]",
        "是否继续深度配置？",
        "好的，到此为止。[DEEP_NO]",
    ]
    inputs = ["跳过", "用EXA", "不用"]
    result = _run_flow(replies, inputs)
    assert result is True
    print("  PASSED")


def test_config_whitelist():
    print("=== 配置白名单校验 ===")
    whitelist = onboarding._valid_config_keys()
    assert "OPENAI_API_KEY" in whitelist
    assert "WORLD_ENABLED" in whitelist
    assert "MAIN_MODEL_TYPE" in whitelist
    assert "INVALID_KEY_XYZ" not in whitelist
    print("  PASSED")


def test_manifest():
    print("=== 紧凑配置清单 ===")
    txt = onboarding._manifest_text(onboarding._BASIC_SECTIONS)
    # 基础清单应比完整 .env.example 小得多
    full = onboarding._get_env_config_info()
    assert len(txt) < len(full) * 0.3, f"basic manifest too big: {len(txt)} vs {len(full)}"
    assert "MAIN_MODEL_TYPE" in txt
    assert "OPENAI_API_KEY" in txt
    # 推荐默认值
    assert "openai" in txt  # MAIN_MODEL_TYPE 默认值
    print(f"  basic manifest {len(txt)}B << full {len(full)}B")
    print("  PASSED")


def test_config_batch_directive():
    print("=== [CONFIG_BATCH] 批量配置 ===")
    whitelist = onboarding._valid_config_keys()
    written = {}
    def _fake_write(key, value):
        written[key] = value
    with mock.patch.object(onboarding, "_env_write", side_effect=_fake_write):
        onboarding._handle_config_directive(
            "[CONFIG_BATCH]\nWORLD_ENABLED=true\nMEMORY_ENABLED=false\n[/CONFIG_BATCH]\n"
            "[CONFIG]NARRATIVE_ENABLED=true[/CONFIG]",
            whitelist,
        )
    assert written.get("WORLD_ENABLED") == "true"
    assert written.get("MEMORY_ENABLED") == "false"
    assert written.get("NARRATIVE_ENABLED") == "true"
    assert "INVALID_KEY" not in written
    print("  PASSED")


def test_provider_selection():
    print("=== API Provider 选择 ===")
    # 选择预设 DeepSeek
    with mock.patch.object(onboarding, "_safe_input", side_effect=["1"]):
        base, model = onboarding._pick_provider()
    assert base == "https://api.deepseek.com/v1"
    assert model == "deepseek-chat"

    # 选择自定义端点
    with mock.patch.object(onboarding, "_safe_input", side_effect=["7", "https://my.api/v1", "my-model"]):
        base, model = onboarding._pick_provider()
    assert base == "https://my.api/v1"
    assert model == "my-model"

    # 选择稍后配置
    with mock.patch.object(onboarding, "_safe_input", side_effect=["8"]):
        base, model = onboarding._pick_provider()
    assert base == "" and model == ""
    print("  PASSED")


def test_service_probe():
    print("=== 服务探活阈值 ===")
    class _FakeResp:
        def __init__(self, code):
            self.status_code = code
    import requests as _req
    orig = _req.get

    # GPT-SoVITS 根路径 400 → 视为可达（与运行时 probe 一致）
    _req.get = lambda url, timeout=3.0: _FakeResp(400)
    assert onboarding._probe_service("http://127.0.0.1:9880") is True
    # 连接拒绝 → 不可达
    def _refused(url, timeout=3.0):
        raise _req.ConnectionError("refused")
    _req.get = _refused
    assert onboarding._probe_service("http://127.0.0.1:9880") is False
    # 5xx → 不可达
    _req.get = lambda url, timeout=3.0: _FakeResp(500)
    assert onboarding._probe_service("http://x") is False
    _req.get = orig
    print("  PASSED")


def test_single_probe_and_waiting_hint():
    print("=== 单次探测 + 等待提示 ===")
    # 每个服务严格探测一次
    class _FakeResp:
        def __init__(self, code):
            self.status_code = code
    import requests as _req
    orig_get = _req.get
    counts = {"n": 0}
    def _fake_get(url, timeout=3.0):
        counts["n"] += 1
        return _FakeResp(400)
    _req.get = _fake_get
    try:
        with mock.patch.object(onboarding, "_env_read", side_effect=lambda k: ""):
            onboarding._check_third_party()
    finally:
        _req.get = orig_get
    assert counts["n"] == 3, f"每个服务应探测一次, 实际 {counts['n']}"

    # 等待提示
    class _C:
        def send_message(self, m):
            return "OK"
    with mock.patch("builtins.print") as mp:
        onboarding._chat_send_with_retry(_C(), "hi")
    texts = [str(c.args[0]) for c in mp.call_args_list]
    assert any("提示词正在注入" in t for t in texts), texts
    print("  PASSED")


if __name__ == "__main__":
    test_manifest()
    test_config_whitelist()
    test_config_batch_directive()
    test_provider_selection()
    test_service_probe()
    test_single_probe_and_waiting_hint()
    test_skip_deep()
    test_full_flow_with_deep()
    print("\nALL ONBOARDING PHASES TESTS PASSED")
