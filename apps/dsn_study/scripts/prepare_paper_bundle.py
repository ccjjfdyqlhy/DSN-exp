# apps/dsn_study/scripts/prepare_paper_bundle.py
"""把多套 gaokzx 卷子准备成一份可打印的合卷 PDF（**默认不打印**）。

用法：
    # 抓取 + 分卷 + 合成（不打印）
    python -m apps.dsn_study.scripts.prepare_paper_bundle \
        --paper 语文:161613 --paper 数学:161699 --paper 英语:161633 \
        --out .dsn/papers/朝阳高三期中

    # 复用已下载的图片，只重判分界 + 重新合成
    python -m apps.dsn_study.scripts.prepare_paper_bundle ... --skip-download

    # 真的打印（要显式加 --print；本机无自动双面，走手动长边翻转两阶段）
    python -m apps.dsn_study.scripts.prepare_paper_bundle ... --print

流程与耗时（6 科 / 83 页，2026-11-11 实测）：
    下载（并发 4）        ~35s
    题/答分界判定        ~15s   ← 原来是逐页判定，约 5~6 分钟
    拆卷 + 合成 A4 PDF   ~2s
    ─────────────────────────
    合计                  ~50s
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))


def _parse_papers(items: list) -> list:
    out = []
    for it in items or []:
        if ":" in it:
            subject, pid = it.split(":", 1)
        else:
            subject, pid = "", it
        out.append({"subject": subject.strip(), "paper_id": int(pid)})
    return out


def main(argv: list = None) -> int:
    ap = argparse.ArgumentParser(description="准备合卷 PDF（默认不打印）")
    ap.add_argument("--paper", action="append", default=[],
                    help="科目:文章id，可重复，如 语文:161613")
    ap.add_argument("--out", default="", help="输出目录")
    ap.add_argument("--title", default="合卷", help="合卷标题前缀")
    ap.add_argument("--uid", type=int, default=1)
    ap.add_argument("--skip-download", action="store_true",
                    help="跳过下载（用已下载的图片）")
    ap.add_argument("--no-vision", action="store_true",
                    help="不用视觉模型判定（位置启发式，快但不准）")
    ap.add_argument("--concurrency", type=int, default=4, help="下载并发度")
    ap.add_argument("--no-separator", action="store_true", help="不插分隔标题页")
    ap.add_argument("--print", action="store_true",
                    help="**会真的送印**（默认不打印）")
    args = ap.parse_args(argv)

    papers = _parse_papers(args.paper)
    if not papers:
        ap.error("至少要给一个 --paper 科目:文章id")

    from apps.dsn_study.skills.builtin.paper_import.tools.paper_import_tools import (
        PaperImportTool,
    )
    tool = PaperImportTool()

    t0 = time.time()
    if args.skip_download:
        print("① 跳过下载（用已有图片）", flush=True)
    else:
        print("① 下载中（并发 %d）…" % args.concurrency, flush=True)

    t1 = time.time()
    print("② 判定题/答分界 + 合成…", flush=True)
    res = tool.prepare_bundle(
        papers, out_dir=args.out, user_id=args.uid,
        use_vision=not args.no_vision, concurrency=args.concurrency,
        title_prefix=args.title, separator_pages=not args.no_separator,
        print_pdf=False, skip_download=args.skip_download)
    if not res.get("success"):
        print("失败：", res.get("error"))
        return 1
    print("   判定用时 %.1fs，统计 %s" % (
        time.time() - t1, json.dumps(res.get("stats") or {}, ensure_ascii=False)))

    print("\n分卷结果：")
    for d in res.get("details") or []:
        print("  %-4s %5d 页 → 试题 %2d / 答案 %2d  （判定方式 %s）" % (
            d["subject"], d["total"], d["question_pages"], d["answer_pages"],
            d["mode"]))
    print("\nPDF：")
    print("  试卷：%s" % res.get("question_pdf"))
    print("  答案：%s" % res.get("answer_pdf"))
    print("  总用时 %.1fs" % res.get("elapsed_sec", time.time() - t0))

    if args.print:
        print("\n送印（正面）…")
        pr = tool.print_duplex(res["question_pdf"], phase="first")
        print(json.dumps(pr, ensure_ascii=False, indent=1))
    else:
        print("\n（未打印；要打请加 --print）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
