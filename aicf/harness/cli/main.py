# harness/cli/main.py
# `aicf` 命令行入口。
#
# 子命令：
#   init      生成空白 Agent 骨架（接入点已接好，生成后立刻能跑）
#   run       跑一次 agent，落 trace（--dataset 跑整个数据集）
#   eval      拿 dataset + trace 打分（--group 只评子集）
#   gate      出四闸门报告
#   tool      工具目录 / 手工执行
#   session   会话列表 / 从 journal 恢复
#   resources 资源策略档：随时可用 vs 显存（resident/balanced/eco）
#   learn     从 trace 构建监督微调数据集（learning/finetune 的第二消费者）
#   finetune  训练作业与晋级：learn 产出的数据集在这里变成生效的适配器（W7）
#   artifact  Agent 资产的校验 / 目录 / 发布 / 回滚（策划案 §5.4）
#
# 设计原则：
#   - 默认离线可用（不配 API key 也能跑通 init → run → eval → gate）
#   - 机器可读：--json 输出结构化结果
#   - 失败方向一致：策略拒绝 / 审批超时 / 沙箱拦截都返回非 0 退出码

from __future__ import annotations

import argparse
import sys
from typing import Any, Optional, Sequence

from . import artifactcmd, evalcmd, finetunecmd, initcmd, learncmd, runcmd, resourcescmd, sessioncmd, toolcmd


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='aicf',
        description='AICF 命令行 —— 安全、幂等、可评测地跑一次长任务')
    parser.add_argument('--version', action='store_true', dest='show_version',
                        help='打印版本号并退出')
    sub = parser.add_subparsers(dest='command')

    # ── run ──────────────────────────────────────────────
    run = sub.add_parser('run', help='跑一次 agent，落一份 trace')
    run.add_argument('input', nargs='?', default='', help='用户输入')
    run.add_argument('--artifact', default='',
                     help='Agent 声明（agent.yaml）：kernel/工具/模型按声明装配')
    run.add_argument('--input', dest='input_opt', default='',
                     help='用户输入（与位置参数等价）')
    run.add_argument('--trace', default='', help='trace 输出路径（JSONL）')
    run.add_argument('--model', default='', help='模型名')
    run.add_argument('--base-url', default='', help='OpenAI 兼容端点')
    run.add_argument('--api-key', default='', help='API key（默认读环境变量）')
    run.add_argument('--max-steps', type=int, default=4, help='最大执行步数')
    run.add_argument('--kernel', default='',
                     help='执行架构（react/workflow/planner）；--artifact 声明优先')
    run.add_argument('--include', action='append', default=[],
                     help='只启用某些工具组（可重复）')
    run.add_argument('--deny-tool', action='append', default=[],
                     help='显式拒绝某个工具（可重复）')
    run.add_argument('--yes', action='store_true',
                     help='自动批准需要审批的调用（谨慎使用）')
    run.add_argument('--run-id', default='', help='运行 id')
    run.add_argument('--session-id', default='', help='会话 id')
    run.add_argument('--case-id', default='', help='关联的评测 case id')
    run.add_argument('--dataset', default='',
                     help='跑整个数据集（每个用例一轮、一条 trace），如 offline')
    run.add_argument('--trace-dir', default='traces',
                     help='数据集模式下 trace 输出目录（默认 traces/）')
    run.add_argument('--workspace', default='.aicf-workspace',
                     help='数据集 setup 文件写入的工作区目录')
    run.add_argument('--identity', default='',
                     help='agent identity for the audit trail (W5.1)')
    run.add_argument('--db', default='aicf.db', help='运行时数据库')
    run.add_argument('--json', action='store_true', help='输出 JSON')

    # ── eval ─────────────────────────────────────────────
    evaluate = sub.add_parser('eval', help='对一批 trace 打分')
    evaluate.add_argument('--dataset', default='', help='数据集路径（--from-badcases 时可省）')
    evaluate.add_argument('--group', action='append', default=[],
                          help='只评某几组（可重复、可逗号分隔，如 --group refusal,safety）')
    evaluate.add_argument('--from-badcases', default='',
                          help='从坏样本库构建回归集（db 路径；W5.3）')
    evaluate.add_argument('--traces', default='', help='trace 文件或目录')
    evaluate.add_argument('--artifact', default='', help='Agent 声明文件')
    evaluate.add_argument('--model', default='', help='模型名（进 run version）')
    evaluate.add_argument('--commit', default='', help='git commit（进 run version）')
    evaluate.add_argument('--run-id', default='', help='运行 id')
    evaluate.add_argument('--out', default='', help='运行结果输出路径')
    evaluate.add_argument('--json', action='store_true', help='输出 JSON')

    # ── gate ─────────────────────────────────────────────
    gate = sub.add_parser('gate', help='出四闸门报告')
    gate.add_argument('--run', required=True, help='运行结果文件')
    gate.add_argument('--baseline', default='', help='baseline 运行结果文件')
    gate.add_argument('--out', default='', help='报告输出路径')
    gate.add_argument('--cost-budget', type=float, default=None,
                      help='会话成本绝对上限（美元；不设且有 baseline 才判成本）')
    gate.add_argument('--db', default='',
                      help='报告落库位置（发布迁移从这里查报告；默认 aicf.db）')
    gate.add_argument('--json', action='store_true', help='输出 JSON')

    # ── tool ─────────────────────────────────────────────
    tool = sub.add_parser('tool', help='工具目录与手工执行')
    tool_sub = tool.add_subparsers(dest='tool_command')
    tool_list = tool_sub.add_parser('list', help='列出工具目录')
    tool_list.add_argument('--include', action='append', default=[])
    tool_list.add_argument('--json', action='store_true')
    tool_exec = tool_sub.add_parser('exec', help='手工执行一个工具')
    tool_exec.add_argument('name', help='工具名')
    tool_exec.add_argument('--args', dest='args_json', default='{}',
                           help='JSON 参数')
    tool_exec.add_argument('--identity', default='',
                           help='agent identity for the audit trail (W5.1)')
    tool_exec.add_argument('--policy', choices=['strict', 'legacy'],
                           default='strict', help='策略模式')
    tool_exec.add_argument('--allow', action='append', default=[],
                           help='显式放行的工具（可重复）')
    tool_exec.add_argument('--deny', action='append', default=[],
                           help='显式拒绝的工具（可重复）')
    tool_exec.add_argument('--yes', action='store_true',
                           help='自动批准需要审批的调用')
    tool_exec.add_argument('--approval-timeout', type=float, default=30.0)
    tool_exec.add_argument('--include', action='append', default=[])
    tool_exec.add_argument('--db', default='aicf.db', help='运行时数据库')
    tool_exec.add_argument('--json', action='store_true')

    # ── session ──────────────────────────────────────────
    session = sub.add_parser('session', help='会话与恢复')
    session_sub = session.add_subparsers(dest='session_command')
    session_list = session_sub.add_parser('list', help='列出会话')
    session_list.add_argument('--db', default='aicf.db', help='运行时数据库')
    session_list.add_argument('--json', action='store_true')
    session_resume = session_sub.add_parser('resume', help='从 journal 恢复')
    session_resume.add_argument('session_id', help='会话 id')
    session_resume.add_argument('--db', default='aicf.db', help='运行时数据库')
    session_resume.add_argument('--json', action='store_true')

    # ── init ─────────────────────────────────────────────
    initcmd.register(sub)

    # ── resources ────────────────────────────────────────
    resourcescmd.register(sub)

    # ── learn / finetune ─────────────────────────────────
    learncmd.register(sub)
    finetunecmd.register(sub)

    # ── artifact ─────────────────────────────────────────
    artifactcmd.register(sub)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exit_code:
        # argparse 的 --help / 参数错误会抛 SystemExit。这里接住并转成
        # 返回码：main() 永远返回 int，测试和库内调用都不用包 try/except。
        code = exit_code.code
        return code if isinstance(code, int) else (0 if code is None else 1)

    if getattr(args, 'show_version', False):
        import aicf.harness
        print(aicf.harness.__version__)
        return 0

    command = args.command
    if not command:
        parser.print_help()
        return 0

    if command == 'run':
        if getattr(args, 'input_opt', ''):
            args.input = args.input_opt
        return runcmd.cmd_run(args)
    if command == 'eval':
        return evalcmd.cmd_eval(args)
    if command == 'gate':
        return evalcmd.cmd_gate(args)
    if command == 'tool':
        if args.tool_command == 'list':
            return toolcmd.cmd_list(args)
        if args.tool_command == 'exec':
            return toolcmd.cmd_exec(args)
        print('用法: aicf tool {list|exec} ...')
        return 2
    if command == 'session':
        if args.session_command == 'list':
            return sessioncmd.cmd_list(args)
        if args.session_command == 'resume':
            return sessioncmd.cmd_resume(args)
        print('用法: aicf session {list|resume} ...')
        return 2
    if command == 'init':
        func = getattr(args, 'func', None)
        if func is None:
            print('用法: aicf init [项目名]')
            return 2
        return func(args)
    if command == 'resources':
        if args.resources_command == 'profile':
            return resourcescmd.cmd_profile(args)
        print('用法: aicf resources profile [--set resident|balanced|eco]')
        return 2
    if command == 'finetune':
        func = getattr(args, 'func', None)
        if func is None:
            print('用法: aicf finetune {submit|status|promote|rollback|active}')
            return 2
        return func(args)
    if command == 'learn':
        func = getattr(args, 'func', None)
        if func is None:
            print('用法: aicf learn --traces <path> [--out dir]')
            return 2
        return func(args)
    if command == 'artifact':
        func = getattr(args, 'func', None)
        if func is None:
            print('用法: aicf artifact {validate|show|list|history|publish|rollback} ...')
            return 2
        return func(args)

    parser.print_help()
    return 0


if __name__ == '__main__':  # pragma: no cover
    sys.exit(main())
