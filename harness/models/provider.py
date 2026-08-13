# harness/models/provider.py
# ModelProviderRegistry — 可插拔模型后端注册。
#
# 按 (model_type, model_name) 解析对话/嵌入客户端，支持惰性工厂。
# 应用通过 registry 注册自己的模型后端，AgentLoop 等只依赖 IChatClient 接口。

from __future__ import annotations

from typing import Callable, Optional

from .base import IChatClient, IEmbeddingClient


class ModelProviderRegistry:
    """模型提供商注册表。"""

    def __init__(self):
        self._chat_factories: dict[str, Callable[[], IChatClient]] = {}
        self._embedding_factories: dict[str, Callable[[], IEmbeddingClient]] = {}
        self._chat_instances: dict[str, IChatClient] = {}
        self._embedding_instances: dict[str, IEmbeddingClient] = {}

    def register_chat(self, key: str, factory: Callable[[], IChatClient],
                      *, replace: bool = False) -> "ModelProviderRegistry":
        if key in self._chat_factories and not replace:
            raise KeyError(f"对话模型后端已注册: {key}")
        self._chat_factories[key] = factory
        self._chat_instances.pop(key, None)
        return self

    def register_embedding(self, key: str, factory: Callable[[], IEmbeddingClient],
                           *, replace: bool = False) -> "ModelProviderRegistry":
        if key in self._embedding_factories and not replace:
            raise KeyError(f"嵌入模型后端已注册: {key}")
        self._embedding_factories[key] = factory
        self._embedding_instances.pop(key, None)
        return self

    def get_chat_client(self, key: str) -> IChatClient:
        if key not in self._chat_instances:
            if key not in self._chat_factories:
                raise KeyError(f"对话模型后端未注册: {key}")
            self._chat_instances[key] = self._chat_factories[key]()
        return self._chat_instances[key]

    def get_embedding_client(self, key: str) -> Optional[IEmbeddingClient]:
        if key not in self._embedding_instances:
            if key not in self._embedding_factories:
                return None
            self._embedding_instances[key] = self._embedding_factories[key]()
        return self._embedding_instances[key]

    def chat_keys(self) -> list[str]:
        return list(self._chat_factories.keys())

    def embedding_keys(self) -> list[str]:
        return list(self._embedding_factories.keys())
