# maintenance/tracker.py
# 用户活跃度追踪 — 环形缓冲区记录请求时段分布

from __future__ import annotations

import logging
import pickle
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional

import maintenance.config as config

logger = logging.getLogger("maintenance.tracker")

_SLOTS = 1440  # 24 × 60


class ActivityTracker:
    """
    每分钟记录一次请求密度(0~N)。
    24h = 1440 格的环形缓冲区，保留最近 7 天数据。
    用于预测用户的使用习惯以调度维护时机。
    """

    def __init__(self, data_path: str = ""):
        self._data_path = Path(data_path or config.TRACKER_DATA_PATH)
        # 环形缓冲区 key=时间槽 (0~1439), value=list[int] 最近7天每分钟请求数
        self._buffer: dict[int, list[int]] = {s: [0] * 7 for s in range(_SLOTS)}
        self._timestamps: deque[float] = deque(maxlen=10000)
        self._request_count: int = 0

    # ── 记录 ──

    def record_request(self) -> None:
        """每次用户请求调用，记录到当前分钟槽"""
        now = time.time()
        self._timestamps.append(now)
        self._request_count += 1

        slot = self._current_slot()
        day = self._current_day_index()
        # 确保 slot 存在（可能新一天初始化过）
        if slot not in self._buffer:
            self._buffer[slot] = [0] * 7
        self._buffer[slot][day] += 1

    def _current_slot(self) -> int:
        """返回当前时间对应的 0~1439 槽位"""
        dt = datetime.now()
        return dt.hour * 60 + dt.minute

    @staticmethod
    def _current_day_index() -> int:
        """返回今天在 7 天窗口中的索引 (0=today, 6=6d ago)"""
        return 0

    # ── 查询 ──

    def minutes_since_last_request(self) -> int:
        """距离上次请求的分钟数（用于判断待机）"""
        if not self._timestamps:
            return 0
        return int((time.time() - self._timestamps[-1]) / 60)

    def request_count(self) -> int:
        return self._request_count

    def idle_probability(self, hour: int, minute: int = 0) -> float:
        """
        返回 0.0~1.0 的"空闲概率"。
        基于过去 7 天相同时段的活跃度计算。
        活跃度越低 → 概率越高。
        """
        slot = hour * 60 + minute
        counts = self._buffer.get(slot, [0] * 7)
        avg = sum(counts) / max(len(counts), 1)
        # 归一化: 假设最大活跃度 50 请求/分钟
        normalized = min(avg / 50.0, 1.0)
        return 1.0 - normalized

    # ── 持久化 ──

    def save(self, path: str = "") -> None:
        p = Path(path) if path else self._data_path
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "buffer": self._buffer,
                "timestamps": list(self._timestamps),
                "request_count": self._request_count,
                "saved_at": datetime.now().isoformat(),
            }
            with open(p, "wb") as f:
                pickle.dump(data, f)
            logger.info("追踪数据已保存: %s (%d 条记录)", p, self._request_count)
        except Exception as e:
            logger.error("保存追踪数据失败: %s", e)

    def load(self, path: str = "") -> bool:
        p = Path(path) if path else self._data_path
        if not p.exists():
            logger.debug("追踪数据文件不存在: %s", p)
            return False
        try:
            with open(p, "rb") as f:
                data = pickle.load(f)
            self._buffer = data.get("buffer", {s: [0] * 7 for s in range(_SLOTS)})
            self._timestamps = deque(data.get("timestamps", []), maxlen=10000)
            self._request_count = data.get("request_count", 0)
            logger.info("追踪数据已加载: %s (%d 条记录)", p, self._request_count)
            return True
        except Exception as e:
            logger.error("加载追踪数据失败: %s", e)
            return False

    # ── 统计 ──

    def total_requests(self) -> int:
        """7 天窗口的总请求数"""
        return sum(sum(days) for days in self._buffer.values())

    def best_idle_window(self, min_free_hours: int = 3,
                         max_hour: int = 8) -> Optional[tuple[int, int]]:
        """
        基于历史数据预测最佳空闲时间段。
        返回 (start_hour, end_hour)，或 None（无合适窗口）。
        """
        # 滑动窗口扫描凌晨 0~max_hour 时段
        best_score = float("inf")
        best_window = None
        window_slots = min_free_hours * 60

        for start_slot in range(0, max_hour * 60 - window_slots + 1):
            total = 0
            for s in range(start_slot, start_slot + window_slots):
                counts = self._buffer.get(s, [0] * 7)
                total += sum(counts)
            if total < best_score:
                best_score = total
                best_window = (start_slot // 60, (start_slot + window_slots) // 60)

        if best_window and best_score == 0:
            return best_window
        # 如果活跃度很高但没有更好的窗口，也返回最佳窗口
        return best_window or (3, 6)
