# prompt/personality_v3/events.py
# 语义事件层 — LLM 只负责把用户消息分类为结构化事件，所有数值由确定性映射表给出。
# 设计原则：数值被限制在确定性层，LLM 回到它擅长的语义判断。

from __future__ import annotations

from dataclasses import dataclass, field

# === 事件类型枚举（角色无关） ===

EVENT_TASK_REQUEST = "task_request"
EVENT_PROBLEM_SOLVING = "problem_solving"
EVENT_THANKS = "thanks"
EVENT_PRAISE = "praise"
EVENT_PERSONAL_SHARING = "personal_sharing"
EVENT_VENTING = "venting"
EVENT_COMPLAINT = "complaint"
EVENT_CONFLICT = "conflict"
EVENT_BOUNDARY_VIOLATION = "boundary_violation"
EVENT_SILENCE = "silence"
EVENT_HUMOR = "humor"
EVENT_DEEP_TOPIC = "deep_topic"
EVENT_EMOTIONAL_SUPPORT = "emotional_support"
EVENT_FAREWELL = "farewell"
EVENT_NEUTRAL = "neutral"

EVENT_TYPES: list[str] = [
    EVENT_TASK_REQUEST,
    EVENT_PROBLEM_SOLVING,
    EVENT_THANKS,
    EVENT_PRAISE,
    EVENT_PERSONAL_SHARING,
    EVENT_VENTING,
    EVENT_COMPLAINT,
    EVENT_CONFLICT,
    EVENT_BOUNDARY_VIOLATION,
    EVENT_SILENCE,
    EVENT_HUMOR,
    EVENT_DEEP_TOPIC,
    EVENT_EMOTIONAL_SUPPORT,
    EVENT_FAREWELL,
    EVENT_NEUTRAL,
]

VALID_EVENT_TYPES: set[str] = set(EVENT_TYPES)

INTENSITY_LOW = "low"
INTENSITY_MEDIUM = "medium"
INTENSITY_HIGH = "high"

VALID_INTENSITIES: set[str] = {INTENSITY_LOW, INTENSITY_MEDIUM, INTENSITY_HIGH}

# 强度→乘数：low/medium/high
INTENSITY_FACTORS: dict[str, float] = {
    INTENSITY_LOW: 0.5,
    INTENSITY_MEDIUM: 1.0,
    INTENSITY_HIGH: 1.6,
}

VALID_VALENCES: set[str] = {"positive", "neutral", "negative"}

# === 情绪冲量表（中等强度基础冲量） ===
# 每类事件对 joy/sadness/anger/fear 的基准冲量，实际冲量 = 基础值 × 强度系数。

EVENT_MOOD_IMPULSES: dict[str, dict[str, float]] = {
    EVENT_TASK_REQUEST: {"joy": 0.02, "sadness": 0.00, "anger": 0.00, "fear": 0.00},
    EVENT_PROBLEM_SOLVING: {"joy": 0.04, "sadness": 0.00, "anger": 0.00, "fear": 0.00},
    EVENT_THANKS: {"joy": 0.08, "sadness": 0.00, "anger": 0.00, "fear": 0.00},
    EVENT_PRAISE: {"joy": 0.12, "sadness": 0.00, "anger": 0.00, "fear": 0.00},
    EVENT_PERSONAL_SHARING: {"joy": 0.06, "sadness": -0.01, "anger": 0.00, "fear": 0.00},
    EVENT_VENTING: {"joy": -0.02, "sadness": 0.03, "anger": 0.00, "fear": 0.00},
    EVENT_COMPLAINT: {"joy": -0.03, "sadness": 0.00, "anger": 0.04, "fear": 0.00},
    EVENT_CONFLICT: {"joy": -0.05, "sadness": 0.02, "anger": 0.08, "fear": 0.02},
    EVENT_BOUNDARY_VIOLATION: {"joy": -0.04, "sadness": 0.00, "anger": 0.06, "fear": 0.04},
    EVENT_SILENCE: {"joy": -0.01, "sadness": 0.01, "anger": 0.00, "fear": 0.00},
    EVENT_HUMOR: {"joy": 0.10, "sadness": 0.00, "anger": -0.01, "fear": -0.01},
    EVENT_DEEP_TOPIC: {"joy": 0.05, "sadness": 0.00, "anger": -0.02, "fear": 0.00},
    EVENT_EMOTIONAL_SUPPORT: {"joy": -0.01, "sadness": 0.04, "anger": 0.00, "fear": 0.02},
    EVENT_FAREWELL: {"joy": 0.00, "sadness": 0.02, "anger": 0.00, "fear": 0.00},
    EVENT_NEUTRAL: {"joy": 0.00, "sadness": 0.00, "anger": 0.00, "fear": 0.00},
}

# === 亲密度权重表（中等强度基础权重，正=增长，负=降低） ===

