# tests/test_harness_utilities.py
# Core utility modules: token accounting, usage normalization, image
# markers and file diffs.

from __future__ import annotations

import pytest

from harness.filediff import FileSnapshot, format_diff_for_model, make_file_diff, snapshot_file
from harness.images import (
    FileIdCache, count_image_markers, estimate_marker_charge, has_image_marker,
    image_marker, iter_segments, strip_image_markers,
)
from harness.usage import (
    TokenBudget, TokenBudgetExceeded, canonical_json, effective_reserved,
    estimate_tokens, merge_usage, normalize_tool_result, normalize_usage,
)


# ── usage ────────────────────────────────────────────────────────────

def test_estimate_tokens_counts_images():
    text = 'plain ascii text'
    assert estimate_tokens(text) == (len(text) + 3) // 4
    marked = image_marker('sessions/images/x.png')
    assert count_image_markers(marked) == 1
    assert estimate_tokens(marked) >= 1_200


def test_normalize_tool_result_truncates():
    blob = 'x' * 100_000
    out = normalize_tool_result('bash', blob, max_tokens=1_000)
    assert len(out['text']) < 8_000 * 4
    assert '<bash output truncated>' in out['text']
    assert out['original_hash'].startswith('sha256:')


def test_normalize_usage_shapes():
    merged = normalize_usage({'prompt_tokens': 100,
                              'prompt_tokens_details': {'cached_tokens': 40},
                              'completion_tokens': 20})
    assert merged == {'input_tokens': 100, 'cached_input_tokens': 40,
                      'uncached_input_tokens': 60, 'output_tokens': 20,
                      'cache_hit_rate': 0.4}
    extra = merge_usage(merged, {'output_tokens': 35})
    assert extra['output_tokens'] == 35
    assert extra['input_tokens'] == 100


def test_token_budget_math():
    budget = TokenBudget(context_window=100_000, reserved_output=8_000,
                         safety_margin=1_000, stable_tokens=2_000)
    assert budget.usable() == 89_000
    assert budget.used_fraction(8_900) == 0.1
    assert effective_reserved(10_000, 8_192, 8_192) == 5_000
    with pytest.raises(TokenBudgetExceeded):
        raise TokenBudgetExceeded('over')


# ── image markers ────────────────────────────────────────────────────

def test_marker_roundtrip():
    text = f'before {image_marker("sessions/images/a.png")} after'
    assert has_image_marker(text)
    segments = iter_segments(text)
    assert segments[0] == ('text', 'before ')
    assert segments[1] == ('image', 'sessions/images/a.png')
    assert strip_image_markers(text) == 'before  after'


def test_estimate_marker_charge_helper():
    from harness.images import IMAGE_TOKEN_ESTIMATE
    assert estimate_marker_charge('no markers here') == 0
    assert estimate_marker_charge(image_marker('a.png')) == IMAGE_TOKEN_ESTIMATE


def test_file_id_cache_roundtrip(tmp_path):
    cache = FileIdCache(tmp_path / 'files.json')
    cache.set_id('endpoint::scope', 'key', 'file-123')
    assert FileIdCache(tmp_path / 'files.json').get_id('endpoint::scope', 'key') == 'file-123'
    cache.mark_unsupported('endpoint::scope', 'no files api')
    assert FileIdCache(tmp_path / 'files.json').unsupported('endpoint::scope')


# ── file diffs ───────────────────────────────────────────────────────

def test_snapshot_and_diff(tmp_path):
    target = tmp_path / 'f.txt'
    target.write_text('one\ntwo\n', encoding='utf-8')
    before = snapshot_file(target)
    target.write_text('one\nthree\n', encoding='utf-8')
    after = snapshot_file(target)
    diff = make_file_diff('f.txt', before, after)
    assert diff is not None and diff.additions == 1 and diff.deletions == 1
    assert '<file_diff path="f.txt"' in format_diff_for_model(diff)
    # identical content -> no diff
    assert make_file_diff('f.txt', after, snapshot_file(target)) is None


def test_snapshot_binary_and_huge_files_are_omitted(tmp_path):
    binary = tmp_path / 'b.bin'
    binary.write_bytes(b'\x00\x01\x02')
    assert snapshot_file(binary).omitted is True
    huge = tmp_path / 'h.txt'
    huge.write_text('x' * (1_100_000), encoding='utf-8')
    assert snapshot_file(huge).omitted is True
    assert snapshot_file(tmp_path / 'missing.txt') == FileSnapshot(False, None)
