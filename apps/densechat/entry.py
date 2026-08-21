# DenseChat WebUI 应用入口。
from __future__ import annotations


def main() -> None:
    from apps.densechat.__main__ import main as run
    run()
