import json
import random
import logging

logger = logging.getLogger("ExamComposer")


class ComposeParams:
    def __init__(
        self,
        subject: str,
        knowledge_points: list[str] = None,
        difficulty_dist: dict = None,
        type_dist: dict = None,
        count: int = 10,
        exclude_recent: int = 5,
    ):
        self.subject = subject
        self.knowledge_points = knowledge_points or []
        self.difficulty_dist = difficulty_dist or {1: 0.1, 2: 0.2, 3: 0.4, 4: 0.2, 5: 0.1}
        self.type_dist = type_dist or {"选择题": 0.4, "填空题": 0.2, "解答题": 0.4}
        self.count = count
        self.exclude_recent = exclude_recent


class ExamComposer:

    def __init__(self, question_store=None):
        self._store = question_store

    def compose(self, params: ComposeParams) -> dict:
        all_questions = self._store.search_questions(
            subject=params.subject,
            limit=500,
        )

        if not all_questions:
            return {
                "success": False,
                "error": f"学科 {params.subject} 没有可用题目",
            }

        # 按知识点过滤
        if params.knowledge_points:
            filtered = []
            for q in all_questions:
                kps = q.get("knowledge_points", [])
                if isinstance(kps, str):
                    try:
                        kps = json.loads(kps)
                    except Exception:
                        kps = []
                if any(kp in str(kps) for kp in params.knowledge_points):
                    filtered.append(q)
            if filtered:
                all_questions = filtered

        # 按难度分组
        by_difficulty = {1: [], 2: [], 3: [], 4: [], 5: []}
        for q in all_questions:
            d = q.get("difficulty", 3)
            if d in by_difficulty:
                by_difficulty[d].append(q)

        # 按题型分组
        by_type = {}
        for q in all_questions:
            tname = q.get("type_name", "解答题")
            if tname not in by_type:
                by_type[tname] = []
            by_type[tname].append(q)

        selected = []
        used_ids = set()

        # 按难度分布选
        for diff, ratio in params.difficulty_dist.items():
            count = max(1, int(params.count * ratio))
            pool = by_difficulty.get(diff, [])
            if pool:
                picks = random.sample(pool, min(count, len(pool)))
                for q in picks:
                    if q["question_id"] not in used_ids and len(selected) < params.count:
                        selected.append(q)
                        used_ids.add(q["question_id"])

        # 如果选不够，从所有题目中补充
        if len(selected) < params.count:
            remaining = [q for q in all_questions if q["question_id"] not in used_ids]
            extra = random.sample(remaining, min(params.count - len(selected), len(remaining)))
            selected.extend(extra)

        # 随机打乱顺序
        random.shuffle(selected)

        # 计算总分和预估时长
        total_score = len(selected) * 10
        estimated_min = len(selected) * 3

        return {
            "success": True,
            "questions": selected,
            "total_score": total_score,
            "estimated_min": estimated_min,
            "question_ids": [q["question_id"] for q in selected],
        }

    def compose_by_diff(self, subject: str, difficulty: int = 3, count: int = 10) -> dict:
        return self.compose(ComposeParams(
            subject=subject,
            difficulty_dist={difficulty: 1.0},
            count=count,
        ))

    def compose_adaptive(self, user_id: int, subject: str, count: int = 10) -> dict:
        """自适应组卷：优先挑选用户错题相关的知识点"""
        if not self._store:
            return {"success": False, "error": "QuestionStore 未注入"}

        errors = self._store.get_error_logs(user_id, subject=subject)
        kps = set()
        for e in errors:
            qid = e.get("question_id")
            if not qid:
                continue
            q = self._store.get_question(qid)
            if q:
                kps_list = q.get("knowledge_points", [])
                if isinstance(kps_list, list):
                    for kp in kps_list:
                        kps.add(str(kp))

        params = ComposeParams(
            subject=subject,
            knowledge_points=list(kps)[:10] if kps else None,
            count=count,
        )
        return self.compose(params)
