# harness/pipeline/base.py
# generic plugin base, hook points and pipeline context.
#
# Context carries generic "message in, output out" fields only. voice,
# personality and reminder semantics belong to the application and travel in
# extra / outputs / events.
#
# HookPoint and Context are a superset of the earlier engine: PRE_FILTER,
# PRE_PROCESS and POST_TTS keep their established names, while PREPARE and the
# generic fields serve new code.

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class HookPoint(Enum):
    """Generic pipeline hook points, in execution order.

    PRE_FILTER, PRE_PROCESS and POST_TTS keep their established names.
    PRE_PROCESS and PREPARE look similar but stay separate: the earlier engine
    assembles the system prompt after PRE_FILTER and then dispatches
    PRE_PROCESS, while PREPARE owns context assembly here. Each caller uses its
    own name, so neither path interferes with the other.
    """
    INBOUND = "inbound"              # inbound handling and filtering, may short-circuit
    PRE_FILTER = "pre_filter"        # input filtering, may short-circuit
    PREPARE = "prepare"              # context assembly, system prompt, memory injection
    PRE_PROCESS = "pre_process"      # compatibility stage after prompt assembly
    MODEL_INVOKE = "model_invoke"    # model call
    POST_PROCESS = "post_process"    # post-processing, tools, memory update
    POST_TTS = "post_tts"            # speech synthesis
    OUTPUT = "output"                # render and deliver


@dataclass
class Attachment:
    """多模态附件（图片/文件/音频等）。data 为原始字节或文本描述。"""
    kind: str                        # "image" | "file" | "audio" | "text" ...
    data: Any = None
    mime: Optional[str] = None
    name: Optional[str] = None


@dataclass
class Context:
    """Context that travels through the pipeline.

    It also carries compatibility fields (chat_id, image_data, agent_*) that all
    have defaults. Application-specific data belongs in extra / outputs / events.
    """

    # input
    session_id: str = ""
    user_id: str | int = ""          # str in generic code, int in the legacy engine
    message: str = ""
    attachments: list[Attachment] = field(default_factory=list)

    # input: compatibility fields
    chat_id: Optional[int] = None
    chat_name: str = "未命名"
    is_asr_input: bool = False
    tts_enabled: bool = True
    model_type: Optional[str] = None
    nickname: str = "用户"
    image_data: Optional[str] = None

    # intermediate state
    system_prompt: str = ""
    history: list = field(default_factory=list)      # 对话历史（通用消息）
    reply: str = ""                                   # 最终文本回复
    filtered: bool = False                            # 短路标记
    tool_calls: list = field(default_factory=list)    # 待执行工具调用
    usage: Optional[dict] = None
    model_name: Optional[str] = None

    # intermediate state: compatibility fields
    full_history: list = field(default_factory=list)
    original_reply: str = ""                          # 含标签的原始回复
    audio: Optional[bytes] = None
    audio_b64: Optional[str] = None
    tts_error: Optional[str] = None

    # agent loop state
    agent_active: bool = False
    agent_step_count: int = 0
    agent_max_steps: int = 5
    agent_token_budget: int = 1000000

    # scripted replay: compatibility fields
    skip_model: bool = False                          # 回放命中时跳过 MODEL_INVOKE
    cross_user_id: Optional[int] = None               # Agent 模式下绑定的用户 uid
    recall_engine: Optional[Any] = None               # 记忆召回引擎实例

    # output produced by renderers, such as text, audio or image
    outputs: dict = field(default_factory=dict)

    # extension point for application-specific data
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
