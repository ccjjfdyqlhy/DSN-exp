#!/usr/bin/env python3
"""把 pytest 的结果摘要变成一个 shields.io endpoint badge 的 JSON。

为什么需要它：
README 顶部的 CI badge 只说明「绿了没绿」，看不出这套东西到底有多大。
而「1288 passed」这种具体数字，是外部读者判断「这是不是一个认真维护的项目」
的最直接信号 —— 比任何形容词都管用。

用法：
    python -m pytest -q tests/ > pytest.log 2>&1 || true
    python scripts/write_tests_badge.py pytest.log --out docs/site/tests.json

不给 --out 时打到 stdout（方便管道）。

输出是 shields.io 的 endpoint 契约（schemaVersion 1）：
    {"schemaVersion": 1, "label": "tests", "message": "1288 passed", "color": "brightgreen"}

解析不出来的时候**不猜**：message 写成 "unknown"、颜色写成 lightgrey。
一个说不清的 badge 比没有 badge 诚实。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

#: pytest 结尾那行摘要，形如：
#: "7 failed, 1288 passed, 3 skipped, 59 deselected, 15 warnings in 81.06s"
_SUMMARY = re.compile(
    r"(?P<body>(?:\d+\s+\w+,?\s*)+)"
    r"(?:\s+in\s+\d+(?:\.\d+)?s)?\s*$"
)

_COUNT = re.compile(r"(\d+)\s+(passed|failed|error|errors|skipped|xfailed|xpassed|deselected|warnings?)")


def parse_summary(text: str) -> dict[str, int]:
    """从 pytest 输出里抠出各状态的计数。"""
    counts: dict[str, int] = {}
    # 只看最后 40 行：摘要行在最后，前面的进度字符没有意义
    for line in text.splitlines()[-40:]:
        if "passed" not in line and "failed" not in line and "error" not in line:
            continue
        if "=" in line and "passed" not in line:
            continue
        found = _COUNT.findall(line)
        if not found:
            continue
        # 取「最后一个摘要行」—— 同一个文件可能有多段输出
        for number, word in found:
            key = "error" if word.startswith("error") else word
            counts[key] = int(number)
        if "passed" in counts or "failed" in counts:
            break
    return counts


def build_badge(counts: dict[str, int]) -> dict[str, str]:
    passed = counts.get("passed", 0)
    failed = counts.get("failed", 0) + counts.get("error", 0)
    if not counts:
        return {"schemaVersion": 1, "label": "tests",
                "message": "unknown", "color": "lightgrey"}
    if failed:
        return {"schemaVersion": 1, "label": "tests",
                "message": f"{failed} failed", "color": "red"}
    if passed == 0:
        return {"schemaVersion": 1, "label": "tests",
                "message": "unknown", "color": "lightgrey"}
    return {"schemaVersion": 1, "label": "tests",
            "message": f"{passed} passed", "color": "brightgreen"}


def main(argv: list[str]) -> int:
    args = argv[1:]
    out: Path | None = None
    if "--out" in args:
        i = args.index("--out")
        if i + 1 >= len(args):
            print("--out 后面要跟文件名", file=sys.stderr)
            return 2
        out = Path(args[i + 1])
        args = args[:i] + args[i + 2:]
    if not args:
        print("用法: write_tests_badge.py <pytest 输出文件> [--out <json 文件>]",
              file=sys.stderr)
        return 2
    path = Path(args[0])
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"读不到 {path}: {exc}", file=sys.stderr)
        text = ""
    badge = build_badge(parse_summary(text))
    payload = json.dumps(badge, ensure_ascii=False)
    if out is None:
        print(payload)
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
