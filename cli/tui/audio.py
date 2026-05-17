# cli/tui/audio.py
"""TTS audio playback via pygame mixer."""

from __future__ import annotations

import base64
import tempfile
import threading
import logging

logger = logging.getLogger("tui.audio")

_pygame_init = False
_lock = threading.Lock()


def _ensure_init():
    global _pygame_init
    if _pygame_init:
        return
    with _lock:
        if _pygame_init:
            return
        import pygame
        pygame.mixer.init(frequency=22050, size=-16, channels=1)
        _pygame_init = True
        logger.info("pygame mixer initialized")


def play_wav_base64(b64_data: str | None) -> None:
    """Play base64-encoded WAV audio in a background thread. Non-blocking."""
    if not b64_data:
        return
    try:
        raw = base64.b64decode(b64_data)
    except Exception as e:
        logger.error("Failed to decode audio: %s", e)
        return

    def _play():
        try:
            _ensure_init()
            import pygame
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(raw)
                tmp_path = f.name
            try:
                sound = pygame.mixer.Sound(tmp_path)
                sound.play()
                # Wait for playback in this thread (non-blocking to main)
                import time
                length = sound.get_length()
                time.sleep(length + 0.2)
            finally:
                try:
                    import os
                    os.unlink(tmp_path)
                except OSError:
                    pass
        except Exception as e:
            logger.error("Audio playback error: %s", e)

    t = threading.Thread(target=_play, daemon=True)
    t.start()


def stop_audio():
    """Stop currently playing audio."""
    if not _pygame_init:
        return
    try:
        import pygame
        pygame.mixer.stop()
    except Exception:
        pass
