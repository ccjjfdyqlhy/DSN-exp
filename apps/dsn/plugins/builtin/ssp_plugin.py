# plugins/builtin/ssp_plugin.py
# SelfSustainingPipeline (SSP) — 自维持管线，AI 无干预连续调用工具
# 用于"全面了解协议"：扫描用户电脑 UGC，归纳用户印象

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from harness.pipeline import Plugin, HookPoint, Context as PluginContext

logger = logging.getLogger("SSPPlugin")

SSP_DEFAULT_MAX_STEPS = 50

SENSE_SYSTEM_PROMPT = """## 自维持管线模式 (SSP)

你现在进入了"全面了解"自维持管线模式。你的目标是主动探索用户的环境，收集信息，总结对用户的了解。

你可以使用的工具：
- `<tool>` 标签调用 skills (read_file, list_dir, web_search)
- ````action` 代码块 + `<task>` 标签执行 shell/python 命令

行为指南：
1. 每轮执行 1-3 个操作，获取信息后思考下一轮做什么
2. 发现有用信息后，用以下格式写入印象：
   - 格式：`IMPRESSION:[类别]:[内容]:[置信度0-100]`
   - 类别可选：兴趣、工作、技能、习惯、偏好、项目、设备、社交、其他
   - 示例：`IMPRESSION:兴趣:用户喜欢玩原神:80`
3. 每 5 轮总结一次阶段性发现
4. 当认为已经收集足够信息（至少 10 条印象），或遍历完主要目录后，发送 SSP_DONE 信号
5. 探索策略：
   - 先 list_dir "~" 看顶层目录
   - 然后进入 Documents、Desktop、Projects 等 UGC 密集目录
   - 读取 README、配置文件、代码文件、文档等获取用户画像
   - 不要读 .env、credentials、密钥文件等敏感内容
"""


