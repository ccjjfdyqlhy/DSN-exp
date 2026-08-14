# tests/test_harness_standard_tools.py
# 标准工具集（harness/tools/standard.py）单元测试。

from __future__ import annotations

import pytest

from harness import ToolRegistry
from harness.tools.base import ToolResult
from harness.tools.standard import ToolDeps, install_standard_tools


def call(reg, name, **kw):
    """调用工具并解包 ToolResult。"""
    result = reg.get(name).run(**kw)
    if isinstance(result, ToolResult):
        return result.output if result.success else {"success": False, "error": result.error}
    return result


@pytest.fixture
def reg(tmp_path):
    r = ToolRegistry()
    install_standard_tools(r, deps=ToolDeps(workspace=str(tmp_path)))
    return r


def test_install_registers_all(reg):
    names = {"file.read", "file.write", "file.list", "file.tree",
             "text.chunk", "text.extract_json", "text.diff",
             "code.syntax_check", "proc.run", "web.fetch",
             "project.summary", "project.todo", "batch.run"}
    assert names <= set(reg.names())


def test_file_write_read(reg, tmp_path):
    r = call(reg, "file.write", path="a.txt", content="hello")
    assert r["success"]
    out = call(reg, "file.read", path="a.txt")
    assert out["content"] == "hello"


def test_file_list_and_tree(reg, tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.py").write_text("x = 1")
    (tmp_path / "a.py").write_text("y = 2")
    lst = call(reg, "file.list", path=".", recursive=True)
    assert lst["count"] == 2
    tr = call(reg, "file.tree", path=".", max_depth=2)
    assert "a.py" in tr["tree"] and "sub/" in tr["tree"]


def test_path_traversal_guard(reg):
    out = call(reg, "file.read", path="../../etc/passwd")
    assert not out["success"]


def test_text_chunk_and_diff(reg):
    ch = call(reg, "text.chunk", text="a" * 100, chunk_size=30)
    assert ch["count"] == 4
    d = call(reg, "text.diff", a="line1\nline2", b="line1\nline3")
    assert "-line2" in d["diff"] and "+line3" in d["diff"]


def test_code_syntax_check(reg, tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("def f(:")
    out = call(reg, "code.syntax_check", path="bad.py")
    assert out["valid"] is False
    assert "语法错误" in out["error"]


def test_proc_run(reg):
    out = call(reg, "proc.run", command="echo hi", timeout=10)
    assert out["success"] and "hi" in out["stdout"]


def test_project_summary_and_todo(reg, tmp_path):
    (tmp_path / "main.py").write_text("print(1)\nprint(2)\n")
    s = call(reg, "project.summary")
    assert s["files"] == 1
    assert s["lines"] == 2
    call(reg, "project.todo", action="add", text="任务A")
    lst = call(reg, "project.todo", action="list")
    assert lst["items"][0]["text"] == "任务A"
    call(reg, "project.todo", action="update", index=0, status="done")
    assert call(reg, "project.todo", action="list")["items"][0]["status"] == "done"
