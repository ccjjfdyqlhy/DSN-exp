#!/usr/bin/env python3
"""清掉「整卷入库」产生的题目，便于用另一套 OCR 重新入库做对照。

背景：入库去重靠**题干文本前缀匹配**（见 paper_import._dedupe_key）。
换 OCR 引擎后同一道题的措辞会变（标点/空格/LaTeX 记号差异），前缀匹配
就判不中，于是同一道题会以两种表述各存一份。切换 OCR 引擎做对照实验时，
需要先把旧的那批清掉，否则「新增题数」会被重复题污染。

只删 source='paper_import' 的题，不动其它来源（manual / quick_scan 等）。

用法:
    python3 -m apps.dsn_study.scripts.reset_paper_import            # 预演
    python3 -m apps.dsn_study.scripts.reset_paper_import --apply    # 真删
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

SOURCE = "paper_import"


def _backup(db_path: str) -> str:
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak_dir = os.path.join(os.path.dirname(os.path.abspath(db_path)), "backups")
    os.makedirs(bak_dir, exist_ok=True)
    dst = os.path.join(bak_dir,
                       "%s.%s.bak" % (os.path.basename(db_path), ts))
    shutil.copy2(db_path, dst)
    return dst


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="真正删除（默认只预演）")
    args = ap.parse_args(argv)

    from apps.dsn_study.config import Config

    db_path = Config.QUESTION_BANK_DB_PATH
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "select question_id, subject_id from questions where source = ?",
        (SOURCE,)).fetchall()
    by_subject: dict[int, int] = {}
    for _qid, sid in rows:
        by_subject[sid] = by_subject.get(sid, 0) + 1

    print("数据库：%s" % db_path)
    print("待删除 %s 来源题目 %d 道：" % (SOURCE, len(rows)))
    for sid, n in sorted(by_subject.items()):
        print("  subject_id=%d : %d 道" % (sid, n))

    if not args.apply:
        print("\n（预演模式，未删除。确认后加 --apply）")
        conn.close()
        return 0

    bak = _backup(db_path)
    print("\n已备份 → %s" % bak)
    conn.execute("delete from questions where source = ?", (SOURCE,))
    conn.commit()
    left = conn.execute(
        "select count(*) from questions where source = ?", (SOURCE,)).fetchone()[0]
    total = conn.execute("select count(*) from questions").fetchone()[0]
    conn.close()
    print("删除完成：剩余 %s 来源 %d 道，题库共 %d 道" % (SOURCE, left, total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
