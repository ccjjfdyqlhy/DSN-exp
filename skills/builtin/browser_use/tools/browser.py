# skills/builtin/browser_use/tools/browser.py
# BrowserTool — Playwright 浏览器操控封装（async API + 独立线程事件循环）

from __future__ import annotations

import asyncio
import base64
import logging
import os
import threading
from typing import Any

logger = logging.getLogger("skill.browser_use")


def _run_async(coro):
    loop = _BrowserLoop.get()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=60)


class _BrowserLoop:
    _loop: asyncio.AbstractEventLoop | None = None
    _thread: threading.Thread | None = None
    _lock = threading.Lock()

    @classmethod
    def get(cls) -> asyncio.AbstractEventLoop:
        if cls._loop is None or cls._loop.is_closed():
            with cls._lock:
                if cls._loop is None or cls._loop.is_closed():
                    cls._loop = asyncio.new_event_loop()
                    cls._thread = threading.Thread(target=cls._loop.run_forever, daemon=True)
                    cls._thread.start()
        return cls._loop

    @classmethod
    def stop(cls):
        if cls._loop and not cls._loop.is_closed():
            cls._loop.call_soon_threadsafe(cls._loop.stop)
        if cls._thread and cls._thread.is_alive():
            cls._thread.join(timeout=5)
        cls._loop = None
        cls._thread = None


class BrowserTool:
    """浏览器操控工具 — 基于 Playwright 持久化会话（async API）"""

    _playwright = None
    _browser = None
    _context = None
    _page = None
    _headless = True

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        BrowserTool._headless = self.config.get("headless", True)

    @classmethod
    def _ensure_browser(cls):
        if cls._playwright is not None:
            return

        async def _start():
            from playwright.async_api import async_playwright
            cls._playwright = await async_playwright().start()
            cls._browser = await cls._playwright.chromium.launch(
                headless=cls._headless,
            )
            cls._context = await cls._browser.new_context(
                viewport={"width": 1280, "height": 720},
                accept_downloads=False,
            )
            cls._page = await cls._context.new_page()
            logger.info("Playwright 浏览器已启动 (headless=%s)", cls._headless)

        try:
            _run_async(_start())
        except ImportError:
            raise RuntimeError(
                "Playwright 未安装。运行: pip install playwright && playwright install chromium"
            )
        except Exception as e:
            cls._playwright = None
            cls._browser = None
            cls._context = None
            cls._page = None
            raise RuntimeError(f"浏览器启动失败: {e}")

    @classmethod
    def _close(cls):
        async def _stop():
            try:
                if cls._page:
                    await cls._page.close()
            except Exception:
                logger.warning("Close operation failed", exc_info=True)
            try:
                if cls._context:
                    await cls._context.close()
            except Exception:
                logger.warning("Close operation failed", exc_info=True)
            try:
                if cls._browser:
                    await cls._browser.close()
            except Exception:
                logger.warning("Close operation failed", exc_info=True)
            try:
                if cls._playwright:
                    await cls._playwright.stop()
            except Exception:
                logger.warning("Stop operation failed", exc_info=True)

        try:
            _run_async(_stop())
        except Exception:
            logger.warning("Stop operation failed", exc_info=True)
        finally:
            cls._playwright = None
            cls._browser = None
            cls._context = None
            cls._page = None

    def navigate(self, url: str, timeout: int = 30) -> dict[str, Any]:
        try:
            self._ensure_browser()

            async def _do():
                await self._page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
                title = await self._page.title()
                current_url = self._page.url
                return {"success": True, "url": current_url, "title": title}

            return _run_async(_do())
        except Exception as e:
            return {"success": False, "error": str(e), "url": url}

    def click(self, selector: str, timeout: int = 10) -> dict[str, Any]:
        try:
            self._ensure_browser()

            async def _do():
                await self._page.wait_for_selector(selector, timeout=timeout * 1000)
                elements = self._page.locator(selector)
                count = await elements.count()
                if count == 0:
                    await self._page.get_by_text(selector, exact=False).first.click(timeout=timeout * 1000)
                else:
                    await elements.first.click(timeout=timeout * 1000)
                return {"success": True, "selector": selector, "count": max(count, 1)}

            return _run_async(_do())
        except Exception as e:
            return {"success": False, "error": str(e), "selector": selector}

    def type(self, selector: str, text: str, press_enter: bool = False) -> dict[str, Any]:
        try:
            self._ensure_browser()

            async def _do():
                await self._page.wait_for_selector(selector, timeout=10000)
                await self._page.locator(selector).first.fill("")
                await self._page.locator(selector).first.type(text, delay=50)
                if press_enter:
                    await self._page.locator(selector).first.press("Enter")
                return {"success": True}

            return _run_async(_do())
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_content(self, selector: str = None) -> dict[str, Any]:
        try:
            self._ensure_browser()

            async def _do():
                if selector:
                    el = self._page.locator(selector).first
                    content = await el.inner_text()
                else:
                    content = await self._page.locator("body").inner_text()
                max_len = 4000
                if len(content) > max_len:
                    content = content[:max_len] + f"\n...(截断，共 {len(content)} 字符)"
                return {"success": True, "content": content, "length": len(content)}

            return _run_async(_do())
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_title(self) -> dict[str, Any]:
        try:
            self._ensure_browser()

            async def _do():
                title = await self._page.title()
                return {"success": True, "title": title}

            return _run_async(_do())
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_url(self) -> dict[str, Any]:
        try:
            self._ensure_browser()

            async def _do():
                url = self._page.url
                return {"success": True, "url": url}

            return _run_async(_do())
        except Exception as e:
            return {"success": False, "error": str(e)}

    def screenshot(self, filename: str = None, full_page: bool = False) -> dict[str, Any]:
        try:
            self._ensure_browser()

            async def _do():
                screenshot_bytes = await self._page.screenshot(full_page=full_page, type="png")
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

            return _run_async(_do())
        except Exception as e:
            return {"success": False, "error": str(e)}

    def execute_js(self, code: str) -> dict[str, Any]:
        try:
            self._ensure_browser()

            async def _do():
                result = await self._page.evaluate(code)
                return {"success": True, "result": str(result)[:3000]}

            return _run_async(_do())
        except Exception as e:
            return {"success": False, "error": str(e)}

    def wait_for(self, selector: str, timeout: int = 10) -> dict[str, Any]:
        try:
            self._ensure_browser()

            async def _do():
                await self._page.wait_for_selector(selector, timeout=timeout * 1000)
                return {"success": True, "selector": selector, "appeared": True}

            return _run_async(_do())
        except Exception as e:
            return {"success": False, "error": str(e), "selector": selector, "appeared": False}

    def scroll(self, direction: str = "down", amount: int = 500) -> dict[str, Any]:
        try:
            self._ensure_browser()

            async def _do():
                if direction == "down":
                    await self._page.evaluate(f"window.scrollBy(0, {amount})")
                elif direction == "up":
                    await self._page.evaluate(f"window.scrollBy(0, -{amount})")
                elif direction == "top":
                    await self._page.evaluate("window.scrollTo(0, 0)")
                elif direction == "bottom":
                    await self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                return {"success": True, "direction": direction}

            return _run_async(_do())
        except Exception as e:
            return {"success": False, "error": str(e)}
