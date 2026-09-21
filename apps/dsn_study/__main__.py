# apps/dsn_study/__main__.py
# 终端交互入口: python -m apps.dsn_study

from __future__ import annotations

import os
import sys

def main() -> None:
    from .app import DsnStudyAgent  # type: ignore[import-not-found]
    agent = DsnStudyAgent()
    agent.enable_persistence(db_path=os.environ.get("DSN_STUDY_DB", ":memory:"))

    print("==================================================")
    print("  DSN 学习特化助手 (dsn_study) 已启动 [基于 Harness]")
    print("  支持题库检索、模考组卷、知识点梳理与答疑")
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
            reply = agent.chat(line)
            print(f"\n{reply}")
        except Exception as e:
            print(f"\n[错误] 执行失败: {e}")


if __name__ == "__main__":
    main()
