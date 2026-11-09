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
from apps.dsn_study.prompts import StudyPromptBuilder
from apps.dsn_study.pipeline import (
    AsrFilterPlugin,
    StudyPipelineRunner,
    SystemPromptPlugin,
    TopicContextPlugin,
    VisionContextPlugin,
    ExamSessionPlugin,
    DailyReportPlugin,
    ComplexityPlugin,
    ModelInvokePlugin,
    PlanCheckPlugin,
    MemoryRecordPlugin,
    PersonalityFeedbackPlugin,
    TTSPlugin,
)
from harness.pipeline.base import Context

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
                 task_manager=None, memory_system=None, cache_engine=None,
                 chat_hooks=None, complexity_analyzer=None,
                 studylog=None, checkin_store=None, voice=None,
                 prompt_builder=None, personality=None,
                 pipeline_runner=None, vision_coordinator=None):
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
        # 对话期钩子（考试超时/交卷/<plan_check> 勾选/日终报告）
        self.chat_hooks = chat_hooks
        # 复杂度分析器（复杂问题 → 提示走 create_reasoner 深入推理）
        self.complexity_analyzer = complexity_analyzer
        # 学习日志 / 打卡（供技能依赖注入与统计）
        self.studylog = studylog
        self.checkin_store = checkin_store
        # 语音合成门面（infra 资源池 + GPT-SoVITS）；为 None 时不产出音频
        self.voice = voice
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
        #: system prompt 组装器（阶段 1）：逐轮重建，支持 {personality}/{user_context}
        self.prompt_builder = prompt_builder
        #: 人格系统（阶段 2，harness/personality PEV3）；None = 无性格运行
        self.personality = personality
        #: 对话管线（阶段 3，harness/pipeline）；None = 走直连模型兜底
        self.pipeline_runner = pipeline_runner
        #: 视觉感知协调器（阶段 5）；None = 无摄像头链路
        self.vision_coordinator = vision_coordinator
        #: 上一轮管线产出的音频（chat_audio 用）
        self._last_tts: tuple = (None, "")
        # 旧管线代码兼容别名（api/scan.py 期望 engine.pipeline）
        # 扫题批次总结用的这条轻量管线此前只有 58 字身份 —— 与主助手人格割裂。
        # 这里给「身份 + 人格」两段（不含 17KB 技能指令：总结任务用不上）。
        self.pipeline = StudyPipeline(
            chat_client,
            system_prompt=(prompt_builder.build(only_tags=["core", "personality"])
                           if prompt_builder is not None
                           else DEFAULT_SYSTEM_PROMPT))

    # ── 学习上下文注入（对齐参考实现 4 个 PRE_PROCESS 插件的职责） ──

    def _build_preamble(self, user_id: int) -> str:
        blocks: list[str] = []

        try:  # 今日计划（PlanPlugin）
            summary = self.plan_engine.daily_summary(user_id)
            if summary["total"]:
                blocks.append(
                    f"[今日计划] {summary['done']}/{summary['total']} 已完成，"
                    f"{summary['pending']} 待办、{summary['skipped']} 已跳过。"
                    + "；".join(
                        f"{t['title']}({t['status']}"
                        + (f", id={t['task_id'][:8]}" if t.get("task_id") else "")
                        + ")"
                        for t in summary["tasks"][:8])
                )
        except Exception:
            # 静默吞掉会让「今日计划」块无声消失 —— 学习上下文注入是
            # dsn_study 的核心价值，DB/schema 一漂移就静默降级且零日志。
            logger.warning("今日计划注入失败（已跳过）", exc_info=True)

        try:  # 到期复习（KnowledgeGraphPlugin）
            due = self.graph_store.get_due_reviews(user_id)
            if due:
                names = [d.get("kp_name") or d.get("kp_code", "") for d in due[:6]]
                blocks.append(f"[到期复习] {len(due)} 个知识点待复习：{', '.join(filter(None, names))}")
        except Exception:
            logger.warning("到期复习注入失败（已跳过）", exc_info=True)

        try:  # 错题概况（QuestionBankPlugin）
            total_errors = self.question_store.get_total_errors(user_id)
            if total_errors:
                blocks.append(f"[错题本] 累计 {total_errors} 道错题待巩固")
        except Exception:
            logger.warning("错题本注入失败（已跳过）", exc_info=True)

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

    def _complexity_preamble(self, message: str) -> str:
        """复杂问题提示 — 引导 AI 走 create_reasoner 深入推理。"""
        if self.complexity_analyzer is None:
            return ""
        try:
            result = self.complexity_analyzer.analyze_complexity(message or "", 0)
        except Exception:
            return ""
        if not result.get("is_complex"):
            return ""
        reasons = "、".join(result.get("reasons", [])[:3])
        return (f"(系统上下文·仅供你参考) 该问题复杂度较高（评分 "
                f"{result.get('score', 0)}；{reasons}）。"
                f"如需深入推理，可调用 create_reasoner 工具后台分析。")

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
             session_id: Optional[str] = None,
             image: Optional[str] = None,
             tts_enabled: bool = False,
             is_asr_input: bool = False) -> str:
        session_key = session_id or self.session_id
        # 同一会话串行：防止并发请求把 run_with_tools 的"读历史→执行→写回"
        # 交错执行（轮次错乱），以及记忆轮次号重复分配。
        with self._chat_lock_for(session_key):
            # 语义缓存读路径：命中直接返回，不进模型（组卷等贵请求收益最大）
            served = self._cache_serve(message)
            if served:
                return served

            # 人格系统：首次对话前确保用户已绑定角色卡（PEV3 会自动绑默认卡）
            if self.personality is not None:
                try:
                    self.personality.ensure_user_bound(user_id)
                except Exception:
                    logger.warning("人格角色卡绑定失败（已跳过）", exc_info=True)

            # ── system prompt 逐轮重建（阶段 1）──
            # 学习上下文（今日计划 / 到期复习 / 错题本 / 长期备忘）描述的是
            # 「当前学习状态」而非用户说的话，放 system 侧语义更准，
            # 学习上下文（计划 / 到期复习 / 错题本 / 备忘）→ 进 system prompt 的
            # {user_context} 插槽（阶段 1）。它描述的是「当前学习状态」而非用户
            # 说的话，放 system 侧语义更准，因此走 system 插槽而不是塞进 user 轮。
            learning_context = "\n\n".join(
                b for b in (self._memory_preamble(user_id),
                            self._build_preamble(user_id)) if b)

            # ── 对话管线（阶段 3）──
            # 能力全部挂在 harness/pipeline 的钩子上：
            #   PREPARE      组装 system prompt（身份+人格+上下文+技能指令）
            #   PRE_PROCESS  视觉 / 考试 / 日终报告 / 复杂度（与本条消息强相关）
            #   MODEL_INVOKE 调模型
            #   POST_PROCESS <plan_check> 回写 / 记忆落库 / 人格回写
            #   POST_TTS     语音合成
            ctx = Context(user_id=user_id, message=message,
                          session_id=session_key, image_data=image,
                          chat_id=self._chat_id_for(session_key),
                          nickname="用户", tts_enabled=bool(tts_enabled),
                          is_asr_input=bool(is_asr_input))
            # 附件通道（阶段 5.6）：图片走 Attachment(kind="image")，
            # 插件侧优先消费 attachments，image_data 保留为兼容来源。
            if image:
                from harness.pipeline.base import Attachment
                ctx.attachments.append(Attachment(
                    kind="image", data=image, mime="image/jpeg", name="chat-image"))
            ctx.extra["user_message"] = message
            ctx.extra["round_index"] = self._next_round(ctx.chat_id)
            try:
                ctx = self.pipeline_runner.run(ctx)
                reply = ctx.reply or ""
                # POST_TTS 插件的产物（chat_audio 直接取，不再二次合成）
                self._last_tts = (ctx.audio_b64, ctx.tts_error or "")
                tag_results = ctx.outputs.get("plan_check") or []
                if tag_results:
                    ok = sum(1 for r in tag_results if r.get("success"))
                    logger.info("plan_check 处理: %d/%d 成功", ok, len(tag_results))
            except Exception:
                logger.warning("对话管线失败（回退到直连模型）", exc_info=True)
                reply = ""

            if not reply:
                # 管线不可用（未启动 / 模型调用失败）→ 直连模型兜底，
                # 保证对话永远有结果。
                self._last_tts = (None, "")
                try:
                    if self.prompt_builder is not None:
                        self.prompt_builder.begin_turn(user_id, learning_context)
                    result = self.agent.run_with_tools(
                        message, session_id=session_key,
                        system_prompt=(self.prompt_builder.build()
                                       if self.prompt_builder is not None
                                       else None))
                    reply = result.reply or ""
                except Exception:
                    logger.warning("直连模型兜底也失败", exc_info=True)
                    reply = ""

            # 语义缓存写路径（失败静默）
            self._cache_write(user_id, message, reply)
            return reply

    # ── 语音合成（跟随回复自动生成，不提供 AI 主动合成入口）──

    def _synthesize(self, reply: str) -> tuple[Optional[str], str]:
        """把回复合成为音频。返回 (audio_b64, error)；失败时 audio 为 None。"""
        if self.voice is None:
            return None, ""
        try:
            return self.voice.synthesize_b64(reply)
        except Exception as e:
            logger.warning("语音合成失败（已降级为纯文本）: %s", e)
            return None, str(e)

    def chat_audio(self, message: str, user_id: int = 1,
                   session_id: Optional[str] = None,
                   image: Optional[str] = None,
                   is_asr_input: bool = False) -> dict:
        """带语音的对话：返回 {reply, audio_b64, tts_error}。

        chat() 保持只返回文本（REPL / 心跳 / 既有调用方不受影响）；
        需要音频的调用方走本方法。
        """
        reply = self.chat(message, user_id=user_id, session_id=session_id,
                          image=image, tts_enabled=True,
                          is_asr_input=is_asr_input)
        # POST_TTS 插件已在管线里合成过；管线不可用时退回本地合成。
        audio_b64, tts_error = self._last_tts
        if audio_b64 is None and reply:
            audio_b64, tts_error = self._synthesize(reply)
        return {"reply": reply, "audio_b64": audio_b64, "tts_error": tts_error}

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

