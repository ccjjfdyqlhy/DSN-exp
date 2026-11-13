#!/usr/bin/env python3
"""核对题库里的物理题答案与官方答案表（人工核对过的卷面事实）。

用法:
    python3 -m apps.dsn_study.scripts.verify_answers
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

#: 官方答案表（人工核对卷面得出，不采信任何模型输出）
OFFICIAL = {"1": "A", "2": "C", "3": "D", "4": "C", "5": "C",
            "6": "B", "7": "C", "8": "B", "9": "A", "10": "B"}

#: 选择题题型 id（question_types 表）
CHOICE_TYPE_IDS = (10, 11)   # 10=单选, 11=多选

_NUM_PATTERNS = (
    re.compile(r'"number"\s*:\s*"?(\d+)'),
    re.compile(r"题号[^0-9]{0,8}(\d+)"),
)


def _clean_answer(raw: str) -> str:
    """答案字段存的是 JSON 字符串（'"A"'），比对前先剥掉引号。"""
    s = (raw or "").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        s = s[1:-1]
    return s.strip()


def _extract_number(meta: str, content: str) -> str:
    for pat in _NUM_PATTERNS:
        m = pat.search(meta or "")
        if m:
            return m.group(1)
    m = re.match(r"\s*(\d+)\s*[.、．]", content or "")
    return m.group(1) if m else ""


def main() -> int:
    from apps.dsn_study.config import Config

    db = Config.QUESTION_BANK_DB_PATH
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "select question_id, type_id, answer, content, metadata, source "
        "from questions where subject_id=4 order by question_id").fetchall()

    ok = bad = empty = 0
    print("总题数：%d" % len(rows))
    print("-" * 92)
    for r in rows:
        meta = r["metadata"] or ""
        try:
            meta = json.dumps(json.loads(meta), ensure_ascii=False) if meta else ""
        except Exception:
            pass
        num = _extract_number(meta, r["content"] or "")
        ans = _clean_answer(r["answer"])
        exp = OFFICIAL.get(num)
        is_choice = r["type_id"] in CHOICE_TYPE_IDS
        if not is_choice:
            verdict = "(非选择题)"
        elif exp is None:
            verdict = "(官方表无此题号)"
        elif not ans:
            verdict = "(空)"
            empty += 1
        elif ans == exp:
            verdict = "OK"
            ok += 1
        else:
            verdict = "WRONG 期望" + exp
            bad += 1
        kind = "单选" if r["type_id"] == 10 else (
            "多选" if r["type_id"] == 11 else "非选择")
        head = (r["content"] or "").replace("\n", " ")[:42]
        print("id=%-4s #%-3s %-4s 答案=%-10s %-18s %s"
              % (r["question_id"], num, kind, ans[:10], verdict, head))
    print("-" * 92)
    print("选择题答案：%d 对 / %d 错 / %d 空" % (ok, bad, empty))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
