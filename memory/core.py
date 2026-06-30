# memory/core.py
# MemorySystem — 单文件单类，第一性原理重设计
# v3.0 — 替换旧的 MemoryManager + MemoryRecallEngine

import json
import math
import re
import struct
import threading
import time
import logging
from datetime import datetime
from typing import Optional

from config import Config
from db.chat import ChatDBManager, _tokenize
from models import LMSummaryModel, EmbeddingClient

logger = logging.getLogger("MemorySystem")

_RECALL_RE = re.compile(r"<recall>\s*(.*?)\s*</recall>", re.DOTALL)
_MEMO_RE = re.compile(r"<memo>(.*?)</memo>", re.DOTALL)

MAX_DETAIL_CHARS_PER_ROUND = 4000
MAX_TOTAL_DETAIL_CHARS = 16000


class MemorySystem:
    def __init__(
        self,
        db: ChatDBManager,
        summary_model: Optional[LMSummaryModel] = None,
        embedding_client: Optional[EmbeddingClient] = None,
    ):
        self.db = db
        self.summary_model = summary_model or LMSummaryModel()
        self._ec = embedding_client
        self._embedding_enabled = (
            embedding_client is not None and Config.MEMORY_EMBEDDING_ENABLED
        )
        self._lock = threading.Lock()
        self._init_table()

    def _init_table(self):
        conn = self.db._get_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_v2 (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                chat_id    INTEGER NOT NULL,
                type       TEXT NOT NULL CHECK(type IN ('exp', 'memo')),
                round      INTEGER,
                content    TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_mem_v2_lookup "
            "ON memory_v2(user_id, chat_id, type, round)"
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_embeds (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                chat_id    INTEGER NOT NULL,
                round      INTEGER NOT NULL,
                embedding  BLOB NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                UNIQUE(user_id, chat_id, round)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_mem_embeds_lookup "
            "ON memory_embeds(user_id, chat_id, round)"
        )
        conn.commit()

    # ---- crypto ----

    def _encrypt(self, user_id: int, text: str) -> str:
        return self.db._cipher.encrypt(user_id, text)

    def _decrypt(self, user_id: int, text: str) -> str:
        if not text:
            return ""
        return self.db._cipher.decrypt(user_id, text)

    # =================================================================
    # 摘要生成 (经验记忆)
    # =================================================================

    def summarize_turn(
        self,
        user_id: int,
        chat_id: int,
        round_idx: int,
        user_msg: str,
        assistant_reply: str,
        async_mode: bool = True,
    ) -> Optional[int]:
        """对一轮对话生成 LLM 摘要并持久化。"""
        marked = (
            getattr(user_msg, "skip_memory", False)
            if isinstance(user_msg, dict)
            else False
        )
        if marked:
            return None

        if async_mode and Config.MEMORY_ASYNC_ENABLED:
            threading.Thread(
                target=self._do_summarize,
                args=(user_id, chat_id, round_idx, user_msg, assistant_reply),
                daemon=True,
            ).start()
            return None
        return self._do_summarize(user_id, chat_id, round_idx, user_msg, assistant_reply)

    def _do_summarize(self, user_id, chat_id, round_idx, user_msg, assistant_reply):
        try:
            summary = self.summary_model.summarize_dialog(
                [
                    {"role": "user", "content": user_msg},
                    {"role": "assistant", "content": assistant_reply},
                ],
                max_length=Config.MEMORY_SUMMARY_LENGTH,
            )
            if not summary:
                return None

            encrypted = self._encrypt(user_id, summary)
            conn = self.db._get_connection()
            with self._lock:
                cursor = conn.execute(
                    "INSERT INTO memory_v2 (user_id, chat_id, type, round, content) "
                    "VALUES (?, ?, 'exp', ?, ?)",
                    (user_id, chat_id, round_idx, encrypted),
                )
                memory_id = cursor.lastrowid
                conn.commit()

            if self._embedding_enabled:
                self._embed_raw_round(user_id, chat_id, round_idx, user_msg, assistant_reply)

            return memory_id
        except Exception:
            logger.exception("Summarize failed uid=%d chat=%d round=%d", user_id, chat_id, round_idx)
            return None

    def _get_exp_memories(self, user_id: int) -> list[dict]:
        conn = self.db._get_connection()
        rows = conn.execute(
            "SELECT id, round, content, created_at FROM memory_v2 "
            "WHERE user_id = ? AND type = 'exp' ORDER BY id ASC",
            (user_id,),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "round": r["round"],
                "content": self._decrypt(user_id, r["content"]),
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    # =================================================================
    # 向量嵌入
    # =================================================================

    def _embed_raw_round(self, user_id: int, chat_id: int, round_idx: int,
                         user_msg: str, assistant_reply: str) -> None:
        """对原始对话文本生成 embedding，写入 memory_embeds 表。"""
        try:
            text = f"[用户] {user_msg}\n[助手] {assistant_reply}"
            vec = self._ec.embed(text)
            if vec is None:
                return
            blob = self._pack_embedding(vec)
            conn = self.db._get_connection()
            with self._lock:
                conn.execute(
                    "INSERT OR REPLACE INTO memory_embeds "
                    "(user_id, chat_id, round, embedding) VALUES (?, ?, ?, ?)",
                    (user_id, chat_id, round_idx, blob),
                )
                conn.commit()
        except Exception:
            logger.exception("embed-raw-round failed uid=%d chat=%d round=%d",
                             user_id, chat_id, round_idx)

    @staticmethod
    def _pack_embedding(vec: list[float]) -> bytes:
        return struct.pack(f"{len(vec)}f", *vec)

    @staticmethod
    def _unpack_embedding(blob: bytes) -> list[float]:
        return list(struct.unpack(f"{len(blob) // 4}f", blob))

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    # =================================================================
    # 上下文组装 (被动回忆)
    # =================================================================

    def assemble_context(
        self, user_id: int, history: list[dict]
    ) -> list[dict]:
        memos = self._get_memos(user_id)
        exps = self._get_exp_memories(user_id)
        window = Config.MEMORY_CONTEXT_WINDOW_SIZE
        threshold = int(window * Config.MEMORY_REPLACE_THRESHOLD_RATIO)

        result = []
        for m in memos:
            result.append({"role": "system", "content": f"[备忘] {m['content']}"})

        if len(history) <= threshold or not exps:
            result.extend(history)
            return result

        replace_count = len(history) - threshold
        recent = history[replace_count:]

        for mem in exps:
            header = f"[记忆 · 轮次{mem['round']}]"
            result.append({"role": "system", "content": f"{header} {mem['content']}"})

        result.extend(recent)
        return result

    # =================================================================
    # 主动召回 (搜索)
    # =================================================================

    def search(
        self,
        user_id: int,
        keywords: list[str],
        limit: int = 5,
        threshold: float = 0.5,
        embedding_query: Optional[str | list[float]] = None,
        embedding_weight: Optional[float] = None,
    ) -> list[dict]:
        """
        混合搜索: keyword + vector (若 embedding 启用且提供 query)。

        embedding_query 可为:
        - str: 自动调用 embedding_client 嵌入
        - list[float]: 直接作为向量相似度查询
        - None: 仅做 keyword 搜索 (原有行为)
        """
        use_vector = (
            self._embedding_enabled
            and embedding_query is not None
        )

        conn = self.db._get_connection()
        row = conn.execute(
            "SELECT MAX(round) FROM memory_v2 WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        total_rounds = row[0] or 1

        rows = conn.execute(
            "SELECT v.id, v.type, v.round, v.content, v.created_at, e.embedding "
            "FROM memory_v2 v "
            "LEFT JOIN memory_embeds e "
            "ON v.user_id = e.user_id AND v.chat_id = e.chat_id AND v.round = e.round "
            "WHERE v.user_id = ? "
            "ORDER BY v.round DESC LIMIT ?",
            (user_id, limit * 20),
        ).fetchall()

        # ---- 向量搜索（若启用） ----
        query_vec = None
        if use_vector:
            if isinstance(embedding_query, str):
                query_vec = self._ec.embed(embedding_query)
            elif isinstance(embedding_query, list):
                query_vec = embedding_query
            if query_vec is not None and len(query_vec) < 2:
                query_vec = None  # 无效向量

        vec_norm = Config.MEMORY_EMBEDDING_WEIGHT if embedding_weight is None else embedding_weight

        # ---- 搜素 ----
        search_terms = [kw.lower().strip() for kw in keywords if kw.strip()] if keywords else []
        use_keyword = bool(search_terms)

        if not use_keyword and query_vec is None:
            return []

        search_tokens = set()
        if use_keyword:
            for t in search_terms:
                search_tokens.update(_tokenize(t))

        scored = []
        for r in rows:
            content = self._decrypt(user_id, r["content"])
            if not content:
                continue
            content_lower = content.lower() if use_keyword else ""

            # keyword 得分
            kw_score = 0.0
            if use_keyword:
                if not any(term in content_lower for term in search_terms):
                    if query_vec is None:
                        continue  # 纯 keyword 模式，不匹配直接跳过
                    kw_score = 0.0  # 混合模式，keyword 为 0 但仍可能靠 vector 进入
                else:
                    content_tokens = set(_tokenize(content_lower))
                    if search_tokens and content_tokens:
                        intersection = search_tokens & content_tokens
                        if not intersection:
                            for term in search_terms:
                                if term in content_lower:
                                    intersection.add(term)
                        hit_score = len(intersection) / len(search_tokens) if search_tokens else 0
                        rd = r["round"] or 0
                        recency = 1.0 - (rd / (total_rounds + 1)) if total_rounds > 0 else 0
                        kw_score = hit_score * 0.7 + recency * 0.3

            # vector 得分
            vec_score = 0.0
            if query_vec is not None:
                blob = r["embedding"]
                if blob and len(blob) >= 8:
                    try:
                        mem_vec = self._unpack_embedding(blob)
                        vec_score = self._cosine_similarity(query_vec, mem_vec)
                    except Exception:
                        vec_score = 0.0

            # 融合
            if use_keyword and query_vec is not None:
                final_score = kw_score * (1 - vec_norm) + vec_score * vec_norm
            elif query_vec is not None:
                final_score = vec_score
            else:
                final_score = kw_score

            if final_score < threshold:
                if use_keyword:
                    continue  # keyword / hybrid: 严格阈值
                if final_score < threshold * 0.5:  # vector-only: 更低阈值
                    continue

            scored.append(
                {
                    "id": r["id"],
                    "type": r["type"],
                    "round": r["round"],
                    "content": content,
                    "created_at": r["created_at"],
                    "score": round(final_score, 3),
                }
            )

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]

    def get_detail(
        self, user_id: int, chat_id: int, rounds: list[int]
    ) -> dict[int, list[dict]]:
        return self.db.get_messages_by_rounds(user_id, chat_id, rounds)

    # =================================================================
    # 批量索引 (旧记忆后填 embedding)
    # =================================================================

    def reindex_embeddings(
        self,
        user_id: Optional[int] = None,
    ):
        """
        生成器: 遍历消息表中的原始对话，构建文本并生成 embedding，
        写入 memory_embeds 表 (覆盖旧索引)。

        参数:
            user_id:  若指定则仅索引该用户

        产出:
            (processed: int, total: int, current_text: str, skipped: int)
        """
        if not self._embedding_enabled or self._ec is None:
            logger.warning("embedding 未启用，跳过批量索引")
            return

        conn = self.db._get_connection()
        where = "WHERE 1=1"
        params: list = []
        if user_id is not None:
            where += " AND c.user_id = ?"
            params.append(user_id)

        rows = conn.execute(
            f"SELECT DISTINCT c.user_id, m.chat_id, m.round_index "
            f"FROM messages m "
            f"JOIN chats c ON m.chat_id = c.chat_id "
            f"{where} ORDER BY m.chat_id, m.round_index",
            params,
        ).fetchall()

        total = len(rows)
        if total == 0:
            logger.info("没有需要索引的原始消息")
            return

        processed = 0
        skipped = 0
        for r in rows:
            uid = r["user_id"]
            cid = r["chat_id"]
            round_ = r["round_index"]
            try:
                text = self._build_round_text(uid, cid, round_)
                if not text:
                    skipped += 1
                    processed += 1
                    yield (processed, total, "[跳过] 无消息文本", skipped)
                    continue

                vec = self._ec.embed(text)
                if vec is None:
                    skipped += 1
                    processed += 1
                    yield (processed, total, "[失败] embedding 返回空", skipped)
                    continue

                blob = self._pack_embedding(vec)
                with self._lock:
                    conn.execute(
                        "INSERT OR REPLACE INTO memory_embeds "
                        "(user_id, chat_id, round, embedding) VALUES (?, ?, ?, ?)",
                        (uid, cid, round_, blob),
                    )
                    conn.commit()
                processed += 1
                preview = text[:60].replace("\n", " ")
                yield (processed, total, preview, skipped)
            except Exception as e:
                logger.exception("reindex round %d 失败", round_)
                skipped += 1
                processed += 1
                yield (processed, total, f"[错误] {e}", skipped)

    # =================================================================
    # 摘要重建
    # =================================================================

    def rebuild_summaries(
        self,
        entries: list[tuple[int, int, int, int]],
    ):
        """
        生成器: 重建指定条目的摘要并清除对应的旧 embedding。

        注意: 词嵌入不在此处重建，摘要覆盖后需通过 /memory index 命令
        单独重建 embedding。

        参数:
            entries: [(user_id, chat_id, round, memory_id), ...]

        产出:
            (processed: int, total: int, current_preview: str, error: str)
        """
        total = len(entries)
        if total == 0:
            return

        # 预热摘要模型，确保整个批次只加载一次
        try:
            self.summary_model.summarize_text("预热", max_length=10)
        except Exception:
            logger.warning("摘要模型预热失败，将继续尝试逐条重建")

        processed = 0
        for uid, cid, round_, mid in entries:
            try:
                msgs = self._build_round_messages(uid, cid, round_)
                if not msgs:
                    yield (processed, total, "[跳过] 无原始消息", "")
                    processed += 1
                    continue

                summary = self.summary_model.summarize_dialog(
                    msgs,
                    max_length=Config.MEMORY_SUMMARY_LENGTH,
                )
                if not summary:
                    yield (processed, total, "[跳过] 摘要返回空", "")
                    processed += 1
                    continue

                encrypted = self._encrypt(uid, summary)
                conn = self.db._get_connection()
                with self._lock:
                    conn.execute(
                        "UPDATE memory_v2 SET content = ? WHERE id = ?",
                        (encrypted, mid),
                    )
                    conn.commit()

                processed += 1
                preview = summary[:50].replace("\n", " ")
                yield (processed, total, preview, "")
                time.sleep(0.2)
            except Exception as e:
                logger.exception("rebuild memory_id=%d 失败", mid)
                processed += 1
                yield (processed, total, f"[错误]", str(e))

    def _build_round_text(self, user_id: int, chat_id: int, round_: int) -> str:
        """从 messages 表读取指定轮次的原始对话，拼接为文本。"""
        msgs = self._build_round_messages(user_id, chat_id, round_)
        if not msgs:
            return ""
        parts = []
        for m in msgs:
            if m["role"] == "user":
                role = "[用户]"
            elif m["role"] == "assistant":
                role = "[助手]"
            else:
                role = m["role"]
            parts.append(f"{role}: {m['content']}")
        return "\n".join(parts)

    def _build_round_messages(self, user_id: int, chat_id: int, round_: int) -> list[dict]:
        """从 messages 表读取指定轮次的消息，返回 [{role, content}, ...]。
        memory_v2.round 与 messages.round_index 对齐。"""
        if round_ < 1:
            return []
        conn = self.db._get_connection()
        rows = conn.execute(
            "SELECT role, content FROM messages "
            "WHERE chat_id = ? AND round_index = ? "
            "ORDER BY message_id ASC",
            (chat_id, round_),
        ).fetchall()
        result = []
        for m in rows:
            try:
                text = self._decrypt(user_id, m["content"])
            except Exception:
                text = m["content"] or ""
            result.append({"role": m["role"], "content": text})
        return result

    # =================================================================
    # 标签处理 (<recall> + <memo>)
    # =================================================================

    def handle_tags(self, user_id: int, chat_id: int, text: str) -> str:
        if not text:
            return text

        memo_matches = list(_MEMO_RE.finditer(text))
        for match in memo_matches:
            content = match.group(1).strip()
            if content:
                self.add_memo(user_id, chat_id, content)
        text = _MEMO_RE.sub("", text)

        recall_matches = list(_RECALL_RE.finditer(text))
        results = []
        for match in recall_matches:
            try:
                payload = json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            r = self._handle_recall(user_id, chat_id, payload)
            if r:
                results.append(r)

        text = _RECALL_RE.sub("", text).strip()
        if results:
            text += "\n\n" + "\n\n".join(results)
        return text

    def _handle_recall(self, user_id, chat_id, payload):
        keywords = payload.get("keywords", [])
        detail_indices = payload.get("detail", [])
        auto_detail = payload.get("detail") is True
        count = payload.get("count", 5)

        if isinstance(detail_indices, list) and detail_indices:
            detail = self.get_detail(user_id, chat_id, detail_indices)
            return self._format_detail_results(detail)

        if keywords:
            embedding_query = " ".join(keywords) if isinstance(keywords, list) else keywords
            hits = self.search(
                user_id, keywords, count,
                embedding_query=embedding_query if self._embedding_enabled else None,
            )
            search_text = self._format_search_results(hits, keywords)
            if auto_detail and hits:
                indices = [h["round"] for h in hits if h.get("round") is not None]
                if indices:
                    detail = self.get_detail(user_id, chat_id, indices)
                    detail_text = self._format_detail_results(detail)
                    return search_text + "\n\n" + detail_text
            return search_text

        return None

    # =================================================================
    # 备忘录 CRUD
    # =================================================================

    def add_memo(self, user_id: int, chat_id: int, text: str) -> int:
        encrypted = self._encrypt(user_id, text)
        conn = self.db._get_connection()
        with self._lock:
            cursor = conn.execute(
                "INSERT INTO memory_v2 (user_id, chat_id, type, content) "
                "VALUES (?, ?, 'memo', ?)",
                (user_id, chat_id, encrypted),
            )
            conn.commit()
        return cursor.lastrowid

    def _get_memos(self, user_id: int) -> list[dict]:
        conn = self.db._get_connection()
        rows = conn.execute(
            "SELECT id, content, created_at FROM memory_v2 "
            "WHERE user_id = ? AND type = 'memo' ORDER BY id ASC",
            (user_id,),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "content": self._decrypt(user_id, r["content"]),
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    def delete_memo(self, memo_id: int) -> bool:
        conn = self.db._get_connection()
        with self._lock:
            cursor = conn.execute(
                "DELETE FROM memory_v2 WHERE id = ? AND type = 'memo'", (memo_id,)
            )
            conn.commit()
        return cursor.rowcount > 0

    # =================================================================
    # 格式化 (静态方法)
    # =================================================================

    @staticmethod
    def _format_timedelta(ts_str):
        if not ts_str:
            return ""
        try:
            fmt = "%Y-%m-%d %H:%M:%S"
            if len(ts_str) <= 10:
                fmt = "%Y-%m-%d"
            ts = datetime.strptime(
                ts_str[:19] if len(ts_str) > 19 else ts_str, fmt
            )
            delta = datetime.now() - ts
            if delta.days > 30:
                return f"{delta.days // 30}个月前"
            elif delta.days > 0:
                return f"{delta.days}天前"
            elif delta.seconds > 3600:
                return f"{delta.seconds // 3600}小时前"
            elif delta.seconds > 60:
                return f"{delta.seconds // 60}分钟前"
            else:
                return "刚刚"
        except Exception:
            return ""

    @classmethod
    def _format_search_results(cls, hits, search_keywords):
        if not hits:
            kw_str = ", ".join(search_keywords) if search_keywords else ""
            return f'[记忆检索结果] 未找到与 "{kw_str}" 相关的记忆。'

        kw_str = ", ".join(search_keywords) if search_keywords else ""
        lines = [f"[记忆检索结果] 找到 {len(hits)} 条相关记忆 (关键词: {kw_str}):"]
        lines.append("─" * 56)

        for hit in hits:
            rd = hit.get("round", "?")
            ts = hit.get("created_at", "") or ""
            date_str = ts[:10] if isinstance(ts, str) and len(ts) > 10 else ts
            ago = cls._format_timedelta(ts)
            time_label = f"{date_str} ({ago})" if ago else date_str
            score = hit.get("score", 0)
            content = hit.get("content", "")
            if len(content) > 200:
                content = content[:200] + "..."
            memo_tag = " [备忘]" if hit.get("type") == "memo" else ""

            lines.append(
                f"第{rd}轮 · {time_label} · 匹配度: {score:.2f}{memo_tag}"
            )
            lines.append(f"  {content}")
            lines.append("─" * 56)

        lines.append(
            '(使用 <recall>{"detail": [轮次号, ...]}</recall> 可查看完整对话)'
        )
        return "\n".join(lines)

    @classmethod
    def _format_detail_results(cls, detail):
        if not detail:
            return "[记忆细节还原] 未找到对应轮次的对话记录。"

        lines = ["[记忆细节还原]"]
        total_chars = 0
        truncated = False

        for round_idx in sorted(detail.keys()):
            messages = detail[round_idx]
            if not messages:
                continue
            ts = ""
            for msg in messages:
                if msg.get("timestamp"):
                    ts = msg["timestamp"]
                    if isinstance(ts, str) and len(ts) > 10:
                        ts = ts[:10]
                    break
            ago = cls._format_timedelta(ts)
            time_label = f"{ts} ({ago})" if ago else ts
            lines.append(f"第{round_idx}轮 ({time_label}):")
            lines.append("─" * 56)
            for msg in messages:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                role_label = "User" if role == "user" else "Agent"
                line = f"{role_label}: {content}"
                lines.append(line)
                total_chars += len(line)
                if total_chars > MAX_TOTAL_DETAIL_CHARS:
                    truncated = True
                    break
            if truncated:
                lines.append("...(内容截断)")
                break
            lines.append("─" * 56)
        return "\n".join(lines)
