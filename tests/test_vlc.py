# tests/test_vlc.py
# check that vlc can read the duration of a TTS clip.
#
# this used to open a player at import time against a hardcoded local path.
# it now does nothing at import, takes the clip from an environment variable
# with a repo sample as the default, and skips when vlc or the clip is missing.

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("vlc", reason="python-vlc is not installed")

DEFAULT_CLIP = Path(__file__).resolve().parent / "synthesized_serial.wav"
CLIP = Path(os.environ.get("AICF_VLC_TEST_CLIP", str(DEFAULT_CLIP)))


def _duration_ms(clip: Path) -> int:
    import vlc

    player = vlc.MediaPlayer(str(clip))
    media = player.get_media()
    media.parse()
    duration_ms = media.get_duration()
    player.release()
    return int(duration_ms or 0)


def test_vlc_can_read_the_clip_duration():
    """vlc returns a positive duration for the clip."""
    if not CLIP.is_file():
        pytest.skip(f"sample clip missing: {CLIP} (set AICF_VLC_TEST_CLIP to override)")
    assert _duration_ms(CLIP) > 0


if __name__ == "__main__":
    print("clip:", CLIP, "exists:", CLIP.is_file())
    if CLIP.is_file():
        print("duration_ms:", _duration_ms(CLIP))
