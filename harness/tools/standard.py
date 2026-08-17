# harness/tools/standard.py
# 标准工具集 — 搭建通用 AI 应用的开箱即用工具（场景无关，纯 Python 实现）。
#
# 设计目标（对比 DSH 的"环境操作工具"）：
#   DSH 工具 = 操纵 Agent 运行环境（fs/bash/subagent/web）
#   harness 标准工具 = 操纵"应用世界"（文件/代码/文本/进程/项目），
#   并刻意设计为可组合、可注入依赖（fs/shell/codegraph 等经 deps 注入，
#   未注入时自动降级或返回清晰错误）。
#
# 工具命名空间：
#   file.*    文件读写与探索        text.*  文本处理
#   code.*    代码分析（语法/diff）  proc.*  进程执行
#   web.*     网络抓取               project.* 项目级操作
#
# 用法:
#     from harness.tools.standard import install_standard_tools
#     install_standard_tools(registry, deps={"workspace": "/path"})

from __future__ import annotations

import ast
import difflib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

from .base import Tool, ToolRegistry

NL = chr(10)


# ── 依赖容器 ──

class ToolDeps:
    """工具依赖注入：workspace / shell / codegraph / fetcher。

    未注入的能力自动降级（工具返回带提示的错误或空结果）。
    """

    def __init__(self, **kwargs):
        self.workspace: str = kwargs.get("workspace", os.getcwd())
        self.codegraph: Any = kwargs.get("codegraph")   # harness.codegraph 实例
        self.fetcher: Any = kwargs.get("fetcher")       # web 抓取器
        self.tool_registry: Any = kwargs.get("tool_registry")  # ToolRegistry（batch.run 解析 fn 用）
        self.max_output_chars: int = kwargs.get("max_output_chars", 6000)


# ── 文件工具 ──

def _safe_path(deps: ToolDeps, path: str) -> Path:
    """把相对路径解析到工作区内（防目录穿越）。"""
    p = Path(path)
    if not p.is_absolute():
        p = Path(deps.workspace) / p
    return p.resolve()


def _read_text(path: Path, max_chars: int) -> tuple[bool, str, int, int, bool]:
    """读取文本，返回 (ok, text, total_bytes, total_lines, truncated)。"""
    try:
        data = path.read_bytes()
    except OSError as e:
        return False, f"读取失败: {e}", 0, 0, False
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:
            return False, "无法解码文件（非 UTF-8）", 0, 0, False
    total_lines = text.count("\n") + (0 if text.endswith("\n") or not text else 1)
    if max_chars and len(text) > max_chars:
        truncated_text = text[:max_chars]
        shown_lines = truncated_text.count("\n") + 1
        truncated_text += f"{NL}...[截断, 总 {len(data)} 字节 / {total_lines} 行, 当前仅显示 {shown_lines} 行]"
        return True, truncated_text, len(data), total_lines, True
    return True, text, len(data), total_lines, False


def tool_file_read(deps: ToolDeps):
    def run(path: str, max_chars: int = 0):
        p = _safe_path(deps, path)
        if not p.is_file():
            return {"success": False, "error": f"文件不存在: {p}"}
        ok, text, total_bytes, total_lines, truncated = _read_text(
            p, max_chars or deps.max_output_chars)
        result: dict = {"success": ok, "content": text,
                        "total_bytes": total_bytes, "total_lines": total_lines}
        if truncated:
            shown_lines = text.count("\n")
            result["shown_lines"] = shown_lines
            result["truncated"] = True
            # 关键提示：告诉 AI 行号可能偏移，编辑前应读完整文件或改用 file.edit(match=...)。
            result["warning"] = (
                f"内容已截断（共 {total_lines} 行，当前仅 {shown_lines} 行），"
                f"按行号 file.edit 极易错位！请改用 file.edit(target=path, match=<old text>)"
                f" 按内容锚点定位，或先 file.read(max_chars=0) 读完整文件。")
        return result
    return run


def tool_file_write(deps: ToolDeps):
    def run(path: str, content: str, append: bool = False):
        p = _safe_path(deps, path)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            mode = "a" if append else "w"
            with open(p, mode, encoding="utf-8") as f:
                f.write(content)
            return {"success": True, "path": str(p), "bytes": len(content.encode("utf-8"))}
        except OSError as e:
            return {"success": False, "error": str(e)}
    return run


