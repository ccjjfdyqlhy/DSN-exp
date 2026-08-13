# model_scheduler.py
# LMStudio model orchestrator with per-model FIFO queues and priority eviction.

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import requests
import yaml

logger = logging.getLogger("ModelScheduler")


def _get_lm_load_unload():
    from .clients import _load_lmstudio_model, _unload_lmstudio_model
    return _load_lmstudio_model, _unload_lmstudio_model


def _get_loaded_models(base_url: str) -> list[str]:
    """Return models currently visible from LMStudio's OpenAI-compatible API."""
    try:
        resp = requests.get(f"{base_url}/v1/models", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return [m.get("id", "") for m in data.get("data", []) if m.get("id")]
    except Exception:
        return []


@dataclass(slots=True)
class ModelProfile:
    priority: int = 50
    resident: bool = False
    immediate: bool = False
    orchestrated: bool = True
    load_timeout: int | None = None
    request_timeout: int | None = None


@dataclass(slots=True)
class ModelTask:
    id: str
    immediate: bool
    ready: threading.Event = field(default_factory=threading.Event)
    done: threading.Event = field(default_factory=threading.Event)
    error: BaseException | None = None


@dataclass(slots=True)
class ModelInfo:
    name: str
    base_url: str
    load_fn: Callable[[], bool]
    unload_fn: Callable[[], bool]
    profile: ModelProfile
    loaded: bool = False
    refcount: int = 0
    last_used: float = 0.0
    queue: deque[ModelTask] = field(default_factory=deque)
    displaced_by_immediate: bool = False


class ModelScheduler:
    """
    Thread-safe LMStudio orchestrator.

    - Unregistered/non-orchestrated models are never unloaded by this scheduler.
    - Each registered model owns a FIFO task queue.
    - Loaded slot count excludes resident models.
    - Normal requests can evict only lower-priority idle models.
    - Immediate requests may temporarily evict idle models with higher/equal priority;
      after the immediate queue drains, those temporary models are unloaded first so
      higher-priority suspended work can resume.
    """

    _instance: Optional["ModelScheduler"] = None
    _profiles: dict[str, ModelProfile] | None = None

    @classmethod
    def get_instance(cls) -> "ModelScheduler":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls):
        cls._instance = None
        cls._profiles = None

    def __init__(self, max_concurrent: int | None = None):
        from apps.dsn.config import Config

        self.max_concurrent = max_concurrent or Config.MAX_CONCURRENT_LM_MODELS
        self.default_request_timeout = Config.MODEL_REQUEST_TIMEOUT
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._models: dict[str, ModelInfo] = {}
        self._slot_order: list[str] = []
        self._profiles_by_name = self._load_profiles()

        emb_model = Config.MEMORY_EMBEDDING_MODEL
        if emb_model and Config.MEMORY_EMBEDDING_ENABLED:
            self.register(
                model_name=emb_model,
                base_url=Config.LMSTUDIO_BASE_URL,
                load_fn=lambda: _get_lm_load_unload()[0](Config.LMSTUDIO_BASE_URL, emb_model, "embedding"),
                unload_fn=lambda: _get_lm_load_unload()[1](Config.LMSTUDIO_BASE_URL, emb_model),
                resident=True,
                orchestrated=False,
            )

        logger.info("ModelScheduler initialized (slots=%d, profiles=%d)",
                    self.max_concurrent, len(self._profiles_by_name))

    def _load_profiles(self) -> dict[str, ModelProfile]:
        if ModelScheduler._profiles is not None:
            return ModelScheduler._profiles

        root = Path(__file__).resolve().parent.parent / "model_profiles"
        profiles: dict[str, ModelProfile] = {}
        if root.exists():
            for path in sorted(root.glob("*.yaml")):
                try:
                    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                    name = data.get("model") or data.get("name") or path.stem
                    profiles[str(name)] = ModelProfile(
                        priority=int(data.get("priority", 50)),
                        resident=bool(data.get("resident", False)),
                        immediate=bool(data.get("immediate", False)),
                        orchestrated=bool(data.get("orchestrated", True)),
                        load_timeout=data.get("load_timeout"),
                        request_timeout=data.get("request_timeout"),
                    )
                except Exception:
                    logger.exception("Failed to load model profile: %s", path)
        ModelScheduler._profiles = profiles
        return profiles

    def register(
        self,
        model_name: str,
        base_url: str,
        load_fn: Callable[[], bool],
        unload_fn: Callable[[], bool],
        resident: bool | None = None,
        priority: int | None = None,
        immediate: bool | None = None,
        orchestrated: bool | None = None,
    ):
        """Register a model and merge explicit arguments with model_profiles/*.yaml."""
        if not model_name:
            return
        profile = self._profiles_by_name.get(model_name, ModelProfile())
        merged = ModelProfile(
            priority=profile.priority if priority is None else priority,
            resident=profile.resident if resident is None else resident,
            immediate=profile.immediate if immediate is None else immediate,
            orchestrated=profile.orchestrated if orchestrated is None else orchestrated,
            load_timeout=profile.load_timeout,
            request_timeout=profile.request_timeout,
        )
        with self._condition:
            existing = self._models.get(model_name)
            if existing:
                existing.base_url = base_url.rstrip("/")
                existing.load_fn = load_fn
                existing.unload_fn = unload_fn
                existing.profile = merged
                return
            self._models[model_name] = ModelInfo(
                name=model_name,
                base_url=base_url.rstrip("/"),
                load_fn=load_fn,
                unload_fn=unload_fn,
                profile=merged,
            )
            logger.info("Registered model: %s priority=%d resident=%s immediate=%s orchestrated=%s",
                        model_name, merged.priority, merged.resident, merged.immediate, merged.orchestrated)

    def mark_preloaded(self, model_name: str):
        with self._condition:
            info = self._models.get(model_name)
            if not info:
                return
            info.loaded = True
            info.last_used = time.time()
            if info.profile.orchestrated and not info.profile.resident:
                self._bump_slot(model_name)
            self._condition.notify_all()

    @contextmanager
    def use(self, model_name: str, timeout: float | None = None, immediate: bool | None = None):
        task = self._enqueue(model_name, timeout=timeout, immediate=immediate)
        try:
            yield
        finally:
            self._release(model_name, task)

    def snapshot(self) -> dict:
        with self._condition:
            return {
                name: {
                    "loaded": info.loaded,
                    "refcount": info.refcount,
                    "queue": len(info.queue),
                    "priority": info.profile.priority,
                    "resident": info.profile.resident,
                    "immediate": info.profile.immediate,
                    "orchestrated": info.profile.orchestrated,
                }
                for name, info in self._models.items()
            }

    def _enqueue(self, model_name: str, timeout: float | None, immediate: bool | None) -> ModelTask:
        with self._condition:
            info = self._models.get(model_name)
            if info is None:
                raise ValueError(f"模型未注册: {model_name}")
            timeout = timeout or info.profile.request_timeout or self.default_request_timeout
            task = ModelTask(id=str(uuid.uuid4()), immediate=info.profile.immediate if immediate is None else immediate)
            info.queue.append(task)
            deadline = time.time() + timeout

            while True:
                if info.queue and info.queue[0] is task:
                    try:
                        self._ensure_loaded_for_task(info, task)
                        if info.loaded:
                            info.refcount += 1
                            info.last_used = time.time()
                            self._bump_slot(model_name)
                            task.ready.set()
                            return task
                    except BaseException as exc:
                        task.error = exc
                        if info.queue and info.queue[0] is task:
                            info.queue.popleft()
                        self._condition.notify_all()
                        raise

                remaining = deadline - time.time()
                if remaining <= 0:
                    try:
                        info.queue.remove(task)
                    except ValueError:
                        pass
                    self._condition.notify_all()
                    raise TimeoutError(f"无法在 {timeout}s 内获取模型 {model_name} 的使用权")
                self._condition.wait(min(0.2, remaining))

    def _release(self, model_name: str, task: ModelTask):
        with self._condition:
            info = self._models[model_name]
            info.refcount = max(0, info.refcount - 1)
            info.last_used = time.time()
            if info.queue and info.queue[0] is task:
                info.queue.popleft()
            else:
                try:
                    info.queue.remove(task)
                except ValueError:
                    pass
            task.done.set()

            if info.profile.immediate and not info.queue and info.refcount == 0 and info.loaded:
                self._do_unload(model_name, reason="immediate request drained")
            self._restore_best_waiting_model()
            self._condition.notify_all()

    def _ensure_loaded_for_task(self, info: ModelInfo, task: ModelTask):
        if info.loaded:
            return
        if not info.profile.orchestrated or info.profile.resident:
            self._do_load(info.name)
            return
        while self._loaded_slot_count() >= max(0, self.max_concurrent):
            victim = self._select_victim(info, task.immediate)
            if not victim:
                self._condition.wait(0.2)
                return
            self._do_unload(victim, reason=f"evicted by {info.name}")
        self._do_load(info.name)

    def _loaded_slot_count(self) -> int:
        return sum(
            1 for info in self._models.values()
            if info.loaded and info.profile.orchestrated and not info.profile.resident
        )

    def _select_victim(self, requester: ModelInfo, immediate: bool) -> str | None:
        idle = [
            self._models[name] for name in self._slot_order
            if self._models[name].loaded
            and self._models[name].refcount == 0
            and self._models[name].profile.orchestrated
            and not self._models[name].profile.resident
            and self._models[name].name != requester.name
        ]
        if not idle:
            return None

        suspended = [m for m in idle if not m.queue and not m.profile.immediate]
        candidates = suspended or idle
        allowed = [m for m in candidates if requester.profile.priority > m.profile.priority]
        if not allowed and immediate:
            allowed = candidates
        if not allowed:
            return None
        victim = sorted(allowed, key=lambda m: (bool(m.queue), m.profile.priority, m.last_used))[0]
        victim.displaced_by_immediate = immediate and requester.profile.priority <= victim.profile.priority
        return victim.name

    def _restore_best_waiting_model(self):
        if self._loaded_slot_count() >= max(0, self.max_concurrent):
            candidates = [
                info for info in self._models.values()
                if info.loaded and info.refcount == 0 and info.profile.immediate and not info.queue
            ]
            if candidates:
                victim = sorted(candidates, key=lambda m: (m.profile.priority, m.last_used))[0]
                self._do_unload(victim.name, reason="free slot after immediate task")

        waiting = [
            info for info in self._models.values()
            if (info.queue or info.displaced_by_immediate)
            and not info.loaded
            and info.profile.orchestrated
            and not info.profile.resident
        ]
        if not waiting or self._loaded_slot_count() >= max(0, self.max_concurrent):
            return
        best = sorted(waiting, key=lambda m: (-m.profile.priority, 0 if m.queue else 1, m.last_used))[0]
        try:
            self._do_load(best.name)
        except Exception:
            logger.exception("Failed to restore waiting model: %s", best.name)

    def _do_load(self, model_name: str):
        info = self._models[model_name]
        if info.loaded:
            return
        logger.info("Loading model: %s", model_name)
        if not info.load_fn():
            raise RuntimeError(f"模型 {model_name} 加载失败")
        info.loaded = True
        info.last_used = time.time()
        info.displaced_by_immediate = False
        if info.profile.orchestrated and not info.profile.resident:
            self._bump_slot(model_name)
        logger.info("Model loaded: %s", model_name)

    def _do_unload(self, model_name: str, reason: str = "eviction"):
        info = self._models[model_name]
        if not info.loaded or info.refcount > 0 or info.profile.resident or not info.profile.orchestrated:
            return
        logger.info("Unloading model: %s (%s)", model_name, reason)
        try:
            info.unload_fn()
        except Exception:
            logger.exception("模型卸载异常: %s", model_name)
        info.loaded = False
        if model_name in self._slot_order:
            self._slot_order.remove(model_name)

    def _bump_slot(self, model_name: str):
        info = self._models.get(model_name)
        if not info or info.profile.resident or not info.profile.orchestrated:
            return
        if model_name in self._slot_order:
            self._slot_order.remove(model_name)
        self._slot_order.append(model_name)
