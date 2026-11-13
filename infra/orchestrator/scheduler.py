# infra/models/scheduler.py
# ModelScheduler — 多模型编排器（场景无关，从 DSN 应用广义化移植）。
#
# 能力：
#   - 每模型 FIFO 任务队列（use() 上下文管理器获取使用权）
#   - 插槽上限 + 优先级驱逐（普通请求只能驱逐低优先级空闲模型）
#   - immediate 请求可临时驱逐同级/高优先级空闲模型，结束后先卸载恢复
#   - resident（常驻）模型永不卸载；orchestrated=False 的模型不受本调度器管理
#   - 模型 profile 可来自 YAML 目录（profiles_dir）或 register() 显式参数
#
# 与 DSN 的差异：本实现不依赖任何应用配置/客户端——load_fn/unload_fn、
# 插槽数、超时、profiles 目录全部由调用方注入。

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import yaml

from .base import local_probe_session

logger = logging.getLogger("ModelScheduler")


def _env_int(name: str, default: int) -> int:
    """读环境变量整数；非法值退回默认值（不让配置错误把服务搞挂）。"""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        logger.warning("环境变量 %s=%r 不是整数，使用默认值 %d", name, raw, default)
        return default


def list_loaded_models(base_url: str) -> list[str]:
    """查询远端当前已加载模型（LMStudio OpenAI 兼容 /v1/models）。"""
    try:
        # 忽略代理：LMStudio 在 127.0.0.1，被 ALL_PROXY 接管会查不到已加载模型
        resp = local_probe_session().get(f"{base_url}/v1/models", timeout=10)
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
    engine: str = "lmstudio"                 # "lmstudio" | "llama_cpp" | "openai"
    llama_config: dict | None = None          # llama.cpp 专属启动参数（GGUF 路径、分层、上下文等）


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
    #: 是否有线程正在执行 load_fn（加载中）。
    #: 用于保证"同一模型同一时刻只被拉起一次"，见 _do_load。
    loading: bool = False


@dataclass(slots=True)
class DeviceLease:
    """一次显存独占租约。"""

    id: str
    holder: str                       # 持有者：模型名或 "finetune:<job_id>"
    device_ids: tuple[int, ...]
    reason: str = ""
    acquired_at: float = field(default_factory=time.time)
    released: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "holder": self.holder,
            "device_ids": list(self.device_ids),
            "reason": self.reason,
            "acquired_at": self.acquired_at,
            "released": self.released,
        }


class DeviceBusy(RuntimeError):
    """显存被占用且在超时时间内没有拿到租约。"""


