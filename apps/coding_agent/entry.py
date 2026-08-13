# apps/coding_agent/entry.py
# CodingAgent 启动入口。

from __future__ import annotations


def main() -> None:
    from apps.coding_agent.__main__ import main as run
    run()
