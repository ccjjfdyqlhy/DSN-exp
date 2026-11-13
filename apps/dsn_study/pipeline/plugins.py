# apps/dsn_study/pipeline/plugins.py
# dsn_study 的对话期插件（阶段 3）—— 迁移到 harness/pipeline。
#
# 迁移前：这些逻辑内联在 `chat_hooks.py`（pre_process/post_process 两个大方法）
#         + `boot.py` 的 StudyEngine.chat 里，靠 if/else 串起来。
# 迁移后：每个能力一个 Plugin，挂在 harness/pipeline 的钩子上，
#         调度、优先级、短路、异常隔离全部交给基座。
#
# 钩子分配（harness/pipeline/base.py 的 HookPoint）：
#   PREPARE      —— 上下文组装 / system prompt / 记忆注入
#   PRE_PROCESS  —— 与「当前这条消息」强相关的处理（视觉 / 考试 / 日终报告）
#   MODEL_INVOKE —— 真正调模型
#   POST_PROCESS —— 回复后处理（<plan_check> 回写 / 记忆落库 / 人格回写）
#   POST_TTS     —— 语音合成
#
# ⚠️ 两条纪律：
#   1. **插件初始化一律放 __init__** —— `on_load`/`on_unload` 全仓零调用，
#      harness 的 PluginManager 不会调它们。
#   2. **priority 是升序**（值小者先执行），与技能提示词的 prompt_priority
#      （降序）相反，别搞混。

from __future__ import annotations

import json
import logging
import re
import threading
from datetime import date, datetime
from typing import Optional

from harness.pipeline.base import Context, HookPoint, Plugin

from apps.dsn_study.config import Config

logger = logging.getLogger("StudyPipeline")

#: 消息内嵌图片 data URL
DATA_URL_RE = re.compile(r"data:image/\w+;base64,[A-Za-z0-9+/=]+")

#: <plan_check>{"task_id": "...", "action": "done"|"skip"}</plan_check>
PLAN_CHECK_RE = re.compile(
    r"<plan_check>\s*(.*?)\s*</plan_check>", re.DOTALL | re.IGNORECASE)

#: 明确的交卷语义（不收窄会误伤"提交作业"等普通表达）
SUBMIT_KEYWORDS = (
    "交卷", "提交试卷", "交卷吧", "交卷了", "我交卷", "答完了", "做完交卷",
    "submit exam", "submit the exam", "finish exam", "hand in",
)

#: 日终报告触发时间（参考实现用 22 点）
DAILY_REPORT_HOUR = 22

#: 注入到上下文里的块的统一前缀（提示模型这是系统信息，不要复述）
CTX_PREFIX = "(系统上下文·仅供你参考，不要复述) "


def _prepend(message: str, block: str) -> str:
    """把上下文块插到用户消息前面。"""
    if not block:
        return message
    return f"{CTX_PREFIX}{block}\n\n{message}" if message else f"{CTX_PREFIX}{block}"


class _BaseStudyPlugin(Plugin):
    """插件基类：统一异常隔离与上下文追加方式。"""

    version = "1.0"

    def _append_context(self, ctx: Context, block: str) -> None:
        if block:
            ctx.message = _prepend(ctx.message, block)


# ══════════════════════════════════════════════════════════════
# PRE_FILTER —— ASR 输入过滤（可短路）
# ══════════════════════════════════════════════════════════════

class AsrFilterPlugin(_BaseStudyPlugin):
    """判断这段语音该不该唤醒主模型（FORWARD / HOLD）。

    对齐参考实现 plugins/builtin/asr_filter_plugin.py：
    只作用于 **ASR 来源**的轮次，文本输入一律放行。
    判定 HOLD → `ctx.short_circuit()`，管线就此停下，模型不被调用。
    """

    name = "study_asr_filter"
    description = "ASR 输入过滤（FORWARD/HOLD）"
    hooks = [HookPoint.PRE_FILTER]
    priority = 10

    def __init__(self, filter_model=None):
        self._filter_model = filter_model

    def on_hook(self, hook: HookPoint, ctx: Context) -> Context:
        if self._filter_model is None:
            return ctx
        if not ctx.is_asr_input:
            return ctx          # 文本输入不过滤
        try:
            decision = self._filter_model.filter_input(ctx.message or "")
        except Exception:
            logger.warning("ASR 过滤判定异常（按放行处理）", exc_info=True)
            return ctx
        if decision == "HOLD":
            logger.info("ASR 过滤：HOLD（不转发给主模型）")
            ctx.short_circuit("asr_filter_hold")
            ctx.reply = ""
        else:
            logger.info("ASR 过滤：FORWARD")
        return ctx


