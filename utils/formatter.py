# skills/formatter.py
# 工具结果格式化 — 给 app.py 和 engine.py 共用


def format_tool_result(skill: str, tool: str, result) -> str:
    """格式化工具执行结果为用户友好的文本。"""
    if not isinstance(result, dict):
        return str(result)

    if not result.get("success", False):
        return f"[工具 {skill}.{tool} 失败] {result.get('error', '未知错误')}"

    if skill == "web_search" and tool == "search":
        lines = [f"搜索: {result.get('query', '')}"]
        for i, r in enumerate(result.get("results", []), 1):
            lines.append(f"  {i}. {r.get('title', '')}")
            if r.get("snippet"):
                lines.append(f"     {r['snippet'][:200]}")
            if r.get("url"):
                lines.append(f"     {r['url']}")
        return "\n".join(lines)

    if skill == "file_manager":
        if tool == "list_dir":
            lines = [f"目录 {result.get('path', '')}:"]
            for item in result.get("items", []):
                marker = "[DIR]" if item.get("type") == "dir" else "[FILE]"
                lines.append(f"  {marker} {item['name']}")
            return "\n".join(lines)
        if tool == "read_file":
            content = result.get("content", "")
            if len(content) > 2000:
                content = content[:2000] + "\n...(截断)"
            return f"文件 {result.get('path', '')} ({result.get('size', 0)} bytes):\n{content}"
        if tool == "write_file":
            return f"已写入 {result.get('path', '')} ({result.get('size', 0)} bytes)"

    if skill == "browser_use":
        if tool == "navigate":
            return f"[浏览器] 已导航到 {result.get('url', '')}\n标题: {result.get('title', '')}"
        if tool == "click":
            return f"[浏览器] 已点击 \"{result.get('selector', '')}\""
        if tool == "type":
            return f"[浏览器] 已在 \"{result.get('selector', '')}\" 中输入文本"
        if tool == "get_content":
            return f"[浏览器] 页面内容 ({result.get('length', 0)} 字符):\n{result.get('content', '')[:2000]}"
        if tool == "get_title":
            return f"[浏览器] 页面标题: {result.get('title', '')}"
        if tool == "get_url":
            return f"[浏览器] 当前 URL: {result.get('url', '')}"
        if tool == "screenshot":
            if result.get("path"):
                return f"[浏览器] 截图已保存到 {result['path']}"
            return f"[浏览器] 截图 (base64, {result.get('length', 0)} 字符)"
        if tool == "execute_js":
            return f"[浏览器] JS 执行结果: {result.get('result', '')[:1000]}"
        if tool == "wait_for":
            appeared = result.get("appeared", False)
            status = "已出现" if appeared else "未出现"
            return f"[浏览器] 等待 \"{result.get('selector', '')}\" → {status}"
        if tool == "scroll":
            return f"[浏览器] 已向{result.get('direction', '')}滚动"

    if skill == "skillmgr":
        if tool == "list_skills":
            skills = result.get("skills", [])
            lines = [f"已安装技能 ({len(skills)} 个):"]
            for s in skills:
                status = "✓" if s.get("enabled") else "✗"
                lines.append(f"  {status} {s['name']} ({s.get('display_name', '')}) [{s.get('source', '')}] — {s.get('tool_count', 0)} tools")
            return "\n".join(lines)
        if tool == "enable_skill":
            return f"[skillmgr] {result.get('message', '')}"
        if tool == "disable_skill":
            return f"[skillmgr] {result.get('message', '')}"
        if tool == "install_deps":
            py = result.get("python_installed", [])
            sk = result.get("python_skipped", [])
            sys_r = result.get("system_results", [])
            lines = [f"[skillmgr] 依赖安装完成:"]
            if py:
                lines.append(f"  新安装: {', '.join(py)}")
            if sk:
                lines.append(f"  已存在: {', '.join(sk)}")
            if sys_r:
                for r in sys_r:
                    lines.append(f"  系统命令: {r.get('command', '')} (exit={r.get('exit_code', '?')})")
            return "\n".join(lines)
        if tool == "convert_skill":
            return f"[skillmgr] {result.get('message', '')}\n目标: {result.get('target', '')}\n二进制: {result.get('binary', '')}"
        if tool == "download_skill":
            return f"[skillmgr] {result.get('message', '')}"

    import json
    return json.dumps(result, ensure_ascii=False, indent=2)
