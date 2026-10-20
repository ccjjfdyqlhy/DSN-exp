# harness/memory/vector.py
# 向量原语 —— **兼容层**。
#
# 实现已下沉到 infra/vector.py（原因见那里文件头的说明：避免 infra ↔ harness
# 循环依赖）。本模块保留原有的导入路径，保证 `from harness.memory import
# cosine_similarity` 等历史写法继续可用。
#
# 新代码请直接用 infra.vector。

from __future__ import annotations

from infra.vector import (
    VectorIndex,
    cosine_similarity,
    pack_embedding,
    unpack_embedding,
)

__all__ = ["VectorIndex", "cosine_similarity", "pack_embedding", "unpack_embedding"]
