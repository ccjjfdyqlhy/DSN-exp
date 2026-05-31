# skills/builtin/browser_use/tools/browser.py
# BrowserTool — Playwright 浏览器操控封装

from __future__ import annotations

import base64
import logging
import os
import tempfile
from typing import Any

logger = logging.getLogger("skill.browser_use")


class BrowserTool:
    """浏览器操控工具 — 基于 Playwright 持久化会话"""

    _playwright = None
    _browser = None
    _context = None
    _page = None
    _headless = True

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self._headless = self.config.get("headless", True)
        self._viewport = self.config.get("viewport", {"width": 1280, "height": 720})
        self._screenshot_dir = self.config.get("screenshot_dir", "")

    @classmethod
    def _ensure_browser(cls):
        if cls._playwright is None:
            try:
                from playwright.sync_api import sync_playwright
                cls._playwright = sync_playwright().start()
                cls._browser = cls._playwright.chromium.launch(
                    headless=cls._headless,
                )
                cls._context = cls._browser.new_context(
                    viewport={"width": 1280, "height": 720},
                    accept_downloads=False,
                )
                cls._page = cls._context.new_page()
                logger.info("Playwright 浏览器已启动 (headless=%s)", cls._headless)
            except ImportError:
                raise RuntimeError(
                    "Playwright 未安装。运行: pip install playwright && playwright install chromium"
                )
            except Exception as e:
                cls._playwright = None
                raise RuntimeError(f"浏览器启动失败: {e}")

    @classmethod
    def _close(cls):
        try:
            if cls._page:
                cls._page.close()
            if cls._context:
                cls._context.close()
            if cls._browser:
                cls._browser.close()
            if cls._playwright:
                cls._playwright.stop()
        except Exception:
            pass
        finally:
            cls._playwright = None
            cls._browser = None
            cls._context = None
            cls._page = None

    def navigate(self, url: str, timeout: int = 30) -> dict[str, Any]:
        try:
            self._ensure_browser()
            self._page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
            title = self._page.title()
            current_url = self._page.url
            return {
                "success": True,
                "url": current_url,
                "title": title,
            }
        except Exception as e:
            return {"success": False, "error": str(e), "url": url}

    def click(self, selector: str, timeout: int = 10) -> dict[str, Any]:
        try:
            self._ensure_browser()
            self._page.wait_for_selector(selector, timeout=timeout * 1000)
            elements = self._page.locator(selector)
            count = elements.count()
            if count == 0:
                self._page.get_by_text(selector, exact=False).first.click(timeout=timeout * 1000)
            else:
                elements.first.click(timeout=timeout * 1000)
            return {"success": True, "selector": selector, "count": max(count, 1)}
        except Exception as e:
            return {"success": False, "error": str(e), "selector": selector}

    def type(self, selector: str, text: str, press_enter: bool = False) -> dict[str, Any]:
        try:
            self._ensure_browser()
            self._page.wait_for_selector(selector, timeout=10000)
            self._page.locator(selector).first.fill("")
            self._page.locator(selector).first.type(text, delay=50)
            if press_enter:
                self._page.locator(selector).first.press("Enter")
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_content(self, selector: str = None) -> dict[str, Any]:
        try:
            self._ensure_browser()
            if selector:
                el = self._page.locator(selector).first
                content = el.inner_text()
            else:
                content = self._page.locator("body").inner_text()
            max_len = 4000
            if len(content) > max_len:
                content = content[:max_len] + f"\n...(截断，共 {len(content)} 字符)"
            return {"success": True, "content": content, "length": len(content)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_title(self) -> dict[str, Any]:
        try:
            self._ensure_browser()
            title = self._page.title()
            return {"success": True, "title": title}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_url(self) -> dict[str, Any]:
        try:
            self._ensure_browser()
            url = self._page.url
            return {"success": True, "url": url}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def screenshot(self, filename: str = None, full_page: bool = False) -> dict[str, Any]:
        try:
            self._ensure_browser()
            screenshot_bytes = self._page.screenshot(full_page=full_page, type="png")
            b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
            if filename:
                if not os.path.isabs(filename):
                    d = self._screenshot_dir or os.path.join(os.getcwd(), "screenshots")
                    os.makedirs(d, exist_ok=True)
                    filename = os.path.join(d, filename)
                with open(filename, "wb") as f:
                    f.write(screenshot_bytes)
                return {"success": True, "path": filename, "base64_len": len(b64)}
            return {"success": True, "base64": b64, "length": len(b64)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def execute_js(self, code: str) -> dict[str, Any]:
        try:
            self._ensure_browser()
            result = self._page.evaluate(code)
            return {"success": True, "result": str(result)[:3000]}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def wait_for(self, selector: str, timeout: int = 10) -> dict[str, Any]:
        try:
            self._ensure_browser()
            self._page.wait_for_selector(selector, timeout=timeout * 1000)
            return {"success": True, "selector": selector, "appeared": True}
        except Exception as e:
            return {"success": False, "error": str(e), "selector": selector, "appeared": False}

    def scroll(self, direction: str = "down", amount: int = 500) -> dict[str, Any]:
        try:
            self._ensure_browser()
            if direction == "down":
                self._page.evaluate(f"window.scrollBy(0, {amount})")
            elif direction == "up":
                self._page.evaluate(f"window.scrollBy(0, -{amount})")
            elif direction == "top":
                self._page.evaluate("window.scrollTo(0, 0)")
            elif direction == "bottom":
                self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            return {"success": True, "direction": direction}
        except Exception as e:
            return {"success": False, "error": str(e)}
