# apps/dsn_study/memory/embeddings.py
# OpenAI 兼容嵌入客户端（dsn_study 版）。
#
# dsn 原版 EmbeddingClient 与其模型层耦合；study 版是独立的最小实现：
# POST {base_url}/embeddings，兼容 OpenAI / LM Studio / Ollama(openai 兼容口)。
# 返回 None 表示失败（MemorySystem 会静默降级为纯关键词检索）。
#
# ⚠️ 两个必须有的护栏（踩过的坑）：
#
# 1. **超时必须短**。embedding 只用于话题语义打分，是"锦上添花"，
#    不是回答问题的主路径。而一轮对话里会调 2 次（查询 + 存消息），
#    60s 的超时 × 2 = 120s，正好把客户端的读超时耗尽 —— 表现为
#    "按下空格没反应"，其实卡在一次 embedding 请求上。
#    默认降到 8s，可用 MEMORY_EMBEDDING_TIMEOUT 覆盖。
#
# 2. **要有熔断**。嵌入端点挂掉时会连续失败（实测 88 次），
#    每次都白等到超时。连续失败达阈值后直接跳过一段时间，
#    期间走关键词检索，不再打这个端点。

from __future__ import annotations

import logging
import os
import time
from typing import Optional

import requests

logger = logging.getLogger("MemoryEmbedding")

#: 单次请求超时（秒）—— 短超时是刻意的，见文件头说明
DEFAULT_TIMEOUT = float(os.environ.get("MEMORY_EMBEDDING_TIMEOUT", "8"))
#: 连接超时（秒）
CONNECT_TIMEOUT = float(os.environ.get("MEMORY_EMBEDDING_CONNECT_TIMEOUT", "3"))
#: 连续失败多少次后熔断
FAIL_THRESHOLD = int(os.environ.get("MEMORY_EMBEDDING_FAIL_THRESHOLD", "3"))
#: 熔断冷却时长（秒）
FAIL_COOLDOWN = float(os.environ.get("MEMORY_EMBEDDING_FAIL_COOLDOWN", "300"))


class OpenAIEmbeddingClient:
    def __init__(self, base_url: str, api_key: str = "",
                 model: str = "text-embedding-nomic-embed-text-v1.5@f16",
                 timeout: int = 0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = float(timeout) if timeout else DEFAULT_TIMEOUT
        #: 熔断状态
        self._fail_count = 0
        self._open_until = 0.0

    # ── 熔断 ──

    def _is_open(self) -> bool:
        return time.time() < self._open_until

    def _record_failure(self, err: Exception) -> None:
        self._fail_count += 1
        if self._fail_count >= FAIL_THRESHOLD and not self._is_open():
            self._open_until = time.time() + FAIL_COOLDOWN
            logger.warning(
                "embedding 连续失败 %d 次，熔断 %.0fs（期间降级为关键词检索）: %s",
                self._fail_count, FAIL_COOLDOWN, err)
        else:
            logger.warning("embedding 请求失败（降级为关键词检索）: %s", err)

    def _record_success(self) -> None:
        if self._fail_count:
            logger.info("embedding 恢复正常（此前连续失败 %d 次）", self._fail_count)
        self._fail_count = 0
        self._open_until = 0.0

    # ── 主流程 ──

    def embed(self, text: str) -> Optional[list[float]]:
        """返回嵌入向量；失败返回 None（不抛异常，记忆路径不因嵌入故障中断）。"""
        if not text or not text.strip():
            return None
        if self._is_open():
            # 熔断期：直接走关键词检索，不打端点
            return None
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            resp = requests.post(
                f"{self.base_url}/embeddings",
                json={"model": self.model, "input": text},
                headers=headers,
                # (连接超时, 读超时) —— 分开设，别让连接建立也吃掉整个预算
                timeout=(CONNECT_TIMEOUT, self.timeout),
            )
            resp.raise_for_status()
            data = resp.json()
            vec = data["data"][0]["embedding"]
            self._record_success()
            return vec
        except Exception as e:
            self._record_failure(e)
            return None

    def __repr__(self):
        return (f"<OpenAIEmbeddingClient base={self.base_url} "
                f"model={self.model} timeout={self.timeout}s>")