# ══════════════════════════════════════════════════════════════
# PREPARE —— 上下文组装
# ══════════════════════════════════════════════════════════════

#: 语音输入（ASR）时追加到 system prompt 的补充指令。
#:
#: 为什么需要它：语音场景的回复会被送进 TTS 合成，实测合成耗时
#: ≈ 1.3s 固定 + 0.045s/字（8 字 1.3s / 24 字 1.7s / 67 字 4.2s）。
#: 也就是说回复写长了，用户要**多等同样长的时间**才听见声音 ——
#: 对讲机场景下这是体感延迟的最大来源。文本对话则相反，长一点没关系。
#: 语音模式保留的提示词片段标签 —— **不含 "skills"**。
#: 实测完整技能说明有 17KB（19KB 的 system prompt 里的大头），而语音场景
#: 多数是闲聊/答疑；模型只需要知道"有哪些能力可用"，不必背说明书。
#: 完整技能说明仍然可以通过紧凑索引里的技能名触发。
VOICE_PROMPT_TAGS = ("core", "personality", "context")

#: 语音轮的「短回复」指令 —— **默认不启用**（Config.VOICE_SHORT_REPLY=false）。
#:
#: 它存在的唯一理由是 TTS 延迟（≈1.3s + 0.045s/字）：回复写 100 字，
#: 用户就要多等 4 秒。但它同时把主AI 钉死在「只回一两句话」——
#: 讲题讲不开、推导被压成一句话，正是「只能短回复」的来源。
#: 所以现在默认关掉，需要「快答」时再用配置打开。
VOICE_MODE_INSTRUCTION = (
    "【语音对话模式 —— 本条覆盖上面「步骤该展开就展开」的通用要求】\n"
    "用户是用**说的**在跟你交流，你的回答会被合成为语音播报给他。\n"
    "语音播报有成本：合成耗时 ≈ 1.3s + 0.045s/字，回复写 100 字用户就要多等 4 秒。\n"
    "因此本次回答：\n"
    "- 只回一到两句话，总共不超过 40 个字；\n"
    "- 不要罗列清单、不要写公式、不要用 markdown 或表情符号；\n"
    "- 不要复述用户刚说的话；\n"
    "- 需要展开讲解时，先用一句话给结论，再问一句「要展开讲吗」，"
    "他同意后你再详细展开。"
)


class SystemPromptPlugin(_BaseStudyPlugin):
    """组装 system prompt（harness/pipeline 的 PREPARE 职责）。

    人格（{personality}）与学习上下文（{user_context}）由
    `StudyPromptBuilder` 的插槽渲染 —— 本插件只负责把整段组装结果放进
    `ctx.system_prompt`，**注入点唯一**，不会与 builder 重复。

    阶段 1 起 system prompt 是**逐轮重建**的（禁用技能后指令立即消失）；
    阶段 3 起这条重建也归管线所有。
    """

    name = "study_system_prompt"
    description = "组装 system prompt（身份 + 人格 + 学习上下文 + 技能指令）"
    hooks = [HookPoint.PREPARE]
    priority = 10

    def __init__(self, prompt_builder=None):
        self._prompt_builder = prompt_builder

    def on_hook(self, hook: HookPoint, ctx: Context) -> Context:
        if self._prompt_builder is None:
            return ctx
        voice = bool(getattr(ctx, "is_asr_input", False))
        uid = int(ctx.user_id or 1)
        # 学习上下文由 boot 在**请求线程**算好后随 ctx 传进来。
        # 不能靠 contextvars：管线跑在自己的常驻事件循环线程里，
        # contextvars 不跨线程继承 —— 靠它传上下文等于永远传不到
        # （这就是「主AI 没有上下文」的根因之一）。
        context = ctx.extra.get("learning_context")
        try:
            if voice:
                # 语音模式：去掉 17KB 技能说明，只留身份/人格/学习上下文
                prompt = self._prompt_builder.build(
                    uid=uid, context=context,
                    only_tags=list(VOICE_PROMPT_TAGS))
            else:
                prompt = self._prompt_builder.build(uid=uid, context=context)
        except Exception:
            logger.warning("system prompt 组装失败（已跳过）", exc_info=True)
            return ctx
        if prompt:
            ctx.system_prompt = prompt
        # prompt 体积（chars）—— 直接决定 model_invoke 的 provider 侧耗时
        logger.info("system prompt 组装完成: %d 字 (asr=%s)",
                    len(ctx.system_prompt or ""), bool(ctx.is_asr_input))
        # 语音输入 → 追加紧凑技能索引 + "简短回答"指令（文本输入不受影响）
        if voice:
            idx = ""
            try:
                idx = self._prompt_builder.compact_skill_index()
            except Exception:
                idx = ""
            if idx:
                ctx.system_prompt += ("\n\n【可用能力（简表）】\n" + idx
                                      + "\n（需要细节时再调用对应工具）")
            # 短回复限制是**可选**的（默认关）：开了才注入 40 字上限，
            # 否则语音轮也能完整展开讲解。
            if getattr(Config, "VOICE_SHORT_REPLY", False):
                ctx.system_prompt += ("\n\n" + VOICE_MODE_INSTRUCTION)
        return ctx


