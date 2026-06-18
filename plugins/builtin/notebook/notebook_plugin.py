# plugins/builtin/notebook/notebook_plugin.py
# 用户观察日记插件 — POST_PROCESS 钩子
# 按可配置频率触发 AI 写笔记, 提取 <notebook> 标签保存

from __future__ import annotations

import logging
import re
import threading

from plugins.base import Plugin, HookPoint, PluginContext
from config import Config

logger = logging.getLogger("NotebookPlugin")

_NOTEBOOK_RE = re.compile(r"<notebook>\s*(.*?)\s*</notebook>", re.DOTALL | re.IGNORECASE)


class NotebookPlugin(Plugin):
    """
    用户观察日记插件。

    行为:
      - 跟踪每个用户的累计互动次数
      - 当次数达到 NOTEBOOK_FREQUENCY 的倍数时, 在 PRE_PROCESS
        阶段向系统提示词注入一节"请写一篇用户观察笔记"的指令
      - 在 POST_PROCESS 阶段从 AI 回复中提取 <notebook> 标签
      - 将笔记保存到 NotebookStore
      - 同时从 ctx.reply 中移除 <notebook> 标签 (不展示给用户)

    配置:
      NOTEBOOK_FREQUENCY (默认 10): 每 N 次对话触发一次笔记
    """

    name = "notebook"
    description = "用户观察日记 — AI 定期记录对用户的观察"
    hooks = [HookPoint.PRE_PROCESS, HookPoint.POST_PROCESS]
    priority = 39  # 在 memory(30) 之后, task(40) 之前

    def __init__(self, notebook_store=None):
        from .notebook_store import NotebookStore
        self._store = notebook_store or NotebookStore()
        self._user_interactions: dict[int, int] = {}
        self._lock = threading.Lock()
        self._frequency = getattr(Config, "NOTEBOOK_FREQUENCY", 10)

    def on_load(self) -> None:
        logger.info("NotebookPlugin 已加载, frequency=%d", self._frequency)

    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        if hook == HookPoint.PRE_PROCESS:
            return self._on_pre_process(ctx)
        if hook == HookPoint.POST_PROCESS:
            return self._on_post_process(ctx)
        return ctx

    def _on_pre_process(self, ctx: PluginContext) -> PluginContext:
        uid = ctx.user_id
        with self._lock:
            count = self._user_interactions.get(uid, 0) + 1
            self._user_interactions[uid] = count

        if count % self._frequency == 0:
            notes_count = self._store.note_count(uid)
            inject = _build_notebook_prompt(notes_count)
            ctx.system_prompt += inject
            logger.info("Notebook: uid=%d 第 %d 轮, 注入笔记提示 (%d 条已有笔记)",
                        uid, count, notes_count)

        return ctx

    def _on_post_process(self, ctx: PluginContext) -> PluginContext:
        uid = ctx.user_id
        reply = ctx.original_reply or ctx.reply or ""

        for match in _NOTEBOOK_RE.finditer(reply):
            content = match.group(1).strip()
            if content:
                self._store.add_note(uid, content, ctx.chat_id or 0)
                logger.info("Notebook: uid=%d 保存笔记 (%d chars)", uid, len(content))

        ctx.reply = _NOTEBOOK_RE.sub("", ctx.reply).strip()
        if not ctx.reply:
            ctx.reply = "..."

        return ctx


def _build_notebook_prompt(existing_count: int) -> str:
    return f"""

## 用户观察笔记

你现在有机会记录一条"用户观察日记"。
请在你回复的最后用 <notebook> 标签写一段笔记, 观察并记录关于当前用户的任何值得记住的事情。

笔记内容可以包括但不限于:
- 用户的技术水平和编程习惯
- 用户的偏好 (命名风格、工具选择、工作流程)
- 用户当前在做什么项目、遇到了什么问题
- 用户表达出的情绪、态度、兴趣变化
- 用户提到的个人背景或生活细节

要求:
1. 用中文, 1~3 句话, 不超过 100 字
2. 像私人日记, 用第一人称: "我发现用户..."
3. 只记录有价值的信息, 不要写无关紧要的流水账
4. 格式: <notebook>你的观察笔记</notebook>
5. 写在所有其他内容之后 (对话回复已经完成, 最后加笔记)

(当前已有 {existing_count} 条历史笔记)
"""
