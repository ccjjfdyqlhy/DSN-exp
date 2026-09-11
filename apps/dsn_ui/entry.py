# apps/dsn_ui/entry.py
"""DSN-UI 启动入口，对接 launcher.py。"""

from __future__ import annotations

import sys


def main() -> None:
    from apps.dsn_ui.server import main as run_server
    run_server()


if __name__ == "__main__":
    main()
