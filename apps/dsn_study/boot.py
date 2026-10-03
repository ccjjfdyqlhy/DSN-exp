# apps/dsn_study/boot.py
# DSN 学习特化应用 — 启动引导（对照 apps/dsn/boot.py 的 harness 标准装配形态）。
#
# 装配顺序:
#   Flask + Config + 日志
#   → harness Runtime + Settings（bind_dsn_study_settings）
#   → ModelProviderRegistry（openai / lmstudio / llamacpp）
#   → 本地认证垫片 + 题库主库（12 张题库表 + plan 3 表 + timetable 3 表 + async_tasks）
#   → 学习子系统栈（QuestionStore/TemplateManager/ExamEngine+Scorer/
#     GraphStore+GraphEngine+Builder+Matcher/ScannerPipeline/TimetableStore/
#     AsyncTaskStore/PlanEngine）
#   → SkillRegistry + SkillManager（扫描 builtin 目录 + 按技能注入依赖）
#   → AgentRuntime（技能工具桥接进 harness ToolRegistry + 技能提示词聚合）
#   → StudyEngine 门面（对话 + 学习上下文注入）
#   → AppBundleRegistry + FlaskGateway 挂载蓝图

from __future__ import annotations

import logging
import os
import uuid
from logging.handlers import RotatingFileHandler
from typing import Optional

from flask import Flask

from harness import AppBundleRegistry, Runtime, Settings
from harness import AgentRuntime
from harness.gateway import FlaskGateway
from harness.models import (
    LMStudioChat,
    LlamaCppChat,
    ModelProviderRegistry,
    OpenAICompatClient,
)

from apps.dsn_study.config import Config
from apps.dsn_study.settings import bind_dsn_study_settings
from apps.dsn_study.auth import LocalAuthManager
from apps.dsn_study.engine_support import LLMService, StudyPipeline

logger = logging.getLogger("boot")

DEFAULT_SYSTEM_PROMPT = (
    "你是一名专业的AI学习助手，擅长解题、组卷、模拟考试、错题归纳、学习计划管理"
    "与知识图谱梳理。请用清晰明了的中文回答。"
)

# ── StudyEngine 门面 ──

class StudyEngine:
    """学习特化引擎：AgentLoop 对话 + 学习领域组件 + 上下文注入。"""

    def __init__(self, *, agent: AgentRuntime, chat_client, llm: LLMService,
                 db_mgr, question_store, template_manager, composer, scorer,
                 exam_engine, graph_store, graph_engine, kg_builder, kg_matcher,
                 scanner_pipeline, timetable_store, async_task_store, plan_engine,
                 skill_registry, skill_manager, workspace=None):
        self.agent = agent
        self.chat_client = chat_client
        self.llm = llm
        self.db_mgr = db_mgr
        self.question_store = question_store
        self.template_manager = template_manager
        self.composer = composer
        self.scorer = scorer
        self.exam_engine = exam_engine
        self.graph_store = graph_store
        self.graph_engine = graph_engine
        self.kg_builder = kg_builder
        self.kg_matcher = kg_matcher
        self.scanner_pipeline = scanner_pipeline
        self.timetable_store = timetable_store
        self.async_task_store = async_task_store
        self.plan_engine = plan_engine
        self.skill_registry = skill_registry
        self.skill_manager = skill_manager
        self.workspace = workspace
        # 复用同一会话，使 REPL/HTTP 多轮对话共享历史
        self.session_id = f"study-{uuid.uuid4().hex[:12]}"
        # 旧管线代码兼容别名（api/scan.py 期望 engine.pipeline）
        self.pipeline = StudyPipeline(chat_client, system_prompt=DEFAULT_SYSTEM_PROMPT)

    # ── 学习上下文注入（对齐参考实现 4 个 PRE_PROCESS 插件的职责） ──

    def _build_preamble(self, user_id: int) -> str:
        blocks: list[str] = []

        try:  # 今日计划（PlanPlugin）
            summary = self.plan_engine.daily_summary(user_id)
            if summary["total"]:
                blocks.append(
                    f"[今日计划] {summary['done']}/{summary['total']} 已完成，"
                    f"{summary['pending']} 待办、{summary['skipped']} 已跳过。"
                    + "；".join(f"{t['title']}({t['status']})" for t in summary["tasks"][:8])
                )
        except Exception:
            pass

        try:  # 到期复习（KnowledgeGraphPlugin）
            due = self.graph_store.get_due_reviews(user_id)
            if due:
                names = [d.get("name") or d.get("kp_code", "") for d in due[:6]]
                blocks.append(f"[到期复习] {len(due)} 个知识点待复习：{', '.join(filter(None, names))}")
        except Exception:
            pass

        try:  # 错题概况（QuestionBankPlugin）
            total_errors = self.question_store.get_total_errors(user_id)
            if total_errors:
                blocks.append(f"[错题本] 累计 {total_errors} 道错题待巩固")
        except Exception:
            pass

        if not blocks:
            return ""
        return "\n".join(f"(系统上下文·仅供你参考，不要复述) {b}" for b in blocks)

    # ── 对话 ──

    def chat(self, message: str, user_id: int = 1,
             session_id: Optional[str] = None) -> str:
        preamble = self._build_preamble(user_id)
        full = f"{preamble}\n\n{message}" if preamble else message
        result = self.agent.run_with_tools(full, session_id=session_id or self.session_id)
        return result.reply

    def __repr__(self):
        return (f"<StudyEngine tools={len(self.skill_registry.list_active_tools())} "
                f"session={self.session_id}>")


