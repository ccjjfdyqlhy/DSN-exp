#!/usr/bin/env python3
"""apps/dsn_study/scripts/purge_test_data.py — 清理题库里的合成测试数据。

用法:
    python3 -m apps.dsn_study.scripts.purge_test_data            # 预演（只报数量）
    python3 -m apps.dsn_study.scripts.purge_test_data --apply    # 真删（先自动备份）

删什么:
  * questions            —— 题库正文（全部为「1+1=?」「组卷测试题N」这类合成数据）
  * exam_sessions / exam_results —— 模考会话与成绩（答案全是 "A" 的自动测试）
  * goals / phases / daily_tasks —— 学习目标树（标题全是「测试目标」等）
  * checkins / study_sessions / study_timetable_slots / study_stats —— 打卡与课表记录
  * tasks / task_results / async_tasks —— 「测试提醒」等自动任务
  * error_logs / knowledge_point_refs —— 关联题目的从表

不删（真实使用痕迹）:
  subjects / question_types / subject_templates  学科与题型字典
  chat_rounds / memory_v2 / memory_embeds          对话与记忆
  personality_* / user_character_cards             人格档案
  vision_cameras / alarms / stopwatches           设备与配置
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import time

# 主库里的表 → 清理口径
PURGE_TABLES = [
    # 从表（对 questions 有外键）必须先删
    "knowledge_point_refs",
    "error_logs",
    # 题目与模考
    "questions",
    "exam_results",
    "exam_sessions",
    # 目标树
    "daily_tasks",
    "phases",
    "goals",
    # 打卡 / 课表
    "study_stats",
    "study_sessions",
    "study_timetable_slots",
    "checkins",
    # 任务
    "task_results",
    "tasks",
    "async_tasks",
]

# 保留的表（显式声明，便于审计）
KEEP_TABLES = [
    "subjects", "question_types", "subject_templates",
    "chat_rounds", "memory_v2", "memory_embeds",
    "personality_audit", "personality_evidence", "user_character_cards",
    "vision_cameras", "alarms", "stopwatches", "task_notifications",
    "knowledge_nodes", "knowledge_edges", "user_knowledge_state",
]


def _default_db() -> str:
    from apps.dsn_study.config import Config
    return os.path.abspath(Config.QUESTION_BANK_DB_PATH)


def _count(conn: sqlite3.Connection, table: str) -> int:
    try:
        return conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    except sqlite3.Error:
        return -1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="清理 dsn_study 题库里的合成测试数据")
    ap.add_argument("--db", default=None, help="题库路径（默认取 Config.QUESTION_BANK_DB）")
    ap.add_argument("--apply", action="store_true", help="真正执行删除（默认只预演）")
    ap.add_argument("--no-backup", action="store_true", help="跳过备份")
    args = ap.parse_args(argv)

    db_path = os.path.abspath(args.db or _default_db())
    if not os.path.isfile(db_path):
        print(f"[错误] 题库不存在: {db_path}")
        return 1

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")

    before = {t: _count(conn, t) for t in PURGE_TABLES}
    print(f"题库: {db_path}")
    print("\n待清理：")
    total = 0
    for t, n in before.items():
        if n > 0:
            print(f"  {t:24s} {n:>6d}")
            total += max(n, 0)
    print(f"  {'合计':24s} {total:>6d}")

    keep = {t: _count(conn, t) for t in KEEP_TABLES}
    print("\n保留（真实使用痕迹 / 字典表）：")
    for t, n in keep.items():
        if n > 0:
            print(f"  {t:24s} {n:>6d}")

    if not args.apply:
        print("\n预演结束。加 --apply 执行实际删除。")
        conn.close()
        return 0

    if not args.no_backup:
        backup_dir = os.path.join(os.path.dirname(db_path), "backups")
        os.makedirs(backup_dir, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        backup = os.path.join(backup_dir, f"{os.path.basename(db_path)}.{stamp}.bak")
        shutil.copy2(db_path, backup)
        print(f"\n已备份 → {backup}")

    print("\n删除中…")
    conn.execute("PRAGMA foreign_keys=OFF")
    for t in PURGE_TABLES:
        n = _count(conn, t)
        if n <= 0:
            continue
        conn.execute(f'DELETE FROM "{t}"')
        print(f"  {t:24s} - {n}")
    # 重置自增序列，让新题从 1 开始
    conn.execute("DELETE FROM sqlite_sequence")
    conn.commit()
    conn.execute("PRAGMA foreign_keys=ON")

    print("\n清理后：")
    for t in PURGE_TABLES:
        n = _count(conn, t)
        if n:
            print(f"  {t:24s} {n:>6d}  ← 仍有残留")
    print(f"  questions 剩余: {_count(conn, 'questions')}")
    conn.close()
    print("\n完成。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
