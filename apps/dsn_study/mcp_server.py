# apps/dsn_study/mcp_server.py
# 暴露侧 MCP —— 把 dsn_study 的学习技能工具经 stdio MCP 暴露给外部 Agent。
#
# 定位（FEATURE_GAP 阶段 6）：「Agent 接入不走 cp（api/agent.py 依赖记忆同步链），
# 改用 harness MCP 桥接把学习工具暴露出去」。harness/tools/mcp.py 是**消费侧**
# （把外部 MCP 服务器的工具接入 ToolRegistry），本文件是**暴露侧**：
# 一个 stdio MCP 服务器，外部 MCP 客户端（Claude Desktop / 另一个 DSN 实例 /
# 任何 MCP 客户端）连接后可直接调用题库 / 学习跟踪 / 知识图谱 / 打卡等技能工具。
#
# 启动：
#     python -m apps.dsn_study.mcp_server            # stdio JSON-RPC（阻塞）
#     python -m apps.dsn_study.mcp_server --check    # 装配自检：打印工具数退出
#
# 与 Web 应用（boot.create_application）的关系 —— 只装配「工具可达」所需的
# 最小上下文（db / 题库 / 模板 / 考试 / 图谱 / 计划 / 打卡 / 学习日志 / 记忆 /
# 任务 / LLM），**不起 Flask、不预热视觉、不连 Obsidian MCP**：那些是 Web 侧的
# 长驻能力；对应技能的工具因能力缺失自然不注册（harness 的 needs 判定），
# 而不是"注册了但调用必挂"。能力注册与依赖注入表直接复用 boot.py 的同一份
# 实现（_register_skill_capabilities / _build_skill_dep_map）—— 工具在
# Web 侧和 MCP 侧拿到同一套依赖，行为一致。
#
# 工具命名：MCP 工具名只允许 [A-Za-z0-9_-] 且建议 ≤64 字符，故把
# "skill.tool" 编码为 "skill__tool"（双下划线分隔，保留反向映射）。
# 调度错误不抛协议异常 —— 返回 {"success": false, "error": …}，
# 让调用方（通常是 LLM）能看到错误并自行纠正，而不是断掉整个会话。

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys

logger = logging.getLogger("dsn_study.mcp_server")

_MCP_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


# ── 工具名编码 ──

def mcp_tool_name(skill: str, tool: str) -> str:
    """skill.tool → skill__tool（MCP 名只允许字母/数字/下划线/连字符）。"""
    name = f"{skill}__{tool}"
    if len(name) > 64 or not _MCP_NAME_RE.match(name):
        raise ValueError(f"工具名不符合 MCP 命名规则: {name}")
    return name


def build_tool_index(registry) -> dict[str, tuple[str, str]]:
    """全部已注册工具 → {mcp 名: (skill, tool)}。重名（理论上不会）后到先得并告警。"""
    index: dict[str, tuple[str, str]] = {}
    for spec in registry.get_all_tool_specs():
        name = mcp_tool_name(spec["skill"], spec["name"])
        if name in index:
            logger.warning("MCP 工具名冲突: %s (%s) 覆盖 %s",
                           name, spec["full_name"], index[name])
        index[name] = (spec["skill"], spec["name"])
    return index


# ── tools/list ──

def list_mcp_tools(registry, skill_loader=None) -> list[dict]:
    """MCP tools/list 载荷。参数 schema 与 function calling 用同一生成器
    （SkillLoader.build_function_schema），保证两边看到的参数契约一致。"""
    if skill_loader is None:
        from apps.dsn_study.skills.loader import SkillLoader
        skill_loader = SkillLoader()
    tools: list[dict] = []
    for spec in registry.get_all_tool_specs():
        schema = {"type": "object", "properties": {}}
        obj = spec.get("_tool_spec_obj")
        if obj is not None:
            try:
                schema = skill_loader.build_function_schema(
                    spec["skill"], obj)["function"]["parameters"]
            except Exception:
                logger.warning("工具 %s 参数 schema 生成失败，使用空参",
                               spec["full_name"], exc_info=True)
        tools.append({
            "name": mcp_tool_name(spec["skill"], spec["name"]),
            "description": spec.get("description")
                           or f"{spec['skill']}.{spec['name']}",
            "inputSchema": schema,
        })
    return tools


