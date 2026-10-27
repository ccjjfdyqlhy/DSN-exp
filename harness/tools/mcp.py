# harness/tools/mcp.py
# 外部 MCP（Model Context Protocol）工具源 — 把外部 MCP 服务器的工具接入 ToolRegistry。
#
# 定位：harness 只认识 Tool / ToolRegistry，不直接依赖 MCP 协议；本模块负责
# 协议桥接 —— 连接外部 MCP 服务器（stdio 子进程 / streamable HTTP / SSE），
# 把远端工具包装成本地 Tool（命名空间 mcp.<server>.<tool>），调用时经
# ClientSession 转发。AgentLoop / ToolboxManager / wire 名编码自动生效。
#
# 连接生命周期（惰性连接，核心约束）:
#   AgentAssembler.assemble() 是同步的，而 MCP 会话是绑定事件循环的异步长连接
#   （stdio 传输的子进程随事件循环销毁而终止）。因此装配阶段只创建 manager、
#   不建立任何连接；真正的连接发生在:
#     1. 应用显式预热:  await agent.setup_mcp()（服务端 lifespan 场景）
#     2. 首次工具调用:  handler 内 ensure_connected()（SDK 单次任务场景）
#   同步 chat() 在单次 asyncio.run 内完成「连接 → 调用」，stdio 子进程存活到
#   本次对话结束即被回收 —— 功能正确，代价是每次对话重启子进程；长驻服务
#   请使用异步入口保持连接复用。
#
# 依赖：官方 SDK `mcp`（pip install "mcp>=1.2"）。延迟导入 —— 未安装时
# harness 其余功能完全不受影响，仅在真正连接时报清晰错误。
#
# 用法:
#     from harness.tools.mcp import MCPManager
#     manager = MCPManager.from_yaml("mcp_servers.yaml")
#     await manager.load_tools(registry)        # 连接 + 注册全部工具
#     ...
#     await manager.close()                     # 应用关停时

from __future__ import annotations

import asyncio
import datetime as _dt
import logging
import os
import re
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .base import Tool, ToolRegistry, ToolResult

logger = logging.getLogger("harness.mcp")

# 配置字符串里的 ${ENV_VAR} 展开（密钥不入库，运行时从环境读取）
_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

# call_tool 外层 asyncio.wait_for 相对 call_timeout 的余量（秒）：SDK 内部的
# read_timeout 先行触发，外层只是兜底（进程僵死 / 清理动作卡住等极端情形）。
# 做成模块常量是为了单测能把它调小，否则超时用例要白等 5 秒。
_OUTER_TIMEOUT_MARGIN = 5.0


def _expand_env(value: str) -> str:
    """展开 ${VAR}；未设置的变量展开为空串并告警（空 Authorization 会在连接期显式失败）。"""

    def _sub(m: re.Match) -> str:
        var = m.group(1)
        if var not in os.environ:
            logger.warning("MCP 配置引用了未设置的环境变量 %s，已展开为空串", var)
            return ""
        return os.environ[var]

    return _ENV_RE.sub(_sub, value)


def _sanitize(name: str) -> str:
    """把服务器/工具名里的非 wire 安全字符替换为下划线。

    内部工具名用点号分命名空间（mcp.<server>.<tool>），远端名字里的点号
    会破坏 from_wire_name 的还原，必须净化；原始名保留用于真实调用。
    """
    return re.sub(r"[^A-Za-z0-9_-]", "_", name)


def _require_mcp_sdk() -> Any:
    """延迟导入官方 mcp SDK，缺包时报可操作的安装指引。"""
    try:
        import mcp  # noqa: F401
        from mcp import ClientSession
        from mcp.client.sse import sse_client
        from mcp.client.stdio import StdioServerParameters, stdio_client
        from mcp.client.streamable_http import streamablehttp_client
    except ImportError as e:
        raise ImportError(
            "外部 MCP 桥接需要官方 SDK：pip install 'mcp>=1.2'"
            "（或在本仓库执行 pip install -e '.[mcp]'）"
        ) from e
    import types
    return types.SimpleNamespace(
        ClientSession=ClientSession,
        sse_client=sse_client,
        stdio_client=stdio_client,
        StdioServerParameters=StdioServerParameters,
        streamablehttp_client=streamablehttp_client,
    )


