#!/usr/bin/env python3
"""apps/dsn_study/scripts/dedupe_memories.py — 去掉内容高度重复的经验记忆。

背景:
    `memory_v2` 的 exp 行是「一轮对话的摘要」。脚本化测试 / 反复追问
    会把**同一件事**记好几遍（措辞略有差异），于是：
      * 主AI 每次注入的「过往记忆」全是同一件事
        （本机就是十条几乎一样的「用户问第二问怎么用动能定理」）；
      * 模型每轮都围着那一件事转 —— 表现成「会话卡在某个话题推不下去」。

做什么:
    按字符 bigram 相似度聚类，每组只留**最早**的一条，其余删除。
    memo 行（长期备忘）与非 exp 行一律不动。

用法:
    python3 -m apps.dsn_study.scripts.dedupe_memories            # 预演
    python3 -m apps.dsn_study.scripts.dedupe_memories --apply    # 真删（先备份）
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import time

#: 相似度 ≥ 该值即视为「同一件事」
#:
#: 0.40 是量出来的：同一件事的不同措辞之间相似度 0.37~0.83，
#: 而不同事情之间最高只有 0.33（还是同一类事件的两次）—— 0.40 落在这
#: 个明显的空档里，不会误伤。
DEFAULT_THRESHOLD = 0.40


def _default_db() -> str:
    from apps.dsn_study.config import Config
    return os.path.abspath(Config.QUESTION_BANK_DB_PATH)


def _similar(a: str, b: str) -> float:
    import re
    a = re.sub(r"\s+", "", a or "")
    b = re.sub(r"\s+", "", b or "")
    if len(a) < 2 or len(b) < 2:
        return 1.0 if a and a == b else 0.0
    ga = {a[i:i + 2] for i in range(len(a) - 1)}
    gb = {b[i:i + 2] for i in range(len(b) - 1)}
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="去重 dsn_study 的经验记忆")
    ap.add_argument("--db", default=None)
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    ap.add_argument("--apply", action="store_true", help="真正删除（默认只预演）")
    ap.add_argument("--no-backup", action="store_true")
    args = ap.parse_args(argv)

    db_path = os.path.abspath(args.db or _default_db())
    if not os.path.isfile(db_path):
        print("[错误] 题库不存在: %s" % db_path)
        return 1
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT id, content FROM memory_v2 WHERE type='exp' ORDER BY id ASC"
    ).fetchall()

    groups: list[list] = []          # [[id, content], ...]
    dropped: list[tuple] = []
    for mid, content in rows:
        content = (content or "").strip()
        if not content:
            continue
        hit = None
        for g in groups:
            if _similar(content, g[0][1]) >= args.threshold:
                hit = g
                break
        if hit is None:
            groups.append([(mid, content)])
        else:
            hit.append((mid, content))
            dropped.append((mid, content))

    print("题库: %s" % db_path)
    print("exp 共 %d 条，聚成 %d 组（阈值 %.2f）\n"
          % (len(rows), len(groups), args.threshold))
    for g in groups:
        if len(g) > 1:
            print("· %d 条同一件事，保留 #%d" % (len(g), g[0][0]))
            for mid, c in g[1:]:
                print("    ✗ #%d  %s" % (mid, c[:60]))
    if not dropped:
        print("没有重复项。")
        conn.close()
        return 0

    if not args.apply:
        print("\n预演结束。加 --apply 执行实际删除。")
        conn.close()
        return 0

    if not args.no_backup:
        backup_dir = os.path.join(os.path.dirname(db_path), "backups")
        os.makedirs(backup_dir, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        backup = os.path.join(backup_dir,
                              "%s.%s.bak" % (os.path.basename(db_path), stamp))
        shutil.copy2(db_path, backup)
        print("\n已备份 → %s" % backup)

    for mid, _c in dropped:
        conn.execute("DELETE FROM memory_v2 WHERE id=?", (mid,))
    conn.commit()
    left = conn.execute(
        "SELECT count(*) FROM memory_v2 WHERE type='exp'").fetchone()[0]
    conn.close()
    print("\n删除 %d 条重复记忆，exp 剩余 %d 条。" % (len(dropped), left))
    return 0


if __name__ == "__main__":
    sys.exit(main())
