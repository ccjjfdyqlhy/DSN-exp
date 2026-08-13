# apps/dsn/entry.py
# DSN 语音陪伴应用的启动入口。
#
# 调用方式:
#   python -m apps.dsn            # 终端控制台 + Flask 服务
#   python -m apps.dsn --web      # 若 main 支持（与 python apps/dsn/main.py 等价）

from __future__ import annotations

import sys


def main() -> None:
    """把 apps.dsn 作为可运行包，转发到 DSN 控制台 main。"""
    from apps.dsn import main as dsn_console
    # main.py 内部在 __main__ 时调用 main()；这里显式调用，避免重入 __main__ 分支
    dsn_console.main()


def create_app():
    """供 WSGI 使用：创建 Flask 应用。"""
    from apps.dsn.boot import create_application
    return create_application()


if __name__ == "__main__":
    main()
