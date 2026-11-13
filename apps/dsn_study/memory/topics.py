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
import re
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

#: 旧版关话题时写死的占位摘要（「与【X】相关的过往探讨」）。
#: 这句话**不含任何上下文**，却被当作 [话题回顾] 注入 system prompt ——
#: 结果就是主AI 每次都带着一条固定不变的假记忆（"找物理卷子"那条）。
#: 识别出来是为了：(a) 组装时跳过；(b) 迁移脚本回填成有信息量的摘要。
PLACEHOLDER_SUMMARY_RE = re.compile(r"^与【.*?】相关的过往探讨$")


def lexical_similarity(a: str, b: str) -> float:
    """字符 bigram 的 Jaccard 相似度（0~1）。

    为什么需要它：嵌入服务（LMStudio:4501）没起时，话题系统**没有任何
    语义信号** → 判定逻辑退化成「永远延续当前话题」→ 会话被卡死在一个
    话题里，用户怎么换话题都推不下去。词面相似度不需要模型、不需要网络，
    中文短句上够用（同一话题的续问通常会复用关键词）。

    只作**兜底**：有嵌入信号时仍以向量相似度为准。
    """
    a = re.sub(r"\s+", "", a or "")
    b = re.sub(r"\s+", "", b or "")
    if len(a) < 2 or len(b) < 2:
        return 1.0 if a and a == b else 0.0
    ga = {a[i:i + 2] for i in range(len(a) - 1)}
    gb = {b[i:i + 2] for i in range(len(b) - 1)}
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)

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
                       round_idx: int = 0,
                       allow_llm_judge: bool = True) -> dict:
        """新消息进来 → 决定 continue / new / reopen。

        ``allow_llm_judge=False`` 时只用规则判定，不发起 LLM 调用 ——
        语音轮（对讲机）走这条：一次 judge 要 8~18s，而说话人只想要一句回答。
        """
        with self._lock:
            st = self._state(uid, chat_id)
            now = time.time()

            # 1) 时间边界：空闲超时 → 关当前话题
            cur = self.store.get_topic(st["current_topic_id"]) \
                if st["current_topic_id"] else None
            if cur and cur["status"] == "open" \
                    and now - cur["last_active_at"] > self.idle_timeout:
                # 不传 summary → close_topic 用话题原文提炼（有信息量）
                self.close_topic(uid, chat_id, cur["topic_id"])
                st["active_pins"].clear()
                cur = None

            # 2) 语义打分：本会话的候选话题
            query_vec = self._embed(user_text) if self.embedding_client else None
            candidates = self._score_candidates(uid, chat_id, cur, query_vec,
                                                user_text)
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
                                    best_status=best_status,
                                    allow_llm_judge=allow_llm_judge)
            action = decision["action"]

            if action == "continue" and cur:
                pass
            elif action == "reopen" and best_tid:
                # 关当前 → 重开目标 → 切换
                if cur and cur["status"] == "open":
                    self.close_topic(uid, chat_id, cur["topic_id"])
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
                best_status: str = "open",
                allow_llm_judge: bool = True) -> dict:
        """决策：continue / reopen / new（规则优先，可选 LLM judge）。

        对齐 dsn memory/topics.py 的规则骨架：
          当前话题够像 → continue；有更相似的历史话题 → reopen；
          有嵌入信号且都不像 → judge（失败回退：cur_sim ≥ CONTINUE×0.6 →
          continue，否则 new）。
        reopen 门槛按候选状态区分（dsn 的 ACTIVATION 语义）：
          **closed（已归档）话题重开走 TOPIC_ACTIVATION_THRESHOLD**（默认更高，
          归档话题复活要求更强的相似依据），open 候选仍走 TOPIC_REOPEN_THRESHOLD。
        **无嵌入信号时用词面相似度兜底**（见 `lexical_similarity`）：
        嵌入服务（LMStudio:4501）没起时，若还「一律延续当前话题」，
        会话会被卡死在一个话题里 —— 用户换个话题问也还是老上下文。
        词面阈值比向量阈值低（中文 bigram 更严），单独配置。
        """
        from apps.dsn_study.config import Config as _C
        continue_th = float(_C.TOPIC_CONTINUE_THRESHOLD)
        reopen_th = float(_C.TOPIC_ACTIVATION_THRESHOLD
                          if best_status == "closed"
                          else _C.TOPIC_REOPEN_THRESHOLD)

        # ── 无嵌入信号：词面兜底分支（必须在下面的 continue 分支之前）──
        if not has_signal and _C.TOPIC_LEXICAL_ENABLED:
            if _C.TOPIC_JUDGE_ALWAYS and self._judge_wanted(user_text, allow_llm_judge):
                judged = self._judge(user_text, cur, cur_sim, best_tid, best_sim)
                if judged:
                    return judged
            lex_continue = float(_C.TOPIC_LEXICAL_CONTINUE_THRESHOLD)
            lex_new = float(_C.TOPIC_LEXICAL_NEW_THRESHOLD)
            lex_reopen = float(_C.TOPIC_LEXICAL_REOPEN_THRESHOLD)
            text = (user_text or "").strip()

            # 短句（"好的"/"打印"/"下一题"）信息量不足，不足以支撑切话题。
            # 语音场景一大半是这种短句 —— 按它们切话题会把会话碎成片。
            if len(text) < int(_C.TOPIC_LEXICAL_MIN_CHARS):
                if cur is None:
                    return {"action": "new", "reason": "无进行中话题"}
                return {"action": "continue",
                        "reason": f"短句（{len(text)} 字），不足以判定边界"}

            if cur is not None:
                if cur_sim >= lex_continue:
                    return {"action": "continue",
                            "reason": f"词面相似 {cur_sim:.2f}（无嵌入信号）"}
                if cur_sim <= lex_new:
                    return {"action": "new",
                            "reason": f"与当前话题词面无关 ({cur_sim:.2f}，无嵌入信号)"}
                # 中间地带：证据不足 → 保守延续（宁可同一话题，也别碎成片）
                return {"action": "continue",
                        "reason": f"词面证据不足 ({cur_sim:.2f})，保守延续"}

            if best_tid and best_sim >= lex_reopen:
                return {"action": "reopen",
                        "reason": f"词面相似历史话题 {best_sim:.2f}（无嵌入信号）"}
            return {"action": "new", "reason": "无进行中话题"}

        if cur is not None and (cur_sim >= continue_th or not has_signal):
            if _C.TOPIC_JUDGE_ALWAYS and self._judge_wanted(user_text, allow_llm_judge):
                judged = self._judge(user_text, cur, cur_sim, best_tid, best_sim)
                if judged:
                    return judged
            return {"action": "continue",
                    "reason": (f"当前话题相似 {cur_sim:.2f}" if has_signal
                               else "无嵌入信号，默认延续")}

        if best_tid and best_sim >= reopen_th:
            if self._judge_wanted(user_text, allow_llm_judge):
                judged = self._judge(user_text, cur, cur_sim, best_tid, best_sim)
                if judged:
                    return judged
            return {"action": "reopen", "reason": f"相似话题 {best_sim:.2f}"}

        if cur is None:
            return {"action": "new", "reason": "无进行中话题"}

        # 有嵌入信号、当前话题不像、也没有可 reopen 的历史话题
        if self._judge_wanted(user_text, allow_llm_judge):
            judged = self._judge(user_text, cur, cur_sim, best_tid, best_sim)
            if judged:
                return judged
        if cur_sim >= continue_th * 0.6:
            return {"action": "continue",
                    "reason": f"当前话题弱相似 {cur_sim:.2f}"}
        return {"action": "new", "reason": f"与当前话题不相似 ({cur_sim:.2f})"}

    def _judge_wanted(self, user_text: str,
                      allow_llm_judge: bool = True) -> bool:
        if not allow_llm_judge:
            return False
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
            # 短超时：judge 只是"话题归属"的启发式判定，失败有规则回退，
            # 不值得让它把对话热路径堵住。
            raw = self.judge_chat.send_message(
                prompt, timeout=getattr(Config, "TOPIC_JUDGE_TIMEOUT", 8),
                max_retries=0)      # 超时不重试 —— judge 只是启发式判定
            raw = raw[raw.find("{"): raw.rfind("}") + 1]
            import json as _json
            data = _json.loads(raw)
            action = data.get("action")
            if action in ("continue", "reopen", "new"):
                return {"action": action, "reason": "llm_judge"}
        except Exception:   # noqa: BLE001 - judge 失败回退规则
            logger.debug("话题 judge 失败（回退规则）", exc_info=True)
        return None

    def _summarize_in_background(self, topic_id: str, transcript: str) -> None:
        """后台线程做话题摘要，完成后回填 summary。

        不占用对话热路径 —— 摘要是一次可能上万 token 的 LLM 调用，
        同步做会让整轮对话等上几十秒。
        """
        def _work():
            try:
                text = self.summary_model.summarize_text(transcript) or ""
            except Exception:   # noqa: BLE001
                return
            if not text:
                return
            try:
                topic = self.store.get_topic(topic_id) or {}
                if not topic:
                    return
                topic["summary"] = text[:int(Config.TOPIC_SUMMARY_CHARS)]
                self.store.save_topic(topic)
                logger.info("话题摘要已回填: %s", topic_id[:16])
            except Exception:   # noqa: BLE001
                logger.debug("话题摘要回填失败（已跳过）", exc_info=True)

        try:
            threading.Thread(target=_work, daemon=True,
                             name="topic-summarize").start()
        except Exception:   # noqa: BLE001
            logger.debug("话题摘要线程启动失败（已跳过）", exc_info=True)

    @staticmethod
    def _content_summary(msgs: list[dict], limit: int = 400) -> str:
        """从话题原文里提炼一段**有信息量**的摘要（不依赖 LLM）。

        旧实现在关话题时写死「与【X】相关的过往探讨」—— 不含任何事实，
        注入到 system prompt 后只是一条占位噪声。现在改成：
        取该话题的第一条用户发言 + 最后一条助手发言（截断），
        至少让「这个话题聊过什么」是真的。

        后台的 LLM 摘要（`_summarize_in_background`）算好后仍会覆盖它。
        """
        users = [str(m.get("content") or "").strip() for m in msgs
                 if m.get("role") == "user" and str(m.get("content") or "").strip()]
        asst = [str(m.get("content") or "").strip() for m in msgs
                if m.get("role") == "assistant" and str(m.get("content") or "").strip()]
        parts: list[str] = []
        if users:
            parts.append("用户：" + users[0][:120])
        if asst:
            parts.append("助手：" + asst[-1][:limit])
        if not parts:
            return ""
        return "\n".join(parts)

    def _embed(self, text: str) -> Optional[list]:
        if not self.embedding_client or not (text or "").strip():
            return None
        try:
            return self.embedding_client.embed(text[:512])
        except Exception:   # noqa: BLE001
            return None

    def _score_candidates(self, uid: int, chat_id: int, cur,
                          query_vec, user_text: str = "") -> dict[str, float]:
        """候选话题相似度：本会话全部话题（open + closed —— closed 是
        reopen 的候选）+ 跨会话 open/pinned 话题。

        没有嵌入向量时（嵌入服务没起/熔断中）→ **词面相似度兜底**，
        否则判定层拿不到任何相似度依据，会话会卡在一个话题里。
        """
        scores: dict[str, float] = {}
        if not query_vec:
            if not (user_text or "").strip():
                return scores
            return self._score_candidates_lexical(uid, chat_id, user_text)
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

    def _score_candidates_lexical(self, uid: int, chat_id: int,
                                  user_text: str) -> dict[str, float]:
        """词面相似度打分（嵌入服务不可用时的兜底）。"""
        scores: dict[str, float] = {}
        seen: set[str] = set()
        for scope_chat in (chat_id, None):
            for t in self.store.list_topics(uid, scope_chat, status=None):
                if t["topic_id"] in seen:
                    continue
                seen.add(t["topic_id"])
                scores[t["topic_id"]] = self._topic_lexical_score(
                    t["topic_id"], t.get("title") or "", user_text)
            if scope_chat == chat_id and len(scores) >= Config.TOPIC_CANDIDATE_K:
                break
        return scores

    def _topic_lexical_score(self, topic_id: str, title: str,
                             user_text: str) -> float:
        """新消息与某话题的词面相似度（标题 + 最近几条用户发言取最大）。"""
        if not (user_text or "").strip():
            return 0.0
        best = lexical_similarity(user_text, title or "")
        users = [str(m.get("content") or "")
                 for m in self.topic_messages(topic_id)
                 if m.get("role") == "user"]
        for text in reversed(users[-4:]):
            best = max(best, lexical_similarity(user_text, text))
        return best

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
            # 兜底摘要：优先用话题原文提炼（**有信息量**），
            # 而不是「与【X】相关的过往探讨」这种零信息占位串。
            placeholder = self._content_summary(msgs)
            if not summary and self.summary_model is not None and msgs:
                # 摘要**放后台**：它是一次可能上万 token 的 LLM 调用，
                # 同步做会把整轮对话堵住（对讲机场景尤其致命）。
                # 先用占位摘要顶上，摘要好了再回填。
                try:
                    transcript = "\n".join(
                        f"[{m['role']}] {m['content']}" for m in msgs[-20:])
                except Exception:   # noqa: BLE001
                    transcript = ""
                if transcript:
                    self._summarize_in_background(topic_id, transcript)
                summary = placeholder
            if not summary:
                summary = placeholder
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
                summary = (t.get("summary") or "").strip()
                # 旧版占位摘要（零信息）不进上下文 —— 它只会让主AI 抱着
                # 一条固定不变的假记忆。空摘要同理。
                if not summary or PLACEHOLDER_SUMMARY_RE.match(summary):
                    continue
                segments.append(ContextSegment(
                    kind=SEG_SUMMARY, content=summary,
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
