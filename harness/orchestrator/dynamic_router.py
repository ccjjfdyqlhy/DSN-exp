# harness/models/dynamic_router.py
# DynamicRouter + MonitorStore — 端点可用性学习路由（场景无关，从 DSN 广义化移植）。
#
# 问题域：同一"服务"有多个可用端点（API 账号 / 后端 / 镜像站），
# 各端点在一天不同时段的可靠性不同。本模块：
#   - MonitorStore   记录每次请求的成功/失败/延迟观察（线程安全 + JSON 持久化）
#   - DynamicRouter  基于观察为每个端点生成动态时段优先级（reliability 加权）
#
# 与 DSN 的差异：端点来源抽象为 AccountProvider 协议（names()/get()），
# 端点为 ManagedAccount 协议（name/enabled/priority/time_slots + 时段写入方法），
# 手动时段规则可通过 manual_schedule 回调注入——应用只需接线，不承载学习逻辑。

from __future__ import annotations

import datetime
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Callable, Optional, Protocol, runtime_checkable

logger = logging.getLogger("DynamicRouter")

# 学习窗口: 观察所在小时 ± 1 小时
DEFAULT_WINDOW = 1
# 每个 (端点, 时段) 至少需要的观察数才参与学习
DEFAULT_MIN_OBS = 2
# 观察有效时长（超过则不计入学习）
DEFAULT_MAX_AGE_DAYS = 7
# 保留观察数上限（内存 + 磁盘均截断）
MAX_OBS = 3000
# 每累计 N 条新观察强制落盘一次
FLUSH_EVERY = 100


def _minutes(hhmm: str) -> int:
    try:
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return -1


class MonitorStore:
    """监控观察存储 — 线程安全内存缓存 + JSON 持久化。"""

    def __init__(self, path: str | None = None):
        self._path = path or os.path.join(
            os.getcwd(), ".dsn", "endpoint_monitor.json")
        self._lock = threading.Lock()
        self._observations: list[dict] = []
        self._enabled = False
        self._pending = 0
        self.load()

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        with self._lock:
            self._enabled = bool(value)
            self._pending += 1
        self.save()

    def load(self) -> None:
        try:
            p = Path(self._path)
            if not p.exists():
                return
            data = json.loads(p.read_text(encoding="utf-8"))
            with self._lock:
                self._observations = list(data.get("observations", []) or [])
                self._enabled = bool(data.get("enabled", False))
        except Exception as e:
            logger.error("加载监控数据失败: %s", e)

    def save(self) -> None:
        try:
            p = Path(self._path)
            p.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                data = {
                    "enabled": self._enabled,
                    "observations": self._observations[-MAX_OBS:],
                }
                self._pending = 0
            p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            try:
                os.chmod(self._path, 0o600)
            except Exception:
                pass
        except Exception as e:
            logger.error("保存监控数据失败: %s", e)

    def record(self, account: str, ok: bool, latency_ms: float = 0.0,
               source: str = "request", hour: int | None = None,
               ts: float | None = None) -> None:
        now = ts if ts is not None else time.time()
        with self._lock:
            self._observations.append({
                "account": str(account),
                "ts": now,
                "hour": datetime.datetime.now().hour if hour is None else int(hour),
                "ok": bool(ok),
                "latency_ms": round(float(latency_ms or 0), 1),
                "source": str(source),
            })
            if len(self._observations) > MAX_OBS:
                self._observations = self._observations[-MAX_OBS:]
            self._pending += 1
            do_save = self._pending >= FLUSH_EVERY
        if do_save:
            self.save()

    def snapshot(self, max_age_seconds: float | None = None) -> list[dict]:
        with self._lock:
            obs = list(self._observations)
        if max_age_seconds is not None:
            cutoff = time.time() - max_age_seconds
            obs = [o for o in obs if o.get("ts", 0) >= cutoff]
        return obs

    def count(self) -> int:
        with self._lock:
            return len(self._observations)

    def flush(self) -> None:
        with self._lock:
            dirty = self._pending > 0
        if dirty:
            self.save()

    def clear(self) -> None:
        with self._lock:
            self._observations = []
            self._pending = 1
        self.save()


@runtime_checkable
class ManagedAccount(Protocol):
    """受管端点协议：只读属性 + 手动时段（写入在 AccountProvider 上）。"""

    name: str
    enabled: bool
    priority: int
    time_slots: list[dict]


