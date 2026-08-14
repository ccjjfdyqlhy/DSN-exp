# memory/topics.py
# TopicManager — 话题系统: 时间/语义分段、话题激活、上下文组装
# 与 MemorySystem 深度绑定 (v1.0)
#
# 设计:
#   - 每个 chat 内按 30min 静默 + 语义无关划出话题, 话题原文按轮存储。
#   - 话题状态: open(原文注入) / closed(仅聚合摘要注入)。
#   - 运行时激活叠加层(内存): current(当前话题) / passive(本轮被动激活) / pinned(主动激活)。
#   - 归属判定: 词嵌入召回候选 + LLM judge 确认(仅在歧义时调用)。

from __future__ import annotations

import json
import logging
import math
import re
import struct
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from apps.dsn.config import Config
from apps.dsn.db.chat import ChatDBManager
from apps.dsn.models import LMSummaryModel, EmbeddingClient

from harness.context_assembly import (
    ContextBudget,
    ContextSegment,
    PRIORITY_ACTIVE,
    PRIORITY_CURRENT,
    PRIORITY_MEMO,
    PRIORITY_SUMMARY,
    SEG_MEMO,
    SEG_SUMMARY,
    SEG_VERBATIM,
    SegmentedContextAssembler,
)

logger = logging.getLogger("TopicManager")

_JUDGE_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

TOPIC_REPR_CHARS = 2000  # 话题代表文本预算(向量用)
_TOPIC_PIN_CAP = 5       # 同时 pinned 话题上限


def _ts_to_epoch(ts: Optional[str]) -> Optional[float]:
    """解析 SQLite datetime('now') 存储的 UTC 时间戳。"""
    if not ts:
        return None
    try:
        s = ts[:19] if len(ts) > 19 else ts
        if len(s) <= 10:
            s += " 00:00:00"
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
    except Exception:
        return None


class TopicState:
    """单个 (user, chat) 的运行时话题状态(纯内存)。"""

    def __init__(self):
        self.current_topic_id: Optional[int] = None
        self.passive_activations: set[int] = set()
        self.active_pins: set[int] = set()