# ── 模块级单例 ──
app: Optional[Flask] = None
engine: Optional[StudyEngine] = None


# ── 日志 ──

def setup_logging(app: Flask):
    log_dir = app.config.get("LOG_DIR", "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "dsn_study.log")
    level = getattr(logging, str(app.config.get("LOG_LEVEL", "INFO")).upper(), logging.INFO)
    handler = RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    root = logging.getLogger()
    for h in root.handlers[:]:
        root.removeHandler(h)
    root.addHandler(handler)
    root.addHandler(console)
    root.setLevel(level)


# ── 模型 ──

def _make_chat(model_type: str):
    if model_type in ("llamacpp", "llama_cpp", "gguf"):
        return LlamaCppChat(
            base_url=Config.LLAMACPP_BASE_URL,
            model_name=Config.MAIN_MODEL_NAME,
            temperature=getattr(Config, "LLAMACPP_TEMPERATURE", 0.7),
            max_tokens=getattr(Config, "LLAMACPP_MAX_TOKENS", 4096),
            timeout=getattr(Config, "LLAMACPP_TIMEOUT", 300),
        )
    if model_type in ("fast", "lmstudio"):
        return LMStudioChat(
            base_url=Config.LMSTUDIO_BASE_URL,
            model_name=Config.MAIN_MODEL_NAME,
            temperature=getattr(Config, "LMSTUDIO_TEMPERATURE", 0.7),
            max_tokens=getattr(Config, "LMSTUDIO_MAX_TOKENS", 4096),
            timeout=getattr(Config, "LMSTUDIO_TIMEOUT", 300),
        )
    return OpenAICompatClient(
        api_key=Config.OPENAI_API_KEY,
        base_url=Config.OPENAI_API_BASE,
        model=Config.MAIN_MODEL_NAME,
    )


# ── 技能依赖注入 ──

def _build_skill_dep_map(c) -> dict[str, dict]:
    """skill 名 → 工具实例属性注入表。"""
    return {
        "question_bank": dict(_store=c["question_store"], _tm=c["template_manager"],
                              _models=c["llm"]),
        "knowledge_graph": dict(_store=c["graph_store"], _engine=c["graph_engine"],
                                _matcher=c["kg_matcher"], _models=c["llm"],
                                _question_store=c["question_store"]),
        "exam_sim": dict(_engine=c["exam_engine"], _scorer=c["scorer"],
                         _store=c["question_store"], _models=c["llm"]),
        "exam_review": dict(_store=c["question_store"], _db=c["db_mgr"]),
        "batch_import": dict(_store=c["question_store"], _tm=c["template_manager"]),
        "quick_question": dict(_store=c["question_store"], _tm=c["template_manager"]),
        "text_extract": dict(_store=c["question_store"], _tm=c["template_manager"],
                             _models=c["llm"]),
        "quest_from_image": dict(_store=c["question_store"], _tm=c["template_manager"]),
        "doc_to_questions": dict(_pipeline=c["scanner_pipeline"]),
        "question_print": dict(_store=c["question_store"], _tm=c["template_manager"]),
        "plan": {},  # PlanTools 经 get_plan_db() 全局取库
        "study_timetable": {},  # StudyTimetableTool 经 get_study_db() 全局取库
    }


def _bridge_tools_to_agent(agent: AgentRuntime, skill_registry, skill_loader) -> int:
    """把 SkillRegistry 里的全部工具桥接为 harness AgentLoop 工具。"""
    count = 0
    for key, spec in skill_registry._tool_specs.items():
        skill_name, tool_name = key.split(".", 1)
        tool_spec_obj = spec.get("_tool_spec_obj")
        parameters = {"type": "object", "properties": {}}
        if tool_spec_obj is not None:
            try:
                schema = skill_loader.build_function_schema(skill_name, tool_spec_obj)
                parameters = schema["function"]["parameters"]
            except Exception:
                logger.warning("工具 %s 参数 schema 生成失败，使用空参", key, exc_info=True)

        def _handler(_sk=skill_name, _tl=tool_name, **kwargs):
            return skill_registry.call_tool(_sk, _tl, kwargs)

        agent.register_tool(key, spec.get("description", ""), _handler,
                            parameters=parameters)
        count += 1
    return count


# ── 启动 ──

def create_application() -> Flask:
    """初始化所有组件并装配 AppBundle，返回 Flask app。"""
    global app, engine

    flask_app = Flask("dsn_study")
    flask_app.config.from_object(Config)
    setup_logging(flask_app)

    # ── Harness Runtime + Settings ──
    runtime = Runtime(name="dsn_study")
    settings = Settings()
    runtime.register("settings", settings)
    runtime.set_default()
    bind_dsn_study_settings(settings)

    # ── 模型提供商注册表 ──
    provider = ModelProviderRegistry()
    provider.register_chat("openai", lambda: _make_chat("openai"))
    provider.register_chat("lmstudio", lambda: _make_chat("lmstudio"))
    provider.register_chat("llamacpp", lambda: _make_chat("llamacpp"))
    runtime.register("model_provider", provider)

    model_type = str(Config.MAIN_MODEL_TYPE).lower()
    if model_type not in ("openai", "lmstudio", "llamacpp", "llama_cpp", "gguf", "fast"):
        logger.warning("未知 MAIN_MODEL_TYPE=%s，回退 openai", model_type)
        model_type = "openai"
    chat_client = provider.get_chat_client(model_type)
    flask_app.logger.info("主模型: %s (%s)", Config.MAIN_MODEL_NAME, model_type)

    # ── 认证垫片 ──
    auth = LocalAuthManager()
    flask_app.config["AUTH_MANAGER"] = auth

    # ── 数据库（题库主库承载全部学习域表） ──
    from apps.dsn_study.db.question_bank import QuestionBankDBManager
    from apps.dsn_study.db.plan_store import set_plan_db
    from apps.dsn_study.db.study_timetable import set_study_db

    db_path = os.path.abspath(Config.QUESTION_BANK_DB_PATH)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    db_mgr = QuestionBankDBManager(db_path=db_path)
    set_plan_db(db_mgr)
    set_study_db(db_mgr)
    runtime.register("db", db_mgr)

    # ── 学习子系统栈 ──
    from apps.dsn_study.question_bank.store import QuestionStore
    from apps.dsn_study.question_bank.composer import ExamComposer
    from apps.dsn_study.question_bank.template_manager import SubjectTemplateManager
    from apps.dsn_study.question_bank.scanner_pipeline import ScannerPipeline
    from apps.dsn_study.exam_sim.engine import ExamEngine
    from apps.dsn_study.exam_sim.scorer import ExamScorer
    from apps.dsn_study.knowledge_graph.graph_store import GraphStore
    from apps.dsn_study.knowledge_graph.graph_engine import GraphEngine
    from apps.dsn_study.knowledge_graph.builder import KnowledgeGraphBuilder
    from apps.dsn_study.knowledge_graph.matcher import KnowledgeMatcher
    from apps.dsn_study.db.study_timetable import StudyTimetableStore
    from apps.dsn_study.async_task_store import AsyncTaskStore
    from apps.dsn_study.db.plan_store import PlanStore
    from apps.dsn_study.db.plan_engine import PlanEngine

    llm = LLMService(chat_client)
    question_store = QuestionStore(db_mgr)
    template_manager = SubjectTemplateManager(db_mgr)
    composer = ExamComposer(question_store=question_store)
    scorer = ExamScorer(question_store=question_store, models_plugin=llm)
    exam_engine = ExamEngine(db=db_mgr, question_store=question_store, scorer=scorer)
    graph_store = GraphStore(db_mgr)
    graph_engine = GraphEngine(graph_store, models_plugin=llm)
    kg_builder = KnowledgeGraphBuilder(graph_store, models_plugin=llm)
    kg_matcher = KnowledgeMatcher(graph_store, models_plugin=llm)
    scanner_pipeline = ScannerPipeline(question_store=question_store, models_plugin=llm)
    timetable_store = StudyTimetableStore(db_mgr)
    async_task_store = AsyncTaskStore(db=db_mgr)
    plan_engine = PlanEngine(PlanStore(db_mgr))

    try:
        template_manager.init_builtin_templates()
        if not template_manager.has_subjects():
            # 与参考实现一致：全新库自动应用高考 6 科模板，开箱即用
            template_manager.apply_template("6_subjects")
            logger.info("首次启动: 已应用默认科目模板 6_subjects")
    except Exception:
        logger.warning("内置科目模板初始化失败", exc_info=True)

    # ── 工作区 ──
    try:
        from apps.dsn_study.workspace import init_workspace_manager
        workspace = init_workspace_manager(Config.WORKSPACE_DIR)
    except Exception:
        workspace = None

    # ── 技能系统 ──
    from apps.dsn_study.skills.registry import SkillRegistry
    from apps.dsn_study.skills.manager import SkillManager
    from apps.dsn_study.skills.loader import SkillLoader

    skill_registry = SkillRegistry()
    app_root = os.path.dirname(__file__)
    skill_dirs = [os.path.join(app_root, "skills", "builtin")]
    custom_dir = os.path.join(app_root, "skills", "custom")
    if os.path.isdir(custom_dir):
        skill_dirs.append(custom_dir)
    skill_manager = SkillManager(skill_dirs, skill_registry)
    loaded_skills = skill_manager.scan_and_load()
    logger.info("技能加载完成: %d 个", loaded_skills)

    c = {
        "db_mgr": db_mgr, "llm": llm, "question_store": question_store,
        "template_manager": template_manager, "composer": composer, "scorer": scorer,
        "exam_engine": exam_engine, "graph_store": graph_store,
        "graph_engine": graph_engine, "kg_builder": kg_builder, "kg_matcher": kg_matcher,
        "scanner_pipeline": scanner_pipeline, "timetable_store": timetable_store,
        "async_task_store": async_task_store, "plan_engine": plan_engine,
    }
    dep_map = _build_skill_dep_map(c)
    for skill_name in list(skill_registry._active_skills):
        deps = dep_map.get(skill_name)
        if deps and not skill_registry.inject_dependencies(skill_name, **deps):
            logger.warning("技能 %s 依赖注入未命中任何工具属性", skill_name)

    # ── Agent（技能工具桥接 + 提示词聚合） ──
    skill_prompts = skill_registry.get_all_skill_prompts()
    system_prompt = (DEFAULT_SYSTEM_PROMPT + "\n\n" + skill_prompts).strip()
    agent = AgentRuntime(
        chat_client,
        name="dsn-study-agent",
        system_prompt=system_prompt,
        max_steps=int(Config.AGENT_MAX_STEPS),
    )
    bridged = _bridge_tools_to_agent(agent, skill_registry, SkillLoader())
    logger.info("已桥接 %d 个技能工具到 AgentLoop", bridged)

    # ── 引擎门面 ──
    engine = StudyEngine(
        agent=agent, chat_client=chat_client,
        skill_registry=skill_registry, skill_manager=skill_manager,
        workspace=workspace, **c,
    )
    runtime.register("engine", engine)
    flask_app.config["ENGINE"] = engine

    # ── 蓝图初始化 + 装配 ──
    from apps.dsn_study.api.scan import scan_bp, init_scan_api
    from apps.dsn_study.api.study_timetable import study_bp, init_study_timetable_api
    from apps.dsn_study.api.plan import plan_bp, init_plan_api
    from apps.dsn_study.api.async_tasks import async_task_bp, init_async_tasks_api
    from apps.dsn_study.api.chat import chat_bp, init_chat_api

    init_scan_api(auth_manager=auth)
    init_study_timetable_api(db_mgr, auth)
    init_plan_api(db_mgr, auth)
    init_async_tasks_api(auth)
    init_chat_api(auth)

    blueprints = {
        "scan": scan_bp,
        "study_timetable": study_bp,
        "plan": plan_bp,
        "async_tasks": async_task_bp,
        "chat": chat_bp,
    }

    from apps.dsn_study.bundles import make_dsn_study_bundles

    gateway = FlaskGateway(flask_app)
    bundles = make_dsn_study_bundles(blueprints)
    bundle_registry = AppBundleRegistry(runtime)
    for bundle in bundles:
        bundle_registry.add(bundle)
    bundle_registry.install_all()
    for bundle in bundles:
        bundle.register_routes(gateway)
    bundle_registry.start_all()

    flask_app.config["BUNDLE_REGISTRY"] = bundle_registry
    flask_app.config["GATEWAY"] = gateway

    app = flask_app
    flask_app.logger.info("dsn_study 装配完成: %s", engine)
    return flask_app


def get_engine() -> StudyEngine:
    """懒加载入口：REPL / SDK 调用方无需手动建 Flask app。"""
    if engine is None:
        create_application()
    assert engine is not None
    return engine