class DeviceGate:
    """显存（GPU 设备）独占租约闸门。

    为什么放在编排器里，而不是新建 infra/resources/device_pool.py：
      - infra/resources/pool.py 的 ResourceKind 覆盖 ASR / TTS / VLM 三类本地服务，
        但它们的显存与「训练任务」不构成同一套仲裁（语音/视觉服务是常驻或按需的
        推理进程，不是训练作业）；
      - LLM 的显存由编排器管（docs/infra.md:150-151）。
      - 训练（infra/finetune）与推理（llama.cpp 服务）抢的是**同一批卡**，
        必须由同一个仲裁点裁决，否则两边各自以为卡是空的，最后 OOM。

    本机现实（本机实测）：
      - 2×RTX 2080Ti，各 11264 MiB；
      - Bonsai-2（PQ2_0 7.2GB）单卡即可，训练可用另一张卡；
      - JEV-27B-VL（Q4_K_M 16.5GB）必须 -ngl 99，**独占双卡**，
        它在的时候训练只能排队。
    """

    def __init__(self, device_count: int = 2):
        self._condition = threading.Condition(threading.RLock())
        self._device_count = max(1, int(device_count))
        self._leases: dict[str, DeviceLease] = {}
        self._by_device: dict[int, str] = {}

    @property
    def device_count(self) -> int:
        return self._device_count

    # ── 查询 ──

    def free_devices(self) -> list[int]:
        with self._condition:
            return [d for d in range(self._device_count) if d not in self._by_device]

    def occupancy(self) -> dict:
        with self._condition:
            out: dict = {}
            for dev, lease_id in self._by_device.items():
                lease = self._leases.get(lease_id)
                out[str(dev)] = lease.to_dict() if lease else {"id": lease_id}
            return out

    def is_free(self, device_ids: tuple[int, ...]) -> bool:
        with self._condition:
            return all(d not in self._by_device for d in device_ids)

    # ── 占用 ──

    def claim(
        self,
        device_ids: tuple[int, ...],
        holder: str,
        *,
        reason: str = "",
        replace: bool = False,
    ) -> DeviceLease:
        """非阻塞占用设备（用于编排器登记模型已加载）。

        设备已被别人占着时：
          - replace=True → 强行替换（**只允许编排器用它来抢占自己登记的模型**）；
          - replace=False → 抛 DeviceBusy。
        """
        with self._condition:
            for dev in device_ids:
                if dev in self._by_device and not replace:
                    other = self._leases.get(self._by_device[dev])
                    raise DeviceBusy(
                        f"设备 {dev} 已被占用: {other.holder if other else '?'}"
                    )
            lease = DeviceLease(
                id=str(uuid.uuid4()), holder=holder, device_ids=tuple(device_ids), reason=reason,
            )
            self._leases[lease.id] = lease
            for dev in device_ids:
                self._by_device[dev] = lease.id
            logger.info("设备占用: %s → %s", holder, list(device_ids))
            return lease

    def acquire(
        self,
        device_ids: tuple[int, ...],
        holder: str,
        *,
        reason: str = "",
        timeout: float = 0.0,
        preempt=None,
    ) -> DeviceLease:
        """阻塞占用设备直到拿到租约或超时。

        preempt: 可调用对象，签名 (holder) -> bool。
        当设备被**模型**占着时调用它尝试让路（编排器会卸载空闲模型）；
        训练作业之间**不互相抢占**——两个训练同时跑必然 OOM，宁可排队。
        """
        deadline = time.time() + max(0.0, timeout)
        while True:
            with self._condition:
                busy = [d for d in device_ids if d in self._by_device]
                if not busy:
                    lease = DeviceLease(
                        id=str(uuid.uuid4()), holder=holder,
                        device_ids=tuple(device_ids), reason=reason,
                    )
                    self._leases[lease.id] = lease
                    for dev in device_ids:
                        self._by_device[dev] = lease.id
                    logger.info("设备占用: %s → %s", holder, list(device_ids))
                    return lease

                blockers = []
                for dev in busy:
                    lease = self._leases.get(self._by_device[dev])
                    blockers.append(f"{dev}:{lease.holder if lease else '?'}")

            if preempt is not None:
                for dev in busy:
                    with self._condition:
                        lease = self._leases.get(self._by_device.get(dev, ""))
                    if lease is not None and lease.holder != holder:
                        try:
                            preempt(lease.holder)
                        except Exception:
                            logger.exception("设备让路失败: %s", lease.holder)

            remaining = deadline - time.time()
            if remaining <= 0:
                raise DeviceBusy(
                    f"等待设备 {list(device_ids)} 超时（{timeout}s），当前占用: {', '.join(blockers)}"
                )
            with self._condition:
                self._condition.wait(min(0.5, remaining))

    def release(self, lease: DeviceLease | str) -> None:
        """释放租约（按 lease 对象或 lease id）。"""
        lease_id = lease.id if isinstance(lease, DeviceLease) else lease
        with self._condition:
            held = self._leases.pop(lease_id, None)
            if held is None:
                return
            held.released = True
            for dev in list(held.device_ids):
                if self._by_device.get(dev) == lease_id:
                    del self._by_device[dev]
            logger.info("设备释放: %s ← %s", held.holder, list(held.device_ids))
            self._condition.notify_all()

    def release_holder(self, holder: str) -> None:
        """释放某个持有者的全部租约（模型卸载时调用）。"""
        with self._condition:
            for lease_id, lease in list(self._leases.items()):
                if lease.holder == holder:
                    self.release(lease_id)

    def leases_for(self, holder: str) -> list[DeviceLease]:
        """某个持有者当前持有的租约。"""
        with self._condition:
            return [lease for lease in self._leases.values() if lease.holder == holder]

    def acquire_any(
        self,
        holder: str,
        *,
        reason: str = "",
        timeout: float = 0.0,
    ) -> DeviceLease:
        """等待并占用**任意一张**空闲设备。

        训练用：两张卡都被模型占着时，训练应该等到有一张空出来，
        而不是死等某一张特定的卡。
        """
        deadline = time.time() + max(0.0, timeout)
        while True:
            with self._condition:
                free = [d for d in range(self._device_count) if d not in self._by_device]
                if free:
                    lease = DeviceLease(
                        id=str(uuid.uuid4()), holder=holder,
                        device_ids=(free[0],), reason=reason,
                    )
                    self._leases[lease.id] = lease
                    self._by_device[free[0]] = lease.id
                    logger.info("设备占用: %s → [%d]", holder, free[0])
                    return lease
            remaining = deadline - time.time()
            if remaining <= 0:
                raise DeviceBusy(f"等待任意空闲设备超时（{timeout}s）")
            with self._condition:
                self._condition.wait(min(0.5, remaining))


