# engine.py
# DSNEngine — 核心引擎，聚合所有组件，供主应用和 SubApp 使用

from __future__ import annotations

import asyncio
import logging
import os
import threading
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, AsyncGenerator

import yaml

from subapp_loader import SubAppConfig
from config import Config
from chatdbmgr import ChatDBManager
from models import LMSummaryModel
from memory import MemoryManager
from tasks import TaskManager, TaskType, ComplexityAnalyzer

from plugins.base import PluginContext
from plugins.manager import PluginManager
from plugins.pipeline import ChatPipeline

from prompt import PromptEngine, PromptLibrary, PersonalitySystemV2

from skills.registry import SkillRegistry
from skills.manager import SkillManager

logger = logging.getLogger("DSNEngine")

_pipeline_cache: dict[str, ChatPipeline] = {}

_ENGINE_CONFIG_PATH = "engine.yaml"


@dataclass
class EngineConfig:
    """引擎级配置：控制哪些子系统启用"""
    deepseek_api_key: str = ""
    model_type: str = "deepseek"
    model_name: str = "deepseek-v4-flash"
    lmstudio_base_url: str = "http://localhost:4501"
    lmstudio_temperature: float = 0.7
    lmstudio_max_tokens: int = 4096
    lmstudio_timeout: int = 300
    database_path: str = "chats.db"
    memory_enabled: bool = True
    memory_summary_backend: str = "deepseek"
    memory_summary_length: int = 100
    task_manager_enabled: bool = True
    task_max_workers: int = 5
    agent_max_steps: int = 5
    agent_token_budget: int = 8000
    agent_timeout: float = 120.0

    @staticmethod
    def from_subapp(cfg: SubAppConfig) -> EngineConfig:
        return EngineConfig(
            deepseek_api_key=cfg.model_api_key or Config.DEEPSEEK_API_KEY,
            model_type=cfg.model_provider,
            model_name=cfg.model_name,
            lmstudio_base_url=cfg.lmstudio_base_url,
            lmstudio_temperature=cfg.model_temperature,
            lmstudio_max_tokens=cfg.model_max_tokens,
            lmstudio_timeout=cfg.model_timeout,
            database_path=cfg.database_path or f"subapp_{cfg.name}.db",
            memory_enabled=cfg.memory_enabled,
            memory_summary_length=cfg.memory_summary_length,
            task_manager_enabled=True,
            agent_max_steps=cfg.agent_max_steps,
            agent_token_budget=cfg.agent_token_budget,
            agent_timeout=cfg.agent_timeout,
        )