# ── tools/call ──

def _jsonable(out) -> str:
    """工具返回值 → JSON 文本。不可序列化的对象退化为 str。"""
    try:
        return json.dumps(out, ensure_ascii=False, default=str)
    except Exception:
        return json.dumps({"repr": repr(out)}, ensure_ascii=False)


async def invoke_mcp_tool(registry, index: dict, name: str,
                          arguments: dict | None) -> str:
    """MCP tools/call → 技能工具派发。同步工具丢线程池（不阻塞事件循环），
    协程工具走 call_tool_async（MCP 会话工具需要 await 外部资源）。
    任何异常都折返回错误载荷 —— 协议层不断连。"""
    hit = index.get(name)
    if not hit:
        return _jsonable({"success": False, "error": f"未知工具: {name}",
                          "hint": "tools/list 查看可用工具"})
    skill, tool = hit
    params = dict(arguments or {})
    try:
        if registry.is_async_tool(skill, tool):
            out = await registry.call_tool_async(skill, tool, params)
        else:
            out = await asyncio.to_thread(registry.call_tool, skill, tool, params)
        return _jsonable({"success": True, "tool": f"{skill}.{tool}",
                          "result": out})
    except Exception as e:  # noqa: BLE001 —— 错误必须可被调用方读到
        logger.warning("MCP 工具调用失败 %s.%s: %s", skill, tool, e,
                       exc_info=True)
        return _jsonable({"success": False, "tool": f"{skill}.{tool}",
                          "error": f"{type(e).__name__}: {e}"})


# ── 最小装配（工具可达所需，无 Web/线程副作用） ──

