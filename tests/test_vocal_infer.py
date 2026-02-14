
# tests/test_vocal_infer.py
# PASSED v1_260214

import os
import sys
import logging

# 将项目根目录添加到 sys.path，以便导入 vocal_infer 模块
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from vocal_infer import VocalExp, TTSRequestError

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def main():
    # API 服务地址（根据实际情况修改）
    base_url = "http://127.0.0.1:9880"

    # 参考音频路径和提示文本（需替换为实际存在的文件路径和对应文本）
    # 请确保参考音频文件存在且可访问
    REF_AUDIO_PATH = os.path.join(os.path.dirname(__file__), "ref.wav")
    PROMPT_TEXT = "Many people may feel lost at times. After all, it's impossible for everything to happen according to your own wishes."

    poem = "许多人可能会感到迷茫。毕竟，不可能事事都如自己所愿。"

    # 合成参数
    params = {
        "text": poem,
        "text_lang": "zh",
        "ref_audio_path": REF_AUDIO_PATH,
        "prompt_lang": "en",
        "prompt_text": PROMPT_TEXT,
        "media_type": "wav",
        "streaming_mode": False,          # 使用非流式模式，一次返回完整音频
        # 其他参数可按需添加
    }

    # 输出文件路径（保存到 tests 文件夹下）
    output_dir = os.path.dirname(__file__)
    output_file = os.path.join(output_dir, "synthesized_poem.wav")

    try:
        logger.info("初始化 VocalExp 客户端...")
        tts_client = VocalExp(base_url)

        logger.info("开始合成音频...")
        audio_data = tts_client.tts(**params)

        # 保存音频文件
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