class DSNEngine:
    """
    DSN 核心引擎。

    用法:
        engine = DSNEngine(subapp_path="subapps/self_evolution")
        reply = engine.chat("你好", user_id=1)
        async for event in engine.chat_stream("你好", user_id=1):
            print(event)
    """

    def __init__(self, subapp_path: str | None = None):
        self._subapp_path = Path(subapp_path).resolve() if subapp_path else None
        self._cfg: Optional[SubAppConfig] = None
        self._engine_cfg: Optional[EngineConfig] = None

        self.db: Optional[ChatDBManager] = None
        self.memory_manager: Optional[MemoryManager] = None
        self.task_manager: Optional[TaskManager] = None
        self.summary_model: Optional[LMSummaryModel] = None

        self.plugin_manager = PluginManager()
        self.skill_registry = SkillRegistry()
        self.skill_manager: Optional[SkillManager] = None
        self.prompt_engine: Optional[PromptEngine] = None
        self.pipeline: Optional[ChatPipeline] = None

        self._logger = logger

        if self._subapp_path:
            self._init_from_subapp()

    # ── 初始化 ──

    def _init_from_subapp(self):
        from subapp_loader import load_subapp_config
        self._cfg = load_subapp_config(str(self._subapp_path))
        self._engine_cfg = EngineConfig.from_subapp(self._cfg)

        self._init_database()
        self._init_tasks()
        self._init_memory()
        self._init_skills()
        self._init_prompt()
        self._init_plugins()
        self._init_pipeline()

        self._logger.info("DSNEngine 初始化完成: %s", self._cfg.name)

    def _init_database(self):
        db_path = self._engine_cfg.database_path
        abs_path = self._cfg.resolve_path(db_path) if self._cfg else db_path
        self.db = ChatDBManager(db_path=abs_path)

    def _init_tasks(self):
        if not self._engine_cfg.task_manager_enabled:
            return
        try:
            import queue
            self._completion_queue = queue.Queue()
            self.task_manager = TaskManager(
                db=self.db,
                max_workers=self._engine_cfg.task_max_workers,
            )
            self.task_manager.completion_queue = self._completion_queue
            self._task_completion_thread = threading.Thread(
                target=self._process_task_completion, daemon=True
            )
            self._task_completion_thread.start()
            self._logger.info("TaskManager 初始化完成 (max_workers=%d)", self._engine_cfg.task_max_workers)
        except Exception as e:
            self._logger.warning("TaskManager 初始化失败: %s", e)

    _TASK_MAX_RETRY_DEPTH = 3

    def _process_task_completion(self):
        from tasks import TaskType
        while True:
            try:
                item = self._completion_queue.get()
                if item is None:
                    break
                task_id, result = item
                task = self.task_manager.get_task(task_id)
                if not task:
                    continue
                self._logger.info("任务完成: %s (type=%s)", task_id, task.task_type.value)
                if task.task_type == TaskType.ACTION:
                    retry_depth = 0
                    if hasattr(self.task_manager, '_retry_depths'):
                        if hasattr(self.task_manager, '_retry_lock'):
                            with self.task_manager._retry_lock:
                                retry_depth = self.task_manager._retry_depths.pop(task_id, 0)
                        else:
                            retry_depth = self.task_manager._retry_depths.pop(task_id, 0)
                    self._handle_engine_action_completion(task, result, retry_depth)
            except Exception as e:
                self._logger.error("任务完成通知处理失败: %s", e)

    def _handle_engine_action_completion(self, task, result, retry_depth: int = 0):
        if not result.get("requires_ai_notification", True):
            return
        try:
            ai_message = self._generate_result_message(task, result)
            if not ai_message:
                return
            self.db.append_messages(
                task.user_id, task.chat_id,
                [{"role": "assistant", "content": ai_message}],
            )
            if not result.get("success", False) and retry_depth < self._TASK_MAX_RETRY_DEPTH:
                self._retry_engine_action(ai_message, task, retry_depth)
        except Exception as e:
            self._logger.error("处理动作完成失败: %s", e)

    def _generate_result_message(self, task, result) -> str | None:
        try:
            from datetime import datetime
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            action_type = result.get("action_type", "unknown")
            success = result.get("success", False)
            output = result.get("output", "")
            error = result.get("error")
            preview = result.get("content_preview", "")[:100]

            prompt_text = f"""
现在时间是 {now}，之前执行的 {action_type} 操作已经完成。

命令预览：{preview}
执行结果：
- 成功：{success}
- 退出码：{result.get('exit_code', 'N/A')}
- 输出：{output[:500] if output else '无输出'}
- 错误：{error if error else '无'}

请根据这个结果生成回复。如果失败且可以纠正，使用 <task> 和 ```action``` 提供修正后的代码。
"""
            history = self.db.get_chat_history(task.user_id, task.chat_id)
            system_prompt = self.prompt_engine.build_system_prompt(
                {"uid": task.user_id, "nickname": f"用户{task.user_id}"}
            ) if self.prompt_engine else ""

            from models import DeepSeekChat
            chat = DeepSeekChat(api_key=self._engine_cfg.deepseek_api_key)
            chat.messages = [{"role": "system", "content": system_prompt}]
            recent = history[-5:] if len(history) > 5 else history
            for msg in recent:
                chat.messages.append(msg)
            chat.messages.append({"role": "user", "content": prompt_text})
            return chat.send_message("请生成回复")
        except Exception as e:
            self._logger.error("生成结果消息失败: %s", e)
            return None

    def _retry_engine_action(self, ai_message: str, task, retry_depth: int):
        from plugins.builtin.task_plugin import TaskPlugin
        from tasks import TaskType
        tasks = TaskPlugin._parse_tasks(ai_message)
        if not tasks:
            return
        self._logger.info("引擎自纠正: %d 个任务 (深度=%d)", len(tasks), retry_depth + 1)
        for task_data in tasks:
            if task_data.get("type") != "action":
                continue
            params = task_data.get("params", {})
            if "action_type" not in params:
                params["action_type"] = "shell"
            new_id = self.task_manager.create_task(
                task_type=TaskType.ACTION,
                user_id=task.user_id,
                chat_id=task.chat_id,
                params=params, priority=1,
            )
            self.task_manager.execute_task(new_id)
            if not hasattr(self.task_manager, '_retry_depths'):
                self.task_manager._retry_depths = {}
            if not hasattr(self.task_manager, '_retry_lock'):
                import threading as _thr
                self.task_manager._retry_lock = _thr.Lock()
            with self.task_manager._retry_lock:
                self.task_manager._retry_depths[new_id] = retry_depth + 1

    def _init_memory(self):
        if not self._engine_cfg.memory_enabled:
            return
        try:
            backend = self._engine_cfg.memory_summary_backend
            model_name = self._engine_cfg.model_name
            if backend == "deepseek":
                model_name = model_name or getattr(Config, 'MEMORY_MODEL', 'deepseek-v4-flash')

            self.summary_model = LMSummaryModel(
                backend=backend,
                base_url=self._engine_cfg.lmstudio_base_url,
                api_key=self._engine_cfg.deepseek_api_key,
                model_name=model_name,
                summary_length=self._engine_cfg.memory_summary_length,
            )
            self.memory_manager = MemoryManager(db=self.db, summary_model=self.summary_model)
        except Exception as e:
            self._logger.warning("Memory 初始化失败: %s", e)

    def _init_skills(self):
        skill_dirs = []
        if self._cfg and self._cfg.skills_dirs:
            for d in self._cfg.skills_dirs:
                skill_dirs.append(self._cfg.resolve_path(d))

        if not skill_dirs:
            return

        self.skill_manager = SkillManager(skill_dirs=skill_dirs, registry=self.skill_registry)
        try:
            loaded = self.skill_manager.scan_and_load()
            self._logger.info("Skills 加载完成: %d", loaded)
        except Exception as e:
            self._logger.warning("Skills 加载失败: %s", e)

    def _init_prompt(self):
        lib = PromptLibrary()
        peers = PersonalitySystemV2(db=self.db)

        core_dir = Path(__file__).parent / "prompt"

        lib.scan_and_load(
            str(core_dir / "prompts" / "core"),
            str(core_dir / "prompts" / "capabilities"),
        )

        if self._cfg and self._cfg.prompts_dirs:
            for d in self._cfg.prompts_dirs:
                abs_dir = self._cfg.resolve_path(d)
                if Path(abs_dir).exists():
                    lib.scan_and_load(abs_dir)

        v2_presets_dir = str(core_dir / "personality_v2" / "presets")
        peers.scan_presets(v2_presets_dir)
        peers.load_rules_from_files()

        loaded_preset = False
        if self._cfg and self._cfg.personality_file:
            pers_file = self._cfg.resolve_path(self._cfg.personality_file)
            if Path(pers_file).exists():
                try:
                    with open(pers_file, "r", encoding='utf-8-sig') as f:
                        pers_data = yaml.safe_load(f) or {}
                    preset_name = pers_data.get("name", Path(pers_file).stem)
                    if preset_name in [p["name"] for p in peers.list_presets()]:
                        peers.load_preset(0, preset_name)
                        loaded_preset = True
                except Exception:
                    pass
        if not loaded_preset and self._cfg and self._cfg.personality_preset:
            loaded_preset = peers.load_preset(0, self._cfg.personality_preset)
        if not loaded_preset:
            peers.load_preset(0, "default")

        self.prompt_engine = PromptEngine(library=lib, personality_v2=peers)
        self.prompt_engine.set_skill_registry(self.skill_registry)

    def _init_plugins(self):
        ec = self._engine_cfg
        enable_set = set(self._cfg.plugins_enable) if self._cfg else set()
        disable_set = set(self._cfg.plugins_disable) if self._cfg else set()

        # 决定哪些插件启用
        def enabled(name: str) -> bool:
            if enable_set:
                return name in enable_set
            if disable_set:
                return name not in disable_set
            return True

        # ---- 创建插件（按依赖顺序） ----

        # 1. ModelsPlugin (MODEL_INVOKE, priority 50)
        if enabled("models"):
            from plugins.builtin.models_plugin import ModelsPlugin
            models_plugin = ModelsPlugin(
                model_type=ec.model_type,
                deepseek_api_key=ec.deepseek_api_key,
                lmstudio_base_url=ec.lmstudio_base_url,
                lmstudio_model_name=ec.model_name,
                lmstudio_temperature=ec.lmstudio_temperature,
                lmstudio_max_tokens=ec.lmstudio_max_tokens,
                lmstudio_timeout=ec.lmstudio_timeout,
                db=self.db,
            )
            self.plugin_manager.register(models_plugin)
            self._models_plugin = models_plugin
        else:
            self._models_plugin = None

        # 2. MemoryPlugin (PRE_PROCESS + POST_PROCESS, priority 30)
        if enabled("memory"):
            from plugins.builtin.memory_plugin import MemoryPlugin
            self.plugin_manager.register(MemoryPlugin(
                memory_manager=self.memory_manager,
                db=self.db,
            ))

        # 3. RecallPlugin (POST_PROCESS, priority 33)
        if enabled("recall") and self.memory_manager:
            try:
                from plugins.builtin.recall_plugin import RecallPlugin
                from memory_recall import MemoryRecallEngine
                recall_engine = MemoryRecallEngine(db=self.db)
                self.plugin_manager.register(RecallPlugin(recall_engine=recall_engine))
            except Exception as e:
                self._logger.warning("RecallPlugin 加载失败: %s", e)

        # 4. SkillsPlugin (POST_PROCESS, priority 35)
        if enabled("skills"):
            from plugins.builtin.skills_plugin import SkillsPlugin
            self.plugin_manager.register(SkillsPlugin(
                skill_registry=self.skill_registry,
            ))

        # 5. AgentPlugin (POST_PROCESS, priority 35)
        if enabled("agent"):
            from plugins.builtin.agent_plugin import AgentPlugin
            self.plugin_manager.register(AgentPlugin(
                skill_registry=self.skill_registry,
                models_plugin=self._models_plugin,
                max_steps=ec.agent_max_steps,
                token_budget=ec.agent_token_budget,
                agent_timeout=ec.agent_timeout,
            ))

        # 5b. TaskPlugin (POST_PROCESS, priority 40)
        if enabled("task") and self.task_manager:
            from plugins.builtin.task_plugin import TaskPlugin
            self.plugin_manager.register(TaskPlugin(
                task_manager=self.task_manager,
                db=self.db,
                skill_registry=self.skill_registry,
            ))

        # 6. DistillPlugin (POST_PROCESS, priority 100)
        if enabled("distill") and self.skill_manager and self._models_plugin:
            try:
                from plugins.builtin.distill_plugin import DistillPlugin
                from skills.distill import DistillationEngine
                distill_engine = DistillationEngine(
                    db=self.db,
                    skill_manager=self.skill_manager,
                    llm_client=None,
                )
                self.plugin_manager.register(DistillPlugin(
                    distillation_engine=distill_engine,
                ))
            except Exception as e:
                self._logger.warning("DistillPlugin 加载失败: %s", e)

    def _init_pipeline(self):
        self.pipeline = ChatPipeline(
            plugin_manager=self.plugin_manager,
            prompt_engine=self.prompt_engine,
        )

    # ── 对话接口 ──

    def build_context(self, user_id: int, message: str,
                      chat_id: int | None = None,
                      chat_name: str = "未命名",
                      history: list | None = None,
                      model_type: str | None = None,
                      nickname: str = "用户",
                      **kwargs) -> PluginContext:
        """构建 PluginContext"""
        return PluginContext(
            user_id=user_id,
            message=message,
            chat_id=chat_id,
            chat_name=chat_name,
            history=history or [],
            model_type=model_type or self._engine_cfg.model_type,
            nickname=nickname,
            agent_active=kwargs.get("agent_active", False),
            agent_max_steps=kwargs.get("agent_max_steps", self._engine_cfg.agent_max_steps),
            agent_token_budget=kwargs.get("agent_token_budget", self._engine_cfg.agent_token_budget),
        )

    def chat(self, message: str, user_id: int = 1,
             chat_id: int | None = None, chat_name: str = "未命名",
             history: list | None = None, model_type: str | None = None,
             nickname: str = "用户", **kwargs) -> dict:
        """同步对话"""
        if history is not None and not history and chat_id and self.db:
            history = self.db.get_chat_history(user_id, chat_id)

        if chat_id is None and self.db:
            chat_id = self.db.create_chat(user_id, chat_name)

        ctx = self.build_context(
            user_id=user_id, message=message,
            chat_id=chat_id, chat_name=chat_name,
            history=history or [], model_type=model_type,
            nickname=nickname, **kwargs
        )

        loop = asyncio.new_event_loop()
        try:
            result_ctx = loop.run_until_complete(self.pipeline.process(ctx))
        finally:
            loop.close()

        return {
            "reply": result_ctx.reply,
            "original_reply": result_ctx.original_reply,
            "chat_id": result_ctx.chat_id,
            "audio_b64": result_ctx.audio_b64,
            "tts_error": result_ctx.tts_error,
            "filtered": result_ctx.filtered,
            "extra": result_ctx.extra,
        }

    async def chat_stream(self, message: str, user_id: int = 1,
                          chat_id: int | None = None, chat_name: str = "未命名",
                          history: list | None = None, model_type: str | None = None,
                          nickname: str = "用户", **kwargs) -> AsyncGenerator[str, None]:
        """异步流式对话"""
        if history is not None and not history and chat_id and self.db:
            history = self.db.get_chat_history(user_id, chat_id)

        if chat_id is None and self.db:
            chat_id = self.db.create_chat(user_id, chat_name)

        ctx = self.build_context(
            user_id=user_id, message=message,
            chat_id=chat_id, chat_name=chat_name,
            history=history or [], model_type=model_type,
            nickname=nickname, **kwargs
        )

        async for event in self.pipeline.process_stream(ctx):
            yield event

    def create_chat(self, user_id: int, chat_name: str = "未命名") -> int:
        return self.db.create_chat(user_id, chat_name) if self.db else 0

    def get_history(self, user_id: int, chat_id: int) -> list:
        return self.db.get_chat_history(user_id, chat_id) if self.db else []

    # ── 定时调度 ──

    def run_scheduled(self):
        """按配置的 cron 表达式执行定时对话"""
        if not self._cfg or not self._cfg.schedule_cron:
            self._logger.warning("无定时配置，无法启动调度")
            return

        import schedule
        import time

        cron_expr = self._cfg.schedule_cron
        prompt = self._cfg.schedule_prompt

        def job():
            self._logger.info("定时任务触发: %s", prompt)
            try:
                result = self.chat(message=prompt, user_id=0, chat_name="scheduled")
                self._logger.info("定时任务完成: %s", result.get("reply", "")[:100])
            except Exception as e:
                self._logger.error("定时任务失败: %s", e)

        # 支持简单的 cron 解析
        parts = cron_expr.strip().split()
        if len(parts) == 5:
            minute, hour, day, month, weekday = parts
            if weekday != "*":
                schedule.every().day.at(f"{hour.zfill(2)}:{minute.zfill(2)}").do(job)
            if day != "*":
                pass  # 简化：仅支持每日
            else:
                schedule.every().day.at(f"{hour.zfill(2)}:{minute.zfill(2)}").do(job)
        else:
            schedule.every().day.at("09:00").do(job)

        self._logger.info("定时调度已启动: %s → %s", cron_expr, prompt[:50])
        while True:
            schedule.run_pending()
            time.sleep(30)

    # ── 实用方法 ──

    def get_info(self) -> dict:
        return {
            "name": self._cfg.name if self._cfg else "bare",
            "version": self._cfg.version if self._cfg else "0",
            "model": self._engine_cfg.model_name if self._engine_cfg else "",
            "plugins": self.plugin_manager.list_plugins(),
            "skills": self.skill_registry.list_skills() if self.skill_registry else [],
            "prompt_entries": self.prompt_engine.library.list_entries() if self.prompt_engine else [],
        }


