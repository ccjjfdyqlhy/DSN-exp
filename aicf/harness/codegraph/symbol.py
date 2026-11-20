# harness/codegraph/symbol.py
# Symbol / CallGraph 数据结构。

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Symbol:
    name: str
    kind: str              # class | function | method | variable
    file_path: str
    line: int
    signature: str
    calls: list[str] = field(default_factory=list)
    called_by: list[str] = field(default_factory=list)

    def to_compact(self) -> str:
        return f"    {self.signature}  # {self.file_path}:{self.line}"

    def as_dict(self) -> dict:
        return {
            "name": self.name, "kind": self.kind, "file_path": self.file_path,
            "line": self.line, "signature": self.signature,
            "calls": list(self.calls), "called_by": list(self.called_by),
        }


@dataclass
class CallGraph:
    symbols: dict[str, Symbol] = field(default_factory=dict)
    files: set[str] = field(default_factory=set)

    def get(self, name: str) -> Symbol | None:
        return self.symbols.get(name)

    def search(self, query: str) -> list[Symbol]:
        q = query.lower()
        return [s for s in self.symbols.values()
                if q in s.name.lower() or q in s.signature.lower()]

    def get_callers(self, name: str, depth: int = 2) -> list[Symbol]:
        seen: set[str] = set()
        results: list[Symbol] = []

        def walk(n: str, d: int) -> None:
            if d <= 0 or n in seen:
                return
            seen.add(n)
            sym = self.symbols.get(n)
            if not sym:
                return
            for caller_name in sym.called_by:
                caller = self.symbols.get(caller_name)
                if caller and caller not in results:
                    results.append(caller)
                    walk(caller_name, d - 1)

        walk(name, depth)
        return results

    def get_callees(self, name: str, depth: int = 2) -> list[Symbol]:
        seen: set[str] = set()
        results: list[Symbol] = []

        def walk(n: str, d: int) -> None:
            if d <= 0 or n in seen:
                return
            seen.add(n)
            sym = self.symbols.get(n)
            if not sym:
                return
            for callee_name in sym.calls:
                callee = self.symbols.get(callee_name)
                if callee and callee not in results:
                    results.append(callee)
                    walk(callee_name, d - 1)

        walk(name, depth)
        return results

    def files_in_call_chain(self, name: str, depth: int = 2) -> set[str]:
        files = set()
        sym = self.symbols.get(name)
        if sym:
            files.add(sym.file_path)
        files.update(s.file_path for s in self.get_callers(name, depth))
        files.update(s.file_path for s in self.get_callees(name, depth))
        return files

    def to_compact_map(self) -> str:
        by_file: dict[str, list[Symbol]] = {}
        for sym in self.symbols.values():
            by_file.setdefault(sym.file_path, []).append(sym)
        lines = []
        for fpath in sorted(by_file.keys()):
            lines.append(f"{fpath}/")
            for sym in by_file[fpath]:
                lines.append(sym.to_compact())
        return "\n".join(lines)

    def total_symbols(self) -> int:
        return len(self.symbols)
