# apps/dsn_study/chat_hooks.py
# 对话期钩子 — 补齐参考实现 plugins/builtin/{exam_sim,plan}_plugin 的能力。
#
# 参考实现把下列行为挂在插件管线上：
#   - ExamSimPlugin (PRE_FILTER)  考试超时自动交卷 + "交卷/提交" 关键词触发
#   - PlanPlugin     (POST_PROCESS) <plan_check> 标签勾选 + 22:00 日终报告注入
#
# dsn_study 未接插件管线（等价能力在 boot.py 内联），这里用同一套语义补齐：
#   pre_process()  → 在用户消息前注入上下文（考试状态 / 超时报告 / 日终报告）
#   post_process() → 解析模型回复里的 <plan_check> 标签并回写计划任务
#
# 与参考实现的差异（有意为之）：
#   - 关键词触发收窄为明确的交卷语义（"提交" 过于宽泛，会误伤普通对话）；
#   - 考试会话不依赖 ctx.extra，而是按 user_id 查 exam_sessions —— 参考实现里
#     ctx.extra["exam_session_id"] 从无写入方，该分支实为死代码。

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from typing import Optional

from apps.dsn_study.config import Config

logger = logging.getLogger("StudyChatHooks")

#: 消息内嵌图片 data URL
_DATA_URL_RE = re.compile(r"data:image/\w+;base64,[A-Za-z0-9+/=]+")

#: <plan_check>{"task_id": "...", "action": "done"|"skip"}</plan_check>
_PLAN_CHECK_RE = re.compile(
    r"<plan_check>\s*(.*?)\s*</plan_check>", re.DOTALL | re.IGNORECASE)

#: 明确的交卷语义（不收窄会误伤"提交作业"等普通表达）
_SUBMIT_KEYWORDS = (
    "交卷", "提交试卷", "交卷吧", "交卷了", "我交卷", "答完了", "做完交卷",
    "submit exam", "submit the exam", "finish exam", "hand in",
)

#: 日终报告触发时间（参考实现用 22 点）
_DAILY_REPORT_HOUR = 22


class StudyChatHooks:
    """学习域对话钩子集合。"""

    def __init__(self, *, exam_engine=None, plan_engine=None, llm=None):
        self._exam_engine = exam_engine
        self._plan_engine = plan_engine
        self._llm = llm             # 视觉描述用（LLMService.describe_image）
        self._report_date = ""      # 已生成日终报告的日期
        self._report_user = -1      # 已生成报告的用户

    # ── 考试 ──

    def _active_session(self, user_id: int) -> Optional[dict]:
        """取该用户最近一场进行中的考试会话。"""
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

    def _exam_block(self, user_id: int, message: str) -> str:
        """考试上下文：超时自动交卷 / 交卷关键词触发 / 进行中剩余时间。"""
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
                logger.warning("考试超时自动交卷失败: session=%s", sid[:8], exc_info=True)
                return ""
            if result.get("success"):
                return self._report_block(result, prefix="[考试超时自动交卷]")
            return ""

        # 2) 交卷关键词触发
        lowered = (message or "").lower()
        if any(k in lowered for k in _SUBMIT_KEYWORDS):
            try:
                result = self._exam_engine.submit_session(sid)
            except Exception:
                logger.warning("关键词交卷失败: session=%s", sid[:8], exc_info=True)
                return ""
            if result.get("success"):
                return self._report_block(result, prefix="[已交卷]")

        # 3) 进行中剩余时间（参考实现把剩余时间注入上下文）
        try:
            remaining = self._exam_engine.get_remaining_time(sid)
        except Exception:
            remaining = 0
        if remaining > 0:
            return (f"[考试进行中] 剩余 {remaining // 60} 分钟"
                    f"（session={sid[:8]}），可继续作答或交卷。")
        return ""

    @staticmethod
    def _report_block(result: dict, prefix: str = "[考试报告]") -> str:
        """把判分结果压成一段上下文。"""
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

    # ── 计划 ──

    def _daily_report_block(self, user_id: int) -> str:
        """22:00 后每日一次的日终报告（对齐参考实现 PlanPlugin）。"""
        if self._plan_engine is None:
            return ""
        now = datetime.now()
        if now.hour < _DAILY_REPORT_HOUR:
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

    # ── 视觉（对齐参考实现 plugins/builtin/vision_plugin.py）──

    @staticmethod
    def _extract_data_url(message: str, image: Optional[str]) -> str:
        """从显式 image 参数或消息内嵌 data URL 中提取图片。"""
        if image:
            return image
        if not message:
            return ""
        m = _DATA_URL_RE.search(message)
        return m.group(0) if m else ""

    def _vision_block(self, message: str, image: Optional[str]) -> str:
        """检测到图片 → 多模态描述 → 注入上下文。"""
        if self._llm is None:
            return ""
        data_url = self._extract_data_url(message, image)
        if not data_url:
            return ""
        try:
            prompt = getattr(Config, "VISION_PROMPT",
                             "请详细描述这张图片的内容")
            desc = self._llm.describe_image(data_url, prompt)
        except Exception as e:
            logger.warning("图片描述失败: %s", e)
            return f"[无法识别图片: {e}]"
        return f"[图片描述: {desc}]"

    # ── 对外接口 ──

    def pre_process(self, user_id: int, message: str,
                    image: Optional[str] = None) -> str:
        """对话前：返回要注入消息前缀的系统上下文（可能为空串）。"""
        blocks: list[str] = []
        image_desc = self._vision_block(message, image)
        if image_desc:
            blocks.append(image_desc)
        try:
            exam_block = self._exam_block(user_id, message)
        except Exception:
            logger.warning("考试钩子异常（已跳过）", exc_info=True)
            exam_block = ""
        if exam_block:
            blocks.append(exam_block)
        try:
            report_block = self._daily_report_block(user_id)
        except Exception:
            logger.warning("日终报告钩子异常（已跳过）", exc_info=True)
            report_block = ""
        if report_block:
            blocks.append(report_block)
        if not blocks:
            return ""
        return "\n".join(f"(系统上下文·仅供你参考，不要复述) {b}" for b in blocks)

    def post_process(self, reply: str) -> tuple[str, list[dict]]:
        """对话后：解析 <plan_check> 标签回写计划。

        返回 (清洗后的回复, 处理结果列表)。
        """
        if not reply or "<plan_check>" not in reply:
            return reply, []
        results: list[dict] = []
        for match in _PLAN_CHECK_RE.finditer(reply):
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
            except Exception as e:
                logger.warning("plan_check 解析失败: %s", e)
                results.append({"tag": "<plan_check>", "success": False,
                                "summary": f"解析失败: {e}"})
        cleaned = _PLAN_CHECK_RE.sub("", reply).strip()
        return cleaned, results