EVENT_AFFINITY_WEIGHTS: dict[str, float] = {
    EVENT_TASK_REQUEST: 0.5,
    EVENT_PROBLEM_SOLVING: 1.0,
    EVENT_THANKS: 1.5,
    EVENT_PRAISE: 2.0,
    EVENT_PERSONAL_SHARING: 1.8,
    EVENT_VENTING: 0.8,
    EVENT_COMPLAINT: -1.5,
    EVENT_CONFLICT: -3.0,
    EVENT_BOUNDARY_VIOLATION: -4.0,
    EVENT_SILENCE: -0.2,
    EVENT_HUMOR: 1.2,
    EVENT_DEEP_TOPIC: 1.5,
    EVENT_EMOTIONAL_SUPPORT: 1.2,
    EVENT_FAREWELL: 0.2,
    EVENT_NEUTRAL: 0.0,
}

# === 特质证据映射（事件 → {维度tid: 方向}） ===
# 方向 +1 = 证据支持该维度值上升（向 high 标签），-1 = 支持下降（向 low 标签）。
# 每条证据 = 角色经历了一件塑造其性格的事。

EVENT_TRAIT_EVIDENCE: dict[str, dict[str, int]] = {
    EVENT_TASK_REQUEST: {"A2": 1, "H1": 1},
    EVENT_PROBLEM_SOLVING: {"C3": 1, "A2": 1},
    EVENT_THANKS: {"D4": 1, "B4": 1},
    EVENT_PRAISE: {"F4": 1},
    EVENT_PERSONAL_SHARING: {"G1": 1, "B4": 1},
    EVENT_VENTING: {"B4": 1, "A5": 1},
    EVENT_COMPLAINT: {"A4": -1, "A5": 1},
    EVENT_CONFLICT: {"A4": -1, "A5": 1, "G1": -1},
    EVENT_BOUNDARY_VIOLATION: {"G1": -1, "D4": -1, "A5": 1},
    EVENT_SILENCE: {"B3": 1, "E1": -1},
    EVENT_HUMOR: {"E3": 1, "D7": 1},
    EVENT_DEEP_TOPIC: {"C4": 1, "C6": 1},
    EVENT_EMOTIONAL_SUPPORT: {"G3": 1, "B4": 1},
    EVENT_FAREWELL: {"G5": 1},
    EVENT_NEUTRAL: {},
}


@dataclass
class PerceptionRecord:
    """语义事件的载体 —— LLM / 启发式分类器输出，不含任何数值。"""

    event_type: str = EVENT_NEUTRAL
    intensity: str = INTENSITY_MEDIUM
    valence: str = "neutral"
    attribution: str = ""
    analysis: str = ""

    def __post_init__(self):
        if self.event_type not in VALID_EVENT_TYPES:
            self.event_type = EVENT_NEUTRAL
        if self.intensity not in VALID_INTENSITIES:
            self.intensity = INTENSITY_MEDIUM
        if self.valence not in VALID_VALENCES:
            self.valence = "neutral"

    # --- 确定性数值派生（LLM 永远不直接产生这些） ---

    @property
    def intensity_factor(self) -> float:
        return INTENSITY_FACTORS.get(self.intensity, 1.0)

    def mood_impulse(self) -> dict[str, float]:
        base = EVENT_MOOD_IMPULSES.get(self.event_type, EVENT_MOOD_IMPULSES[EVENT_NEUTRAL])
        f = self.intensity_factor
        return {k: round(v * f, 4) for k, v in base.items()}

    def affinity_weight(self) -> float:
        base = EVENT_AFFINITY_WEIGHTS.get(self.event_type, 0.0)
        return round(base * self.intensity_factor, 4)

    def trait_evidence(self) -> dict[str, int]:
        return dict(EVENT_TRAIT_EVIDENCE.get(self.event_type, {}))

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type,
            "intensity": self.intensity,
            "valence": self.valence,
            "attribution": self.attribution,
            "analysis": self.analysis,
        }


# === 亲密度等级系统（集中定义，供动力学引擎/生成器/状态查询复用） ===

AFFINITY_THRESHOLDS = [0, 10, 30, 60, 100, 150, 210, 280, 360, 450, 550, 660, 780, 910, 1050]
AFFINITY_LABELS = {
    1: "初识", 2: "关注", 3: "留意", 4: "在意", 5: "记住",
    6: "习惯", 7: "默契", 8: "依存", 9: "共感", 10: "灵魂链接",
    11: "命定", 12: "共生", 13: "绝对信赖", 14: "不可替代", 15: "永恒契约",
}


def affinity_level(value: float) -> dict:
    """游戏式等级: 等级越高, 升级所需亲密度越多。上不封顶。"""
    thresholds = AFFINITY_THRESHOLDS
    for lv in reversed(range(len(thresholds))):
        if value >= thresholds[lv]:
            actual_lv = lv + 1
            next_thresh = thresholds[lv + 1] if lv + 1 < len(thresholds) else thresholds[-1] + 100
            progress = min(1.0, (value - thresholds[lv]) / max(next_thresh - thresholds[lv], 1))
            label = AFFINITY_LABELS.get(actual_lv, f"Lv.{actual_lv}")
            return {"level": actual_lv, "label": label, "progress": progress}
    return {"level": 1, "label": "初识", "progress": 0.0}


def affinity_stage_cap(value: float) -> float:
    """当前关系阶段的亲密度上限（下一级门槛），用于饱和曲线。"""
    thresholds = AFFINITY_THRESHOLDS
    level = affinity_level(value)["level"]
    if level < len(thresholds):
        return thresholds[level]
    return thresholds[-1] + 100
