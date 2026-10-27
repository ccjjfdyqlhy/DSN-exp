# tests/fixtures/mcp_demo_server.py
# 集成测试用的最小 MCP 服务器（stdio 传输）。
#
# 由 tests/test_harness_mcp.py 的 integration 用例以子进程方式拉起：
#   command=sys.executable, args=[本文件绝对路径]
# 提供两个工具：add(a, b) / echo(text)。文件名刻意不叫 test_*.py，避免被收集。
#
# 注：structured_output=False 是刻意的 —— 本机 mcp 1.28 + pydantic 2.9 组合下，
# FastMCP 为原始类型返回值建包装输出模型会触发 pydantic 2.9 的
# "non-annotated attribute" 报错（mcp 1.28 预期更新的 pydantic）。
# 非结构化输出走文本内容路径，完全绕开该兼容问题；harness 客户端不受影响。

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("demo")


@mcp.tool(structured_output=False)
def add(a: int, b: int) -> str:
    """两整数相加。"""
    return str(a + b)


@mcp.tool(structured_output=False)
def echo(text: str) -> str:
    """原样回显文本。"""
    return f"echo: {text}"


if __name__ == "__main__":
    mcp.run()
