# harness/cli/learncmd.py
# `aicf learn` —— 从 trace 构建监督微调数据集（roadmap 段 8）。
#
# 这条命令是 harness/learning + infra/finetune 的**第二个消费者**：
# 之前这对模块（约 4,044 行）只有私有应用一个消费者，
# 「框架长出没人用的部分」的风险挂在它头上。现在：
#
#   aicf run --dataset offline --trace-dir traces/   # 先跑出轨迹
#   aicf learn --traces traces/ --out sft_out/       # 轨迹 → SFT 数据集
#
# 复用的正是框架自己的学习链路：
#   harness/learning/dataset_builder.py  取数与筛选（结构校验、剥推理内容）
#   infra/finetune/dataset.py            角色归一、切分、写盘、统计
#
# 诚实声明：trace 里只有「输入 → 回复」的对，没有 reward 信号 ——
# 这里产的是**中性样本**（reward=1.0）。要给样本打分，走
# harness/learning/evaluator.py 的分层判官（那是有 reward 消费者的路径）。

from __future__ import annotations

from typing import Any

from .common import eprint, out_json


def cmd_learn(args: Any) -> int:
    from aicf.harness.learning.dataset_builder import DatasetBuilder

    from .evalcmd import _load_traces

    try:
        traces = _load_traces(args.traces)
    except Exception as error:  # noqa: BLE001
        eprint(f'trace 读取失败: {error}')
        return 2

    builder = DatasetBuilder(args.out)
    accepted = 0
    for trace in traces:
        # 没有回答的轨迹教不了模型 —— 直接跳过（builder 也会拒，这里早拒
        # 是为了让「跳过原因」在输出里可读）。
        if not (trace.output or '').strip():
            continue
        messages = [
            {'role': 'user', 'content': trace.input},
            {'role': 'assistant', 'content': trace.output},
        ]
        if builder.from_messages(messages, source='cli-traces'):
            accepted += 1

    if accepted == 0:
        eprint('没有可用轨迹：trace 里没有「输入 → 非空回复」的样本'
               '（桩模型回显会被结构校验接受，但请确认你跑的是真模型）')
        return 1

    report = builder.build()
    payload = {
        'accepted': accepted,
        'total_traces': len(traces),
        'stats': report.stats.to_dict() if hasattr(report.stats, 'to_dict')
                 else dict(report.stats or {}),
        'train_path': str(report.train_path),
        'val_path': str(report.val_path) if report.val_path else '',
        'sources': dict(report.sources or {}),
    }
    if args.json:
        out_json(payload)
        return 0
    print(f"接受 {accepted}/{len(traces)} 条轨迹 → 训练集 {payload['train_path']}")
    if payload['val_path']:
        print(f"验证集 {payload['val_path']}")
    stats = payload['stats']
    for key in ('total', 'kept', 'dropped', 'train', 'val'):
        if key in stats:
            print(f"  {key}: {stats[key]}")
    print('下一步（可选）：infra/finetune 的 FinetuneManager.submit() 用这份 JSONL 提交训练')
    return 0


def register(sub: Any) -> None:
    learn = sub.add_parser('learn',
                           help='从 trace 构建监督微调（SFT）数据集')
    learn.add_argument('--traces', required=True, help='trace 文件或目录')
    learn.add_argument('--out', default='sft_out', help='数据集输出目录')
    learn.add_argument('--json', action='store_true')
    learn.set_defaults(func=cmd_learn)


__all__ = ['cmd_learn', 'register']
