# harness/kernel/capability.py
# 能力协商 —— 「模型到底支持什么」。
#
# 问题（策划案 §4.1.4）：不同模型能力差异极大（是否支持 tool call、并行
# tool call、reasoning、图像、缓存命中）。硬编码假设是当前最容易出错的地方：
# 给一个不支持并行工具的模型发并行工具请求，provider 直接 400；
# 给不支持视觉的模型塞图片，模型静默忽略或者胡编。
#
# 协商的语义是**收敛**：请求的能力 ∩ 模型真实的能力。
# 关键原则：模型**明确声明不支持**的能力要关掉；模型**没声明**的保持原样 ——
# 因为绝大多数 OpenAI 兼容端点都支持标准 tool-calling 形状，
# 把「没说」当成「不支持」会让整个框架在真实模型上不可用。
#
# 代价要说清楚：这里依赖模型**如实声明**能力。声明缺失时我们选择乐观，
# 换来的是 provider 侧的错误而不是框架侧的静默降级 —— 错误是可见的，
# 静默降级不是。

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


@dataclass(frozen=True)
class CapabilitySet:
    """一组模型能力。

    tool_calls           是否支持 function calling
    parallel_tool_calls  是否支持一轮多个工具调用
    reasoning            是否支持推理内容
    vision               是否支持图像输入
    prefix_cache         是否支持前缀缓存
    max_output_tokens    单次输出上限
    context_window       上下文窗口大小
    """

    tool_calls: bool = True
    parallel_tool_calls: bool = False
    reasoning: bool = False
    vision: bool = False
    prefix_cache: bool = False
    max_output_tokens: int = 4096
    context_window: int = 128_000

    @classmethod
    def negotiate(cls, model: Any, requested: "CapabilitySet | None" = None
                 ) -> "CapabilitySet":
        """按模型的真实能力收敛请求。

        model 可以是：
        - CapabilitySet          → 直接用它
        - 有 .capabilities 属性的对象（dict 或 CapabilitySet）
        - 有 .model_capabilities 属性的对象
        - 直接暴露 vision / supports_tool_calls 等属性的对象
        """
        want = requested or cls()
        declared = _declared(model)
        if declared is None:
            return want
        return want.intersect(declared)

    def intersect(self, other: "CapabilitySet") -> "CapabilitySet":
        """取两份能力的交集（更保守的那一份）。"""
        return CapabilitySet(
            tool_calls=self.tool_calls and other.tool_calls,
            parallel_tool_calls=(self.parallel_tool_calls
                                 and other.parallel_tool_calls),
            reasoning=self.reasoning and other.reasoning,
            vision=self.vision and other.vision,
            prefix_cache=self.prefix_cache and other.prefix_cache,
            max_output_tokens=min(self.max_output_tokens,
                                  other.max_output_tokens),
            context_window=min(self.context_window, other.context_window),
        )

    def with_tool_calls(self, enabled: bool) -> "CapabilitySet":
        return replace(self, tool_calls=enabled)

    def to_dict(self) -> dict:
        return {
            'tool_calls': self.tool_calls,
            'parallel_tool_calls': self.parallel_tool_calls,
            'reasoning': self.reasoning,
            'vision': self.vision,
            'prefix_cache': self.prefix_cache,
            'max_output_tokens': self.max_output_tokens,
            'context_window': self.context_window,
        }


#: 模型上可能出现的属性名 → CapabilitySet 字段名
_ATTR_MAP = {
    'vision': 'vision',
    'supports_vision': 'vision',
    'supports_tool_calls': 'tool_calls',
    'tool_calls': 'tool_calls',
    'supports_parallel_tool_calls': 'parallel_tool_calls',
    'parallel_tool_calls': 'parallel_tool_calls',
    'supports_reasoning': 'reasoning',
    'reasoning': 'reasoning',
    'supports_prefix_cache': 'prefix_cache',
    'prefix_cache': 'prefix_cache',
    'max_output_tokens': 'max_output_tokens',
    'context_window': 'context_window',
    'max_context_tokens': 'context_window',
}


def _declared(model: Any) -> CapabilitySet | None:
    """从模型对象上抽取它**明确声明**的能力。

    返回 None 表示「模型没有声明任何能力」—— 此时不收敛（保持请求原样）。
    """
    if model is None:
        return None
    if isinstance(model, CapabilitySet):
        return model

    for attr in ('capabilities', 'model_capabilities'):
        holder = getattr(model, attr, None)
        if holder is None:
            continue
        if isinstance(holder, CapabilitySet):
            return holder
        if isinstance(holder, dict):
            return _from_mapping(holder)

    values: dict[str, Any] = {}
    for attr, field in _ATTR_MAP.items():
        if hasattr(model, attr):
            value = getattr(model, attr)
            if isinstance(value, bool) or isinstance(value, int):
                values[field] = value
    if not values:
        return None
    return _from_mapping(values)


def _from_mapping(mapping: dict) -> CapabilitySet:
    """从 dict 构造 CapabilitySet，忽略无法识别的键。"""
    base = CapabilitySet()
    kwargs: dict[str, Any] = {}
    for key, value in mapping.items():
        field = _ATTR_MAP.get(key)
        if field is None:
            continue
        current = getattr(base, field)
        if isinstance(current, bool):
            kwargs[field] = bool(value)
        elif isinstance(current, int) and isinstance(value, int):
            kwargs[field] = value
    return replace(base, **kwargs)


__all__ = ['CapabilitySet']
