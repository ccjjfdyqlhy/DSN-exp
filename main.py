# main.py
# DSN-exp 入口 — Harness 应用启动器。
#
# 项目根目录由 harness 框架代码占领。启动时默认运行 DSN 语音陪伴应用，
# 可通过以下方式切换为其他基于本 harness 构建的应用:
#
#   python main.py                       # 默认 → DSN 语音陪伴应用
#   python main.py --app coding_agent    # 启动参数
#   DSN_APP=coding_agent python main.py  # 环境变量
#   python main.py --list                # 列出可用应用
#
# 亦可用 apps.yaml 在根目录声明应用 → 入口映射（可选）。

from __future__ import annotations

import sys

from launcher import main as launcher_main

if __name__ == "__main__":
    sys.exit(launcher_main())
