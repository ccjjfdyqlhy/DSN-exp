# apps/dsn_study/memory/topics.py
# 话题系统策略层（迁移计划阶段 7）—— 长会话不丢上下文、不超预算。
#
# 分工（**剪裁引擎不重写**）：
#   - 存储:   infra/store/sqlite.SqliteStore + MigrationRunner（本文件只建表/读写）
#   - 剪裁:   harness/context_assembly.SegmentedContextAssembler（纯函数，
#             memo/summary/verbatim/tail 四段 + 优先级驱逐）
#   - 压缩持久化: infra/store/chat_store.SessionStore —— 话题关闭/压缩时把
#             被摘要掉的原文章进 compressed_chunks（7.7 接线）
#   - 向量:   infra.vector（cosine_similarity / pack / unpack）
#
# 照抄现代参考实现 apps/dsn_ui/topic_manager.py 的两条不可违反规则：
#   1. **SEG_TAIL 强制**：最近 N 轮原文必须保底注入（unbounded=True），
#      否则预算耗尽会丢掉包含最后一条消息的段 —— "弹性上下文偶尔丢上一条消息"。
#   2. **所有 system 内容合并成一条 system 消息**：严格 Jinja 模板拒绝
#      system,system,system,…（上游 500）。
#
# 边界检测（dsn_ui 只有时间边界；这里补上 dsn memory/topics.py 的语义边界）：
#   - 时间边界：TOPIC_IDLE_SECONDS（默认 1800s）不聊 → 关当前话题
#   - 语义边界：消息嵌入 vs 话题向量 cosine → continue/new/reopen
#     （阈值 0.65 / 0.50；可选 LLM judge，失败回退规则）

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Optional

from infra.store.chat_store import SessionStore
from infra.store.sqlite import SqliteStore
from infra.store.base import Migration, MigrationRunner
from infra.vector import cosine_similarity, pack_embedding, unpack_embedding
from harness.context_assembly import (
    ContextBudget, ContextSegment, SegmentedContextAssembler,
    PRIORITY_SUMMARY, PRIORITY_TAIL, PRIORITY_ACTIVE, PRIORITY_CURRENT,
    SEG_SUMMARY, SEG_TAIL, SEG_VERBATIM,
)

from apps.dsn_study.config import Config

logger = logging.getLogger("StudyTopics")

_MIGRATIONS = [
    Migration("001_study_topics", lambda c: c.executescript(
        """
        CREATE TABLE IF NOT EXISTS study_topics (
            topic_id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            chat_id INTEGER NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'open',      -- open | closed
            is_pinned INTEGER NOT NULL DEFAULT 0,
            summary TEXT NOT NULL DEFAULT '',
            embedding BLOB,
            start_round INTEGER NOT NULL DEFAULT 0,
            last_round INTEGER NOT NULL DEFAULT 0,
            last_active_at REAL NOT NULL,
            created_at REAL NOT NULL,
            closed_at REAL
        );
        CREATE INDEX IF NOT EXISTS idx_study_topics_scope
            ON study_topics(user_id, chat_id, status);
        CREATE TABLE IF NOT EXISTS study_topic_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            round_idx INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_study_topic_msgs
            ON study_topic_messages(topic_id, id);
        """
    )),
]