# ══════════════════════════════════════════════════════════════
# PRE_PROCESS —— 与当前消息强相关
# ══════════════════════════════════════════════════════════════

class VisionContextPlugin(_BaseStudyPlugin):
    """检测到图片 → 多模态描述 → 注入上下文。

    对齐参考实现 plugins/builtin/vision_plugin.py。

    迁移计划阶段 5.6/5.7：
    - 图片来源优先走 `ctx.attachments`（Attachment(kind="image")）——
      基座的标准附件通道，不再依赖 `image_data` 字符串塞值；
      `image_data` 与消息内嵌 data URL 保留为兼容来源。
    - 「看到 → 录入」桥：图片自动落盘到工作区 vision 目录，路径写进
      `ctx.extra["vision_image_paths"]` 并附进上下文 —— AI 据此可调用
      只认文件路径的入库工具（quest_from_image.import_photo_questions 等）。
    """

    name = "study_vision_context"
    description = "图片描述注入（多模态）+ 落盘桥"
    hooks = [HookPoint.PRE_PROCESS]
    priority = 10

    #: 单轮最多描述的图片数（多图成本线性涨，摄像头场景一轮一图是常态）
    MAX_IMAGES_PER_TURN = 3

    def __init__(self, llm=None, workspace=None):
        self._llm = llm
        self._workspace = workspace

    @staticmethod
    def _extract_data_url(message: str, image: Optional[str]) -> str:
        if image:
            return image
        if not message:
            return ""
        m = DATA_URL_RE.search(message)
        return m.group(0) if m else ""

    def _collect_images(self, ctx: Context) -> list:
        """按优先级收集本轮图片 data URL：attachments > image_data > 消息内嵌。

        优先级语义：attachments 里有图时**只认 attachments**（旧来源视为
        已被取代），避免同一张图被兼容通道重复描述。
        """
        urls: list[str] = []
        for att in (getattr(ctx, "attachments", None) or []):
            kind = getattr(att, "kind", "")
            if kind != "image":
                continue
            data = getattr(att, "data", None)
            if isinstance(data, str) and data:
                urls.append(data if data.startswith("data:")
                            else f"data:image/jpeg;base64,{data}")
        if urls:
            return urls[: self.MAX_IMAGES_PER_TURN]
        main = self._extract_data_url(ctx.message, ctx.image_data)
        if main:
            urls.append(main)
        # 消息正文里除主图外可能还有内嵌图
        for m in DATA_URL_RE.finditer(ctx.message or ""):
            if m.group(0) not in urls:
                urls.append(m.group(0))
        return urls[: self.MAX_IMAGES_PER_TURN]

    def _save_to_disk(self, ctx: Context, data_url: str) -> str:
        """把图片落盘到工作区 vision 目录，返回路径（失败返回空串）。

        这是「看到 → 录入」桥的落盘半边：入库工具只认文件路径。
        """
        try:
            import base64 as _b64
            import os as _os
            import re as _re
            import time as _time
            import uuid as _uuid

            m = _re.match(r"data:image/(\w+);base64,(.*)", data_url, _re.DOTALL)
            raw = _b64.b64decode(m.group(2) if m else data_url)
            if not raw:
                return ""
            ext = (m.group(1) if m else "jpg").lower()
            if ext not in ("jpg", "jpeg", "png", "webp", "bmp"):
                ext = "jpg"
            uid = int(ctx.user_id or 1)
            try:
                base_dir = self._workspace.user_subdir(uid, "vision")
            except Exception:
                base_dir = _os.path.join("workspace", f"user_{uid}", "vision")
                _os.makedirs(base_dir, exist_ok=True)
            ts = _time.strftime("%Y%m%d_%H%M%S")
            path = _os.path.join(
                str(base_dir), f"chat_{ts}_{_uuid.uuid4().hex[:6]}.{ext}")
            with open(path, "wb") as f:
                f.write(raw)
            return path
        except Exception:
            logger.warning("对话图片落盘失败（录入桥降级）", exc_info=True)
            return ""

    def on_hook(self, hook: HookPoint, ctx: Context) -> Context:
        if self._llm is None:
            return ctx
        data_urls = self._collect_images(ctx)
        if not data_urls:
            return ctx
        prompt = getattr(Config, "VISION_PROMPT", "请详细描述这张图片的内容")
        blocks: list[str] = []
        saved_paths: list[str] = []
        for idx, data_url in enumerate(data_urls):
            try:
                desc = self._llm.describe_image(data_url, prompt)
                blocks.append(f"[图片描述: {desc}]")
            except Exception as exc:
                logger.warning("图片描述失败: %s", exc)
                blocks.append(f"[无法识别图片: {exc}]")
            path = self._save_to_disk(ctx, data_url)
            if path:
                saved_paths.append(path)
        if saved_paths:
            ctx.extra["vision_image_paths"] = saved_paths
            blocks.append(
                "[图片已保存] " + "；".join(saved_paths)
                + "。若图中是题目且用户想收录，"
                "可调用图片识题技能 import_photo_questions(file_path=<上述路径>) 入库。")
        self._append_context(ctx, "\n".join(blocks))
        return ctx