@dataclass
class MCPServerConfig:
    """一台外部 MCP 服务器的连接声明。

    transport:
      stdio  本地子进程（command + args），最常见（npx/uvx 拉起的社区服务器）
      http   Streamable HTTP（url），MCP 当前推荐的远程传输
      sse    旧版 HTTP+SSE（url），为存量服务器保留
    """

    name: str
    transport: str = "stdio"
    # ── stdio ──
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str = ""
    # ── http / sse ──
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    # ── 通用 ──
    enabled: bool = True
    call_timeout: float = 120.0        # 单次工具调用超时（秒）
    connect_timeout: float = 30.0      # 建立连接 + initialize 超时（秒）
    tool_allowlist: Optional[list[str]] = None   # 只注册这些远端工具（None = 全部）
    tool_blocklist: Optional[list[str]] = None   # 排除这些远端工具

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("MCP 服务器必须提供 name")
        self.transport = (self.transport or "stdio").lower()
        if self.transport not in ("stdio", "http", "sse"):
            raise ValueError(f"MCP 服务器 {self.name}: 未知传输类型 {self.transport!r}"
                             "（支持 stdio / http / sse）")
        if self.transport == "stdio" and not self.command:
            raise ValueError(f"MCP 服务器 {self.name}: stdio 传输必须提供 command")

    @classmethod
    def from_dict(cls, data: dict) -> "MCPServerConfig":
        known = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        # 字符串字段做 ${VAR} 展开（密钥走环境变量；args/env/headers 里的值同样处理）
        for key in ("command", "cwd", "url"):
            if isinstance(known.get(key), str):
                known[key] = _expand_env(known[key])
        for key in ("args",):
            if isinstance(known.get(key), list):
                known[key] = [_expand_env(v) if isinstance(v, str) else v for v in known[key]]
        for key in ("env", "headers"):
            if isinstance(known.get(key), dict):
                known[key] = {k: _expand_env(v) if isinstance(v, str) else v
                              for k, v in known[key].items()}
        return cls(**known)

    def to_dict(self) -> dict:
        return {
            "name": self.name, "transport": self.transport,
            "command": self.command, "args": list(self.args),
            "env": dict(self.env), "cwd": self.cwd,
            "url": self.url, "headers": dict(self.headers),
            "enabled": self.enabled,
            "call_timeout": self.call_timeout,
            "connect_timeout": self.connect_timeout,
            "tool_allowlist": list(self.tool_allowlist) if self.tool_allowlist else None,
            "tool_blocklist": list(self.tool_blocklist) if self.tool_blocklist else None,
        }


