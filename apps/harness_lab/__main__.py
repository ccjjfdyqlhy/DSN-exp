# apps/harness_lab/__main__.py
"""CLI 入口：python -m apps.harness_lab"""

from __future__ import annotations

import argparse
import logging
import sys

from .config import LabConfig
from .report import build_summary, write_reports
from .runner import run_all
from .scenarios import DIRECTIONS, SCENARIOS


def _print_scenarios() -> None:
    print("预设人格演化方向：\n")
    for d in DIRECTIONS:
        print(f"  [{d['id']}] {d['title']}")
        print(f"      意图：{d['intent']}")
        print(f"      机制：{d['mechanism']}")
    print("\n场景：\n")
    for s in SCENARIOS:
        print(f"  {s.id:<24} {s.title}   [kind={s.kind}, 检查项={len(s.checks)}]")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m apps.harness_lab",
        description="harness 记忆与人格系统的专用验证台")
    parser.add_argument("--list", action="store_true", help="列出预设人格演化方向与场景")
    parser.add_argument("--scenario", action="append", default=[],
                        help="只跑指定场景（可重复）")
    parser.add_argument("--llm", choices=["scripted", "live"], default="scripted",
                        help="scripted=确定性桩（默认，无需凭据）；live=真实模型")
    parser.add_argument("--no-truncate", action="store_true",
                        help="对照组：让桩**不**遵守 max_tokens")
    parser.add_argument("--out", default=None, help="输出目录")
    parser.add_argument("--uid", type=int, default=1, help="验证用的用户 id")
    parser.add_argument("--clean", action="store_true", help="跑完删掉场景工作区")
    parser.add_argument("--verbose", "-v", action="store_true", help="打开调试日志")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    # 这几个库很吵，验证台只需要结果
    for noisy in ("harness.personality", "harness.personality.personality_generator",
                  "harness.personality.distillation_engine",
                  "harness.personality.personality_judge",
                  "harness.personality.evidence_accumulator"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if args.list:
        _print_scenarios()
        return 0

    cfg = LabConfig.from_args(args)
    print(f"▶ 验证台启动：{cfg.describe()}\n")

    results = run_all(cfg)
    summary = build_summary(results)

    md_path, json_path = write_reports(results, cfg.describe(), cfg.output_dir)

    print("\n" + "=" * 68)
    for r in results:
        p = sum(1 for c in r.checks if c.passed)
        t = len(r.checks)
        mark = "✅" if (t and p == t) else ("💥" if not r.ok else "❌")
        print(f"{mark} {r.scenario_id:<24} {p}/{t}  {r.title}")
        if not r.ok:
            print(f"     执行异常: {r.error}")
        for c in r.checks:
            if not c.passed:
                print(f"     ❌ {c.id}: {c.detail}")
    print("=" * 68)
    print(f"总计 {summary['passed']}/{summary['total']} 通过，{summary['failed']} 失败")
    print(f"报告: {md_path}")
    print(f"      {json_path}")
    return 0 if summary["failed"] == 0 and not summary["scenario_errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
