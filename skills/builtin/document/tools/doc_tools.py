# skills/builtin/document/tools/doc_tools.py
# 文档处理工具 — 包装 DocProcessor 管线 + HMD 读取

from __future__ import annotations

import json as json_mod
import logging
import os
from datetime import datetime

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

    # ════════════════════════════════════════════════════════════════
    # scan_import_questions — 一键管线: OCR → VisionModel 合成(含科目/图片描述) → 入库
    # 全程由 VisionModel 产出格式化 JSON，主模型不接触题目内容
    # ════════════════════════════════════════════════════════════════

    def scan_import_questions(self, scanned_files: list,
                              subject: str = "",
                              user_id: int = 0) -> dict:
        """
        扫描试卷 PNG → 直接入库（VisionModel 全权处理，不经主模型）。

        流程:
          1. OCRModel (deepseek-ocr/glm-ocr) 对每张 PNG 做 OCR → Markdown
          2. 将 PNG + MD 成对保存到 workspace/<user>/documents/scan_import_questions/<session>/
          3. VisionModel 结合 PNG 图片 + OCR 文本，一次性输出完整 JSON:
             - subject: 科目自动识别（无需主模型判断）
             - page_description: 整页图片描述
             - questions: 每题含题目原文/选项/参考答案/解析/题型/难度/标签/知识点/手写备注
          4. 解析 JSON → 批量入库到 question_bank（科目以 VisionModel 识别结果为准）
          5. 返回反馈给 LLM

        :param scanned_files: 文件路径列表 ["/path/page1.png", ...] 或对象列表
        :param subject: 学科代码，可留空；留空时由 VisionModel 从图片内容自动识别
        :param user_id: 用户 ID
        :return: {
            success, questions_found, questions_imported,
            subject, page_descriptions,
            questions: [{id, preview}],
            session_dir, page_errors, import_errors, feedback_text
        }
        """
        uid = user_id or 1

        # ── Step 0: 规范化输入 ──
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

        logger.info("scan_import_questions 开始: %d 文件, subject=%s, user_id=%d",
                     len(normalized), subject or "(自动识别)", uid)

        # ── Step 1: OCR 每张 PNG → Markdown ──
        from config import Config
        from models import OCRModel, VisionModel

        ocr = OCRModel()
        ocr_pages = []
        for item in normalized:
            fp = item["filepath"]
            data_url = VisionModel.encode_image(fp)
            try:
                md = ocr.ocr(data_url)
            except Exception as e:
                logger.warning("OCR 失败 %s: %s", item["filename"], e)
                md = ""
            ocr_pages.append({
                "filename": item["filename"],
                "filepath": fp,
                "data_url": data_url,
                "markdown": md,
            })
            logger.info("OCR 完成 %s: %d chars", item["filename"], len(md))

        # ── Step 2: 保存 PNG+MD 成对到工作区 ──
        from utils.workspace import get_workspace_manager
        wm = get_workspace_manager()
        session = datetime.now().strftime("scan_%Y%m%d_%H%M%S")
        session_dir = wm.user_subdir(uid, "documents") / "scan_import_questions" / session
        session_dir.mkdir(parents=True, exist_ok=True)

        saved_pairs = []
        for r in ocr_pages:
            base = os.path.splitext(r["filename"])[0]
            md_path = session_dir / f"{base}.md"
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(r["markdown"])
            saved_pairs.append({"png": r["filepath"], "md": str(md_path)})
            logger.info("保存 PNG+MD 对: %s ↔ %s", r["filename"], md_path)

        # ── Step 3: VisionModel 直接合成完整 JSON（科目+图片描述+题目）──
        if not Config.VISION_API_KEY:
            return {
                "success": False,
                "error": "VISION_API_KEY 未配置，请先设置视觉模型 API 密钥才能使用 scan_import_questions",
                "session_dir": str(session_dir),
            }

        vm = VisionModel()
        all_questions = []
        detected_subjects = {}
        page_descriptions = {}
        page_errors = []

        for r in ocr_pages:
            prompt = self._build_question_prompt(r["markdown"], subject)
            try:
                response = vm.ask(r["data_url"], prompt,
                                  max_tokens=8192, temperature=0.1)
            except Exception as e:
                page_errors.append(f"{r['filename']}: VisionModel 失败 - {e}")
                logger.error("VisionModel 提取失败 %s: %s", r["filename"], e)
                continue

            try:
                qs, page_subject, page_desc = self._parse_vision_page(response)
            except Exception as e:
                page_errors.append(f"{r['filename']}: JSON 解析失败 - {e}")
                logger.error("JSON 解析失败 %s: %s", r["filename"], e)
                continue

            for q in qs:
                q["_source_page"] = r["filename"]
            all_questions.extend(qs)
            if page_subject:
                detected_subjects[r["filename"]] = page_subject
            if page_desc:
                page_descriptions[r["filename"]] = page_desc
            logger.info("VisionModel 提取 %s: %d 道题, subject=%s",
                        r["filename"], len(qs), page_subject or "?")

        if not all_questions:
            return {
                "success": False,
                "error": "未能从扫描件中提取任何题目",
                "page_errors": page_errors,
                "session_dir": str(session_dir),
            }

        # ── Step 4: 入库（科目以 VisionModel 识别结果为准）──
        store = self._question_store
        if store is None:
            from question_bank.store import QuestionStore
            from db.question_bank import QuestionBankDBManager
            store = QuestionStore(db=QuestionBankDBManager())

        subject_name_map = {
            "math": "数学", "physics": "物理", "chemistry": "化学",
            "english": "英语", "chinese": "语文", "biology": "生物",
            "history": "历史", "geography": "地理", "politics": "政治",
        }
        detected_counts = {}
        for s in detected_subjects.values():
            detected_counts[s] = detected_counts.get(s, 0) + 1
        final_subject = subject or (max(detected_counts, key=detected_counts.get) if detected_counts else "unknown")
        subject_name = subject_name_map.get(final_subject, final_subject)
        default_subject = subject or "unknown"

        imported = []
        import_errors = []
        for q in all_questions:
            try:
                page_key = q.get("_source_page", "")
                q_subject = detected_subjects.get(page_key) or default_subject
                subject_id = self._resolve_subject_id(q_subject, store)
                type_id = self._resolve_type_id(
                    q.get("type_name", "解答题"),
                    q.get("subtype", ""),
                    store,
                )
                metadata = {
                    "source": "scan_import_questions",
                    "source_page": page_key,
                    "session": session,
                    "subject_detected": detected_subjects.get(page_key, ""),
                    "page_description": page_descriptions.get(page_key, ""),
                }
                notes = q.get("notes", "").strip()
                if notes:
                    metadata["handwritten_notes"] = notes

                qid = store.create_question({
                    "subject_id": subject_id,
                    "type_id": type_id,
                    "source": "scan_png",
                    "difficulty": q.get("difficulty", 3),
                    "content": q.get("content", ""),
                    "options": q.get("options", []),
                    "answer": q.get("answer", ""),
                    "explanation": q.get("explanation", ""),
                    "tags": q.get("tags", []),
                    "knowledge_points": q.get("knowledge_points", []),
                    "metadata": metadata,
                })
                preview = q.get("content", "")[:60].replace("\n", " ")
                imported.append({"question_id": qid, "preview": preview})
            except Exception as e:
                import_errors.append(str(e))
                logger.error("题目入库失败: %s", e)

        # ── Step 5: 反馈 ──
        feedback_parts = [
            f"导入了一道题, 科目: {subject_name}",
            f"共识别 {len(all_questions)} 道题，成功导入 {len(imported)} 道",
        ]
        if detected_subjects and not subject:
            feedback_parts.append(
                f"科目由视觉模型自动识别: {subject_name}"
            )
        if page_errors:
            feedback_parts.append(
                f"部分页面处理异常: {'; '.join(page_errors[:3])}"
            )
        if import_errors:
            feedback_parts.append(
                f"部分题目入库失败: {'; '.join(import_errors[:3])}"
            )
        if saved_pairs:
            feedback_parts.append(
                f"扫描件与OCR文本已保存至: {session_dir}"
            )

        logger.info("scan_import_questions 完成: 识别 %d 题, 入库 %d 题, subject=%s",
                     len(all_questions), len(imported), final_subject)

        return {
            "success": True,
            "questions_found": len(all_questions),
            "questions_imported": len(imported),
            "subject": final_subject,
            "page_descriptions": page_descriptions,
            "questions": imported,
            "session_dir": str(session_dir),
            "page_errors": page_errors,
            "import_errors": import_errors,
            "feedback_text": "\n".join(feedback_parts),
        }

    # ── 辅助方法 ──

    @staticmethod
    def _build_question_prompt(ocr_md: str, subject: str = "") -> str:
        """
        构建发给 VisionModel 的提示词。
        要求其综合图片 + OCR 文本，一次性输出完整 JSON：
        科目自动识别、整页图片描述、逐题结构，全部由视觉模型直接产出。
        """
        subject_hint = ""
        if subject:
            subject_hint = (
                "用户已指定科目：__SUBJECT__，请按此科目处理。\n"
            ).replace("__SUBJECT__", subject)

        # 用 replace 而非 f-string，避免 OCR 文本中的 { } 导致崩溃
        template = (
            "你是一个试卷题目提取专家，正在把扫描试卷导入题库。\n"
            "__SUBJECT_HINT__"
            "你同时能看到这一页的扫描图片和下方 OCR 文本。请**综合图片与 OCR**，"
            "直接输出一个 JSON 对象，格式如下：\n"
            "\n"
            "{\n"
            '  "subject": 科目代码（从 math/physics/chemistry/english/chinese/biology 中自动判断；无法判断填 "unknown"）,\n'
            '  "page_description": 整页图片的文字描述（表格/图形/实验装置等，用于补充题图）,\n'
            '  "questions": [每道题的 JSON 对象数组]\n'
            "}\n"
            "\n"
            "每道题字段：\n"
            "- content: 题目原文（如有图表，在括号中补充该图描述）\n"
            "- options: 选项列表，如[\"A. xxx\", \"B. xxx\"]；非选择题填 []\n"
            "- answer: 参考答案\n"
            "- explanation: 详细解析\n"
            "- type_name: \"选择题\"/\"填空题\"/\"解答题\"/\"判断题\"\n"
            "- subtype: \"单选\"/\"多选\"/\"填空\"/\"计算\"/\"证明\"/\"简答\"/\"判断\"\n"
            "- difficulty: 1-5 整数\n"
            "- tags: 字符串数组，如[\"代数\",\"函数\"]\n"
            "- knowledge_points: 知识点字符串数组\n"
            "- notes: 图片中的手写备注（无则填\"\"）\n"
            "\n"
            "--- OCR 文本开始 ---\n"
            "__OCR_MD__\n"
            "--- OCR 文本结束 ---\n"
            "\n"
            "只返回这一个 JSON 对象，不要包含其他任何内容。"
        )
        return (template
                .replace("__SUBJECT_HINT__", subject_hint)
                .replace("__OCR_MD__", ocr_md))

    @staticmethod
    def _parse_vision_page(text: str) -> tuple[list, str, str]:
        """
        解析 VisionModel 回复，兼容两种格式：
          - 包裹对象: {"subject":..., "page_description":..., "questions":[...]}
          - 纯数组: [...]
        返回 (questions, subject, page_description)
        """
        text = text.strip()
        if "```" in text:
            lines = text.split("\n")
            json_lines = []
            in_block = False
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("```"):
                    if in_block:
                        break
                    in_block = True
                    continue
                if in_block:
                    json_lines.append(line)
            text = "\n".join(json_lines)
            text = text.strip()
            if text.startswith("json"):
                text = text[4:].strip()
        result = json_mod.loads(text)
        if isinstance(result, dict):
            qs = result.get("questions") or result.get("items") or []
            if isinstance(qs, dict):
                qs = [qs]
            return (qs if isinstance(qs, list) else []), \
                   str(result.get("subject", "") or "").strip(), \
                   str(result.get("page_description", "") or "").strip()
        if isinstance(result, list):
            return result, "", ""
        return [], "", ""

    @staticmethod
    def _parse_vision_json(text: str) -> list[dict]:
        """从 VisionModel 回复中提取 JSON，确保返回列表。"""
        text = text.strip()
        if "```" in text:
            lines = text.split("\n")
            json_lines = []
            in_block = False
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("```"):
                    if in_block:
                        break
                    in_block = True
                    continue
                if in_block:
                    json_lines.append(line)
            text = "\n".join(json_lines)
            text = text.strip()
            if text.startswith("json"):
                text = text[4:].strip()
        result = json_mod.loads(text)
        if isinstance(result, dict):
            return [result]
        return result

    @staticmethod
    def _resolve_subject_id(code: str, store) -> int:
        """根据学科代码查找 subject_id。"""
        conn = store._db._get_connection()
        row = conn.execute(
            "SELECT subject_id FROM subjects WHERE code = ?", (code,)
        ).fetchone()
        if row:
            return row["subject_id"]
        row = conn.execute("SELECT subject_id FROM subjects LIMIT 1").fetchone()
        return row["subject_id"] if row else 1

    @staticmethod
    def _resolve_type_id(name: str, subtype: str, store) -> int:
        """根据题型名称和子类型查找或创建 type_id。"""
        conn = store._db._get_connection()
        row = conn.execute(
            "SELECT type_id FROM question_types WHERE name = ? AND subtype = ?",
            (name, subtype),
        ).fetchone()
        if row:
            return row["type_id"]
        if not subtype:
            row = conn.execute(
                "SELECT type_id FROM question_types WHERE name = ? LIMIT 1",
                (name,),
            ).fetchone()
            if row:
                return row["type_id"]
        cursor = conn.execute(
            "INSERT INTO question_types (name, subtype, scoring_mode) VALUES (?, ?, 'exact')",
            (name, subtype),
        )
        conn.commit()
        return cursor.lastrowid
