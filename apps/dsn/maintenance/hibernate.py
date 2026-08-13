# maintenance/hibernate.py
# HibernateManager — 快速缓存模式下，将非关键操作挂起到空闲队列延迟执行

from __future__ import annotations

import logging
import queue
import time
from typing import TYPE_CHECKING

from apps.dsn.maintenance import config as maint_config

if TYPE_CHECKING:
    from apps.dsn.engine import DSNEngine

logger = logging.getLogger("HibernateManager")


class HibernateManager:
    """
    挂起任务管理器。

    fastcache 模式下，原本同步/后台执行的 WorldPlugin 后置旁白、
    PersonalityV3 情绪分析、Memory 摘要等被包装为 HibernateTask，
    推入 FIFO 队列，等到系统空闲时自动排空。

    空闲触发入口：
      - 心跳 /api/heartbeat
      - 下轮对话 PRE_PROCESS
    """

    MAX_QUEUE = maint_config.HIBERNATE_MAX_QUEUE

    def __init__(self, engine: DSNEngine):
        self._engine = engine
        self._queue: queue.Queue[dict] = queue.Queue()
        self._dropped = 0
        # 任务节流: uid -> 上次执行时间戳
        self._last_personality: dict[int, float] = {}
        self._last_memory: dict[int, float] = {}

    # ── 推入 ──

    def push(self, task_type: str, snapshot: dict) -> bool:
        task = {
            "type": task_type,
            "snapshot": snapshot,
            "enqueued_at": time.time(),
        }
        if self._queue.qsize() >= self.MAX_QUEUE:
            try:
                self._queue.get_nowait()
                self._dropped += 1
            except queue.Empty:
                pass
        self._queue.put(task)
        return True

    # ── 排空 ──

    def drain(self, max_count: int = 5) -> int:
        processed = 0
        for _ in range(max_count):
            try:
                task = self._queue.get_nowait()
            except queue.Empty:
                break
            try:
                self._execute(task)
            except Exception as e:
                logger.error("Hibernate 任务失败 type=%s: %s", task["type"], e)
            self._queue.task_done()
            processed += 1
        if processed:
            logger.info("Hibernate 排空了 %d 个任务 (队列剩余 %d)", processed, self._queue.qsize())
        return processed

    def size(self) -> int:
        return self._queue.qsize()

    # ── 内部派发 ──

    def _execute(self, task: dict):
        ttype = task["type"]
        snap = task["snapshot"]
        handler = {
            "world_post_process": self._exec_world,
            "personality_analysis": self._exec_personality,
            "memory_summarize": self._exec_memory,
        }.get(ttype)
        if handler:
            handler(snap)
        else:
            logger.warning("未知 Hibernate 任务类型: %s", ttype)

    # ── WorldPlugin 后置旁白 + tick ──

    def _exec_world(self, snap: dict):
        eng = getattr(self._engine, "world_engine", None)
        nar = getattr(self._engine, "narrative_model", None)
        if not eng or not nar:
            return
        mood_label = snap.get("mood_label", "")
        wc = eng.get_complete_context(mood_label)
        narrative = nar.narrate(
            user_msg=snap["message"],
            main_reply=snap["reply"],
            world_context=wc,
            mood_label=mood_label,
        )
        if narrative:
            logger.info("Hibernate[world]: 旁白已生成 (%d 字)", len(narrative))

        # interaction events
        update = snap.get("interaction_update", {})
        if update:
            for evt in eng.check_interaction_events(update):
                eng.record_event(evt.get("text", ""), "interaction")

        eng.tick()

    # ── PersonalityV3 情绪分析（带节流：同用户最小间隔，降低本地 GPU 争抢）──

    def _exec_personality(self, snap: dict):
        uid = snap.get("user_id")
        cooldown = getattr(maint_config, "HIBERNATE_PERSONALITY_COOLDOWN", 30)
        now = time.time()
        if uid is not None:
            last = self._last_personality.get(uid, 0.0)
            if now - last < cooldown:
                logger.debug("Hibernate[pv3]: 节流跳过 uid=%d (距上次 %.0fs < %ds)",
                             uid, now - last, cooldown)
                return
            self._last_personality[uid] = now
        pe = getattr(self._engine, "prompt_engine", None)
        pv3 = getattr(pe, "personality_v3", None) if pe else None
        if not pv3 or not pv3.enabled:
            return
        try:
            result = pv3.analyze_interaction(
                uid=uid,
                user_message=snap["message"],
                ai_reply=snap["reply"],
                conversation_history=snap.get("history", ""),
            )
            if result:
                d_joy = result.new_mood.get("joy", 0.5) - result.old_mood.get("joy", 0.5)
                d_aff = result.new_affinity - result.old_affinity
                logger.info("Hibernate[pv3]: uid=%s joy=%+.2f affinity=%+.1f",
                            uid, d_joy, d_aff)
        except Exception as e:
            logger.error("Hibernate[pv3] 分析失败: %s", e)

    # ── Memory 摘要 + embedding（带节流：同用户最小间隔）──

    def _exec_memory(self, snap: dict):
        ms = getattr(self._engine, "memory_system", None)
        if not ms:
            return
        uid = snap.get("user_id")
        cooldown = getattr(maint_config, "HIBERNATE_MEMORY_COOLDOWN", 60)
        now = time.time()
        if uid is not None:
            last = self._last_memory.get(uid, 0.0)
            if now - last < cooldown:
                logger.debug("Hibernate[memory]: 节流跳过 uid=%s (距上次 %.0fs < %ds)",
                             uid, now - last, cooldown)
                return
            self._last_memory[uid] = now
        try:
            ms.summarize_turn(
                user_id=uid,
                chat_id=snap["chat_id"],
                round_idx=snap.get("round_index"),
                user_msg=snap["message"],
                assistant_reply=snap["reply"],
                async_mode=True,
                topic_id=snap.get("topic_id"),
            )
            logger.debug("Hibernate[memory]: 摘要任务已提交 uid=%s", uid)
        except Exception as e:
            logger.error("Hibernate[memory] 失败: %s", e)
