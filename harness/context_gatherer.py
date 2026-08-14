# harness/context_gatherer.py
# ContextGatherer — 输入指令解析与上下文块采集（场景无关）。
#
# 从 dekacode context_gatherer.py 提炼并引擎化：
#   - @req <file>   把文件内容注入上下文
#   - @sym <name>   把符号定义注入上下文（接 codegraph）
#   - @grep <pat>   把 grep 结果注入上下文
#   - @ls <dir>     列出目录
#   - @tree         目录树
#
# 用法:
#     gatherer = ContextGatherer(workspace, graph=call_graph)
#     parsed = gatherer.parse("看看 @req main.py 这个文件")
#     # parsed.clean_input = "看看 这个文件"
#     # parsed.context_block = 文件内容...

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

_REQ_RE = re.compile(r"(?:^|\s)@req\s+(\S+)")
_SYM_RE = re.compile(r"(?:^|\s)@sym\s+(\S+)")
_GREP_RE = re.compile(r'(?:^|\s)@grep\s+"([^"]+)"(?:\s+(\S+))?')
_LS_RE = re.compile(r"(?:^|\s)@ls\s+(\S+)")
_TREE_RE = re.compile(r"(?:^|\s)@tree(?=\s|$)")


@dataclass
class ParseResult:
    clean_input: str = ""
    context_block: str = ""
    directives_found: bool = False
    directive_kinds: list[str] = field(default_factory=list)


class ContextGatherer:
    """解析输入中的 @ 指令并采集上下文块。"""

    MAX_FILE_LINES = 500
    MAX_FILE_SIZE = 200 * 1024
    MAX_BLOCK_SIZE = 100_000

    def __init__(self, workspace: str, graph: Optional[Any] = None):
        self.workspace = Path(workspace).resolve()
        self.graph = graph

    # ── 解析 ──

    def parse(self, user_input: str) -> ParseResult:
        directives = self._extract(user_input)
        clean = self._strip_directives(user_input)
        if not directives:
            return ParseResult(clean_input=clean, context_block="",
                               directives_found=False)
        block = self._execute(directives)
        if len(block) > self.MAX_BLOCK_SIZE:
            block = block[:self.MAX_BLOCK_SIZE] + "\n\n... [context truncated]"
        return ParseResult(clean_input=clean, context_block=block,
                           directives_found=True,
                           directive_kinds=[d["kind"] for d in directives])

    def _extract(self, text: str) -> list[dict]:
        directives: list[dict] = []
        for m in _REQ_RE.finditer(text):
            directives.append({"kind": "req", "arg": m.group(1).strip()})
        for m in _SYM_RE.finditer(text):
            directives.append({"kind": "sym", "arg": m.group(1).strip()})
        for m in _GREP_RE.finditer(text):
            directives.append({"kind": "grep", "arg": m.group(1).strip(),
                               "glob": m.group(2).strip() if m.lastindex and m.group(2) else ""})
        for m in _LS_RE.finditer(text):
            directives.append({"kind": "ls", "arg": m.group(1).strip()})
        for m in _TREE_RE.finditer(text):
            directives.append({"kind": "tree"})
        return directives

    def _strip_directives(self, text: str) -> str:
        spans = []
        for pat in (_REQ_RE, _SYM_RE, _LS_RE, _TREE_RE):
            for m in pat.finditer(text):
                spans.append((m.start(), m.end()))
        for m in _GREP_RE.finditer(text):
            spans.append((m.start(), m.end()))
        if not spans:
            return text.strip()
        spans.sort()
        parts = []
        pos = 0
        for start, end in spans:
            if start > pos:
                parts.append(text[pos:start])
            pos = end
        parts.append(text[pos:])
        return "".join(parts).strip()

    # ── 执行 ──

    def _execute(self, directives: list[dict]) -> str:
        blocks: list[str] = []
        for d in directives:
            kind = d["kind"]
            try:
                if kind == "req":
                    blocks.append(self._exec_req(d["arg"]))
                elif kind == "sym":
                    blocks.append(self._exec_sym(d["arg"]))
                elif kind == "grep":
                    blocks.append(self._exec_grep(d["arg"], d.get("glob", "")))
                elif kind == "ls":
                    blocks.append(self._exec_ls(d["arg"]))
                elif kind == "tree":
                    blocks.append(self._exec_tree())
            except Exception as e:
                blocks.append(f"[@{kind} 失败: {e}]")
        return "\n\n".join(b for b in blocks if b)

    def _safe(self, path: str) -> Path:
        p = Path(path)
        if not p.is_absolute():
            p = self.workspace / p
        return p.resolve()

    def _exec_req(self, path: str) -> str:
        p = self._safe(path)
        if not p.is_file():
            return f"[@req 文件不存在: {p}]"
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            return f"[@req 读取失败: {e}]"
        lines = text.splitlines()
        if len(lines) > self.MAX_FILE_LINES:
            text = "\n".join(lines[:self.MAX_FILE_LINES]) + f"\n... [仅显示前 {self.MAX_FILE_LINES} 行]"
        return f"### {p}\n```\n{text}\n```"

    def _exec_sym(self, name: str) -> str:
        if self.graph is None:
            return f"[@sym 未注入 codegraph，无法定位 {name}]"
        from .codegraph import search_symbols, get_symbol_source
        syms = search_symbols(self.graph, name)
        if not syms:
            return f"[@sym 未找到符号 {name}]"
        parts = []
        for s in syms[:5]:
            src = get_symbol_source(self.graph, s.name) or s.signature
            parts.append(f"### {s.name} ({s.file_path}:{s.line})\n```\n{src}\n```")
        return "\n\n".join(parts)

    def _exec_grep(self, pattern: str, glob: str = "") -> str:
        import subprocess
        cmd = ["grep", "-rn", "--exclude-dir=.git", pattern, str(self.workspace)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=15, cwd=str(self.workspace))
        except (subprocess.TimeoutExpired, OSError) as e:
            return f"[@grep 失败: {e}]"
        out = proc.stdout or ""
        if len(out) > 8000:
            out = out[:8000] + "\n... [结果截断]"
        return f"### grep {pattern}\n{out}"

    def _exec_ls(self, path: str) -> str:
        p = self._safe(path)
        if not p.is_dir():
            return f"[@ls 目录不存在: {p}]"
        try:
            entries = sorted(p.iterdir())
        except OSError as e:
            return f"[@ls 失败: {e}]"
        lines = [f"{e.name}{'/' if e.is_dir() else ''}" for e in entries[:100]]
        return f"### {p}\n" + "\n".join(lines)

    def _exec_tree(self) -> str:
        lines = []

        def walk(d: Path, prefix: str, depth: int):
            if depth > 2:
                return
            try:
                items = sorted(d.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
            except OSError:
                return
            for i, item in enumerate(items):
                if item.name.startswith("."):
                    continue
                last = i == len(items) - 1
                lines.append(prefix + ("└── " if last else "├── ") + item.name +
                             ("/" if item.is_dir() else ""))
                if item.is_dir():
                    walk(item, prefix + ("    " if last else "│   "), depth + 1)

        walk(self.workspace, "", 0)
        return "### 目录树\n" + "\n".join(lines[:200])
