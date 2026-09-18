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

# SSE 保活心跳间隔（秒）。必须明显小于浏览器/代理的空闲超时
# （常见为 30~60s），也要小于前端 visibilitychange 判定的静默阈值，
# 这样即便模型正在跑一个耗时几十秒的工具，连接也不会被判死。
# 前端请求里的 sse_ping_interval=1 会被用作这一间隔。
DEFAULT_HEARTBEAT_INTERVAL = 1.0


def heartbeat_bytes(conversation_id: str = "") -> bytes:
    """构造一条 SSE 注释行作为心跳。

    以 ':' 开头的是 SSE 注释，规范要求客户端忽略其内容。
    前端解析器只处理以 'data:' 开头的行，因此这些心跳不会污染消息内容，
    但足以让 TCP/浏览器/代理看到"连接仍在活动"，从而不触发空闲断开。
    """
    ts = int(time.time() * 1000)
    return f": ping {ts}\n\n".encode("utf-8")


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

    def resolve_offset(self, offset: int) -> int:
        """把客户端给出的偏移"吸附"到最近的合法 SSE 事件边界。

        背景：客户端为了排除保活心跳等不在缓冲中的字节，会自行推算偏移，
        这类推算很容易出现 ±几字节的误差。若偏差落在一个事件中间，
        重连就会从半个 JSON 中间开始，解析失败导致内容丢失。

        这里把偏移向前吸附到最近的 "data: " 起点（即完整事件的开头），
        确保重连从事件边界开始；找不到就返回原值（从头开始最安全）。
        """
        if offset <= 0:
            return 0
        if offset >= len(self.buffer):
            return len(self.buffer)

        # 判定"合法边界"的唯一标准：该位置必须是一个事件的起点，即
        # 以 "data:" 开头，且它要么在缓冲区开头，要么前面紧跟事件分隔符。
        def _is_event_start(pos: int) -> bool:
            if pos == 0:
                return self.buffer.startswith(b"data:", 0)
            if not self.buffer.startswith(b"data:", pos):
                return False
            # 前一个字符必须是分隔符的结尾（即 pos >= 2 且 buffer[pos-2:pos] == b"\n\n"）
            return pos >= 2 and self.buffer[pos - 2:pos] == b"\n\n"

        if _is_event_start(offset):
            return offset

        # 不合法：向前找最近的事件起点（窗口内），找不到就从头开始。
        # 从头开始只会重发已读内容（客户端按内容幂等处理），
        # 而从半截 JSON 开始会丢内容，因此前者是安全的降级。
        window_start = max(0, offset - 65536)
        search = offset
        while True:
            idx = self.buffer.rfind(b"data:", window_start, search)
            if idx == -1:
                return 0 if window_start == 0 else window_start
            if _is_event_start(idx):
                return idx
            search = idx

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
        heartbeat_interval: float = DEFAULT_HEARTBEAT_INTERVAL,
    ) -> AsyncIterator[bytes]:
        """从 offset 开始回放并实时续传，直到会话结束。

        生成器产出的是原始 SSE 字节块。客户端断开时（GeneratorExit）
        只是停止读取，不影响后台生产任务继续跑。

        **保活**：当底层长时间没有新字节（例如模型正在执行一个耗时很久的
        工具调用，如 90 秒的 nmap 扫描）时，本生成器仍会按 heartbeat_interval
        周期性下发 SSE 注释行 ": ping"。这是关键 —— 否则连接长时间无任何字节，
        浏览器/代理会判定连接已死而断开，前端显示「SSE 中断」，
        但后端其实还在正常执行工具、模型后续仍在生成。

        注意：心跳**只发给当前连接，不写入会话缓冲**。否则重连回放时会把
        历史 ping 当成正文重放一遍。
        """
        session = await self.get(conversation_id)
        if session is None:
            raise KeyError(conversation_id)

        session.subscriber_count += 1
        # 吸附到事件边界：客户端偏移可能因心跳/分片存在几字节误差，
        # 从半个 JSON 中间开始解析会丢内容。
        sent = session.resolve_offset(max(0, offset))
        if sent != offset:
            logger.info(
                "回放偏移吸附: conv=%s %d -> %d（对齐到事件边界）",
                conversation_id, offset, sent,
            )
        idle_rounds = 0
        # 距离上次向客户端发送"真实数据"的秒数，用于决定何时补心跳
        since_real_bytes = 0.0
        hb = max(0.1, heartbeat_interval)
        try:
            logger.info(
                "开始回放: conv=%s from=%d total=%d done=%s heartbeat=%.1fs",
                conversation_id, sent, session.total_bytes, session.is_done, hb,
            )
            while True:
                data = session.snapshot_from(sent)
                if data:
                    sent += len(data)
                    idle_rounds = 0
                    since_real_bytes = 0.0
                    yield data
                    continue

                if session.is_done:
                    logger.info(
                        "回放结束(会话已完成): conv=%s sent=%d", conversation_id, sent
                    )
                    return

                # 无新数据：等待 min(心跳间隔, 空闲轮询间隔) 后决定补心跳还是继续等
                wait_for = min(idle_timeout, hb)
                await session.wait_for_data(timeout=wait_for)
                since_real_bytes += wait_for

                # 到点仍未获得真实数据 → 下发心跳保活（不写入缓冲）
                if since_real_bytes >= hb and session.snapshot_from(sent) == b"":
                    since_real_bytes = 0.0
                    yield heartbeat_bytes(conversation_id)
                    # 心跳不算一次"空闲轮询"，继续等待真实数据
                    continue

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
