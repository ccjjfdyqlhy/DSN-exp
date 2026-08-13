# harness/auth/api_key.py
# API Key 生成与校验 — 只存哈希，明文只返回一次。

from __future__ import annotations

import hashlib
import secrets
from typing import Optional


class APIKeyManager:
    """生成带前缀的 API Key，校验时比较 SHA-256 哈希。"""

    def __init__(self, prefix: str = "apk", secret: str = ""):
        self._prefix = prefix
        self._secret = secret
        self._keys: dict[str, str] = {}   # 明文 → sha256（测试/内存用）

    def generate(self, *, label: str = "", scopes: Optional[list[str]] = None) -> str:
        """生成新 key 并登记。返回明文（仅此一次可见）。"""
        token = secrets.token_urlsafe(24)
        key = f"{self._prefix}_{token}"
        self.register(key, label=label, scopes=scopes)
        return key

    def register(self, key: str, *, label: str = "", scopes: Optional[list[str]] = None) -> None:
        self._keys[self._hash(key)] = key

    def verify(self, key: str) -> bool:
        return self._hash(key) in self._keys

    def revoke(self, key: str) -> bool:
        return self._keys.pop(self._hash(key), None) is not None

    def count(self) -> int:
        return len(self._keys)

    def _hash(self, key: str) -> str:
        return hashlib.sha256((self._secret + key).encode("utf-8")).hexdigest()
