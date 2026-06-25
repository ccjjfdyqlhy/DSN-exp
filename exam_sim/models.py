from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ExamConfig:
    subject: str = ""
    paper_id: Optional[int] = None
    question_ids: list[int] = field(default_factory=list)
    time_limit_min: int = 120
    total_score: int = 100
    difficulty: int = 3
    title: str = "未命名考试"
    shuffle: bool = True
    show_result_immediately: bool = False


@dataclass
class ExamSession:
    session_id: str = ""
    user_id: int = 0
    paper_id: Optional[int] = None
    status: str = "idle"
    config: str = "{}"
    answers: str = "{}"
    score: Optional[float] = None
    max_score: Optional[float] = None
    started_at: Optional[str] = None
    submitted_at: Optional[str] = None
    time_limit_sec: Optional[int] = None
    remaining_sec: Optional[int] = None
    auto_submitted: bool = False


@dataclass
class ExamReport:
    session_id: str = ""
    user_id: int = 0
    score: float = 0.0
    max_score: float = 0.0
    correct_count: int = 0
    total_count: int = 0
    duration_sec: int = 0
    details: list[dict] = field(default_factory=list)
    weak_kps: list[dict] = field(default_factory=list)
    recommendations: list[int] = field(default_factory=list)
