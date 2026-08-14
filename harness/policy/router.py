# harness/policy/router.py
# ModelRouter — 模型路由策略（场景无关）。
#
# 从 dekacode router.py 提炼并引擎化，创新扩展：
#   - 路由依据可扩展：任务类型 / 高峰时段 / 手动覆盖 / 预算告警（budget pressure）
#   - 多档位模型（tier）：flash/pro/自定义档，register_tier 声明即用
#   - 路由决策可记录（decision log），供可观测性消费
#   - 与 TokenBudget 联动：预算压力高时自动降级到廉价模型
#
# 本模块同时是 harness.models.router 的唯一实现（旧 models/router.py 已合并删除）。

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# 默认高峰时段（可配置）
DEFAULT_PEAK_RANGES = ((9, 12), (14, 18))

# 廉价任务类型：默认路由到 flash
CHEAP_TASKS = ("search", "summary", "simple_edit", "list", "glob", "grep",
               "recall", "classify", "extract")


def in_peak_hours(now: Optional[datetime] = None,
                  ranges=DEFAULT_PEAK_RANGES) -> bool:
    h = (now or datetime.now()).hour
    return any(start <= h < end for start, end in ranges)


@dataclass
class TierConfig:
    """每档模型的接入配置（多档位扩展）。"""

    model: str = ""
    api_key: str = ""
    base_url: str = ""


@dataclass
class ModelConfig:
    """模型配置：内置 flash/pro 双档 + 任意注册档位（tiers）。"""

    flash_model: str = "deepseek-v4-flash"
    pro_model: str = "deepseek-v4-pro"
    flash_api_key: str = ""
    flash_base_url: str = ""
    pro_api_key: str = ""
    pro_base_url: str = ""
    auto_downgrade_on_peak: bool = True
    cheap_tasks: tuple = CHEAP_TASKS
    peak_ranges: tuple = DEFAULT_PEAK_RANGES
    tiers: dict[str, TierConfig] = field(default_factory=dict)


@dataclass
class RouterDecision:
    """一次路由决策的记录（供可观测性/调试）。"""

    mode: str = ""
    model_name: str = ""
    reason: str = ""
    ts: float = field(default_factory=lambda: datetime.now().timestamp())


class ModelRouter:
    """模型路由策略。

    select(task_type, budget_pressure) → mode（"flash" | "pro" | 注册档位 | 自定义覆盖）
    决策优先级：手动覆盖 > 预算压力降级 > 任务类型 > 高峰降级 > 默认。
    """

    def __init__(self, config: Optional[ModelConfig] = None):
        self.config = config or ModelConfig()
        self.current_model: str = "flash"
        self.manual_override: Optional[str] = None
        self.decisions: list[RouterDecision] = []

    # ── 档位管理 ──

    def register_tier(self, name: str, model: str, api_key: str = "",
                      base_url: str = "") -> "ModelRouter":
        """注册一个模型档位（如 local/embedding），之后可 switch/select。"""
        self.config.tiers[name] = TierConfig(model=model, api_key=api_key,
                                             base_url=base_url)
        return self

    def tier_config(self, tier: Optional[str] = None) -> Optional[TierConfig]:
        """查询档位接入配置；tier 缺省取当前模式。"""
        return self.config.tiers.get(tier or self.current_model)

    # ── 决策 ──

    def select(self, task_type: str = "", budget_pressure: float = 0.0) -> str:
        if self.manual_override:
            self._log("manual", self.manual_override, f"手动覆盖: {self.manual_override}")
            return self.manual_override

        if budget_pressure >= 0.8 and self.config.flash_model:
            self._log("budget", "flash", f"预算压力 {budget_pressure:.0%}, 降级 flash")
            return "flash"

        if task_type in self.config.cheap_tasks:
            self._log("task", "flash", f"廉价任务类型: {task_type}")
            return "flash"

        if self.config.auto_downgrade_on_peak and in_peak_hours(ranges=self.config.peak_ranges):
            self._log("peak", "flash", "高峰时段自动降级")
            return "flash"

        self._log("default", self.current_model, "默认模型")
        return self.current_model

    # ── 切换 ──

    def switch(self, mode: str) -> str:
        """切换模型模式：注册档位名 / auto / 自定义模型 id（手动锁定）。"""
        if mode == "auto":
            self.manual_override = None
            self.current_model = "flash"
        elif mode in self.config.tiers:
            self.manual_override = None
            self.current_model = mode
        else:
            self.manual_override = mode
            self.current_model = mode
        return self.current_model

    def reset(self) -> None:
        self.manual_override = None
        self.current_model = "flash"

    def reset_auto(self) -> str:
        """别名：清除手动覆盖，恢复自动路由。"""
        self.manual_override = None
        return self.current_model

    # ── 查询 ──

    def get_model_name(self, mode: str) -> str:
        if mode in self.config.tiers:
            return self.config.tiers[mode].model
        if mode == "pro":
            return self.config.pro_model
        return self.config.flash_model

    def get_model_config(self, mode: str) -> dict:
        if mode in self.config.tiers:
            t = self.config.tiers[mode]
            return {"model": t.model, "api_key": t.api_key, "base_url": t.base_url}
        if mode == "pro":
            return {"model": self.config.pro_model,
                    "api_key": self.config.pro_api_key,
                    "base_url": self.config.pro_base_url}
        return {"model": self.config.flash_model,
                "api_key": self.config.flash_api_key,
                "base_url": self.config.flash_base_url}

    def _log(self, reason: str, mode: str, detail: str) -> None:
        self.decisions.append(RouterDecision(
            mode=mode, model_name=self.get_model_name(mode), reason=detail))

    def __repr__(self) -> str:
        return (f"<ModelRouter current={self.current_model} "
                f"override={self.manual_override or 'auto'}>")
