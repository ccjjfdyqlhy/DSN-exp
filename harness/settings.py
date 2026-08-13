# harness/settings.py
# 命名空间化配置 — 替代全局 Config 单例的逐步迁移路径。
#
# 设计:
#   - 每个命名空间 (Namespace) 把属性访问绑定到环境变量键
#   - 支持类型转换器 (bool / int / float)，默认值兜底
#   - 可注入自定义 loader（测试用），默认 os.environ
#
# 用法:
#     settings = Settings()
#     ns = settings.namespace("voice")
#     ns.bind_bool("tts_enabled", "TTS_ENABLED", default=True)
#     ns.bind("main_model", "MAIN_MODEL_NAME", default="deepseek-v4-flash")
#
#     settings.namespace("voice").tts_enabled   # -> bool
#
# 兼容性: 现有 .env 变量名不变，仅新增一层命名空间访问。
# 现有 config.Config 作为兼容门面继续工作，二者读取同一份环境变量。

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Optional


# ── 类型转换器 ──

def as_bool(v: Any) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def as_int(v: Any) -> int:
    return int(v)


def as_float(v: Any) -> float:
    return float(v)


# ── 单个配置项 ──

@dataclass
class Setting:
    env_key: str
    default: Any = None
    converter: Optional[Callable[[Any], Any]] = None

    def get(self, loader: Callable[[str], Optional[str]]) -> Any:
        raw = loader(self.env_key)
        if raw is None or raw == "":
            return self.default
        if self.converter is not None:
            try:
                return self.converter(raw)
            except (TypeError, ValueError):
                return self.default
        return raw


# ── 命名空间 ──

class Namespace:
    """一组配置项的命名空间。属性访问代理到环境变量绑定。"""

    def __init__(self, name: str, loader: Callable[[str], Optional[str]] = os.environ.get):
        self._name = name
        self._loader = loader
        self._bindings: dict[str, Setting] = {}

    @property
    def name(self) -> str:
        return self._name

    def bind(self, attr: str, env_key: str, default: Any = None,
             converter: Optional[Callable[[Any], Any]] = None) -> "Namespace":
        self._bindings[attr] = Setting(env_key, default, converter)
        return self

    def bind_bool(self, attr: str, env_key: str, default: bool = False) -> "Namespace":
        return self.bind(attr, env_key, default=default, converter=as_bool)

    def bind_int(self, attr: str, env_key: str, default: int = 0) -> "Namespace":
        return self.bind(attr, env_key, default=default, converter=as_int)

    def bind_float(self, attr: str, env_key: str, default: float = 0.0) -> "Namespace":
        return self.bind(attr, env_key, default=default, converter=as_float)

    def __getattr__(self, attr: str) -> Any:
        if attr.startswith("_"):
            raise AttributeError(attr)
        s = self._bindings.get(attr)
        if s is None:
            raise AttributeError(f"Namespace '{self._name}' 没有配置项 '{attr}'")
        return s.get(self._loader)

    def __contains__(self, attr: str) -> bool:
        return attr in self._bindings

    def as_dict(self) -> dict[str, Any]:
        return {k: s.get(self._loader) for k, s in self._bindings.items()}

    def __repr__(self) -> str:
        return f"<Namespace '{self._name}' bindings={len(self._bindings)}>"


# ── 配置注册表 ──

class Settings:
    """命名空间配置注册表。`settings.namespace(name)` 获取或创建命名空间。"""

    def __init__(self, loader: Optional[Callable[[str], Optional[str]]] = None):
        self._loader = loader or os.environ.get
        self._namespaces: dict[str, Namespace] = {}

    def namespace(self, name: str, *, create: bool = True) -> Optional[Namespace]:
        ns = self._namespaces.get(name)
        if ns is None and create:
            ns = Namespace(name, loader=self._loader)
            self._namespaces[name] = ns
        return ns

    def namespaces(self) -> dict[str, Namespace]:
        return dict(self._namespaces)

    def __repr__(self) -> str:
        return f"<Settings namespaces={list(self._namespaces)}>"
