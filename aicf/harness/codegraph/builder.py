# harness/codegraph/builder.py
# GraphBuilder — 扫描 Python 项目，从 AST 构建符号索引。

from __future__ import annotations

import ast
import os

from .symbol import CallGraph, Symbol


class GraphBuilder:
    def __init__(self, project_root: str, max_depth: int = -1):
        self.project_root = os.path.abspath(project_root)
        self.max_depth = max_depth

    def build(self) -> CallGraph:
        graph = CallGraph()
        for fpath in self._find_py_files():
            relpath = os.path.relpath(fpath, self.project_root)
            graph.files.add(relpath)
            self._extract_symbols(fpath, graph)
        self._resolve_calls(graph)
        return graph

    def _find_py_files(self) -> list[str]:
        results = []
        root_depth = self.project_root.rstrip(os.sep).count(os.sep)
        skip = {".git", "__pycache__", ".venv", "node_modules"}
        for root, dirs, files in os.walk(self.project_root):
            depth = root.rstrip(os.sep).count(os.sep) - root_depth
            if self.max_depth >= 0 and depth >= self.max_depth:
                dirs.clear()
            dirs[:] = [d for d in dirs if d not in skip]
            for f in files:
                if f.endswith(".py"):
                    results.append(os.path.join(root, f))
        return results

    def _extract_symbols(self, file_path: str, graph: CallGraph) -> None:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=file_path)
        except (SyntaxError, UnicodeDecodeError, OSError):
            return
        relpath = os.path.relpath(file_path, self.project_root)
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                self._add_class(node, relpath, graph)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._add_function(node, relpath, graph)

    def _add_class(self, node: ast.ClassDef, relpath: str, graph: CallGraph) -> None:
        bases = [b.id for b in node.bases if isinstance(b, ast.Name)]
        bases_str = f"({', '.join(bases)})" if bases else ""
        graph.symbols[node.name] = Symbol(
            name=node.name, kind="class", file_path=relpath, line=node.lineno,
            signature=f"class {node.name}{bases_str}:")
        for item in ast.iter_child_nodes(node):
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._add_method(item, node.name, relpath, graph)

    def _add_method(self, node, class_name: str, relpath: str, graph: CallGraph) -> None:
        args = self._format_args(node.args)
        returns = f" -> {self._format_expr(node.returns)}" if node.returns else ""
        full_name = f"{class_name}.{node.name}"
        sym = Symbol(
            name=full_name, kind="method", file_path=relpath, line=node.lineno,
            signature=f"    def {node.name}({args}){returns}:")
        self._extract_calls_from_body(node, sym)
        graph.symbols[full_name] = sym

    def _add_function(self, node, relpath: str, graph: CallGraph) -> None:
        args = self._format_args(node.args)
        returns = f" -> {self._format_expr(node.returns)}" if node.returns else ""
        sym = Symbol(
            name=node.name, kind="function", file_path=relpath, line=node.lineno,
            signature=f"def {node.name}({args}){returns}:")
        self._extract_calls_from_body(node, sym)
        graph.symbols[node.name] = sym

    def _extract_calls_from_body(self, node, sym: Symbol) -> None:
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                called = self._resolve_call_name(child.func)
                if called and called != sym.name and called not in sym.calls:
                    sym.calls.append(called)

    @staticmethod
    def _resolve_call_name(func: ast.expr) -> str | None:
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
        return None

    def _resolve_calls(self, graph: CallGraph) -> None:
        for name, sym in graph.symbols.items():
            for callee_name in sym.calls:
                callee = graph.symbols.get(callee_name)
                if callee and name not in callee.called_by:
                    callee.called_by.append(name)

    def _format_args(self, args: ast.arguments) -> str:
        parts = []
        for i, arg in enumerate(args.args):
            if i == 0 and arg.arg == "self":
                parts.append("self")
                continue
            a = arg.arg
            if arg.annotation:
                a += f": {self._format_expr(arg.annotation)}"
            parts.append(a)
        if args.vararg:
            va = f"*{args.vararg.arg}"
            if args.vararg.annotation:
                va += f": {self._format_expr(args.vararg.annotation)}"
            parts.append(va)
        if args.kwonlyargs:
            if not args.vararg:
                parts.append("*")
            for ka in args.kwonlyargs:
                k = ka.arg
                if ka.annotation:
                    k += f": {self._format_expr(ka.annotation)}"
                parts.append(k)
        if args.kwarg:
            kw = f"**{args.kwarg.arg}"
            if args.kwarg.annotation:
                kw += f": {self._format_expr(args.kwarg.annotation)}"
            parts.append(kw)
        return ", ".join(parts)

    @staticmethod
    def _format_expr(node) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return f"{GraphBuilder._format_expr(node.value)}.{node.attr}"
        if isinstance(node, ast.Subscript):
            return f"{GraphBuilder._format_expr(node.value)}[{GraphBuilder._format_expr(node.slice)}]"
        if isinstance(node, ast.Constant):
            return repr(node.value)
        if isinstance(node, ast.Call):
            return f"{GraphBuilder._format_expr(node.func)}(...)"
        return "..."
