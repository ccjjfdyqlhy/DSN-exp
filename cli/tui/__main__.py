# cli/tui/__main__.py
"""Entry point: python -m cli.tui [--server URL] [--model deepseek|lmstudio] [--no-tts]"""

from __future__ import annotations

import sys
import logging

from cli.tui.app import DSNTuiApp
from cli.tui.config import ClientConfig


def main():
    config = ClientConfig.from_args()

    if config.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)

    app = DSNTuiApp(config)
    app.run()


if __name__ == "__main__":
    main()