class TopicStore:
    """topics 表 CRUD + 向量编码。"""

    def __init__(self, db: ChatDBManager, embedding_client: Optional[EmbeddingClient] = None):
        self.db = db
        self._ec = embedding_client
        self._embedding_enabled = (
            embedding_client is not None and Config.MEMORY_EMBEDDING_ENABLED
        )
        self._lock = threading.Lock()

    # ── 加解密 ──

    def _encrypt(self, user_id: int, text: str) -> str:
        return self.db._cipher.encrypt(user_id, text)

    def _decrypt(self, user_id: int, text: str) -> str:
        if not text:
            return ""
        return self.db._cipher.decrypt(user_id, text)

    # ── 向量 ──

    @staticmethod
    def _pack_embedding(vec) -> bytes:
        return struct.pack(f"{len(vec)}f", *vec)

    @staticmethod
    def _unpack_embedding(blob) -> list:
        return list(struct.unpack(f"{len(blob) // 4}f", blob))

    @staticmethod
    def _cosine_similarity(a, b) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    # ── CRUD ──

    def create_topic(self, user_id: int, chat_id: int, start_round: int) -> int:
        conn = self.db._get_connection()
        with self._lock:
            cur = conn.execute(
                "INSERT INTO topics (user_id, chat_id, start_round, status, last_activity_at) "
                "VALUES (?, ?, ?, 'open', datetime('now'))",
                (user_id, chat_id, start_round),
            )
            conn.commit()
        return cur.lastrowid

    def touch_topic(self, topic_id: int, round_idx: int) -> None:
        conn = self.db._get_connection()
        with self._lock:
            conn.execute(
                "UPDATE topics SET end_round = ?, last_activity_at = datetime('now') "
                "WHERE topic_id = ?",
                (round_idx, topic_id),
            )
            conn.commit()

    def close_topic(self, topic_id: int, end_round: Optional[int] = None) -> bool:
        conn = self.db._get_connection()
        with self._lock:
            if end_round is not None:
                cur = conn.execute(
                    "UPDATE topics SET status = 'closed', end_round = COALESCE(end_round, ?), "
                    "closed_at = datetime('now') WHERE topic_id = ? AND status = 'open'",
                    (end_round, topic_id),
                )
            else:
                cur = conn.execute(
                    "UPDATE topics SET status = 'closed', closed_at = datetime('now') "
                    "WHERE topic_id = ? AND status = 'open'",
                    (topic_id,),
                )
            conn.commit()
        return cur.rowcount > 0

    def reopen_topic(self, topic_id: int) -> bool:
        conn = self.db._get_connection()
        with self._lock:
            cur = conn.execute(
                "UPDATE topics SET status = 'open', closed_at = NULL, "
                "last_activity_at = datetime('now') WHERE topic_id = ?",
                (topic_id,),
            )
            conn.commit()
        return cur.rowcount > 0

    def get_topic(self, user_id: int, topic_id: int) -> Optional[dict]:
        conn = self.db._get_connection()
        row = conn.execute(
            "SELECT * FROM topics WHERE topic_id = ? AND user_id = ?", (topic_id, user_id)
        ).fetchone()
        if not row:
            return None
        return self._row_to_dict(user_id, row)

    def _row_to_dict(self, user_id: int, row) -> dict:
        d = dict(row)
        d["title"] = self._decrypt(user_id, d.get("title") or "")
        d["summary"] = self._decrypt(user_id, d.get("summary") or "")
        return d

    def list_topics(self, user_id: int, chat_id: Optional[int] = None,
                    status: Optional[str] = None) -> list[dict]:
        conn = self.db._get_connection()
        sql = "SELECT * FROM topics WHERE user_id = ?"
        params: list = [user_id]
        if chat_id is not None:
            sql += " AND chat_id = ?"
            params.append(chat_id)
        if status is not None:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY start_round ASC"
        rows = conn.execute(sql, params).fetchall()
        return [self._row_to_dict(user_id, r) for r in rows]

    def set_summary(self, user_id: int, topic_id: int, title: str, summary: str) -> None:
        conn = self.db._get_connection()
        with self._lock:
            conn.execute(
                "UPDATE topics SET title = ?, summary = ? WHERE topic_id = ?",
                (self._encrypt(user_id, title or ""), self._encrypt(user_id, summary or ""), topic_id),
            )
            conn.commit()

    def set_embedding(self, topic_id: int, vec) -> None:
        conn = self.db._get_connection()
        with self._lock:
            conn.execute(
                "UPDATE topics SET embedding = ? WHERE topic_id = ?",
                (self._pack_embedding(vec), topic_id),
            )
            conn.commit()

    def get_embedding_vector(self, topic_id: int) -> Optional[list]:
        conn = self.db._get_connection()
        row = conn.execute("SELECT embedding FROM topics WHERE topic_id = ?", (topic_id,)).fetchone()
        if not row or not row["embedding"]:
            return None
        try:
            return self._unpack_embedding(row["embedding"])
        except Exception:
            return None

    # ── 代表文本 / 摘要 ──

    def topic_exp_summaries(self, user_id: int, topic_id: int) -> list[tuple[int, str]]:
        conn = self.db._get_connection()
        rows = conn.execute(
            "SELECT round, content FROM memory_v2 "
            "WHERE user_id = ? AND topic_id = ? AND type = 'exp' AND round IS NOT NULL "
            "ORDER BY round ASC",
            (user_id, topic_id),
        ).fetchall()
        out = []
        for r in rows:
            try:
                c = self._decrypt(user_id, r["content"])
            except Exception:
                continue
            if c:
                out.append((r["round"], c))
        return out

    def build_topic_repr(self, user_id: int, topic_id: int) -> str:
        """话题代表文本: 标题 + 聚合摘要 + 各轮摘要; 无摘要时回退原文。"""
        topic = self.get_topic(user_id, topic_id)
        if not topic:
            return ""
        parts = []
        if topic.get("title"):
            parts.append(topic["title"])
        if topic.get("summary"):
            parts.append(topic["summary"])
        parts.extend(c for _, c in self.topic_exp_summaries(user_id, topic_id))
        text = "\n".join(x for x in parts if x)
        if not text.strip():
            rounds = self.db.get_messages_by_topic(user_id, topic_id)
            rids = sorted(rounds.keys())
            keep = rids[:2] + rids[-3:] if len(rids) > 5 else rids
            lines = []
            for ri in keep:
                for m in rounds[ri]:
                    role = "用户" if m["role"] == "user" else "DSN"
                    lines.append(f"{role}: {m['content']}")
            text = "\n".join(lines)
        return text[:TOPIC_REPR_CHARS]

    def compute_embedding(self, user_id: int, topic_id: int) -> Optional[list]:
        if not self._embedding_enabled or self._ec is None:
            return None
        text = self.build_topic_repr(user_id, topic_id)
        if not text.strip():
            return None
        try:
            vec = self._ec.embed(text)
        except Exception:
            logger.exception("topic embedding failed tid=%d", topic_id)
            return None
        if vec is None:
            return None
        self.set_embedding(topic_id, vec)
        return vec


