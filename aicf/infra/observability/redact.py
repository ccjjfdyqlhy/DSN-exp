# infra/observability/redact.py
# **统一**脱敏出口 + JSONL 读写。
#
# 为什么住在 infra：脱敏是**所有**落盘路径都要用的原语 —— trace 导出
# （harness 侧）、审计（infra 侧）、评测样本（infra 侧）都要过同一道门。
# 放在 infra，harness 往上 import 它，两边共用**一份**实现；
# 放在 harness 就会逼着 infra 反向依赖 harness（违规）。
#
# 为什么脱敏只实现一次：敏感值一旦分散在多个模块里各写一遍，必然漏改一处 ——
# 而漏改的那一处就是事故。所以本模块的 redact() 是唯一实现，
# 任何需要脱敏的地方都从这里 import，不允许另写一份。
#
# 缺陷备忘：
#   - redact 会递归进 dict/list；遇到自引用结构会无限递归 → 限制深度，
#     超深直接替换成占位符（宁可少信息，也不要栈溢出）。
#   - 占位符是 '***' 而不是 '***REDACTED***'：审计要给人看，
#     长得像原值的占位符容易和真实值混淆。
#   - **引用型**键名（credential_ref 这类）不脱敏：值是「指向某物的指针」
#     而不是秘密本身。把它抹成 '***' 等于把审计里最关键的信息擦掉 ——
#     脱敏的目标是「不泄露秘密」，不是「不泄露任何信息」。
#   - 写文件用 UTF-8 + ensure_ascii=False：中文 payload 不该变成 \uXXXX。

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

__all__ = [
    'REDACTED',
    'REFERENCE_KEY_SUFFIXES',
    'SECRET_VALUE_PREFIXES',
    'SENSITIVE_KEYS',
    'SENSITIVE_KEY_PARTS',
    'read_jsonl',
    'redact',
    'redact_dict',
    'write_jsonl',
]

#: 敏感值的统一占位符
REDACTED = '***'

#: 键名命中即视为敏感（**精确**匹配，键名统一小写）
SENSITIVE_KEYS = frozenset({
    'password', 'passwd', 'pwd', 'passphrase', 'secret', 'secrets',
    'token', 'api_key', 'apikey', 'access_key', 'secret_key',
    'client_secret', 'private_key', 'credential', 'credentials',
    'auth', 'authorization', 'cookie', 'session_key', 'signature',
    'bearer', 'jwt', 'refresh_token', 'access_token',
})

#: 键名包含这些片段即视为敏感（子串匹配，覆盖 access_token / my_password 等）
SENSITIVE_KEY_PARTS = (
    'password', 'passwd', 'passphrase', 'secret', 'token',
    'api_key', 'apikey', 'credential', 'private_key',
)

#: **引用**型键名：值是「指向某物的指针」而不是秘密本身。
#:
#: 典型例子：audit.secret_access 的 credential_ref（'vault://prod/db'）。
#: 把它脱敏成 '***' 等于把审计里最关键的信息（访问的是哪个凭据）擦掉。
#: 约定：以 _ref / _refs / _id / _ids / _name 结尾的键名按引用处理。
REFERENCE_KEY_SUFFIXES = ('_ref', '_refs', '_id', '_ids', '_name')

#: 值长得像凭据时的兜底（前缀匹配）—— 键名没标出来但值明显是密钥
SECRET_VALUE_PREFIXES = (
    'sk-', 'sk_', 'ghp_', 'gho_', 'ghu_', 'ghs_', 'github_pat_',
    'xoxb-', 'xoxp-', 'AKIA', 'AIza', 'eyJhbGciOi', '-----BEGIN',
)

#: 递归深度上限（防自引用）
_MAX_DEPTH = 12


def _normalize_key(key: Any) -> str:
    return str(key).strip().lower().replace('-', '_')


def _is_sensitive_key(key: Any) -> bool:
    norm = _normalize_key(key)
    if norm.endswith(REFERENCE_KEY_SUFFIXES):
        return False  # 引用型键名：值不是秘密本身
    if norm in SENSITIVE_KEYS:
        return True
    return any(part in norm for part in SENSITIVE_KEY_PARTS)


def _redact_str(value: str, secrets: tuple[str, ...], placeholder: str) -> str:
    for secret in secrets:
        if secret and secret in value:
            value = value.replace(secret, placeholder)
    if value.startswith(SECRET_VALUE_PREFIXES):
        return placeholder
    return value


def redact(value: Any,
           *,
           secrets: Iterable[str] = (),
           placeholder: str = REDACTED) -> Any:
    """把敏感值替换成 '***'，返回脱敏后的副本。

    规则：
      - dict 的键命中敏感名单 → 整个值替换为 '***'（不递归，因为值本身就是秘密）；
      - 字符串里包含已知 secret（显式传入）→ 片段替换；
      - 字符串长得像凭据（sk- / ghp_ / AKIA / JWT …）→ 整体替换；
      - 其他类型原样返回（数字、布尔、None 不需要脱敏）。

    深拷贝语义：不会改到入参。
    """
    secret_tuple = tuple(s for s in (secrets or ()) if s)
    return _redact(value, secret_tuple, placeholder, 0)


def _redact(value: Any, secrets: tuple[str, ...], placeholder: str, depth: int) -> Any:
    if depth > _MAX_DEPTH:
        return placeholder
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, val in value.items():
            if _is_sensitive_key(key):
                out[key] = placeholder
            else:
                out[key] = _redact(val, secrets, placeholder, depth + 1)
        return out
    if isinstance(value, (list, tuple, set)):
        items = [_redact(v, secrets, placeholder, depth + 1) for v in value]
        if isinstance(value, tuple):
            return tuple(items)
        if isinstance(value, set):
            return set(items)
        return items
    if isinstance(value, str):
        return _redact_str(value, secrets, placeholder)
    return value


def redact_dict(mapping: Mapping[str, Any] | None,
                *,
                secrets: Iterable[str] = (),
                placeholder: str = REDACTED) -> dict[str, Any]:
    """redact() 的 dict 版本（保证返回 dict，便于直接写进 payload）。"""
    if not mapping:
        return {}
    result = redact(dict(mapping), secrets=secrets, placeholder=placeholder)
    return result if isinstance(result, dict) else {}


def write_jsonl(path: str | os.PathLike[str],
                records: Iterable[Mapping[str, Any]],
                *,
                append: bool = False) -> int:
    """把记录写成 JSONL，返回写出的行数。

    逐行 flush：进程被 kill -9 时已写下的行仍然完整（这是选 JSONL 的原因）。
    """
    target = Path(path)
    if target.parent and str(target.parent) not in ('', '.'):
        target.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    mode = 'a' if append else 'w'
    with open(target, mode, encoding='utf-8') as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False, default=str))
            fh.write('\n')
            count += 1
        fh.flush()
    return count


def read_jsonl(path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    """读回 JSONL；坏行跳过而不是整体失败（trace 文件可能被写坏一半）。"""
    target = Path(path)
    if not target.exists():
        return []
    out: list[dict[str, Any]] = []
    with open(target, encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except (ValueError, TypeError):
                continue
            if isinstance(record, dict):
                out.append(record)
    return out
