# harness/policy — 策略层：可插拔的 Agent 行为策略（场景无关）。
#
# 架构创新：把"行为策略"从应用层下沉为引擎一级公民。
# 与 DSH 的差异：DSH 以插件/事件为组织单元，harness 以"策略对象"为组织单元——
# 每个策略是可独立测试、可组合、可序列化的决策对象：
#
#   ModelRouter        模型路由（任务分级 + 高峰降级 + 手动覆盖）
#   TokenMeter         成本核算（缓存命中/未命中分账）
#   TokenBudget        会话预算（token/费用双上限，超限自动降级或截断）
#   DurationPredictor  请求耗时预测（自适应线性模型，死区学习）
#   CacheWarmer        前缀缓存保活（空闲 keepalive）
#
# 用法:
#     router = ModelRouter(...)
#     meter = TokenMeter(pricing)
#     budget = TokenBudget(cap_cost=0.5)
#     predictor = DurationPredictor()
#     # 组装成 PolicySet 注入 AgentLoop / Pipeline

from .router import ModelRouter, ModelConfig
from .token_meter import TokenMeter, UsageRecord, pricing
from .budget import TokenBudget
from .predictor import DurationPredictor
from .warmer import CacheWarmer
from .retry import RetryPolicy, RetryStats

__all__ = [
    "ModelRouter", "ModelConfig",
    "TokenMeter", "UsageRecord", "pricing",
    "TokenBudget", "DurationPredictor", "CacheWarmer",
    "RetryPolicy", "RetryStats",
]