class TopicManager:
    """话题决策 + 激活窗口 + 上下文组装。"""

    def __init__(self, db: ChatDBManager, memory_system=None,
                 summary_model: Optional[LMSummaryModel] = None,
                 embedding_client: Optional[EmbeddingClient] = None):
        self.db = db
        self._ms = memory_system
        self.store = TopicStore(db, embedding_client)
        self.summary_model = summary_model or (
            getattr(memory_system, "summary_model", None) if memory_system else None
        )
        self._states: dict[tuple[int, int], TopicState] = {}
        self._states_lock = threading.Lock()

    # ── 运行时状态 ──

    def _state(self, user_id: int, chat_id: int) -> TopicState:
        key = (user_id, chat_id)
        with self._states_lock:
            st = self._states.get(key)
            if st is None:
                st = TopicState()
                self._states[key] = st
            return st

    def reset_state(self, user_id: int, chat_id: int) -> None:
        with self._states_lock:
            self._states.pop((user_id, chat_id), None)

    # ── 嵌入 ──

    def _embed(self, text: str) -> Optional[list]:
        if not self.store._embedding_enabled or self.store._ec is None or not text:
            return None
        try:
            return self.store._ec.embed(text)
        except Exception:
            logger.exception("embed failed")
            return None

    def _score(self, user_id: int, topics: list[dict], qvec) -> list[tuple[float, dict]]:
        scored = []
        for t in topics:
            sim = 0.0
            if qvec is not None:
                tvec = self.store.get_embedding_vector(t["topic_id"])
                if tvec is None:
                    tvec = self.store.compute_embedding(user_id, t["topic_id"])
                if tvec:
                    sim = self.store._cosine_similarity(qvec, tvec)
            scored.append((sim, t))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored

    # ── 消息归属判定 ──

    def on_new_message(self, user_id: int, chat_id: int, message: str,
                       round_idx: Optional[int] = None) -> dict:
        """决定当前消息归属话题并更新激活窗口, 返回决策 dict。"""
        st = self._state(user_id, chat_id)

        if not Config.TOPIC_ENABLED:
            open_topics = self.store.list_topics(user_id, chat_id, status="open")
            if open_topics and st.current_topic_id not in {t["topic_id"] for t in open_topics}:
                st.current_topic_id = open_topics[-1]["topic_id"]
            return {"action": "continue", "topic_id": st.current_topic_id,
                    "new_topic_id": None, "passive": [], "sims": {}}

        # 1) 时间间隔 → 关闭当前话题
        gap = None
        last_ts = self.db.get_last_message_timestamp(chat_id) if self.db else None
        if last_ts:
            ts = _ts_to_epoch(last_ts)
            if ts is not None:
                gap = time.time() - ts
        current = self.store.get_topic(user_id, st.current_topic_id) if st.current_topic_id else None
        if current and current["status"] != "open":
            current = None
        # 无消息时间戳时回退到当前话题的活动时间(懒判定兜底)
        if gap is None and current:
            ts = _ts_to_epoch(current.get("last_activity_at"))
            if ts is not None:
                gap = time.time() - ts

        if current and gap is not None and gap > Config.TOPIC_IDLE_SECONDS:
            logger.info("话题 #%d 已静默 %.0fs(>%ds), 关闭话题", current["topic_id"], gap, Config.TOPIC_IDLE_SECONDS)
            self._close_topic(user_id, current["topic_id"], current.get("end_round"))
            st.current_topic_id = None
            st.active_pins.clear()  # 30min 静默 = 话题结束, 所有持续激活一并失效
            current = None

        # 2) 语义打分
        qvec = self._embed(message)
        topics = self.store.list_topics(user_id, chat_id)
        scored = self._score(user_id, topics, qvec)
        sims = {t["topic_id"]: s for s, t in scored}

        # 3) 决策
        decision = self._decide(user_id, chat_id, message, st, current, scored, gap, sims)

        # 4) 应用
        action = decision["action"]
        new_topic_id = None
        if action == "new":
            if current and current["status"] == "open":
                self._close_topic(user_id, current["topic_id"], current.get("end_round"))
            start_round = round_idx or (self.db.get_next_round_index(chat_id) if self.db else 1)
            new_topic_id = self.store.create_topic(user_id, chat_id, start_round)
            st.current_topic_id = new_topic_id
            st.active_pins.clear()
            st.passive_activations = set()
            logger.info("新建话题 #%d (round=%d) uid=%d chat=%d",
                        new_topic_id, start_round, user_id, chat_id)
        elif action == "reopen":
            tid = decision.get("topic_id")
            if tid and self.store.get_topic(user_id, tid):
                if current and current["topic_id"] != tid and current["status"] == "open":
                    self._close_topic(user_id, current["topic_id"], current.get("end_round"))
                self.store.reopen_topic(tid)
                st.current_topic_id = tid
                st.active_pins.clear()
                logger.info("重新激活话题 #%d uid=%d", tid, user_id)
        else:  # continue
            tid = decision.get("topic_id") or (current["topic_id"] if current else None)
            if tid and self.store.get_topic(user_id, tid):
                st.current_topic_id = tid
            else:
                start_round = round_idx or (self.db.get_next_round_index(chat_id) if self.db else 1)
                new_topic_id = self.store.create_topic(user_id, chat_id, start_round)
                st.current_topic_id = new_topic_id
                logger.info("首条/无归属消息创建话题 #%d (round=%d)", new_topic_id, start_round)

        # 5) 被动激活: 本轮 sim 达标且非 current 的关闭话题
        passive = set()
        if qvec is not None:
            for sim, t in scored:
                if t["topic_id"] == st.current_topic_id:
                    continue
                if t["status"] == "closed" and sim >= Config.TOPIC_ACTIVATION_THRESHOLD:
                    passive.add(t["topic_id"])
                    if len(passive) >= 3:
                        break
        st.passive_activations = passive

        return {
            "action": action,
            "topic_id": st.current_topic_id,
            "new_topic_id": new_topic_id,
            "passive": sorted(passive),
            "sims": {k: round(v, 3) for k, v in sims.items()},
        }

    def _decide(self, user_id, chat_id, message, st, current, scored, gap, sims) -> dict:
        cur_sim = sims.get(current["topic_id"], 0.0) if current else 0.0
        k = Config.TOPIC_CANDIDATE_K
        old_cands = [t for _, t in scored if t["topic_id"] != (current["topic_id"] if current else None)][:k]

        # 连续对话且与当前话题高度相关 → 直接续接(免 judge)
        if current and current["status"] == "open" and gap is not None and gap <= Config.TOPIC_IDLE_SECONDS:
            if cur_sim >= Config.TOPIC_CONTINUE_THRESHOLD and not Config.TOPIC_JUDGE_ALWAYS:
                return {"action": "continue", "topic_id": current["topic_id"]}

        no_current = current is None or current["status"] != "open"
        if no_current:
            top_sim = scored[0][0] if scored else 0.0
            if top_sim < Config.TOPIC_REOPEN_THRESHOLD and not Config.TOPIC_JUDGE_ALWAYS:
                return {"action": "new"}

        # LLM judge 确认
        if Config.TOPIC_JUDGE_ENABLED and self.summary_model is not None:
            try:
                return self._judge(user_id, chat_id, message, current, old_cands)
            except Exception as e:
                logger.warning("话题 judge 失败, 回退规则判定: %s", e)

        # 规则回退
        if current and current["status"] == "open" and cur_sim >= Config.TOPIC_CONTINUE_THRESHOLD * 0.6:
            return {"action": "continue", "topic_id": current["topic_id"]}
        if no_current and old_cands:
            best = old_cands[0]
            if sims.get(best["topic_id"], 0.0) >= Config.TOPIC_REOPEN_THRESHOLD:
                return {"action": "reopen", "topic_id": best["topic_id"]}
        return {"action": "new"}

    def _judge(self, user_id, chat_id, message, current, old_cands) -> dict:
        lines = [
            "# 话题归属判断",
            f"当前用户消息: {message}",
            "",
        ]
        if current:
            lines.append(f"[当前话题] #{current['topic_id']} 「{current.get('title') or '未命名'}」 轮次{current['start_round']}-{current.get('end_round') or '?'}")
            if current.get("summary"):
                lines.append(f"  摘要: {current['summary'][:200]}")
        else:
            lines.append("[当前话题] (无)")
        lines.append("")
        lines.append("[候选旧话题]")
        if not old_cands:
            lines.append("  (无)")
        for t in old_cands:
            lines.append(f"- #{t['topic_id']} 「{t.get('title') or '未命名'}」 轮次{t['start_round']}-{t.get('end_round') or '?'} 状态={t['status']}")
            if t.get("summary"):
                lines.append(f"    摘要: {t['summary'][:150]}")
        lines.append("")
        lines.append(
            "判断这条新消息属于以下哪种情况, 只输出 JSON:\n"
            '{"action":"continue|reopen|new","topic_id":<数字,仅reopen时填>,"reference_ids":[],"reason":"简短原因"}'
        )
        prompt = "\n".join(lines)
        fallback = self._judge_fallback(current, old_cands)
        try:
            raw = self.summary_model.complete_text(prompt, max_length=300)
        except Exception as e:
            logger.warning("judge 调用失败: %s", e)
            return fallback
        if not raw:
            return fallback
        m = _JUDGE_JSON_RE.search(raw)
        if not m:
            return fallback
        try:
            data = json.loads(m.group(0))
        except Exception:
            return fallback
        action = data.get("action")
        if action not in ("continue", "reopen", "new"):
            return fallback
        result = {"action": action}
        if action == "reopen":
            tid = data.get("topic_id")
            all_ids = {t["topic_id"] for t in self.store.list_topics(user_id, chat_id)}
            if not tid or tid not in all_ids:
                return fallback
            result["topic_id"] = tid
        elif action == "continue" and current:
            result["topic_id"] = current["topic_id"]
        return result

    @staticmethod
    def _judge_fallback(current, old_cands) -> dict:
        if current and current["status"] == "open":
            return {"action": "continue", "topic_id": current["topic_id"]}
        if old_cands:
            return {"action": "reopen", "topic_id": old_cands[0]["topic_id"]}
        return {"action": "new"}

    # ── 主动激活(pin) ──

    def pin_topic(self, user_id: int, chat_id: int, topic_id: int) -> bool:
        if not Config.TOPIC_ENABLED:
            return False
        topic = self.store.get_topic(user_id, topic_id)
        if not topic or topic["chat_id"] != chat_id:
            return False
        st = self._state(user_id, chat_id)
        if len(st.active_pins) >= _TOPIC_PIN_CAP and topic_id not in st.active_pins:
            return False
        st.active_pins.add(topic_id)
        if topic["status"] != "open":
            self.store.reopen_topic(topic_id)
        logger.info("主动激活(持续)话题 #%d uid=%d", topic_id, user_id)
        return True

    def unpin_topic(self, user_id: int, chat_id: int, topic_id: int) -> bool:
        st = self._state(user_id, chat_id)
        if topic_id in st.active_pins:
            st.active_pins.discard(topic_id)
            logger.info("取消持续激活话题 #%d uid=%d", topic_id, user_id)
            return True
        return False

    # ── 上下文组装 ──

    def assemble_topic_context(self, user_id: int, chat_id: int, history: list[dict],
                               cross_user_id: Optional[int] = None) -> list[dict]:
        """组装最终注入上下文: 备忘 + agent/跨用户 + 闭锁摘要 + 激活话题原文 + 原始尾部。

        预算与剪裁策略由引擎层 SegmentedContextAssembler 承担
        （harness/context_assembly.py，场景无关的通用能力）；本方法只负责
        数据准备与段构造，不再自行维护逐层 used 预算。
        """
        st = self._state(user_id, chat_id)
        segments: list[ContextSegment] = []

        # 1) 全局备忘 + 绑定 agent / 跨用户
        #    用户 memo 受 memo 预算约束；agent/跨用户内容为常驻段（unbounded）
        if self._ms is not None:
            used = 0
            for m in self._ms._get_memos(user_id):
                content = m.get("content") or ""
                if not content:
                    continue
                if used > 0 and used + len(content) > Config.TOPIC_MEMO_CHARS:
                    break
                used += len(content)
                segments.append(ContextSegment(
                    kind=SEG_MEMO, content=content,
                    priority=PRIORITY_MEMO, label="[备忘]"))

            if cross_user_id is None:
                bound = self._ms._get_bound_agent(user_id)
                if bound:
                    for m in self._ms._get_memos(bound):
                        segments.append(ContextSegment(
                            kind=SEG_MEMO, content=m["content"], unbounded=True,
                            priority=PRIORITY_MEMO, label="[AI Agent备忘]"))
                    for mem in self._ms._get_exp_memories(bound):
                        segments.append(ContextSegment(
                            kind=SEG_MEMO, content=mem["content"], unbounded=True,
                            priority=PRIORITY_MEMO,
                            label=f"[AI Agent记忆 · 轮次{mem['round']}]"))
                    unsynced: list[dict] = []
                    self._ms._inject_unsynced_agent_chat(unsynced, user_id, bound)
                    for u in unsynced:
                        segments.append(ContextSegment(
                            kind=SEG_MEMO, content=u.get("content", ""),
                            unbounded=True, priority=PRIORITY_MEMO, label="[AI Agent]"))
            elif cross_user_id and cross_user_id != user_id:
                for m in self._ms._get_memos(cross_user_id):
                    segments.append(ContextSegment(
                        kind=SEG_MEMO, content=m["content"], unbounded=True,
                        priority=PRIORITY_MEMO, label="[来自关联用户的备忘]"))
                for mem in self._ms._get_exp_memories(cross_user_id):
                    segments.append(ContextSegment(
                        kind=SEG_MEMO, content=mem["content"], unbounded=True,
                        priority=PRIORITY_MEMO,
                        label=f"[关联用户记忆 · 轮次{mem['round']}]"))

        # 2) 话题状态快照
        current = self.store.get_topic(user_id, st.current_topic_id) if st.current_topic_id else None
        if current and current["status"] != "open":
            current = None
        open_ids = set()
        if current:
            open_ids.add(current["topic_id"])
        open_ids.update(st.passive_activations)
        open_ids.update(st.active_pins)

        # 3) 关闭且未激活话题 → 聚合摘要段（summary 预算由引擎承担）
        all_topics = self.store.list_topics(user_id, chat_id)
        for t in all_topics:
            if t["status"] != "closed" or t["topic_id"] in open_ids:
                continue
            snippet = t.get("summary") or ""
            if not snippet:
                continue
            title = t.get("title") or f"第{t['start_round']}轮起"
            segments.append(ContextSegment(
                kind=SEG_SUMMARY, content=snippet, priority=PRIORITY_SUMMARY,
                label=f"[闭锁话题·{title}·第{t['start_round']}-{t.get('end_round') or '?'}轮]"))

        # 4) 激活话题原文段 (被动 + 持续激活), 数量受 TOPIC_MAX_OPEN_TOPICS 限制
        #    优先保留持续激活(pin), 再补被动激活
        ordered = list(st.active_pins) + [t for t in st.passive_activations if t not in st.active_pins]
        ordered = ordered[:max(0, Config.TOPIC_MAX_OPEN_TOPICS - (1 if current else 0))]
        for tid in ordered:
            t = self.store.get_topic(user_id, tid)
            if not (t and (t["status"] == "open" or tid in st.passive_activations
                           or tid in st.active_pins)):
                continue
            label = "被动激活" if tid in st.passive_activations else "持续激活"
            block = self._topic_block(user_id, t, label)
            if block:
                segments.append(ContextSegment(
                    kind=SEG_VERBATIM, content=block, priority=PRIORITY_ACTIVE,
                    meta={"topic_id": tid}))

        # 5) 当前话题段: 注入不在尾部窗口内的轮次(可截断保留)
        tail_rounds = self._build_tail(user_id, chat_id)
        tail_round_indices = set(tail_rounds[1])
        if current:
            try:
                cur_rounds = self.db.get_messages_by_topic(user_id, current["topic_id"])
            except Exception:
                cur_rounds = {}
            inject = [r for r in sorted(cur_rounds.keys()) if r not in tail_round_indices]
            if inject:
                block = self._topic_block(user_id, current, "当前话题", include_rounds=inject)
                if block:
                    segments.append(ContextSegment(
                        kind=SEG_VERBATIM, content=block, priority=PRIORITY_CURRENT,
                        truncatable=True, meta={"topic_id": current["topic_id"]}))

        # 6) 引擎预算剪裁组装 + 原始尾部
        assembler = SegmentedContextAssembler(ContextBudget(
            memo_chars=Config.TOPIC_MEMO_CHARS,
            summary_chars=Config.TOPIC_SUMMARY_CHARS,
            verbatim_chars=Config.TOPIC_MAX_VERBATIM_CHARS,
            tail_rounds=Config.TOPIC_TAIL_ROUNDS,
            max_open_topics=Config.TOPIC_MAX_OPEN_TOPICS,
        ))
        return assembler.assemble(segments, tail=tail_rounds[0])

    def _topic_block(self, user_id: int, topic: dict, label: str,
                      include_rounds: Optional[list[int]] = None) -> str:
        try:
            rounds = self.db.get_messages_by_topic(user_id, topic["topic_id"])
        except Exception:
            logger.exception("get topic rounds failed tid=%d", topic["topic_id"])
            return ""
        if not rounds:
            return ""
        rids = sorted(rounds.keys())
        if include_rounds is not None:
            want = set(include_rounds)
            rids = [r for r in rids if r in want]
        if not rids:
            return ""
        lines = [f"[话题·{label}·{topic.get('title') or f'第{topic['start_round']}轮起'}·第{rids[0]}-{rids[-1]}轮]"]
        total = 0
        for ri in rids:
            for m in rounds[ri]:
                role = "用户" if m["role"] == "user" else ("DSN" if m["role"] == "assistant" else m["role"])
                line = f"{role}: {m['content']}"
                lines.append(line)
                total += len(line)
        block = "\n".join(lines)
        if total > Config.TOPIC_MAX_VERBATIM_CHARS:
            block = block[:Config.TOPIC_MAX_VERBATIM_CHARS].rstrip() + "\n...(原文截断)"
        return block

    def _build_tail(self, user_id: int, chat_id: int,
                    history: list[dict] = None) -> tuple[list[dict], list[int]]:
        """从 DB 取最近 TOPIC_TAIL_ROUNDS 轮原文作尾部(精确去重)。
        返回 (tail消息列表, 覆盖的round集合); 失败回退 history。"""
        try:
            tail_rounds = Config.TOPIC_TAIL_ROUNDS
            conn = self.db._get_connection()
            rows = conn.execute(
                "SELECT DISTINCT round_index FROM messages WHERE chat_id = ? "
                "AND round_index IS NOT NULL ORDER BY round_index DESC LIMIT ?",
                (chat_id, tail_rounds),
            ).fetchall()
            rids = [r[0] for r in rows][::-1]
            if rids:
                rounds = self.db.get_messages_by_rounds(user_id, chat_id, rids)
                tail = []
                for ri in sorted(rounds.keys()):
                    for m in rounds[ri]:
                        tail.append({"role": m["role"], "content": m["content"]})
                if tail:
                    return tail, sorted(rounds.keys())
        except Exception:
            logger.exception("build tail from db failed, fallback history")
        return list(history or []), []

    # ── 关闭与聚合 ──

    def _close_topic(self, user_id: int, topic_id: int, end_round: Optional[int] = None) -> None:
        try:
            self.store.close_topic(topic_id, end_round)
        except Exception:
            logger.exception("close topic %d failed", topic_id)
        threading.Thread(target=self._finalize_topic, args=(user_id, topic_id), daemon=True).start()

    def _finalize_topic(self, user_id: int, topic_id: int) -> None:
        """后台: 生成聚合摘要 + 标题 + 话题向量。"""
        try:
            topic = self.store.get_topic(user_id, topic_id)
            if not topic:
                return
            exps = self.store.topic_exp_summaries(user_id, topic_id)
            summary = topic.get("summary") or ""
            if not summary and exps and self.summary_model is not None:
                text = " ".join(f"[第{r}轮] {c}" for r, c in exps)
                try:
                    summary = self.summary_model.summarize_text(
                        text, max_length=Config.MEMORY_SUMMARY_LENGTH)
                except Exception:
                    summary = text[:500]
            title = topic.get("title") or ""
            if not title and (summary or exps) and self.summary_model is not None:
                try:
                    src = (summary or " ".join(c for _, c in exps))[:300]
                    title = self.summary_model.complete_text(
                        f"给下面这段聊天话题拟一个简短标题(≤12字, 直接输出标题, 不要引号和标点):\n{src}",
                        max_length=30,
                    ).strip().strip('"').strip("「」『』“”")
                except Exception:
                    title = ""
            if summary or title:
                self.store.set_summary(user_id, topic_id, title or f"话题{topic_id}", summary)
            if self.store._embedding_enabled:
                self.store.compute_embedding(user_id, topic_id)
            logger.info("话题 #%d 关闭聚合完成", topic_id)
        except Exception:
            logger.exception("finalize topic %d failed", topic_id)

    def sweep_stale_topics(self) -> int:
        """维护用: 关闭所有 last_activity_at 超过 TOPIC_IDLE_SECONDS 的 open 话题。"""
        if not Config.TOPIC_ENABLED:
            return 0
        conn = self.db._get_connection()
        rows = conn.execute(
            "SELECT user_id, topic_id FROM topics WHERE status = 'open'"
        ).fetchall()
        closed = 0
        for r in rows:
            topic = self.store.get_topic(r["user_id"], r["topic_id"])
            if not topic:
                continue
            ts = _ts_to_epoch(topic.get("last_activity_at"))
            if ts is not None and time.time() - ts > Config.TOPIC_IDLE_SECONDS:
                self._close_topic(r["user_id"], r["topic_id"], topic.get("end_round"))
                closed += 1
        if closed:
            logger.info("清扫过期话题 %d 个", closed)
        return closed