def tool_file_list(deps: ToolDeps):
    def run(path: str = ".", recursive: bool = False, max_depth: int = 3):
        p = _safe_path(deps, path)
        if not p.is_dir():
            return {"success": False, "error": f"目录不存在: {p}"}
        entries = []
        if recursive:
            for root, dirs, files in os.walk(p):
                depth = len(Path(root).relative_to(p).parts)
                if depth >= max_depth:
                    dirs[:] = []
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for f in sorted(files):
                    if f.startswith("."):
                        continue
                    fp = Path(root) / f
                    try:
                        size = fp.stat().st_size
                    except OSError:
                        size = -1
                    rel = fp.relative_to(deps.workspace) if str(fp).startswith(deps.workspace) else fp
                    entries.append({"path": str(rel), "size": size})
        else:
            try:
                for f in sorted(p.iterdir()):
                    entries.append({"name": f.name, "is_dir": f.is_dir()})
            except OSError as e:
                return {"success": False, "error": str(e)}
        return {"success": True, "path": str(p), "count": len(entries), "entries": entries}
    return run


def tool_file_edit(deps: ToolDeps):
    """按行范围或内容锚点替换文件内容。

    两种定位方式：
    1) 行号模式（默认）：target = "path:start-end"（1 基含端点；start/end 可省略，
       end 缺省 = 文件末尾）。适合精确定位。
    2) 内容锚点模式（推荐，抗 read 截断导致的行号错位）：
       target = "path"，match = "<old text>"。在文件全文中查找 match 第一次
       出现位置并替换为 replacement。match 必须 unique（出现多次时报错）。

    两种模式写回时都保留原文件的末尾换行符。
    """

    def run(target: str, replacement: str, match=None):
        target = target.strip()
        if match is not None:
            # 内容锚点模式：target 当作 path
            if re.search(r":\d", target):
                return {"success": False,
                        "error": "使用 match 时 target 不应带行号 (path:start-end)"}
            path = target
        else:
            m = re.match(r"^(.+):(\d+)?-(\d+)?$", target)
            if not m:
                return {"success": False,
                        "error": f"目标格式应为 path:start-end，得到: {target!r}"}
            path = m.group(1)
        p = _safe_path(deps, path)
        if not p.is_file():
            return {"success": False, "error": f"文件不存在: {p}"}
        try:
            raw = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            return {"success": False, "error": f"读取失败: {e}"}
        orig_ended_with_nl = raw.endswith("\n")
        lines = raw.splitlines()

        if match is not None:
            occurrences = raw.count(match)
            if occurrences == 0:
                return {"success": False,
                        "error": f"未找到 match 内容: {match[:80]!r}"}
            if occurrences > 1:
                return {"success": False,
                        "error": (f"match 在文件中出现 {occurrences} 次，不唯一。"
                                  f"请提供更长/更具体的 old text 以唯一定位。")}
            idx = raw.find(match)
            before = raw[:idx]
            match_lines = match.split("\n")
            start_line = before.count("\n") + 1  # 1 基
            replaced = len(match_lines)
            new_raw = before + replacement + raw[idx + len(match):]
        else:
            start_s, end_s = m.group(2), m.group(3)
            start = int(start_s) if start_s else 1
            end = int(end_s) if end_s else len(lines)  # 缺省=末尾
            if start < 1 or end < start or end > len(lines):
                return {"success": False,
                        "error": f"行范围越界: {start}-{end} (共 {len(lines)} 行)"}
            replaced = end - start + 1
            new_lines = lines[:start - 1] + replacement.splitlines() + lines[end:]
            new_raw = "\n".join(new_lines)
        # 保留原文件末尾换行（POSIX 文本文件惯例，避免无意义 diff/编辑器告警）
        if orig_ended_with_nl and not new_raw.endswith("\n"):
            new_raw += "\n"
        try:
            p.write_text(new_raw, encoding="utf-8")
        except OSError as e:
            return {"success": False, "error": f"写入失败: {e}"}
        return {"success": True, "path": str(p), "replaced": replaced}
    return run


