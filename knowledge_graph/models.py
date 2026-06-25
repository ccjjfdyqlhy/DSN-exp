from dataclasses import dataclass, field
from typing import Optional


@dataclass
class KnowledgeNode:
    kp_code: str = ""
    subject: str = ""
    name: str = ""
    aliases: list[str] = field(default_factory=list)
    level: int = 0
    parent_code: Optional[str] = None
    description: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class KnowledgeEdge:
    id: int = 0
    source: str = ""
    target: str = ""
    edge_type: str = "related"
    weight: float = 1.0
    description: str = ""


@dataclass
class UserKnowledgeState:
    id: int = 0
    user_id: int = 0
    kp_code: str = ""
    total_attempts: int = 0
    correct_attempts: int = 0
    correct_rate: float = 0.0
    last_practiced: Optional[str] = None
    confidence: float = 0.0
    next_review_at: Optional[str] = None
