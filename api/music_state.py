# api/music_state.py
# 音乐播放器共享内存状态 — 被 api/music.py 和 NCMApi 共同读写

from __future__ import annotations

import logging

logger = logging.getLogger("music_state")

# 播放器状态（后端内存，由 minimal.py 上报）
_music_state: dict = {
    "state": "stopped",       # playing / paused / stopped
    "current": None,          # {"filename": "..."} 或 None
    "volume": 0.7,
}

# AI 发起的控制命令队列（一次性消费）
_pending_control: dict | None = None


def get_status(consume: bool = True) -> dict:
    """返回当前播放状态。

    如果 consume=True，同时返回并清空 pending_control（minimal.py 轮询用）。
    如果 consume=False，只读不删（AI 查看状态用），但仍在返回中附带 pending 以便 AI 感知。
    """
    global _pending_control
    ret = dict(_music_state)
    ret["pending_control"] = _pending_control
    if consume:
        _pending_control = None
        ret["pending_control"] = None  # 复制后也置空
    return ret


def enqueue_control(action: str, value: str = None) -> dict:
    """AI 调用：入队一条播放控制命令。"""
    global _pending_control
    _pending_control = {"action": action, "value": value}
    logger.info("enqueue_control: action=%s value=%s", action, value)
    return {"success": True, "action": action, "value": value}


def update_state(state: dict) -> None:
    """minimal.py 上报当前播放状态。"""
    global _music_state
    for k in ("state", "current", "volume"):
        if k in state:
            _music_state[k] = state[k]
    logger.debug("update_state: %s", _music_state)
