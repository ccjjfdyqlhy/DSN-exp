# maintenance/tracker.py
# 用户活跃度追踪 — DB 持久化，无额外文件

from __future__ import annotations

import json
import logging
import time
from collections import deque
from datetime import datetime
from typing import Optional

import maintenance.config as config

logger = logging.getLogger("maintenance.tracker")

_SLOTS = 1440  # 24 × 60
_KV_KEY = "activity_tracker"


class ActivityTracker:
    """
    每分钟记录一次请求密度。
    数据持久化到 system_kv 表，不产生额外文件。
    """

    def __init__(self, db=None):
        self._db = db
        self._buffer: dict[int, list[int]] = {s: [0] * 7 for s in range(_SLOTS)}
        self._timestamps: deque[float] = deque(maxlen=10000)
        self._request_count: int = 0
        self._base_date = datetime.now().date()

    def record_request(self) -> None:
        now = time.time()
        self._timestamps.append(now)
        self._request_count += 1
        self._rotate_if_new_day()
        slot = self._current_slot()
        self._buffer[slot][0] += 1

    def _rotate_if_new_day(self):
        today = datetime.now().date()
        if today == self._base_date:
            return
        days_diff = (today - self._base_date).days
        if days_diff >= 7:
            self._buffer = {s: [0] * 7 for s in range(_SLOTS)}
        else:
            for s in range(_SLOTS):
                row = self._buffer[s]
                for i in range(6, days_diff - 1, -1):
                    row[i] = row[i - days_diff] if i - days_diff >= 0 else 0
                for i in range(min(days_diff - 1, 6)):
                    row[i] = 0
                row[0] = 0
        self._base_date = today

    def _current_slot(self) -> int:
        dt = datetime.now()
        return dt.hour * 60 + dt.minute

    def minutes_since_last_request(self) -> int:
        if not self._timestamps:
            return 0
        return int((time.time() - self._timestamps[-1]) / 60)

    def request_count(self) -> int:
        return self._request_count

    def idle_probability(self, hour: int, minute: int = 0) -> float:
        slot = hour * 60 + minute
        counts = self._buffer.get(slot, [0] * 7)
        avg = sum(counts) / max(len(counts), 1)
        normalized = min(avg / 50.0, 1.0)
        return 1.0 - normalized

    def save(self) -> None:
        if self._db is None:
            return
        try:
            data = {
                "buffer": self._buffer,
                "timestamps": list(self._timestamps),
                "request_count": self._request_count,
                "base_date": self._base_date.isoformat(),
                "saved_at": datetime.now().isoformat(),
            }
            self._db.save_kv(_KV_KEY, json.dumps(data, ensure_ascii=False))
            logger.info("追踪数据已保存 (%d 条记录)", self._request_count)
        except Exception as e:
            logger.error("保存追踪数据失败: %s", e)

    def load(self) -> bool:
        if self._db is None:
            return False
        try:
            raw = self._db.load_kv(_KV_KEY)
            if not raw:
                return False
            data = json.loads(raw)
            self._buffer = data.get("buffer", {s: [0] * 7 for s in range(_SLOTS)})
            self._timestamps = deque(data.get("timestamps", []), maxlen=10000)
            self._request_count = data.get("request_count", 0)
            base_raw = data.get("base_date", "")
            if base_raw:
                try:
                    self._base_date = datetime.fromisoformat(str(base_raw)[:10]).date()
                except Exception:
                    self._base_date = datetime.now().date()
            logger.info("追踪数据已加载 (%d 条记录)", self._request_count)
            return True
        except Exception as e:
            logger.error("加载追踪数据失败: %s", e)
            return False

    def total_requests(self) -> int:
        return sum(sum(days) for days in self._buffer.values())

    def best_idle_window(self, min_free_hours: int = 3, max_hour: int = 8) -> Optional[tuple[int, int]]:
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
        return best_window or (3, 6)
