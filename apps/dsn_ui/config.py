# apps/dsn_ui/config.py
"""DSN-UI 独立应用配置。"""

from __future__ import annotations

import os
from pathlib import Path


class UIConfig:
    HOST: str = os.getenv("DSN_UI_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("DSN_UI_PORT", "8888"))
    DEFAULT_SLOTS: int = int(os.getenv("DSN_UI_DEFAULT_SLOTS", "2"))
    PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent
