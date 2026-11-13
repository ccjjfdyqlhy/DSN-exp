# apps/harness_lab/report.py
"""验证报告输出（Markdown + JSON）。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .runner import ScenarioResult


def build_summary(results: list[ScenarioResult]) -> dict:
    total = 0
    passed = 0
    failed = 0
    by_domain: dict[str, dict] = {}
    for r in results:
        for c in r.checks:
            total += 1
            if c.passed:
                passed += 1
            else:
                failed += 1
            d = by_domain.setdefault(c.domain, {"total": 0, "passed": 0, "failed": 0})
            d["total"] += 1
            d["passed" if c.passed else "failed"] += 1
    return {
        "total": total, "passed": passed, "failed": failed,
        "scenarios": len(results),
        "scenario_errors": [r.scenario_id for r in results if not r.ok],
        "by_domain": by_domain,
    }


def _fmt_evidence(ev: dict) -> str:
    if not ev:
        return ""
    try:
        text = json.dumps(ev, ensure_ascii=False, indent=2, default=str)
    except Exception:
        text = str(ev)
    if len(text) > 2400:
        text = text[:2400] + "\n…（已截断）"
    return text


def render_markdown(results: list[ScenarioResult], meta: dict) -> str:
    summary = build_summary(results)
    lines: list[str] = []
    A = lines.append

    A("# harness 记忆与人格系统 · 验证报告")
    A("")
    A(f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    for k, v in meta.items():
        A(f"- {k}：`{v}`")
    A("")
    A("## 总览")
    A("")
    A(f"**{summary['passed']}/{summary['total']} 项通过**，{summary['failed']} 项失败"
      f"（{summary['scenarios']} 个场景）。")
    A("")
    A("| 域 | 通过 | 失败 |")
    A("|---|---|---|")
    for dom, d in sorted(summary["by_domain"].items()):
        A(f"| {dom} | {d['passed']} | {d['failed']} |")
    A("")

    A("## 场景结果")
    A("")
    A("| 场景 | 方向 | 结果 | 通过/总数 | 耗时 |")
    A("|---|---|---|---|---|")
    for r in results:
        p = sum(1 for c in r.checks if c.passed)
        t = len(r.checks)
        state = "✅ 全过" if (t and p == t) else ("❌ 有失败" if t else "⚠️ 无检查项")
        if not r.ok:
            state = "💥 执行异常"
        A(f"| `{r.scenario_id}` | {r.direction} | {state} | {p}/{t} | {r.duration_ms:.0f}ms |")
    A("")

    failed = [(r, c) for r in results for c in r.checks if not c.passed]
    A("## 失败项（这些是「实际行为」与「应有行为」的差异）")
    A("")
    if not failed:
        A("无。所有检查项都通过了。")
        A("")
    for r, c in failed:
        A(f"### ❌ `{c.id}` — {c.desc}")
        A("")
        A(f"- 场景：`{r.scenario_id}`（{r.title}）")
        A(f"- 判定：{c.detail or '（无详情）'}")
        ev = _fmt_evidence(c.evidence)
        if ev:
            A("- 证据：")
            A("")
            A("```json")
            A(ev)
            A("```")
            A("")

    A("## 全部检查项")
    A("")
    for r in results:
        if not r.checks:
            continue
        A(f"### `{r.scenario_id}` — {r.title}")
        A("")
        A("| 检查项 | 域 | 结果 | 说明 |")
        A("|---|---|---|---|")
        for c in r.checks:
            A(f"| `{c.id}` | {c.domain} | {'✅' if c.passed else '❌'} | "
              f"{(c.detail or '').replace('|', '/')} |")
        A("")
    return "\n".join(lines)


def write_reports(results: list[ScenarioResult], meta: dict, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / "report.md"
    json_path = output_dir / "report.json"
    summary = build_summary(results)
    payload = {
        "meta": meta,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": summary,
        "scenarios": [r.to_dict() for r in results],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                         encoding="utf-8")
    md_path.write_text(render_markdown(results, meta), encoding="utf-8")
    return md_path, json_path
