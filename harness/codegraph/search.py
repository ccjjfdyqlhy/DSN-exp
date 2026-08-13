# harness/codegraph/search.py
# 调用图查询助手 — 搜索符号、调用链文本、源码提取。

from __future__ import annotations

import os

from .symbol import CallGraph, Symbol


def search_symbols(graph: CallGraph, query: str) -> list[Symbol]:
    return graph.search(query)


def find_callers(graph: CallGraph, symbol_name: str, depth: int = 2) -> list[Symbol]:
    return graph.get_callers(symbol_name, depth)


def find_callees(graph: CallGraph, symbol_name: str, depth: int = 2) -> list[Symbol]:
    return graph.get_callees(symbol_name, depth)


def get_call_chain_text(graph: CallGraph, symbol_name: str, depth: int = 2) -> str:
    sym = graph.get(symbol_name)
    if not sym:
        return f"Symbol '{symbol_name}' not found"
    lines = [f"# {sym.signature}  ({sym.file_path}:{sym.line})"]
    callers = find_callers(graph, symbol_name, depth)
    if callers:
        lines.append(f"# Called by ({len(callers)}):")
        for c in callers:
            lines.append(f"#   {c.signature}  ({c.file_path}:{c.line})")
    callees = find_callees(graph, symbol_name, depth)
    if callees:
        lines.append(f"# Calls ({len(callees)}):")
        for c in callees:
            lines.append(f"#   {c.signature}  ({c.file_path}:{c.line})")
    return "\n".join(lines)


def get_symbol_source(graph: CallGraph, symbol_name: str) -> str | None:
    sym = graph.get(symbol_name)
    if not sym:
        return None
    fpath = sym.file_path
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except (FileNotFoundError, IOError, OSError):
        fpath_abs = None
        for gf in graph.files:
            if gf.endswith(sym.file_path) or sym.file_path.endswith(gf):
                fpath_abs = gf
                break
        if not fpath_abs:
            return None
        try:
            with open(fpath_abs, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except (FileNotFoundError, IOError, OSError):
            return None
    start = sym.line - 1
    end = min(start + 30, len(lines))
    source = "".join(lines[start:end])
    return f"# {sym.signature}  ({sym.file_path}:{sym.line})\n{source}"