class ExamSessionPlugin(_BaseStudyPlugin):
    """考试上下文：超时自动交卷 / 交卷关键词触发 / 进行中剩余时间。

    对齐参考实现 plugins/builtin/exam_sim_plugin.py。
    与参考实现的有意差异：关键词收窄为明确的交卷语义（"提交"太宽泛，
    会误伤"提交作业"）；考试会话按 user_id 查 exam_sessions
    —— 参考实现里 ctx.extra["exam_session_id"] 从无写入方，该分支实为死代码。
    """

    name = "study_exam_session"
    description = "考试状态注入 / 超时自动交卷 / 关键词交卷"
    hooks = [HookPoint.PRE_PROCESS]
    priority = 20

    def __init__(self, exam_engine=None):
        self._exam_engine = exam_engine

    def _active_session(self, user_id: int) -> Optional[dict]:
        if self._exam_engine is None:
            return None
        try:
            sessions = self._exam_engine.get_user_sessions(user_id, limit=10)
        except Exception:
            logger.debug("读取考试会话失败（已忽略）", exc_info=True)
            return None
        for s in sessions or []:
            if s.get("status") == "in_progress":
                return s
        return None

    @staticmethod
    def _report_block(result: dict, prefix: str = "[考试报告]") -> str:
        total = result.get("total_count", 0) or 0
        correct = result.get("correct_count", 0) or 0
        score = result.get("score", 0) or 0
        max_score = result.get("max_score", total) or total
        rate = (correct / total * 100) if total else 0
        lines = [
            f"{prefix} 得分 {score}/{max_score}（正确率 {rate:.0f}%，"
            f"用时 {int(result.get('duration_sec', 0) or 0) // 60} 分钟）。",
        ]
        wrong = [d for d in (result.get("details") or []) if not d.get("correct")]
        if wrong:
            lines.append("错题：")
            for d in wrong[:5]:
                content = str(d.get("content", ""))[:40]
                lines.append(f"  - {content}（正确答案：{d.get('correct_answer', '未知')}）")
        return "\n".join(lines)

    def _exam_block(self, user_id: int, message: str) -> str:
        if self._exam_engine is None:
            return ""
        session = self._active_session(user_id)
        if not session:
            return ""
        sid = session.get("session_id", "")

        # 1) 超时自动交卷（优先于一切）
        try:
            timed_out = self._exam_engine.is_timeout(sid)
        except Exception:
            timed_out = False
        if timed_out:
            try:
                result = self._exam_engine.auto_submit(sid)
            except Exception:
                logger.warning("考试超时自动交卷失败: session=%s", sid[:8],
                               exc_info=True)
                return ""
            if result.get("success"):
                return self._report_block(result, prefix="[考试超时自动交卷]")
            return ""

        # 2) 交卷关键词触发
        lowered = (message or "").lower()
        if any(k in lowered for k in SUBMIT_KEYWORDS):
            try:
                result = self._exam_engine.submit_session(sid)
            except Exception:
                logger.warning("关键词交卷失败: session=%s", sid[:8], exc_info=True)
                return ""
            if result.get("success"):
                return self._report_block(result, prefix="[已交卷]")

        # 3) 进行中剩余时间
        try:
            remaining = self._exam_engine.get_remaining_time(sid)
        except Exception:
            remaining = 0
        if remaining > 0:
            return (f"[考试进行中] 剩余 {remaining // 60} 分钟"
                    f"（session={sid[:8]}），可继续作答或交卷。")
        return ""

    def on_hook(self, hook: HookPoint, ctx: Context) -> Context:
        try:
            block = self._exam_block(int(ctx.user_id or 1), ctx.message)
        except Exception:
            logger.warning("考试钩子异常（已跳过）", exc_info=True)
            return ctx
        self._append_context(ctx, block)
        return ctx


