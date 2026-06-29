# engine.py
# DSNEngine — 核心引擎，聚合所有组件，供主应用和 SubApp 使用

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, AsyncGenerator

import yaml

from utils.subapp_loader import SubAppConfig
from config import Config
from db.chat import ChatDBManager
from models import LMSummaryModel, EmbeddingClient
from models.tts_process import TTSProcessModel
from memory import MemorySystem
from tasks import TaskManager, TaskType, ComplexityAnalyzer

from plugins.base import PluginContext
from plugins.manager import PluginManager
from plugins.pipeline import ChatPipeline

from prompt import PromptEngine, PromptLibrary, PersonalitySystemV2

from skills.registry import SkillRegistry
from skills.manager import SkillManager

logger = logging.getLogger("DSNEngine")

_pipeline_cache: dict[str, ChatPipeline] = {}

# 持久事件循环，避免每次同步 chat() 调用创建/销毁
_engine_loop: asyncio.AbstractEventLoop | None = None
_engine_loop_lock = threading.Lock()


def _get_event_loop() -> asyncio.AbstractEventLoop:
    global _engine_loop
    if _engine_loop is None or _engine_loop.is_closed():
        with _engine_loop_lock:
            if _engine_loop is None or _engine_loop.is_closed():
                _engine_loop = asyncio.new_event_loop()
    return _engine_loop

_ENGINE_CONFIG_PATH = "engine.yaml"


