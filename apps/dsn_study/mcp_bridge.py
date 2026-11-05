# apps/dsn_study/mcp_bridge.py
# 外部 MCP 桥接 —— 把 Obsidian 等外部 MCP 服务器的工具接进 dsn_study 的 AgentLoop。
#
# 设计要点：
#   * 复用 harness 的 MCPManager（连接/失败隔离/超时/重连/工具命名空间全部现成），
#     dsn_study 只做「加载 YAML → 连接 → 把 Tool 注册给 AgentRuntime」。
#   * **专属常驻事件循环**：MCP 会话（stdio 子进程 + anyio task group）必须活在与
#     它同一个事件循环里。若用 asyncio.run() 建连再退出，循环关闭会把会话一起
#     销毁（表现为「工具列出来了但调用永远失败」）。因此这里起一个专属的、
#     永不退出的事件循环线程，跨线程调用用 run_coroutine_threadsafe。
#   * **连接放后台线程**：stdio 子进程冷启动（npx 拉包）要数秒，不能阻塞应用启动；
#     连不上只影响 MCP 工具，其余功能照常（失败隔离）。
#   * vault 路径经环境变量注入：YAML 里用 ${OBSIDIAN_VAULT_PATH} 占位，
#     由 Config 决定实际 vault，避免把绝对路径写死在配置文件里。

from __future__ import annotations

import asyncio
import logging
import os
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger("MCPBridge")


class MCPBridge:
    """外部 MCP 服务器 → AgentRuntime 工具桥。"""

    def __init__(self, agent, config_path: str = "",
                 env: Optional[dict] = None):
        self._agent = agent
        self._config_path = config_path
        self._env = dict(env or {})
        self._manager = None
        self._errors: dict = {}
        self._tools: list[str] = []
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._loop_thread: Optional[threading.Thread] = None
        self._connect_thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self._closed = False

    # ── 生命周期 ──

    def start(self) -> bool:
        """后台启动连接。立即返回（不阻塞调用方）。"""
        if not self._config_path:
            logger.info("未配置 MCP，未启用外部 MCP 工具")
            return False
        path = Path(self._config_path).expanduser()
        if not path.is_absolute():
            # 相对路径按仓库根解析（配置里写相对路径时不应依赖进程 CWD）
            path = (Path(__file__).resolve().parents[2] / path).resolve()
        if not path.is_file():
            logger.warning("MCP 配置文件不存在: %s（外部 MCP 工具不可用）", path)
            return False

        # 注入 vault 等运行时变量（YAML 里用 ${VAR} 占位）
        for key, value in self._env.items():
            if value is None:
                continue
            os.environ.setdefault(key, str(value))

        # 专属事件循环线程（常驻，直到 close）
        ready = threading.Event()

        def _loop_main():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            with self._lock:
                self._loop = loop
            ready.set()
            try:
                loop.run_forever()
            finally:
                try:
                    loop.close()
                except Exception:
                    pass

        self._loop_thread = threading.Thread(target=_loop_main, daemon=True,
                                              name="mcp-loop")
        self._loop_thread.start()
        ready.wait(timeout=10)

        def _connect_main():
            try:
                self._connect(path)
            except Exception as e:
                logger.warning("MCP 桥接失败（外部 MCP 工具不可用）: %s", e)

        self._connect_thread = threading.Thread(target=_connect_main, daemon=True,
                                                name="mcp-connect")
        self._connect_thread.start()
        return True

    def _connect(self, path: Path) -> None:
        """在专属事件循环上连接服务器并注册工具。"""
        from harness.tools import MCPManager, ToolRegistry

        manager = MCPManager.from_yaml(path)
        registry = ToolRegistry()
        loop = self._loop

        async def _load():
            return await manager.load_tools(registry)

        future = asyncio.run_coroutine_threadsafe(_load(), loop)
        errors = future.result(timeout=180)

        with self._lock:
            self._manager = manager
            self._errors = errors or {}
            self._tools = sorted(registry.names())
            # 逐个注册给 AgentRuntime（Tool 对象自带 async handler 与 schema）
            for name in self._tools:
                try:
                    self._agent.register(registry.require(name))
                except Exception as e:
                    logger.warning("MCP 工具 %s 注册失败: %s", name, e)
        if errors:
            logger.warning("部分 MCP 服务器未就绪: %s", errors)
        logger.info("MCP 工具已接入 %d 个: %s", len(self._tools),
                    ", ".join(self._tools) or "(无)")

    def close(self) -> None:
        """关闭所有 MCP 连接并停止事件循环（应用停止时调用）。"""
        with self._lock:
            self._closed = True
            manager = self._manager
            loop = self._loop
            self._manager = None
        if manager is not None and loop is not None and not loop.is_closed():
            try:
                asyncio.run_coroutine_threadsafe(manager.close(), loop).result(
                    timeout=10)
            except Exception:
                logger.debug("MCP 关闭异常（已忽略）", exc_info=True)
        if loop is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(loop.stop)
            except Exception:
                pass

    # ── 状态 ──

    @property
    def manager(self):
        """底层 MCPManager（未连接时 None）。"""
        with self._lock:
            return self._manager

    @property
    def tools(self) -> list:
        with self._lock:
            return list(self._tools)

    def status(self) -> dict:
        """连接状态快照。"""
        with self._lock:
            manager = self._manager
            tools = list(self._tools)
            errors = dict(self._errors)
        info = {
            "enabled": bool(self._config_path),
            "connected": manager is not None,
            "tool_count": len(tools),
            "tools": tools,
            "errors": errors,
            "servers": {},
        }
        if manager is not None:
            try:
                info["servers"] = manager.status()
            except Exception:
                pass
        return info

    async def call(self, server: str, tool: str, arguments: Optional[dict] = None):
        """调用远端 MCP 工具（跨线程 → 专属事件循环）。"""
        manager = self.manager
        loop = self._loop
        if manager is None or loop is None or loop.is_closed():
            raise RuntimeError("MCP 未连接")
        future = asyncio.run_coroutine_threadsafe(
            manager.call(server, tool, arguments or {}), loop)
        return await asyncio.wrap_future(future)

    def __repr__(self) -> str:
        return "<MCPBridge tools=%d connected=%s>" % (len(self.tools),
                                                      self.manager is not None)