class DailyReportPlugin(_BaseStudyPlugin):
    """22:00 后每日一次的日终报告（对齐参考实现 PlanPlugin）。"""

    name = "study_daily_report"
    description = "22:00 日终报告注入"
    hooks = [HookPoint.PRE_PROCESS]
    priority = 30

    def __init__(self, plan_engine=None):
        self._plan_engine = plan_engine
        self._report_date = ""      # 已生成日终报告的日期
        self._report_user = -1      # 已生成报告的用户

    def _daily_report_block(self, user_id: int) -> str:
        if self._plan_engine is None:
            return ""
        now = datetime.now()
        if now.hour < DAILY_REPORT_HOUR:
            return ""
        today = date.today().isoformat()
        if self._report_date == today and self._report_user == user_id:
            return ""
        try:
            summary = self._plan_engine.daily_summary(user_id, today)
        except Exception:
            return ""
        if not summary or not summary.get("total"):
            return ""
        self._report_date = today
        self._report_user = user_id
        lines = [
            f"[日终报告 — {today}]",
            f"  完成: {summary['done']}/{summary['total']}",
            f"  跳过: {summary['skipped']}",
            f"  进度: {summary.get('progress', 0) * 100:.0f}%",
        ]
        done_titles = [t["title"] for t in summary.get("tasks", [])
                       if t.get("status") == "done"]
        if done_titles:
            lines.append(f"  完成项: {', '.join(done_titles[:8])}")
        return "\n".join(lines)

    def on_hook(self, hook: HookPoint, ctx: Context) -> Context:
        try:
            block = self._daily_report_block(int(ctx.user_id or 1))
        except Exception:
            logger.warning("日终报告钩子异常（已跳过）", exc_info=True)
            return ctx
        self._append_context(ctx, block)
        return ctx


class ComplexityPlugin(_BaseStudyPlugin):
    """复杂问题提示 —— 引导 AI 走 create_reasoner 深入推理。"""

    name = "study_complexity"
    description = "复杂度分析提示（引导走 create_reasoner）"
    hooks = [HookPoint.PRE_PROCESS]
    priority = 40

    def __init__(self, complexity_analyzer=None):
        self._complexity_analyzer = complexity_analyzer

    def on_hook(self, hook: HookPoint, ctx: Context) -> Context:
        if self._complexity_analyzer is None:
            return ctx
        try:
            result = self._complexity_analyzer.analyze_complexity(
                ctx.message or "", 0)
        except Exception:
            logger.warning("复杂度分析失败（已跳过）", exc_info=True)
            return ctx
        if not result or not result.get("is_complex"):
            return ctx
        reasons = "、".join(result.get("reasons", [])[:3])
        self._append_context(
            ctx,
            f"(系统上下文·仅供你参考) 该问题复杂度较高（评分 "
            f"{result.get('score', 0)}；{reasons}）。"
            f"如需深入推理，可调用 create_reasoner 工具后台分析。")
        return ctx


# ══════════════════════════════════════════════════════════════
# MODEL_INVOKE —— 调模型
# ══════════════════════════════════════════════════════════════