class SSPPlugin(Plugin):
    """
    自维持管线 (Self-Sustaining Pipeline) 插件。

    在 POST_PROCESS 阶段检测 SSP 启动信号，
    进入高迭代上限的自主探索循环，
    收集信息 → 写入印象 → 总结报告。
    """

    name = "ssp"
    description = "自维持管线 — 无干预连续工具调用，用于全面了解用户"
    hooks = [HookPoint.POST_PROCESS]
    priority = 50

    def __init__(self, db=None, impression_manager=None,
                 models_plugin=None, skill_registry=None,
                 max_steps: int = SSP_DEFAULT_MAX_STEPS):
        self._db = db
        self._impression = impression_manager
        self._models = models_plugin
        self._skill_registry = skill_registry
        self._max_steps = max_steps

    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        if hook != HookPoint.POST_PROCESS:
            return ctx
        if not self._should_activate(ctx):
            return ctx
        return self._run_ssp(ctx)

    def _should_activate(self, ctx: PluginContext) -> bool:
        if ctx.extra.get("ssp_active"):
            return False
        if ctx.extra.get("ssp_stopped"):
            ctx.extra["ssp_active"] = False
            ctx.extra.pop("ssp_stopped", None)
            return False
        if ctx.extra.get("ssp_requested"):
            if self._models is None:
                logger.warning("SSP 收到信号但 models_plugin 未注入，跳过")
                ctx.extra.pop("ssp_requested", None)
                return False
            ctx.extra.pop("ssp_requested", None)
            return True
        reply = ctx.original_reply or ctx.reply or ""
        if re.search(r"<ssp>", reply, re.IGNORECASE):
            return True
        return False

    def _run_ssp(self, ctx: PluginContext) -> PluginContext:
        logger.info("SSP 启动: uid=%d max_steps=%d", ctx.user_id, self._max_steps)
        ctx.extra["ssp_active"] = True

        ssp_context = [{"role": "system", "content": SENSE_SYSTEM_PROMPT}]
        ssp_context.append({
            "role": "user",
            "content": "开始全面了解协议。请探索我的电脑，收集关于我的信息，构建用户画像。"
        })

        accumulated_impressions = []
        ssp_reply = ""

        for step in range(self._max_steps):
            try:
                ssp_reply = self._models.send_message(ssp_context)
            except Exception as e:
                logger.error("SSP step %d 模型调用失败: %s", step + 1, e)
                break

            action_results = self._execute_actions(ssp_reply, ctx)
            tool_results = self._execute_tools(ssp_reply)

            new_impressions = self._extract_impressions(ssp_reply)
            if new_impressions:
                for imp in new_impressions:
                    self._impression.add(
                        ctx.user_id, imp["category"], imp["content"],
                        imp["confidence"], "protocol",
                    )
                accumulated_impressions.extend(new_impressions)
                logger.info("SSP step %d: 提取 %d 条印象 (累计 %d)",
                             step + 1, len(new_impressions), len(accumulated_impressions))

            if action_results or tool_results:
                feedback = "\n".join(filter(None, [action_results, tool_results]))
                ssp_context.append({"role": "assistant", "content": ssp_reply})
                ssp_context.append({"role": "system", "content": f"[系统] 操作结果:\n{feedback}"})
            else:
                ssp_context.append({"role": "assistant", "content": ssp_reply})

            if re.search(r"SSP_DONE|SSP_COMPLETE", ssp_reply, re.IGNORECASE):
                logger.info("SSP 主动终止: step %d", step + 1)
                break

            if len(accumulated_impressions) >= 20:
                logger.info("SSP 印象充足 (%d 条), 终止管线", len(accumulated_impressions))
                break

        self._finalize(ctx, accumulated_impressions)
        return ctx

    def _execute_actions(self, text: str, ctx: PluginContext) -> str:
        results = []
        action_pat = re.compile(r"```action\s*\n(.*?)```", re.DOTALL)
        task_pat = re.compile(r"<task>(.*?)</task>", re.DOTALL)

        action_matches = list(action_pat.finditer(text))
        task_matches = list(task_pat.finditer(text))

        for am in action_matches:
            content = am.group(1).strip()
            for tm in task_matches:
                try:
                    td = json.loads(tm.group(1).strip())
                    if td.get("type") != "action":
                        continue
                    params = td.get("params", {})
                    params.setdefault("content", content)
                    params.setdefault("action_type", "shell")
                    # Execute via task system
                    import subprocess, locale
                    _enc = locale.getpreferredencoding(False)
                    proc = subprocess.run(
                        params.get("content", content),
                        shell=True, capture_output=True,
                        encoding=_enc, errors='replace',
                        timeout=60,
                    )
                    results.append(f"[{params.get('action_type', 'shell')}]\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
                except Exception as e:
                    results.append(f"[action 失败] {e}")
        return "\n\n".join(results) if results else ""

    def _execute_tools(self, text: str) -> str:
        if not self._skill_registry:
            return ""
        results = []
        tool_pat = re.compile(r"<tool>\s*(.*?)\s*</tool>", re.DOTALL)
        for m in tool_pat.finditer(text):
            try:
                d = json.loads(m.group(1).strip())
                r = self._skill_registry.call_tool(
                    d.get("skill", ""), d.get("tool", ""), d.get("params", {}),
                )
                results.append(json.dumps(r, ensure_ascii=False, indent=2))
            except Exception as e:
                results.append(f"[tool 失败] {e}")
        return "\n".join(results) if results else ""

    def _extract_impressions(self, text: str) -> list[dict]:
        impressions = []
        pat = re.compile(
            r"IMPRESSION\s*:\s*(.+?)\s*:\s*(.+?)\s*:\s*(\d+)",
            re.IGNORECASE,
        )
        for match in pat.finditer(text):
            category = match.group(1).strip()
            content = match.group(2).strip()
            confidence = int(match.group(3)) / 100.0
            if not content or len(content) < 2:
                continue
            impressions.append({
                "category": category,
                "content": content,
                "confidence": min(1.0, max(0.1, confidence)),
            })
        return impressions

    def _finalize(self, ctx: PluginContext, impressions: list[dict]) -> None:
        if not impressions:
            ctx.reply = (ctx.reply or "") + "\n\n[SSP] 管线完成，未收集到有效印象。"
            return
        summary = f"\n\n[SSP] 全面了解协议完成。共收集 {len(impressions)} 条印象。\n"
        cats: dict[str, list[str]] = {}
        for imp in impressions:
            cats.setdefault(imp["category"], []).append(imp["content"])
        for cat, items in cats.items():
            summary += f"\n  [{cat}]\n"
            for item in items[:8]:
                summary += f"    - {item}\n"
        ctx.reply = (ctx.reply or "") + summary
        logger.info("SSP 完成: uid=%d 印象=%d", ctx.user_id, len(impressions))
