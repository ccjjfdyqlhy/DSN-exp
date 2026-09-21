# apps/dsn_study/entry.py
# DSN 学习特化应用（dsn_study）启动入口

from __future__ import annotations


def main() -> None:
    """把 apps.dsn_study 作为可运行包，转发到控制台 main。"""
    from .__main__ import main as run_cli
    run_cli()


def create_app():
    """供 WSGI / Web 模式调用。"""
    from .app import DsnStudyAgent  # type: ignore[import-not-found]
    return DsnStudyAgent()


if __name__ == "__main__":
    main()