@dataclass
class EngineConfig:
    """引擎级配置：控制哪些子系统启用"""
    deepseek_api_key: str = Config.DEEPSEEK_API_KEY
    model_type: str = Config.MAIN_MODEL_TYPE
    model_name: str = Config.MAIN_MODEL_NAME
    lmstudio_base_url: str = Config.LMSTUDIO_BASE_URL
    lmstudio_temperature: float = Config.LMSTUDIO_TEMPERATURE
    lmstudio_max_tokens: int = Config.LMSTUDIO_MAX_TOKENS
    lmstudio_timeout: int = Config.LMSTUDIO_TIMEOUT
    database_path: str = Config.DATABASE_PATH
    memory_enabled: bool = Config.MEMORY_ENABLED
    memory_summary_backend: str = Config.MEMORY_SUMMARY_BACKEND
    memory_summary_length: int = Config.MEMORY_SUMMARY_LENGTH
    task_manager_enabled: bool = Config.TASK_MANAGER_ENABLED
    task_max_workers: int = Config.TASK_MAX_WORKERS
    agent_active: bool = True
    agent_max_steps: int = Config.AGENT_MAX_STEPS
    agent_token_budget: int = 1000000
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
            agent_active=cfg.agent_active,
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
        self.memory_system: Optional[MemorySystem] = None
        self.task_manager: Optional[TaskManager] = None
        self.summary_model: Optional[LMSummaryModel] = None
        self.impression_manager = None
        self.world_engine = None
        self.world_state_manager = None
        self.narrative_model = None

        self.plugin_manager = PluginManager()
        self.skill_registry = SkillRegistry()
        self.skill_manager: Optional[SkillManager] = None
        self.prompt_engine: Optional[PromptEngine] = None
        self.prompt_cache = None  # PromptCache 实例
        self.pipeline: Optional[ChatPipeline] = None

        self._models_plugin = None
        self._tts_client = None
        self._tts_profile_mgr = None
        self._tts_process_model = None
        self._tts_available = False
        self._filter_model = None
        self.complexity_analyzer: Optional[ComplexityAnalyzer] = None

        self._logger = logger

        if self._subapp_path:
            self._init_from_subapp()

    # ── 初始化 ──

    def _init_from_subapp(self):
        from utils.subapp_loader import load_subapp_config
        self._cfg = load_subapp_config(str(self._subapp_path))
        self._engine_cfg = EngineConfig.from_subapp(self._cfg)

        self._init_database()
        self._init_tasks()
        self._init_memory()
        self._init_world()
        self._init_tts()
        self._init_skills()
        self._init_prompt()
        self._init_plugins()
        self._init_pipeline()

        self._logger.info("DSNEngine 初始化完成: %s", self._cfg.name)

    def _init_database(self):
        db_path = self._engine_cfg.database_path
        abs_path = self._cfg.resolve_path(db_path) if self._cfg else db_path
        self.db = ChatDBManager(db_path=abs_path)
        from prompt.impression import ImpressionManager
        self.impression_manager = ImpressionManager(db=self.db)

    def _init_tasks(self):
        if not self._engine_cfg.task_manager_enabled:
            return
        try:
            import queue
            self._completion_queue = queue.Queue()
            self._task_completion_stop = threading.Event()
            self.task_manager = TaskManager(
                db=self.db,
                max_workers=self._engine_cfg.task_max_workers,
            )
            self.task_manager.completion_queue = self._completion_queue
            self._task_completion_thread = threading.Thread(
                target=self._process_task_completion, daemon=True
            )
            self._task_completion_thread.start()
            self.complexity_analyzer = ComplexityAnalyzer()
            self._logger.info("TaskManager 初始化完成 (max_workers=%d)", self._engine_cfg.task_max_workers)
        except Exception as e:
            self._logger.warning("TaskManager 初始化失败: %s", e)

    _TASK_MAX_RETRY_DEPTH = 3

    def _process_task_completion(self):
        from tasks import TaskType
        while not self._task_completion_stop.is_set():
            try:
                item = self._completion_queue.get(timeout=1.0)
                if item is None:
                    break
                task_id, result = item
                task = self.task_manager.get_task(task_id)
                if not task:
                    continue
                self._logger.info("任务完成: %s (type=%s)", task_id, task.task_type.value)
                self._dispatch_task_completion(task, result)
            except Exception as e:
                self._logger.error("任务完成通知处理失败: %s", e)

    def _dispatch_task_completion(self, task, result):
        from tasks import TaskType
        if task.task_type == TaskType.REMINDER:
            self._handle_reminder_completion(task, result)
        elif task.task_type == TaskType.REASONER:
            self._handle_reasoner_completion(task, result)
        elif task.task_type == TaskType.ACTION:
            retry_depth = 0
            with self.task_manager._retry_lock:
                retry_depth = self.task_manager._retry_depths.pop(task.task_id, 0)
            self._handle_engine_action_completion(task, result, retry_depth)

    def _handle_engine_action_completion(self, task, result, retry_depth: int = 0):
        if not result.get("requires_ai_notification", True):
            return
        # pipeline 已在 SSE 流中处理过，避免重复
        if getattr(task, "handled_by_pipeline", False):
            self._logger.debug("任务 %s 已被 pipeline 处理，跳过引擎处理", task.task_id[:8])
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

    def _handle_reminder_completion(self, task, result):
        self._logger.info("提醒任务到期: task_id=%s", task.task_id)
        short_id = task.task_id[:8]
        reminder_text = result.get("reminder_text", "提醒时间到了！")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        msg = f"[系统] ⏰ 提醒（ID: {short_id}）\n现在是 {now}，你之前设置的提醒：{reminder_text}"
        try:
            self.db.append_messages(task.user_id, task.chat_id, [{"role": "system", "content": msg}])
        except Exception as e:
            self._logger.error("保存提醒消息失败: %s", e)

    def _handle_reasoner_completion(self, task, result):
        self._logger.info("推理任务完成: task_id=%s", task.task_id)
        short_id = task.task_id[:8]
        conclusion = result.get("conclusion", "")
        if conclusion:
            msg = f"[系统] 推理任务完成（ID: {short_id}）。\n结论: {conclusion}"
        else:
            reasoning = result.get("reasoning", "")
            msg = f"[系统] 推理任务完成（ID: {short_id}）。\n{reasoning[:2000]}"
        try:
            self.db.append_messages(task.user_id, task.chat_id, [{"role": "system", "content": msg}])
        except Exception as e:
            self._logger.error("保存推理结果失败: %s", e)

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

            if self._engine_cfg.model_type == "lmstudio":
                from models import LMStudioChat
                chat = LMStudioChat(
                    base_url=self._engine_cfg.lmstudio_base_url,
                    model_name=self._engine_cfg.model_name,
                    temperature=self._engine_cfg.lmstudio_temperature,
                    max_tokens=self._engine_cfg.lmstudio_max_tokens,
                    timeout=self._engine_cfg.lmstudio_timeout,
                )
            else:
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
            with self.task_manager._retry_lock:
                self.task_manager._retry_depths[new_id] = retry_depth + 1

    def _init_memory(self):
        if not self._engine_cfg.memory_enabled:
            return
        try:
            backend = self._engine_cfg.memory_summary_backend
            model_name = getattr(Config, 'MEMORY_MODEL', None) or self._engine_cfg.model_name

            self.summary_model = LMSummaryModel(
                backend=backend,
                base_url=self._engine_cfg.lmstudio_base_url,
                api_key=self._engine_cfg.deepseek_api_key,
                model_name=model_name,
                summary_length=self._engine_cfg.memory_summary_length,
            )
            embedding_client = None
            if Config.MEMORY_EMBEDDING_ENABLED:
                try:
                    embedding_client = EmbeddingClient(
                        base_url=self._engine_cfg.lmstudio_base_url,
                    )
                except Exception as e:
                    self._logger.warning("EmbeddingClient 初始化失败: %s", e)
            self.memory_system = MemorySystem(
                db=self.db,
                summary_model=self.summary_model,
                embedding_client=embedding_client,
            )
        except Exception as e:
            self._logger.warning("Memory 初始化失败: %s", e)

    def _init_world(self):
        if not Config.WORLD_ENABLED:
            return
        try:
            from world import WorldEngine, WorldStateManager, NarrativeModel
            preset_path = Path(__file__).parent / "world" / "worlds" / f"{Config.WORLD_PRESET}.yaml"
            self.world_engine = WorldEngine()
            self.world_engine.load_config_file(str(preset_path))
            self.world_state_manager = WorldStateManager(self.world_engine, Config.WORLD_UPDATE_INTERVAL)
            self.world_state_manager.start()
            if Config.NARRATIVE_ENABLED:
                self.narrative_model = NarrativeModel(
                    model_type=Config.NARRATIVE_MODEL_TYPE,
                    model_name=Config.NARRATIVE_MODEL,
                    api_key=Config.DEEPSEEK_API_KEY,
                    base_url=Config.LMSTUDIO_BASE_URL if Config.NARRATIVE_MODEL_TYPE == "lmstudio" else None,
                    temperature=Config.NARRATIVE_TEMPERATURE,
                    max_tokens=Config.NARRATIVE_MAX_TOKENS,
                    keep_history=Config.NARRATIVE_KEEP_HISTORY,
                )
                prompt_path = Path(__file__).parent / "prompt" / "world" / "narrative.md"
                self.narrative_model.load_system_prompt_file(str(prompt_path))
            self._logger.info("World/Narrative 初始化完成 (world=%s, narrative=%s)",
                              Config.WORLD_PRESET, "enabled" if self.narrative_model else "disabled")
        except Exception as e:
            self._logger.warning("World/Narrative 初始化失败: %s", e)

    def _init_tts(self):
        try:
            from audio.infer import VocalExp
            from plugins.builtin.tts_profile import TTSProfileManager
            self._tts_client = VocalExp(Config.TTS_BASE_URL)
            self._tts_profile_mgr = TTSProfileManager()
            self._tts_available = True
            self._logger.info("TTS 客户端初始化完成")

            if Config.TTS_PROCESS_ENABLED:
                self._tts_process_model = TTSProcessModel()
                self._logger.info("TTSProcessModel 初始化完成")
        except Exception as e:
            self._logger.warning("TTS 初始化失败: %s", e)
            self._tts_client = None
            self._tts_profile_mgr = None
            self._tts_available = False

    def _init_skills(self):
        skill_dirs = []
        if self._cfg and self._cfg.skills_dirs:
            for d in self._cfg.skills_dirs:
                skill_dirs.append(self._cfg.resolve_path(d))

        if not skill_dirs:
            return

        self.skill_manager = SkillManager(skill_dirs=skill_dirs,
                                          registry=self.skill_registry)
        try:
            loaded = self.skill_manager.scan_and_load()
            self._logger.info("Skills 加载完成: %d", loaded)

            # 注入系统技能依赖
            self._inject_system_skill_deps()

            self._inject_v3_to_exa_evolution()
        except Exception as e:
            self._logger.warning("Skills 加载失败: %s", e)

    def _inject_system_skill_deps(self):
        """注入运行时依赖到系统技能工具类"""
        try:
            # 注入 NotebookStore
            from plugins.builtin.notebook.notebook_store import NotebookStore
            nb_store = NotebookStore()

            # 注入 PlanEngine
            plan_engine = None
            try:
                from db.plan_store import PlanStore
                from db.plan_engine import PlanEngine
                plan_engine = PlanEngine(PlanStore(self.db))
            except Exception:
                pass

            for key, instance in list(self.skill_registry._tool_instances.items()):
                if not key.startswith("system."):
                    continue
                cls = type(instance)
                if not hasattr(cls, '_ctx'):
                    continue
                cls._ctx["task_manager"] = self.task_manager
                cls._ctx["db"] = self.db
                cls._ctx["memory_system"] = self.memory_system
                cls._ctx["notebook_store"] = nb_store
                cls._ctx["plan_engine"] = plan_engine
                cls._ctx["prompt_cache"] = self.prompt_cache
                cls._ctx["impression_manager"] = self.impression_manager
            self._logger.info("系统技能依赖注入完成")
        except Exception as e:
            self._logger.warning("系统技能依赖注入失败: %s", e)

    def _inject_v3_to_exa_evolution(self):
        """将 V3 引用注入到 SkillRegistry 中的 personality_materials 工具实例"""
        try:
            v3 = self.prompt_engine.personality_v3 if self.prompt_engine else None
            if not v3:
                self._logger.warning("PersonalityMaterials: V3 未初始化，跳过注入")
                return
            for key, instance in self.skill_registry._tool_instances.items():
                if key.startswith("personality_materials."):
                    instance._v3 = v3
                    self._logger.info("PersonalityMaterials: V3 已注入到 %s", key)
        except Exception as e:
            self._logger.warning("PersonalityMaterials: 注入 V3 失败: %s", e)

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

        # 初始化提示词缓存
        from prompt.prompt_cache import PromptCache
        embedding_client = None
        if Config.MEMORY_EMBEDDING_ENABLED:
            embedding_client = EmbeddingClient()
        self.prompt_cache = PromptCache(db=self.db, embedding_client=embedding_client)

    def _init_plugins(self):
        ec = self._engine_cfg
        self._enable_set = set(self._cfg.plugins_enable) if self._cfg else set()
        self._disable_set = set(self._cfg.plugins_disable) if self._cfg else set()

        self._register_filter_plugins()
        self._register_model_plugin()
        self._register_context_plugins()
        self._register_personality_plugins()
        self._register_execution_plugins()
        self._register_output_plugins()

        # 注入 skill_registry 到 ModelsPlugin (供 tool call schema 生成)
        if self._models_plugin and self.skill_registry:
            self._models_plugin.set_skill_registry(self.skill_registry)

        # 补注入 prompt_cache (此时 _init_prompt 已完成)
        self._inject_system_skill_deps()

    def _plugin_enabled(self, name: str) -> bool:
        if self._enable_set:
            return name in self._enable_set
        if self._disable_set:
            return name not in self._disable_set
        return True

    def _register_filter_plugins(self):
        if not self._plugin_enabled("asr_filter"):
            return
        from plugins.builtin.asr_filter_plugin import ASRFilterPlugin
        self.plugin_manager.register(ASRFilterPlugin(
            filter_model=self._filter_model,
            db=self.db,
        ))

    def _register_model_plugin(self):
        if not self._plugin_enabled("models"):
            self._models_plugin = None
            return
        from plugins.builtin.models_plugin import ModelsPlugin
        self._models_plugin = ModelsPlugin(
            model_type=self._engine_cfg.model_type,
            deepseek_api_key=self._engine_cfg.deepseek_api_key,
            lmstudio_base_url=self._engine_cfg.lmstudio_base_url,
            lmstudio_model_name=self._engine_cfg.model_name,
            lmstudio_temperature=self._engine_cfg.lmstudio_temperature,
            lmstudio_max_tokens=self._engine_cfg.lmstudio_max_tokens,
            lmstudio_timeout=self._engine_cfg.lmstudio_timeout,
            db=self.db,
        )
        self.plugin_manager.register(self._models_plugin)

    def _register_context_plugins(self):
        if self._plugin_enabled("memory"):
            from plugins.builtin.memory_plugin import MemoryPlugin
            self.plugin_manager.register(MemoryPlugin(
                memory_system=self.memory_system, db=self.db,
            ))
        if self._plugin_enabled("notebook"):
            from plugins.builtin.notebook import NotebookPlugin
            self.plugin_manager.register(NotebookPlugin())
        if self._plugin_enabled("vision") and self._models_plugin:
            from plugins.builtin.vision_plugin import VisionPlugin
            self.plugin_manager.register(VisionPlugin(models_plugin=self._models_plugin))
        if self._plugin_enabled("world") and self.world_engine:
            from world import WorldPlugin
            self.plugin_manager.register(WorldPlugin(
                world_engine=self.world_engine,
                world_state_manager=self.world_state_manager,
                narrative_model=self.narrative_model,
                personality_v2=self.prompt_engine.personality_v2 if self.prompt_engine else None,
            ))

    def _register_personality_plugins(self):
        if self._plugin_enabled("personality"):
            pe = self.prompt_engine
            if pe and pe.personality_v3 and pe.personality_v3.enabled:
                from plugins.builtin.personality_v3_plugin import PersonalityV3Plugin
                self.plugin_manager.register(PersonalityV3Plugin(
                    personality_v3=pe.personality_v3,
                ))
            elif pe and pe.personality_v2:
                from plugins.builtin.personality_plugin import PersonalityPlugin
                self.plugin_manager.register(PersonalityPlugin(
                    personality_v2=pe.personality_v2,
                ))
        if self._plugin_enabled("impression"):
            from plugins.builtin.impression_plugin import ImpressionPlugin
            self.plugin_manager.register(ImpressionPlugin(
                impression_manager=self.impression_manager,
            ))
        if self._plugin_enabled("confirm"):
            from plugins.builtin.confirm_plugin import ConfirmPlugin
            self.plugin_manager.register(ConfirmPlugin())

    def _register_execution_plugins(self):
        if self._plugin_enabled("recall") and self.memory_system:
            try:
                from plugins.builtin.recall_plugin import RecallPlugin
                self.plugin_manager.register(RecallPlugin(
                    memory_system=self.memory_system,
                ))
            except Exception as e:
                self._logger.warning("RecallPlugin 加载失败: %s", e)
        if self._plugin_enabled("tool") or self._plugin_enabled("skills") or self._plugin_enabled("agent"):
            from plugins.builtin.tool_plugin import ToolPlugin
            self.plugin_manager.register(ToolPlugin(
                skill_registry=self.skill_registry,
            ))
        if self._plugin_enabled("ssp"):
            from plugins.builtin.ssp_plugin import SSPPlugin
            self.plugin_manager.register(SSPPlugin(
                db=self.db, impression_manager=self.impression_manager,
                models_plugin=self._models_plugin, skill_registry=self.skill_registry,
            ))
        if self._plugin_enabled("task") and self.task_manager:
            from plugins.builtin.task_plugin import TaskPlugin
            self.plugin_manager.register(TaskPlugin(
                task_manager=self.task_manager, db=self.db,
                skill_registry=self.skill_registry,
            ))
        if self._plugin_enabled("todo") and self._models_plugin:
            from plugins.builtin.todo_plugin import TodoPlugin
            self.plugin_manager.register(TodoPlugin(
                models_plugin=self._models_plugin,
                complexity_analyzer=self.complexity_analyzer,
                skill_registry=self.skill_registry, db=self.db,
            ))
        if self._plugin_enabled("plan"):
            from plugins.builtin.plan_plugin import PlanPlugin
            self.plugin_manager.register(PlanPlugin(db=self.db))
        if self._plugin_enabled("help") and self.prompt_cache:
            from plugins.builtin.help_plugin import HelpPlugin
            self.plugin_manager.register(HelpPlugin(prompt_cache=self.prompt_cache))

    def _register_output_plugins(self):
        if self._plugin_enabled("tts") and self._tts_client:
            from plugins.builtin.tts_plugin import TTSPlugin
            self.plugin_manager.register(TTSPlugin(
                tts_client=self._tts_client,
                profile_manager=self._tts_profile_mgr,
                tts_process_model=self._tts_process_model,
            ))
        if self._plugin_enabled("distill") and self.skill_manager and self._models_plugin:
            try:
                from plugins.builtin.distill_plugin import DistillPlugin
                from skills.distill import DistillationEngine
                from models import DeepSeekChat
                _skill_distill_llm = DeepSeekChat(api_key=self._engine_cfg.deepseek_api_key)
                self.plugin_manager.register(DistillPlugin(
                    distillation_engine=DistillationEngine(
                        db=self.db, skill_manager=self.skill_manager,
                        llm_client=_skill_distill_llm,
                    ),
                    v3_system=self.prompt_engine.personality_v3 if self.prompt_engine else None,
                    card_id=self._cfg.card_id if self._cfg else "exa",
                ))
            except Exception as e:
                self._logger.warning("DistillPlugin 加载失败: %s", e)

    def _init_pipeline(self):
        self.pipeline = ChatPipeline(
            plugin_manager=self.plugin_manager,
            prompt_engine=self.prompt_engine,
            tts_client=self._tts_client,
            tts_profile_mgr=self._tts_profile_mgr,
            tts_process_model=self._tts_process_model,
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
        ec = self._engine_cfg
        ctx = PluginContext(
            user_id=user_id,
            message=message,
            chat_id=chat_id,
            chat_name=chat_name,
            history=history or [],
            model_type=model_type or (ec.model_type if ec else "deepseek"),
            nickname=nickname,
            is_asr_input=kwargs.get("is_asr_input", False),
            tts_enabled=kwargs.get("tts_enabled", True),
            image_data=kwargs.get("image_data"),
            agent_active=kwargs.get("agent_active", ec.agent_active if ec else True),
            agent_max_steps=kwargs.get("agent_max_steps", ec.agent_max_steps if ec else Config.AGENT_MAX_STEPS),
            agent_token_budget=kwargs.get("agent_token_budget", ec.agent_token_budget if ec else 1000000),
        )
        if self.task_manager:
            ctx.extra["_task_manager"] = self.task_manager
        if hasattr(self, '_completion_queue'):
            ctx.extra["_completion_queue"] = self._completion_queue
        if self.db:
            ctx.extra["_db"] = self.db
        sensing_hint = kwargs.get("sensing_hint", "")
        if sensing_hint:
            ctx.extra["_sensing_hint"] = sensing_hint
        return ctx

    def chat(self, message: str, user_id: int = 1,
             chat_id: int | None = None, chat_name: str = "未命名",
             history: list | None = None, model_type: str | None = None,
             nickname: str = "用户", **kwargs) -> dict:
        """同步对话"""
        if history is None and chat_id and self.db:
            history = self.db.get_chat_history(user_id, chat_id)

        if chat_id is None and self.db:
            chat_id = self.db.create_chat(user_id, chat_name)

        ctx = self.build_context(
            user_id=user_id, message=message,
            chat_id=chat_id, chat_name=chat_name,
            history=history or [], model_type=model_type,
            nickname=nickname, **kwargs
        )

        loop = _get_event_loop()
        try:
            result_ctx = loop.run_until_complete(self.pipeline.process(ctx))
        except RuntimeError:
            # 事件循环已关闭时重建
            global _engine_loop
            with _engine_loop_lock:
                _engine_loop = asyncio.new_event_loop()
            result_ctx = _engine_loop.run_until_complete(self.pipeline.process(ctx))

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
        if history is None and chat_id and self.db:
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

    def index_prompts_for_chat(self, user_id: int, chat_id: int) -> int:
        """
        为指定聊天索引提示词到 prompt_cache 表。
        
        在用户首次对话或同步时调用，将所有提示词按文件分组存储。
        """
        if not self.prompt_cache or not self.prompt_engine:
            return 0

        lib = self.prompt_engine.library
        prompts = []
        
        for entry in lib.entries:
            if entry.enabled and entry.content.strip():
                prompts.append({
                    "category": entry.category,
                    "source_file": entry.source_file,
                    "content": entry.content,
                })
        
        return self.prompt_cache.index_prompts(user_id, chat_id, prompts)

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

        try:
            import croniter
            def cron_loop():
                now = datetime.now()
                cron = croniter.croniter(cron_expr, now)
                next_run = cron.get_next(datetime)
                delay = max(0, (next_run - now).total_seconds())
                if delay <= 60:
                    job()
                else:
                    self._logger.info("下次定时任务: %s", next_run)
                return schedule.CancelJob
            schedule.every(60).seconds.do(cron_loop)
            self._logger.info("定时调度已启动(croniter): %s → %s", cron_expr, prompt[:50])
        except ImportError:
            self._logger.warning("croniter 未安装，回退到简易 cron 解析(每日同一时间)")
            parts = cron_expr.strip().split()
            if len(parts) == 5:
                time_str = f"{parts[1].zfill(2)}:{parts[0].zfill(2)}"
                schedule.every().day.at(time_str).do(job)
                self._logger.info("定时调度已启动(简易): %s → %s @ %s", cron_expr, prompt[:50], time_str)
            else:
                self._logger.warning("无法解析 cron 表达式: %s", cron_expr)
                return

        _stop_event = threading.Event()
        while not _stop_event.is_set():
            schedule.run_pending()
            _stop_event.wait(timeout=30)

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
     memory_system: MemorySystem = None,
    skill_registry: SkillRegistry = None,
    skill_manager: SkillManager = None,
    impression_manager = None,
    tts_client = None,
    filter_model = None,
    world_engine = None,
    world_state_manager = None,
    narrative_model = None,
    task_manager = None,
    personality_v3 = None,
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

    if memory_system:
        engine.memory_system = memory_system

    if skill_registry:
        engine.skill_registry = skill_registry
    if skill_manager:
        engine.skill_manager = skill_manager
    if impression_manager:
        engine.impression_manager = impression_manager
    if tts_client:
        engine._tts_client = tts_client
        engine._tts_available = True
        try:
            from plugins.builtin.tts_profile import TTSProfileManager
            engine._tts_profile_mgr = TTSProfileManager()
        except Exception:
            engine._tts_profile_mgr = None
    if filter_model:
        engine._filter_model = filter_model
    if world_engine:
        engine.world_engine = world_engine
    if world_state_manager:
        engine.world_state_manager = world_state_manager
    if narrative_model:
        engine.narrative_model = narrative_model
    if task_manager:
        engine.task_manager = task_manager

    # PromptEngine
    _prompt_dir = _os.path.join(_os.path.dirname(__file__), "prompt")
    lib = PromptLibrary()
    lib.scan_and_load(
        _os.path.join(_prompt_dir, "prompts", "core"),
        _os.path.join(_prompt_dir, "prompts", "capabilities"),
        _os.path.join(_prompt_dir, "prompts", "extensions"),
    )

    # V3 存在且 override 时，跳过 V2 创建
    _v3_override = personality_v3 and personality_v3.enabled
    pers_v2 = None
    if not _v3_override:
        try:
            from config import Config
            pers_v2 = PersonalitySystemV2(db=db)
            pers_v2.scan_presets(_os.path.join(_prompt_dir, "personality_v2", "presets"))
            pers_v2.load_rules_from_files()
            logging.getLogger("DSNEngine").info("PersonalitySystemV2 已在引擎内初始化")
        except Exception as e:
            logging.getLogger("DSNEngine").warning("PersonalitySystemV2 引擎内初始化失败: %s", e)

    engine.prompt_engine = PromptEngine(library=lib, personality_v2=pers_v2)
    if personality_v3:
        engine.prompt_engine.personality_v3 = personality_v3
        logging.getLogger("DSNEngine").info("PersonalitySystemV3 已注入到引擎 PromptEngine")
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
    if skill_registry:
        models_plugin.set_skill_registry(skill_registry)
        logging.getLogger("DSNEngine").info("ModelsPlugin: skill_registry 已注入")

    if memory_system and db:
        from plugins.builtin.memory_plugin import MemoryPlugin
        engine.plugin_manager.register(MemoryPlugin(memory_system=memory_system, db=db))

    # 用户观察日记
    from plugins.builtin.notebook import NotebookPlugin
    engine.plugin_manager.register(NotebookPlugin())

    from plugins.builtin.vision_plugin import VisionPlugin
    engine.plugin_manager.register(VisionPlugin(models_plugin=models_plugin))

    if engine.world_engine:
        from world import WorldPlugin
        from world.action_narrator import ActionNarrator
        action_narrator = ActionNarrator(
            narrative_model=engine.narrative_model,
            world_engine=engine.world_engine,
        )
        engine.plugin_manager.register(WorldPlugin(
            world_engine=engine.world_engine,
            world_state_manager=engine.world_state_manager,
            narrative_model=engine.narrative_model,
            personality_v2=pers_v2,
            action_narrator=action_narrator,
        ))

    pe = engine.prompt_engine
    if pe and pe.personality_v3 and pe.personality_v3.enabled:
        from plugins.builtin.personality_v3_plugin import PersonalityV3Plugin
        engine.plugin_manager.register(PersonalityV3Plugin(
            personality_v3=pe.personality_v3,
        ))
        logging.getLogger("DSNEngine").info("PersonalityV3Plugin 已注册")
    elif pe and pe.personality_v2:
        from plugins.builtin.personality_plugin import PersonalityPlugin
        engine.plugin_manager.register(PersonalityPlugin(
            personality_v2=pe.personality_v2,
        ))
        logging.getLogger("DSNEngine").info("PersonalityPlugin (V2) 已注册")

    if engine.impression_manager:
        from plugins.builtin.impression_plugin import ImpressionPlugin
        engine.plugin_manager.register(ImpressionPlugin(
            impression_manager=engine.impression_manager,
        ))

    if skill_registry:
        from plugins.builtin.tool_plugin import ToolPlugin
        engine.plugin_manager.register(ToolPlugin(
            skill_registry=skill_registry,
        ))

    if engine.task_manager:
        from plugins.builtin.task_plugin import TaskPlugin
        engine.plugin_manager.register(TaskPlugin(
            task_manager=engine.task_manager,
            db=db,
            skill_registry=skill_registry,
        ))

    if engine._tts_client:
        from plugins.builtin.tts_plugin import TTSPlugin
        engine.plugin_manager.register(TTSPlugin(
            tts_client=engine._tts_client,
            profile_manager=engine._tts_profile_mgr,
            tts_process_model=engine._tts_process_model,
        ))

    if engine._filter_model:
        from plugins.builtin.asr_filter_plugin import ASRFilterPlugin
        engine.plugin_manager.register(ASRFilterPlugin(
            filter_model=engine._filter_model,
            db=db,
        ))

    # ---- 补充注册：ConfirmPlugin / RecallPlugin / SSPPlugin ----

    try:
        from plugins.builtin.confirm_plugin import ConfirmPlugin
        engine.plugin_manager.register(ConfirmPlugin())
    except Exception as e:
        engine._logger.warning("ConfirmPlugin 加载失败: %s", e)

    if memory_system and db:
        try:
            from plugins.builtin.recall_plugin import RecallPlugin
            engine.plugin_manager.register(RecallPlugin(memory_system=memory_system))
        except Exception as e:
            engine._logger.warning("RecallPlugin 加载失败: %s", e)

    if skill_registry and models_plugin:
        try:
            from plugins.builtin.ssp_plugin import SSPPlugin
            engine.plugin_manager.register(SSPPlugin(
                db=db,
                impression_manager=impression_manager,
                models_plugin=models_plugin,
                skill_registry=skill_registry,
            ))
        except Exception as e:
            engine._logger.warning("SSPPlugin 加载失败: %s", e)

    # DistillPlugin — 双引擎蒸馏（V3 性格 + 技能模式）
    if engine.skill_manager and models_plugin:
        try:
            from plugins.builtin.distill_plugin import DistillPlugin
            from skills.distill import DistillationEngine
            from models import DeepSeekChat
            _skill_distill_llm = DeepSeekChat(api_key=Config.DEEPSEEK_API_KEY)
            _distill_engine = DistillationEngine(
                db=db,
                skill_manager=engine.skill_manager,
                llm_client=_skill_distill_llm,
            )
            _v3_sys = engine.prompt_engine.personality_v3 if engine.prompt_engine else None
            engine.plugin_manager.register(DistillPlugin(
                distillation_engine=_distill_engine,
                v3_system=_v3_sys,
                card_id="exa",
            ))
        except Exception as e:
            engine._logger.warning("DistillPlugin 加载失败: %s", e)

    # ---- TTS 文本预处理 ----
    if Config.TTS_PROCESS_ENABLED:
        try:
            from models.tts_process import TTSProcessModel
            engine._tts_process_model = TTSProcessModel()
            engine._logger.info("TTSProcessModel 初始化完成")
        except Exception as e:
            engine._logger.warning("TTSProcessModel 初始化失败: %s", e)

    engine._init_pipeline()
    engine._logger.info("DSNEngine 已从默认配置创建（复用 app.py 组件）")
    return engine
