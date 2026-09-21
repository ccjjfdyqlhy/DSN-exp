# apps/dsn_study/app.py
# DsnStudyAgent — 基于 harness 的学习特化 Agent 应用。
#
# 整合题库管理（question_bank）、模拟考试系统（exam_sim）、考点知识图谱（knowledge_graph）
# 并挂载 Harness 运行时调度器。

from __future__ import annotations

import os
import logging
from typing import Optional

from harness import AgentRuntime
from harness.agent import ThreeZoneContext
from harness.models import ChatMessage, IChatClient, IEmbeddingClient, OpenAICompatClient
from harness.observability import UsageTracker
from harness.store import SessionStore
from apps.dsn_study.config import Config

logger = logging.getLogger(__name__)


def build_default_client() -> OpenAICompatClient:
    api_key = os.environ.get("OPENAI_API_KEY") or Config.OPENAI_API_KEY
    api_base = os.environ.get("OPENAI_API_BASE") or Config.OPENAI_API_BASE
    model = os.environ.get("MAIN_MODEL_NAME") or Config.MAIN_MODEL_NAME
    return OpenAICompatClient(
        api_key=api_key,
        base_url=api_base,
        model=model,
    )


class DsnStudyAgent:
    """学习特化 Agent 门面类。"""

    def __init__(
        self,
        client: Optional[IChatClient] = None,
        *,
        embedding_client: Optional[IEmbeddingClient] = None,
        system_prompt: str = "你是一名专业的AI学习助手，擅长解题、组卷、模拟考试、错题归纳与知识图谱梳理。请用清晰明了的中文回答。",
        max_steps: int = 10,
    ):
        self.client = client or build_default_client()
        self.agent = AgentRuntime(
            self.client,
            embedding_client=embedding_client,
            name="dsn-study-agent",
            system_prompt=system_prompt,
            max_steps=max_steps,
        )
        self.ctx = ThreeZoneContext(system_prompt)
        self.usage = UsageTracker()
        self.session_store: Optional[SessionStore] = None

        # 延迟/安全初始化题库与学习组件（避免启动崩溃）
        self._init_study_modules()

    def _init_study_modules(self) -> None:
        """初始化题库、模考与图谱底层。"""
        try:
            from apps.dsn_study.db.question_bank import QuestionBankDBManager
            from apps.dsn_study.question_bank.store import QuestionStore
            from apps.dsn_study.question_bank.template_manager import SubjectTemplateManager
            from apps.dsn_study.exam_sim.engine import ExamEngine
            from apps.dsn_study.knowledge_graph.graph_store import GraphStore

            qb_db = os.environ.get("QUESTION_BANK_DB_PATH", Config.QUESTION_BANK_DB_PATH)
            os.makedirs(os.path.dirname(os.path.abspath(qb_db)), exist_ok=True)

            self.db_mgr = QuestionBankDBManager(db_path=qb_db)
            self.qb_store = QuestionStore(self.db_mgr)
            self.template_mgr = SubjectTemplateManager(self.db_mgr)
            self.exam_engine = ExamEngine(db=self.db_mgr, question_store=self.qb_store)
            self.kg_store = GraphStore(self.db_mgr)
        except Exception as e:
            logger.warning(f"初始化部分学习子系统失败 (可在对话中继续使用核心LLM能力): {e}")

    def enable_persistence(self, db_path: str = ":memory:") -> "DsnStudyAgent":
        self.session_store = SessionStore(db_path=db_path)
        self.session_store.create_session()
        return self

    def register_tool(self, name: str, description: str, handler, parameters=None):
        return self.agent.register_tool(name, description, handler, parameters)

    def chat(self, message: str) -> str:
        """执行一次带学习工具循环的对话。"""
        self.ctx.add_user(message)
        result = self.agent.run_with_tools(message)
        self.ctx.add_assistant(ChatMessage.assistant(result.reply))
        return result.reply

    @property
    def runtime(self):
        return self.agent.runtime
