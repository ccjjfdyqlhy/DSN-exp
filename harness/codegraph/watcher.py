# harness/codegraph/watcher.py
# FileWatcher — 源码变更监听（场景无关）。
#
# 从 dekacode code_graph/watcher.py 提炼并引擎化：
#   - mtime 轮询扫描（跳过 .git/__pycache__/venv/node_modules/.dekacode）
#   - get_changed_files() 返回变更文件列表（首次扫描不报变更）
#   - on_change 回调可挂接 codegraph 增量重建
#   - include_exts 可配置（默认 .py）

from __future__ import annotations

import os
import time
from typing import Callable, Optional

_SKIP_DIRS = {".git", "__pycache__", "venv", "node_modules", ".dekacode", ".dsn", ".idea", ".vscode"}


class FileWatcher:
    """轮询式文件变更监听。"""

    def __init__(self, project_root: str, *, interval: float = 2.0,
                 include_exts: Optional[set] = None,
                 on_change: Optional[Callable[[list[str]], None]] = None):
        self.project_root = os.path.abspath(project_root)
        self.interval = interval
        self.include_exts = include_exts or {".py"}
        self.on_change = on_change
        self._mtimes: dict[str, int] = {}   # st_mtime_ns（纳秒，避免秒级精度漏检）
        self._scan()

    def _walk(self):
        for root, dirs, files in os.walk(self.project_root):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
            yield root, files

    def _scan(self) -> None:
        for root, files in self._walk():
            for f in files:
                if not self._wanted(f):
                    continue
                fpath = os.path.join(root, f)
                try:
                    self._mtimes[fpath] = os.stat(fpath).st_mtime_ns
                except OSError:
                    pass

    def _wanted(self, fname: str) -> bool:
        return os.path.splitext(fname)[1] in self.include_exts

    def get_changed_files(self) -> list[str]:
        """返回自上次调用以来变更/新增的文件；首次扫描返回空。"""
        changed = []
        seen: set[str] = set()
        for root, files in self._walk():
            for f in files:
                if not self._wanted(f):
                    continue
                fpath = os.path.join(root, f)
                seen.add(fpath)
                try:
                    mtime = os.stat(fpath).st_mtime_ns
                except OSError:
                    continue
                old = self._mtimes.get(fpath)
                if old is None or mtime != old:
                    changed.append(fpath)
                    self._mtimes[fpath] = mtime
        # 删除检测
        for fpath in list(self._mtimes):
            if fpath not in seen:
                self._mtimes.pop(fpath, None)
                changed.append(fpath)
        if changed and self.on_change is not None:
            try:
                self.on_change(changed)
            except Exception:
                pass
        return changed

    def watch_loop(self, *, stop_event: Optional[object] = None) -> None:
        """阻塞轮询循环（供线程运行）。stop_event 需支持 .is_set()。"""
        while stop_event is None or not stop_event.is_set():
            try:
                self.get_changed_files()
            except Exception:
                pass
            time.sleep(self.interval)

    def __repr__(self) -> str:
        return f"<FileWatcher root={self.project_root} tracked={len(self._mtimes)}>"
