# apps/coding_agent/skills.py
# Coding Agent 内置技能 — 用 harness Tool 定义的真正可用的代码工具。

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from harness.tools import ToolRegistry, tool_from_function


def read_file(path: str) -> str:
    """读取文本文件内容。"""
    return Path(path).read_text(encoding="utf-8")


def write_file(path: str, content: str) -> str:
    """写入/覆盖文本文件。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"已写入 {path} ({len(content)} 字符)"


def list_dir(path: str = ".") -> str:
    """列出目录内容（不含隐藏与 __pycache__）。"""
    p = Path(path)
    items = [e for e in p.iterdir()
             if not e.name.startswith(".") and e.name != "__pycache__"]
    items.sort(key=lambda e: (e.is_file(), e.name.lower()))
    return "\n".join(f"{'📁' if e.is_dir() else '📄'} {e.name}" for e in items) or "(空目录)"


def run_bash(command: str) -> str:
    """执行 shell 命令，返回 stdout+stderr。"""
    proc = subprocess.run(command, shell=True, capture_output=True,
                          text=True, timeout=60)
    out = (proc.stdout or "") + (proc.stderr or "")
    return out.strip() or "(无输出)"


def grep(pattern: str, path: str = ".", max_results: int = 50) -> str:
    """在目录内递归 grep 文本，返回匹配行。"""
    lines = []
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
        for f in files:
            if f.endswith((".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml")):
                fp = os.path.join(root, f)
                try:
                    for i, line in enumerate(Path(fp).read_text(encoding="utf-8").splitlines(), 1):
                        if pattern in line:
                            lines.append(f"{fp}:{i}: {line.strip()[:160]}")
                            if len(lines) >= max_results:
                                return "\n".join(lines)
                except (UnicodeDecodeError, OSError):
                    continue
    return "\n".join(lines) or "(无匹配)"


def git_diff() -> str:
    """显示工作区相对 HEAD 的改动统计与 diff 摘要。"""
    proc = subprocess.run("git diff --stat && git diff -- '*.py' | head -200",
                          shell=True, capture_output=True, text=True)
    return (proc.stdout or proc.stderr).strip() or "(无改动)"


def install_coding_tools(registry: ToolRegistry) -> None:
    """把全部 coding 工具注册进 registry。"""
    for fn in (read_file, write_file, list_dir, run_bash, grep, git_diff):
        registry.register(tool_from_function(fn, namespace="code"))
