# infra/resources/profiles.py
# 资源策略档（roadmap 段 6）：随时可用 vs 显存的显式取舍。
#
# ── 为什么要有这三档 ──
# 现状是「配置散在各资源里」（tts 3600s / decision 900s / vlm 900s），
# 用户安静 15 分钟后第一次开口要等模型重新加载 —— 而「随时可用」
# 是愿景里写着的承诺，不能只是一句口号。三档把取舍摆在明面上：
#
#   resident   显存换延迟：永不自动卸载。第一次语音请求的延迟 == 常驻延迟。
#              代价：ASR/TTS/VLM/decision 的显存**一直**占着。
#   balanced   各资源按自己的配置来（现状行为，向后兼容的默认档）。
#   eco        显存优先：闲置 10 分钟就卸（decision/vlm 5 分钟）。
#              代价：每次冷启动都重新加载，第一次请求明显变慢。
#
# 生效方式：resident/eco 是**全局覆盖**（按资源 kind 改写 spec.idle_timeout）；
# balanced 不动任何配置 —— 每个资源的独立配置继续有效。
#
# 解析顺序（resolve_profile）：显式参数 > AICF_RESOURCE_PROFILE 环境变量 >
# ~/.aicf/resource_profile 配置文件 > balanced。CLI 的 --set 只写配置文件，
# 环境变量优先级更高 —— 想临时覆盖时不用改文件。

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

try:
    from .pool import ResourceKind
except ImportError:  # pragma: no cover - 直接以模块方式导入时
    ResourceKind = None  # type: ignore[assignment]

__all__ = [
    'PROFILE_TIMEOUTS',
    'PROFILES',
    'ResourceProfile',
    'apply_profile',
    'describe_profile',
    'profile_idle_timeout',
    'read_saved_profile',
    'resolve_profile',
    'save_profile',
]

#: kind → 秒。0 = 永不卸载。
PROFILES: dict[str, dict[str, int]] = {
    'resident': {'asr': 0, 'tts': 0, 'vlm': 0, 'decision': 0},
    # balanced 不在本表里 —— 它意味着「不动每个资源的独立配置」。
    'eco': {'asr': 600, 'tts': 600, 'vlm': 300, 'decision': 300},
}

#: 文档与 CLI 展示用的「balanced 基线」（不是覆盖值，只是现状参考值，
#: 与 apps 侧 Config 的默认一致）。
BALANCED_REFERENCE: dict[str, int] = {
    'asr': 3600, 'tts': 3600, 'vlm': 900, 'decision': 900,
}

PROFILE_TIMEOUTS = PROFILES  # 兼容别名（别用，读 PROFILES）


class ResourceProfile(str, Enum):
    RESIDENT = 'resident'
    BALANCED = 'balanced'
    ECO = 'eco'

    @classmethod
    def parse(cls, value: 'str | ResourceProfile') -> 'ResourceProfile':
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value).strip().lower())
        except ValueError:
            raise ValueError(
                f'未知资源策略档: {value!r}（可用: resident / balanced / eco）'
            ) from None


def resolve_profile(explicit: 'str | ResourceProfile | None' = None) -> ResourceProfile:
    """显式参数 > 环境变量 AICF_RESOURCE_PROFILE > 配置文件 > balanced。"""
    if explicit is not None:
        return ResourceProfile.parse(explicit)
    env = (os.environ.get('AICF_RESOURCE_PROFILE') or '').strip()
    if env:
        return ResourceProfile.parse(env)
    saved = read_saved_profile()
    if saved:
        return ResourceProfile.parse(saved)
    return ResourceProfile.BALANCED


def config_path() -> Path:
    base = os.environ.get('AICF_CONFIG_DIR', '~/.aicf')
    return Path(base).expanduser() / 'resource_profile'


def read_saved_profile() -> str:
    """读配置文件里的档名；文件缺失/内容无效 → ''（不当成错误）。"""
    path = config_path()
    try:
        value = path.read_text(encoding='utf-8').strip()
    except OSError:
        return ''
    return value if value in ('resident', 'balanced', 'eco') else ''


def save_profile(profile: 'str | ResourceProfile') -> Path:
    """把档名写进配置文件（CLI --set 的落点）。"""
    name = ResourceProfile.parse(profile).value
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(name + '\n', encoding='utf-8')
    return path


def profile_idle_timeout(profile: 'str | ResourceProfile',
                         kind: str) -> int:
    """某档下某类资源的 idle_timeout（秒；0 = 永不卸载）。

    balanced 返回 0 并由调用方区分 —— 0 在 spec 里本来就是「不回收」，
    但 balanced 的语义是「不动配置」，所以 apply_profile 对 balanced
    直接跳过（见下）。
    """
    name = ResourceProfile.parse(profile).value
    table = PROFILES.get(name)
    if table is None:  # balanced
        return 0
    return table.get(str(kind), 0)


@dataclass
class ProfileChange:
    name: str
    kind: str
    before: int
    after: int

    def to_dict(self) -> dict:
        return {'name': self.name, 'kind': self.kind,
                'before': self.before, 'after': self.after}


def apply_profile(pool: Any,
                  profile: 'str | ResourceProfile | None' = None,
                  ) -> list[ProfileChange]:
    """把策略档落到资源池：改写每个已注册资源的 spec.idle_timeout。

    balanced 是显式的「不动」—— 返回空列表，每个资源的独立配置继续有效。
    pool 需要 list_resources() 与 get_spec(name)（ResourcePool 都有）。
    """
    resolved = resolve_profile(profile)
    if resolved is ResourceProfile.BALANCED:
        return []
    changes: list[ProfileChange] = []
    for row in pool.list_resources():
        spec = pool.get_spec(row['name'])
        if spec is None:
            continue
        after = profile_idle_timeout(resolved, str(row.get('kind', '')))
        before = int(spec.idle_timeout)
        if before == after:
            continue
        spec.idle_timeout = after
        changes.append(ProfileChange(name=row['name'],
                                     kind=str(row.get('kind', '')),
                                     before=before, after=after))
    return changes


def describe_profile(profile: 'str | ResourceProfile | None' = None) -> dict:
    """给 CLI / 文档看的描述：档名 + 来源 + 每类资源的超时。"""
    resolved = resolve_profile(profile)
    if os.environ.get('AICF_RESOURCE_PROFILE', '').strip():
        source = 'env:AICF_RESOURCE_PROFILE'
    elif read_saved_profile():
        source = f'config:{config_path()}'
    else:
        source = 'default'
    timeouts = dict(BALANCED_REFERENCE) if resolved is ResourceProfile.BALANCED \
        else dict(PROFILES[resolved.value])
    return {
        'profile': resolved.value,
        'source': source,
        'idle_timeouts': timeouts,
        'note': ('balanced = 各资源按自己的配置来（这里显示的是参考基线，'
                 '不是覆盖值）') if resolved is ResourceProfile.BALANCED else '',
    }