def build_context() -> dict:
    """构造技能依赖上下文 —— boot.create_application 的"工具可达"子集。

    刻意不做的事：Flask、视觉预热（要打真实 VLM 请求）、Obsidian MCP 消费桥
    （npx 子进程）、话题系统（对话上下文特性，与工具暴露无关）。
    """
    from apps.dsn_study.boot import _make_chat
    from apps.dsn_study.config import Config

    # 主模型（与 boot 同一工厂；工具里的 LLM 调用走同一凭据）
    model_type = str(Config.MAIN_MODEL_TYPE).lower()
    if model_type not in ("openai", "lmstudio", "llamacpp", "llama_cpp",
                          "gguf", "fast"):
        model_type = "openai"
    llm = None
    try:
        from apps.dsn_study.engine_support import LLMService
        llm = LLMService(_make_chat(model_type))
    except Exception:
        logger.warning("LLM 服务构造失败（模型类工具将不可用）", exc_info=True)

    # ── 数据库（题库主库承载学习域表，与 boot 一致） ──
    from apps.dsn_study.db.question_bank import QuestionBankDBManager
    from apps.dsn_study.db.plan_store import set_plan_db
    from apps.dsn_study.db.study_timetable import set_study_db

    db_path = os.path.abspath(Config.QUESTION_BANK_DB_PATH)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    db_mgr = QuestionBankDBManager(db_path=db_path)
    set_plan_db(db_mgr)
    set_study_db(db_mgr)

    from apps.dsn_study.db.checkin_store import CheckinStore
    from apps.dsn_study.tracking_lite import TrackingStore, StudyLog
    from apps.dsn_study.question_bank.store import QuestionStore
    from apps.dsn_study.question_bank.template_manager import SubjectTemplateManager
    from apps.dsn_study.question_bank.scanner_pipeline import ScannerPipeline
    from apps.dsn_study.exam_sim.engine import ExamEngine
    from apps.dsn_study.exam_sim.scorer import ExamScorer
    from apps.dsn_study.knowledge_graph.graph_store import GraphStore
    from apps.dsn_study.knowledge_graph.graph_engine import GraphEngine
    from apps.dsn_study.knowledge_graph.builder import KnowledgeGraphBuilder
    from apps.dsn_study.knowledge_graph.matcher import KnowledgeMatcher
    from apps.dsn_study.db.plan_store import PlanStore
    from apps.dsn_study.db.plan_engine import PlanEngine

    checkin_store = CheckinStore(db_mgr)
    tracking_db_dir = os.path.join(os.path.dirname(db_path), "tracking")
    os.makedirs(tracking_db_dir, exist_ok=True)
    tracking_store = TrackingStore(
        db_path=os.path.join(tracking_db_dir, "tracking.db"))

    question_store = QuestionStore(db_mgr)
    template_manager = SubjectTemplateManager(db_mgr)
    # 全新库初始化内置模板并应用默认科目（与 boot.create_application 一致，
    # 否则 create_question 这类工具会报「学科不存在，请先应用模板」）
    try:
        template_manager.init_builtin_templates()
        if not template_manager.has_subjects():
            template_manager.apply_template("6_subjects")
            logger.info("首次启动: 已应用默认科目模板 6_subjects")
    except Exception:
        logger.warning("内置科目模板初始化失败", exc_info=True)
    scorer = ExamScorer(question_store=question_store, models_plugin=llm)
    exam_engine = ExamEngine(db=db_mgr, question_store=question_store,
                             scorer=scorer)
    graph_store = GraphStore(db_mgr)
    graph_engine = GraphEngine(graph_store, models_plugin=llm)
    kg_builder = KnowledgeGraphBuilder(graph_store, models_plugin=llm)
    kg_matcher = KnowledgeMatcher(graph_store, models_plugin=llm)
    scanner_pipeline = ScannerPipeline(question_store=question_store,
                                       models_plugin=llm)
    plan_engine = PlanEngine(PlanStore(db_mgr))
    studylog = StudyLog(tracking_store, checkin_store=checkin_store,
                        plan_engine=plan_engine)

    # 任务管理器（提醒/习惯/日计划）。后台线程随进程存活，main() 退出时关闭。
    task_manager = None
    if Config.TASK_MANAGER_ENABLED:
        try:
            from apps.dsn_study.tasks import TaskManager
            task_manager = TaskManager(db_mgr, llm=llm,
                                       max_workers=int(Config.TASK_MAX_WORKERS))
        except Exception:
            logger.warning("TaskManager 装配失败（任务类工具将不可用）",
                           exc_info=True)

    # 记忆系统（study_memory 的 recall/save_memo 需要）。
    # 不接话题系统：那是"对话上下文"特性，MCP 暴露场景没有对话主链。
    memory_system = None
    if Config.MEMORY_ENABLED:
        try:
            from apps.dsn_study.memory import (
                MemorySystem, LLMSummaryModel, OpenAIEmbeddingClient,
            )
            embedding_client = None
            if Config.MEMORY_EMBEDDING_ENABLED:
                embedding_client = OpenAIEmbeddingClient(
                    base_url=(Config.MEMORY_EMBEDDING_BASE_URL
                              or Config.OPENAI_API_BASE),
                    api_key=Config.OPENAI_API_KEY,
                    model=Config.MEMORY_EMBEDDING_MODEL,
                )
            memory_system = MemorySystem(
                db_mgr, summary_model=LLMSummaryModel(llm),
                embedding_client=embedding_client)
        except Exception:
            logger.warning("记忆系统装配失败（memory 工具将不可用）",
                           exc_info=True)

    # 工作区（扫描件 / 下载落盘）
    workspace = None
    try:
        from apps.dsn_study.workspace import init_workspace_manager
        workspace = init_workspace_manager(Config.WORKSPACE_DIR)
    except Exception:
        logger.warning("工作区初始化失败（落盘类工具将不可用）", exc_info=True)

    complexity_analyzer = None
    try:
        from apps.dsn_study.tasks import ComplexityAnalyzer
        complexity_analyzer = ComplexityAnalyzer()
    except Exception:
        pass

    return {
        "db_mgr": db_mgr,
        "llm": llm,
        "question_store": question_store,
        "template_manager": template_manager,
        "scorer": scorer,
        "exam_engine": exam_engine,
        "graph_store": graph_store,
        "graph_engine": graph_engine,
        "kg_builder": kg_builder,
        "kg_matcher": kg_matcher,
        "scanner_pipeline": scanner_pipeline,
        "plan_engine": plan_engine,
        "studylog": studylog,
        "checkin_store": checkin_store,
        "task_manager": task_manager,
        "memory_system": memory_system,
        "cache_engine": None,           # 语义缓存是对话拦截特性，不装配
        "vision_coordinator": None,     # 视觉链路属 Web 侧长驻能力
        "workspace": workspace,
        "complexity_analyzer": complexity_analyzer,
    }