class MCPManager:
    """管理多台外部 MCP 服务器的连接，并把它们的工具注册进 ToolRegistry。

    单服务器失败隔离：一台连不上只影响它自己的工具，其余服务器照常工作；
    失败信息进 status()，调用侧拿到 ToolResult.fail 而不是异常。
    """

    def __init__(self, servers: Optional[list[MCPServerConfig]] = None):
        self.servers: dict[str, MCPServerConfig] = {}
        for cfg in servers or []:
            if cfg.name in self.servers:
                raise ValueError(f"MCP 服务器重名: {cfg.name}")
            self.servers[cfg.name] = cfg
        # name → 运行态
        self._sessions: dict[str, Any] = {}
        self._stacks: dict[str, AsyncExitStack] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._status: dict[str, dict] = {}
        # name → 已注册进 registry 的内部工具名列表（refresh / close 清理用）
        self._registered: dict[str, list[str]] = {}
        self._registry: Optional[ToolRegistry] = None

    # ── 构造入口 ──

    @classmethod
    def from_config(cls, config: Any) -> "MCPManager":
        """从 dict/list 构造。接受 {"servers": [...]} 或裸 list [...]。"""
        if isinstance(config, dict):
            # `or []`：YAML 里只写 `servers:`（空值）时 get 返回 None，不能进迭代
            servers = config.get("servers") or []
        elif isinstance(config, list):
            servers = config
        else:
            raise TypeError(f"MCP 配置必须是 dict 或 list，得到 {type(config).__name__}")
        return cls([MCPServerConfig.from_dict(s) for s in servers])

    @classmethod
    def from_yaml(cls, path: str | Path) -> "MCPManager":
        """从 YAML 文件构造（支持 ~/ 展开）。文件格式见仓库根 mcp_servers.yaml。"""
        import yaml

        p = Path(os.path.expanduser(str(path)))
        if not p.exists():
            raise FileNotFoundError(f"MCP 配置文件不存在: {p}")
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return cls.from_config(data)

    # ── 连接管理 ──

    @property
    def registry(self) -> Optional[ToolRegistry]:
        return self._registry

    async def _open_session(self, cfg: MCPServerConfig, stack: AsyncExitStack) -> Any:
        """按传输类型建立连接并完成 initialize，返回 ClientSession。

        测试注记：本方法是协议边界，单测可覆写它注入桩会话（不起子进程/网络）。
        """
        sdk = _require_mcp_sdk()
        if cfg.transport == "stdio":
            params = sdk.StdioServerParameters(
                command=cfg.command,
                args=list(cfg.args),
                env={k: v for k, v in cfg.env.items()} if cfg.env else None,
                cwd=cfg.cwd or None,
            )
            cm = sdk.stdio_client(params)
        elif cfg.transport == "http":
            cm = sdk.streamablehttp_client(cfg.url, headers=cfg.headers or None)
        else:
            cm = sdk.sse_client(cfg.url, headers=cfg.headers or None)

        # 三种传输 yield 的都是 (read, write[, get_session_id])，统一取前两个
        streams = await stack.enter_async_context(cm)
        read, write = streams[0], streams[1]
        session = await stack.enter_async_context(sdk.ClientSession(read, write))
        await asyncio.wait_for(session.initialize(), timeout=cfg.connect_timeout)
        return session

    async def ensure_connected(self, name: str) -> Any:
        """确保某服务器已连接（惰性连接入口），返回其 ClientSession。"""
        cfg = self.servers.get(name)
        if cfg is None:
            raise KeyError(f"MCP 服务器未配置: {name}")
        if name in self._sessions:
            return self._sessions[name]
        lock = self._locks.setdefault(name, asyncio.Lock())
        async with lock:
            if name in self._sessions:      # 锁内二次确认（并发首调用）
                return self._sessions[name]
            stack = AsyncExitStack()
            try:
                session = await asyncio.wait_for(
                    self._open_session(cfg, stack), timeout=cfg.connect_timeout + 10)
            except Exception as e:  # noqa: BLE001
                await stack.aclose()
                self._status[name] = {"connected": False, "tools": 0,
                                      "error": f"{type(e).__name__}: {e}"}
                raise
            self._stacks[name] = stack
            self._sessions[name] = session
            self._status[name] = {"connected": True, "tools": 0, "error": None}
            logger.info("MCP 服务器已连接: %s (%s)", name, cfg.transport)
            return session

    async def connect_all(self) -> dict[str, str]:
        """连接全部启用的服务器（失败隔离）。返回 name → 错误信息（成功为空 dict）。"""
        errors: dict[str, str] = {}
        for name, cfg in self.servers.items():
            if not cfg.enabled:
                self._status[name] = {"connected": False, "tools": 0,
                                      "error": None, "disabled": True}
                continue
            try:
                await self.ensure_connected(name)
            except Exception as e:  # noqa: BLE001
                errors[name] = f"{type(e).__name__}: {e}"
                logger.warning("MCP 服务器 %s 连接失败（已跳过）: %s", name, e)
        return errors

    async def _disconnect(self, name: str) -> None:
        """关闭某服务器的连接（容忍重复关闭）。

        持有该服务器的连接锁执行，避免与并发进行的 ensure_connected 竞态：
        否则 close() 在连接建立中途执行时，新会话会在 close 结束后才被写入
        self._sessions，变成永远无人关闭的泄漏连接。
        """
        lock = self._locks.get(name)
        if lock is not None:
            async with lock:
                self._sessions.pop(name, None)
                stack = self._stacks.pop(name, None)
        else:
            self._sessions.pop(name, None)
            stack = self._stacks.pop(name, None)
        if stack is not None:
            try:
                await stack.aclose()
            except Exception as e:  # noqa: BLE001
                logger.debug("MCP 服务器 %s 关闭时异常（已忽略）: %s", name, e)

    async def close(self) -> None:
        """关闭全部连接。应用关停（lifespan shutdown / atexit）时调用。"""
        for name in list(self._sessions):
            await self._disconnect(name)

    def close_sync(self) -> None:
        """无事件循环上下文的同步关停（Runtime.on_stop 等）。

        已在事件循环内时无法阻塞等待，只能派发后台任务 —— 关闭失败只记日志，
        不让关停路径因清理动作而失败。
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.close())
            return
        loop.create_task(self.close())
        logger.info("MCP: 检测到运行中的事件循环，close() 已转为后台任务")

    # ── 工具发现与注册 ──

    def _filter(self, cfg: MCPServerConfig, remote_name: str) -> bool:
        if cfg.tool_blocklist and remote_name in cfg.tool_blocklist:
            return False
        if cfg.tool_allowlist is not None and remote_name not in cfg.tool_allowlist:
            return False
        return True

    async def _list_remote_tools(self, name: str) -> list[Any]:
        """list_tools 并按 nextCursor 翻页，聚合全部远端工具。"""
        session = await self.ensure_connected(name)
        tools: list[Any] = []
        cursor: Optional[str] = None
        while True:
            result = await session.list_tools() if cursor is None \
                else await session.list_tools(cursor=cursor)
            tools.extend(result.tools)
            cursor = getattr(result, "nextCursor", None)
            if not cursor:
                return tools

    def _make_tool(self, cfg: MCPServerConfig, remote: Any) -> Tool:
        """把一个远端 MCP 工具包装成本地 Tool。

        parameters 原样透传 inputSchema（MCP 本身就是 JSON-Schema，与
        OpenAI function-calling 的参数描述同构，不需要转换）。
        handler 首次调用时才建立连接（惰性），返回值已是 ToolResult。
        """
        remote_name = remote.name
        full_name = f"mcp.{_sanitize(cfg.name)}.{_sanitize(remote_name)}"
        desc = (remote.description or remote_name).strip()
        schema = dict(remote.inputSchema) if getattr(remote, "inputSchema", None) \
            else {"type": "object", "properties": {}}
        manager = self

        async def _handler(**kwargs: Any) -> ToolResult:
            return await manager.call(cfg.name, remote_name, kwargs)

        return Tool(
            name=full_name,
            description=f"[MCP:{cfg.name}] {desc}",
            handler=_handler,
            parameters=schema,
            async_mode=True,
        )

    async def load_tools(self, registry: ToolRegistry) -> dict[str, str]:
        """连接全部启用服务器并把工具注册进 registry（replace=True 支持刷新）。

        返回 name → 错误信息（全部成功为空 dict）。重复调用是安全的：
        工具按全名覆盖注册，旧工具列表先清理，不会累积。
        """
        self._registry = registry
        errors: dict[str, str] = {}
        for name, cfg in self.servers.items():
            # 该服务器上一次注册的工具先摘除（服务器可能已下线/被禁用/改了工具集）。
            # 摘除必须在 enabled 判断之前：否则 refresh() 时把某服务器置为
            # disabled 后，它的旧工具会永远残留在 registry 里。
            for old in self._registered.pop(name, []):
                registry.unregister(old)
            if not cfg.enabled:
                self._status[name] = {"connected": False, "tools": 0,
                                      "error": None, "disabled": True}
                continue
            try:
                remote_tools = await self._list_remote_tools(name)
            except Exception as e:  # noqa: BLE001
                errors[name] = f"{type(e).__name__}: {e}"
                self._status[name] = {"connected": False, "tools": 0,
                                      "error": errors[name]}
                logger.warning("MCP 服务器 %s 列工具失败（已跳过）: %s", name, e)
                continue
            registered: list[str] = []
            for remote in remote_tools:
                if not self._filter(cfg, remote.name):
                    continue
                tool = self._make_tool(cfg, remote)
                registry.register(tool, replace=True)
                registered.append(tool.name)
            self._registered[name] = registered
            self._status[name] = {"connected": True, "tools": len(registered),
                                  "error": None}
            logger.info("MCP 服务器 %s 注册工具 %d 个", name, len(registered))
        return errors

    async def refresh(self, name: Optional[str] = None) -> None:
        """重连并重新注册（应对服务器端工具变更）。name 为空刷新全部启用服务器。"""
        targets = [name] if name else [n for n, c in self.servers.items() if c.enabled]
        for target in targets:
            if target not in self.servers:
                raise KeyError(f"MCP 服务器未配置: {target}")
            await self._disconnect(target)
        if self._registry is not None:
            await self.load_tools(self._registry)

    # ── 调用 ──

    async def call(self, server: str, tool: str,
                   arguments: Optional[dict] = None, *,
                   _retried: bool = False) -> ToolResult:
        """调用远端工具并映射为 ToolResult。

        超时：asyncio.wait_for 兜底（SDK 内部 read_timeout 之外再加一层）。
        重连：非超时异常（传输断开 / JSON-RPC 错误）时重连一次再试 ——
        对 UnknownTool 这类服务器端逻辑错误重连是无害的浪费，只发生一次。
        """
        cfg = self.servers.get(server)
        if cfg is None:
            return ToolResult.fail(f"MCP 服务器未配置: {server}")
        try:
            session = await self.ensure_connected(server)
        except Exception as e:  # noqa: BLE001
            return ToolResult.fail(
                f"MCP 服务器 {server} 连接失败: {e}",
                hint="检查服务器配置与进程/网络状态，或调用 mcp.refresh() 重连。")
        try:
            result = await asyncio.wait_for(
                session.call_tool(
                    tool, arguments or {},
                    read_timeout_seconds=_dt.timedelta(seconds=cfg.call_timeout)),
                timeout=cfg.call_timeout + _OUTER_TIMEOUT_MARGIN)
        except asyncio.TimeoutError:
            return ToolResult.retry(
                f"MCP 工具 {server}.{tool} 调用超时（>{cfg.call_timeout}s）",
                hint="可重试；若持续超时请检查远端服务器负载或调大 call_timeout。")
        except Exception as e:  # noqa: BLE001
            if _retried:
                return ToolResult.fail(
                    f"MCP 工具 {server}.{tool} 调用失败: {type(e).__name__}: {e}",
                    hint="连接可能已断开，可调用 mcp.refresh() 重连后重试。")
            logger.warning("MCP 调用异常，重连一次再试: %s.%s: %s", server, tool, e)
            await self._disconnect(server)
            return await self.call(server, tool, arguments, _retried=True)
        return self._to_tool_result(result, server, tool)

    @staticmethod
    def _to_tool_result(result: Any, server: str, tool: str) -> ToolResult:
        """CallToolResult → ToolResult。

        文本内容拼接为 output；structuredContent 进 data；Image/EmbeddedResource
        本轮只回计数（harness 工具结果目前是纯文本回喂，图像直通待前端多模态
        工具结果支持后再做）。
        """
        texts: list[str] = []
        images = 0
        embedded = 0
        for block in getattr(result, "content", None) or []:
            kind = getattr(block, "type", None)
            if kind == "text":
                texts.append(block.text)
            elif kind == "image":
                images += 1
            elif kind == "resource":
                embedded += 1
            else:
                texts.append(str(block))
        output = "\n".join(t for t in texts if t)
        data: dict[str, Any] = {}
        structured = getattr(result, "structuredContent", None)
        if structured is not None:
            data["structured"] = structured
        if images:
            data["images_omitted"] = images
        if embedded:
            data["resources_omitted"] = embedded
        if getattr(result, "isError", False):
            return ToolResult.fail(
                output or f"MCP 工具 {server}.{tool} 返回错误（无文本详情）",
                **data)
        return ToolResult.ok(output, **data)

    # ── 状态 ──

    def status(self) -> dict[str, dict]:
        """各服务器连接状态快照（供日志 / UI 展示）。"""
        snap: dict[str, dict] = {}
        for name, cfg in self.servers.items():
            info = dict(self._status.get(name) or
                        {"connected": False, "tools": 0, "error": None})
            info["transport"] = cfg.transport
            info["enabled"] = cfg.enabled
            snap[name] = info
        return snap

    def __repr__(self) -> str:
        connected = sum(1 for s in self._status.values() if s.get("connected"))
        return (f"<MCPManager servers={len(self.servers)} "
                f"connected={connected} tools={sum(len(v) for v in self._registered.values())}>")