class TopicStore:
    """话题持久化（SqliteStore + MigrationRunner）。"""

    def __init__(self, store: Optional[SqliteStore] = None, *,
                 db_path: Optional[str] = None):
        if store is None:
            store = SqliteStore(db_path or ":memory:")
        self.store = store
        MigrationRunner(self.store).migrate(_MIGRATIONS)

    # ── 话题 ──

    def save_topic(self, t: dict) -> None:
        self.store.execute(
            "INSERT INTO study_topics (topic_id, user_id, chat_id, title, status,"
            " is_pinned, summary, embedding, start_round, last_round,"
            " last_active_at, created_at, closed_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(topic_id) DO UPDATE SET"
            " title=excluded.title, status=excluded.status,"
            " is_pinned=excluded.is_pinned, summary=excluded.summary,"
            " embedding=excluded.embedding, last_round=excluded.last_round,"
            " last_active_at=excluded.last_active_at, closed_at=excluded.closed_at",
            (t["topic_id"], t["user_id"], t["chat_id"], t.get("title", ""),
             t.get("status", "open"), 1 if t.get("is_pinned") else 0,
             t.get("summary", ""),
             pack_embedding(t["embedding"]) if t.get("embedding") else None,
             t.get("start_round", 0), t.get("last_round", 0),
             t.get("last_active_at", time.time()), t.get("created_at", time.time()),
             t.get("closed_at")))

    def get_topic(self, topic_id: str) -> Optional[dict]:
        rows = self.store.execute(
            "SELECT * FROM study_topics WHERE topic_id = ?", (topic_id,))
        return self._row_to_topic(rows[0]) if rows else None

    def list_topics(self, user_id: int, chat_id: Optional[int] = None,
                    status: Optional[str] = None) -> list[dict]:
        sql = "SELECT * FROM study_topics WHERE user_id = ?"
        args: list = [user_id]
        if chat_id is not None:
            sql += " AND chat_id = ?"
            args.append(chat_id)
        if status:
            sql += " AND status = ?"
            args.append(status)
        sql += " ORDER BY last_active_at DESC"
        return [self._row_to_topic(r) for r in self.store.execute(sql, tuple(args))]

    def drop_messages(self, topic_id: str, count: int) -> None:
        """按 id 升序删最早 N 条（压缩后同步删除，防重载回灌）。"""
        self.store.execute(
            "DELETE FROM study_topic_messages WHERE id IN ("
            " SELECT id FROM study_topic_messages WHERE topic_id = ?"
            " ORDER BY id LIMIT ?)", (topic_id, max(0, int(count))))

    def _row_to_topic(self, r) -> dict:
        emb = None
        if r["embedding"]:
            try:
                emb = unpack_embedding(r["embedding"])
            except Exception:   # noqa: BLE001
                emb = None
        return {
            "topic_id": r["topic_id"], "user_id": r["user_id"],
            "chat_id": r["chat_id"], "title": r["title"],
            "status": r["status"], "is_pinned": bool(r["is_pinned"]),
            "summary": r["summary"], "embedding": emb,
            "start_round": r["start_round"], "last_round": r["last_round"],
            "last_active_at": r["last_active_at"], "created_at": r["created_at"],
            "closed_at": r["closed_at"],
        }


