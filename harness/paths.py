# harness/paths.py
# 用户级状态目录：引擎与应用自己的东西放在哪。
#
# 为什么需要它：
#   引擎的默认持久化路径曾经是**相对工作目录**的
#   （``<cwd>/sessions/agent.db``）—— 于是「在哪个项目里启动引擎」
#   就决定了「项目目录里多出哪个文件」。应用（agent 正在改的那个仓库）
#   不该替引擎的运行时状态买单。
#
# 规则：
#   $AICF_HOME  显式指定
#   ~/.aicf     默认
#
# 应用想放在别处就自己传路径 —— 这个函数只是**默认**的落点，
# 不是强制的隔离。

from __future__ import annotations

import os
from pathlib import Path

#: 默认的用户级状态目录名。
DEFAULT_STATE_DIR = '.aicf'


def state_dir() -> Path:
    """用户级状态目录（``$AICF_HOME`` 或 ``~/.aicf``）。"""
    override = os.environ.get('AICF_HOME')
    if override:
        return Path(override).expanduser()
    return Path.home() / DEFAULT_STATE_DIR


def state_file(*parts: str) -> Path:
    """状态目录下的一个文件；父目录会被建出来。"""
    target = state_dir().joinpath(*parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


__all__ = ['DEFAULT_STATE_DIR', 'state_dir', 'state_file']
