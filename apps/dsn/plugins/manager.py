# plugins/manager.py
# 兼容层（shim）— 插件管理器由 harness 引擎提供。
#
# DSN 引擎已整体迁移到 harness.pipeline.manager.PluginManager。
# 调度语义与 DSN 一致：按 priority 升序（值小者先执行），
# 注册/启停/查询/dispatch 系列 API 完全兼容。
# 本模块仅再导出，不再有任何自研实现。

from __future__ import annotations

from harness.pipeline.manager import PluginManager

__all__ = ["PluginManager"]
