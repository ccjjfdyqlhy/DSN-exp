# dual/coordinator.py
# 双模协调器 — 编排 Instant + Main 的 SSE 流

from __future__ import annotations

import json
import logging
import queue
import time
from typing import Optional, Generator

from apps.dsn.config import Config

logger = logging.getLogger("DualCoordinator")


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


class DualCoordinator:
    """双模协调器。

    process_stream 是一个普通 Python 生成器 (非 async)，
    由 api/app.py 的 stream_with_context 消费。
    """

    def __init__(
        self,
        instant_service=None,
        main_dispatcher=None,
        stream_registry=None,
        request_pool=None,
        tts_synth=None,
    ):
        self._instant = instant_service
        self._main = main_dispatcher
        self._registry = stream_registry
        self._pool = request_pool
        self._tts = tts_synth
        self._last_progress_tts: dict[str, float] = {}  # task_id → last TTS timestamp
        self._last_text_ready: dict[str, str] = {}  # task_id → last text_ready reply (fallback)

    def get_active_session(self, user_id: int, chat_id: int):
        return self._registry.get_by_user_chat(user_id, chat_id)

    def process_stream(
        self,
        user_id: int,
        chat_id: int,
        message: str,
        nickname: str = "用户",
        chat_name: str = "dual",
    ) -> Generator[str, None, None]:
        """双模 SSE 流生成器"""

        session = None
        try:
            # ── ① Instant 处理用户消息 (step 0) ──
            instant_result = self._instant.handle_request(
                user_id, chat_id, message, nickname,
            )
            yield _sse({
                "status": "instant_reply",
                "reply": instant_result.text,
                "audio_b64": instant_result.audio_b64,
            })

            # ── ② 无 summon → 结束 ──
            if not instant_result.summons:
                yield _sse({"status": "completed"})
                return

            # ── ③ 创建流会话 + 调度主模型 ──
            session = self._registry.create(user_id, chat_id)
            active_tasks: dict[str, bool] = {}  # task_id → is_active

            for summon_desc in instant_result.summons:
                task_id = self._main.dispatch(
                    user_id=user_id, chat_id=chat_id,
                    message=message,
                    nickname=nickname,
                    stream_session=session,
                )
                active_tasks[task_id] = True
                yield _sse({
                    "status": "main_started",
                    "task_id": task_id,
                    "description": summon_desc,
                })

            # ── ④ 并行进度循环 ──
            while active_tasks:
                # 非阻塞检查插话
                try:
                    interject_msg = session.interject_queue.get_nowait()
                    if interject_msg:
                        ir = self._instant.handle_request(
                            user_id, chat_id, interject_msg, nickname,
                        )
                        yield _sse({
                            "status": "instant_reply",
                            "reply": ir.text,
                            "audio_b64": ir.audio_b64,
                        })
                        for summon in ir.summons:
                            tid = self._main.dispatch(
                                user_id=user_id, chat_id=chat_id,
                                message=interject_msg,
                                nickname=nickname,
                                stream_session=session,
                            )
                            active_tasks[tid] = True
                            yield _sse({
                                "status": "main_started",
                                "task_id": tid,
                                "description": summon,
                            })
                        for ctrl in ir.controls:
                            if ctrl["action"] in ("stop", "cancel"):
                                target = ctrl.get("target", "")
                                target_tid = self._find_task(target, active_tasks)
                                if target_tid:
                                    self._main.cancel(target_tid, session)
                                    yield _sse({
                                        "status": "cancelled",
                                        "task_id": target_tid,
                                    })
                except queue.Empty:
                    pass

                # 阻塞等待主模型事件
                try:
                    event = session.progress_queue.get(timeout=0.5)
                except queue.Empty:
                    yield _sse({"status": "heartbeat"})
                    continue

                if not event:
                    continue

                # 哨兵：某个任务已结束
                if event.get("_sentinel"):
                    tid = event.get("task_id", "")
                    active_tasks.pop(tid, None)
                    self._last_text_ready.pop(tid, None)
                    self._last_progress_tts.pop(tid, None)
                    if not active_tasks:
                        yield _sse({"status": "completed"})
                    continue

                status = event.get("status", "")
                tid = event.get("task_id", "")
                end_flag = event.get("end_flag", 0)

                if status == "cancelled":
                    yield _sse({"status": "cancelled", "task_id": tid})
                    continue

                if status == "error":
                    yield _sse({
                        "status": "progress",
                        "task_id": tid,
                        "text": f"任务出错: {event.get('error', '')[:100]}",
                    })
                    continue

                # 进度事件 → Instant 概括
                # 只处理 agent_progress (真正的 agent loop 工具调用步骤)
                # 忽略 thinking (管道插件描述)、text_ready、narrative_update 等内部事件
                if end_flag == 0 and status == "agent_progress":
                    # TTS 节流：同一任务至少间隔 5 秒才播报一次
                    now_ts = time.time()
                    if now_ts - self._last_progress_tts.get(tid, 0) < 5.0:
                        # 跳过 TTS，只发文字进度
                        try:
                            prog = self._instant.summarize_progress(
                                user_id, chat_id, tid, event,
                            )
                            yield _sse({
                                "status": "progress",
                                "task_id": tid,
                                "text": prog.text,
                            })
                        except Exception as e:
                            logger.warning("进度概括失败: %s", e)
                    else:
                        self._last_progress_tts[tid] = now_ts
                        try:
                            prog = self._instant.summarize_progress(
                                user_id, chat_id, tid, event,
                            )
                            yield _sse({
                                "status": "progress",
                                "task_id": tid,
                                "text": prog.text,
                                "audio_b64": prog.audio_b64,
                            })
                        except Exception as e:
                            logger.warning("进度概括失败: %s", e)
                    continue

                # 其他 end_flag=0 事件 → 静默忽略，但捕获 text_ready 的回复
                if end_flag == 0:
                    if status == "text_ready":
                        self._last_text_ready[tid] = event.get("reply", "")
                    continue

                # completed (end_flag=1) → 主模型最终回复
                if end_flag == 1 and status == "completed":
                    # pipeline 的 completed 事件不包含 reply 字段，
                    # 从之前捕获的 text_ready 事件中获取回复
                    final_reply = event.get("reply", "") or self._last_text_ready.get(tid, "")
                    logger.info("DualCoordinator: main_reply reply=%s (from=%s)",
                                final_reply[:60],
                                "completed" if event.get("reply") else "text_ready_fallback")
                    tts_audio = ""
                    if final_reply and self._tts and self._tts.available:
                        tts_lines = self._tts.synthesize(final_reply)
                        if tts_lines:
                            tts_audio = tts_lines[0].get("audio_b64", "")

                    yield _sse({
                        "status": "main_reply",
                        "task_id": tid,
                        "reply": final_reply,
                        "audio_b64": tts_audio,
                    })
                    self._instant.notify_completion(
                        user_id, chat_id, tid, final_reply,
                    )
                    continue

        finally:
            if session:
                self._registry.close(session.stream_id)

    @staticmethod
    def _find_task(prefix: str, active: dict) -> Optional[str]:
        """根据前缀模糊匹配活跃 task_id"""
        if not prefix:
            return None
        for tid in active:
            if tid.startswith(prefix) or tid[:8] == prefix:
                return tid
        return None
