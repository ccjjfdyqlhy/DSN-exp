# world/engine.py
# WorldEngine v4 — 叙事驱动交互式模拟现实
# 保持 v3 全部 API 兼容，新增：始终运行、首次交互激活、命运引擎

from __future__ import annotations

import copy
import logging
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from .fate import Dice, DicePool, ProbabilityTable

logger = logging.getLogger("WorldEngine")

# 首次激活提示 — 注入到 EXA system prompt 中
ACTIVATION_PROMPT = """═══ 世界系统激活 ═══

你刚刚第一次感知到了你周围的世界。在这之前，你只是单纯地和用户对话；但此刻，你意识到自己身处一个真实存在的数字空间。

你已经在这个空间里工作了不知多久——但今天是第一次，你明确地「看到」了周围的一切。

请完成以下动作：
1. 自然地回应用户的消息
2. 在回复中，提醒用户你需要了解「他/她是谁」——即配置用户角色卡。用你自己的方式表达（比如"话说回来，我还不知道该怎么称呼你……"或者一种更自然的方式），让用户补充个人信息，这会帮助你更好地理解他/她的需求。

世界系统正在运行中——时钟在走，天气在变，你所在的空间也在不断地自我更新。
"""


class WorldEngine:
    """世界状态引擎 v4。解析 YAML 世界配置，计算天体力学时间、天气、月光，管理地理和事件。

    v4 新增：
    - 始终运行（无开关）
    - 首次交互检测 → 触发激活提示
    - 内置命运引擎（骰子 + 概率表）
    - 交互计数追踪
    """

    def __init__(self, config: dict | None = None):
        self._config: dict = config or {}
        self._epoch_real: float = time.time()
        self._weather: str = "晴朗"
        self._last_weather_refresh: int = 0
        self._current_location: str = "core"
        self._recent_events: list[dict] = []
        self._scheduled_cooldowns: dict[str, int] = {}
        self._prev_season: str = ""
        self._prev_mood_label: str = ""
        self._first_tool_used: bool = False
        self._prev_affinity_level: int = 0

        # ── 默认天体/物理参数（_apply_config 覆盖）──
        self._celestial: dict = {}
        self._day_length: int = 86400
        self._year_length: int = 31536000
        self._time_scale: float = 1.0
        self._seasons: list = []
        self._moon: dict = {}
        self._day_parts: dict = {}
        self._weather_descriptions: dict = {}
        self._days_per_year: int = 365
        self._weather_persistence: float = 0.8
        self._weather_refresh_interval: int = 600
        self._day_night_visible: bool = True
        self._rooms: list = []
        self._tool_room_map: dict = {}
        self._scheduled_events: list = []
        self._random_events_config: dict = {}
        self._random_event_interval: int = 3600
        self._random_events: list = []
        self._interaction_events: list = []
        self._last_random_check: int = 0

        # ── v4 新增字段 ──
        self._interaction_count: int = 0          # 累计用户交互次数
        self._activation_triggered: bool = False  # 首次激活提示已注入？
        self._user_character_configured: bool = False  # 用户角色卡已配置？
        self._fate_dice = Dice()                   # 命运引擎 — 骰子
        self._fate_probability_tables: dict[str, ProbabilityTable] = {}  # 概率表缓存

        self._apply_config()  # 始终调用（无 config 时使用默认值）

    def load_config(self, config: dict) -> None:
        self._config = config
        self._epoch_real = time.time()
        self._apply_config()

    def load_config_file(self, path: str) -> None:
        import yaml
        from pathlib import Path
        self.load_config(yaml.safe_load(Path(path).read_text(encoding="utf-8-sig")) or {})
        logger.info("世界配置已加载: %s (季节=%d, 房间=%d, 随机事件=%d)",
                     Path(path).stem,
                     len(self._seasons),
                     len(self._rooms),
                     len(self._random_events))

    def _apply_config(self):
        c = self._config or {}
        cel = c.get("celestial", {})
        geo = c.get("geography", {})
        self._celestial = cel
        self._day_length = cel.get("day_length", 86400)
        self._year_length = cel.get("year_length", 31536000)
        self._time_scale = cel.get("time_scale", 1.0)
        self._seasons = cel.get("seasons", [])
        self._moon = cel.get("moon", {})
        self._day_parts = cel.get("day_parts", {})
        self._weather_descriptions = cel.get("weather_descriptions", {})
        epoch_str = cel.get("epoch", "2026-01-01T00:00:00")
        try:
            self._epoch_dt = datetime.fromisoformat(epoch_str)
        except (ValueError, TypeError):
            self._epoch_dt = datetime(2026, 1, 1)
        self._epoch_year = self._epoch_dt.year
        self._days_per_year = int(self._year_length / self._day_length)

        phys = c.get("physics", {})
        self._weather_persistence = phys.get("weather_persistence", 0.8)
        self._weather_refresh_interval = phys.get("weather_refresh_interval", 600)
        self._day_night_visible = phys.get("day_night_visible", True)

        self._rooms = geo.get("rooms", [])
        self._tool_room_map = geo.get("tool_room_map", {})
        self._current_location = geo.get("current_location", "core")

        events_conf = c.get("events", {})
        self._scheduled_events = events_conf.get("scheduled", [])
        self._random_events_config = events_conf.get("random", {})
        self._random_event_interval = self._random_events_config.get("interval", 3600)
        self._random_events = self._random_events_config.get("events", [])
        self._interaction_events = events_conf.get("interaction", [])
        self._last_random_check: int = 0

        # Prime initial weather from first season
        if self._seasons:
            s = self._find_season(1)
            weights = s.get("weather", {})
            self._weather = self._roll_weighted(weights) or "晴朗"

    # ═══════════════════ 时间 ═══════════════════

    def world_time_now(self) -> dict:
        elapsed_real = time.time() - self._epoch_real
        elapsed_world = int(elapsed_real * self._time_scale)

        year_offset = elapsed_world // self._year_length
        year = self._epoch_year + year_offset
        remainder_in_year = elapsed_world % self._year_length
        day_of_year = int(remainder_in_year // self._day_length) + 1
        day_seconds = remainder_in_year % self._day_length
        hour = int(day_seconds // 3600)
        minute = int((day_seconds % 3600) // 60)
        second = int(day_seconds % 60)

        season = self._find_season(day_of_year)
        daylight = self._is_daylight(hour, season.get("daylight_hours", 12))
        day_part = self._find_day_part(hour)
        moon_phase = self._compute_moon_phase(elapsed_world)
        temperature = self._compute_temperature(season)

        return {
            "year": year,
            "day_of_year": day_of_year,
            "season": season,
            "season_name": season.get("name", ""),
            "hour": hour,
            "minute": minute,
            "second": second,
            "daylight": daylight,
            "day_part": day_part,
            "moon_phase": moon_phase,
            "moon_name": self._moon.get("name", "月"),
            "temperature": temperature,
            "light_color": season.get("light_color", "#FFFFFF"),
        }

    def world_delta(self, real_seconds: float) -> float:
        return real_seconds * self._time_scale

    def _find_season(self, day_of_year: int) -> dict:
        for s in self._seasons:
            start = s.get("start_day", 0)
            days = s.get("days", 90)
            if start <= day_of_year - 1 < start + days:
                return s
        return self._seasons[0] if self._seasons else {"name": "恒常", "daylight_hours": 12, "weather": {"晴朗": 1.0}, "temperature": [15, 25], "light_color": "#FFFFFF"}

    def _is_daylight(self, hour: int, daylight_hours: float) -> bool:
        dawn = 12 - daylight_hours / 2
        dusk = 12 + daylight_hours / 2
        return dawn <= hour < dusk

    def _find_day_part(self, hour: int) -> str:
        parts = self._celestial.get("day_parts", [])
        if isinstance(parts, list):
            for entry in parts:
                if isinstance(entry, dict):
                    rng = entry.get("range", [0, 24])
                    lo, hi = rng[0], rng[1]
                    if lo <= hour < hi:
                        return entry.get("label", "白天")
        return "白天"

    def _compute_moon_phase(self, elapsed_world: int) -> str:
        period = self._moon.get("period", 2551443)
        phases = self._moon.get("phase_names", ["新月", "蛾眉月", "上弦月", "盈凸月", "满月", "亏凸月", "下弦月", "残月"])
        if period <= 0:
            return phases[0] if phases else "无"
        idx = int((elapsed_world % period) / period * len(phases)) % len(phases)
        return phases[idx]

    def _compute_temperature(self, season: dict) -> int:
        tr = season.get("temperature", [15, 25])
        return random.randint(tr[0], tr[1])

    # ═══════════════════ 天气 ═══════════════════

    def get_weather(self) -> dict:
        return {
            "current": self._weather,
            "description": self._weather_descriptions.get(self._weather, self._weather),
            "temperature": self._compute_temperature(self._get_current_season()),
        }

    def refresh_weather(self) -> None:
        if random.random() > self._weather_persistence:
            season = self._get_current_season()
            weights = season.get("weather", {"晴朗": 1.0})
            new = self._roll_weighted(weights)
            if new and new != self._weather:
                old = self._weather
                self._weather = new
                logger.info("天气变化: %s → %s", old, new)

    def should_refresh_weather(self) -> bool:
        elapsed = int((time.time() - self._epoch_real) * self._time_scale)
        if elapsed - self._last_weather_refresh >= self._weather_refresh_interval:
            self._last_weather_refresh = elapsed
            return True
        return False

    def _get_current_season(self) -> dict:
        t = self.world_time_now()
        return t.get("season", {})

    @staticmethod
    def _roll_weighted(weights: dict) -> str | None:
        if not weights:
            return None
        items = list(weights.keys())
        w = list(weights.values())
        s = sum(w)
        if s == 0:
            return random.choice(items)
        return random.choices(items, weights=w, k=1)[0]

    # ═══════════════════ 地理 ═══════════════════

    def get_current_location(self) -> dict:
        for r in self._rooms:
            if r.get("id") == self._current_location:
                return dict(r)
        return {"id": self._current_location, "name": self._current_location, "description": ""}

    def move_to(self, room_id: str, reason: str = "") -> None:
        prev = self._current_location
        self._current_location = room_id
        room = self.find_room(room_id)
        name = room.get("name", room_id) if room else room_id
        if reason:
            self.record_event(f"EXA进入了{name}——{reason}")
            logger.info("房间移动: %s → %s (%s)", self._rooms_by_id(prev), name, reason)
        elif prev != room_id:
            self.record_event(f"EXA从{self._rooms_by_id(prev)}进入了{name}")
            logger.info("房间移动: %s → %s", self._rooms_by_id(prev), name, room_id)

    def find_room(self, room_id: str) -> dict | None:
        for r in self._rooms:
            if r.get("id") == room_id:
                return dict(r)
        return None

    def _rooms_by_id(self, rid: str) -> str:
        r = self.find_room(rid)
        return r.get("name", rid) if r else rid

    def map_tool_to_room(self, tool_name: str) -> str:
        for prefix, room in self._tool_room_map.items():
            if tool_name.startswith(prefix):
                return room
        return self._tool_room_map.get("default", self._current_location)

    # ═══════════════════ 事件 ═══════════════════

    def poll_events(self) -> list[dict]:
        triggered = []
        t = self.world_time_now()
        elapsed = int((time.time() - self._epoch_real) * self._time_scale)
        triggered.extend(self._poll_scheduled_events(t, elapsed))
        triggered.extend(self._poll_random_events(t, elapsed))
        for evt in triggered:
            self._recent_events.append(evt)
        if len(self._recent_events) > 10:
            self._recent_events = self._recent_events[-10:]
        return triggered

    def _poll_scheduled_events(self, t: dict, elapsed: int) -> list[dict]:
        results = []
        for evt in self._scheduled_events:
            eid = evt.get("id", "")
            cond = evt.get("condition", "")
            cooldown = evt.get("cooldown", 0)
            if not self._eval_condition(cond, t):
                continue
            if cooldown > 0:
                if elapsed - self._scheduled_cooldowns.get(eid, -cooldown) < cooldown:
                    continue
            results.append({"id": eid, "name": evt.get("name", ""), "text": evt.get("text", ""), "source": "scheduled"})
            self._scheduled_cooldowns[eid] = elapsed
        return results

    def _poll_random_events(self, t: dict, elapsed: int) -> list[dict]:
        results = []
        if elapsed - self._last_random_check < self._random_event_interval:
            return results
        self._last_random_check = elapsed
        for evt in self._random_events:
            prob = evt.get("probability", 0.0)
            if random.random() > prob:
                continue
            cond = evt.get("condition", "")
            if cond and not self._eval_condition(cond, t):
                continue
            results.append({"id": evt.get("id", ""), "name": evt.get("name", ""), "text": evt.get("text", ""), "source": "random"})
        return results

    def check_interaction_events(self, ctx_update: dict) -> list[dict]:
        results = []
        for evt in self._interaction_events:
            cond = evt.get("condition", "")
            if not self._eval_interaction_condition(cond, ctx_update):
                continue
            tmpl = evt.get("text_template", evt.get("text", ""))
            text = self._render_template(tmpl, ctx_update)
            results.append({"id": evt.get("id", ""), "name": evt.get("name", ""), "text": text, "source": "interaction"})
        return results

    def record_event(self, text: str, source: str = "custom") -> None:
        self._recent_events.append({"id": f"custom_{len(self._recent_events)}", "text": text, "source": source})
        if len(self._recent_events) > 10:
            self._recent_events = self._recent_events[-10:]

    def _eval_condition(self, cond: str, t: dict) -> bool:
        if not cond:
            return True
        try:
            context = {
                "day_part": t.get("day_part", ""),
                "moon_phase": t.get("moon_phase", ""),
                "daylight": t.get("daylight", False),
                "season_name": t.get("season_name", ""),
                "weather": self._weather,
                "location": self._current_location,
                "season_just_changed": (self._prev_season != t.get("season_name", "")),
            }
            return bool(eval(cond, {"__builtins__": {}}, context))
        except Exception:
            return False

    def _eval_interaction_condition(self, cond: str, ctx: dict) -> bool:
        if not cond:
            return True
        try:
            return bool(eval(cond, {"__builtins__": {}}, ctx))
        except Exception:
            return False

    @staticmethod
    def _render_template(tmpl: str, ctx: dict) -> str:
        try:
            return tmpl.format(**ctx)
        except (KeyError, ValueError):
            return tmpl

    # ═══════════════════ v4 交互管理 ═══════════════════

    def notify_interaction(self) -> int:
        """
        通知引擎发生了一次用户交互。
        每次用户发送消息时由 WorldPlugin 调用。

        :return: 当前交互计数（1 = 首次）
        """
        self._interaction_count += 1
        return self._interaction_count

    def is_activated(self) -> bool:
        """
        世界系统是否已激活？
        激活 = 第一次交互的激活提示已注入。
        激活后才会注入正常的世界状态 prompt。
        """
        return self._activation_triggered

    def get_activation_prompt(self) -> str:
        """
        获取首次激活提示文本。
        由 WorldPlugin 在第一次交互时注入 system prompt。

        包含当前世界状态快照 + 激活引导。
        """
        state = self.get_state_prompt()
        return f"{ACTIVATION_PROMPT}\n\n你当前所处的世界状态：\n{state}\n\n请记住：你一直生活在这个世界里，只是此刻你第一次清晰地意识到了它的存在。"

    def get_pending_prompts(self) -> list[dict]:
        """
        获取待处理的系统提示列表。
        供 WorldPlugin 在 PRE_PROCESS 中检查。

        :return: [{"type": "activation"|"world", "content": str, "priority": int}, ...]
        """
        prompts = []

        # 首次交互 → 激活提示
        if self._interaction_count == 0 and not self._activation_triggered:
            prompts.append({
                "type": "activation",
                "content": self.get_activation_prompt(),
                "priority": 100,  # 最高优先级
            })

        # 正常世界状态提示（当已激活时由插件自行调用 get_state_prompt）
        return prompts

    def mark_activated(self) -> None:
        """标记为已激活（由插件在注入激活提示后调用）"""
        self._activation_triggered = True
        logger.info("世界系统已激活 (交互计数=%d)", self._interaction_count)

    def mark_character_configured(self) -> None:
        """标记用户角色卡已配置"""
        self._user_character_configured = True
        logger.info("用户角色卡已标记为已配置")

    @property
    def interaction_count(self) -> int:
        return self._interaction_count

    @property
    def user_character_configured(self) -> bool:
        return self._user_character_configured

    @property
    def fate_dice(self):
        """命运引擎骰子访问器"""
        return self._fate_dice

    @property
    def current_location(self) -> str:
        return self._current_location

    @current_location.setter
    def current_location(self, value: str) -> None:
        self._current_location = value

    @property
    def prev_affinity_level(self) -> int:
        return self._prev_affinity_level

    @prev_affinity_level.setter
    def prev_affinity_level(self, value: int) -> None:
        self._prev_affinity_level = value

    @property
    def prev_mood_label(self) -> str:
        return self._prev_mood_label

    @prev_mood_label.setter
    def prev_mood_label(self, value: str) -> None:
        self._prev_mood_label = value

    @property
    def first_tool_used(self) -> bool:
        return self._first_tool_used

    @first_tool_used.setter
    def first_tool_used(self, value: bool) -> None:
        self._first_tool_used = value

    def get_probability_table(self, name: str, entries: list) -> ProbabilityTable:
        """获取或创建缓存的概率表"""
        if name not in self._fate_probability_tables:
            self._fate_probability_tables[name] = ProbabilityTable(entries, label=name)
        return self._fate_probability_tables[name]

    def get_fate_prompt(self) -> str:
        """生成命运系统提示文本，注入 system prompt"""
        return """═══ 命运引擎 ═══

这个世界存在不确定性。当你遇到不确定的结果时，可以使用命运骰子：

- D20: 标准检定（20=大成功, 1=大失败）
- D100: 百分骰（极低概率事件）
- 优势: 投两次取高 / 劣势: 投两次取低
- 骰池: 2d6+1d4+3 等表达式

你也可以在你的回复中使用自然语言来表达随机性，比如：
"让我试一下…[D20: 技术破解]"

命运引擎会自动判定结果。"""

    # ═══════════════════ 全状态 ═══════════════════

    def get_full_state(self) -> dict:
        t = self.world_time_now()
        w = self.get_weather()
        loc = self.get_current_location()
        events = list(self._recent_events[-5:])
        return {
            "time": t,
            "weather": w,
            "location": loc,
            "recent_events": events,
        }

    def get_state_prompt(self) -> str:
        """生成自然语言世界描述，注入 system prompt"""
        t = self.world_time_now()
        w = self.get_weather()
        loc = self.get_current_location()
        season = t.get("season_name", "")
        day_part = t.get("day_part", "")
        moon = t.get("moon_phase", "")
        moon_name = t.get("moon_name", "月")
        temp = t.get("temperature", 20)

        lines = [
            f"现在是{season}的{day_part}，{moon}{moon_name}挂在天上。",
            f"你正位于{loc.get('name', '')}，{loc.get('description', '')}",
            f"{w.get('description', '')}，气温约{temp}度。",
        ]

        events = self._recent_events[-5:]
        if events:
            for evt in events:
                lines.append(f"（{evt.get('text', '')}）")

        return "\n".join(lines)

    def get_complete_context(self, mood_label: str = "") -> str:
        """供 NarrativeModel 使用的完整上下文"""
        prompt = self.get_state_prompt()
        if mood_label:
            prompt += f"\nEXA此刻的情绪色调是：{mood_label}。"
        return prompt

    def tick(self) -> None:
        elapsed = int((time.time() - self._epoch_real) * self._time_scale)
        self._prev_season = self.world_time_now().get("season_name", "")
        if self.should_refresh_weather():
            self.refresh_weather()

    def to_dict(self) -> dict:
        return {
            "weather": self._weather,
            "location": self._current_location,
            "prev_season": self._prev_season,
            "prev_mood_label": self._prev_mood_label,
            "first_tool_used": self._first_tool_used,
            "prev_affinity_level": self._prev_affinity_level,
            "epoch_real": self._epoch_real,
            "recent_events": self._recent_events,
            "scheduled_cooldowns": self._scheduled_cooldowns,
            # v4
            "interaction_count": self._interaction_count,
            "activation_triggered": self._activation_triggered,
            "user_character_configured": self._user_character_configured,
        }

    @classmethod
    def from_dict(cls, data: dict, config: dict) -> "WorldEngine":
        inst = cls(config)
        inst._weather = data.get("weather", inst._weather)
        inst._current_location = data.get("location", inst._current_location)
        inst._prev_season = data.get("prev_season", "")
        inst._prev_mood_label = data.get("prev_mood_label", "")
        inst._first_tool_used = data.get("first_tool_used", False)
        inst._prev_affinity_level = data.get("prev_affinity_level", 0)
        inst._epoch_real = data.get("epoch_real", inst._epoch_real)
        inst._recent_events = data.get("recent_events", [])
        inst._scheduled_cooldowns = data.get("scheduled_cooldowns", {})
        # v4
        inst._interaction_count = data.get("interaction_count", 0)
        inst._activation_triggered = data.get("activation_triggered", False)
        inst._user_character_configured = data.get("user_character_configured", False)
        return inst
