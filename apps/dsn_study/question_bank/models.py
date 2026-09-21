from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Subject:
    subject_id: int = 0
    name: str = ""
    code: str = ""
    icon: str = ""
    typical_score: int = 100
    exam_duration: int = 120
    is_active: bool = True


@dataclass
class QuestionType:
    type_id: int = 0
    name: str = ""
    subtype: str = ""
    scoring_mode: str = "exact"


@dataclass
class Question:
    question_id: int = 0
    subject_id: int = 0
    type_id: int = 0
    source: str = ""
    difficulty: int = 3
    content: str = ""
    options: str = "[]"
    answer: str = ""
    explanation: str = ""
    tags: str = "[]"
    knowledge_points: str = "[]"
    metadata: str = "{}"
    version: int = 1


@dataclass
class ErrorLog:
    log_id: int = 0
    user_id: int = 0
    question_id: int = 0
    attempt_count: int = 1
    user_answer: str = ""
    error_type: str = ""
    error_reason: str = ""
    mastered: bool = False


@dataclass
class ExamPaper:
    paper_id: int = 0
    user_id: int = 0
    title: str = ""
    subject_id: int = 0
    difficulty: int = 3
    question_ids: str = "[]"
    total_score: int = 100
    time_limit_min: int = 120
    source: str = "composed"
    status: str = "draft"


@dataclass
class ExamResult:
    result_id: int = 0
    exam_id: int = 0
    user_id: int = 0
    answers: str = "{}"
    score: float = 0.0
    max_score: float = 100.0
    duration_sec: int = 0
    details: str = "{}"


@dataclass
class ExamSession:
    session_id: str = ""
    user_id: int = 0
    paper_id: int = 0
    status: str = "idle"
    config: str = "{}"
    answers: str = "{}"
    score: Optional[float] = None
    max_score: Optional[float] = None
    time_limit_sec: Optional[int] = None
    remaining_sec: Optional[int] = None
    auto_submitted: bool = False


@dataclass
class SubjectTemplate:
    template_id: int = 0
    name: str = ""
    description: str = ""
    content: str = ""
    is_builtin: bool = False