@runtime_checkable
class AccountProvider(Protocol):
    """端点来源协议：枚举/获取端点 + 写入动态时段（写入在管理器上）。"""

    def names(self) -> list[str]: ...
    def get(self, name: str) -> Optional[ManagedAccount]: ...
    def set_dynamic_slots(self, name: str, slots: list[dict]) -> Any: ...
    def clear_dynamic_slots(self, name: str) -> Any: ...


class DynamicRouter:
    """基于监控数据为各端点生成动态时段优先级。"""

    def __init__(
        self,
        store: MonitorStore | None = None,
        provider: Optional[AccountProvider] = None,
        *,
        window: int = DEFAULT_WINDOW,
        min_obs: int = DEFAULT_MIN_OBS,
        max_age_days: int = DEFAULT_MAX_AGE_DAYS,
        manual_schedule: Optional[Callable[[], list[dict]]] = None,
    ):
        self._store = store or MonitorStore()
        self._provider = provider
        self._window = window
        self._min_obs = min_obs
        self._max_age_days = max_age_days
        # 手动时段规则源（返回 [{account,start,end}, ...]）；None = 无全局规则
        self._manual_schedule = manual_schedule

    # ── 基础访问 ──

    def _manager(self) -> AccountProvider:
        if self._provider is None:
            raise RuntimeError("未注入 AccountProvider（endpoint 来源）")
        return self._provider

    def is_enabled(self) -> bool:
        return self._store.enabled

    def set_enabled(self, enabled: bool) -> None:
        self._store.enabled = enabled
        logger.info("动态路由 %s", "已启用" if enabled else "已关闭")

    def record(self, account: str, ok: bool, latency_ms: float = 0.0,
               source: str = "request", hour: int | None = None,
               ts: float | None = None) -> None:
        self._store.record(account, ok, latency_ms, source=source,
                           hour=hour, ts=ts)

    def flush(self) -> None:
        self._store.flush()

    def params(self) -> dict:
        return {
            "enabled": self.is_enabled(),
            "window": self._window,
            "min_obs": self._min_obs,
            "max_age_days": self._max_age_days,
        }

    def stats(self) -> dict:
        obs = self._store.snapshot()
        by_src: dict[str, int] = {}
        by_acc: dict[str, int] = {}
        ok_count = 0
        for o in obs:
            src = o.get("source", "")
            by_src[src] = by_src.get(src, 0) + 1
            by_acc[o.get("account", "?")] = by_acc.get(o.get("account", "?"), 0) + 1
            if o.get("ok"):
                ok_count += 1
        return {
            "enabled": self.is_enabled(),
            "observations": len(obs),
            "ok": ok_count,
            "by_source": by_src,
            "by_account": by_acc,
        }

    # ── 可靠性估计 ──

    def _reliability(self, obs: list[dict], account: str, hour: int) -> tuple[float | None, int]:
        """返回 (加权成功率, 命中观察数)；无命中返回 (None, 0)。"""
        now = time.time()
        num = 0.0
        den = 0.0
        n = 0
        for o in obs:
            if o.get("account") != account:
                continue
            d = abs(int(o.get("hour", -1)) - hour)
            d = min(d, 24 - d)
            if d > self._window:
                continue
            age_days = (now - float(o.get("ts", now))) / 86400.0
            w = 1.0 / (1.0 + age_days)  # 越近权重越高
            den += w
            num += w * (1.0 if o.get("ok") else 0.0)
            n += 1
        if n == 0:
            return None, 0
        return (num / den if den else 0.0), n

    # ── 计算当前时段排序（不写入） ──

    def plan(self) -> dict[int, list[tuple[str, int]]]:
        """每个小时各端点的动态排序。返回 {hour: [(name, rank), ...]}"""
        mgr = self._manager()
        obs = self._store.snapshot(max_age_seconds=self._max_age_days * 86400)
        accounts = [a for a in (mgr.get(n) for n in mgr.names()) if a is not None]
        result: dict[int, list[tuple[str, int]]] = {}
        for h in range(24):
            ranked = []
            for acc in accounts:
                if not acc.enabled:
                    continue
                rel, n = self._reliability(obs, acc.name, h)
                if rel is None or n < self._min_obs:
                    continue
                ranked.append((acc.name, acc.priority, rel))
            ranked.sort(key=lambda x: (-x[2], x[1], x[0]))
            result[h] = [(name, i) for i, (name, _, _) in enumerate(ranked)]
        return result

    # ── 学习并写入动态时段 ──

    def recompute(self) -> dict:
        """基于监控数据为每个受管端点重算动态时段（source=dynamic）。

        手动时段覆盖的时段不会被动态时段触碰。
        """
        mgr = self._manager()
        if not self.is_enabled():
            return {"applied": 0, "message": "动态路由未启用"}
        obs = self._store.snapshot(max_age_seconds=self._max_age_days * 86400)
        accounts = [a for a in (mgr.get(n) for n in mgr.names()) if a is not None]

        learned: dict[str, list[int | None]] = {a.name: [None] * 24 for a in accounts}
        for h in range(24):
            ranked = []
            for acc in accounts:
                if not acc.enabled:
                    continue
                rel, n = self._reliability(obs, acc.name, h)
                if rel is None or n < self._min_obs:
                    continue
                ranked.append((acc.name, acc.priority, rel))
            ranked.sort(key=lambda x: (-x[2], x[1], x[0]))
            for i, (name, _, _) in enumerate(ranked):
                learned[name][h] = i

        applied = 0
        for acc in accounts:
            manual_hours = self._manual_hours(acc)
            slots = self._slots_from_hourly(learned[acc.name], manual_hours)
            if slots:
                mgr.set_dynamic_slots(acc.name, slots)
                applied += 1
            else:
                mgr.clear_dynamic_slots(acc.name)
        self._store.flush()
        logger.info("动态路由重算完成: %d 个端点写入动态时段", applied)
        return {"applied": applied, "accounts": len(accounts)}

    def clear(self) -> None:
        """清空监控历史与全部动态时段（保留手动时段与开关状态）。"""
        mgr = self._manager()
        for name in mgr.names():
            mgr.clear_dynamic_slots(name)
        self._store.clear()
        logger.info("动态路由监控数据已清空")

    # ── 手动时段覆盖 ──

    def _manual_hours(self, acc) -> set[int]:
        """返回被手动时段覆盖的小时集合（端点自身 time_slots + 全局手动规则）。"""
        covered: set[int] = set()

        def _cover(h: int, start: int, end: int) -> bool:
            h0, h1 = h * 60, h * 60 + 60
            if start <= end:
                return h0 < end and h1 > start
            return h0 >= start or h1 <= end  # 跨午夜

        for s in acc.time_slots:
            if s.get("source") == "dynamic":
                continue
            start = _minutes(s.get("start", ""))
            end = _minutes(s.get("end", ""))
            if start < 0 or end < 0:
                continue
            for h in range(24):
                if _cover(h, start, end):
                    covered.add(h)

        if self._manual_schedule is not None:
            try:
                for rule in self._manual_schedule():
                    if rule.get("account") != acc.name:
                        continue
                    start = _minutes(rule.get("start", ""))
                    end = _minutes(rule.get("end", ""))
                    if start < 0 or end < 0:
                        continue
                    for h in range(24):
                        if _cover(h, start, end):
                            covered.add(h)
            except Exception:
                pass
        return covered

    @classmethod
    def _slots_from_hourly(cls, prios: list[int | None],
                           manual_hours: set[int]) -> list[dict]:
        """把 24 小时优先级数组压缩成区间时段，合并连续相同优先级。"""
        slots: list[dict] = []
        start: int | None = None
        prev: int | None = None
        for h in range(24):
            p = prios[h]
            if p is None or h in manual_hours:
                if start is not None:
                    slots.append({"start": f"{start:02d}:00", "end": f"{h:02d}:00",
                                  "priority": prev, "source": "dynamic"})
                    start, prev = None, None
                continue
            if start is None:
                start, prev = h, p
            elif p == prev:
                continue
            else:
                slots.append({"start": f"{start:02d}:00", "end": f"{h:02d}:00",
                              "priority": prev, "source": "dynamic"})
                start, prev = h, p
        if start is not None:
            slots.append({"start": f"{start:02d}:00", "end": "24:00",
                          "priority": prev, "source": "dynamic"})
        return slots