class TopicManager:
    """话题策略：边界检测 / pin / close / reopen / 弹性上下文组装。"""

    def __init__(self, db_path: Optional[str] = None, *,
                 store: Optional[SqliteStore] = None,
                 summary_model=None, embedding_client=None, judge_chat=None,
                 budget: Optional[ContextBudget] = None,
                 idle_timeout_seconds: Optional[float] = None):
        self.store = TopicStore(store=store, db_path=db_path)
        # 压缩持久化（7.7）：与话题库同一 sqlite 文件，save_compressed_chunk /
        # update_summary 的存储半边此前无人接线 —— 现在由 close/compact 调用。
        self.chunks = (SessionStore(store=self.store.store)
                       if store is not None else SessionStore(
                           db_path=db_path or ":memory:"))
        self.summary_model = summary_model
        self.embedding_client = embedding_client
        self.judge_chat = judge_chat
        self.budget = budget or ContextBudget(
            memo_chars=int(Config.TOPIC_MEMO_CHARS),
            summary_chars=int(Config.TOPIC_SUMMARY_CHARS),
            verbatim_chars=int(Config.TOPIC_MAX_VERBATIM_CHARS),
            tail_rounds=int(Config.TOPIC_TAIL_ROUNDS),
            max_open_topics=int(Config.TOPIC_MAX_OPEN_TOPICS),
        )
        self.idle_timeout = float(idle_timeout_seconds
                                  if idle_timeout_seconds is not None
                                  else Config.TOPIC_IDLE_SECONDS)
        self.assembler = SegmentedContextAssembler(self.budget)
        # 运行时状态：(uid, chat_id) -> {"current_topic_id", "active_pins"}
        self._states: dict[tuple, dict] = {}
        self._lock = threading.RLock()

    # ── 运行时状态 ──

    def _state(self, uid: int, chat_id: int) -> dict:
        key = (uid, chat_id)
        st = self._states.get(key)
        if st is None:
            st = {"current_topic_id": None, "active_pins": set()}
            # 回灌：取该会话最近活跃的 open 话题
            topics = self.store.list_topics(uid, chat_id, status="open")
            if topics:
                st["current_topic_id"] = topics[0]["topic_id"]
            self._states[key] = st
        return st

    def current_topic(self, uid: int, chat_id: int) -> Optional[dict]:
        tid = self._state(uid, chat_id).get("current_topic_id")
        return self.store.get_topic(tid) if tid else None

    # ── 边界检测（on_new_message） ──

    def on_new_message(self, uid: int, chat_id: int, user_text: str,
                       round_idx: int = 0) -> dict:
        """新消息进来 → 决定 continue / new / reopen。"""
        with self._lock:
            st = self._state(uid, chat_id)
            now = time.time()

            # 1) 时间边界：空闲超时 → 关当前话题
            cur = self.store.get_topic(st["current_topic_id"]) \
                if st["current_topic_id"] else None
            if cur and cur["status"] == "open" \
                    and now - cur["last_active_at"] > self.idle_timeout:
                self.close_topic(uid, chat_id, cur["topic_id"],
                                 summary=f"与【{cur['title']}】相关的过往探讨")
                st["active_pins"].clear()
                cur = None

            # 2) 语义打分：本会话的候选话题
            query_vec = self._embed(user_text) if self.embedding_client else None
            candidates = self._score_candidates(uid, chat_id, cur, query_vec)
            cur_sim = candidates.get(cur["topic_id"], 0.0) if cur else 0.0
            best_tid, best_sim, best_status = None, 0.0, "open"
            for tid, sim in sorted(candidates.items(), key=lambda kv: -kv[1]):
                if tid != (cur["topic_id"] if cur else None):
                    cand = self.store.get_topic(tid) or {}
                    best_status = cand.get("status", "open")
                    best_tid, best_sim = tid, sim
                    break

            decision = self._decide(cur, cur_sim, best_tid, best_sim,
                                    user_text, has_signal=query_vec is not None,
                                    best_status=best_status)
            action = decision["action"]

            if action == "continue" and cur:
                pass
            elif action == "reopen" and best_tid:
                # 关当前 → 重开目标 → 切换
                if cur and cur["status"] == "open":
                    self.close_topic(uid, chat_id, cur["topic_id"],
                                     summary=f"与【{cur['title']}】相关的过往探讨")
                self.reopen_topic(best_tid)
                st["current_topic_id"] = best_tid
                st["active_pins"].clear()
            else:   # new
                title = (user_text or "").strip().splitlines()[0][:20] or "新话题"
                tid = f"topic_{uuid.uuid4().hex[:8]}"
                topic = {
                    "topic_id": tid, "user_id": uid, "chat_id": chat_id,
                    "title": title, "status": "open", "is_pinned": False,
                    "summary": "", "embedding": query_vec,
                    "start_round": round_idx, "last_round": round_idx,
                    "last_active_at": now, "created_at": now, "closed_at": None,
                }
                self.store.save_topic(topic)
                st["current_topic_id"] = tid
                st["active_pins"].clear()
                decision["topic_id"] = tid
                decision["topic_title"] = title

            decision.setdefault("topic_id", st["current_topic_id"])
            decision["current_topic_id"] = st["current_topic_id"]
            return decision

    def _decide(self, cur, cur_sim: float, best_tid, best_sim: float,
                user_text: str, has_signal: bool = False,
                best_status: str = "open") -> dict:
        """决策：continue / reopen / new（规则优先，可选 LLM judge）。

        对齐 dsn memory/topics.py 的规则骨架：
          当前话题够像 → continue；有更相似的历史话题 → reopen；
          有嵌入信号且都不像 → judge（失败回退：cur_sim ≥ CONTINUE×0.6 →
          continue，否则 new）。
        reopen 门槛按候选状态区分（dsn 的 ACTIVATION 语义）：
          **closed（已归档）话题重开走 TOPIC_ACTIVATION_THRESHOLD**（默认更高，
          归档话题复活要求更强的相似依据），open 候选仍走 TOPIC_REOPEN_THRESHOLD。
        **无嵌入信号时退化为"延续当前"**（时间边界负责切分）——
        没有任何相似度依据就按消息开新话题，会把会话碎成片。
        """
        from apps.dsn_study.config import Config as _C
        continue_th = float(_C.TOPIC_CONTINUE_THRESHOLD)
        reopen_th = float(_C.TOPIC_ACTIVATION_THRESHOLD
                          if best_status == "closed"
                          else _C.TOPIC_REOPEN_THRESHOLD)

        if cur is not None and (cur_sim >= continue_th or not has_signal):
            if _C.TOPIC_JUDGE_ALWAYS and self._judge_wanted(user_text):
                judged = self._judge(user_text, cur, cur_sim, best_tid, best_sim)
                if judged:
                    return judged
            return {"action": "continue",
                    "reason": (f"当前话题相似 {cur_sim:.2f}" if has_signal
                               else "无嵌入信号，默认延续")}

        if best_tid and best_sim >= reopen_th:
            if self._judge_wanted(user_text):
                judged = self._judge(user_text, cur, cur_sim, best_tid, best_sim)
                if judged:
                    return judged
            return {"action": "reopen", "reason": f"相似话题 {best_sim:.2f}"}

        if cur is None:
            return {"action": "new", "reason": "无进行中话题"}

        # 有嵌入信号、当前话题不像、也没有可 reopen 的历史话题
        if self._judge_wanted(user_text):
            judged = self._judge(user_text, cur, cur_sim, best_tid, best_sim)
            if judged:
                return judged
        if cur_sim >= continue_th * 0.6:
            return {"action": "continue",
                    "reason": f"当前话题弱相似 {cur_sim:.2f}"}
        return {"action": "new", "reason": f"与当前话题不相似 ({cur_sim:.2f})"}

    def _judge_wanted(self, user_text: str) -> bool:
        return bool(Config.TOPIC_JUDGE_ENABLED and self.judge_chat
                    and (user_text or "").strip())

    def _judge(self, user_text, cur, cur_sim, best_tid, best_sim) -> Optional[dict]:
        """LLM judge（JSON action: continue/reopen/new）；失败返回 None 走规则。"""
        try:
            prompt = (
                "判断用户这条新消息应当属于哪个对话话题。可选动作：\n"
                "continue = 延续当前话题；reopen = 回到更早的相似话题；new = 开新话题。\n"
                f"当前话题标题：{cur['title'] if cur else '（无）'}\n"
                f"候选话题标题：{self.store.get_topic(best_tid)['title'] if best_tid else '（无）'}\n"
                f"用户消息：{user_text[:200]}\n"
                '只输出 JSON：{"action": "continue|reopen|new"}')
            raw = self.judge_chat.send_message(prompt)
            raw = raw[raw.find("{"): raw.rfind("}") + 1]
            import json as _json
            data = _json.loads(raw)
            action = data.get("action")
            if action in ("continue", "reopen", "new"):
                return {"action": action, "reason": "llm_judge"}
        except Exception:   # noqa: BLE001 - judge 失败回退规则
            logger.debug("话题 judge 失败（回退规则）", exc_info=True)
        return None

    def _embed(self, text: str) -> Optional[list]:
        if not self.embedding_client or not (text or "").strip():
            return None
        try:
            return self.embedding_client.embed(text[:512])
        except Exception:   # noqa: BLE001
            return None

    def _score_candidates(self, uid: int, chat_id: int, cur,
                          query_vec) -> dict[str, float]:
        """候选话题相似度：本会话全部话题（open + closed —— closed 是
        reopen 的候选）+ 跨会话 open/pinned 话题。"""
        scores: dict[str, float] = {}
        if not query_vec:
            return scores
        seen = set()
        for scope_chat in (chat_id, None):
            for t in self.store.list_topics(uid, scope_chat, status=None):
                if t["topic_id"] in seen:
                    continue
                seen.add(t["topic_id"])
                vec = t.get("embedding")
                if vec:
                    try:
                        scores[t["topic_id"]] = cosine_similarity(query_vec, vec)
                    except Exception:   # noqa: BLE001
                        pass
            if scope_chat == chat_id and len(scores) >= Config.TOPIC_CANDIDATE_K:
                break
        return scores

    # ── 轮次记录 ──

    def record_turn(self, uid: int, chat_id: int, user_msg: str,
                    assistant_msg: str, round_idx: int = 0) -> None:
        with self._lock:
            st = self._state(uid, chat_id)
            tid = st.get("current_topic_id")
            if not tid:
                return
            now = time.time()
            for role, content in (("user", user_msg or ""),
                                  ("assistant", assistant_msg or "")):
                if not content:
                    continue
                self.store.store.execute(
                    "INSERT INTO study_topic_messages (topic_id, role, content,"
                    " round_idx, created_at) VALUES (?, ?, ?, ?, ?)",
                    (tid, role, content[:20000], round_idx, now))
            topic = self.store.get_topic(tid)
            if topic:
                topic["last_round"] = max(topic.get("last_round", 0), round_idx)
                topic["last_active_at"] = now
                # 话题向量：与最新消息嵌入做滑动平均（缺嵌入则保持）
                vec = self._embed(user_msg or assistant_msg or "")
                if vec and topic.get("embedding"):
                    old = topic["embedding"]
                    topic["embedding"] = [0.7 * o + 0.3 * n
                                          for o, n in zip(old, vec)]
                elif vec:
                    topic["embedding"] = vec
                self.store.save_topic(topic)

    def topic_messages(self, topic_id: str) -> list[dict]:
        rows = self.store.store.execute(
            "SELECT role, content, round_idx FROM study_topic_messages"
            " WHERE topic_id = ? ORDER BY id", (topic_id,))
        return [{"role": r["role"], "content": r["content"],
                 "round_idx": r["round_idx"]} for r in rows]

    # ── close / pin / reopen ──

    def close_topic(self, uid: int, chat_id: int, topic_id: str,
                    summary: str = "") -> bool:
        """关闭话题：自动摘要 + **压缩原文章进 compressed_chunks**（7.7）。"""
        with self._lock:
            topic = self.store.get_topic(topic_id)
            if not topic:
                return False
            msgs = self.topic_messages(topic_id)
            if not summary and self.summary_model is not None and msgs:
                try:
                    transcript = "\n".join(
                        f"[{m['role']}] {m['content']}" for m in msgs[-20:])
                    summary = self.summary_model.summarize_text(transcript) or ""
                except Exception:   # noqa: BLE001
                    summary = ""
            if not summary:
                summary = f"讨论了关于【{topic['title']}】的内容，共 {len(msgs)} 条记录。"
            topic["status"] = "closed"
            topic["summary"] = summary[:int(Config.TOPIC_SUMMARY_CHARS)]
            topic["closed_at"] = time.time()
            self.store.save_topic(topic)

            # 压缩持久化：原文（ChatMessage）存 compressed_chunks，
            # 摘要写 sessions.summary —— 两半边都是 infra 备好但无人接线的 API
            try:
                from infra.models import ChatMessage
                chunk = [ChatMessage(role=m["role"], content=m["content"])
                         for m in msgs]
                if chunk:
                    self.chunks.save_compressed_chunk(chunk,
                                                      session_id=topic_id)
                    # sessions 行 + 摘要（update_summary 需要 sessions 行存在）
                    self.chunks.store.execute(
                        "INSERT OR IGNORE INTO sessions (id, created_at,"
                        " updated_at, summary, mode) VALUES (?, ?, ?, ?, 'topic')",
                        (topic_id, _now(), _now(), ""))
                    self.chunks.update_summary(topic["summary"],
                                               session_id=topic_id)
            except Exception:   # noqa: BLE001 - 压缩存档失败不影响关闭
                logger.warning("压缩块持久化失败 topic=%s", topic_id,
                               exc_info=True)

            if self._states.get((uid, chat_id), {}).get("current_topic_id") == topic_id:
                self._states[(uid, chat_id)]["current_topic_id"] = None
        logger.info("话题已关闭: %s（%d 条消息 → 摘要 %d 字）",
                    topic_id, len(msgs), len(topic["summary"]))
        return True

    def pin_topic(self, uid: int, chat_id: int, topic_id: str,
                  pin: bool = True) -> bool:
        with self._lock:
            topic = self.store.get_topic(topic_id)
            if not topic:
                return False
            topic["is_pinned"] = bool(pin)
            self.store.save_topic(topic)
            st = self._state(uid, chat_id)
            if pin:
                st["active_pins"].add(topic_id)
            else:
                st["active_pins"].discard(topic_id)
        return True

    def reopen_topic(self, topic_id: str) -> bool:
        with self._lock:
            topic = self.store.get_topic(topic_id)
            if not topic:
                return False
            topic["status"] = "open"
            topic["closed_at"] = None
            topic["last_active_at"] = time.time()
            self.store.save_topic(topic)
        return True

    # ── 弹性上下文组装 ──

    def assemble_topic_context(self, uid: int, chat_id: int, *,
                               new_user_message: str = "",
                               system_prefix: str = "",
                               include_tail: bool = True) -> list[dict]:
        """组装话题上下文 → **单条 system 消息**（+ 可选 user 消息）的 dict 列表。

        段序与优先级（对齐 dsn_ui/topic_manager.py:531-657）：
          closed 摘要（SEG_SUMMARY）→ pin/其它 open 原文（SEG_VERBATIM/ACTIVE）
          → 当前话题原文（SEG_VERBATIM/CURRENT, truncatable）
          → SEG_TAIL 最近 N 轮原文（unbounded，保底不丢上一条消息）
        """
        with self._lock:
            st = self._state(uid, chat_id)
            cur_tid = st.get("current_topic_id")
            segments: list[ContextSegment] = []

            # 1) 关闭话题摘要（本会话，最近优先，预算内全给）
            closed = self.store.list_topics(uid, chat_id, status="closed")
            for t in closed[:8]:
                if t.get("summary"):
                    segments.append(ContextSegment(
                        kind=SEG_SUMMARY, content=t["summary"],
                        priority=PRIORITY_SUMMARY,
                        label=f"[话题回顾 · {t['title']}]",
                        truncatable=True, meta={"topic_id": t["topic_id"]}))

            # 2) 其它 open / pinned 话题原文（非当前；pinned 优先）
            actives = [t for t in self.store.list_topics(uid, chat_id,
                                                         status="open")
                       if t["topic_id"] != cur_tid
                       and (t["is_pinned"] or t["topic_id"]
                            in st.get("active_pins", set()))]
            for t in actives[: self.budget.max_open_topics]:
                msgs = self.topic_messages(t["topic_id"])
                text = "\n".join(f"{m['role']}: {m['content']}"
                                 for m in msgs if m.get("content"))
                if text:
                    segments.append(ContextSegment(
                        kind=SEG_VERBATIM, content=text,
                        priority=PRIORITY_ACTIVE,
                        label=f"[进行中话题 · {t['title']}]",
                        truncatable=False, meta={"topic_id": t["topic_id"]}))

            # 3) 当前话题原文（truncatable：预算耗尽可截）
            cur_text_for_dedup = ""
            if cur_tid:
                cur_msgs = self.topic_messages(cur_tid)
                cur_text_for_dedup = "\n".join(
                    f"{m['role']}: {m['content']}" for m in cur_msgs
                    if m.get("content"))
                if cur_text_for_dedup:
                    segments.append(ContextSegment(
                        kind=SEG_VERBATIM, content=cur_text_for_dedup,
                        priority=PRIORITY_CURRENT, label="[当前话题]",
                        truncatable=True, meta={"topic_id": cur_tid}))

            # 4) SEG_TAIL 保底（规则 1：最近 N 轮原文必须 unbounded 注入）
            tail_rounds = max(1, int(getattr(self.budget, "tail_rounds", 3) or 3))
            if include_tail and cur_tid:
                cur_msgs = self.topic_messages(cur_tid)
                tail_msgs = cur_msgs[-tail_rounds * 2:]
                tail_text = "\n".join(
                    f"{m['role']}: {m['content']}" for m in tail_msgs
                    if m.get("content"))
                # 去重：当前原文若完整覆盖尾部且未超预算，不重复注入
                already_covered = bool(
                    cur_text_for_dedup
                    and cur_text_for_dedup.endswith(tail_text)
                    and len(cur_text_for_dedup) <= self.budget.verbatim_chars)
                if tail_text and not already_covered:
                    segments.append(ContextSegment(
                        kind=SEG_TAIL, content=tail_text,
                        priority=PRIORITY_TAIL, label="[最近对话]",
                        truncatable=False, unbounded=True,
                        meta={"rounds": tail_rounds}))

            # plan 只调一次（plan 会就地改写 content，二次调用统计失真）
            plan = self.assembler.plan(segments)

            # 规则 2：所有 system 内容合并成一条 system 消息
            system_parts: list[str] = []
            if system_prefix:
                system_parts.append(system_prefix)
            for seg in plan.kept:
                text = f"{seg.label}\n{seg.content}" if seg.label else seg.content
                if text:
                    system_parts.append(text)

            assembled: list[dict] = []
            merged = "\n\n".join(p for p in system_parts if p)
            if merged:
                assembled.append({"role": "system", "content": merged})
            if new_user_message:
                assembled.append({"role": "user", "content": new_user_message})
            return assembled

    def get_assembly_stats(self) -> dict:
        return self.assembler.last_stats if hasattr(
            self.assembler, "last_stats") else {}


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")
