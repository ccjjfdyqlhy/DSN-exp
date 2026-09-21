# skills/builtin/doc_to_questions/tools/doc_to_questions.py
# 文档→题库录入工具 — 从 .hmd / 原始文本中提取题目并入库

from __future__ import annotations

import logging

logger = logging.getLogger("skill.doc_to_questions")


class DocToQuestionsTool:
    """
    文档→题库录入工具。

    AI 通过 <tool>{"skill":"doc_to_questions","tool":"process_hmd",...}</tool>
    或 <tool>{"skill":"doc_to_questions","tool":"process_text",...}</tool> 调用。

    依赖注入:
        self._pipeline : ScannerPipeline — 由 engine.py 在初始化时注入
    """

    def __init__(self):
        self._pipeline = None

    def process_hmd(self, hmd_path: str, subject_code: str = "math",
                    user_id: int = 1) -> dict:
        """
        从 .hmd 扫描文档中提取题目并录入题库。

        1. 读取 .hmd 中的 OCR 文本 (mdA) 和布局文本 (mdB)
        2. 调用 LLM 将文本拆解为结构化题目
        3. 逐题存入 question_bank

        :param hmd_path: .hmd 文件路径（来自 document.read_hmd）
        :param subject_code: 学科代码 (math/physics/chemistry/english/chinese/biology)
        :param user_id: 用户 ID
        :return: {success, questions_found, questions_added, error?}
        """
        if not self._pipeline:
            return {"success": False, "error": "题库管线未就绪，无法处理"}

        try:
            from document.hmd import HmdClient
            data = HmdClient.read_hmd(hmd_path)
        except Exception as e:
            logger.error("读取 .hmd 失败 %s: %s", hmd_path, e)
            return {"success": False, "error": f"读取 .hmd 失败: {e}"}

        texts = []
        mda = (data.get("mda") or "").strip()
        if mda:
            texts.append(mda)
        mdb = (data.get("mdb") or "").strip()
        if mdb:
            texts.append(mdb)

        if not texts:
            return {"success": False, "error": ".hmd 文件中未找到文本内容"}

        combined = "\n\n".join(texts)
        logger.info("process_hmd: %s → %d 字符 (user_id=%d, subject=%s)",
                     hmd_path, len(combined), user_id, subject_code)

        return self._process(combined, subject_code, user_id)

    def process_text(self, text: str, subject_code: str = "math",
                     user_id: int = 1) -> dict:
        """
        从原始文本中提取题目并录入题库。

        :param text: 包含题目的文本（OCR 结果、粘贴文本等）
        :param subject_code: 学科代码
        :param user_id: 用户 ID
        :return: {success, questions_found, questions_added, error?}
        """
        if not self._pipeline:
            return {"success": False, "error": "题库管线未就绪，无法处理"}

        text = text.strip()
        if not text:
            return {"success": False, "error": "输入文本为空"}

        logger.info("process_text: %d 字符 (user_id=%d, subject=%s)",
                     len(text), user_id, subject_code)

        return self._process(text, subject_code, user_id)

    def _process(self, text: str, subject_code: str, user_id: int) -> dict:
        try:
            result = self._pipeline.process_text(
                text=text,
                user_id=user_id,
                subject_code=subject_code,
            )
            return {
                "success": True,
                "questions_found": result.get("questions_found", 0),
                "questions_added": result.get("questions_added", 0),
                "errors": result.get("errors", []),
            }
        except Exception as e:
            logger.exception("提取题目失败: %s", e)
            return {"success": False, "error": f"提取题目失败: {e}"}
