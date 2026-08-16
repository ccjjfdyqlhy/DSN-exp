# tools.py — Dekacode WebUI 的扩展工具集与技能加载器。
#
# 在 harness 标准工具之上补齐 coding agent 常用能力：
#   file.grep / file.glob / code.callers / code.callees / code.read_symbol
#   git.status / git.diff / git.commit
# 并支持从 skills 目录加载自定义技能模块。

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable, Optional

from harness.tools import ToolRegistry, tool_from_function


# ── 扩展工具 ──

def _safe_path(workspace: str, path: str) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = Path(workspace) / p
    return p.resolve()


def make_grep(workspace: str):
    def grep(pattern: str, path: str = ".", max_results: int = 50) -> str:
        """在项目中递归搜索文本，返回匹配行（最多 max_results 条）。"""
        root = _safe_path(workspace, path)
        lines: list[str] = []
        if not root.exists():
            return f"(路径不存在: {root})"
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "__pycache__"]
            for fname in filenames:
                if fname.startswith("."):
                    continue
                fp = Path(dirpath) / fname
                try:
                    text = fp.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                for i, line in enumerate(text.splitlines(), 1):
                    if pattern in line:
                        rel = fp.relative_to(workspace) if str(fp).startswith(workspace) else fp
                        lines.append(f"{rel}:{i}: {line.strip()[:160]}")
                        if len(lines) >= max_results:
                            return "\n".join(lines) or "(无匹配)"
        return "\n".join(lines) or "(无匹配)"
    return grep


def make_glob(workspace: str):
    def glob(pattern: str) -> str:
        """按 glob 模式列出项目内文件（如 **/*.py）。"""
        root = Path(workspace)
        matches = [str(p.relative_to(root)) for p in root.glob(pattern) if p.is_file()]
        return "\n".join(sorted(matches)[:500]) or "(无匹配)"
    return glob


def make_callers(workspace: str, graph: Any):
    def callers(symbol: str, depth: int = 2) -> str:
        """查询符号的调用者链。"""
        if graph is None:
            return "(codegraph 未注入)"
        from harness.codegraph import get_call_chain_text
        return get_call_chain_text(graph, symbol, depth) or f"(未找到 {symbol})"
    return callers


def make_read_symbol(workspace: str, graph: Any):
    def read_symbol(symbol: str) -> str:
        """读取符号定义源码。"""
        if graph is None:
            return "(codegraph 未注入)"
        from harness.codegraph import get_symbol_source
        return get_symbol_source(graph, symbol) or f"(未找到符号 {symbol})"
    return read_symbol


def make_git_status(workspace: str):
    def git_status() -> str:
        """显示工作区 Git 状态摘要。"""
        proc = subprocess.run(
            "git status --short", shell=True, capture_output=True, text=True,
            cwd=workspace, timeout=15,
        )
        return (proc.stdout or proc.stderr).strip() or "(无改动)"
    return git_status


def make_git_diff(workspace: str):
    def git_diff(path: str = "") -> str:
        """显示工作区 diff（可指定文件）。"""
        cmd = "git diff --stat && git diff -- " + (path or "")
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                              cwd=workspace, timeout=20)
        return (proc.stdout or proc.stderr).strip() or "(无改动)"
    return git_diff


def make_git_commit(workspace: str):
    def git_commit(message: str) -> str:
        """提交当前所有改动。"""
        proc = subprocess.run(
            f'git commit -am {json.dumps(message)}', shell=True, capture_output=True,
            text=True, cwd=workspace, timeout=20,
        )
        return (proc.stdout or proc.stderr).strip()
    return git_commit


def make_code_review(workspace: str):
    def code_review(path: str) -> str:
        """对 Python 文件做静态审查：语法、长行、TODO/FIXME、未使用导入（粗略）。"""
        import ast as _ast
        p = _safe_path(workspace, path)
        if not p.is_file():
            return f"(文件不存在: {p})"
        try:
            source = p.read_text(encoding="utf-8")
        except OSError as e:
            return f"(读取失败: {e})"
        issues: list[str] = []
        try:
            tree = _ast.parse(source, filename=str(p))
        except SyntaxError as e:
            return f"语法错误 行{e.lineno} 列{e.offset}: {e.msg}"
        classes = sum(isinstance(n, _ast.ClassDef) for n in _ast.walk(tree))
        funcs = sum(isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef)) for n in _ast.walk(tree))
        for i, line in enumerate(source.splitlines(), 1):
            if len(line) > 120:
                issues.append(f"行 {i}: 长度 {len(line)} > 120")
            low = line.lower()
            if "todo" in low or "fixme" in low or "xxx" in low:
                issues.append(f"行 {i}: 疑似 TODO/FIXME/XXX")
        imported: set[str] = set()
        used: set[str] = set()
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Import):
                for alias in node.names:
                    imported.add((alias.asname or alias.name).split(".")[0])
            elif isinstance(node, _ast.ImportFrom):
                for alias in node.names:
                    if alias.name != "*":
                        imported.add(alias.asname or alias.name)
            if isinstance(node, _ast.Name):
                used.add(node.id)
        unused = sorted(imported - used)
        report = [f"文件: {p}", f"类: {classes}, 函数: {funcs}"]
        if issues:
            report.append("发现:")
            report.extend(f"  - {x}" for x in issues[:30])
        else:
            report.append("未发现明显长行/TODO 问题")
        if unused:
            report.append(f"可能未使用的导入: {', '.join(unused[:20])}")
        return "\n".join(report)
    return code_review


