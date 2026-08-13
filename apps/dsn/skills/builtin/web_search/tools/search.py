import json
import logging
import os
import urllib.request

from typing import Any

logger = logging.getLogger("skill.web_search")

_API_BASE = os.environ.get("WEB_SEARCH_API_BASE", "http://127.0.0.1:8142/v1")
_MODEL = os.environ.get("WEB_SEARCH_MODEL", "glm-5.2-search")


class WebSearchTool:

    def search(self, query: str, max_results: int = 5) -> dict[str, Any]:
        messages = [{"role": "user", "content": query}]
        body = json.dumps({
            "model": _MODEL,
            "messages": messages,
            "stream": True,
        }, ensure_ascii=False).encode("utf-8")

        try:
            request = urllib.request.Request(
                f"{_API_BASE}/chat/completions",
                method="POST",
                data=body,
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Authorization": "Bearer dummy",
                },
            )
            resp = urllib.request.urlopen(request, timeout=30)
            reply = ""
            buf = b""
            while True:
                chunk = resp.read(1)
                if not chunk:
                    break
                buf += chunk
                if buf.endswith(b"\n\n"):
                    for line in buf.decode("utf-8", errors="replace").strip().split("\n"):
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str.strip() == "[DONE]":
                                return {
                                    "success": True,
                                    "query": query,
                                    "content": reply,
                                    "provider": _MODEL,
                                }
                            try:
                                data = json.loads(data_str)
                            except json.JSONDecodeError:
                                continue
                            choices = data.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    reply += content
                    buf = b""

            return {
                "success": True,
                "query": query,
                "content": reply,
                "provider": _MODEL,
            }
        except Exception as e:
            logger.error("搜索失败: %s", e)
            return {
                "success": False,
                "error": str(e),
                "query": query,
                "content": "",
            }
