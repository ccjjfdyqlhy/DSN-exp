# skills/formatter.py
# 工具结果格式化 — 给 app.py 和 engine.py 共用

from typing import Any


def _fmt_web_search(result: dict) -> str:
    lines = [f"搜索: {result.get('query', '')}"]
    for i, r in enumerate(result.get("results", []), 1):
        lines.append(f"  {i}. {r.get('title', '')}")
        if r.get("snippet"):
            lines.append(f"     {r['snippet'][:200]}")
        if r.get("url"):
            lines.append(f"     {r['url']}")
    return "\n".join(lines)


def _fmt_file_list_dir(result: dict) -> str:
    lines = [f"目录 {result.get('path', '')}:"]
    for item in result.get("items", []):
        marker = "[DIR]" if item.get("type") == "dir" else "[FILE]"
        lines.append(f"  {marker} {item['name']}")
    return "\n".join(lines)


def _fmt_file_read(result: dict) -> str:
    content = result.get("content", "")
    if len(content) > 2000:
        content = content[:2000] + "\n...(截断)"
    return f"文件 {result.get('path', '')} ({result.get('size', 0)} bytes):\n{content}"


def _fmt_file_write(result: dict) -> str:
    return f"已写入 {result.get('path', '')} ({result.get('size', 0)} bytes)"


def _fmt_browser_navigate(result: dict) -> str:
    return f"[浏览器] 已导航到 {result.get('url', '')}\n标题: {result.get('title', '')}"


def _fmt_browser_click(result: dict) -> str:
    return f'[浏览器] 已点击 "{result.get("selector", "")}"'


def _fmt_browser_type(result: dict) -> str:
    return f'[浏览器] 已在 "{result.get("selector", "")}" 中输入文本'


def _fmt_browser_get_content(result: dict) -> str:
    return f"[浏览器] 页面内容 ({result.get('length', 0)} 字符):\n{result.get('content', '')[:2000]}"


def _fmt_browser_get_title(result: dict) -> str:
    return f"[浏览器] 页面标题: {result.get('title', '')}"


def _fmt_browser_get_url(result: dict) -> str:
    return f"[浏览器] 当前 URL: {result.get('url', '')}"


def _fmt_browser_screenshot(result: dict) -> str:
    if result.get("path"):
        return f"[浏览器] 截图已保存到 {result['path']}"
    return f"[浏览器] 截图 (base64, {result.get('length', 0)} 字符)"


def _fmt_browser_execute_js(result: dict) -> str:
    return f"[浏览器] JS 执行结果: {result.get('result', '')[:1000]}"


def _fmt_browser_wait_for(result: dict) -> str:
    appeared = result.get("appeared", False)
    status = "已出现" if appeared else "未出现"
    return f'[浏览器] 等待 "{result.get("selector", "")}" → {status}'


def _fmt_browser_scroll(result: dict) -> str:
    return f"[浏览器] 已向{result.get('direction', '')}滚动"


def _fmt_skillmgr_list(result: dict) -> str:
    skills = result.get("skills", [])
    lines = [f"已安装技能 ({len(skills)} 个):"]
    for s in skills:
        status = "✓" if s.get("enabled") else "✗"
        lines.append(f"  {status} {s['name']} ({s.get('display_name', '')}) [{s.get('source', '')}] — {s.get('tool_count', 0)} tools")
    return "\n".join(lines)


def _fmt_skillmgr_message(result: dict) -> str:
    return f"[skillmgr] {result.get('message', '')}"


def _fmt_skillmgr_install(result: dict) -> str:
    py = result.get("python_installed", [])
    sk = result.get("python_skipped", [])
    sys_r = result.get("system_results", [])
    lines = ["[skillmgr] 依赖安装完成:"]
    if py:
        lines.append(f"  新安装: {', '.join(py)}")
    if sk:
        lines.append(f"  已存在: {', '.join(sk)}")
    if sys_r:
        for r in sys_r:
            lines.append(f"  系统命令: {r.get('command', '')} (exit={r.get('exit_code', '?')})")
    return "\n".join(lines)


def _fmt_skillmgr_convert(result: dict) -> str:
    return f"[skillmgr] {result.get('message', '')}\n目标: {result.get('target', '')}\n二进制: {result.get('binary', '')}"


_FORMATTERS: dict[tuple[str, str], Any] = {
    ("web_search", "search"): _fmt_web_search,
    ("file_manager", "list_dir"): _fmt_file_list_dir,
    ("file_manager", "read_file"): _fmt_file_read,
    ("file_manager", "write_file"): _fmt_file_write,
    ("browser_use", "navigate"): _fmt_browser_navigate,
    ("browser_use", "click"): _fmt_browser_click,
    ("browser_use", "type"): _fmt_browser_type,
    ("browser_use", "get_content"): _fmt_browser_get_content,
    ("browser_use", "get_title"): _fmt_browser_get_title,
    ("browser_use", "get_url"): _fmt_browser_get_url,
    ("browser_use", "screenshot"): _fmt_browser_screenshot,
    ("browser_use", "execute_js"): _fmt_browser_execute_js,
    ("browser_use", "wait_for"): _fmt_browser_wait_for,
    ("browser_use", "scroll"): _fmt_browser_scroll,
    ("skillmgr", "list_skills"): _fmt_skillmgr_list,
    ("skillmgr", "enable_skill"): _fmt_skillmgr_message,
    ("skillmgr", "disable_skill"): _fmt_skillmgr_message,
    ("skillmgr", "install_deps"): _fmt_skillmgr_install,
    ("skillmgr", "convert_skill"): _fmt_skillmgr_convert,
    ("skillmgr", "download_skill"): _fmt_skillmgr_message,
}


def format_tool_result(skill: str, tool: str, result) -> str:
    """格式化工具执行结果为用户友好的文本。"""
    if not isinstance(result, dict):
        return str(result)
    if not result.get("success", False):
        return f"[工具 {skill}.{tool} 失败] {result.get('error', '未知错误')}"
    fn = _FORMATTERS.get((skill, tool))
    if fn:
        return fn(result)
    import json
    return json.dumps(result, ensure_ascii=False, indent=2)
