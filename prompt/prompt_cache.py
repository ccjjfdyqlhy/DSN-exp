# prompt/prompt_cache.py
# PromptCache — 提示词缓存系统，支持 <help> 标签检索
# v1.0 — 基于向量相似度的提示词检索

import struct
import threading
import logging
from typing import Optional

from config import Config
from models import EmbeddingClient

logger = logging.getLogger("PromptCache")


class PromptCache:
    """
    提示词缓存系统。
    
    职责:
    - 将提示词按文件分组存储到 prompt_cache 表
    - 为每个提示词生成嵌入向量
    - 支持 <help> 标签的向量检索
    """

    def __init__(
        self,
        db,
        embedding_client: Optional[EmbeddingClient] = None,
    ):
        self.db = db
        self._ec = embedding_client
        self._embedding_enabled = (
            embedding_client is not None and Config.MEMORY_EMBEDDING_ENABLED
        )
        self._lock = threading.Lock()
        
        if not self._embedding_enabled:
            logger.info("PromptCache: 向量嵌入未启用 (MEMORY_EMBEDDING_ENABLED=false)，仅使用关键词搜索")
        else:
            logger.info("PromptCache: 向量嵌入已启用")

    def index_prompts(
        self,
        uid: int,
        chat_id: int,
        prompts: list[dict],
    ) -> int:
        """
        索引提示词到 prompt_cache 表。
        
        :param uid: 用户 ID
        :param chat_id: 聊天 ID
        :param prompts: 提示词列表，每个元素为 {
            "category": str,
            "source_file": str,
            "content": str
        }
        :return: 索引的提示词数量
        """
        if not prompts:
            return 0

        conn = self.db._get_connection()
        count = 0

        for prompt in prompts:
            category = prompt.get("category", "unknown")
            source_file = prompt.get("source_file", "")
            content = prompt.get("content", "")
            
            if not content or not source_file:
                continue

            # 生成嵌入向量
            embedding_blob = None
            if self._embedding_enabled and self._ec:
                embedding = self._ec.embed(content)
                if embedding:
                    embedding_blob = self._vec_to_blob(embedding)

            try:
                conn.execute("""
                    INSERT OR REPLACE INTO prompt_cache 
                    (uid, chat_id, category, source_file, content, embedding, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                """, (uid, chat_id, category, source_file, content, embedding_blob))
                count += 1
            except Exception as e:
                logger.error("索引提示词失败 %s: %s", source_file, e)

        conn.commit()
        logger.info("已索引 %d 条提示词 (uid=%d, chat_id=%d)", count, uid, chat_id)
        return count

    def search(
        self,
        uid: int,
        chat_id: int,
        query: str,
        limit: int = 3,
        category: Optional[str] = None,
    ) -> list[dict]:
        """
        搜索提示词（向量相似度 + 关键词匹配）。
        
        :param uid: 用户 ID
        :param chat_id: 聊天 ID
        :param query: 搜索查询
        :param limit: 返回结果数量
        :param category: 可选的类别过滤
        :return: 匹配的提示词列表
        """
        conn = self.db._get_connection()
        results = []

        # 1. 向量搜索（如果启用）
        if self._embedding_enabled and self._ec:
            query_vec = self._ec.embed(query)
            if query_vec:
                results = self._vector_search(uid, chat_id, query_vec, limit, category)

        # 2. 关键词搜索作为补充
        if len(results) < limit:
            keyword_results = self._keyword_search(uid, chat_id, query, limit - len(results), category)
            # 去重
            existing_files = {r["source_file"] for r in results}
            for kr in keyword_results:
                if kr["source_file"] not in existing_files:
                    results.append(kr)
                    existing_files.add(kr["source_file"])

        return results[:limit]

    def _vector_search(
        self,
        uid: int,
        chat_id: int,
        query_vec: list[float],
        limit: int,
        category: Optional[str],
    ) -> list[dict]:
        """向量相似度搜索"""
        conn = self.db._get_connection()
        
        # 构建查询
        sql = """
            SELECT id, category, source_file, content, embedding
            FROM prompt_cache
            WHERE uid = ? AND chat_id = ? AND embedding IS NOT NULL
        """
        params = [uid, chat_id]
        
        if category:
            sql += " AND category = ?"
            params.append(category)
        
        sql += " ORDER BY id DESC"  # 优先最新的
        
        try:
            rows = conn.execute(sql, params).fetchall()
        except Exception as e:
            logger.error("向量搜索查询失败: %s", e)
            return []

        # 计算相似度
        scored_results = []
        for row in rows:
            embedding_blob = row["embedding"]
            if not embedding_blob:
                continue
            
            vec = self._blob_to_vec(embedding_blob)
            if not vec:
                continue
            
            similarity = self._cosine_similarity(query_vec, vec)
            if similarity > 0.3:  # 阈值
                scored_results.append({
                    "id": row["id"],
                    "category": row["category"],
                    "source_file": row["source_file"],
                    "content": row["content"],
                    "similarity": similarity,
                })

        # 按相似度排序
        scored_results.sort(key=lambda x: x["similarity"], reverse=True)
        return scored_results[:limit]

    def _keyword_search(
        self,
        uid: int,
        chat_id: int,
        query: str,
        limit: int,
        category: Optional[str],
    ) -> list[dict]:
        """关键词搜索"""
        conn = self.db._get_connection()
        
        # 提取关键词
        keywords = [k for k in query.split() if len(k) > 1]
        if not keywords:
            return []

        # 构建 LIKE 条件
        conditions = []
        params = [uid, chat_id]
        for kw in keywords[:5]:  # 限制关键词数量
            conditions.append("content LIKE ?")
            params.append(f"%{kw}%")

        sql = f"""
            SELECT id, category, source_file, content
            FROM prompt_cache
            WHERE uid = ? AND chat_id = ? AND ({' OR '.join(conditions)})
        """
        
        if category:
            sql += " AND category = ?"
            params.append(category)
        
        sql += f" LIMIT ?"
        params.append(limit)

        try:
            rows = conn.execute(sql, params).fetchall()
            return [
                {
                    "id": row["id"],
                    "category": row["category"],
                    "source_file": row["source_file"],
                    "content": row["content"],
                    "similarity": 0.5,  # 关键词匹配给一个中等分数
                }
                for row in rows
            ]
        except Exception as e:
            logger.error("关键词搜索失败: %s", e)
            return []

    def clear(self, uid: int, chat_id: int) -> int:
        """清除指定聊天的提示词缓存"""
        conn = self.db._get_connection()
        cursor = conn.execute(
            "DELETE FROM prompt_cache WHERE uid = ? AND chat_id = ?",
            (uid, chat_id)
        )
        conn.commit()
        count = cursor.rowcount
        logger.info("已清除 %d 条提示词缓存 (uid=%d, chat_id=%d)", count, uid, chat_id)
        return count

    @staticmethod
    def _vec_to_blob(vec: list[float]) -> bytes:
        """将向量转换为 BLOB 存储"""
        return struct.pack(f"{len(vec)}f", *vec)

    @staticmethod
    def _blob_to_vec(blob: bytes) -> Optional[list[float]]:
        """将 BLOB 转换回向量"""
        if not blob:
            return None
        try:
            count = len(blob) // 4  # float32 = 4 bytes
            return list(struct.unpack(f"{count}f", blob))
        except Exception:
            return None

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """计算余弦相似度"""
        if len(a) != len(b):
            return 0.0
        
        dot_product = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        
        if norm_a == 0 or norm_b == 0:
            return 0.0
        
        return dot_product / (norm_a * norm_b)