def build_skill_registry(c: dict):
    """能力注册 + 技能扫描 + 依赖注入 —— 复用 boot.py 的同一份实现。"""
    from apps.dsn_study.boot import (_build_skill_dep_map,
                                     _ensure_custom_skill_dir,
                                     _register_skill_capabilities)
    from apps.dsn_study.skills.manager import SkillManager
    from apps.dsn_study.skills.registry import SkillRegistry

    registry = SkillRegistry()
    _register_skill_capabilities(registry, c, c.get("workspace"))

    app_root = os.path.dirname(os.path.abspath(__file__))
    skill_dirs = [os.path.join(app_root, "skills", "builtin")]
    custom_dir = os.path.join(app_root, "skills", "custom")
    _ensure_custom_skill_dir(custom_dir)
    skill_dirs.append(custom_dir)

    manager = SkillManager(skill_dirs, registry)
    manager.set_legacy_deps(_build_skill_dep_map(c))
    loaded = manager.scan_and_load()
    logger.info("MCP 暴露侧技能加载完成: %d 个", loaded)
    return registry


# ── 入口 ──

def _setup_logging() -> None:
    # stdio 上跑的是 JSON-RPC：任何打到 stdout 的日志都会破坏协议流
    logging.basicConfig(
        level=logging.INFO, stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def build_all():
    """装配 → (registry, tool_index, context)。--check 与主服务共用。"""
    context = build_context()
    registry = build_skill_registry(context)
    return registry, build_tool_index(registry), context


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    _setup_logging()

    from apps.dsn_study.config import Config   # 导入即加载 .env

    if not getattr(Config, "MCP_EXPOSE_ENABLED", True):
        logger.error("MCP_EXPOSE_ENABLED=false —— 暴露侧 MCP 未启用")
        return 2

    registry, index, context = build_all()
    logger.info("MCP 暴露侧就绪: %d 个工具", len(index))

    if "--check" in argv:
        for name in sorted(index):
            print(name)          # --check 的输出就是给脚本消费的
        return 0

    try:
        from mcp.server.lowlevel import Server
        from mcp.server.stdio import stdio_server
        from mcp.types import TextContent, Tool
    except ImportError:
        logger.error("缺少 mcp SDK（pip install \"mcp>=1.2\"）—— 无法启动暴露侧服务")
        return 3

    server = Server("dsn-study")

    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        return [Tool(name=t["name"], description=t["description"],
                     inputSchema=t["inputSchema"])
                for t in list_mcp_tools(registry)]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict) -> list[TextContent]:
        payload = await invoke_mcp_tool(registry, index, name, arguments)
        return [TextContent(type="text", text=payload)]

    async def _serve() -> None:
        async with stdio_server() as (reader, writer):
            await server.run(reader, writer,
                             server.create_initialization_options())

    try:
        asyncio.run(_serve())
    except KeyboardInterrupt:
        logger.info("收到中断，退出")
    finally:
        tm = context.get("task_manager")
        if tm is not None:
            try:
                tm.shutdown()
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