class ModelInvokePlugin(_BaseStudyPlugin):
    """真正调用 agent（AgentLoop + 技能工具）。

    做成**同步** Plugin：PluginManager 会用 run_in_executor 把它挪到线程池，
    不阻塞事件循环。模型客户端是同步的（infra orchestrator 的 invoke）。
    """

    name = "study_model_invoke"
    description = "调用主模型"
    hooks = [HookPoint.MODEL_INVOKE]
    priority = 50

    def __init__(self, agent=None):
        self._agent = agent

    def on_hook(self, hook: HookPoint, ctx: Context) -> Context:
        if self._agent is None:
            return ctx
        result = self._agent.run_with_tools(
            ctx.message,
            session_id=ctx.session_id or None,
            system_prompt=ctx.system_prompt or None,
        )
        ctx.reply = result.reply or ""
        ctx.original_reply = ctx.reply
        return ctx


# ══════════════════════════════════════════════════════════════
# POST_PROCESS —— 回复后处理
# ══════════════════════════════════════════════════════════════

class PlanCheckPlugin(_BaseStudyPlugin):
    """解析模型回复里的 <plan_check> 标签并回写计划任务（对齐参考实现 PlanPlugin）。"""

    name = "study_plan_check"
    description = "<plan_check> 标签回写计划任务"
    hooks = [HookPoint.POST_PROCESS]
    priority = 50

    def __init__(self, plan_engine=None):
        self._plan_engine = plan_engine

    def on_hook(self, hook: HookPoint, ctx: Context) -> Context:
        reply = ctx.reply or ""
        if "<plan_check>" not in reply:
            return ctx
        results: list[dict] = []
        for match in PLAN_CHECK_RE.finditer(reply):
            try:
                data = json.loads(match.group(1).strip())
                task_id = data.get("task_id", "")
                action = data.get("action", "done")
                if not task_id:
                    results.append({"tag": "<plan_check>", "success": False,
                                    "summary": "缺少 task_id"})
                    continue
                if self._plan_engine is None:
                    results.append({"tag": "<plan_check>", "success": False,
                                    "summary": "计划系统未初始化"})
                    continue
                if action == "skip":
                    self._plan_engine.skip_task(task_id)
                else:
                    self._plan_engine.check_off(task_id)
                results.append({"tag": "<plan_check>", "success": True,
                                "summary": f"任务 {task_id[:8]} → {action}"})
                logger.info("plan_check: %s → %s", task_id[:8], action)
            except Exception as exc:
                logger.warning("plan_check 解析失败: %s", exc)
                results.append({"tag": "<plan_check>", "success": False,
                                "summary": "解析失败: %s" % exc})
        ctx.reply = PLAN_CHECK_RE.sub("", reply).strip()
        ctx.set_output("plan_check", results)
        return ctx


class MemoryRecordPlugin(_BaseStudyPlugin):
    """记忆闭环：原始轮次落库 → 异步摘要 → 处理回复里的 <memo>/<recall> 标签。

    迁移计划阶段 7：TOPIC_ENABLED 时同步把本轮写进话题库（record_turn），
    话题边界与上下文归 TopicContextPlugin 管。
    """

    name = "study_memory_record"
    description = "记忆轮次落库 + <memo>/<recall> 标签处理"
    hooks = [HookPoint.POST_PROCESS]
    priority = 60

    def __init__(self, memory_system=None, context_store=None):
        self._memory_system = memory_system
        #: 新上下文内核的存储（把这一轮写进 context_turns，供 tail 来源读取）
        self._context_store = context_store

    def on_hook(self, hook: HookPoint, ctx: Context) -> Context:
        if self._memory_system is None:
            return ctx
        try:
            uid = int(ctx.user_id or 1)
            cid = ctx.chat_id or 0
            ridx = ctx.extra.get("round_index", 0)
            self._memory_system.record_round(uid, cid, ridx,
                                            ctx.extra.get("user_message", ""),
                                            ctx.reply)
            self._memory_system.summarize_turn(uid, cid, ridx,
                                               ctx.extra.get("user_message", ""),
                                               ctx.reply)
            ctx.reply = self._memory_system.handle_tags(uid, cid, ctx.reply)
            # 新上下文内核：原始轮次落 context_turns（"最近对话"由它承载）
            if self._context_store is not None:
                try:
                    from apps.dsn_study.context import TurnContext
                    turn = TurnContext(
                        uid=uid,
                        session_id=str(ctx.session_id or ""),
                        message=ctx.extra.get("user_message", ""),
                        round_index=ridx,
                        chat_id=cid,
                    )
                    self._context_store.record_turn(
                        turn, ctx.extra.get("user_message", ""), ctx.reply or "")
                except Exception:
                    logger.warning("轮次写入上下文内核失败（已跳过）", exc_info=True)
            # 话题库：本轮原文归档进当前话题（POST_PROCESS 时话题已由
            # TopicContextPlugin 决定 —— 不新建，只记录）
            if Config.TOPIC_ENABLED:
                topics = getattr(self._memory_system, "_topics", None)
                if topics is not None:
                    topics.record_turn(uid, cid,
                                       ctx.extra.get("user_message", ""),
                                       ctx.reply or "", round_idx=ridx)
        except Exception:
            logger.warning("记忆闭环失败（已跳过）", exc_info=True)
        return ctx