# 插件目录说明 —— 首次创建 custom/ 时写入，让"技能可以插拔"这件事有据可查。
_CUSTOM_SKILL_README = """# 自定义技能目录（可插拔）

把一个技能包放进本目录的子目录里，重启应用即可生效（也可调用
`POST /api/skills/install` 在运行时安装，不必重启）。

## 目录结构

```
skills/custom/<技能名>/
├── skill.yaml          # 必需：技能元信息 + 工具声明
├── prompts/*.md        # 可选：注入 system prompt 的说明
├── tools/*.py          # 可选：工具实现
└── skill.env           # 可选：技能私有配置（KEY=VALUE）
```

## 依赖注入（不再需要改 boot.py）

工具类用类属性 `needs` 声明需要哪些**能力**，harness 会自动注入：

```python
class MyTool:
    needs = {"question_store": "_store", "workspace": "_workspace"}

    def __init__(self):
        self._store = None
        self._workspace = None
```

可用能力见 `GET /api/skills` 的 `capabilities` 字段。
能力缺失时该工具**不会被注册**（而不是静默拿到 None）。

## 声明与实现不一致时

工具类名、方法名、参数名必须与 skill.yaml 一致，否则加载期就会报出
具体是哪一条不对（见 `GET /api/skills` 的 `issues`）。
"""


