# harness/pipeline/__init__.py
# 通用消息管线层 — 与具体模态/场景解耦。
#
# base.py     Plugin / AsyncPlugin / HookPoint / Context
# manager.py  PluginManager（优先级调度）
# pipeline.py Pipeline（编排 HookPoint）
# events.py   EventBus（发布/订阅）
# outputs.py  OutputRenderer（输出渲染 SPI）

from .base import HookPoint, Context, Attachment, Plugin, AsyncPlugin
from .manager import PluginManager
from .pipeline import Pipeline
from .events import EventBus
from .outputs import OutputRenderer
from .filters import OutputFilter

__all__ = [
    "HookPoint",
    "Context",
    "Attachment",
    "Plugin",
    "AsyncPlugin",
    "PluginManager",
    "Pipeline",
    "EventBus",
    "OutputRenderer",
    "OutputFilter",
]