class TopicContextPlugin(_BaseStudyPlugin):
    """话题上下文（迁移计划阶段 7.5）：边界检测 + 弹性上下文接热路径。

    PREPARE（priority 15，在 SystemPromptPlugin(10) 之后）：
      1. `on_new_message` 决定 continue / new / reopen（时间 + 语义边界）；
      2. `memory_system.assemble_context(chat_id=...)` 拿到话题上下文
         （单条 system：关闭话题摘要 + pin 原文 + 当前话题原文 + SEG_TAIL 保底）；
      3. 话题块合并进 `ctx.system_prompt`；
      4. **裁剪 agent 会话历史**：长会话只保留最近 tail_rounds 轮原文，
         更早的内容由话题摘要承担 —— 这是不超预算的关键（此前
         AgentRuntime 的 conv.messages 无限增长）。
    """

    name = "study_topic_context"
    description = "话题边界 + 弹性上下文（长会话预算控制）"
    hooks = [HookPoint.PREPARE]
    priority = 15

    def __init__(self, memory_system=None, agent=None):
        self._memory_system = memory_system
        self._agent = agent

    def on_hook(self, hook: HookPoint, ctx: Context) -> Context:
        if self._memory_system is None or not Config.TOPIC_ENABLED:
            return ctx
        topics = getattr(self._memory_system, "_topics", None)
        if topics is None:
            return ctx
        try:
            uid = int(ctx.user_id or 1)
            cid = ctx.chat_id or 0
            message = ctx.extra.get("user_message", "") or ctx.message or ""

            # 语音轮不跑 LLM judge：一次 judge 8~18s，而对讲机要的是即时回应。
            decision = topics.on_new_message(
                uid, cid, message,
                round_idx=ctx.extra.get("round_index", 0),
                allow_llm_judge=not getattr(ctx, "is_asr_input", False))
            ctx.extra["topic_decision"] = decision
            ctx.extra["topic_id"] = decision.get("topic_id")
            # 话题边界判定落日志：会话「推不下去 / 换话题没反应」时，
            # 先看这一行（是 continue 还是 new、依据是什么）。
            logger.info("话题判定: %s（%s）→ %s",
                        decision.get("action"), decision.get("reason", ""),
                        decision.get("topic_title") or decision.get("topic_id"))

            # 话题上下文 → 合并进 system prompt（单条 system 语义，
            # 与 {user_context} 等插槽并列）。SEG_TAIL 保底随块注入。
            assembled = self._memory_system.assemble_context(
                uid, history=[], chat_id=cid)
            block = "\n\n".join(
                m["content"] for m in assembled
                if isinstance(m, dict) and m.get("role") == "system"
                and m.get("content"))
            if block:
                ctx.system_prompt = (f"{ctx.system_prompt}\n\n{block}"
                                     if ctx.system_prompt else block)

            # 裁剪 agent 会话历史：历史原文已由话题块承载（当前话题 verbatim
            # + SEG_TAIL 保底 + 关闭话题摘要），conv.messages 清空后由
            # run_with_tools 重新追加本轮 —— 这是不超预算的关键
            # （此前 AgentRuntime 的 conv.messages 无限增长）。
            self._trim_agent_history(ctx)
        except Exception:
            logger.warning("话题上下文处理失败（已跳过）", exc_info=True)
        return ctx

    def _trim_agent_history(self, ctx: Context) -> None:
        agent = self._agent
        if agent is None or not getattr(ctx, "session_id", ""):
            return
        try:
            conv = agent.conversations.get(ctx.session_id) \
                if hasattr(agent, "conversations") else None
            if conv is None:
                return
            prior = len(conv.messages)
            if prior <= 0:
                return
            kept_system = [m for m in conv.messages if m.role == "system"]
            removed = prior - len(kept_system)
            conv.messages = kept_system
            if removed:
                logger.info("话题系统裁剪 agent 历史: session=%s -%d 条"
                            "（上下文由话题块承载）", ctx.session_id, removed)
        except Exception:
            logger.debug("agent 历史裁剪失败（已跳过）", exc_info=True)


