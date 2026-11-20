# harness/usage.py
# Token estimation, usage normalization and budget math.
#
# One estimator for the whole engine: the context manager uses it for
# compaction decisions, the transcript for display, the tool layer for
# result truncation.  Estimates are deliberately conservative (ASCII ~4
# chars per token, every image a fixed charge) so budgets fail safe.

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from .images import estimate_marker_charge

_ANSI_RE = re.compile(r'\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
_UUID_RE = re.compile(
    r'\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-'
    r'[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b'
)
NORMALIZER_VERSION = '2'


def canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
    ).replace('\r\n', '\n').replace('\r', '\n')


def estimate_text_tokens(text: str) -> int:
    ascii_count = sum(ord(char) < 128 for char in text)
    return max(1, (ascii_count + 3) // 4 + (len(text) - ascii_count))


def estimate_tokens(value: Any) -> int:
    if isinstance(value, str):
        text = value
    else:
        text = canonical_json(value)
    return estimate_text_tokens(text) + estimate_marker_charge(text)


def normalize_tool_result(tool_name: str, original: str,
                          max_tokens: int = 8_000) -> dict[str, Any]:
    text = _ANSI_RE.sub('', original).replace('\r\n', '\n').replace('\r', '\n')
    text = _UUID_RE.sub('<uuid>', text)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    limit = max_tokens * 4
    if len(text) > limit:
        head = limit * 2 // 3
        tail = limit - head
        text = f'{text[:head]}\n... <{tool_name} output truncated> ...\n{text[-tail:]}'
    return {
        'text': text,
        'original_hash': 'sha256:' + hashlib.sha256(original.encode('utf-8')).hexdigest(),
        'normalizer_version': NORMALIZER_VERSION,
    }


def _get(obj: Any, key: str, default: Any = None) -> Any:
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def normalize_usage(raw: Any) -> dict[str, int | float | None]:
    if raw is None:
        return {
            'input_tokens': None, 'cached_input_tokens': None,
            'uncached_input_tokens': None, 'output_tokens': None,
            'cache_hit_rate': None,
        }
    input_tokens = _get(raw, 'input_tokens', _get(raw, 'prompt_tokens'))
    output_tokens = _get(raw, 'output_tokens', _get(raw, 'completion_tokens'))
    details = _get(raw, 'input_tokens_details', _get(raw, 'prompt_tokens_details'))
    cached = _get(details, 'cached_tokens') if details is not None else None
    cached = _get(raw, 'cache_read_input_tokens', cached)
    try:
        input_tokens = int(input_tokens) if input_tokens is not None else None
        output_tokens = int(output_tokens) if output_tokens is not None else None
        cached = int(cached) if cached is not None else None
    except (TypeError, ValueError):
        input_tokens = output_tokens = cached = None
    uncached = None if input_tokens is None or cached is None else max(0, input_tokens - cached)
    hit_rate = None if not input_tokens or cached is None else cached / input_tokens
    return {
        'input_tokens': input_tokens,
        'cached_input_tokens': cached,
        'uncached_input_tokens': uncached,
        'output_tokens': output_tokens,
        'cache_hit_rate': hit_rate,
    }


def merge_usage(previous: dict[str, Any] | None,
                update: dict[str, Any] | None) -> dict[str, int | float | None]:
    """Merge split usage reports (Anthropic sends prompt and completion counts
    in separate stream events) without discarding the earlier fields."""
    merged: dict[str, int | float | None] = dict(previous or {})
    if update:
        for key in ('input_tokens', 'cached_input_tokens', 'output_tokens'):
            value = update.get(key)
            if value is not None:
                merged[key] = value
    input_tokens = merged.get('input_tokens')
    cached = merged.get('cached_input_tokens')
    merged['uncached_input_tokens'] = (
        None if input_tokens is None or cached is None
        else max(0, int(input_tokens) - int(cached)))
    merged['cache_hit_rate'] = (
        None if not input_tokens or cached is None
        else cached / input_tokens)
    return merged


@dataclass(frozen=True)
class TokenBudget:
    context_window: int
    reserved_output: int = 8_192
    safety_margin: int = 1_024
    stable_tokens: int = 0

    def usable(self) -> int:
        return max(0, self.context_window - self.stable_tokens
                   - self.reserved_output - self.safety_margin)

    def used_fraction(self, used_tokens: int) -> float:
        usable = self.usable()
        if usable <= 0:
            return 1.0
        return used_tokens / usable


def effective_reserved(context_window: int, configured: int,
                       model_max_output: int) -> int:
    """Keep the output reserve inside both the model and window budgets."""
    reserved = max(256, min(int(configured), int(model_max_output)))
    return min(reserved, max(256, int(context_window) // 2))


class TokenBudgetExceeded(RuntimeError):
    pass
