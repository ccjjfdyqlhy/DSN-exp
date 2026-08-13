# harness/runtime.py
# Runtime — 场景无关的 DI 容器与生命周期管理。
#
# 用途:
#   - 提供服务的注册 / 解析（实例注册 或 惰性工厂注册）
#   - 通过 on_start / on_stop 统一管理生命周期钩子
#   - 通过 current() 提供线程/异步安全的运行时访问
#
# 用法:
#     rt = Runtime(name="dsn")
#     rt.register("db", db)
#     rt.register_factory("engine", lambda: create_engine(rt.get("db")))
#
#     engine = rt.resolve("engine")
#
#     rt.set_default()          # 全局兜底，任何线程可用 Runtime.current()
#     with Runtime.activate(rt):  # 或按异步上下文覆盖
#         ...  # Runtime.current() 返回 rt
#
# 键归一化: 接受 str 或 type；type 归一化为 "module.QualName"，避免跨模块撞名。

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable, Iterator, Optional

logger = logging.getLogger("harness.runtime")

_current_runtime: ContextVar["Runtime | None"] = ContextVar("harness_runtime", default=None)
_default_runtime: Optional["Runtime"] = None


def _key(key: Any) -> str:
    if isinstance(key, str):
        return key
    if isinstance(key, type):
        return f"{key.__module__}.{key.__qualname__}"
    raise TypeError(f"服务键必须是 str 或 type, 得到 {type(key).__name__}")


class Runtime:
    """DI 容器。服务按键注册，支持惰性工厂与生命周期钩子。"""

    def __init__(self, *, name: str = "default"):
        self.name = name
        self._services: dict[str, Any] = {}
        self._factories: dict[str, Callable[[], Any]] = {}
        self._start_hooks: list[Callable[[], None]] = []
        self._stop_hooks: list[Callable[[], None]] = []
        self._started = False

    # ── 注册 ──

    def register(self, key: Any, instance: Any, *, replace: bool = False) -> "Runtime":
        k = _key(key)
        self._check_collision(k, replace)
        self._services[k] = instance
        self._factories.pop(k, None)
        return self

    def register_factory(self, key: Any, factory: Callable[[], Any],
                         *, replace: bool = False) -> "Runtime":
        k = _key(key)
        self._check_collision(k, replace)
        self._factories[k] = factory
        self._services.pop(k, None)
        return self

    def register_all(self, *, replace: bool = False, **kwargs: Any) -> "Runtime":
        for k, v in kwargs.items():
            self.register(k, v, replace=replace)
        return self

    def _check_collision(self, k: str, replace: bool) -> None:
        if not replace and (k in self._services or k in self._factories):
            raise KeyError(f"服务已注册: {k} (replace=True 可覆盖)")

    # ── 查询 ──

    def has(self, key: Any) -> bool:
        k = _key(key)
        return k in self._services or k in self._factories

    def get(self, key: Any, default: Any = None) -> Any:
        try:
            return self.resolve(key)
        except KeyError:
            return default

    def resolve(self, key: Any) -> Any:
        k = _key(key)
        if k in self._services:
            return self._services[k]
        if k in self._factories:
            instance = self._factories[k]()
            self._services[k] = instance
            return instance
        raise KeyError(f"服务未注册: {k}")

    def keys(self) -> set[str]:
        return set(self._services) | set(self._factories)

    def snapshot(self) -> dict[str, Any]:
        """已解析服务快照（不含未解析的工厂）。"""
        return dict(self._services)

    # ── 生命周期 ──

    def on_start(self, hook: Callable[[], None]) -> "Runtime":
        self._start_hooks.append(hook)
        return self

    def on_stop(self, hook: Callable[[], None]) -> "Runtime":
        self._stop_hooks.append(hook)
        return self

    def start(self) -> "Runtime":
        if self._started:
            logger.debug("Runtime '%s' 已启动, 忽略重复 start", self.name)
            return self
        for hook in self._start_hooks:
            try:
                hook()
            except Exception:
                logger.exception("Runtime '%s' start hook 异常", self.name)
        self._started = True
        logger.info("Runtime '%s' 已启动 (%d 服务, %d 工厂)",
                    self.name, len(self._services), len(self._factories))
        return self

    def stop(self) -> "Runtime":
        if not self._started:
            logger.debug("Runtime '%s' 未启动, 忽略 stop", self.name)
            return self
        for hook in reversed(self._stop_hooks):
            try:
                hook()
            except Exception:
                logger.exception("Runtime '%s' stop hook 异常", self.name)
        self._started = False
        logger.info("Runtime '%s' 已停止", self.name)
        return self

    @property
    def started(self) -> bool:
        return self._started

    # ── 上下文 ──

    def set_current(self) -> "Runtime":
        """仅当前（异步）上下文内生效。"""
        _current_runtime.set(self)
        return self

    def set_default(self) -> "Runtime":
        """全局兜底运行时，任何线程 / 上下文均可通过 current() 取到。"""
        global _default_runtime
        _default_runtime = self
        return self

    @classmethod
    def current(cls) -> Optional["Runtime"]:
        rt = _current_runtime.get()
        return rt if rt is not None else _default_runtime

    @classmethod
    @contextmanager
    def activate(cls, rt: "Runtime") -> Iterator["Runtime"]:
        """上下文管理器: 进入时设置当前运行时, 退出时恢复。"""
        token = _current_runtime.set(rt)
        try:
            yield rt
        finally:
            _current_runtime.reset(token)

    def __repr__(self) -> str:
        return f"<Runtime '{self.name}' started={self._started} services={len(self._services)}>"
