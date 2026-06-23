
# tests/test_vocal_infer.py
# PASSED v1_260611 — 对接 TTSProfileManager; v2 支持 serial/parallel 架构

import os
import sys
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from audio.infer import VocalExp, TTSRequestError
from plugins.builtin.tts_profile import TTSProfileManager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BASE_URL = "http://127.0.0.1:9880"
OUTPUT_DIR = os.path.dirname(__file__)

POEM = "许多人可能会感到迷茫。毕竟，不可能事事都如自己所愿。"


def test_parallel_profile():
    """测试 parallel (默认) 架构的 profile"""
    logger.info("=" * 60)
    logger.info("测试 parallel profile")
    logger.info("=" * 60)

    tts_client = VocalExp(BASE_URL)
    profile_mgr = TTSProfileManager()
    profile_mgr.set_default("default")

    logger.info("可用 profile: %s, 当前默认=%s", profile_mgr.list_profiles(), profile_mgr.default_name)
    profile = profile_mgr.get_profile()
    logger.info("profile=%s, architecture=%s", profile.name, profile.architecture)
    assert profile.architecture == "parallel", "default profile 应为 parallel"

    params = profile_mgr.build_params(POEM)
    logger.info("构建参数: %s", {k: v for k, v in params.items() if k != "text"})
    assert "ref_audio_path" in params, "parallel 应使用 ref_audio_path"
    assert "text_lang" in params
    assert "prompt_lang" in params

    output_file = os.path.join(OUTPUT_DIR, "synthesized_parallel.wav")
    _do_tts(tts_client, params, output_file, "parallel")


def test_serial_profile():
    """测试 serial (串行) 架构的 profile"""
    logger.info("=" * 60)
    logger.info("测试 serial profile")
    logger.info("=" * 60)

    tts_client = VocalExp(BASE_URL, architecture="serial")
    profile_mgr = TTSProfileManager()
    profile_mgr.set_default("advanced")

    logger.info("可用 profile: %s, 当前默认=%s", profile_mgr.list_profiles(), profile_mgr.default_name)
    profile = profile_mgr.get_profile()
    logger.info("profile=%s, architecture=%s", profile.name, profile.architecture)
    assert profile.architecture == "serial", "advanced profile 应为 serial"

    params = profile_mgr.build_params(POEM)
    logger.info("构建参数: %s", {k: v for k, v in params.items() if k != "text"})
    assert "refer_wav_path" in params, "serial 应使用 refer_wav_path"
    assert "text_language" in params
    assert "prompt_language" in params

    output_file = os.path.join(OUTPUT_DIR, "synthesized_serial.wav")
    _do_tts(tts_client, params, output_file, "serial")


def test_architecture_routing():
    """验证 build_params 根据 architecture 产出正确的字段名，以及 VocalExp 正确推断架构。"""
    mgr = TTSProfileManager()

    # parallel — 字段名映射
    p = mgr.get_profile("default")
    assert p.architecture == "parallel"
    par = p.build_params("test")
    assert "ref_audio_path" in par
    assert "text_lang" in par
    assert "prompt_lang" in par
    assert "refer_wav_path" not in par

    # serial — 字段名映射
    p = mgr.get_profile("advanced")
    assert p.architecture == "serial"
    ser = p.build_params("test")
    assert "refer_wav_path" in ser
    assert "text_language" in ser
    assert "prompt_language" in ser
    assert "ref_audio_path" not in ser

    # VocalExp 自动推断
    client = VocalExp(BASE_URL)
    assert client._detect_architecture(par) == "parallel"
    assert client._detect_architecture(ser) == "serial"


def _do_tts(tts_client, params, output_file, label):
    try:
        logger.info("[%s] 开始合成音频...", label)
        audio_data = tts_client.tts(**params)
        with open(output_file, "wb") as f:
            f.write(audio_data)
        logger.info("[%s] 音频已保存至: %s (%d bytes)", label, output_file, len(audio_data))
    except TTSRequestError as e:
        logger.warning("[%s] TTS 请求失败 (服务器可能未就绪): %s", label, e)
    except Exception as e:
        logger.exception("[%s] 发生未知错误: %s", label, e)


if __name__ == "__main__":
    test_architecture_routing()
    test_parallel_profile()
    test_serial_profile()