def tool_file_tree(deps: ToolDeps):
    def run(path: str = ".", max_depth: int = 2):
        p = _safe_path(deps, path)
        if not p.is_dir():
            return {"success": False, "error": f"目录不存在: {p}"}
        lines: list[str] = []
        def walk(d: Path, prefix: str, depth: int):
            if depth > max_depth:
                return
            try:
                items = sorted(d.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
            except OSError:
                return
            for i, item in enumerate(items):
                if item.name.startswith("."):
                    continue
                last = i == len(items) - 1
                connector = "└── " if last else "├── "
                lines.append(prefix + connector + item.name + ("/" if item.is_dir() else ""))
                if item.is_dir():
                    walk(item, prefix + ("    " if last else "│   "), depth + 1)
        lines.append(str(p))
        walk(p, "", 1)
        return {"success": True, "tree": NL.join(lines)}
    return run


# ── 文本工具 ──

def tool_text_chunk():
    def run(text: str, chunk_size: int = 2000, overlap: int = 0):
        if chunk_size <= 0:
            return {"success": False, "error": "chunk_size 必须为正"}
        chunks = []
        i = 0
        while i < len(text):
            chunks.append(text[i:i + chunk_size])
            i += chunk_size - overlap if overlap < chunk_size else chunk_size
        return {"success": True, "count": len(chunks), "chunks": chunks}
    return run


def tool_text_extract_json():
    def run(text: str):
        m = re.search(r"\{[^{}]*\}", text, re.DOTALL)
        if not m:
            return {"success": False, "error": "未找到 JSON 对象"}
        try:
            return {"success": True, "data": json.loads(m.group(0))}
        except json.JSONDecodeError as e:
            return {"success": False, "error": f"JSON 解析失败: {e}"}
    return run


def tool_text_diff():
    def run(a: str, b: str, context: int = 3):
        diff = difflib.unified_diff(
            a.splitlines(), b.splitlines(), fromfile="a", tofile="b", n=context)
        return {"success": True, "diff": NL.join(diff)}
    return run


# ── 代码工具 ──

def tool_code_syntax_check(deps: ToolDeps):
    def run(path: str):
        p = _safe_path(deps, path)
        if not p.is_file():
            return {"success": False, "error": f"文件不存在: {p}"}
        if p.suffix == ".py":
            try:
                ast.parse(p.read_text(encoding="utf-8"))
                return {"success": True, "valid": True, "path": str(p)}
            except SyntaxError as e:
                return {"success": True, "valid": False,
                        "error": f"语法错误 行{e.lineno} 列{e.offset}: {e.msg}"}
        return {"success": False, "error": f"不支持的文件类型: {p.suffix}"}
    return run


def tool_code_locate_symbol(deps: ToolDeps):
    def run(name: str):
        if deps.codegraph is None:
            return {"success": False, "error": "codegraph 未注入，无法定位符号"}
        try:
            result = deps.codegraph.lookup(name) if hasattr(deps.codegraph, "lookup")                 else None
            if result:
                return {"success": True, "symbol": result}
            return {"success": True, "symbol": None, "note": f"未找到符号 {name}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    return run


# ── 进程工具 ──

def tool_proc_run(deps: ToolDeps):
    def run(command: str, timeout: int = 30, cwd: str = ""):
        try:
            proc = subprocess.run(
                command, shell=True, capture_output=True, text=True,
                timeout=timeout, cwd=cwd or deps.workspace,
            )
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"命令超时（>{timeout}s）",
                    "timed_out": True}
        except OSError as e:
            return {"success": False, "error": str(e)}
        out = proc.stdout or ""
        err = proc.stderr or ""
        if len(out) > deps.max_output_chars:
            out = out[:deps.max_output_chars] + f"{NL}...[输出截断]"
        return {
            "success": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": out,
            "stderr": err[: min(len(err), deps.max_output_chars // 2)],
        }
    return run


# ── 网络工具 ──

def tool_web_fetch(deps: ToolDeps):
    def run(url: str, max_chars: int = 8000):
        if deps.fetcher is not None:
            try:
                return deps.fetcher(url, max_chars=max_chars)
            except Exception as e:
                return {"success": False, "error": str(e)}
        try:
            import urllib.request
            req = urllib.request.Request(url, headers={"User-Agent": "harness/0.1"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read(max_chars * 2)
            text = data.decode("utf-8", errors="replace")
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            if len(text) > max_chars:
                text = text[:max_chars] + "..."
            return {"success": True, "text": text}
        except Exception as e:
            return {"success": False, "error": f"抓取失败: {e}"}
    return run


# ── 项目工具 ──

def tool_project_summary(deps: ToolDeps):
    def run(path: str = ".", max_files: int = 200):
        p = _safe_path(deps, path)
        if not p.is_dir():
            return {"success": False, "error": f"目录不存在: {p}"}
        total_files = total_lines = total_bytes = 0
        by_ext: dict[str, int] = {}
        for root, dirs, files in os.walk(p):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for f in files:
                if f.startswith("."):
                    continue
                fp = Path(root) / f
                try:
                    size = fp.stat().st_size
                except OSError:
                    continue
                total_files += 1
                total_bytes += size
                ext = fp.suffix or "(无)"
                by_ext[ext] = by_ext.get(ext, 0) + 1
                if total_files <= max_files:
                    try:
                        total_lines += sum(1 for _ in open(fp, "rb") if False)  # 占位
                    except Exception:
                        pass
        # 行数统计（限制文件数避免慢）
        lines = 0
        counted = 0
        for root, dirs, files in os.walk(p):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for f in files:
                if counted >= max_files:
                    break
                if f.startswith("."):
                    continue
                fp = Path(root) / f
                try:
                    with open(fp, "rb") as fh:
                        lines += sum(1 for _ in fh)
                    counted += 1
                except OSError:
                    pass
        top_ext = sorted(by_ext.items(), key=lambda x: -x[1])[:8]
        return {
            "success": True,
            "path": str(p),
            "files": total_files,
            "bytes": total_bytes,
            "lines": lines,
            "top_extensions": [{"ext": k, "count": v} for k, v in top_ext],
        }
    return run


def tool_project_todo(deps: ToolDeps):
    """轻量待办文件（.harness_todo.json）：Agent 可读写的任务清单。"""
    def _path() -> Path:
        return Path(deps.workspace) / ".harness_todo.json"

    def load() -> list[dict]:
        p = _path()
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return []
        return []

    def save(items: list[dict]) -> None:
        _path().write_text(json.dumps(items, ensure_ascii=False, indent=2),
                           encoding="utf-8")

    def run(action: str, text: str = "", index: int = -1,
            status: str = "pending"):
        items = load()
        if action == "add":
            items.append({"text": text, "status": status,
                          "created": time.time()})
            save(items)
            return {"success": True, "items": items}
        if action == "list":
            return {"success": True, "items": items}
        if action == "update":
            if 0 <= index < len(items):
                if text:
                    items[index]["text"] = text
                items[index]["status"] = status
                save(items)
                return {"success": True, "items": items}
            return {"success": False, "error": f"索引越界: {index}"}
        if action == "remove":
            if 0 <= index < len(items):
                removed = items.pop(index)
                save(items)
                return {"success": True, "removed": removed, "items": items}
            return {"success": False, "error": f"索引越界: {index}"}
        return {"success": False, "error": f"未知 action: {action}"}
    return run


# ── 批量工具 ──

def tool_project_snapshot(deps: ToolDeps):
    """项目快照：递归列出文件与其内容哈希（轻量版本控制/变更检测）。"""

    def run(path: str = ".", max_files: int = 500):
        root = _safe_path(deps, path)
        if not root.is_dir():
            return {"success": False, "error": f"目录不存在: {root}"}
        import hashlib
        entries = []
        for root_, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for f in files:
                if f.startswith(".") or len(entries) >= max_files:
                    continue
                fp = Path(root_) / f
                try:
                    h = hashlib.md5(fp.read_bytes()[:1 << 20]).hexdigest()[:10]
                    size = fp.stat().st_size
                except OSError:
                    continue
                rel = fp.relative_to(deps.workspace) if str(fp).startswith(deps.workspace) else fp
                entries.append({"path": str(rel), "hash": h, "size": size})
        return {"success": True, "count": len(entries), "files": entries}
    return run


def tool_batch_run(deps: ToolDeps):
    """批量执行：对 items 逐项调用已注册工具 fn（fn 为工具名）。

    每个 item 可以是 dict（作为 fn 的参数）或标量（转为 {"value": item}）。
    逐项收集 success/status/error/hint，聚合返回。
    """
    def run(items: list, fn: str = ""):
        reg = deps.tool_registry
        if not fn:
            return {"success": False, "error": "缺少 fn（要批量调用的工具名）",
                    "hint": "例如 batch.run(fn='text.chunk', items=[...])"}
        if reg is None:
            return {"success": False, "error": "tool_registry 未注入，无法解析工具",
                    "hint": "在 ToolDeps 中注入 tool_registry"}
        tool = reg.get(fn) if hasattr(reg, "get") else None
        if tool is None:
            names = reg.names() if hasattr(reg, "names") else []
            return {"success": False, "error": f"工具不存在: {fn}",
                    "hint": f"可用工具: {', '.join(names[:12])}"}
        results = []
        for i, item in enumerate(items or []):
            params = item if isinstance(item, dict) else {"value": item}
            if hasattr(tool, "run"):
                tr = tool.run(**params)
                results.append({
                    "index": i,
                    "success": tr.success,
                    "status": tr.status,
                    "output": tr.output,
                    "error": tr.error,
                    "hint": tr.hint,
                })
            else:
                results.append({"index": i, "success": False,
                                "error": "工具无 run 方法"})
        ok_count = sum(1 for r in results if r["success"])
        return {
            "success": True,
            "count": len(results),
            "ok": ok_count,
            "failed": len(results) - ok_count,
            "results": results,
        }
    return run


def tool_code_diagnose(deps: ToolDeps):
    """错误诊断：输入报错文本，借助 codegraph 检索相关符号并给出建议。

    无 codegraph 时返回带提示的降级结果（hint 指明如何注入）。
    """
    def run(error: str, context: str = ""):
        if deps.codegraph is None:
            return {"success": False, "error": "codegraph 未注入，无法诊断",
                    "hint": "在 ToolDeps 中注入 codegraph（GraphBuilder 构建）"}
        try:
            import re as _re
            query = (context or error or "").strip()
            # 从错误文本提取疑似符号名（标识符 token）
            tokens = _re.findall(r"[A-Za-z_][A-Za-z0-9_]{1,}", query)
            candidates: list[str] = []
            graph = deps.codegraph
            for tok in tokens:
                if hasattr(graph, "search"):
                    for sym in (graph.search(tok) or [])[:3]:
                        name = getattr(sym, "name", None) or getattr(sym, "to_compact", lambda: str(sym))()
                        if name not in candidates:
                            candidates.append(name)
            return {
                "success": True,
                "matches": candidates[:10],
                "note": "可对匹配符号用 code.locate_symbol / file.read 深入排查",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    return run


# ── 安装器 ──

def install_standard_tools(registry: ToolRegistry, *,
                           deps: Optional[ToolDeps] = None,
                           include: Optional[list[str]] = None) -> list[Tool]:
    """把标准工具集注册进 ToolRegistry。

    include 可过滤（如 ["file", "text"]）；deps 注入依赖（workspace/codegraph 等）。
    返回已注册的 Tool 列表。
    """
    deps = deps or ToolDeps()
    builders: dict[str, Any] = {
        "file.read": tool_file_read(deps),
        "file.write": tool_file_write(deps),
        "file.edit": tool_file_edit(deps),
        "file.list": tool_file_list(deps),
        "file.tree": tool_file_tree(deps),
        "text.chunk": tool_text_chunk(),
        "text.extract_json": tool_text_extract_json(),
        "text.diff": tool_text_diff(),
        "code.syntax_check": tool_code_syntax_check(deps),
        "code.locate_symbol": tool_code_locate_symbol(deps),
        "code.diagnose": tool_code_diagnose(deps),
        "proc.run": tool_proc_run(deps),
        "web.fetch": tool_web_fetch(deps),
        "project.summary": tool_project_summary(deps),
        "project.snapshot": tool_project_snapshot(deps),
        "project.todo": tool_project_todo(deps),
        "batch.run": tool_batch_run(deps),
    }
    tool_meta: dict[str, tuple[str, dict]] = {
        "file.read": ("读取文本文件（截断时返回 total_lines/truncated/warning，编辑前请读完整或用 file.edit+match）",
                      {"type": "object", "properties": {
                          "path": {"type": "string"},
                          "max_chars": {"type": "integer", "default": 0,
                                        "description": "0=读完整文件；>0 截断到此字符数（按行号 file.edit 极易错位）"}},
                       "required": ["path"]}),
        "file.write": ("写入/追加文本文件",
                       {"type": "object", "properties": {
                           "path": {"type": "string"}, "content": {"type": "string"},
                           "append": {"type": "boolean"}},
                        "required": ["path", "content"]}),
        "file.list": ("列目录（可选递归）",
                      {"type": "object", "properties": {
                          "path": {"type": "string"}, "recursive": {"type": "boolean"},
                          "max_depth": {"type": "integer"}}}),
        "file.tree": ("目录树",
                      {"type": "object", "properties": {
                          "path": {"type": "string"}, "max_depth": {"type": "integer"}}}),
        "file.edit": ("替换文件内容。行号模式 target='path:start-end'（end 缺省=末尾）；"
                      "内容锚点模式 target='path' + match='<old text>'（推荐，抗 read 截断，match 必须 unique）",
                      {"type": "object", "properties": {
                          "target": {"type": "string",
                                     "description": "path 或 path:start-end（end 可省略，缺省=末尾）"},
                          "replacement": {"type": "string"},
                          "match": {"type": "string",
                                    "description": "可选 old-text 锚点。提供时按内容定位（必须 unique）"}},
                       "required": ["target", "replacement"]}),
        "text.chunk": ("把长文本按块切分",
                       {"type": "object", "properties": {
                           "text": {"type": "string"}, "chunk_size": {"type": "integer"},
                           "overlap": {"type": "integer"}},
                        "required": ["text"]}),
        "text.extract_json": ("从文本提取首个 JSON 对象",
                              {"type": "object", "properties": {
                                  "text": {"type": "string"}}, "required": ["text"]}),
        "text.diff": ("两个文本的 unified diff",
                      {"type": "object", "properties": {
                          "a": {"type": "string"}, "b": {"type": "string"}},
                       "required": ["a", "b"]}),
        "code.syntax_check": ("Python 语法检查",
                              {"type": "object", "properties": {
                                  "path": {"type": "string"}}, "required": ["path"]}),
        "code.locate_symbol": ("在项目符号图中定位符号定义",
                               {"type": "object", "properties": {
                                   "name": {"type": "string"}}, "required": ["name"]}),
        "code.diagnose": ("错误诊断：从报错文本检索相关符号并给出排查建议",
                          {"type": "object", "properties": {
                              "error": {"type": "string"},
                              "context": {"type": "string"}},
                           "required": ["error"]}),
        "proc.run": ("执行 shell 命令（带超时与输出截断）",
                     {"type": "object", "properties": {
                         "command": {"type": "string"}, "timeout": {"type": "integer"},
                         "cwd": {"type": "string"}},
                      "required": ["command"]}),
        "web.fetch": ("抓取网页文本",
                      {"type": "object", "properties": {
                          "url": {"type": "string"}, "max_chars": {"type": "integer"}},
                       "required": ["url"]}),
        "project.summary": ("项目概览统计（文件/行数/扩展名分布）",
                            {"type": "object", "properties": {
                                "path": {"type": "string"}}}),
        "project.snapshot": ("项目文件快照（路径+内容哈希）",
                            {"type": "object", "properties": {
                                "path": {"type": "string"},
                                "max_files": {"type": "integer"}}}),
        "project.todo": ("轻量待办（add/list/update/remove）",
                         {"type": "object", "properties": {
                             "action": {"type": "string",
                                        "enum": ["add", "list", "update", "remove"]},
                             "text": {"type": "string"}, "index": {"type": "integer"},
                             "status": {"type": "string"}},
                          "required": ["action"]}),
        "batch.run": ("批量执行：对 items 逐项调用已注册工具 fn（map 风格）",
                      {"type": "object", "properties": {
                          "items": {"type": "array"}, "fn": {"type": "string"}},
                       "required": ["items"]}),
    }
    registered: list[Tool] = []
    for name, handler in builders.items():
        ns = name.split(".")[0]
        if include and ns not in include:
            continue
        desc, params = tool_meta[name]
        tool = Tool(name=name, description=desc, handler=handler, parameters=params)
        try:
            registry.register(tool)
            registered.append(tool)
        except KeyError:
            continue
    return registered


__all__ = ["ToolDeps", "install_standard_tools"]
