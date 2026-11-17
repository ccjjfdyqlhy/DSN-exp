# tests/test_vlc.py
# 验证 vlc 能播放 TTS 产物（原来是一个模块级就开播放器的脚本）。
#
# 之前这个文件在 **import 阶段** 就创建播放器并读一个写死在本机的绝对路径：
#   - 别的机器上必然 FileNotFoundError；
#   - pytest 收集它时就会执行这段代码 → 收集期报错。
#
# 现在：模块导入期什么都不做；音频路径从环境变量取，默认用仓库内的样例；
#       缺 vlc 或缺音频就跳过。

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("vlc", reason="未安装 python-vlc（可选依赖）")

DEFAULT_CLIP = Path(__file__).resolve().parent / "synthesized_serial.wav"
CLIP = Path(os.environ.get("AICF_VLC_TEST_CLIP", str(DEFAULT_CLIP)))


def _duration_ms(clip: Path) -> int:
    import vlc

    player = vlc.MediaPlayer(str(clip))
    media = player.get_media()
    media.parse()
    duration_ms = player.get_duration()
    player.release()
    return int(duration_ms)


def test_vlc_can_read_the_clip_duration():
    """vlc 能解析音频时长（>0 说明真的解出来了）。"""
    if not CLIP.is_file():
        pytest.skip(f"样例音频不存在: {CLIP}（可用 AICF_VLC_TEST_CLIP 指定）")
    assert _duration_ms(CLIP) > 0


if __name__ == "__main__":  # 手动跑：python tests/test_vlc.py
    print("clip:", CLIP, "exists:", CLIP.is_file())
    if CLIP.is_file():
        print("duration_ms:", _duration_ms(CLIP))