def make_project_deps(workspace: str):
    def project_deps(path: str = ".") -> str:
        """统计项目内 Python import 依赖（模块名 → 出现次数）。"""
        import ast as _ast
        root = _safe_path(workspace, path)
        if not root.is_dir():
            return f"(目录不存在: {root})"
        counter: dict[str, int] = {}
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d != "__pycache__"]
            for fname in filenames:
                if not fname.endswith(".py"):
                    continue
                fp = Path(dirpath) / fname
                try:
                    tree = _ast.parse(fp.read_text(encoding="utf-8"), filename=str(fp))
                except (SyntaxError, UnicodeDecodeError, OSError):
                    continue
                for node in _ast.walk(tree):
                    if isinstance(node, _ast.Import):
                        for alias in node.names:
                            mod = alias.name.split(".")[0]
                            counter[mod] = counter.get(mod, 0) + 1
                    elif isinstance(node, _ast.ImportFrom) and node.module:
                        mod = node.module.split(".")[0]
                        counter[mod] = counter.get(mod, 0) + 1
        if not counter:
            return "(未发现 import)"
        lines = sorted(counter.items(), key=lambda x: -x[1])
        return "\n".join(f"  {mod}: {cnt}" for mod, cnt in lines[:40])
    return project_deps


def install_extra_tools(
    registry: ToolRegistry,
    *,
    workspace: str,
    graph: Any = None,
) -> list[str]:
    """注册扩展工具，返回已注册名称列表。"""
    funcs: list[tuple[str, str, Callable, dict]] = [
        ("file.grep", "递归搜索文本，返回 file:line: content", make_grep(workspace),
         {"type": "object", "properties": {
             "pattern": {"type": "string"},
             "path": {"type": "string", "default": "."},
             "max_results": {"type": "integer", "default": 50}},
          "required": ["pattern"]}),
        ("file.glob", "按 glob 模式列出文件", make_glob(workspace),
         {"type": "object", "properties": {"pattern": {"type": "string"}},
          "required": ["pattern"]}),
        ("code.callers", "查询符号调用者链", make_callers(workspace, graph),
         {"type": "object", "properties": {
             "symbol": {"type": "string"}, "depth": {"type": "integer", "default": 2}},
          "required": ["symbol"]}),
        ("code.read_symbol", "读取符号定义源码", make_read_symbol(workspace, graph),
         {"type": "object", "properties": {"symbol": {"type": "string"}},
          "required": ["symbol"]}),
        ("git.status", "查看 Git 工作区状态", make_git_status(workspace),
         {"type": "object", "properties": {}}),
        ("git.diff", "查看 Git diff", make_git_diff(workspace),
         {"type": "object", "properties": {"path": {"type": "string"}}}),
        ("git.commit", "提交当前改动", make_git_commit(workspace),
         {"type": "object", "properties": {"message": {"type": "string"}},
          "required": ["message"]}),
        ("code.review", "对 Python 文件做静态审查（语法/长行/TODO/未使用导入）",
         make_code_review(workspace),
         {"type": "object", "properties": {"path": {"type": "string"}},
          "required": ["path"]}),
        ("project.deps", "统计项目内 Python import 依赖分布",
         make_project_deps(workspace),
         {"type": "object", "properties": {"path": {"type": "string", "default": "."}}}),
    ]
    registered: list[str] = []
    for name, desc, handler, params in funcs:
        try:
            registry.register(tool_from_function(handler, namespace=""))
            # tool_from_function 会生成 name；这里若名字不一致则手动覆盖
            if not registry.has(name):
                # 用 function.__name__ 注册的名字可能不同，手动按 name 注册
                registry.unregister(handler.__name__) if registry.has(handler.__name__) else None
                registry.register_tool(name, desc, handler, params)
            registered.append(name)
        except KeyError:
            # 已存在同名工具，跳过
            pass
    return registered


# ── 技能加载 ──

def load_skills_from_dir(
    registry: ToolRegistry,
    skills_dir: str,
    *,
    deps: Any = None,
) -> dict[str, Any]:
    """扫描技能目录，加载自定义工具。

    约定：
      - 每个 .py 文件是一个技能模块；
      - 模块可定义 `def register(registry, deps)` 主动注册；
      - 也可定义 `TOOLS = [func1, func2, ...]`，自动注册；
      - 也可定义 `SKILL = {"name": ..., "description": ..., "handler": ..., "parameters": ...}`。
    """
    root = Path(skills_dir)
    result: dict[str, Any] = {"loaded": [], "errors": []}
    if not root.is_dir():
        result["errors"].append(f"技能目录不存在: {root}")
        return result

    for py in sorted(root.glob("*.py")):
        if py.name.startswith("_"):
            continue
        mod_name = f"dekacode_skill_{py.stem}"
        try:
            spec = importlib.util.spec_from_file_location(mod_name, py)
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            registered = 0

            if hasattr(mod, "register") and callable(mod.register):
                mod.register(registry, deps)
                registered += 1

            for fn in getattr(mod, "TOOLS", []) or []:
                if callable(fn):
                    try:
                        registry.register(tool_from_function(fn, namespace="skill"))
                        registered += 1
                    except (KeyError, TypeError):
                        result["errors"].append(f"{py.name}: 工具注册失败 {fn.__name__}")

            skill = getattr(mod, "SKILL", None)
            if isinstance(skill, dict):
                name = skill.get("name") or py.stem
                registry.register_tool(
                    name,
                    skill.get("description", ""),
                    skill.get("handler"),
                    skill.get("parameters"),
                )
                registered += 1

            if registered:
                result["loaded"].append({"module": py.name, "tools": registered})
        except Exception as e:  # noqa: BLE001
            result["errors"].append(f"{py.name}: {e}")
    return result


__all__ = ["install_extra_tools", "load_skills_from_dir"]
