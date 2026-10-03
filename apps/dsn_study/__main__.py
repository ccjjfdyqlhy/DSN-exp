# apps/dsn_study/__main__.py
# 终端交互入口: python -m apps.dsn_study [--web]
#
# 默认进入终端 REPL（经 boot 装配的完整引擎：技能工具 + 学习上下文注入）；
# --web 时启动 Flask 服务（scan/plan/study_timetable/chat 等 API）。

from __future__ import annotations

import os
import sys


def main(web: bool = False) -> None:
    from .boot import create_application, get_engine

    flask_app = create_application()
    engine = get_engine()

    if web or "--web" in sys.argv:
        from apps.dsn_study.config import Config
        print(f"dsn_study Web 服务启动: http://{Config.SERVER_HOST}:{Config.SERVER_PORT}")
        flask_app.run(host=Config.SERVER_HOST, port=Config.SERVER_PORT,
                      debug=False, use_reloader=False)
        return

    persist_path = os.environ.get("DSN_STUDY_DB")
    if persist_path and persist_path != ":memory:":
        try:
            from harness.store import SessionStore
            SessionStore(db_path=persist_path).create_session()
        except Exception as e:  # 会话持久化失败不阻塞 REPL
            print(f"[警告] 会话持久化不可用: {e}")

    print("==================================================")
    print("  DSN 学习特化助手 (dsn_study) 已启动 [基于 Harness]")
    print(f"  已加载技能: {len(engine.skill_registry.list_active_tools())} 个工具")
    print("  支持题库检索、模考组卷、错题归纳、知识图谱与学习计划")
    print("  输入问题直接对话，输入 exit 或 quit 退出")
    print("==================================================")

    while True:
        try:
            line = input("\n[Study]> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break
        if not line:
            continue
        if line.lower() in ("exit", "quit"):
            print("再见！")
            break
        try:
            reply = engine.chat(line)
            print(f"\n{reply}")
        except Exception as e:
            print(f"\n[错误] 执行失败: {e}")


if __name__ == "__main__":
    main()
