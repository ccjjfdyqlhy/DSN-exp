# harness/models/router.py
# ModelRouter — 多档模型路由（flash/pro/local/自定义）+ 高峰时段感知。
#
# 让应用按任务类型/高峰自动选择模型档位，配合 ModelProviderRegistry 使用：
#     client = provider.get_chat_client(router.select("search"))

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


DEFAULT_PEAK_RANGES = ((9, 12), (14, 18))


def in_peak_hours(ranges: tuple = DEFAULT_PEAK_RANGES) -> bool:
    h = datetime.now().hour
    return any(start <= h < end for start, end in ranges)


@dataclass
class TierConfig:
    """每档模型的接入配置。"""
    model: str = ""
    api_key: str = ""
    base_url: str = ""


@dataclass
class ModelRouter:
    tiers: dict[str, TierConfig] = field(default_factory=dict)
    current_tier: str = "flash"
    manual_override: Optional[str] = None
    peak_ranges: tuple = DEFAULT_PEAK_RANGES
    auto_downgrade_on_peak: bool = True
    cheap_task_types: set[str] = field(default_factory=lambda: {
        "search", "summary", "simple_edit", "list", "glob", "grep", "read",
    })

    def register_tier(self, name: str, model: str, api_key: str = "",
                      base_url: str = "") -> "ModelRouter":
        self.tiers[name] = TierConfig(model=model, api_key=api_key, base_url=base_url)
        return self

    def select(self, task_type: str = "") -> str:
        """按任务类型 + 高峰选择档位。"""
        if self.manual_override:
            return self.manual_override
        if task_type in self.cheap_task_types:
            return self.current_tier if self.current_tier != "pro" else "flash"
        if self.auto_downgrade_on_peak and in_peak_hours(self.peak_ranges):
            return "flash"
        return self.current_tier

    def switch(self, tier: str) -> str:
        """切换模型档位；传入非档位名视为自定义模型 id（手动锁定）。"""
        if tier in self.tiers:
            self.manual_override = None
            self.current_tier = tier
        else:
            self.manual_override = tier
            self.current_tier = tier
        return self.current_tier

    def reset_auto(self) -> str:
        self.manual_override = None
        return self.current_tier

    def tier_config(self, tier: Optional[str] = None) -> Optional[TierConfig]:
        return self.tiers.get(tier or self.current_tier)
