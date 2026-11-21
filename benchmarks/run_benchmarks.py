#!/usr/bin/env python3
# benchmarks/run_benchmarks.py —— 可复现的数字（roadmap 段 8）。
#
# 「README 上的每个数字都能被一条命令复现」—— 这条命令就是本脚本：
#
#   python benchmarks/run_benchmarks.py            # 全部四项
#   python benchmarks/run_benchmarks.py --json     # 机器可读
#
# 四项数字，各自的口径（口径比数字重要，先读这个再看值）：
#
#   tool_call_latency_us        守卫链路单次往返（策略求值 + 审批跳过 + 执行 + 审计）
#                               的耗时，纯工具、本地无网络。N=300，报 p50/p95。
#                               这衡量的就是「安全不是免费的」那笔税到底多少。
#   journal_recovery_ms         journal 重放恢复（checkpoint 损坏路径）耗时。
#                               先写 N=200 个事件 + checkpoint，再丢 checkpoint
#                               只靠 journal 重放，报耗时与事件数。
#   memory_compaction_ratio     分层记忆 L1 摘要压缩比：进入 L1 的字符量 /
#                               压缩后的字符量（确定性 compactor，可复现）。
#                               >1 才有意义 —— 压缩比小于 1 等于白做。
#   fault_suite                 崩溃恢复证据：直接跑 tests/fault/ 故障注入层，
#                               报通过率与耗时。崩溃恢复「成功率」不是基准出来的，
#                               是这一层测出来的 —— 基准引用它，不伪造它。
#
# 显存占用（roadmap 里提的第四个数字）不在本脚本：它依赖真 GPU 与真模型进程，
# 通用脚本测不了；框架层能如实给出的是各资源的 `vram_estimate_mb` 声明值
# （`aicf/infra/resources/pool.py` 的 ResourceSpec），声明值与实测值分开说。

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


# ── 1. 守卫链路延迟 ─────────────────────────────────────────

def bench_tool_call_latency(n: int = 300) -> dict:
    from aicf.harness.tools.guard import ToolGuard
    from aicf.harness.tools.registry import ManagedToolRegistry
    from aicf.harness.tools.spec import ToolSpec
    from aicf.infra.policy.engine import RulePolicyEngine

    registry = ManagedToolRegistry()
    registry.register_tool('bench.noop', '基准用空转工具', lambda **kw: 'ok',
                           parameters={'type': 'object', 'properties': {}})
    tool = registry.get('bench.noop')
    tool.spec = ToolSpec.read_only_default('bench.noop')
    registry.attach_guard(ToolGuard(policy=RulePolicyEngine()))

    samples = []
    for i in range(n):
        started = time.perf_counter()
        text, _diff, error = registry.execute('bench.noop', {'i': i})
        elapsed_us = (time.perf_counter() - started) * 1_000_000
        assert not error, text
        samples.append(elapsed_us)
    samples.sort()
    return {
        'metric': 'tool_call_latency_us',
        'n': n,
        'p50_us': round(statistics.median(samples), 1),
        'p95_us': round(samples[int(len(samples) * 0.95)], 1),
        'mean_us': round(statistics.fmean(samples), 1),
        'unit': 'µs / call',
        '口径': '纯工具经守卫链路（策略+幂等检查+审计）的本地单次往返',
    }


# ── 2. journal 重放恢复 ────────────────────────────────────

def bench_journal_recovery(events: int = 200) -> dict:
    from aicf.infra.runtime import ManagedRuntime, SqliteRuntimeStore, migrate_runtime
    from aicf.infra.runtime.recovery import recover
    from aicf.infra.store.sqlite import SqliteStore

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / 'bench.db'
        store = SqliteStore(db_path)
        migrate_runtime(store)
        port = SqliteRuntimeStore(store)
        session_id = 'bench-session'
        runtime = ManagedRuntime(port, session_id=session_id)
        runtime.start_session(session_id=session_id)
        runtime.start_turn(turn_id='bench-turn', input={'text': 'bench'})
        for i in range(events):
            runtime.emit('bench.event', {'seq': i, 'text': f'事件内容 {i}'})
        runtime.finish_turn(status='succeeded', stop_reason='done')

        # 恢复口径：只靠 journal 重放（checkpoint 损坏路径的等价场景）
        started = time.perf_counter()
        plan = recover(port, session_id)
        elapsed_ms = (time.perf_counter() - started) * 1000
        store.close()
    return {
        'metric': 'journal_recovery_ms',
        'events': events,
        'recovery_ms': round(elapsed_ms, 2),
        'replayed_events': len(plan.events) if hasattr(plan, 'events') else None,
        'unit': 'ms / 恢复',
        '口径': 'journal 全量重放（无 checkpoint 可用的恢复路径）',
    }


