# harness/orchestrator/router.py
# 统一模型路由与双轨制调度系统 (ModelOrchestrator)。
#
# 架构原则：
#   1. 模型分类分轨：
#      - 本地模型 (LOCAL_LLAMACPP): 基于 llama.cpp 引擎（动态指令合成、子进程拉起、健康轮询、受显存插槽调度）
#      - API 模型 (API_LMSTUDIO): 本地/内网 LMStudio（通过 HTTP 加载/卸载模型，受显存插槽调度）
#      - API 模型 (API_OPENAI): 云端或外部 OpenAI 兼容 API（直接调用，不参与本地显存调度）
#   2. 全局插槽与优先级调度：
#      - 配置机器全局同时允许加载的硬件模型数 (max_concurrent_slots)
#      - 依赖 ModelScheduler 统一管理插槽排队、空闲驱逐、即时抢占 (immediate) 与常驻保护 (resident)
#   3. 全局接入与透明调用：
#      - 对外暴露 invoke() / stream() / get_client()，支持动态注册与状态探查

from __future__ import annotations

import enum
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

from .base import ChatClientAdapter, ChatMessage, ChatResponse, IChatClient, IEmbeddingClient, ToolCall
from .llamacpp import LlamaCppChat, LlamaCppEmbeddingClient, LlamaServerConfig, LlamaServerLauncher
from .lmstudio import LMStudioChat, load_lmstudio_model, unload_lmstudio_model
from .openai import OpenAICompatClient
from .scheduler import ModelProfile, ModelScheduler

logger = logging.getLogger("ModelOrchestrator")


class ModelSourceType(str, enum.Enum):
    """模型上游来源分类。"""
    LOCAL_LLAMACPP = "local_llamacpp"      # 本地 llama.cpp（子进程调度）
    API_LMSTUDIO = "api_lmstudio"          # 本地/网络 LMStudio（HTTP 动态加载调度）
    API_OPENAI = "api_openai"              # 外部 OpenAI 兼容 API（纯调用，无本地插槽调度）


@dataclass
class ModelSpec:
    """受编排器管理的模型定义规格。"""
    name: str
    source_type: ModelSourceType
    profile: ModelProfile = field(default_factory=ModelProfile)
    # 本地 llama.cpp 参数
    llama_config: Optional[LlamaServerConfig] = None
    # API 参数 (LMStudio 或 OpenAI)
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    remote_model_name: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout: float = 300.0
    extra_headers: dict = field(default_factory=dict)
    # 运行时绑定
    launcher: Optional[LlamaServerLauncher] = None
    client_instance: Optional[IChatClient] = None


