# skills/builtin/web_search/tools/search.py
# 网页搜索工具 — 使用 Bing / 360 搜索 (国内可用，免 API key)

import logging
import requests
from typing import Any

logger = logging.getLogger("skill.web_search")


class WebSearchTool:
    """网页搜索工具 — 使用 Bing HTML 搜索 + 360 搜索备用"""

    def __init__(self, config: dict[str, Any] = None):
        self.config = config or {}
        self.timeout = self.config.get("timeout", 15)

    @property
    def _headers(self) -> dict:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

    def search(self, query: str, max_results: int = 5) -> dict[str, Any]:
        try:
            results = self._search_bing(query, max_results)
            return {
                "success": True,
                "query": query,
                "results": results,
                "count": len(results),
                "provider": "bing",
            }
        except requests.RequestException as e:
            logger.warning("Bing 搜索失败: %s, 尝试 360 搜索", e)
            return self._fallback_360(query, max_results)

    def _search_bing(self, query: str, max_results: int) -> list[dict]:
        url = "https://www.bing.com/search"
        params = {
            "q": query,
            "setlang": "zh-CN",
            "count": str(max_results + 2),
        }
        resp = requests.get(url, params=params, headers=self._headers, timeout=self.timeout)
        resp.raise_for_status()
        return self._parse_bing(resp.text, max_results)

    def _fallback_360(self, query: str, max_results: int) -> dict[str, Any]:
        try:
            url = "https://www.so.com/s"
            params = {"q": query, "pn": "1"}
            resp = requests.get(url, params=params, headers=self._headers, timeout=self.timeout)
            resp.raise_for_status()
            results = self._parse_360(resp.text, max_results)
            return {
                "success": True,
                "query": query,
                "results": results,
                "count": len(results),
                "provider": "360",
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
    def _parse_bing(html: str, max_results: int) -> list[dict]:
        import re

        results = []
        algo_blocks = re.split(r'<li class="b_algo"', html)[1:]

        for block in algo_blocks[:max_results]:
            link_m = re.search(r'<a[^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>', block, re.DOTALL)
            if not link_m:
                continue
            url = link_m.group(1)
            title = re.sub(r'<[^>]+>', '', link_m.group(2)).strip()
            if "bing.com" in url or "microsoft.com/bing" in url:
                continue

            snippet = ""
            cap_m = re.search(r'<p[^>]*class="[^"]*b_lineclamp[^"]*"[^>]*>(.*?)</p>', block, re.DOTALL)
            if not cap_m:
                cap_m = re.search(r'<div class="b_caption"[^>]*>.*?<p[^>]*>(.*?)</p>', block, re.DOTALL)
            if cap_m:
                snippet = re.sub(r'<[^>]+>', '', cap_m.group(1)).strip()

            results.append({"title": title, "url": url, "snippet": snippet})

        return results

    @staticmethod
    def _parse_360(html: str, max_results: int) -> list[dict]:
        import re

        results = []
        blocks = re.split(r'<li class="res-list"', html)[1:]

        for block in blocks[:max_results]:
            link_m = re.search(r'<a[^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>', block, re.DOTALL)
            if not link_m:
                continue
            url = link_m.group(1)
            title = re.sub(r'<[^>]+>', '', link_m.group(2)).strip()
            if "so.com" in url or "360.cn" in url:
                continue

            snippet = ""
            desc_m = re.search(r'<p class="res-desc"[^>]*>(.*?)</p>', block, re.DOTALL)
            if desc_m:
                snippet = re.sub(r'<[^>]+>', '', desc_m.group(1)).strip()

            results.append({"title": title, "url": url, "snippet": snippet})

        return results
