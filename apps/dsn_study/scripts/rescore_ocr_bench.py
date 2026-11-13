#!/usr/bin/env python3
"""基于已存 OCR 结果重算评测（不重新调用模型）。

用法:
    python3 -m apps.dsn_study.scripts.rescore_ocr_bench [--in ...] [--out ...]

把 bench.json 里的 text 重新过一遍修正后的参照标准，避免为了改评分标准
再烧一遍 GPU 和 API。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

from apps.dsn_study.scripts.ocr_bench import score_page, similarity  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="/tmp/ocr_bench/bench.json")
    ap.add_argument("--out", default="/tmp/ocr_bench/bench_rescored.json")
    args = ap.parse_args(argv)

    with open(args.inp, encoding="utf-8") as fh:
        r = json.load(fh)

    out = {"local": {}, "remote": {}, "meta": r.get("meta", {})}
    for side in ("local", "remote"):
        for name, v in r.get(side, {}).items():
            if "text" not in v:
                out[side][name] = v
                continue
            s = score_page(name, v["text"])
            out[side][name] = {**v, **s}

    for name in out["local"]:
        lt = out["local"][name].get("text")
        rt = out["remote"].get(name, {}).get("text")
        if lt and rt:
            sim = round(similarity(lt, rt), 3)
            out["local"][name]["similarity"] = sim
            out["remote"][name]["similarity"] = sim

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)

    # ── 汇总 ──
    print(f"{'指标':<20}{'bonsai(本地)':>16}{'deepseek(在线)':>18}")
    print("-" * 56)

    def agg(side, key):
        ok = tot = 0
        for v in out[side].values():
            if v.get(key) is not None:
                tot += 1
                ok += 1 if v[key] else 0
        return ok, tot

    for label, key in (("答案页判定", "page_kind_ok"),
                       ("题号全覆盖", "numbers_ok"),
                       ("公式保真", "formula_ok"),
                       ("页脚页码", "footer_ok")):
        lo, lt = agg("local", key)
        ro, rt = agg("remote", key)
        print(f"{label:<20}{f'{lo}/{lt}':>16}{f'{ro}/{rt}':>18}")

    lsec = sum(v.get("sec", 0) for v in out["local"].values())
    rsec = sum(v.get("sec", 0) for v in out["remote"].values())
    n = max(len(out["local"]), 1)
    print("-" * 56)
    print(f"{'总耗时(s)':<20}{lsec:>16.1f}{rsec:>18.1f}")
    print(f"{'平均单页(s)':<20}{lsec/n:>16.1f}{rsec/n:>18.1f}")
    lch = sum(v.get("chars", 0) for v in out["local"].values())
    rch = sum(v.get("chars", 0) for v in out["remote"].values())
    print(f"{'总字符':<20}{lch:>16d}{rch:>18d}")
    sims = [v["similarity"] for v in out["local"].values()
            if v.get("similarity") is not None]
    if sims:
        print(f"{'两者相似度(均值)':<20}{sum(sims)/len(sims):>16.3f}")
    print(f"\n→ {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
