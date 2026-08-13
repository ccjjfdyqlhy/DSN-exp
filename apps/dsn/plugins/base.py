# plugins/base.py
# 插件基类 + 钩子点定义 + 上下文数据类

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class HookPoint(Enum):
    """插件可以挂载的钩子点，按管道执行顺序排列"""
    PRE_FILTER   = "pre_filter"    # ASR 输入过滤，可短路返回
    PRE_PROCESS  = "pre_process"   # 系统提示词构建 + 记忆注入
    MODEL_INVOKE = "model_invoke"  # 模型调用（通常只有一个插件）
    POST_PROCESS = "post_process"  # 任务解析 + 对话保存
    POST_TTS     = "post_tts"      # TTS 语音合成


@dataclass
class PluginContext:
    """贯穿整个管道的上下文，插件间通过它传递数据"""

    # ---- 输入字段 ----
    user_id: int = 0
    message: str = ""
    chat_id: Optional[int] = None
    chat_name: str = "未命名"
    history: list = field(default_factory=list)
    is_asr_input: bool = False
    tts_enabled: bool = True
    model_type: Optional[str] = None
    nickname: str = "用户"
    image_data: Optional[str] = None

    # ---- 中间产物 ----
    system_prompt: str = ""
    full_history: list = field(default_factory=list)
    reply: str = ""              # 清洗后的回复（给前端 / TTS）
    original_reply: str = ""     # 含标签的原始回复
    audio: Optional[bytes] = None
    audio_b64: Optional[str] = None
    filtered: bool = False       # PRE_FILTER 短路标记
    tts_error: Optional[str] = None
    usage: Optional[dict] = None           # API 返回的 usage 字段
    model_name: Optional[str] = None       # 实际调用的模型名

    # ---- Agent 循环状态 (引擎层使用) ----
    agent_active: bool = False            # 是否启用了 agent 循环
    agent_step_count: int = 0             # 当前步数
    agent_max_steps: int = 5             # 最大步数
    agent_token_budget: int = 1000000    # token 预算（按消息字符数简单估算）

    # ---- 剧本系统 ----
    skip_model: bool = False       # 回放命中时跳过 MODEL_INVOKE

    # ---- 扩展 ----
    extra: dict = field(default_factory=dict)
    cross_user_id: Optional[int] = None   # Agent 模式下绑定的用户 uid
    recall_engine: Optional[Any] = None  # MemoryRecallEngine 实例


class Plugin(ABC):
    """
    同步插件基类 — on_hook 是同步方法，适合 CPU 密集或无需 IO 的插件。
    Pipeline 会在 executor 中调度 sync plugin 以避免阻塞事件循环。
    """

    name: str = ""
    description: str = ""
    version: str = "1.0"
    hooks: list[HookPoint] = []
    priority: int = 50

    def on_load(self) -> None:
        """插件加载时调用"""

    def on_unload(self) -> None:
        """插件卸载时调用"""

    @abstractmethod
    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        """
        钩子回调。
        返回 ctx (可原地修改或返回新建)。
        若设置 ctx.filtered = True，Pipeline 将短路终止。
        """
        ...

    def __repr__(self) -> str:
        enabled_hooks = ",".join(h.value for h in self.hooks)
        return f"<{self.__class__.__name__} name={self.name} hooks=[{enabled_hooks}] pri={self.priority}>"


class AsyncPlugin(ABC):
    """
    异步插件基类 — on_hook 是 async 方法，适合 IO 密集插件。
    Pipeline 直接 await，不经过 executor。
    """

    name: str = ""
    description: str = ""
    version: str = "1.0"
    hooks: list[HookPoint] = []
    priority: int = 50

    async def on_load(self) -> None:
        """插件加载时调用"""

    async def on_unload(self) -> None:
        """插件卸载时调用"""

    @abstractmethod
    async def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        """钩子回调。若设置 ctx.filtered = True，Pipeline 将短路终止。"""
        ...

    def __repr__(self) -> str:
        enabled_hooks = ",".join(h.value for h in self.hooks)
        return f"<{self.__class__.__name__} name={self.name} hooks=[{enabled_hooks}] pri={self.priority}>"
