#!/usr/bin/env python3
"""apps/dsn_study/scripts/backfill_topic_summaries.py — 回填话题摘要。

背景:
    旧版 `TopicManager.close_topic` 在关话题时写死
    `summary="与【X】相关的过往探讨"` —— 这句话**不含任何事实**，却被
    `assemble_topic_context` 当作 `[话题回顾 · X]` 注入 system prompt。
    结果就是主AI 每次对话都带着一条固定不变的假记忆
    （本机就是「找一套最新的高三物理期中卷子做」那条）。

做什么:
    把**占位摘要**（以及空摘要）按该话题自己的原文重新生成 ——
    取第一条用户发言 + 最后一条助手发言。不删任何对话记录，
    只是把没用的占位串换成真正有信息量的摘要。

用法:
    python3 -m apps.dsn_study.scripts.backfill_topic_summaries            # 预演
    python3 -m apps.dsn_study.scripts.backfill_topic_summaries --apply    # 真改（先备份）
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import time


def _default_db() -> str:
    from apps.dsn_study.config import Config
    base = os.path.abspath(Config.QUESTION_BANK_DB_PATH)
    return os.path.join(os.path.dirname(base), "topics.db")


def _placeholder_re():
    from apps.dsn_study.memory.topics import PLACEHOLDER_SUMMARY_RE
    return PLACEHOLDER_SUMMARY_RE


def _content_summary(msgs: list[dict]) -> str:
    from apps.dsn_study.memory.topics import TopicManager
    return TopicManager._content_summary(msgs)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="回填 dsn_study 话题库里的占位摘要")
    ap.add_argument("--db", default=None, help="topics.db 路径（默认从配置推导）")
    ap.add_argument("--apply", action="store_true", help="真正写回（默认只预演）")
    ap.add_argument("--no-backup", action="store_true", help="跳过备份")
    args = ap.parse_args(argv)

    db_path = os.path.abspath(args.db or _default_db())
    if not os.path.isfile(db_path):
        print("[错误] 话题库不存在: %s" % db_path)
        return 1

    conn = sqlite3.connect(db_path)
    ph = _placeholder_re()
    rows = conn.execute(
        "SELECT topic_id, title, summary FROM study_topics ORDER BY last_active_at DESC"
    ).fetchall()

    todo = []
    for topic_id, title, summary in rows:
        summary = (summary or "").strip()
        if summary and not ph.match(summary):
            continue
        msgs = [
            {"role": r[0], "content": r[1]}
            for r in conn.execute(
                "SELECT role, content FROM study_topic_messages "
                "WHERE topic_id = ? ORDER BY id", (topic_id,)
            ).fetchall()
        ]
        new_summary = _content_summary(msgs)
        todo.append((topic_id, title, summary, new_summary, len(msgs)))

    print("话题库: %s" % db_path)
    print("共 %d 个话题，其中 %d 个摘要是占位/空\n" % (len(rows), len(todo)))
    for topic_id, title, old, new, n in todo:
        print("· [%s] %s（%d 条消息）" % (topic_id[:16], title, n))
        print("    旧: %s" % (old or "(空)"))
        print("    新: %s" % (new[:160] or "(无法生成)"))
    if not todo:
        print("无需回填。")
        conn.close()
        return 0

    if not args.apply:
        print("\n预演结束。加 --apply 执行实际写回。")
        conn.close()
        return 0

    if not args.no_backup:
        backup_dir = os.path.join(os.path.dirname(db_path), "backups")
        os.makedirs(backup_dir, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        backup = os.path.join(backup_dir, "%s.%s.bak" % (os.path.basename(db_path), stamp))
        shutil.copy2(db_path, backup)
        print("\n已备份 → %s" % backup)

    changed = 0
    for topic_id, title, old, new, n in todo:
        if not new:
            continue
        conn.execute("UPDATE study_topics SET summary = ? WHERE topic_id = ?",
                     (new[:2000], topic_id))
        changed += 1
    conn.commit()
    print("\n已回填 %d 个话题摘要。" % changed)
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
