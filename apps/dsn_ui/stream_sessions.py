# apps/dsn_ui/stream_sessions.py
"""服务端流式会话注册表：支持断线重连与回放（/v1/stream 协议）。

## 为什么需要它

dsn_ui 原先是"单请求直通流式"：SSE 生成器直接把 AgentLoop 的事件写给
当前 HTTP 连接。一旦浏览器刷新、切标签页、网络抖动导致连接断开，就会：

  1. 客户端失去已产生的输出（TCP 一断，字节就没了）；
  2. 前端走 resume 分支去 GET /v1/stream，而后端只返回 404 →
     前端判定 "Stream connection lost and could not be resumed"，界面卡在"思考中"；
  3. 后端 AgentLoop 仍在继续推理（工具调用、模型生成都没停），
     输出却无人接收 —— GPU 白跑，用户什么也拿不到。

## 设计

每个流式请求对应一个 StreamSession：

  * **后台生产者**：一个独立 asyncio.Task 持续消费 AgentLoop 事件，
    把 SSE 字节追加进内存缓冲区。它与 HTTP 连接完全解耦，
    因此客户端断开不会打断推理，也不会丢数据。
  * **字节缓冲 + 事件通知**：缓冲保留全部 SSE 字节（带上限防爆内存），
    新数据到达时唤醒所有等待的订阅者。
  * **多订阅者**：GET /v1/stream?conv_id=X&from=N 从第 N 字节开始回放，
    先补发历史（重连场景），再实时续传，直到 [DONE]。
  * **TTL 清理**：完成的会话保留一段时间供重连回放，之后回收。

这样前端 mount/visibilitychange 时的 discover → probe → attach 才能成功，
"连接丢失" 与"卡在思考"随之消失。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Callable, Dict, List, Optional

logger = logging.getLogger("DSNUIStreamSessions")

# 单个会话缓冲上限（字节）。SSE 文本膨胀有限，256MB 足以覆盖超长多轮任务，
# 同时避免异常情况下吃光内存。
DEFAULT_MAX_BUFFER_BYTES = 256 * 1024 * 1024
# 会话完成后保留多久，便于前端重连补齐尾部内容。
DEFAULT_TTL_SECONDS = 600.0
# 未被任何订阅者读取时，缓冲区仍持续增长的上限保护
DONE_MARKER = "data: [DONE]\n\n"


@dataclass
class StreamSession:
    """一个后台流式会话的完整状态。"""

    conversation_id: str
    model: str = ""
    started_at: float = field(default_factory=time.time)
    completed_at: float = 0.0
    is_done: bool = False
    error: Optional[str] = None
    buffer: bytearray = field(default_factory=bytearray)
    # 有新字节写入时被 set，订阅者据此唤醒（避免忙轮询）
    _updated: asyncio.Event = field(default_factory=asyncio.Event)
    task: Optional[asyncio.Task] = None
    max_buffer_bytes: int = DEFAULT_MAX_BUFFER_BYTES
    # 生产者已结束但缓冲被截断时置位（客户端会看到不完整回放）
    truncated: bool = False
    subscriber_count: int = 0

    @property
    def total_bytes(self) -> int:
        return len(self.buffer)

    def append(self, data: bytes) -> None:
        """追加 SSE 字节并唤醒等待中的订阅者。"""
        if self.is_done:
            # 已经终止的会话不再接受写入，防止 [DONE] 之后再混入内容
            return
        self.buffer.extend(data)
        if len(self.buffer) > self.max_buffer_bytes:
            # 超限时丢弃最旧的数据（保留最近的，便于查看最新进展）
            overflow = len(self.buffer) - self.max_buffer_bytes
            del self.buffer[:overflow]
            self.truncated = True
            logger.warning(
                "流会话缓冲超限，丢弃最旧 %d 字节: conv=%s",
                overflow, self.conversation_id,
            )
        self._updated.set()

    def finish(self, error: Optional[str] = None) -> None:
        """标记会话结束，唤醒所有订阅者。"""
        if self.is_done:
            return
        self.is_done = True
        self.completed_at = time.time()
        self.error = error
        self._updated.set()

    async def wait_for_data(self, timeout: float = 15.0) -> None:
        """等待新数据或会话结束（用于长轮询式实时续传）。"""
        try:
            await asyncio.wait_for(self._updated.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            # 超时不是错误：交给调用方决定是否继续等待（可借此发心跳）
            pass
        finally:
            self._updated.clear()

    def snapshot_from(self, offset: int) -> bytes:
        """取 offset 之后的所有字节（offset 为已发送字节数）。"""
        if offset < 0:
            offset = 0
        return bytes(self.buffer[offset:])

    def descriptor(self) -> dict:
        """给 /v1/streams/lookup 用的会话描述。"""
        return {
            "conversation_id": self.conversation_id,
            "is_done": self.is_done,
            "total_bytes": self.total_bytes,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


class StreamSessionRegistry:
    """会话注册表：创建 / 查询 / 回放 / 回收。"""

    def __init__(
        self,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        max_buffer_bytes: int = DEFAULT_MAX_BUFFER_BYTES,
    ):
        self._sessions: Dict[str, StreamSession] = {}
        self._lock = asyncio.Lock()
        self.ttl_seconds = ttl_seconds
        self.max_buffer_bytes = max_buffer_bytes

    # ── 生命周期 ──

    async def create(self, conversation_id: str, model: str = "") -> StreamSession:
        """创建（或替换）一个会话。同 id 的旧会话会被结束，避免串流。"""
        async with self._lock:
            old = self._sessions.get(conversation_id)
            if old is not None and not old.is_done:
                logger.info("同 id 新流开始，结束旧会话: %s", conversation_id)
                old.finish(error="superseded")
            session = StreamSession(
                conversation_id=conversation_id,
                model=model,
                max_buffer_bytes=self.max_buffer_bytes,
            )
            self._sessions[conversation_id] = session
            logger.info(
                "创建流会话: conv=%s model=%s (活跃 %d)",
                conversation_id, model, len(self._sessions),
            )
            return session

    async def get(self, conversation_id: str) -> Optional[StreamSession]:
        async with self._lock:
            return self._sessions.get(conversation_id)

    async def lookup(self, conversation_ids: List[str]) -> List[dict]:
        """批量查询会话（只返回调用方显式询问的 id，不泄露其它会话）。"""
        async with self._lock:
            out = []
            for cid in conversation_ids:
                s = self._sessions.get(cid)
                if s is not None:
                    out.append(s.descriptor())
            return out

    async def cancel(self, conversation_id: str) -> bool:
        """取消会话：终止后台生产任务并标记结束。"""
        async with self._lock:
            s = self._sessions.get(conversation_id)
            if s is None:
                return False
            task = s.task
        if task is not None and not task.done():
            task.cancel()
            logger.info("已请求取消流会话: %s", conversation_id)
        s.finish(error="cancelled")
        return True

    async def prune(self) -> None:
        """回收已结束且超过 TTL 的会话。"""
        now = time.time()
        async with self._lock:
            stale = [
                cid for cid, s in self._sessions.items()
                if s.is_done and (now - s.completed_at) > self.ttl_seconds
            ]
            for cid in stale:
                self._sessions.pop(cid, None)
            if stale:
                logger.info("回收过期流会话 %d 个: %s", len(stale), stale[:5])

    async def active_ids(self) -> List[str]:
        async with self._lock:
            return [cid for cid, s in self._sessions.items() if not s.is_done]

    # ── 回放 ──

    async def replay(
        self,
        conversation_id: str,
        offset: int = 0,
        *,
        idle_timeout: float = 15.0,
        max_idle_rounds: Optional[int] = None,
    ) -> AsyncIterator[bytes]:
        """从 offset 开始回放并实时续传，直到会话结束。

        生成器产出的是原始 SSE 字节块。客户端断开时（GeneratorExit）
        只是停止读取，不影响后台生产任务继续跑。
        """
        session = await self.get(conversation_id)
        if session is None:
            raise KeyError(conversation_id)

        session.subscriber_count += 1
        sent = max(0, offset)
        idle_rounds = 0
        try:
            logger.info(
                "开始回放: conv=%s from=%d total=%d done=%s",
                conversation_id, sent, session.total_bytes, session.is_done,
            )
            while True:
                data = session.snapshot_from(sent)
                if data:
                    sent += len(data)
                    idle_rounds = 0
                    yield data
                    continue

                if session.is_done:
                    logger.info(
                        "回放结束(会话已完成): conv=%s sent=%d", conversation_id, sent
                    )
                    return

                await session.wait_for_data(timeout=idle_timeout)
                idle_rounds += 1
                if max_idle_rounds is not None and idle_rounds >= max_idle_rounds:
                    logger.info(
                        "回放空闲超时退出: conv=%s sent=%d", conversation_id, sent
                    )
                    return
        finally:
            session.subscriber_count = max(0, session.subscriber_count - 1)

    def count(self) -> int:
        return len(self._sessions)


registry = StreamSessionRegistry()


def sse_bytes(payload: dict) -> bytes:
    """把事件字典序列化成 SSE 字节块（与直通路径格式完全一致）。"""
    import json as _json
    return f"data: {_json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")
