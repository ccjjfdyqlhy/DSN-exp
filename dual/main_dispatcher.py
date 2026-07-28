# dual/main_dispatcher.py
# 主模型调度器 — 线程池 + 进度事件捕获 + 取消

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from config import Config

logger = logging.getLogger("MainDispatcher")


class MainModelDispatcher:
    """主模型线程池调度器。

    每次 <summon> 触发一个独立线程运行 engine.chat_stream()，
    产生的 SSE 事件解析后推入 StreamSession.progress_queue。
    主模型线程不等待 Instant 概括，只管 put 事件后继续。
    """

    def __init__(self, engine=None, request_pool=None, max_workers: int = 3):
        self._engine = engine
        self._pool = request_pool
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="main-model",
        )

    def dispatch(
        self,
        user_id: int,
        chat_id: int,
        message: str,
        nickname: str,
        stream_session,
    ) -> str:
        """提交主模型任务到线程池，返回 task_id"""
        task_id = self._pool.add(
            user_id, chat_id, message,
            max_steps=Config.AGENT_MAX_STEPS,
        )

        # 注册取消控制
        cancel_event = threading.Event()
        stream_session.cancel_events[task_id] = cancel_event

        self._executor.submit(
            self._run_main,
            user_id=user_id, chat_id=chat_id,
            message=message, nickname=nickname,
            task_id=task_id, session=stream_session,
            cancel_event=cancel_event,
        )
        logger.info("MainDispatcher: 派发任务 %s (user=%d, msg=%s)",
                    task_id[:8], user_id, message[:50])
        return task_id

    def _run_main(
        self,
        user_id: int,
        chat_id: int,
        message: str,
        nickname: str,
        task_id: str,
        session,
        cancel_event: threading.Event,
    ) -> None:
        """线程函数：运行主模型 pipeline，事件推入 session.progress_queue"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        session.main_loops[task_id] = loop

        try:
            # 运行主模型流式 pipeline (TTS 禁用，由 Instant 负责语音)
            async def _consume():
                """在事件循环中消费 engine.chat_stream() 的异步生成器"""
                async_gen = self._engine.chat_stream(
                    message=message,
                    user_id=user_id,
                    chat_id=chat_id,
                    chat_name="dual-main",
                    nickname=nickname,
                    tts_enabled=False,
                    is_asr_input=False,
                )
                try:
                    async for sse_str in async_gen:
                        # 检查取消
                        if cancel_event.is_set():
                            logger.info("MainDispatcher: 任务 %s 被取消", task_id[:8])
                            session.progress_queue.put({
                                "task_id": task_id,
                                "status": "cancelled",
                                "end_flag": 1,
                            })
                            return

                        # 解析 SSE 字符串
                        event = self._parse_sse(sse_str)
                        if not event:
                            continue

                        # 标注 task_id 和 end_flag
                        event["task_id"] = task_id
                        event["end_flag"] = self._extract_end_flag(event)

                        # 更新请求池
                        self._update_pool(task_id, event)

                        # 推入队列供 SSE 生成器消费
                        session.progress_queue.put(event)

                        # completed → 结束
                        if event.get("status") == "completed":
                            final_reply = event.get("reply", "")
                            self._pool.complete(task_id, final_reply)
                            return

                    # async for 正常结束 (没有 completed 事件)
                    session.progress_queue.put({
                        "task_id": task_id, "status": "completed",
                        "end_flag": 1, "reply": "",
                    })
                finally:
                    # 正确关闭 async generator，避免 "Task was destroyed" 警告
                    try:
                        await async_gen.aclose()
                    except Exception:
                        pass

            loop.run_until_complete(_consume())

        except Exception as e:
            logger.error("MainDispatcher: 任务 %s 异常: %s", task_id[:8], e, exc_info=True)
            session.progress_queue.put({
                "task_id": task_id, "status": "error",
                "error": str(e), "end_flag": 1,
            })
            self._pool.complete(task_id, "", status="failed")
        finally:
            # 哨兵：通知 SSE 生成器此任务已结束
            session.progress_queue.put({"task_id": task_id, "_sentinel": True})
            session.main_loops.pop(task_id, None)
            session.cancel_events.pop(task_id, None)
            loop.close()

    def cancel(self, task_id: str, session) -> None:
        """取消指定任务"""
        session.set_cancel(task_id)
        self._pool.cancel(task_id)

    @staticmethod
    def _parse_sse(sse_str: str) -> Optional[dict]:
        """解析 SSE 字符串 'data: {...}\\n\\n' 为 dict"""
        s = sse_str.strip()
        if s.startswith("data: "):
            s = s[6:]
        if s == "[DONE]" or not s:
            return None
        try:
            return json.loads(s)
        except (json.JSONDecodeError, ValueError):
            return None

    @staticmethod
    def _extract_end_flag(event: dict) -> int:
        """
        判断事件是否表示主模型已结束 (end_flag=1)。
        end_flag=0 表示还有工具调用，Instant 应概括进度。
        end_flag=1 表示完成，Instant 不概括。
        """
        status = event.get("status", "")
        if status == "completed":
            return 1
        if status in ("agent_progress", "thinking", "text_ready",
                      "narrative_update", "line"):
            return 0
        if status in ("filtering", "parsing", "request", "execution", "tts"):
            return 0
        return 0

    def _update_pool(self, task_id: str, event: dict) -> None:
        """根据事件更新请求池状态"""
        status = event.get("status", "")
        if status == "agent_progress":
            self._pool.update(
                task_id,
                current_step=event.get("step", 0),
                max_steps=event.get("max", 5),
                progress_text=event.get("text", ""),
            )
            reply = event.get("reply", "")
            if reply:
                entry = self._pool.get(task_id)
                if entry:
                    entry.intermediate_replies.append(reply[:400])
        elif status == "completed":
            self._pool.update(
                task_id,
                status="completed",
                final_reply=event.get("reply", ""),
            )
