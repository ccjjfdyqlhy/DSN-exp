#!/usr/bin/env python3
"""对比「本地 Bonsai OCR」与「在线 OCR」的缓存文本，抽样核对关键事实。

参照标准必须人工核对过卷面，不能凭模型输出自说自话。本脚本只做
**机械比对**（页脚页码、答案标记、选项分行数、字符量），事实核对由人做。

用法:
    python3 -m apps.dsn_study.scripts.compare_ocr_cache \
        --local .dsn/workspace/ocr --online /tmp/ocr_online_backup
"""
from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

# 页脚「第 N 页/共 M 页」
_FOOTER = re.compile(r"第\s*(\d+)\s*页\s*[/／]?\s*共\s*(\d+)\s*页")
# 选项独立成行：A. xxx / B．xxx
_OPTION_LINE = re.compile(r"^\s*[\(（]?([A-D])[\)）\.．、]\s*\S", re.M)


def analyze(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        md = fh.read()
    footers = [int(m.group(1)) for m in _FOOTER.finditer(md)]
    return {
        "chars": len(md),
        "answer_mark": "<!-- ANSWER -->" in md,
        "footer_pages": footers,
        "option_lines": len(set(_OPTION_LINE.findall(md))),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", default=".dsn/workspace/ocr")
    ap.add_argument("--online", default="/tmp/ocr_online_backup")
    args = ap.parse_args(argv)

    names = sorted(f for f in os.listdir(args.local) if f.endswith(".md"))
    print(f"{'页面':<20} {'字符(本/在)':>14} {'答案标记(本/在)':>16} "
          f"{'页脚(本)':>12} {'页脚(在)':>12} {'选项行(本/在)':>14}")
    print("-" * 96)

    tot_local = tot_online = 0
    for name in names:
        lp = os.path.join(args.local, name)
        op = os.path.join(args.online, name)
        if not os.path.isfile(op):
            print(f"{name:<20} {'(在线缓存缺失)':>14}")
            continue
        a, b = analyze(lp), analyze(op)
        tot_local += a["chars"]
        tot_online += b["chars"]
        mark = lambda v: "是" if v else "否"
        print(f"{name:<20} {a['chars']:>6}/{b['chars']:<7} "
              f"{mark(a['answer_mark']):>7}/{mark(b['answer_mark']):<8} "
              f"{str(a['footer_pages'] or '-'):>12} "
              f"{str(b['footer_pages'] or '-'):>12} "
              f"{a['option_lines']:>6}/{b['option_lines']:<7}")
    print("-" * 96)
    print(f"合计字符：本地 {tot_local} / 在线 {tot_online}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
