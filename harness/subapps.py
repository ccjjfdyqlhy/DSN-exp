# harness/subapps.py
# AppBundle — 应用场景包抽象基类。
#
# 一个 AppBundle 是一个可独立装卸的"应用"，声明它需要的
# 技能 / 插件 / 任务 / 路由 / 存储 / 配置命名空间。
#
# harness 核心只提供框架与生命周期；具体的应用语义（语音、人格、提醒……）
# 都由 AppBundle 通过 install/start/stop 装配到 Runtime 上。
#
# 生命周期:
#     runtime 就绪 → bundle.install(runtime)   # 注册服务、技能、任务、路由
#     runtime.start() → bundle.start(runtime)  # 启动后台线程、加载模型
#     runtime.stop()  → bundle.stop()          # 释放资源

from __future__ import annotations

from typing import Any

from .runtime import Runtime


class AppBundle:
    """应用场景包基类。子类需设置 name/version，并按需覆写生命周期方法。"""

    name: str = ""
    version: str = "1.0"
    description: str = ""

    # 本 bundle 使用的配置命名空间名（harness.settings.Settings.namespace）
    settings_namespaces: list[str] = []

    # 本 bundle 声明的 Web 蓝图（Flask Blueprint 等，交由网关挂载）
    blueprints: list[Any] = []

    def install(self, runtime: Runtime) -> None:
        """向 Runtime 注册本 bundle 的服务。在 runtime.start() 之前调用。"""

    def start(self, runtime: Runtime) -> None:
        """启动本 bundle 的资源。"""

    def stop(self) -> None:
        """释放本 bundle 的资源。"""

    def register_routes(self, gateway: Any) -> None:
        """把本 bundle 的路由挂载到网关。默认挂载 self.blueprints。"""
        for bp in self.blueprints:
            gateway.register_blueprint(bp)

    def __repr__(self) -> str:
        return f"<AppBundle name={self.name!r} version={self.version!r}>"


class AppBundleRegistry:
    """AppBundle 注册与装配器。"""

    def __init__(self, runtime: Runtime):
        self._runtime = runtime
        self._bundles: list[AppBundle] = []
        self._installed: set[str] = set()

    def add(self, bundle: AppBundle) -> "AppBundleRegistry":
        if bundle.name in self._installed:
            raise KeyError(f"bundle 已注册: {bundle.name}")
        self._bundles.append(bundle)
        self._installed.add(bundle.name)
        return self

    def bundles(self) -> list[AppBundle]:
        return list(self._bundles)

    def install_all(self) -> "AppBundleRegistry":
        for bundle in self._bundles:
            bundle.install(self._runtime)
        return self

    def start_all(self) -> "AppBundleRegistry":
        for bundle in self._bundles:
            bundle.start(self._runtime)
        return self

    def stop_all(self) -> None:
        for bundle in reversed(self._bundles):
            bundle.stop()

    def __repr__(self) -> str:
        return f"<AppBundleRegistry bundles={[b.name for b in self._bundles]}>"