class ModelOrchestrator:
    """全局模型编排与双轨制调度中心。"""

    _instance: Optional["ModelOrchestrator"] = None
    _lock = threading.RLock()

    @classmethod
    def get_instance(cls, max_concurrent_slots: int = 1) -> "ModelOrchestrator":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(max_concurrent_slots=max_concurrent_slots)
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        with cls._lock:
            if cls._instance:
                cls._instance.shutdown()
            cls._instance = None

    def __init__(self, max_concurrent_slots: int = 1):
        self._max_concurrent_slots = max(1, max_concurrent_slots)
        self._scheduler = ModelScheduler.get_instance()
        self._scheduler.max_concurrent = self._max_concurrent_slots
        self._specs: Dict[str, ModelSpec] = {}
        self._loading_models: set[str] = set()
        self._default_model: Optional[str] = None
        self._registry_lock = threading.RLock()
        self._listeners: list[Callable[[str, str, dict], None]] = []
        logger.info("ModelOrchestrator 初始化完成 (全局最大插槽数: %d)", self._max_concurrent_slots)

    def add_status_listener(self, listener: Callable[[str, str, dict], None]) -> None:
        """添加状态变更监听器: fn(model_name, status_str, extra_dict)"""
        with self._registry_lock:
            if listener not in self._listeners:
                self._listeners.append(listener)

    def remove_status_listener(self, listener: Callable[[str, str, dict], None]) -> None:
        with self._registry_lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    def _notify_status(self, model_name: str, status: str, **kwargs) -> None:
        for fn in list(self._listeners):
            try:
                fn(model_name, status, kwargs)
            except Exception:
                pass

    @property
    def max_concurrent_slots(self) -> int:
        return self._max_concurrent_slots

    @max_concurrent_slots.setter
    def max_concurrent_slots(self, value: int) -> None:
        val = max(1, int(value))
        self._max_concurrent_slots = val
        self._scheduler.max_concurrent = val
        logger.info("ModelOrchestrator 全局最大插槽数已更新为: %d", val)

    def set_default_model(self, name: str) -> None:
        with self._registry_lock:
            if name not in self._specs:
                raise KeyError(f"模型未注册: {name}")
            self._default_model = name
            logger.info("Orchestrator 默认模型切换为: %s", name)

    def get_default_model(self) -> Optional[str]:
        with self._registry_lock:
            return self._default_model

    # ── 模型注册接口 ──

    def register_local_llamacpp(
        self,
        name: str,
        config: LlamaServerConfig,
        priority: int = 50,
        resident: bool = False,
        immediate: bool = False,
        orchestrated: bool = True,
        load_timeout: int = 180,
        request_timeout: int = 300,
    ) -> None:
        """注册本地 llama.cpp 推理引擎模型（受调度器显存插槽排队管理）。"""
        launcher = LlamaServerLauncher(config)
        load_fn, unload_fn = launcher.create_scheduler_hooks(load_timeout=load_timeout)

        profile = ModelProfile(
            priority=priority,
            resident=resident,
            immediate=immediate,
            orchestrated=orchestrated,
            load_timeout=load_timeout,
            request_timeout=request_timeout,
            engine="llama_cpp",
            llama_config=config.to_dict(),
        )

        self._scheduler.register(
            model_name=name,
            base_url=launcher.base_url,
            load_fn=load_fn,
            unload_fn=unload_fn,
            priority=priority,
            resident=resident,
            immediate=immediate,
            orchestrated=orchestrated,
            engine="llama_cpp",
            llama_config=config.to_dict(),
        )

        client = LlamaCppChat(
            base_url=launcher.base_url,
            model_name=name,
            timeout=float(request_timeout),
            temperature=config.temp or 0.7,
            max_tokens=config.ctx_size or 4096,
            api_key=config.api_key,
            scheduler=self._scheduler if orchestrated else None,
            launcher=launcher,
        )

        spec = ModelSpec(
            name=name,
            source_type=ModelSourceType.LOCAL_LLAMACPP,
            profile=profile,
            llama_config=config,
            base_url=launcher.base_url,
            api_key=config.api_key,
            timeout=float(request_timeout),
            temperature=config.temp or 0.7,
            launcher=launcher,
            client_instance=client,
        )

        with self._registry_lock:
            self._specs[name] = spec
            if self._default_model is None:
                self._default_model = name
        logger.info("已注册本地 llama.cpp 模型: %s (端口 %d, 优先级 %d)", name, config.port, priority)

    def register_api_lmstudio(
        self,
        name: str,
        base_url: str = "http://localhost:4501",
        remote_model_name: Optional[str] = None,
        priority: int = 50,
        resident: bool = False,
        immediate: bool = False,
        orchestrated: bool = True,
        load_timeout: int = 180,
        request_timeout: int = 300,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> None:
        """注册 LMStudio 模型（受调度器显存插槽排队管理）。"""
        target_name = remote_model_name or name
        b_url = base_url.rstrip("/")

        load_fn = lambda: load_lmstudio_model(b_url, target_name, "LMStudio模型", timeout=load_timeout)
        unload_fn = lambda: unload_lmstudio_model(b_url, target_name)

        profile = ModelProfile(
            priority=priority,
            resident=resident,
            immediate=immediate,
            orchestrated=orchestrated,
            load_timeout=load_timeout,
            request_timeout=request_timeout,
            engine="lmstudio",
        )

        self._scheduler.register(
            model_name=name,
            base_url=b_url,
            load_fn=load_fn,
            unload_fn=unload_fn,
            priority=priority,
            resident=resident,
            immediate=immediate,
            orchestrated=orchestrated,
            engine="lmstudio",
        )

        client = LMStudioChat(
            base_url=b_url,
            model_name=target_name,
            timeout=request_timeout,
            temperature=temperature,
            max_tokens=max_tokens,
            scheduler=self._scheduler if orchestrated else None,
        )

        spec = ModelSpec(
            name=name,
            source_type=ModelSourceType.API_LMSTUDIO,
            profile=profile,
            base_url=b_url,
            remote_model_name=target_name,
            timeout=float(request_timeout),
            temperature=temperature,
            max_tokens=max_tokens,
            client_instance=client,
        )

        with self._registry_lock:
            self._specs[name] = spec
            if self._default_model is None:
                self._default_model = name
        logger.info("已注册 LMStudio 调度模型: %s -> %s (优先级 %d)", name, target_name, priority)

    def register_api_openai(
        self,
        name: str,
        api_key: str,
        base_url: str = "https://api.deepseek.com/v1",
        remote_model_name: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        timeout: float = 300.0,
        extra_headers: Optional[dict] = None,
    ) -> None:
        """注册通用远程 OpenAI 兼容 API 模型（不负责本地调度，可全并发访问）。"""
        target_name = remote_model_name or name
        client = OpenAICompatClient(
            api_key=api_key,
            base_url=base_url,
            model=target_name,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            extra_headers=extra_headers or {},
        )

        profile = ModelProfile(
            priority=10,
            resident=True,
            orchestrated=False,  # 不计入硬件显存插槽
            request_timeout=int(timeout),
            engine="openai",
        )

        spec = ModelSpec(
            name=name,
            source_type=ModelSourceType.API_OPENAI,
            profile=profile,
            base_url=base_url,
            api_key=api_key,
            remote_model_name=target_name,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            extra_headers=extra_headers or {},
            client_instance=client,
        )

        with self._registry_lock:
            self._specs[name] = spec
            if self._default_model is None:
                self._default_model = name
        logger.info("已注册外部 OpenAI API 模型: %s -> %s (%s)", name, target_name, base_url)

    # ── 客户端检索与调用 ──

    def get_client(self, model_name: Optional[str] = None) -> IChatClient:
        """获取指定或默认模型的调用客户端。"""
        with self._registry_lock:
            target = model_name or self._default_model
            if not target or target not in self._specs:
                raise KeyError(f"未找到可用模型: {target} (可用: {list(self._specs.keys())})")
            return self._specs[target].client_instance

    def invoke(
        self,
        messages: list[Any],
        model_name: Optional[str] = None,
        tools: Optional[list[dict]] = None,
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> ChatResponse:
        """统一同步调用入口，自动走调度器排队与路由分发。"""
        client = self.get_client(model_name)
        return client.invoke(
            messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )

    async def stream(
        self,
        messages: list[Any],
        model_name: Optional[str] = None,
        tools: Optional[list[dict]] = None,
        **kwargs: Any,
    ) -> AsyncGenerator[Any, None]:
        """统一流式调用入口。"""
        client = self.get_client(model_name)
        async for chunk in client.stream(messages, tools=tools, **kwargs):
            yield chunk

    # ── 状态监控与控制 ──

    def status(self) -> dict[str, Any]:
        """导出当前 Orchestrator 状态快照（包括插槽、已加载模型、待运行任务等）。"""
        sched_snap = self._scheduler.snapshot()
        with self._registry_lock:
            models_info = []
            for name, spec in self._specs.items():
                snap = sched_snap.get(name, {})
                is_loading = name in self._loading_models
                is_loaded = snap.get("loaded", spec.source_type == ModelSourceType.API_OPENAI)

                # 自愈：本地托管进程若已意外退出（崩溃/OOM/被外部 kill），
                # 调度器可能仍记为 loaded，导致 UI 永久卡在“已加载”。这里以
                # 进程真实存活状态为准，并反向纠正调度器记录。
                if (
                    is_loaded
                    and not is_loading
                    and spec.source_type == ModelSourceType.LOCAL_LLAMACPP
                    and spec.launcher is not None
                    and not spec.launcher.is_running()
                ):
                    try:
                        self._scheduler.mark_unloaded(name)
                    except Exception:
                        pass
                    is_loaded = False
                    logger.warning("模型 %s 本地进程已退出，已同步为 unloaded", name)
                models_info.append({
                    "name": name,
                    "source_type": spec.source_type.value,
                    "is_local": spec.source_type == ModelSourceType.LOCAL_LLAMACPP,
                    "is_scheduled": spec.profile.orchestrated,
                    "loaded": is_loaded,
                    "is_loading": is_loading,
                    "status": "loading" if is_loading else ("loaded" if is_loaded else "unloaded"),
                    "priority": spec.profile.priority,
                    "resident": spec.profile.resident,
                    "immediate": spec.profile.immediate,
                    "base_url": spec.base_url,
                    "command": spec.llama_config.to_command_string() if spec.llama_config else None,
                })

            loaded_count = sum(1 for m in models_info if m["is_scheduled"] and m["loaded"] and not m["resident"])
            return {
                "max_concurrent_slots": self._max_concurrent_slots,
                "used_slots": loaded_count,
                "default_model": self._default_model,
                "total_models": len(self._specs),
                "models": models_info,
            }

    def load_model(self, model_name: str) -> bool:
        """手动请求加载指定模型进入显存。"""
        with self._registry_lock:
            spec = self._specs.get(model_name)
            if not spec:
                raise KeyError(f"模型未找到: {model_name}")

        with self._registry_lock:
            self._loading_models.add(model_name)

        progress_data = {"stages": ["text_model"], "current": "text_model", "value": 0.05}
        self._notify_status(model_name, "loading", progress=progress_data)
        def _on_launcher_progress(val: float):
            self._notify_status(model_name, "loading", progress={"stages": ["text_model"], "current": "text_model", "value": val})

        try:
            if spec.source_type == ModelSourceType.LOCAL_LLAMACPP and spec.launcher:
                ok = spec.launcher.start(wait_ready=True, timeout=spec.profile.load_timeout or 180, progress_callback=_on_launcher_progress)
                if ok:
                    self._scheduler.mark_preloaded(model_name)
                    self._notify_status(model_name, "loaded")
                else:
                    self._notify_status(model_name, "failed", error="Launch failed")
                return ok
            elif spec.source_type == ModelSourceType.API_LMSTUDIO:
                ok = load_lmstudio_model(spec.base_url, spec.remote_model_name or spec.name, "LMStudio")
                if ok:
                    self._scheduler.mark_preloaded(model_name)
                    self._notify_status(model_name, "loaded")
                else:
                    self._notify_status(model_name, "failed", error="LMStudio load failed")
                return ok
            self._notify_status(model_name, "loaded")
            return True
        except Exception as e:
            self._notify_status(model_name, "failed", error=str(e))
            raise
        finally:
            with self._registry_lock:
                self._loading_models.discard(model_name)

    def unload_model(self, model_name: str) -> bool:
        """手动请求从显存释放指定模型。"""
        with self._registry_lock:
            spec = self._specs.get(model_name)
            if not spec:
                raise KeyError(f"模型未找到: {model_name}")

        with self._registry_lock:
            self._loading_models.discard(model_name)

        try:
            if spec.source_type == ModelSourceType.LOCAL_LLAMACPP and spec.launcher:
                ok = spec.launcher.stop()
            elif spec.source_type == ModelSourceType.API_LMSTUDIO:
                ok = unload_lmstudio_model(spec.base_url, spec.remote_model_name or spec.name)
            else:
                ok = True

            # 无论上游卸载成功与否，都必须同步调度器状态：否则显存已释放但
            # status() 仍报告 loaded=True，前端会一直卡在“已加载”且插槽不回收。
            self._scheduler.mark_unloaded(model_name)
            self._notify_status(model_name, "unloaded")
            return ok
        except Exception as e:
            self._scheduler.mark_unloaded(model_name)
            self._notify_status(model_name, "failed", error=str(e))
            raise

    def shutdown(self) -> None:
        """停止所有托管的子进程与资源。"""
        with self._registry_lock:
            for spec in self._specs.values():
                if spec.launcher and spec.launcher.is_running():
                    try:
                        spec.launcher.stop()
                    except Exception as e:
                        logger.warning("关闭 launcher 异常: %s", e)
