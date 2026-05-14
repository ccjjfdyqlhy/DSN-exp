# skills/builtin/web_search/tools/search.py
# 网页搜索工具 — 使用 DuckDuckGo Instant Answer API (免 API key)

import logging
import requests
from typing import Any

logger = logging.getLogger("skill.web_search")


class WebSearchTool:
    """网页搜索工具 — 使用 DuckDuckGo HTML 搜索（无需 API key）"""

    def __init__(self, config: dict[str, Any] = None):
        self.config = config or {}
        self.timeout = self.config.get("timeout", 15)

    def search(self, query: str, max_results: int = 5) -> dict[str, Any]:
        """
        执行网页搜索。

        :param query: 搜索关键词
        :param max_results: 最大结果数
        :return: 搜索结果字典
        """
        try:
            # 使用 DuckDuckGo Lite (HTML) — 无需 API key
            url = "https://lite.duckduckgo.com/lite/"
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Content-Type": "application/x-www-form-urlencoded",
            }
            resp = requests.post(
                url,
                data={"q": query},
                headers=headers,
                timeout=self.timeout,
            )
            resp.raise_for_status()

            results = self._parse_ddg_lite(resp.text, max_results)

            return {
                "success": True,
                "query": query,
                "results": results,
                "count": len(results),
            }
        except requests.RequestException as e:
            logger.warning("DuckDuckGo Lite 请求失败: %s, 尝试 DuckDuckGo Instant Answer API", e)
            return self._fallback_search(query, max_results)

    def _fallback_search(self, query: str, max_results: int) -> dict[str, Any]:
        try:
            url = "https://api.duckduckgo.com/"
            params = {
                "q": query,
                "format": "json",
                "no_html": "1",
                "skip_disambig": "1",
            }
            resp = requests.get(url, params=params, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()

            results = []
            # 提取 Abstract
            if data.get("AbstractText"):
                results.append({
                    "title": data.get("AbstractSource", "DuckDuckGo"),
                    "url": data.get("AbstractURL", ""),
                    "snippet": data.get("AbstractText", ""),
                })
            # 提取 RelatedTopics
            for topic in data.get("RelatedTopics", [])[:max_results]:
                if isinstance(topic, dict) and topic.get("Text"):
                    results.append({
                        "title": topic.get("FirstURL", "").split("/")[-1].replace("_", " "),
                        "url": topic.get("FirstURL", ""),
                        "snippet": topic.get("Text", ""),
                    })

            return {
                "success": True,
                "query": query,
                "results": results[:max_results],
                "count": min(len(results), max_results),
            }
        except Exception as e:
            logger.error("搜索失败: %s", e)
            return {
                "success": False,
                "error": str(e),
                "query": query,
                "results": [],
            }

    @staticmethod
    def _parse_ddg_lite(html: str, max_results: int) -> list[dict]:
        """解析 DuckDuckGo Lite 返回的 HTML"""
        import re
        results = []
        # DDG Lite 结果格式: <a rel="nofollow" href="URL">Title</a><br><span>Snippet</span>
        # 简化解析: 查找链接和描述
        link_pattern = re.compile(
            r'<a[^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>',
            re.DOTALL
        )
        snippet_pattern = re.compile(
            r'<span class="link-text">(.*?)</span>',
            re.DOTALL
        )

        links = link_pattern.findall(html)
        # 过滤掉内部链接
        links = [(url, title.strip()) for url, title in links
                 if not url.startswith("//duckduckgo.com") and "duckduckgo.com" not in url[:50]]

        snippets = snippet_pattern.findall(html)

        for i, (url, title) in enumerate(links[:max_results]):
            results.append({
                "title": re.sub(r'<[^>]+>', '', title).strip(),
                "url": url,
                "snippet": re.sub(r'<[^>]+>', '', snippets[i]).strip()
                if i < len(snippets) else "",
            })

        return results
