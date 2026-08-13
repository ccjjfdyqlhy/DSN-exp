# plugins/builtin/notebook
# 用户观察日记模块 — 独立于 memory 系统的笔记功能

from .notebook_store import NotebookStore
from .notebook_plugin import NotebookPlugin

__all__ = ["NotebookStore", "NotebookPlugin"]
