# apps/dsn_study/memory/embeddings.py
# OpenAI 兼容嵌入客户端（dsn_study 版）。
#
# dsn 原版 EmbeddingClient 与其模型层耦合；study 版是独立的最小实现：
# POST {base_url}/embeddings，兼容 OpenAI / LM Studio / Ollama(openai 兼容口)。
# 返回 None 表示失败（MemorySystem 会静默降级为纯关键词检索）。

from __future__ import annotations

import logging
from typing import Optional

import requests

logger = logging.getLogger("MemoryEmbedding")


class OpenAIEmbeddingClient:
    def __init__(self, base_url: str, api_key: str = "",
                 model: str = "text-embedding-nomic-embed-text-v1.5@f16",
                 timeout: int = 60):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def embed(self, text: str) -> Optional[list[float]]:
        """返回嵌入向量；失败返回 None（不抛异常，记忆路径不因嵌入故障中断）。"""
        if not text or not text.strip():
            return None
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            resp = requests.post(
                f"{self.base_url}/embeddings",
                json={"model": self.model, "input": text},
                headers=headers, timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["data"][0]["embedding"]
        except Exception as e:
            logger.warning("embedding 请求失败（降级为关键词检索）: %s", e)
            return None

    def __repr__(self):
        return f"<OpenAIEmbeddingClient base={self.base_url} model={self.model}>"
