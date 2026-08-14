# harness/pipeline/base.py
# 通用插件基类 + 钩子点 + 管线上下文。
#
# 关键设计：Context 只包含"消息进、输出出"的通用字段，
# 不含语音/人格/提醒等应用语义 —— 应用特定数据走 extra / outputs / events。
#
# DSN 超集：HookPoint 与 Context 已扩展为 dsn 引擎（apps.dsn.plugins）的超集，
# dsn 的 PluginContext / 5 个钩子点直接映射到本模块（apps.dsn.plugins 直接再导出本模块符号）。

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class HookPoint(Enum):
    """通用管线钩子点，按执行顺序排列。

    DSN 兼容说明：
      - PRE_FILTER / PRE_PROCESS / POST_TTS 与 dsn 引擎同名钩子（超集）。
      - PRE_PROCESS 与 PREPARE 语义相近但保留独立成员：dsn 在 PRE_FILTER 之后
        先组装 system prompt 再派发 PRE_PROCESS；harness 的 PREPARE 自行负责
        上下文组装。两套应用各用各的名字，互不串扰。
    """
    INBOUND = "inbound"              # 入站处理 / 过滤（可短路）
    PRE_FILTER = "pre_filter"        # ASR 输入过滤（可短路）— dsn 兼容
    PREPARE = "prepare"              # 上下文组装 / system prompt / 记忆注入
    PRE_PROCESS = "pre_process"      # dsn 兼容名（PRE_FILTER → assemble_prompt → 本阶段）
    MODEL_INVOKE = "model_invoke"    # 模型调用
    POST_PROCESS = "post_process"    # 后处理 / 工具执行 / 记忆更新
    POST_TTS = "post_tts"            # TTS 合成 — dsn 兼容
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
    """贯穿管线的上下文。插件间通过它传递数据。

    除通用字段外，还承载 DSN 引擎兼容字段（chat_id / image_data / agent_* 等，
    全部可选带默认值，通用场景不受影响）。应用特定数据放 extra / outputs / events。
    """

    # ── 输入 ──
    session_id: str = ""
    user_id: str | int = ""          # 通用为 str，DSN 场景为 int（运行时不强制）
    message: str = ""
    attachments: list[Attachment] = field(default_factory=list)

    # ── 输入（DSN 兼容） ──
    chat_id: Optional[int] = None
    chat_name: str = "未命名"
    is_asr_input: bool = False
    tts_enabled: bool = True
    model_type: Optional[str] = None
    nickname: str = "用户"
    image_data: Optional[str] = None

    # ── 中间态 ──
    system_prompt: str = ""
    history: list = field(default_factory=list)      # 对话历史（通用消息）
    reply: str = ""                                   # 最终文本回复
    filtered: bool = False                            # 短路标记
    tool_calls: list = field(default_factory=list)    # 待执行工具调用
    usage: Optional[dict] = None
    model_name: Optional[str] = None

    # ── 中间态（DSN 兼容） ──
    full_history: list = field(default_factory=list)
    original_reply: str = ""                          # 含标签的原始回复
    audio: Optional[bytes] = None
    audio_b64: Optional[str] = None
    tts_error: Optional[str] = None

    # ── Agent 循环状态 ──
    agent_active: bool = False
    agent_step_count: int = 0
    agent_max_steps: int = 5
    agent_token_budget: int = 1000000

    # ── 剧本/回放（DSN 兼容） ──
    skip_model: bool = False                          # 回放命中时跳过 MODEL_INVOKE
    cross_user_id: Optional[int] = None               # Agent 模式下绑定的用户 uid
    recall_engine: Optional[Any] = None               # 记忆召回引擎实例

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
