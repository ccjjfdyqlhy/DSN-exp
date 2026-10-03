# apps/dsn_study/entry.py
# dsn_study 应用入口 — 供 launcher（python main.py --app dsn_study）与 WSGI 使用。

from __future__ import annotations


def main() -> None:
    """launcher 调用入口：装配并启动 Web 服务（阻塞）。"""
    from .__main__ import main as run_cli
    run_cli(web=True)


def create_app():
    """WSGI / Web 模式入口：返回装配完成的 Flask app。"""
    from .boot import create_application
    return create_application()


if __name__ == "__main__":
    main()