class ModelScheduler:
    """线程安全的多模型编排器。

    - 未注册 / orchestrated=False 的模型永远不会被本调度器卸载。
    - 每个已注册模型拥有独立 FIFO 任务队列。
    - 已加载插槽数不含 resident 模型。
    - 普通请求只能驱逐低优先级空闲模型。
    - immediate 请求可临时驱逐同级/更高优先级空闲模型；
      immediate 队列清空后优先卸载这些临时模型，让被挂起的高优先级工作恢复。
    """

    _instance: Optional["ModelScheduler"] = None
    _instance_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "ModelScheduler":
        # 修复：单例创建此前无锁，两线程同时首次调用会各自 new 一个调度器，
        # 互相不知情地注册/加载/驱逐模型。与 ModelOrchestrator.get_instance 对齐。
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        cls._instance = None

    def __init__(
        self,
        max_concurrent: int = 2,
        default_request_timeout: float = 300.0,
        profiles_dir: Optional[str | Path] = None,
    ):
        self.max_concurrent = max(max_concurrent, 1)
        self.default_request_timeout = default_request_timeout
        self._profiles_dir = Path(profiles_dir) if profiles_dir else None
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._models: dict[str, ModelInfo] = {}
        self._slot_order: list[str] = []
        #: 每个模型最近一次"因无驱逐权而等待"的日志时间戳（限流用，避免刷屏）。
        #: ModelInfo 是 slots=True 的 dataclass，不能挂动态属性，故放在调度器里。
        self._last_block_log: dict[str, float] = {}
        self._profiles_by_name = self._load_profiles()
        #: 显存独占闸门：训练与推理共用同一批卡时的唯一仲裁点。
        #: 设备数默认 2（本机 2×RTX 2080Ti），可用环境变量 DSN_GPU_COUNT 覆盖。
        self._device_gate = DeviceGate(_env_int("DSN_GPU_COUNT", 2))
        logger.info("ModelScheduler initialized (slots=%d, profiles=%d, devices=%d)",
                    self.max_concurrent, len(self._profiles_by_name), self._device_gate.device_count)

    # ── 显存闸门 ──

    @property
    def device_gate(self) -> DeviceGate:
        """显存独占闸门。训练作业通过它排队等待空闲显卡。"""
        return self._device_gate

    def _devices_for_profile(self, profile: ModelProfile) -> tuple[int, ...]:
        """推断一个模型 profile 独占哪些设备。

        规则（来自 llama.cpp 的实际行为）：
          - llama_config 里显式给了 devices → 用它；
          - n_gpu_layers / ngl == -1 → 全量分层，**独占所有卡**；
          - 其余（部分分层、纯 CPU）→ 不独占（它只吃一部分显存，允许别人并行）。
        """
        cfg = profile.llama_config or {}
        explicit = cfg.get("devices")
        if isinstance(explicit, (list, tuple)) and explicit:
            return tuple(int(d) for d in explicit)
        ngl = cfg.get("n_gpu_layers", cfg.get("ngl", cfg.get("gpu_layers")))
        if ngl is None:
            return ()
        try:
            ngl = int(ngl)
        except (TypeError, ValueError):
            return ()
        if ngl == -1:
            return tuple(range(self._device_gate.device_count))
        return ()

    def _claim_devices(self, model_name: str, profile: ModelProfile) -> None:
        """模型加载成功后登记它占用的设备（让训练排队）。"""
        devices = self._devices_for_profile(profile)
        if not devices:
            return
        try:
            self._device_gate.claim(devices, model_name, reason="model loaded", replace=True)
        except DeviceBusy:
            logger.warning("模型 %s 加载完成但设备登记失败（已被占用）: %s", model_name, list(devices))

    def _release_devices(self, model_name: str) -> None:
        self._device_gate.release_holder(model_name)

    # ── profile 加载 ──

    def _load_profiles(self) -> dict[str, ModelProfile]:
        if self._profiles_dir is None or not self._profiles_dir.exists():
            return {}
        profiles: dict[str, ModelProfile] = {}
        for path in sorted(self._profiles_dir.glob("*.yaml")):
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                name = data.get("model") or data.get("name") or path.stem
                engine = data.get("engine", "lmstudio")
                llama_cfg = data.get("llama_config") or data.get("llama_server") or None
                profiles[str(name)] = ModelProfile(
                    priority=int(data.get("priority", 50)),
                    resident=bool(data.get("resident", False)),
                    immediate=bool(data.get("immediate", False)),
                    orchestrated=bool(data.get("orchestrated", True)),
                    load_timeout=data.get("load_timeout"),
                    request_timeout=data.get("request_timeout"),
                    engine=str(engine),
                    llama_config=llama_cfg,
                )
            except Exception:
                logger.exception("Failed to load model profile: %s", path)
        return profiles

    # ── 注册 ──

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
        engine: str | None = None,
        llama_config: dict | None = None,
    ) -> None:
        """注册模型；显式参数与 YAML profile 合并（显式优先）。"""
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
            engine=profile.engine if engine is None else engine,
            llama_config=profile.llama_config if llama_config is None else llama_config,
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
            logger.info("Registered model: %s priority=%d resident=%s immediate=%s orchestrated=%s engine=%s",
                        model_name, merged.priority, merged.resident,
                        merged.immediate, merged.orchestrated, merged.engine)

    def mark_preloaded(self, model_name: str) -> None:
        with self._condition:
            info = self._models.get(model_name)
            if not info:
                return
            info.loaded = True
            info.last_used = time.time()
            if info.profile.orchestrated and not info.profile.resident:
                self._bump_slot(model_name)
            self._condition.notify_all()

    def mark_unloaded(self, model_name: str) -> None:
        """标记模型已从显存/内存释放（手动卸载或外部终止后调用）。

        编排器手动卸载模型时并不会走 _do_unload 的驱逐路径，若不同步调度器
        的 loaded 状态，status() 会一直报告 loaded=True，导致前端永远停留在
        “已加载”状态且插槽计数无法回收。
        """
        with self._condition:
            info = self._models.get(model_name)
            if not info:
                return
            info.loaded = False
            info.refcount = 0
            if model_name in self._slot_order:
                self._slot_order.remove(model_name)
            self._release_devices(model_name)
            self._condition.notify_all()

    @contextmanager
    def use(self, model_name: str, timeout: float | None = None,
            immediate: bool | None = None):
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
                    # 最后一次「被使用」的时刻（加载成功或租约归还时刷新）。
                    # 空闲回收（infra.resources.IdleReaper）据此判断资源闲置了多久。
                    "last_used": info.last_used,
                }
                for name, info in self._models.items()
            }

    # ── 内部调度 ──

    def _enqueue(self, model_name: str, timeout: float | None,
                 immediate: bool | None) -> ModelTask:
        with self._condition:
            info = self._models.get(model_name)
            if info is None:
                raise ValueError(f"模型未注册: {model_name}")
            timeout = timeout or info.profile.request_timeout or self.default_request_timeout
            task = ModelTask(id=str(uuid.uuid4()),
                             immediate=info.profile.immediate if immediate is None else immediate)
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

    def _release(self, model_name: str, task: ModelTask) -> None:
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

    def _ensure_loaded_for_task(self, info: ModelInfo, task: ModelTask) -> None:
        if info.loaded:
            return
        if not info.profile.orchestrated or info.profile.resident:
            self._do_load(info.name)
            return
        # 说明：max_concurrent 在构造函数里已保证 >= 1，这里的 max(0, ...) 是冗余
        # 防御，保留以表明"槽位数为 0 时不加载任何模型"的意图。
        while self._loaded_slot_count() >= max(0, self.max_concurrent):
            victim = self._select_victim(info, task.immediate)
            if not victim:
                # 无驱逐权（槽位被更高优先级/正在使用的模型占满）。
                # 这是**有意的**调度语义：不抢占比自己高优先级的模型，
                # 由调用方排队等待（_enqueue 会一直重试到 request_timeout）。
                # 但原先完全静默，排查时只看到"模型一直未加载"，因此补一条
                # 限流诊断日志，明确告知等待的是谁、阻塞原因是什么。
                now = time.time()
                if now - self._last_block_log.get(info.name, 0.0) >= 5.0:
                    holders = [
                        f"{n}(prio={m.profile.priority},refs={m.refcount})"
                        for n, m in self._models.items()
                        if m.loaded and m.profile.orchestrated and not m.profile.resident
                    ]
                    logger.warning(
                        "模型 %s(prio=%d) 等待槽位：当前占用 %s，无法驱逐（优先级不足或均在使用中）",
                        info.name, info.profile.priority, holders or "无",
                    )
                    self._last_block_log[info.name] = now
                self._condition.wait(0.2)
                return
            self._do_unload(victim, reason=f"evicted by {info.name}")
        self._do_load(info.name)

    def _loaded_slot_count(self) -> int:
        # 修复：`or info.loading` —— _do_load 在锁外执行分钟级加载，期间
        # loaded 仍为 False。不把加载中的模型计入槽位时，两个不同模型的
        # 并发加载会各自通过槽位检查，最终同时驻留的模型数超过 max_concurrent
        # （显存 OOM）。加载中占坑后，后来者会排队等待加载完成。
        return sum(
            1 for info in self._models.values()
            if (info.loaded or info.loading)
            and info.profile.orchestrated and not info.profile.resident
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

    def _restore_best_waiting_model(self) -> None:
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

    def _do_load(self, model_name: str) -> None:
        """加载模型，保证**同一模型并发请求只拉起一次**。

        修复说明（严重）：原实现在持有 _condition（RLock）时直接调用
        info.load_fn()。而 load_fn 是分钟级的阻塞操作，Condition.wait() 又会
        释放锁 —— 于是 N 个并发请求会依次进入 load 分支，而 info.loaded 直到
        load_fn 返回后才置 True。实测 4 个并发 use() 会触发 4 次 load_fn，
        对 llama.cpp 意味着同一端口被拉起 4 个子进程：显存直接翻 N 倍导致
        OOM，且 self._process 被后写覆盖，旧进程变成孤儿无法回收。

        现在用 info.loading 做单飞（single-flight）：只有一个线程真正执行加载，
        其余线程等待它完成；且阻塞的 load_fn 在锁外执行，不阻塞其它模型调度。
        """
        info = self._models[model_name]
        if info.loaded:
            return

        # 已有线程在加载同一模型：等它结束，不重复拉起。
        if info.loading:
            logger.info("模型 %s 正在加载中，等待既有加载完成", model_name)
            while info.loading and not info.loaded:
                self._condition.wait(0.2)
            # 若加载失败（未 loaded），由本次调用负责重试一次，
            # 避免所有等待方都直接返回 False 导致请求集体失败。
            if info.loaded:
                return

        info.loading = True
        logger.info("Loading model: %s", model_name)
        ok = False
        try:
            # 必须释放锁再执行阻塞加载：否则整个调度器会被一次模型加载卡死，
            # 其它模型的请求（甚至 status()）都无法推进。
            self._condition.release()
            try:
                ok = bool(info.load_fn())
            finally:
                self._condition.acquire()
        finally:
            info.loading = False
            # 无论成功失败都唤醒所有等待方，让它们重新判断状态。
            self._condition.notify_all()

        if not ok:
            raise RuntimeError(f"模型 {model_name} 加载失败")

        info.loaded = True
        info.last_used = time.time()
        info.displaced_by_immediate = False
        if info.profile.orchestrated and not info.profile.resident:
            self._bump_slot(model_name)
        # 登记显存占用：全量分层的模型独占所有卡，训练作业必须为它让路。
        self._claim_devices(model_name, info.profile)
        logger.info("Model loaded: %s", model_name);

    def _do_unload(self, model_name: str, reason: str = "eviction") -> None:
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
        self._release_devices(model_name)

    def _bump_slot(self, model_name: str) -> None:
        info = self._models.get(model_name)
        if not info or info.profile.resident or not info.profile.orchestrated:
            return
        if model_name in self._slot_order:
            self._slot_order.remove(model_name)
        self._slot_order.append(model_name)
