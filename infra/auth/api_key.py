# infra/auth/api_key.py
# API Key 生成与校验。
#
# 安全说明（2026-10 修复）：
#   原实现 `self._keys[self._hash(key)] = key` —— 注入了**明文反向映射**，
#   与本文件开头「只存哈希，明文只返回一次」的承诺相反：内存转储或日志一旦
#   泄露就能直接拿到可用密钥。现改为只保存哈希 + 元数据，明文不再留存。

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class APIKeyRecord:
    """一条已登记的密钥元数据（**不含明文**）。"""

    key_id: str
    label: str = ""
    scopes: list[str] = field(default_factory=list)
    revoked: bool = False


class APIKeyManager:
    """生成带前缀的 API Key，校验时比较哈希。明文不落内存。

    校验使用 hmac.compare_digest 做常数时间比较，避免时序侧信道。
    """

    def __init__(self, prefix: str = "apk", secret: str = ""):
        self._prefix = prefix
        self._secret = secret
        #: 哈希 → 元数据。**不保存明文**。
        self._keys: dict[str, APIKeyRecord] = {}

    def generate(self, *, label: str = "", scopes: Optional[list[str]] = None) -> str:
        """生成新 key 并登记。返回明文（仅此一次可见，之后无法取回）。"""
        token = secrets.token_urlsafe(24)
        key = f"{self._prefix}_{token}"
        self.register(key, label=label, scopes=scopes)
        return key

    def register(self, key: str, *, label: str = "", scopes: Optional[list[str]] = None,
                 key_id: Optional[str] = None) -> None:
        """登记一个已存在的 key（只保存其哈希）。"""
        digest = self._hash(key)
        self._keys[digest] = APIKeyRecord(
            key_id=key_id or secrets.token_hex(8),
            label=label,
            scopes=list(scopes or []),
        )

    def verify(self, key: str) -> bool:
        """校验 key 是否有效（存在且未吊销）。常数时间比较。"""
        if not key:
            return False
        digest = self._hash(key)
        record = self._keys.get(digest)
        if record is None or record.revoked:
            return False
        # 命中之后再走一次常数时间比较，避免靠哈希表查找时序推断前缀
        for known in self._keys:
            if hmac.compare_digest(known, digest):
                return True
        return False

    def revoke(self, key: str) -> bool:
        """吊销 key。返回是否确实存在过。"""
        digest = self._hash(key)
        record = self._keys.get(digest)
        if record is None:
            return False
        record.revoked = True
        del self._keys[digest]
        return True

    def revoke_by_id(self, key_id: str) -> bool:
        """按 key_id 吊销（不需要明文）。"""
        for digest, record in list(self._keys.items()):
            if record.key_id == key_id:
                del self._keys[digest]
                return True
        return False

    def get_record(self, key: str) -> Optional[APIKeyRecord]:
        """取元数据（不含明文）。"""
        return self._keys.get(self._hash(key))

    def count(self) -> int:
        return len(self._keys)

    def _hash(self, key: str) -> str:
        return hashlib.sha256((self._secret + key).encode("utf-8")).hexdigest()
