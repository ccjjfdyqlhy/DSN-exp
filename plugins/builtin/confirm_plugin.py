# plugins/builtin/confirm_plugin.py
# ConfirmPlugin — 快速确认协议，AI 用 <confirm> 标签主动发起用户确认请求

from __future__ import annotations

import logging
import re

from plugins.base import Plugin, HookPoint, PluginContext

logger = logging.getLogger("ConfirmPlugin")

CONFIRM_PROMPT_INJECTION = """## 快速确认协议

当你的回答需要用户明确确认后才能继续执行操作时，在回复末尾添加单独的 `<confirm>` 标签。

**典型使用场景：**
- 执行危险操作前（如删除文件、强制推送、修改关键配置）
- 需要用户同意某个方案或建议时
- 涉及外部资源的操作（如创建 PR、发送请求）

**不需要使用的场景：**
- 纯信息性回答
- 闲聊
- 简单的文件读写
- 用户未明确要求执行的操作
- 回答中只提供了建议但未表示要执行

**标签格式：**
只需 `<confirm>` 即可，无需 `</confirm>` 闭合标签。标签应放在回复的最后一行。

**示例：**
```
已分析代码，发现三处可优化的地方：
1. 修复 README 中的拼写错误
2. 移除未使用的导入

建议现在就提交修复并创建 PR，是否继续？
<confirm>
```
"""


class ConfirmPlugin(Plugin):
    """快速确认协议插件。

    PRE_PROCESS: 将确认协议提示词注入 system_prompt，告知 AI 何时使用 <confirm> 标签。
    POST_PROCESS: 检测回复中的 <confirm> 标签，剥离并标记 ctx.extra["confirm_requested"]。
    """

    name = "confirm"
    description = "快速确认协议 — AI 主动发起用户确认请求"
    hooks = [HookPoint.PRE_PROCESS, HookPoint.POST_PROCESS]
    priority = 32

    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        if hook == HookPoint.PRE_PROCESS:
            return self._inject_prompt(ctx)
        elif hook == HookPoint.POST_PROCESS:
            return self._detect_confirm(ctx)
        return ctx

    def _inject_prompt(self, ctx: PluginContext) -> PluginContext:
        if CONFIRM_PROMPT_INJECTION not in ctx.system_prompt:
            ctx.system_prompt += "\n\n" + CONFIRM_PROMPT_INJECTION
        return ctx

    def _detect_confirm(self, ctx: PluginContext) -> PluginContext:
        original = ctx.original_reply or ""
        if not re.search(r"<confirm>", original, re.IGNORECASE):
            return ctx

        ctx.extra["confirm_requested"] = True
        logger.info("检测到 <confirm> 标签，已设置 confirm_requested")

        ctx.original_reply = re.sub(r"<confirm>", "", ctx.original_reply, flags=re.IGNORECASE).strip()
        ctx.reply = re.sub(r"<confirm>", "", ctx.reply or "", flags=re.IGNORECASE).strip()

        return ctx
