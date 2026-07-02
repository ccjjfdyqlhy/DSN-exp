import json
import logging

logger = logging.getLogger("skill.batch_import")


class BatchImportTool:

    def __init__(self):
        self._store = None
        self._tm = None

    def import_questions(self, questions: list, subject: str = None,
                         mode: str = "commit") -> dict:
        if not self._store or not self._tm:
            return {"success": False, "error": "题库系统未就绪"}

        if not questions:
            return {"success": False, "error": "题目列表为空"}

        parsed = []
        errors = []

        for i, q in enumerate(questions):
            try:
                subj = q.get("subject", subject)
                if not subj:
                    errors.append({"index": i, "error": "缺少学科 (subject)"})
                    continue

                subject_info = self._tm.get_subject_by_code(subj)
                if not subject_info:
                    errors.append({"index": i, "error": f"学科 {subj} 不存在"})
                    continue

                type_name = q.get("type_name", "解答题")
                subtype = q.get("subtype", "")
                type_id = self._tm.get_type_id(type_name, subtype)
                if not type_id:
                    type_id = self._tm.get_type_id(type_name)

                parsed.append({
                    "subject_id": subject_info["subject_id"],
                    "type_id": type_id or 1,
                    "source": "batch_import",
                    "difficulty": q.get("difficulty", 3),
                    "content": q.get("content", ""),
                    "options": q.get("options", []),
                    "answer": q.get("answer", ""),
                    "explanation": q.get("explanation", ""),
                    "tags": q.get("tags", []),
                    "knowledge_points": q.get("knowledge_points", []),
                })
            except Exception as e:
                errors.append({"index": i, "error": str(e)})

        if mode == "dry_run":
            return {
                "success": True,
                "mode": "dry_run",
                "total": len(questions),
                "parsed_count": len(parsed),
                "error_count": len(errors),
                "preview": [
                    {
                        "index": i,
                        "content": q.get("content", "")[:120],
                        "type_name": q.get("type_name", "解答题"),
                        "difficulty": q.get("difficulty", 3),
                        "subject": q.get("subject", subject),
                    }
                    for i, q in enumerate(questions)
                    if i < len(parsed)
                ],
                "errors": errors,
            }

        added_ids = []
        for data in parsed:
            try:
                qid = self._store.create_question(data)
                added_ids.append(qid)
            except Exception as e:
                errors.append({"error": f"入库失败: {e}", "content_preview": data.get("content", "")[:80]})

        logger.info("批量导入: 成功 %d 题, 失败 %d 题", len(added_ids), len(errors))
        return {
            "success": len(added_ids) > 0,
            "mode": "commit",
            "total": len(questions),
            "added_count": len(added_ids),
            "added_ids": added_ids,
            "error_count": len(errors),
            "errors": errors,
        }