def _ensure_custom_skill_dir(custom_dir: str) -> str:
    """确保插件目录存在（不存在就建，并写一份说明）。"""
    try:
        os.makedirs(custom_dir, exist_ok=True)
    except Exception as e:
        logger.warning("创建自定义技能目录失败 %s: %s", custom_dir, e)
        return custom_dir
    readme = os.path.join(custom_dir, "README.md")
    if not os.path.exists(readme):
        try:
            with open(readme, "w", encoding="utf-8") as f:
                f.write(_CUSTOM_SKILL_README)
        except Exception as e:
            logger.warning("写入自定义技能目录说明失败: %s", e)
    return custom_dir


def _register_skill_capabilities(skill_registry, c: dict,
                                 workspace=None) -> list[str]:
    """注册技能可用的**语义能力** —— 技能依赖注入的唯一来源。

    技能在 skill.yaml 的 dependencies 里写语义名（如 question_store），
    工具类用 needs 声明"语义能力 → 实例属性名"，由 harness 自动注入。
    以前这套是应用层一张硬编码的属性名映射表，新技能必须去改 boot.py；
    现在新技能只需要声明自己需要什么。
    """
    caps = {
        # 题库 / 模板 / 模型
        "question_store": c.get("question_store"),
        "template_manager": c.get("template_manager"),
        "models_plugin": c.get("llm"),
        "llm": c.get("llm"),
        "db_mgr": c.get("db_mgr"),
        # 考试 / 评分
        "exam_engine": c.get("exam_engine"),
        "exam_scorer": c.get("scorer"),
        "scorer": c.get("scorer"),
        # 知识图谱
        "graph_store": c.get("graph_store"),
        "graph_engine": c.get("graph_engine"),
        "knowledge_matcher": c.get("kg_matcher"),
        "kg_matcher": c.get("kg_matcher"),
        "kg_builder": c.get("kg_builder"),
        # 扫描 / 计划 / 任务 / 记忆
        "scanner_pipeline": c.get("scanner_pipeline"),
        "plan_engine": c.get("plan_engine"),
        "task_manager": c.get("task_manager"),
        "memory_system": c.get("memory_system"),
        "cache_engine": c.get("cache_engine"),
        # 学习跟踪
        "studylog": c.get("studylog"),
        "checkin_store": c.get("checkin_store"),
        # 工作区（落盘：扫描件、下载的图片/PDF 走这里）
        "workspace": workspace,
    }
    usable = {k: v for k, v in caps.items() if v is not None}
    skill_registry.register_capabilities(usable)
    logger.info("已注册 %d 个技能能力: %s", len(usable), ", ".join(sorted(usable)))
    return sorted(usable)


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
        # document 技能（扫描/打印/HMD/作答卷判分）——补注入题库与模型，
        # 否则 scan_import_questions / process_answered_scan 拿不到题库与判分模型
        "document": dict(_question_store=c["question_store"], _models=c["llm"]),
        "question_print": dict(_store=c["question_store"], _tm=c["template_manager"]),
        "plan": {},  # PlanTools 经 get_plan_db() 全局取库
        "study_timetable": {},  # StudyTimetableTool 经 get_study_db() 全局取库
        # TaskTools 实例属性注入（_mgr/_uid 优先读实例属性，_ctx 为兼容兜底）
        "study_tasks": dict(task_manager=c.get("task_manager"), db=c["db_mgr"],
                            _complexity=c.get("complexity_analyzer")),
        # MemoryTools 实例属性注入
        "study_memory": dict(memory_system=c.get("memory_system")),
        # 批量操作工具（多 action 并行提交到 TaskManager）
        "batch": dict(task_manager=c.get("task_manager"), db=c["db_mgr"]),
        # 学习跟踪工具（打卡 / 学习时段 / 笔记 / 每日报告）
        # 注意：注入表的键必须是工具实例的属性名（工具内部用 _studylog/_checkin）
        "study_tracking": dict(_studylog=c.get("studylog"),
                               _checkin=c.get("checkin_store")),
        # 视觉感知工具（阶段 5）：协调器 + 模型服务
        "visual_perception": dict(_coordinator=c.get("vision_coordinator"),
                                  _models=c.get("llm")),
    }


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

        # ── 话题系统（阶段 7）：策略层装配 + 接热路径 ──
        # 剪裁引擎是 harness 的 SegmentedContextAssembler，这里只写策略层
        # （存储/边界/pin/摘要）。压缩持久化（compressed_chunks）由
        # close_topic 经 infra SessionStore 接线。
        if Config.TOPIC_ENABLED:
            try:
                from apps.dsn_study.memory.topics import TopicManager
                topics_dir = os.path.dirname(db_path)
                os.makedirs(topics_dir, exist_ok=True)
                topic_manager = TopicManager(
                    os.path.join(topics_dir, "topics.db"),
                    summary_model=summary_model,
                    embedding_client=(embedding_client
                                      if Config.MEMORY_EMBEDDING_ENABLED else None),
                    judge_chat=llm,
                )
                memory_system.wire_topics(topic_manager)
                runtime.register("topics", topic_manager)
                flask_app.config["TOPIC_MANAGER"] = topic_manager
                logger.info("话题系统已装配: %s", os.path.join(topics_dir, "topics.db"))
            except Exception:
                logger.warning("话题系统初始化失败（记忆走 memo/exp 路径）",
                               exc_info=True)

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
        # 这条路径此前**完全不记日志**（全 boot.py 唯一一处），
        # 而 workspace 能力注册不上去 → 按能力声明规则，
        # question_print / document / quest_from_image 的工具会被**静默不注册**。
        logger.error("工作区初始化失败（相关技能工具将不可用）: %s",
                     Config.WORKSPACE_DIR, exc_info=True)
        workspace = None

    # ── 复杂度分析器（复杂问题 → 提示走 reasoner 深入推理）──
    complexity_analyzer = None
    try:
        from apps.dsn_study.tasks import ComplexityAnalyzer
        complexity_analyzer = ComplexityAnalyzer()
    except Exception:
        logger.warning("复杂度分析器初始化失败（已跳过）", exc_info=True)

    # ── 视觉感知协调器（阶段 5）──
    # 必须在技能装配**之前**初始化：visual_perception 技能的依赖注入表
    # 引用协调器，装配晚了会注入 None（工具永远报「未就绪」）。
    from apps.dsn_study.api.vision import init_vision_api
    init_vision_api(db=db_mgr, engine=None, auth_manager=auth, workspace=workspace)
    from apps.dsn_study.api import vision as _vision_mod
    flask_app.config["VISION_COORDINATOR"] = _vision_mod.coordinator
    runtime.register("vision_coordinator", _vision_mod.coordinator)
    if getattr(Config, "VISION_ENABLED", True) and getattr(Config, "VISION_WARMUP", True):
        def _vision_warmup():
            try:
                from apps.dsn_study.models.clients import VisionModel
                vm = VisionModel()
                if getattr(vm, "api_key", ""):
                    vm.ask(
                        "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
                        "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
                        "这是一张 1x1 测试图。请只回复一个词：ok。",
                        max_tokens=8, temperature=0.0)
                    logger.debug("VisionModel 预热完成 (model=%s)", vm.model_name)
            except Exception as e:
                logger.debug("VisionModel 预热失败（不影响运行）: %s", e)
        threading.Thread(target=_vision_warmup, daemon=True,
                         name="vision-warmup").start()

    c = {
        "db_mgr": db_mgr, "llm": llm, "question_store": question_store,
        "template_manager": template_manager, "composer": composer, "scorer": scorer,
        "exam_engine": exam_engine, "graph_store": graph_store,
        "graph_engine": graph_engine, "kg_builder": kg_builder, "kg_matcher": kg_matcher,
        "scanner_pipeline": scanner_pipeline, "timetable_store": timetable_store,
        "async_task_store": async_task_store, "plan_engine": plan_engine,
        "task_manager": task_manager, "memory_system": memory_system,
        "cache_engine": cache_engine,
        "studylog": studylog, "checkin_store": checkin_store,
        "complexity_analyzer": complexity_analyzer,
        "vision_coordinator": _vision_mod.coordinator,
    }

    # ── 技能系统 ──
    from apps.dsn_study.skills.registry import SkillRegistry
    from apps.dsn_study.skills.manager import SkillManager
    from apps.dsn_study.skills.loader import SkillLoader

    skill_registry = SkillRegistry()
    app_root = os.path.dirname(__file__)
    skill_dirs = [os.path.join(app_root, "skills", "builtin")]
    custom_dir = os.path.join(app_root, "skills", "custom")
    # 插件目录不存在就建一个 —— 以前 custom/ 不存在时静默跳过，
    # 放进去的技能要等"建目录"这个动作发生才生效，坑得很隐蔽。
    _ensure_custom_skill_dir(custom_dir)
    skill_dirs.append(custom_dir)

    # 能力注册（技能依赖注入的唯一来源）—— 必须在扫描之前，
    # 否则工具类用 needs 声明的能力会判定为"缺失"。
    _register_skill_capabilities(skill_registry, c, workspace)

    skill_manager = SkillManager(skill_dirs, skill_registry)
    # 旧式按属性名注入（兼容老技能；新技能请用工具类的 needs 声明）。
    # 交给 manager 保管：enable/reload 换了新的工具实例后会补注入一次。
    skill_manager.set_legacy_deps(_build_skill_dep_map(c))
    loaded_skills = skill_manager.scan_and_load()
    logger.info("技能加载完成: %d 个", loaded_skills)

    # ── 工具派发自检（护栏）──
    # 过去「注册成功但调用必挂」这类缺陷会静默存在：技能正常加载、工具出现在
    # function-calling schema 里，直到模型真的调用才抛「工具方法不存在」。
    # 这里在装配期就跑一遍，把问题挡在服务上线之前。
    try:
        undispatchable = skill_registry.undispatchable_tools()
    except Exception:
        logger.warning("工具派发自检失败（已跳过）", exc_info=True)
        undispatchable = []
    if undispatchable:
        for item in undispatchable:
            logger.error("工具无法派发（注册成功但调用必挂）: %s — %s；"
                         "skill.yaml 声明的方法=%s",
                         item.get("key"), item.get("reason"),
                         item.get("declared_methods"))
        flask_app.config["UNDISPATCHABLE_TOOLS"] = undispatchable
        logger.error("共 %d 个工具无法派发", len(undispatchable))
    else:
        flask_app.config["UNDISPATCHABLE_TOOLS"] = []

    # ── 人格系统（harness/personality PEV3，阶段 2）──
    # 复用 harness 的实现（它是 apps/dsn/prompt/personality_v3 的迁移后超集），
    # **不复制 dsn 的副本**。角色卡目录必须显式指定：
    # harness/personality 的 _find_default_cards_dir() 会去找 apps/dsn/character_cards
    # —— 那是 dsn 的 EXA（AI 同事）卡，study 要的是学习导师卡。
    personality = None
    if getattr(Config, "PERSONALITY_ENABLED", True):
        try:
            from harness.personality import PersonalitySystemV3
            cards_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "character_cards")
            default_card = os.path.join(
                cards_dir,
                getattr(Config, "PERSONALITY_DEFAULT_CARD", "study_tutor.yaml"))
            personality = PersonalitySystemV3(
                db=db_mgr,
                personality_model_chat=chat_client,
                distillation_chat=chat_client,
                fast_distillation_chat=chat_client,
                cards_dir=cards_dir,
                default_card_path=default_card,
            )
            personality.init_tables()
            personality.enabled = True
            runtime.register("personality", personality)
            logger.info("人格系统已就绪: cards_dir=%s default=%s",
                        cards_dir, os.path.basename(default_card))

            # 预热（后台线程）：
            #   * ensure_user_bound —— 绑定默认角色卡，否则没有状态；
            #   * generate_personality_prompt —— PEV3 的 generate() **首调返回兜底串**，
            #     LLM 版在后台线程算、**下次调用才生效**。不预热的话，
            #     用户的第一轮对话拿到的就是没有性格的兜底文案；
            #   * warmup_distillation —— 50 维特质蒸馏同样耗 LLM，放后台。
            def _warm_personality():
                try:
                    personality.ensure_user_bound(1)
                    personality.generate_personality_prompt(1)
                    personality.warmup_distillation()
                except Exception:
                    logger.warning("人格预热失败（已忽略）", exc_info=True)

            threading.Thread(target=_warm_personality, daemon=True,
                             name="personality-warmup").start()
        except Exception:
            logger.warning("人格系统初始化失败（将无性格运行）", exc_info=True)
            personality = None

    # ── Agent（技能工具桥接 + 提示词聚合） ──
    # system prompt 片段化组装（阶段 1）：身份 + 人格 + 学习上下文 + 技能指令。
    # 逐轮重建 → 禁用技能后其指令文本立即消失（旧的 boot 时拼死字符串做不到）。
    prompt_builder = StudyPromptBuilder(skill_registry=skill_registry)
    if personality is not None:
        # 人格提示词按 uid 取（PEV3 的状态按用户存），
        # 且首调返回兜底串 + 后台生成 LLM 版 —— 故预热一次，避免首轮没有性格。
        prompt_builder.set_personality_provider(
            lambda uid: personality.generate_personality_prompt(uid))
    system_prompt = prompt_builder.build()
    from apps.dsn_study.tool_adapter import SkillTagToolCallAdapter
    agent = AgentRuntime(
        chat_client,
        name="dsn-study-agent",
        system_prompt=system_prompt,
        max_steps=int(Config.AGENT_MAX_STEPS),
        # 原生 function calling 优先；模型只吐 XML 时自动降级到 <tool> 标签协议
        adapter=SkillTagToolCallAdapter(),
    )
    # 技能工具桥接（同步 + 协程）—— 走 harness 的唯一实现
    from harness.skills.agent_bridge import bridge_skills_to_agent
    bridged = bridge_skills_to_agent(agent, skill_registry, SkillLoader())
    logger.info("已桥接 %d 个技能工具到 AgentLoop", bridged)

    # ── 外部 MCP（Obsidian 知识库 / 笔记）──
    # 连接放后台线程：stdio 子进程冷启动（npx 拉包）数秒，不能阻塞启动。
    # 连不上只影响 MCP 工具，其余功能照常（失败隔离）。
    mcp_bridge = None
    if getattr(Config, "MCP_ENABLED", False):
        try:
            from apps.dsn_study.mcp_bridge import MCPBridge
            mcp_bridge = MCPBridge(
                agent,
                config_path=getattr(Config, "MCP_CONFIG_PATH", ""),
                env={"OBSIDIAN_VAULT_PATH":
                     getattr(Config, "OBSIDIAN_VAULT_PATH", "")},
            )
            mcp_bridge.start()
            runtime.register("mcp", mcp_bridge)
            runtime.on_stop(mcp_bridge.close)
        except Exception:
            logger.warning("MCP 桥接初始化失败（外部 MCP 工具不可用）",
                           exc_info=True)

    # ── Obsidian 知识库技能依赖注入 ──
    if mcp_bridge is not None:
        try:
            from apps.dsn_study.skills.builtin.obsidian_notes.tools.obsidian_tools import (
                ObsidianNotesTool,
            )
            if not skill_registry.inject_dependencies(
                "obsidian_notes",
                mcp_bridge=mcp_bridge,
                graph_store=graph_store,
                plan_engine=plan_engine,
                vault_id=getattr(Config, "OBSIDIAN_VAULT_ID", "study"),
                kp_folder=getattr(Config, "OBSIDIAN_KP_FOLDER", "知识点库"),
                note_folder=getattr(Config, "OBSIDIAN_NOTE_FOLDER", "学习笔记"),
                # vault 本地路径：obsidian-mcp 是文件系统型 MCP，
                # list_notes 直接读磁盘目录（MCP 侧无 obsidian_list_notes 工具）
                vault_path=getattr(Config, "OBSIDIAN_VAULT_PATH", ""),
            ):
                logger.warning("Obsidian 技能依赖注入未命中（属性名不匹配）")
        except Exception:
            logger.warning("Obsidian 技能依赖注入失败", exc_info=True)

    # ── 语音合成（infra 资源池调度 GPT-SoVITS）──
    voice = None
    try:
        from apps.dsn_study.voice import VoiceService
        voice = VoiceService.create()
        runtime.register("voice", voice)
        if voice.available and getattr(Config, "TTS_WARMUP", True):
            # 后台预热：拉起 TTS 服务（加载权重分钟级），不阻塞应用启动。
            # 预热期间对话照常返回纯文本，音频在服务就绪后自动生效。
            def _warmup():
                try:
                    voice.warmup()
                except Exception as e:
                    logger.warning("TTS 预热异常（已忽略）: %s", e)
            threading.Thread(target=_warmup, daemon=True,
                             name="tts-warmup").start()
    except Exception as e:
        logger.warning("语音子系统初始化失败（将只返回文本）: %s", e)

    # ── 语音识别（infra 资源池调度 FunASR sidecar）──
    asr = None
    try:
        from apps.dsn_study.asr import ASRService
        asr = ASRService.create()
        runtime.register("asr", asr)
        flask_app.config["ASR_SERVICE"] = asr
        if asr.available and getattr(Config, "ASR_WARMUP", False):
            # 后台预热：拉起 sidecar 并加载模型（分钟级），不阻塞应用启动。
            def _asr_warmup():
                try:
                    asr.warmup()
                except Exception as e:
                    logger.warning("ASR 预热异常（已忽略）: %s", e)
            threading.Thread(target=_asr_warmup, daemon=True,
                             name="asr-warmup").start()
    except Exception as e:
        logger.warning("语音识别子系统初始化失败（语音输入不可用）: %s", e)

    # ── 对话期钩子（考试超时/交卷/<plan_check>/日终报告）──
    from apps.dsn_study.chat_hooks import StudyChatHooks
    chat_hooks = StudyChatHooks(exam_engine=exam_engine,
                                  plan_engine=plan_engine, llm=llm)

    # ── 对话管线（阶段 3，harness/pipeline）──
    # 能力从 chat_hooks 的 if/else 串接迁到插件；chat_hooks 保留为兼容门面。
    # ASR 输入过滤（PRE_FILTER）：只过滤 ASR 来源的轮次，文本输入一律放行。
    asr_filter_model = None
    if getattr(Config, "ASR_FILTER_ENABLED", False):
        try:
            from apps.dsn_study.asr_filter import AsrFilterModel
            asr_filter_model = AsrFilterModel(chat=chat_client)
            runtime.register("asr_filter", asr_filter_model)
        except Exception:
            logger.warning("ASR 过滤器初始化失败（将不过滤）", exc_info=True)

    pipeline_runner = StudyPipelineRunner(plugins=[
        AsrFilterPlugin(filter_model=asr_filter_model),
        SystemPromptPlugin(prompt_builder=prompt_builder),
        TopicContextPlugin(memory_system=memory_system, agent=agent),
        VisionContextPlugin(llm=llm, workspace=workspace),
        ExamSessionPlugin(exam_engine=exam_engine),
        DailyReportPlugin(plan_engine=plan_engine),
        ComplexityPlugin(complexity_analyzer=complexity_analyzer),
        ModelInvokePlugin(agent=agent),
        PlanCheckPlugin(plan_engine=plan_engine),
        MemoryRecordPlugin(memory_system=memory_system),
        PersonalityFeedbackPlugin(personality=personality),
        TTSPlugin(voice=voice),
    ])
    pipeline_runner.start()
    runtime.on_stop(pipeline_runner.stop)
    flask_app.config["PIPELINE_RUNNER"] = pipeline_runner

    # ── 引擎门面 ──
    engine = StudyEngine(
        agent=agent, chat_client=chat_client,
        skill_registry=skill_registry, skill_manager=skill_manager,
        workspace=workspace, chat_hooks=chat_hooks, voice=voice,
        prompt_builder=prompt_builder, personality=personality,
        pipeline_runner=pipeline_runner, **c,
    )
    runtime.register("engine", engine)
    flask_app.config["ENGINE"] = engine

    # ── 蓝图初始化 + 装配 ──
    from apps.dsn_study.api.scan import scan_bp, init_scan_api
    from apps.dsn_study.api.study_timetable import study_bp, init_study_timetable_api
    from apps.dsn_study.api.plan import plan_bp, init_plan_api
    from apps.dsn_study.api.async_tasks import async_task_bp, init_async_tasks_api
    from apps.dsn_study.api.chat import chat_bp, init_chat_api
    from apps.dsn_study.api.chat_stream import chat_stream_bp, init_chat_stream_api
    from apps.dsn_study.api.reminder import reminder_bp, init_reminder_api
    from apps.dsn_study.api.alarm import alarm_bp, init_alarm_api
    from apps.dsn_study.api.heartbeat import heartbeat_bp, init_heartbeat_api
    from apps.dsn_study.api.checkin import checkin_bp, init_checkin_api
    from apps.dsn_study.api.studylog import studylog_bp, init_studylog_api
    from apps.dsn_study.api.voice import voice_bp, init_voice_api
    from apps.dsn_study.api.asr import asr_bp, init_asr_api
    from apps.dsn_study.api.obsidian import obsidian_bp, init_obsidian_api
    from apps.dsn_study.api.skills import skills_bp, init_skills_api
    from apps.dsn_study.api.personality import (
        personality_bp, init_personality_api,
    )
    from apps.dsn_study.api.vision import vision_bp as _vision_bp

    # ── 管理面板（阶段 8）：主应用 /api/admin 蓝图 + infra/auth 认证 ──
    # 不再另起 4500 端口；密钥来自 WEB_ADMIN_API_KEY，未配置则自动生成并打日志。
    from apps.dsn_study.web_admin.routes import admin_bp, init_web_admin
    admin_key = init_web_admin(
        engine, api_key=os.environ.get("WEB_ADMIN_API_KEY", ""),
        totp_secret=os.environ.get("WEB_ADMIN_TOTP_SECRET", ""))
    flask_app.config["WEB_ADMIN_KEY"] = admin_key

    init_scan_api(auth_manager=auth)
    init_study_timetable_api(db_mgr, auth)
    init_plan_api(db_mgr, auth)
    init_async_tasks_api(auth)
    init_chat_api(auth)
    init_chat_stream_api(auth, get_engine)
    init_reminder_api(db_mgr, task_manager, auth)
    init_alarm_api(db_mgr, auth)
    init_heartbeat_api(db_mgr, task_manager, auth, engine)
    init_checkin_api(checkin_store, auth)
    init_studylog_api(studylog, auth)
    init_voice_api(voice, auth)
    init_asr_api(asr, auth, get_engine)
    init_obsidian_api(mcp_bridge, skill_registry, auth)
    init_skills_api(skill_manager, skill_registry, auth)
    init_personality_api(personality, auth)

    blueprints = {
        "scan": scan_bp,
        "study_timetable": study_bp,
        "plan": plan_bp,
        "async_tasks": async_task_bp,
        "chat": chat_bp,
        "chat_stream": chat_stream_bp,
        "reminder": reminder_bp,
        "alarm": alarm_bp,
        "heartbeat": heartbeat_bp,
        "checkin": checkin_bp,
        "studylog": studylog_bp,
        "voice": voice_bp,
        "asr": asr_bp,
        "obsidian": obsidian_bp,
        "skills": skills_bp,
        "personality": personality_bp,
        "vision": _vision_bp,
        "web_admin": admin_bp,
    }

    # CLI 自更新（阶段 6.5）：**独立的 study 清单**。
    # 过去复用 apps.dsn.api.update，其 DISTRIBUTED_FILES 指向 apps/dsn/CLI/*，
    # study 客户端会拉到 dsn 的字节 —— 现在用自己的蓝图（只发 apps/dsn_study_cli/*）。
    from apps.dsn_study.api.update import update_bp, init_update_api
    init_update_api(token=os.environ.get("DSN_STUDY_TOKEN", ""))
    blueprints["update"] = update_bp

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
