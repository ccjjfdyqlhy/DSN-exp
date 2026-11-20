# harness/codegraph/imports.py
# ImportResolver — 导入解析（场景无关）。
#
# 从 dekacode code_graph/imports.py 提炼：给定文件，AST 解析其导入，
# 返回每层 import 的签名（用于把"依赖的接口"注入上下文，而非整个文件）。

from __future__ import annotations

import ast
import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class SymbolSignature:
    name: str
    kind: str = ""
    signature: str = ""
    file_path: str = ""
    line: int = 0

    def __str__(self) -> str:
        return self.signature or self.name

    def to_prompt_block(self) -> str:
        return f"  {self.signature or self.name}  # {self.file_path}:{self.line}"


class ImportResolver:
    """解析文件的导入依赖，返回符号签名（每文件最多 MAX_SIGS_PER_FILE 条）。"""

    MAX_SIGS_PER_FILE = 15

    def __init__(self, project_root: Optional[str] = None):
        self.project_root = os.path.abspath(project_root or os.getcwd())
        self._signature_cache: dict[str, list[SymbolSignature]] = {}

    def resolve(self, file_path: str) -> list[SymbolSignature]:
        abspath = os.path.abspath(file_path)
        if abspath in self._signature_cache:
            return self._signature_cache[abspath]

        try:
            with open(abspath, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=abspath)
        except (SyntaxError, FileNotFoundError, UnicodeDecodeError):
            self._signature_cache[abspath] = []
            return []

        # 收集本文件的导入
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    imports.append(f"{module}.{alias.name}" if module else alias.name)

        result: list[SymbolSignature] = []
        seen: set[str] = set()
        for imp in imports:
            # 解析到具体文件（简单映射：包名 → 路径）
            resolved = self._resolve_import(imp)
            if resolved is None or resolved in seen:
                continue
            seen.add(resolved)
            sigs = self._extract_signatures(resolved)
            result.extend(sigs)
            if len(result) >= self.MAX_SIGS_PER_FILE:
                break
        self._signature_cache[abspath] = result
        return result

    def _resolve_import(self, imp: str) -> Optional[str]:
        """把 import 路径映射到项目内文件（仅解析本地模块）。"""
        parts = imp.split(".")
        # 尝试 模块.py / 包/__init__.py
        for i in range(len(parts), 0, -1):
            rel = os.path.join(*parts[:i])
            for candidate in (rel + ".py", os.path.join(rel, "__init__.py")):
                p = os.path.join(self.project_root, candidate)
                if os.path.isfile(p):
                    return p
        return None

    def _extract_signatures(self, file_path: str) -> list[SymbolSignature]:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                tree = ast.parse(f.read(), filename=file_path)
        except (SyntaxError, FileNotFoundError, UnicodeDecodeError):
            return []
        sigs: list[SymbolSignature] = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = ", ".join(a.arg for a in node.args.args[:5])
                sigs.append(SymbolSignature(
                    name=node.name, kind="function",
                    signature=f"def {node.name}({args}...)",
                    file_path=file_path, line=node.lineno))
            elif isinstance(node, ast.ClassDef):
                sigs.append(SymbolSignature(
                    name=node.name, kind="class",
                    signature=f"class {node.name}",
                    file_path=file_path, line=node.lineno))
        return sigs

    def prompt_block(self, file_path: str) -> str:
        sigs = self.resolve(file_path)
        if not sigs:
            return ""
        lines = [f"# {os.path.relpath(file_path, self.project_root)} 依赖的接口:"]
        lines.extend(s.to_prompt_block() for s in sigs[:self.MAX_SIGS_PER_FILE])
        return "\n".join(lines)