# ── 3. 分层记忆压缩比 ──────────────────────────────────────

def bench_memory_compaction(entries: int = 40) -> dict:
    from aicf.harness.memory.base import MemoryEntry
    from aicf.harness.memory.layers import LayeredMemoryView

    def compactor(texts, budget_chars):
        # 确定性「摘要」：每条压成第一句（与生产 compactor 的确定桩同型）
        joined = '；'.join(t.split('。')[0] for t in texts)
        return joined[:budget_chars] if budget_chars else joined

    view = LayeredMemoryView(compactor=compactor)
    memories = [
        MemoryEntry(
            text=f'这是第 {i} 条会话记忆。用户讨论了主题 {i % 7}，'
                 f'并给出了长度可观的上下文，用于撑起一次真实的 L1 压缩。',
            role='user',
            meta={'layer': 'L1'},
            timestamp=1000.0 + i,
        )
        for i in range(entries)
    ]
    raw_chars = sum(len(m.text) for m in memories)
    # 总预算 = 原文总量 → L1 拿 30%，必然触发压缩（这是要测的场景）
    total_budget = raw_chars
    pairs = view.assemble(memories, total_budget, query='主题')
    compacted_chars = sum(len(text) for layer, text in pairs if layer == 'L1')
    ratio = raw_chars / compacted_chars if compacted_chars else 0.0
    return {
        'metric': 'memory_compaction_ratio',
        'entries': entries,
        'raw_chars': raw_chars,
        'compacted_chars': compacted_chars,
        'ratio': round(ratio, 2),
        'unit': '字符比（>1 = 有压缩）',
        '口径': 'L1 层全部原文进入摘要压缩后，组装产物（摘要+保留的最新原文）'
                '与原文的字符量之比',
    }


# ── 4. 故障注入层（崩溃恢复证据）────────────────────────────

def bench_fault_suite() -> dict:
    # 用当前解释器的 pytest —— PATH 上的 pytest 可能属于另一个环境，
    # 那边的 sys.path 没有 aicf，conftest 直接 ImportError。
    import os
    argv = [sys.executable, '-m', 'pytest', '-q', str(REPO / 'tests' / 'fault')]
    env = dict(os.environ)
    env['PYTHONPATH'] = str(REPO) + os.pathsep + env.get('PYTHONPATH', '')
    started = time.perf_counter()
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=600,
                          cwd=str(REPO), env=env)
    wall = time.perf_counter() - started
    import re
    output = proc.stdout or ''
    passed = failed = skipped = 0
    m = re.search(r'(\d+) passed', output)
    if m:
        passed = int(m.group(1))
    m = re.search(r'(\d+) failed', output)
    if m:
        failed = int(m.group(1))
    m = re.search(r'(\d+) skipped', output)
    if m:
        skipped = int(m.group(1))
    attempted = passed + failed
    return {
        'metric': 'fault_suite',
        'passed': passed,
        'failed': failed,
        'skipped': skipped,
        'success_rate': round(passed / attempted, 4) if attempted else None,
        'wall_seconds': round(wall, 1),
        '口径': 'tests/fault/ 故障注入层（kill -9 / 重复投递 / 损坏恢复）'
                '—— 崩溃恢复成功率以这一层为准，不由本脚本伪造',
    }


def main() -> int:
    parser = argparse.ArgumentParser(description='aicf-core 可复现基准')
    parser.add_argument('--json', action='store_true', help='输出 JSON')
    parser.add_argument('--out', default='',
                        help='结果写入该 JSON 文件')
    args = parser.parse_args()

    results = [
        bench_tool_call_latency(),
        bench_journal_recovery(),
        bench_memory_compaction(),
        bench_fault_suite(),
    ]
    if args.out:
        Path(args.out).write_text(
            json.dumps(results, ensure_ascii=False, indent=2),
            encoding='utf-8')
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0
    print('aicf-core 基准（复现命令：python benchmarks/run_benchmarks.py）')
    for item in results:
        print(f"\n◆ {item['metric']}  ——  {item['口径']}")
        for key, value in item.items():
            if key in ('metric', '口径'):
                continue
            print(f'    {key}: {value}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
