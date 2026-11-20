# tests/test_usage_shapes.py
# The token accountants must read both wire shapes: one that only knows the
# OpenAI fields silently bills every Anthropic call at zero.

from __future__ import annotations

from aicf.infra.observability.usage import UsageTracker
from aicf.infra.policy.token_meter import TokenMeter, read_usage


def test_read_usage_understands_the_openai_shape():
    usage = {'prompt_tokens': 100, 'completion_tokens': 20,
             'prompt_tokens_details': {'cached_tokens': 40}}
    assert read_usage(usage) == (100, 20, 40)


def test_read_usage_understands_the_responses_shape():
    usage = {'input_tokens': 100, 'output_tokens': 20,
             'input_tokens_details': {'cached_tokens': 40}}
    assert read_usage(usage) == (100, 20, 40)


def test_read_usage_understands_the_anthropic_shape():
    usage = {'input_tokens': 100, 'output_tokens': 20,
             'cache_read_input_tokens': 40}
    assert read_usage(usage) == (100, 20, 40)


def test_read_usage_tolerates_garbage():
    assert read_usage(None) == (0, 0, 0)
    assert read_usage({'input_tokens': 'not-a-number'}) == (0, 0, 0)


def test_token_meter_bills_an_anthropic_call():
    meter = TokenMeter()
    record = meter.record({'input_tokens': 1_000_000, 'output_tokens': 0,
                           'cache_read_input_tokens': 500_000})
    assert record.input_tokens == 1_000_000
    assert record.cache_hit_input == 500_000
    assert record.cache_miss_input == 500_000
    assert record.cost > 0


def test_usage_tracker_bills_an_anthropic_call():
    tracker = UsageTracker()
    tracker.record_dict({'input_tokens': 1_000_000, 'output_tokens': 0,
                         'cache_read_input_tokens': 500_000})
    assert tracker.total_input == 1_000_000
    assert tracker.total_cache_hit == 500_000
    assert tracker.total_cost > 0
