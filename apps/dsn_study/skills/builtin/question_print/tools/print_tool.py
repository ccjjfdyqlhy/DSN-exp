# skills/builtin/question_print/tools/print_tool.py
# 出题打印工具 — 组卷/AI出题 → A4 PDF → 打印

from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger("skill.question_print")


class QuestionPrintTool:
    """出题打印。AI 通过 <tool>{"skill":"question_print","tool":"print_paper",...}</tool> 调用。"""

    def __init__(self, question_store=None, template_manager=None):
        self._store = question_store
        self._tm = template_manager

    def _store_impl(self):
        """懒加载题库存储（未注入时自建）。"""
        if self._store is None:
            from question_bank.store import QuestionStore
            from db.question_bank import QuestionBankDBManager
            self._store = QuestionStore(db=QuestionBankDBManager())
        return self._store

    def print_paper(
        self,
        subject: str = "math",
        count: int = 10,
        difficulty: int = 3,
        include_answer: bool = False,
        copies: int = 1,
        title: str = "",
        questions: list = None,
        printer: str = "",
        user_id: int = 0,
    ) -> dict:
        """
        出题并打印成纸质试卷。

        题目来源（二选一）：
          - questions 传入：直接使用（AI 自出题 / 从题库查出的题目），忽略 count/difficulty
          - questions 未传：从题库按学科+难度自动组卷

        :param subject: 学科代码 (math/physics/chemistry/english/chinese/biology/...)
        :param count: 组卷题数，默认 10
        :param difficulty: 平均难度 1-5，默认 3
        :param include_answer: True 时在 PDF 中附答案与解析
        :param copies: 打印份数
        :param title: 试卷标题，默认自动生成
        :param questions: 可选题目列表（见上）
        :param printer: 打印机名，留空用系统默认打印机
        :param user_id: 用户 ID（用于保存到工作区）
        :return: {success, pdf_path, job_id, question_count, preview}
        """
        uid = user_id or 1
        try:
            store = self._store_impl()

            if questions:
                qs = list(questions)
            else:
                qs = self._compose(store, subject, count, difficulty)

            if not qs:
                return {
                    "success": False,
                    "error": f"学科 {subject} 没有可用题目，请先录入题目或用 AI 自出题",
                    "subject": subject,
                }

            pdf_path = self._render_pdf(qs, subject, title, include_answer, uid)
            if not pdf_path:
                return {"success": False, "error": "生成 PDF 失败（weasyprint 不可用或渲染异常）"}

            print_result = self._print(pdf_path, copies, printer)

            return {
                "success": True,
                "pdf_path": str(pdf_path),
                "question_count": len(qs),
                "subject": subject,
                "include_answer": include_answer,
                "preview": [self._preview(q) for q in qs[:5]],
                "print": print_result,
            }
        except Exception as e:
            logger.exception("出题打印失败")
            return {"success": False, "error": f"出题打印失败: {e}"}

    # ── 组卷 ──

    def _compose(self, store, subject: str, count: int, difficulty: int) -> list[dict]:
        from question_bank.composer import ExamComposer, ComposeParams
        composer = ExamComposer(question_store=store)
        params = ComposeParams(
            subject=subject,
            count=count,
            difficulty_dist={difficulty: 1.0},
        )
        result = composer.compose(params)
        if not result.get("success"):
            return []
        return result.get("questions", [])

    # ── 渲染 ──

    def _render_pdf(self, qs: list[dict], subject: str, title: str,
                    include_answer: bool, uid: int) -> str:
        try:
            from weasyprint import HTML
        except Exception as e:
            logger.error("weasyprint 不可用: %s", e)
            return ""

        from utils.workspace import get_workspace_manager
        wm = get_workspace_manager()
        try:
            out_dir = wm.user_subdir(uid, "papers")
        except Exception:
            from pathlib import Path
            out_dir = Path(".dsn") / "workspace" / f"user_{uid}" / "papers"
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        pdf_path = out_dir / f"{subject}_{ts}.pdf"

        html = self._build_html(qs, subject, title, include_answer)
        try:
            HTML(string=html).write_pdf(str(pdf_path))
            logger.info("PDF 已生成: %s (%d 题)", pdf_path, len(qs))
            return str(pdf_path)
        except Exception as e:
            logger.exception("PDF 渲染失败")
            return ""

    def _build_html(self, qs: list[dict], subject: str, title: str,
                    include_answer: bool) -> str:
        subj_map = {
            "math": "数学", "physics": "物理", "chemistry": "化学",
            "english": "英语", "chinese": "语文", "biology": "生物",
            "politics": "政治", "history": "历史", "geography": "地理",
        }
        subj_name = subj_map.get(subject, subject)
        heading = title or f"{subj_name}练习题（{len(qs)} 题）"

        def esc(s):
            return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        items = []
        for i, q in enumerate(qs, 1):
            parts = [f'<div class="q">',
                     f'<p class="qtext">{i}. {esc(q.get("content"))}</p>']
            options = q.get("options") or []
            if options:
                parts.append('<div class="opts">')
                for opt in options:
                    parts.append(f'<p>{esc(opt)}</p>')
                parts.append('</div>')
            if include_answer:
                parts.append(f'<p class="ans"><b>答案:</b> {esc(q.get("answer"))}</p>')
                if q.get("explanation"):
                    parts.append(f'<p class="ans"><b>解析:</b> {esc(q.get("explanation"))}</p>')
            parts.append('</div>')
            items.append("\n".join(parts))

        body = "\n".join(items)
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
@page {{ size: A4; margin: 18mm 16mm; }}
body {{ font-family: "Noto Sans CJK SC", "Noto Serif CJK SC", sans-serif;
       font-size: 11.5pt; color: #111; line-height: 1.7; }}
h1 {{ font-size: 16pt; text-align: center; margin-bottom: 4pt; }}
.sub {{ text-align: center; color: #666; font-size: 10pt; margin-bottom: 14pt; }}
.q {{ margin-bottom: 13pt; page-break-inside: avoid; }}
.qtext {{ margin: 0 0 4pt; font-weight: 600; }}
.opts p {{ margin: 1pt 0 1pt 14pt; }}
.ans {{ color: #333; margin: 3pt 0 0 0; font-size: 10pt; }}
</style></head><body>
<h1>{esc(heading)}</h1>
<p class="sub">学科：{esc(subj_name)} · 共 {len(qs)} 题{'' if include_answer else ' · 答案另附'}</p>
{body}
</body></html>"""
        return html

    # ── 打印 ──

    def _print(self, pdf_path: str, copies: int, printer: str) -> dict:
        try:
            from document.printer import PrinterTool
            return PrinterTool.print_file(
                file_path=pdf_path,
                printer_name=printer or None,
                copies=copies,
            )
        except Exception as e:
            logger.error("打印失败: %s", e)
            return {"success": False, "error": str(e)}

    @staticmethod
    def _preview(q: dict) -> dict:
        return {
            "question_id": q.get("question_id"),
            "content": q.get("content", "")[:60],
            "type_name": q.get("type_name", ""),
            "difficulty": q.get("difficulty"),
        }
