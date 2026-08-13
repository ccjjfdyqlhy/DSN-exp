# harness/pipeline/base.py
# 通用插件基类 + 钩子点 + 管线上下文。
#
# 关键设计：Context 只包含"消息进、输出出"的通用字段，
# 不含语音/人格/提醒等应用语义 —— 应用特定数据走 extra / outputs / events。

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class HookPoint(Enum):
    """通用管线钩子点，按执行顺序排列。"""
    INBOUND = "inbound"              # 入站处理 / 过滤（可短路）
    PREPARE = "prepare"              # 上下文组装 / system prompt / 记忆注入
    MODEL_INVOKE = "model_invoke"    # 模型调用
    POST_PROCESS = "post_process"    # 后处理 / 工具执行 / 记忆更新
    OUTPUT = "output"                # 输出渲染 / 投递


@dataclass
class Attachment:
    """多模态附件（图片/文件/音频等）。data 为原始字节或文本描述。"""
    kind: str                        # "image" | "file" | "audio" | "text" ...
    data: Any = None
    mime: Optional[str] = None
    name: Optional[str] = None


@dataclass
class Context:
    """贯穿管线的上下文。插件间通过它传递数据。"""

    # ── 输入 ──
    session_id: str = ""
    user_id: str = ""
    message: str = ""
    attachments: list[Attachment] = field(default_factory=list)

    # ── 中间态 ──
    system_prompt: str = ""
    history: list = field(default_factory=list)      # 对话历史（通用消息）
    reply: str = ""                                   # 最终文本回复
    filtered: bool = False                            # 短路标记
    tool_calls: list = field(default_factory=list)    # 待执行工具调用
    usage: Optional[dict] = None
    model_name: Optional[str] = None

    # ── 输出产物（渲染器填充，如 text/audio/image） ──
    outputs: dict = field(default_factory=dict)

    # ── 扩展（应用特定数据放这里） ──
    extra: dict = field(default_factory=dict)

    # ── 便捷方法 ──

    def emit(self, event: str, payload: Any = None) -> "Context":
        """记录一个待广播事件（由管线在阶段结束后交给 EventBus）。"""
        self.extra.setdefault("_events", []).append((event, payload))
        return self

    def set_output(self, kind: str, value: Any) -> "Context":
        self.outputs[kind] = value
        return self

    def short_circuit(self, reason: str = "") -> "Context":
        self.filtered = True
        if reason:
            self.extra["_filter_reason"] = reason
        return self


class Plugin(ABC):
    """同步插件基类。on_hook 是同步方法。"""

    name: str = ""
    description: str = ""
    version: str = "1.0"
    hooks: list[HookPoint] = []
    priority: int = 50

    def on_load(self) -> None:
        """插件加载时调用。"""

    def on_unload(self) -> None:
        """插件卸载时调用。"""

    @abstractmethod
    def on_hook(self, hook: HookPoint, ctx: Context) -> Context:
        """钩子回调。设置 ctx.filtered=True 会短路终止管线。"""

    def __repr__(self) -> str:
        enabled = ",".join(h.value for h in self.hooks)
        return f"<{self.__class__.__name__} name={self.name} hooks=[{enabled}] pri={self.priority}>"


class AsyncPlugin(ABC):
    """异步插件基类。on_hook 是 async 方法。"""

    name: str = ""
    description: str = ""
    version: str = "1.0"
    hooks: list[HookPoint] = []
    priority: int = 50

    async def on_load(self) -> None:
        """插件加载时调用。"""

    async def on_unload(self) -> None:
        """插件卸载时调用。"""

    @abstractmethod
    async def on_hook(self, hook: HookPoint, ctx: Context) -> Context:
        """钩子回调。设置 ctx.filtered=True 会短路终止管线。"""

    def __repr__(self) -> str:
        enabled = ",".join(h.value for h in self.hooks)
        return f"<{self.__class__.__name__} name={self.name} hooks=[{enabled}] pri={self.priority}>"