# ── 便捷工厂 ──

def create_engine(subapp_path: str | None = None) -> DSNEngine:
    """
    创建引擎实例的便捷入口。

    :param subapp_path: subapp 目录路径。为 None 时创建一个裸引擎（仅基础组件）。
    """
    return DSNEngine(subapp_path=subapp_path)


def create_engine_with_defaults(
    db: ChatDBManager = None,
    memory_manager: MemoryManager = None,
    skill_registry: SkillRegistry = None,
    skill_manager: SkillManager = None,
) -> DSNEngine:
    """
    使用已有组件创建引擎（供 app.py 复用）。

    用于主 Flask 应用场景：引擎直接引用 app.py 中已初始化的 db/memory/skills 等实例，
    无需重新初始化。
    """
    import os as _os
    from prompt import init_prompt_engine, PromptLibrary, PersonalitySystemV2

    engine = DSNEngine()
    engine.db = db

    if memory_manager:
        engine.memory_manager = memory_manager

    if skill_registry:
        engine.skill_registry = skill_registry
    if skill_manager:
        engine.skill_manager = skill_manager

    # PromptEngine — v2
    _prompt_dir = _os.path.join(_os.path.dirname(__file__), "prompt")
    pers_v2 = PersonalitySystemV2(db=db)
    pers_v2.scan_presets(_os.path.join(_prompt_dir, "personality_v2", "presets"))
    pers_v2.load_rules_from_files()
    lib = PromptLibrary()
    lib.scan_and_load(
        _os.path.join(_prompt_dir, "prompts", "core"),
        _os.path.join(_prompt_dir, "prompts", "capabilities"),
        _os.path.join(_prompt_dir, "prompts", "extensions"),
    )
    engine.prompt_engine = PromptEngine(library=lib, personality_v2=pers_v2)
    if skill_registry:
        engine.prompt_engine.set_skill_registry(skill_registry)

    # 注册核心插件
    from plugins.builtin.models_plugin import ModelsPlugin
    from config import Config

    models_plugin = ModelsPlugin(
        model_type=Config.MAIN_MODEL_TYPE,
        deepseek_api_key=Config.DEEPSEEK_API_KEY,
        lmstudio_base_url=Config.LMSTUDIO_BASE_URL,
        lmstudio_model_name=Config.MAIN_MODEL_NAME,
        lmstudio_temperature=Config.LMSTUDIO_TEMPERATURE,
        lmstudio_max_tokens=Config.LMSTUDIO_MAX_TOKENS,
        lmstudio_timeout=Config.LMSTUDIO_TIMEOUT,
        db=db,
    )
    engine.plugin_manager.register(models_plugin)

    if memory_manager and db:
        from plugins.builtin.memory_plugin import MemoryPlugin
        engine.plugin_manager.register(MemoryPlugin(memory_manager=memory_manager, db=db))

    if skill_registry:
        from plugins.builtin.skills_plugin import SkillsPlugin
        engine.plugin_manager.register(SkillsPlugin(skill_registry=skill_registry))

        from plugins.builtin.agent_plugin import AgentPlugin
        engine.plugin_manager.register(AgentPlugin(
            skill_registry=skill_registry,
            models_plugin=models_plugin,
        ))

    engine._init_pipeline()
    engine._logger.info("DSNEngine 已从默认配置创建（复用 app.py 组件）")
    return engine
