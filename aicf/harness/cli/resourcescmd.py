# harness/cli/resourcescmd.py
# `aicf resources` —— 资源策略档的 CLI 开关（roadmap 段 6）。
#
# `aicf resources profile`            看当前档位、来源、每类资源的超时
# `aicf resources profile --set eco`  把选择写进 ~/.aicf/resource_profile
#
# 「随时可用 vs 显存」不该只是一句口号 —— 三档的取舍必须在 CLI 上可见：
#   resident  显存换延迟：永不自动卸载（第一次语音请求零冷启动）
#   balanced  各资源按自己的配置来（默认）
#   eco       显存优先：闲置几分钟就卸（冷启动慢）
#
# 注意优先级：AICF_RESOURCE_PROFILE 环境变量 > 配置文件。
# --set 写的是配置文件；环境变量设了的时候它会赢 —— 这是有意的，
# 临时覆盖不该被配置文件里的旧值绑架。

from __future__ import annotations

from typing import Any

from .common import eprint, out_json

_VALID = ('resident', 'balanced', 'eco')


def cmd_profile(args: Any) -> int:
    from aicf.infra.resources.profiles import (
        describe_profile,
        save_profile,
    )

    set_value = (getattr(args, 'set_profile', '') or '').strip().lower()
    if set_value:
        if set_value not in _VALID:
            eprint(f'未知策略档: {set_value!r}（可用: {" / ".join(_VALID)}）')
            return 2
        if args.json:
            out_json({'profile': set_value, 'saved': True})
        path = save_profile(set_value)
        eprint(f'已保存: {path} → {set_value}')
        # 环境变量还在的话要如实提醒 —— 它会赢过配置文件
        import os
        if os.environ.get('AICF_RESOURCE_PROFILE', '').strip():
            eprint('注意：AICF_RESOURCE_PROFILE 环境变量已设置，'
                   '它的优先级高于配置文件。')

    info = describe_profile()
    if args.json:
        out_json(info)
        return 0
    print(f"当前策略档: {info['profile']}（来源: {info['source']}）")
    timeouts = info['idle_timeouts']
    width = max(len(k) for k in timeouts)
    for kind, seconds in sorted(timeouts.items()):
        human = '永不卸载' if int(seconds) == 0 else f'{int(seconds)} 秒后卸载'
        print(f'  {kind.ljust(width)}  {human}')
    if info.get('note'):
        print(f"  说明: {info['note']}")
    print("三档语义: resident=显存换延迟 / balanced=各资源自配（默认） / "
          "eco=显存优先")
    print("切换: aicf resources profile --set resident|balanced|eco")
    return 0


def cmd_status(args: Any) -> int:
    """Pool-side view (W6): resolved profile, per-kind effective timeouts,
    and which resource kinds the pool knows about. A live pool lives inside
    the app that owns it -- this command never spawns services."""
    from aicf.infra.resources.profiles import describe_profile

    info = describe_profile()
    payload = dict(info)
    try:
        from aicf.infra.resources.pool import ResourceKind
        payload['kinds'] = [k.value for k in ResourceKind]
    except Exception:  # noqa: BLE001 -- the enum import must not break status
        payload['kinds'] = []
    payload['live_pool'] = False
    if args.json:
        out_json(payload)
        return 0
    print(f"策略档: {info['profile']}（来源: {info['source']}）")
    for kind, seconds in sorted(info['idle_timeouts'].items()):
        human = '永不卸载' if int(seconds) == 0 else f'{int(seconds)} 秒后卸载'
        print(f'  {kind.ljust(10)}  {human}')
    print(f"资源种类: {', '.join(payload['kinds']) or '-'}")
    print('说明: 池实例归持有它的应用进程；本命令不拉起任何服务。')
    return 0


def register(sub: Any) -> None:
    resources = sub.add_parser('resources', help='资源策略档（随时可用 vs 显存）')
    resources_sub = resources.add_subparsers(dest='resources_command')
    profile = resources_sub.add_parser('profile', help='查看/设置资源策略档')
    profile.add_argument('--set', dest='set_profile', default='',
                         metavar='PROFILE',
                         help='写入配置文件: resident / balanced / eco')
    profile.add_argument('--json', action='store_true')
    profile.set_defaults(func=cmd_profile)
    status = resources_sub.add_parser('status', help='池侧视图：档位 + 各类资源生效超时')
    status.add_argument('--json', action='store_true')
    status.set_defaults(func=cmd_status)


__all__ = ['cmd_profile', 'cmd_status', 'register']
