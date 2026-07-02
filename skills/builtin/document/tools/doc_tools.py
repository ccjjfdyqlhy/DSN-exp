# skills/builtin/document/tools/doc_tools.py
# 文档处理工具 — 包装 DocProcessor 管线 + HMD 读取

from __future__ import annotations

import logging

logger = logging.getLogger("skill.document")


class DocTools:
    """文档处理：OCR/HMD 管线和读取。AI 通过 <tool>{"skill":"document","tool":"process_scan",...}</tool> 调用。"""

    def __init__(self):
        from document.doc_processor import DocProcessor
        from document.hmd import HmdClient
        self._processor = DocProcessor()
        self._hmd = HmdClient()
        self._question_store = None
        self._models = None
        logger.info("DocTools 已就绪")

    def process_scan(self, scanned_files: list[dict],
                     user_id: int = 0) -> dict:
        """
        处理扫描结果：分类→OCR→2md→打包 .hmd。

        :param scanned_files: 扫描产出的文件列表
        :param user_id: 用户 ID（默认 0=自动取第一个用户）
        :return: {hmd_path, feedback_text, documents_summary, photos_summary}
        """
        uid = user_id or 1
        logger.info("process_scan 开始: %d 文件 (user_id=%d)", len(scanned_files), uid)
        result = self._processor.process_scan(
            user_id=uid,
            scanned_images=scanned_files,
        )
        # 移除 data_url（base64 图片）避免 payload 爆炸，仅保留文件名和路径
        for lst_key in ("documents", "photos"):
            lst = result.get(lst_key, [])
            summary_list = []
            for item in lst:
                summary_list.append({
                    "filename": item.get("filename", ""),
                    "filepath": item.get("filepath", ""),
                    "category": item.get("category", ""),
                })
            result[f"{lst_key}_summary"] = summary_list
            result.pop(lst_key, None)

        logger.info("process_scan 完成: hmd=%s md=%s docs=%d photos=%d",
                     result.get("hmd_path") or "none",
                     result.get("md_path") or "none",
                     len(result.get("documents_summary", [])),
                     len(result.get("photos_summary", [])))
        return result

    def read_hmd(self, hmd_path: str) -> dict:
        """
        解包 .hmd 文件，返回结构化数据供 AI 阅读。
        mda 返回全文，其他字段仅返回摘要（避免 payload 过大）。

        :param hmd_path: .hmd 文件路径
        :return: {success, mda, mdb_summary, json_keys, images_count}
        """
        logger.info("read_hmd: %s", hmd_path)
        data = self._hmd.read_hmd(hmd_path)
        mda = data.get("mda", "")
        mdb = data.get("mdb", "")
        images = data.get("images", [])
        js = data.get("json", {})
        logger.info("read_hmd 完成: mdA=%d chars, mdB=%d chars, images=%d",
                     len(mda), len(mdb), len(images))
        return {
            "success": True,
            "mda": mda,
            "mdb_summary": f"[mdb: {len(mdb)} chars, 布局分析全文未载入，按需询问细节]",
            "json_keys": list(js.keys()) if isinstance(js, dict) else [],
            "images_count": len(images),
        }

    def process_last_scan(self, user_id: int = 0) -> dict:
        """
        自动处理最近一次扫描产生的文件：列出 uploads 目录，按修改时间取最新的 PNG，直接走管线。
        零参数，无需手动构造文件列表。

        :param user_id: 用户 ID（默认 0=自动取第一个用户）
        :return: 同 process_scan 的返回
        """
        import os
        uid = user_id or 1
        from utils.workspace import get_workspace_manager
        wm = get_workspace_manager()
        uploads = wm.user_uploads_dir(uid=uid)
        logger.info("process_last_scan: 扫描 %s (user_id=%d)", uploads, uid)

        pngs = []
        if os.path.isdir(uploads):
            for f in sorted(os.listdir(uploads), key=lambda f: os.path.getmtime(os.path.join(uploads, f)), reverse=True):
                if f.lower().endswith(".png"):
                    fp = os.path.join(uploads, f)
                    pngs.append({"filename": f, "filepath": fp, "size": os.path.getsize(fp)})

        if not pngs:
            return {"success": False, "error": f"在 {uploads} 中未找到 PNG 文件，请先执行 scan", "hmd_path": None, "feedback_text": ""}

        logger.info("process_last_scan: 找到 %d 个文件，自动传入 process_scan", len(pngs))
        return self.process_scan(scanned_files=pngs, user_id=uid)

    def describe_image(self, file_path: str, prompt: str = None) -> dict:
        """
        用视觉模型分析本地图片内容（非文档 OCR，而是通用图像理解）。

        :param file_path: 图片文件路径（支持 ~ 展开）
        :param prompt: 描述提示词，默认 "请详细描述这张图片的内容"
        :return: {success, description, error}
        """
        import os
        file_path = os.path.expanduser(file_path)
        if not os.path.isfile(file_path):
            return {"success": False, "error": f"文件不存在: {file_path}"}

        logger.info("describe_image: %s", file_path)

        # 先转 base64 data URL
        try:
            from models import VisionModel
            data_url = VisionModel.encode_image(file_path)
        except Exception as e:
            return {"success": False, "error": f"读取图片失败: {e}"}

        # 尝试用 VisionModel (GLM-4.6V / 外部 API)
        from config import Config
        if Config.VISION_API_KEY:
            try:
                vm = VisionModel()
                desc = vm.ask(
                    data_url,
                    prompt=(prompt or "请详细描述这张图片的内容"),
                    max_tokens=2048,
                    temperature=0.1,
                )
                logger.info("describe_image VisionModel 完成: %d chars", len(desc))
                return {"success": True, "description": desc}
            except Exception as e:
                logger.warning("VisionModel 失败，尝试 LMStudio 回退: %s", e)

        # 回退：用 LMStudio 多模态模型
        try:
            from models import LMStudioChat
            chat = LMStudioChat(model_name=None)
            desc = chat.describe_image(
                data_url,
                prompt=(prompt or "请详细描述这张图片的内容"),
            )
            logger.info("describe_image LMStudio 完成: %d chars", len(desc))
            return {"success": True, "description": desc}
        except Exception as e:
            logger.error("describe_image 全部失败: %s", e)
            return {"success": False, "error": f"图片分析失败: {e}"}

    def process_answered_scan(self, scanned_files: list, subject: str = "math",
                              user_id: int = 0) -> dict:
        """
        处理已作答的扫描试卷：识别题目 → 匹配题库 → 判分 → 错题分析。

        整个流程:
        1. 用 GradingModel 从图片中提取题目原文、题图描述、学生答案
        2. 用 AnswerSheetMatcher 将提取的题目与题库匹配
        3. 用 ExamScorer.score_answer_sheet() 统一判分
        4. 自动记录 exam_results 和 error_logs

        :param scanned_files: 扫描文件列表，支持字符串路径或 dict 格式
        :param subject: 学科代码
        :param user_id: 用户 ID
        :return: {
            success, score, max_score, correct_count, total_count,
            details, error_analyses, result_id,
            extraction: {提取详情},
            matching: {匹配详情},
        }
        """
        uid = user_id or 1
        logger.info("process_answered_scan 开始: %d 文件, subject=%s, user_id=%d",
                     len(scanned_files), subject, uid)

        # ── Step 0: 规范化文件列表 ──
        from models import VisionModel
        normalized = []
        for img in scanned_files:
            if isinstance(img, str):
                fp = os.path.expanduser(img)
                if not os.path.isfile(fp):
                    return {"success": False, "error": f"文件不存在: {fp}"}
                normalized.append({
                    "filename": os.path.basename(fp),
                    "filepath": fp,
                })
            elif isinstance(img, dict):
                fp = os.path.expanduser(img.get("filepath", img.get("path", "")))
                if not os.path.isfile(fp):
                    continue
                normalized.append({
                    "filename": img.get("filename", os.path.basename(fp)),
                    "filepath": fp,
                })
        if not normalized:
            return {"success": False, "error": "没有有效的扫描文件"}

        # ── Step 1: GradingModel 提取 ──
        try:
            from models import GradingModel
            gm = GradingModel()
            images_with_data = []
            for item in normalized:
                data_url = VisionModel.encode_image(item["filepath"])
                images_with_data.append({
                    "filename": item["filename"],
                    "data_url": data_url,
                })
            extraction = gm.extract_answer_sheet_batch(images_with_data)
        except Exception as e:
            logger.exception("GradingModel 提取失败")
            return {"success": False, "error": f"图片识别失败: {e}"}

        all_questions = []
        for page in extraction.get("pages", []):
            all_questions.extend(page.get("questions", []))
        if not all_questions:
            return {"success": False, "error": "未能从图片中识别出题目"}

        # ── Step 2: AnswerSheetMatcher 匹配题库 ──
        from exam_sim.answer_sheet import AnswerSheetMatcher
        matcher = AnswerSheetMatcher(question_store=self._question_store)
        matching = matcher.match(all_questions, subject=subject)

        if not matching["matched"]:
            return {
                "success": False,
                "error": "未能将提取的题目与题库匹配，请先录入这些题目",
                "extraction": {"questions_found": len(all_questions)},
                "matching": matching,
            }

        # ── Step 3: 统一判分 + 错题分析 ──
        from exam_sim.scorer import ExamScorer
        scorer = ExamScorer(
            question_store=self._question_store,
            models_plugin=self._models,
        )
        scoring = scorer.score_answer_sheet(
            matched_answers=matching["matched"],
            user_id=uid,
            subject=subject,
        )

        # 持久化考试结果到 exam_results
        result_id = None
        if scoring.get("success") and self._question_store:
            try:
                details = scoring.get("details", [])
                result_id = self._question_store.save_exam_result(
                    exam_id=0,
                    user_id=uid,
                    answers={str(d["question_id"]): d["user_answer"] for d in details},
                    score=scoring.get("score", 0),
                    max_score=scoring.get("max_score", 0),
                    duration_sec=0,
                    details={
                        "per_question": details,
                        "error_analyses": scoring.get("error_analyses", []),
                        "subject": subject,
                        "source": "answered_scan",
                    },
                )
                logger.info("扫描批改结果已保存: result_id=%s", result_id)
            except Exception as e:
                logger.warning("保存扫描批改结果失败: %s", e)

        logger.info("process_answered_scan 完成: 得分 %.1f/%.1f, 正确 %d/%d",
                     scoring.get("score", 0), scoring.get("max_score", 0),
                     scoring.get("correct_count", 0), scoring.get("total_count", 0))

        return {
            "success": scoring.get("success", False),
            "score": scoring.get("score", 0),
            "max_score": scoring.get("max_score", 0),
            "correct_count": scoring.get("correct_count", 0),
            "total_count": scoring.get("total_count", 0),
            "details": scoring.get("details", []),
            "error_analyses": scoring.get("error_analyses", []),
            "result_id": result_id,
            "extraction": {
                "pages": len(extraction.get("pages", [])),
                "questions_found": len(all_questions),
            },
            "matching": {
                "matched_count": matching["matched_count"],
                "unmatched_count": matching["unmatched_count"],
                "unmatched": matching["unmatched"],
            },
        }
