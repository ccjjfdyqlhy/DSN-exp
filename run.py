# run.py
# 便捷别名: python run.py [--app <name>]  等价于 python main.py [--app <name>]

from __future__ import annotations

import sys

from launcher import main as launcher_main

if __name__ == "__main__":
    sys.exit(launcher_main())
