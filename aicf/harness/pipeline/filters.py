# harness/pipeline/filters.py
# OutputFilter — 工具输出清洗（RTK）：去 ANSI/时间戳/UUID、折叠空行、截断。
#
# 用于在把工具输出回喂给模型前压缩体积，节省 token。

from __future__ import annotations

import re

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")
_TIMESTAMP_RE = re.compile(r"\d{4}[-/]\d{2}[-/]\d{2}[T ]\d{2}:\d{2}:\d{2}")
_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_REPEATED_BLANK_RE = re.compile(r"\n{3,}")


class OutputFilter:
    """内置输出清洗器。"""

    @staticmethod
    def strip_ansi(output: str) -> str:
        return _ANSI_RE.sub("", output)

    @staticmethod
    def collapse(output: str, *, max_lines: int = 0) -> str:
        output = _ANSI_RE.sub("", output)
        output = _TIMESTAMP_RE.sub("<ts>", output)
        output = _UUID_RE.sub("<uuid>", output)
        output = _REPEATED_BLANK_RE.sub("\n\n", output)
        if max_lines and max_lines > 0:
            lines = output.split("\n")
            if len(lines) > max_lines:
                lines = lines[:max_lines] + [
                    f"[...{len(lines) - max_lines} more lines suppressed]"]
                output = "\n".join(lines)
        return output

    @staticmethod
    def truncate(text: str, max_chars: int = 4000) -> str:
        if max_chars and len(text) > max_chars:
            return text[:max_chars] + "\n...[截断]"
        return text
