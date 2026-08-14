# plugins/base.py
# 兼容层（shim）— 插件基类 / 钩子点 / 上下文统一由 harness 引擎提供。
#
# DSN 引擎已整体迁移到 harness.pipeline：
#   HookPoint      → harness.pipeline.HookPoint（含 PRE_FILTER/PRE_PROCESS/POST_TTS 超集）
#   PluginContext  → harness.pipeline.Context（字段超集，含 chat_id/image_data/agent_* 等）
#   Plugin/AsyncPlugin → harness.pipeline 同名基类（API 完全一致）
# 本模块仅再导出，不再有任何自研实现。

from __future__ import annotations

from harness.pipeline import (
    HookPoint,
    Context as PluginContext,
    Plugin,
    AsyncPlugin,
    Attachment,
)

__all__ = [
    "HookPoint",
    "PluginContext",
    "Plugin",
    "AsyncPlugin",
    "Attachment",
]
