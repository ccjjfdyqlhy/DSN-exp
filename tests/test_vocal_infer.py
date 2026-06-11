
# tests/test_vocal_infer.py
# PASSED v1_260611 — 对接 TTSProfileManager

import os
import sys
import logging

# 将项目根目录添加到 sys.path，以便导入 vocal_infer 模块
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from vocal_infer import VocalExp, TTSRequestError
from plugins.builtin.tts_profile import TTSProfileManager

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def main():
    base_url = "http://127.0.0.1:9880"

    poem = "许多人可能会感到迷茫。毕竟，不可能事事都如自己所愿。"

    output_dir = os.path.dirname(__file__)
    output_file = os.path.join(output_dir, "synthesized_poem.wav")

    try:
        logger.info("初始化 VocalExp 客户端...")
        tts_client = VocalExp(base_url)

        logger.info("加载 TTS Profile 管理器...")
        profile_mgr = TTSProfileManager()
        logger.info("可用 profile: %s, 默认=%s", profile_mgr.list_profiles(), profile_mgr.default_name)

        params = profile_mgr.build_params(poem)
        logger.info("使用 profile=%s 构建参数: text_lang=%s prompt_lang=%s ref=%s prompt_text=%s...",
                     profile_mgr.default_name,
                     params["text_lang"], params["prompt_lang"],
                     os.path.basename(params["ref_audio_path"]),
                     params["prompt_text"][:60])

        logger.info("开始合成音频...")
        audio_data = tts_client.tts(**params)

        with open(output_file, "wb") as f:
            f.write(audio_data)

        logger.info(f"音频已保存至: {output_file}")

    except TTSRequestError as e:
        logger.error(f"TTS 请求失败: {e}")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"发生未知错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
