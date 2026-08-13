from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.dsn.plugins.base import PluginContext
from apps.dsn.plugins.pipeline import ChatPipeline


class _NotCopyable:
    def __deepcopy__(self, memo):
        raise TypeError("runtime service")


def test_preprocess_context_clone_isolates_request_data_and_keeps_runtime_services():
    service = _NotCopyable()
    ctx = PluginContext(history=[{"role": "user", "content": "hello"}])
    ctx.full_history = [{"role": "system", "content": "base"}]
    ctx.extra = {"request": {"values": [1]}, "_db": service}

    cloned = ChatPipeline._clone_pre_process_context(ctx)
    cloned.history[0]["content"] = "changed"
    cloned.full_history.append({"role": "user", "content": "new"})
    cloned.extra["request"]["values"].append(2)

    assert ctx.history[0]["content"] == "hello"
    assert len(ctx.full_history) == 1
    assert ctx.extra["request"]["values"] == [1]
    assert cloned.extra["_db"] is service


def test_preprocess_result_merge_preserves_both_branch_outputs():
    original = PluginContext(message="before", image_data="image")
    vision = PluginContext(message="described", image_data=None)
    vision.extra = {"image_description": "a document"}
    other = PluginContext(system_prompt="prompt", full_history=[{"role": "user", "content": "before"}])
    other.extra = {"memory": "context"}

    merged = ChatPipeline._merge_pre_process_results(original, vision, other)

    assert merged.message == "described"
    assert merged.image_data is None
    assert merged.system_prompt == "prompt"
    assert merged.full_history == other.full_history
    assert merged.extra == {"image_description": "a document", "memory": "context"}
