# Dekacode WebUI 应用入口。
from __future__ import annotations


def main() -> None:
    from apps.dekacode.__main__ import main as run
    run()
