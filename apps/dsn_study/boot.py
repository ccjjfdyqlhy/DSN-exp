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
import threading
import uuid
from logging.handlers import RotatingFileHandler
from typing import Optional

from flask import Flask

from harness import AppBundleRegistry, Runtime, Settings
from harness import AgentRuntime
from infra.gateway import FlaskGateway
from infra.models import (
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
                 skill_registry, skill_manager, workspace=None,
                 task_manager=None, memory_system=None, cache_engine=None):
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
        # 任务管理器（提醒/习惯/倒计时/日计划/正计时；TASK_MANAGER_ENABLED=false 时为 None）
        self.task_manager = task_manager
        # 记忆系统（跨会话记忆；MEMORY_ENABLED=false 时为 None）
        self.memory_system = memory_system
        # 语义缓存引擎（SEMANTIC_CACHE_ENABLED=false 时为 None）
        self.cache_engine = cache_engine
        # 缓存负反馈观察：上次命中若被用户否定（"不对"），衰减该条目
        self._cache_observer_key: str = ""
        self._cache_observer_end: float = 0.0
        # 复用同一会话，使 REPL/HTTP 多轮对话共享历史
        self.session_id = f"study-{uuid.uuid4().hex[:12]}"
        # 会话 → 整数 chat_id（记忆表用），round 计数按会话独立
        self._session_ids: dict[str, int] = {}
        self._round_counters: dict[int, int] = {}
        # 每会话串行锁：Flask 多线程下同一会话的并发 chat 会交错写
        # conversation 历史、重复分配记忆轮次号。不同会话互不阻塞。
        self._chat_locks: dict[str, threading.Lock] = {}
        self._chat_locks_guard = threading.Lock()
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

    def _memory_preamble(self, user_id: int) -> str:
        """长期备忘注入（memo 全量 + 最近经验记忆摘要）。"""
        if self.memory_system is None:
            return ""
        try:
            memos = self.memory_system._get_memos(user_id)
            exps = self.memory_system._get_exp_memories(user_id)
        except Exception:
            return ""
        lines = [f"[备忘] {m['content']}" for m in memos[-10:]]
        lines += [f"[过往记忆] {e['content']}" for e in exps[-5:]]
        if not lines:
            return ""
        return "\n".join(f"(系统上下文·仅供你参考，不要复述) {b}" for b in lines)

    # ── 会话标识（记忆表用整数 chat_id） ──

    def _chat_id_for(self, session_key: str) -> int:
        cid = self._session_ids.get(session_key)
        if cid is None:
            cid = len(self._session_ids) + 1
            self._session_ids[session_key] = cid
        return cid

    def _next_round(self, chat_id: int) -> int:
        nxt = self._round_counters.get(chat_id, 0) + 1
        self._round_counters[chat_id] = nxt
        return nxt

    def _chat_lock_for(self, session_key: str) -> threading.Lock:
        """取（或建）指定会话的串行锁。"""
        lock = self._chat_locks.get(session_key)
        if lock is None:
            with self._chat_locks_guard:
                lock = self._chat_locks.get(session_key)
                if lock is None:
                    lock = threading.Lock()
                    self._chat_locks[session_key] = lock
        return lock

    # ── 语义缓存（对齐 apps.dsn CacheInterceptorPlugin 的三级服务/写入逻辑） ──

    def _cache_serve(self, message: str) -> str:
        """尝试从缓存取回复（L1 → L2 → 语义搜索）。命中返回文本，未命中返回空串。"""
        import time as _time
        engine = self.cache_engine
        if engine is None:
            return ""

        # 负反馈观察：上一轮命中若被用户否定，衰减该条目
        if self._cache_observer_key and _time.time() <= self._cache_observer_end:
            if engine.is_negative_signal(message):
                engine.decay_score(self._cache_observer_key)
                self._cache_observer_key = ""

        message = message.strip()
        if not message:
            return ""

        intent = engine.classify_intent(message)

        # 1) L1 实用语用短语（语音交互场景；study 下通常不命中）
        l1_entry = engine.serve_l1(intent)
        if l1_entry:
            return l1_entry["text"]

        # 2) L2 动作图重放
        l2_result = engine.serve_l2(message, intent)
        if l2_result and l2_result.get("reply_text"):
            return l2_result["reply_text"]

        # 3) 语义搜索（向量相似度回放历史回复）
        for r in engine.search(message, intent_class=intent, top_k=3):
            if r.score < 0.35:
                continue
            self._cache_observer_key = r.cache_key
            self._cache_observer_end = _time.time() + 30
            engine.record_hit(r.cache_key)
            return r.reply_text
        return ""

    def _cache_write(self, user_id: int, message: str, reply: str) -> None:
        """把本轮问答写入语义缓存（失败静默——缓存绝不能反过来打断对话）。"""
        try:
            if self.cache_engine is not None:
                self.cache_engine.cache_response(user_id, message.strip(), reply)
        except Exception:
            import logging
            logging.getLogger("StudyEngine").warning("缓存写入失败（已忽略）", exc_info=True)

    # ── 对话 ──

    def chat(self, message: str, user_id: int = 1,
             session_id: Optional[str] = None) -> str:
        session_key = session_id or self.session_id
        # 同一会话串行：防止并发请求把 run_with_tools 的"读历史→执行→写回"
        # 交错执行（轮次错乱），以及记忆轮次号重复分配。
        with self._chat_lock_for(session_key):
            # 语义缓存读路径：命中直接返回，不进模型（组卷等贵请求收益最大）
            served = self._cache_serve(message)
            if served:
                return served

            preamble = self._build_preamble(user_id)
            memory_preamble = self._memory_preamble(user_id)
            full_prefix = "\n\n".join(b for b in (memory_preamble, preamble) if b)
            full = f"{full_prefix}\n\n{message}" if full_prefix else message
            result = self.agent.run_with_tools(full, session_id=session_key)
            reply = result.reply

            # 记忆闭环：原始轮次落库 → 异步摘要 → 回复中的 <memo>/<recall> 标签处理
            if self.memory_system is not None:
                try:
                    cid = self._chat_id_for(session_key)
                    ridx = self._next_round(cid)
                    self.memory_system.record_round(user_id, cid, ridx, message, reply)
                    self.memory_system.summarize_turn(user_id, cid, ridx, message, reply)
                    reply = self.memory_system.handle_tags(user_id, cid, reply)
                except Exception:
                    import logging
                    logging.getLogger("StudyEngine").warning("记忆闭环失败（已跳过）", exc_info=True)

            # 语义缓存写路径（失败静默）
            self._cache_write(user_id, message, reply)
            return reply

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
        # TaskTools 实例属性注入（_mgr/_uid 优先读实例属性，_ctx 为兼容兜底）
        "study_tasks": dict(task_manager=c.get("task_manager"), db=c["db_mgr"]),
        # MemoryTools 实例属性注入
        "study_memory": dict(memory_system=c.get("memory_system")),
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

    # ── 打卡 + 学习跟踪 lite（阶段 4：纯软件版，无媒体/ASR/摄像头） ──
    from apps.dsn_study.db.checkin_store import CheckinStore
    checkin_store = CheckinStore(db_mgr)
    runtime.register("checkin", checkin_store)

    from apps.dsn_study.tracking_lite import TrackingStore
    tracking_db_dir = os.path.join(os.path.dirname(db_path), "tracking")
    os.makedirs(tracking_db_dir, exist_ok=True)
    tracking_store = TrackingStore(
        db_path=os.path.join(tracking_db_dir, "tracking.db"))
    runtime.register("tracking_store", tracking_store)

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

    # ── 学习日志门面（聚合 tracking 事件 + 打卡 + 计划完成度） ──
    from apps.dsn_study.tracking_lite import StudyLog
    studylog = StudyLog(tracking_store, checkin_store=checkin_store,
                        plan_engine=plan_engine)
    runtime.register("studylog", studylog)

    # ── 任务管理器（提醒/习惯/倒计时/日计划/正计时；自 apps.dsn 移植） ──
    task_manager = None
    if Config.TASK_MANAGER_ENABLED:
        from apps.dsn_study.tasks import TaskManager
        task_manager = TaskManager(db_mgr, llm=llm,
                                   max_workers=int(Config.TASK_MAX_WORKERS))
        runtime.register("task_manager", task_manager)
        runtime.on_stop(task_manager.shutdown)
        flask_app.config["TASK_MANAGER"] = task_manager

    # ── 记忆系统（跨会话记忆 + <recall>/<memo> 标签；自 apps.dsn 移植） ──
    memory_system = None
    if Config.MEMORY_ENABLED:
        from apps.dsn_study.memory import (
            MemorySystem, LLMSummaryModel, OpenAIEmbeddingClient,
        )
        summary_model = LLMSummaryModel(llm)
        embedding_client = None
        if Config.MEMORY_EMBEDDING_ENABLED:
            embedding_client = OpenAIEmbeddingClient(
                base_url=Config.MEMORY_EMBEDDING_BASE_URL or Config.OPENAI_API_BASE,
                api_key=Config.OPENAI_API_KEY,
                model=Config.MEMORY_EMBEDDING_MODEL,
            )
        memory_system = MemorySystem(db_mgr, summary_model=summary_model,
                                     embedding_client=embedding_client)
        runtime.register("memory", memory_system)
        flask_app.config["MEMORY_SYSTEM"] = memory_system

    # ── 语义缓存（L1/L2/L3；拦截重复贵请求，组卷场景收益最大） ──
    cache_engine = None
    if Config.SEMANTIC_CACHE_ENABLED:
        try:
            from apps.dsn_study.semantic_cache import (
                CacheStore, L1PragmaticCache, CacheEngine,
            )
            cache_dir = os.path.abspath(Config.SEMANTIC_CACHE_DIR)
            cache_store = CacheStore(db=db_mgr, cache_dir=cache_dir)
            l1_cache = L1PragmaticCache(store=cache_store)
            l1_cache.init_builtin_phrases()
            emb = memory_system.embedding_client if (
                Config.MEMORY_EMBEDDING_ENABLED and memory_system) else None
            cache_engine = CacheEngine(
                store=cache_store, l1_cache=l1_cache, embedding_client=emb,
                similarity_threshold=Config.SEMANTIC_CACHE_SIMILARITY_THRESHOLD,
            )
            runtime.register("cache_engine", cache_engine)
            logger.info("语义缓存系统: 已启用 (阈值=%.2f, 嵌入=%s)",
                        Config.SEMANTIC_CACHE_SIMILARITY_THRESHOLD, bool(emb))
        except Exception:
            logger.warning("语义缓存系统初始化失败（已跳过）", exc_info=True)
            cache_engine = None

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
        "task_manager": task_manager, "memory_system": memory_system,
        "cache_engine": cache_engine,
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
    from apps.dsn_study.api.reminder import reminder_bp, init_reminder_api
    from apps.dsn_study.api.alarm import alarm_bp, init_alarm_api
    from apps.dsn_study.api.heartbeat import heartbeat_bp, init_heartbeat_api
    from apps.dsn_study.api.checkin import checkin_bp, init_checkin_api
    from apps.dsn_study.api.studylog import studylog_bp, init_studylog_api

    init_scan_api(auth_manager=auth)
    init_study_timetable_api(db_mgr, auth)
    init_plan_api(db_mgr, auth)
    init_async_tasks_api(auth)
    init_chat_api(auth)
    init_reminder_api(db_mgr, task_manager, auth)
    init_alarm_api(db_mgr, auth)
    init_heartbeat_api(db_mgr, task_manager, auth, engine)
    init_checkin_api(checkin_store, auth)
    init_studylog_api(studylog, auth)

    blueprints = {
        "scan": scan_bp,
        "study_timetable": study_bp,
        "plan": plan_bp,
        "async_tasks": async_task_bp,
        "chat": chat_bp,
        "reminder": reminder_bp,
        "alarm": alarm_bp,
        "heartbeat": heartbeat_bp,
        "checkin": checkin_bp,
        "studylog": studylog_bp,
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
