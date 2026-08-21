# harness/groupchat.py
# 原生多用户 AI 群聊底层。
#
# 提供房间 + 成员 + 消息广播的运行时抽象：
#   - GroupChatRoom：一个房间 = 共享消息历史 + 成员表 + 订阅者（asyncio.Queue）广播
#   - GroupChatManager：房间注册表
#
# 与 transport（WebSocket/REST）解耦：上层把每个在线连接注册为一个 subscriber
# （asyncio.Queue），调用 room.publish() 即可向所有在线成员广播。
# AI 响应逻辑也由上层驱动（收到用户消息后运行 AgentLoop，再把回复 publish 出来）。

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from harness.models.base import ChatMessage


@dataclass
class RoomMember:
    """房间成员（= 一个在线连接）。"""
    member_id: str          # 连接唯一标识
    user: Any               # Identity / User
    joined_at: float = 0.0
    extra: dict = field(default_factory=dict)

    @property
    def nickname(self) -> str:
        u = self.user
        if u is None:
            return ""
        return getattr(u, "nickname", "") or getattr(u, "username", "") or getattr(u, "uid", "")

    @property
    def uid(self) -> str:
        u = self.user
        if u is None:
            return ""
        return getattr(u, "uid", "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "member_id": self.member_id,
            "uid": self.uid,
            "nickname": self.nickname,
            "joined_at": self.joined_at,
        }


class GroupChatRoom:
    """一个群聊房间：共享历史 + 成员 + 订阅者广播。"""

    def __init__(self, room_id: str, profile_id: str):
        self.id = room_id
        self.profile_id = profile_id
        self.created_at = time.time()
        self.members: dict[str, RoomMember] = {}       # member_id -> RoomMember
        self.messages: list[ChatMessage] = []          # 共享消息历史
        self._subscribers: set[asyncio.Queue] = set()  # 在线连接广播队列
        self._lock = asyncio.Lock()
        self.history_limit = 200                       # 内存历史上限（持久化由上层负责）
        # AI 回复任务状态（由上层 GroupChat AI runner 维护）
        self._ai_running = False
        self._ai_task: Optional[asyncio.Task] = None

    # ── 订阅（在线连接） ──

    def add_subscriber(self, queue: asyncio.Queue) -> None:
        self._subscribers.add(queue)

    def remove_subscriber(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def subscriber_count(self) -> int:
        return len(self._subscribers)

    async def publish(self, payload: dict[str, Any]) -> None:
        """向所有在线订阅者广播一条事件（不阻塞，队列满则丢弃最旧）。"""
        dead = []
        for q in self._subscribers:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                    q.put_nowait(payload)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass
            except RuntimeError:
                dead.append(q)
        for q in dead:
            self._subscribers.discard(q)

    # ── 成员 ──

    def join(self, member_id: str, user: Any) -> RoomMember:
        member = self.members.get(member_id)
        if member is None:
            member = RoomMember(member_id=member_id, user=user, joined_at=time.time())
            self.members[member_id] = member
        else:
            member.user = user
        return member

    def leave(self, member_id: str) -> Optional[RoomMember]:
        return self.members.pop(member_id, None)

    def has_member(self, member_id: str) -> bool:
        return member_id in self.members

    def is_empty(self) -> bool:
        return not self.members and not self._subscribers

    # ── 消息 ──

    def add_message(self, msg: ChatMessage) -> ChatMessage:
        self.messages.append(msg)
        if len(self.messages) > self.history_limit:
            self.messages = self.messages[-self.history_limit:]
        return msg

    def message_count(self) -> int:
        return len(self.messages)

    # ── 序列化 ──

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "profile_id": self.profile_id,
            "created_at": self.created_at,
            "members": [m.to_dict() for m in self.members.values()],
            "member_count": len(self.members),
            "subscriber_count": len(self._subscribers),
            "message_count": len(self.messages),
        }


class GroupChatManager:
    """群聊房间注册表（进程内单例，由应用持有）。"""

    def __init__(self):
        self.rooms: dict[str, GroupChatRoom] = {}
        self._lock = asyncio.Lock()
        self._seq = 0

    def _next_room_id(self) -> str:
        self._seq += 1
        return f"room_{int(time.time())}_{self._seq}"

    async def create_room(self, profile_id: str) -> GroupChatRoom:
        room = GroupChatRoom(self._next_room_id(), profile_id)
        self.rooms[room.id] = room
        return room

    def get_room(self, room_id: str) -> Optional[GroupChatRoom]:
        return self.rooms.get(room_id)

    def get_or_create(self, room_id: str, profile_id: str) -> GroupChatRoom:
        room = self.rooms.get(room_id)
        if room is None:
            room = GroupChatRoom(room_id, profile_id)
            self.rooms[room_id] = room
        return room

    def list_rooms(self) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self.rooms.values()]

    def delete_room(self, room_id: str) -> bool:
        return self.rooms.pop(room_id, None) is not None


__all__ = ["RoomMember", "GroupChatRoom", "GroupChatManager"]