class PersonalityFeedbackPlugin(_BaseStudyPlugin):
    """人格闭环：把这一轮回写 PEV3（情绪/亲密度/特质证据）。"""

    name = "study_personality_feedback"
    description = "人格状态回写（harness/personality）"
    hooks = [HookPoint.POST_PROCESS]
    priority = 70

    def __init__(self, personality=None, persona_engine=None):
        self._personality = personality
        self._persona_engine = persona_engine

    def on_hook(self, hook: HookPoint, ctx: Context) -> Context:
        if self._personality is None and self._persona_engine is None:
            return ctx
        # 语音轮（对讲机）**不做人格判定**：它要打一次 LLM，而 provider 会
        # 串行排队 —— 后台调用排在用户下一轮的主回复前面，就能把回复拖到
        # 80 秒（实测）。语音回复短、随意，人格判定的收益也最低。
        if getattr(ctx, "is_asr_input", False):
            return ctx
        uid = int(ctx.user_id or 1)
        user_message = ctx.extra.get("user_message", "")
        reply = ctx.reply

        # ── 规则路径（默认）──
        # 事件判定走关键词规则，**零 LLM、零排队**，纯本地计算 →
        # 可以同步跑：状态立刻可见，回复不受任何影响。
        engine = self._persona_engine
        if engine is not None and not engine.use_llm_judge:
            try:
                engine.feedback(uid, user_message, reply)
            except Exception:
                logger.warning("人格回写失败（已跳过）", exc_info=True)
            return ctx

        # ── LLM 路径（可选）──
        # 人格判定要调 LLM（事件分类），**不阻塞回复**：
        # 回复内容不依赖它，下一轮才用到更新后的状态。
        # 同步跑会让每轮对话多花 2-4 秒。

        def _feedback():
            # 捕获"这一轮"的人格判定客户端：后台线程要等用户空闲才发请求，
            # 到那时调用方可能已把客户端换回去了 —— 显式带下来，语义才不漂。
            judge = getattr(self._personality, "_judge", None)
            captured = getattr(judge, "_chat", None) if judge is not None else None
            # 等用户这一轮彻底结束再发起 —— 否则后台这次 LLM 调用会排在
            # 用户**下一轮**的主回复调用前面（provider 串行排队），
            # 把回复拖到 50~100 秒。实测踩过。
            try:
                from apps.dsn_study.turn_gate import wait_for_idle
                wait_for_idle()
            except Exception:
                pass
            try:
                self._personality.analyze_interaction(uid, user_message, reply,
                                                      judge_chat=captured)
            except Exception:
                # 日志流可能已关闭（进程退出 / 测试收尾）—— 再记一次日志
                # 本身也会抛异常，必须兜住，否则线程异常会污染测试结果。
                try:
                    logger.warning("人格状态更新失败（已跳过）", exc_info=True)
                except Exception:
                    pass

        try:
            threading.Thread(target=_feedback, daemon=True,
                             name="personality-feedback").start()
        except Exception:
            logger.warning("人格回写线程启动失败（已跳过）", exc_info=True)
        return ctx


# ══════════════════════════════════════════════════════════════
# POST_TTS —— 语音合成
# ══════════════════════════════════════════════════════════════

class TTSPlugin(_BaseStudyPlugin):
    """语音合成（跟随回复自动生成，不提供 AI 主动合成入口）。

    失败即降级为纯文本，绝不打断对话。
    """

    name = "study_tts"
    description = "回复语音合成（GPT-SoVITS，经 infra 资源池）"
    hooks = [HookPoint.POST_TTS]
    priority = 60

    def __init__(self, voice=None):
        self._voice = voice

    def on_hook(self, hook: HookPoint, ctx: Context) -> Context:
        if self._voice is None or not ctx.reply:
            return ctx
        # 只有需要音频的调用方才合成（chat() 走纯文本，chat_audio() 才要）
        if not ctx.tts_enabled:
            return ctx
        try:
            audio_b64, error = self._voice.synthesize_b64(ctx.reply)
            ctx.audio_b64 = audio_b64
            ctx.tts_error = error
        except Exception as exc:
            logger.warning("语音合成失败（降级为纯文本）: %s", exc)
            ctx.audio_b64 = None
            ctx.tts_error = str(exc)
        return ctx
