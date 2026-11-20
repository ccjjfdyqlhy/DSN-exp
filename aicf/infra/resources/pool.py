# infra/resources/pool.py
# 资源池 —— ASR / TTS 本地资源的统一注册、调度与生命周期视图。
#
# 定位：
#   本模块是**薄封装**，不实现任何调度算法。真正的调度（FIFO 队列、插槽上限、
#   优先级驱逐、immediate 抢占、resident 保护）完全复用
#   infra.orchestrator.scheduler.ModelScheduler —— ResourcePool 直接继承它，
#   只在其上附加「资源描述符（ResourceSpec）」与「租约（ResourceLease）」两层语义。
#
#   之所以能复用：ModelScheduler 只要求调用方注入 (load_fn, unload_fn) 与若干
#   profile 字段，并不关心被调度的是语言模型还是语音模型。ASR/TTS 与 LLM 在
#   显存插槽这一维度上完全同构，因此换一个描述符外壳即可。
#
# 当前范围：ASR（语音识别）、TTS（语音合成）、VLM（视觉多模态模型）、
# DECISION（System-1 决策模型）四类资源。
#   ResourceKind 只保留**已经有真实资源在用**的成员：前两个是语音服务，
#   VLM 是本地 Bonsai llama-server（入库 OCR 用的多模态推理服务）。
#   the decision model is the llama-server that carries the System-1 head.
#   未来如需更多种类，在同一个枚举里扩展，但本模块不预先发明其它种类。

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Callable, Iterator, Optional

from ..orchestrator.scheduler import ModelScheduler

if TYPE_CHECKING:  # pragma: no cover - 仅供类型检查
    from .idle import IdleReaper

logger = logging.getLogger("ResourcePool")


class ResourceKind(str, Enum):
    """资源种类。

    四类：ASR（语音识别）、TTS（语音合成）、VLM（视觉多模态模型）、
    DECISION（System-1 决策模型）。
    VLM 不是凭空发明的成员 —— 入库 OCR 用的本地 Bonsai llama-server
    就是一个「按需拉起、用完可回收」的重量级 GPU 服务，与 ASR/TTS
    在资源池里的语义完全同构。DECISION 同理：JEV-27B-VL 的决策头
    跑在自己的 llama-server 上，显存占用与 VLM 同一量级。
    """

    ASR = "asr"
    TTS = "tts"
    VLM = "vlm"
    #: The decision model (System-1). The decision head of a dual-system
    #: hybrid model such as JEV-27B-VL: one forward pass returns an answer
    #: with a probability and generates no text. It is a **heavy local
    #: service** (a llama-server with weights of several GB) and has the same
    #: shape as the VLM: start on demand, keep the lease alive, reclaim it
    #: when idle. It is listed here because it really is in use.
    DECISION = "decision"


@dataclass
class ResourceSpec:
    """单个资源的描述符。

    字段与 ModelScheduler 的 profile 语义对齐（priority/resident/immediate/
    orchestrated/load_timeout/request_timeout），另外补充语音资源特有的
    连接信息（base_url/endpoint）与显存预估（vram_estimate_mb）。
    """

    kind: ResourceKind
    display_name: str
    #: 调度优先级，数值越大越优先（与 ModelScheduler 一致）
    priority: int = 50
    #: 常驻资源：永不因插槽压力被卸载
    resident: bool = False
    #: 即时资源：任务排空后立即卸载，并可临时抢占同级/更高优先级空闲资源
    immediate: bool = False
    #: 是否交由 ResourcePool/ModelScheduler 管理；False 表示仅登记不调度
    orchestrated: bool = True
    #: 加载超时（秒）。None 表示用调度器默认
    load_timeout: int | None = None
    #: 单次使用权等待超时（秒）。None 表示用调度器默认
    request_timeout: int | None = None
    #: HTTP 服务根地址；进程内资源（如 FunASR）可为空字符串
    base_url: str = ""
    #: 具体业务端点路径（如 /asr、/tts）
    endpoint: str = ""
    #: 显存占用预估（MB），仅用于展示与运维判断，不参与调度
    vram_estimate_mb: int = 0
    #: 空闲自动关闭阈值（秒）。0 = 不做空闲回收。
    #: 超过该时长无人使用（无租约、无排队）时，IdleReaper 会停掉资源释放显存；
    #: 下次有请求时由调度器重新拉起。
    idle_timeout: int = 0
    #: 各启动器/调用方自由使用的附加字段
    extra: dict = field(default_factory=dict)

    def url(self) -> str:
        """拼接 base_url 与 endpoint（进程内资源返回空串）。"""
        base = (self.base_url or "").rstrip("/")
        if not base:
            return ""
        ep = (self.endpoint or "").strip()
        if not ep or ep == "/":
            return base
        return base + (ep if ep.startswith("/") else "/" + ep)


class ResourceLease:
    """acquire() 返回的资源租约。

    既可作为上下文管理器使用（with pool.acquire("tts") as lease: ...），
    也可以手动 release()。release() 是幂等的：重复调用只释放一次。
    释放动作即退出 ModelScheduler 的 use() 上下文（回收 refcount 与插槽）。
    """

    def __init__(
        self,
        name: str,
        base_url: str,
        spec: Optional[ResourceSpec],
        release_fn: Callable[[], None],
    ):
        self.name = name
        self.base_url = base_url
        self.spec = spec
        self.acquired_at = time.time()
        self._release_fn = release_fn
        self._released = False
        self._lock = threading.Lock()

    @property
    def endpoint(self) -> str:
        """资源端点路径（无描述符时返回空串）。"""
        return self.spec.endpoint if self.spec else ""

    @property
    def url(self) -> str:
        """资源完整 URL（进程内资源为空串）。"""
        return self.spec.url() if self.spec else (self.base_url or "")

    @property
    def released(self) -> bool:
        return self._released

    @property
    def held_seconds(self) -> float:
        """自获取到现在的持有时长（秒）。"""
        return max(0.0, time.time() - self.acquired_at)

    def release(self) -> None:
        """释放租约（幂等）。"""
        with self._lock:
            if self._released:
                return
            self._released = True
        try:
            self._release_fn()
        except Exception:  # noqa: BLE001 - 释放失败不应让业务路径崩掉
            logger.exception("释放资源租约失败: %s", self.name)

    def __enter__(self) -> "ResourceLease":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.release()
        return False

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        state = "released" if self._released else "held"
        return f"<ResourceLease {self.name} {state} {self.held_seconds:.1f}s>"


class ResourcePool(ModelScheduler):
    """ASR/TTS/VLM 资源池。

    继承 ModelScheduler，因此以下能力**原样复用、零重复实现**：
      * 每资源 FIFO 任务队列（use() 上下文管理器）
      * 插槽上限与优先级驱逐
      * immediate 请求的临时抢占与恢复
      * resident 资源的永不卸载保护

    本类只做三件事：
      1. 把 ResourceSpec 映射到 ModelScheduler.register() 的参数；
      2. 把 use() 包装成可手动/自动释放的 ResourceLease；
      3. 提供面向 ASR/TTS 的状态视图（list_resources / status / kind_for）。
    """

    def __init__(
        self,
        max_concurrent: int = 2,
        default_request_timeout: float = 300.0,
        profiles_dir: Optional[str] = None,
    ):
        super().__init__(
            max_concurrent=max_concurrent,
            default_request_timeout=default_request_timeout,
            profiles_dir=profiles_dir,
        )
        #: 资源名 -> ResourceSpec。已注册资源在 ModelScheduler._models 中另有条目，
        #: 这里只保存描述符（调度状态一律以基类为准，不重复存储）。
        self._specs: dict[str, ResourceSpec] = {}
        self._specs_lock = threading.RLock()
        #: 正在被空闲回收的资源名。回收期间到达的请求必须等待，
        #: 否则会撞上「正在被杀」的服务（详见 _ensure_loaded_for_task）。
        self._reclaiming: set[str] = set()
        #: 空闲回收器（未启用时为 None），见 infra.resources.idle.IdleReaper
        self._idle_reaper = None

    # ── 注册 ──

    def register_resource(
        self,
        name: str,
        spec: ResourceSpec,
        load_fn: Callable[[], bool],
        unload_fn: Callable[[], bool],
    ) -> None:
        """注册一个资源。

        spec 的调度相关字段映射到基类 register() 的同名参数；base_url 取自
        spec（进程内资源为空串，基类会规范化为空串）。
        """
        if not name:
            raise ValueError("资源名不能为空")
        if not isinstance(spec, ResourceSpec):
            raise TypeError(f"spec 必须是 ResourceSpec，收到 {type(spec).__name__}")

        with self._specs_lock:
            self._specs[name] = spec

        engine = "local"
        if isinstance(spec.extra, dict):
            engine = str(spec.extra.get("engine", "local"))

        self.register(
            model_name=name,
            base_url=spec.base_url or "",
            load_fn=load_fn,
            unload_fn=unload_fn,
            resident=spec.resident,
            priority=spec.priority,
            immediate=spec.immediate,
            orchestrated=spec.orchestrated,
            engine=engine,
        )
        # ModelScheduler.register() 的 load_timeout / request_timeout 只从
        # YAML profile 取值，不接受显式参数 —— 于是 ResourceSpec 上配的这两个
        # 字段形同虚设。这里补写回 profile，否则「VLM 冷启动要等 10 分钟」
        # 这类配置根本不会生效（实际会退回池的 default_request_timeout）。
        if spec.load_timeout is not None or spec.request_timeout is not None:
            with self._condition:
                info = self._models.get(name)
                if info is not None:
                    if spec.load_timeout is not None:
                        info.profile.load_timeout = spec.load_timeout
                    if spec.request_timeout is not None:
                        info.profile.request_timeout = spec.request_timeout
        logger.info(
            "注册资源: %s kind=%s priority=%d resident=%s immediate=%s base_url=%s",
            name, spec.kind.value, spec.priority, spec.resident, spec.immediate,
            spec.base_url or "(in-process)",
        )

    # ── 查询 ──

    def get_spec(self, name: str) -> ResourceSpec | None:
        """返回资源描述符，未注册则 None。"""
        with self._specs_lock:
            return self._specs.get(name)

    def kind_for(self, name: str) -> ResourceKind | None:
        """返回资源种类，未注册则 None。"""
        spec = self.get_spec(name)
        return spec.kind if spec else None

    def _ordered_names(self) -> list[str]:
        """按注册顺序返回资源名（便于稳定输出）。"""
        with self._specs_lock:
            return list(self._specs.keys())

    def _entry(self, name: str, snap: dict) -> dict:
        """合成单个资源的对外字典（调度字段取自基类快照，不另存状态）。"""
        spec = self.get_spec(name)
        st = snap.get(name, {})
        return {
            "name": name,
            "kind": spec.kind.value if spec else None,
            "display_name": spec.display_name if spec else name,
            "base_url": spec.base_url if spec else "",
            "endpoint": spec.endpoint if spec else "",
            "loaded": bool(st.get("loaded", False)),
            "refcount": int(st.get("refcount", 0)),
            "queue": int(st.get("queue", 0)),
            "priority": int(st.get("priority", 50)),
            "resident": bool(st.get("resident", False)),
            "immediate": bool(st.get("immediate", False)),
            "orchestrated": bool(st.get("orchestrated", True)),
            "vram_estimate_mb": int(spec.vram_estimate_mb) if spec else 0,
            # 资源来源/模式（供前端区分「托管」「接入」「进程内」）：
            #   in_process=True  -> 进程内模型（ASR）
            #   managed=True     -> 由资源池拉起/停止（托管 TTS）
            #   adopt=True       -> 只接入既有服务，不拉起也不杀死
            "in_process": not bool(spec.base_url) if spec else False,
            "managed": bool(spec.extra.get("managed", False)) if spec and isinstance(spec.extra, dict) else False,
            "adopt": bool(spec.extra.get("adopt", False)) if spec and isinstance(spec.extra, dict) else False,
            "engine": str(spec.extra.get("engine", "local")) if spec and isinstance(spec.extra, dict) else "local",
            # ── 空闲回收相关 ──
            # idle_timeout: 空闲多少秒后自动关闭（0 = 不回收）
            "idle_timeout": int(spec.idle_timeout) if spec else 0,
            # last_used: 最后一次被使用（加载成功或租约归还）的时刻
            "last_used": float(st.get("last_used", 0.0)),
            # idle_seconds: 已经闲置了多久
            "idle_seconds": max(0.0, time.time() - float(st.get("last_used", 0.0))),
        }

    def list_resources(self, kind: ResourceKind | None = None) -> list[dict]:
        """列出已注册资源（可按种类过滤），调度状态来自基类 snapshot()。"""
        snap = self.snapshot()
        rows = [self._entry(n, snap) for n in self._ordered_names()]
        if kind is None:
            return rows
        target = kind.value if isinstance(kind, ResourceKind) else str(kind)
        return [r for r in rows if r["kind"] == target]

    def status(self) -> dict:
        """资源池整体状态：资源列表 + 按种类分组 + 计数。"""
        rows = self.list_resources()
        by_kind: dict[str, list[str]] = {}
        for row in rows:
            k = row["kind"]
            if k is None:
                continue
            by_kind.setdefault(k, []).append(row["name"])
        return {
            "resources": rows,
            "by_kind": by_kind,
            "totals": {
                "registered": len(rows),
                "loaded": sum(1 for r in rows if r["loaded"]),
            },
        }

    # ── 外周任务槽 ──

    def used_slots(self) -> int:
        """当前被占用的外周任务槽数。

        语义与外层 LLM 插槽不同：LLM 的 used_slots 数的是「已加载的非常驻模型」，
        而外周任务槽关心的是「此刻有多少个外周资源正在被使用」——即 refcount > 0。
        这是因为 ASR/TTS 都是单实例资源，其并发度就是「有几个在使用」。
        """
        snap = self.snapshot()
        return sum(1 for st in snap.values() if int(st.get("refcount", 0)) > 0)

    def slot_status(self) -> dict:
        """外周任务槽状态（供 dsn_ui 的「外周任务槽」卡片消费）。"""
        rows = self.list_resources()
        return {
            "max_concurrent_slots": int(self.max_concurrent),
            "used_slots": self.used_slots(),
            "registered": len(rows),
            "loaded": sum(1 for r in rows if r["loaded"]),
        }

    def set_max_concurrent(self, slots: int) -> int:
        """调整外周任务槽数量，返回生效后的值。

        基类的 max_concurrent 只是一个普通属性，运行中直接赋值不会唤醒等待者，
        因此在收紧/放宽后要 notify_all，并尝试恢复被积压的等待资源。
        """
        new_val = max(1, int(slots))
        with self._condition:
            self.max_concurrent = new_val
            self._condition.notify_all()
            # 修复：恢复调用必须在持有 _condition 时进行——_restore_best_waiting_model
            # → _do_load 会在未持锁状态下执行 self._condition.release()，
            # 锁外调用直接抛 "cannot release un-acquired lock"，恢复功能
            # 每次都静默失败（异常被下面的 except 吞掉）。
            try:
                self._restore_best_waiting_model()
            except Exception:  # noqa: BLE001 - 恢复失败不影响配额变更本身
                logger.exception("调整外周任务槽后恢复等待资源失败")
        logger.info("外周任务槽数量已更新为 %d", new_val)
        return new_val

    # ── 获取 / 释放 ──

    def acquire(self, name: str, timeout: float | None = None) -> ResourceLease:
        """获取资源使用权，返回可作上下文管理器的 ResourceLease。

        实现方式：进入基类 use(name, timeout) 上下文并**保持打开**，
        租约释放时才退出 —— 从而完整复用基类的排队/加载/驱逐逻辑，
        同时给调用方一个可手动释放的句柄。
        """
        if self.get_spec(name) is None:
            raise ValueError(f"资源未注册: {name}")

        ctx = self.use(name, timeout=timeout)
        ctx.__enter__()

        spec = self.get_spec(name)
        base_url = spec.base_url if spec else ""
        if not base_url:
            # 描述符未给 base_url 时回退到基类登记值（进程内资源仍为空串）
            with self._condition:
                info = self._models.get(name)
                base_url = info.base_url if info else ""

        def _release() -> None:
            ctx.__exit__(None, None, None)

        return ResourceLease(
            name=name,
            base_url=base_url,
            spec=spec,
            release_fn=_release,
        )

    @contextmanager
    def lease(self, name: str, timeout: float | None = None) -> Iterator[ResourceLease]:
        """acquire() 的生成器形式（with pool.lease("asr") as l: ...）。"""
        handle = self.acquire(name, timeout=timeout)
        try:
            yield handle
        finally:
            handle.release()

    # ── 生命周期 ──

    def ensure_running(self, name: str, timeout: float | None = None) -> bool:
        """确保资源已加载并就绪；已加载则直接返回 True。

        通过临时获取/释放一次使用权来触达基类的加载路径（含插槽驱逐），
        随后立即归还，因此不会长期占用插槽。
        """
        if self.get_spec(name) is None:
            raise ValueError(f"资源未注册: {name}")
        try:
            with self.acquire(name, timeout=timeout) as handle:
                loaded = self.snapshot().get(name, {}).get("loaded", False)
            return bool(loaded)
        except TimeoutError:
            logger.warning("ensure_running 超时: %s", name)
            return False
        except Exception:  # noqa: BLE001 - 加载失败以 False 表达，不向上抛
            logger.exception("ensure_running 失败: %s", name)
            return False

    def stop_resource(self, name: str) -> bool:
        """显式卸载资源并回收插槽。

        先调用基类登记的 unload_fn 真正释放资源，再用 mark_unloaded() 同步
        调度器状态（基类的手动卸载路径不会自动同步，见其注释）。
        """
        with self._condition:
            info = self._models.get(name)
            if info is None:
                return False
            unload_fn = info.unload_fn

        ok = True
        try:
            ok = bool(unload_fn())
        except Exception:  # noqa: BLE001
            logger.exception("卸载资源失败: %s", name)
            ok = False
        self.mark_unloaded(name)
        logger.info("已停止资源: %s (ok=%s)", name, ok)
        return ok

    # ── 空闲回收 ──

    def reclaim_idle_resource(self, name: str) -> bool:
        """空闲回收专用卸载：确认无人使用、无人排队后才真正停掉资源。

        与 :meth:`stop_resource` 的区别有两点：

        1. **不抢占**——有租约（refcount > 0）或有人排队时直接放弃，
           返回 False。stop_resource 是「用户明确要求停止」的语义，
           强制执行；空闲回收是后台策略，绝不能打断正在进行的请求。
        2. **排他**——回收期间把资源名登记到 ``self._reclaiming``，
           到达的请求会等待回收结束再重新加载（见 _ensure_loaded_for_task），
           不会撞上「正在被杀」的服务。

        回收完成后调用 mark_unloaded 同步调度器状态，因此**下次请求会
        自动重新拉起资源**（resident 资源同样如此）。
        """
        with self._condition:
            info = self._models.get(name)
            if info is None:
                return False
            if not info.loaded:
                # 本来就没加载，无需回收
                return False
            if info.refcount > 0 or info.queue:
                logger.debug("资源 %s 正在被使用或排队，跳过空闲回收", name)
                return False
            unload_fn = info.unload_fn
            self._reclaiming.add(name)

        ok = False
        try:
            # 阻塞的停机动作必须放在锁外，否则整个调度器会被卡住
            ok = bool(unload_fn())
        except Exception:  # noqa: BLE001
            logger.exception("空闲回收失败: %s", name)
            ok = False
        finally:
            with self._condition:
                self._reclaiming.discard(name)
                self._condition.notify_all()

        self.mark_unloaded(name)
        logger.info("空闲回收完成: %s (ok=%s)", name, ok)
        return ok

    def enable_idle_shutdown(self, interval: float = 60.0) -> "IdleReaper":
        """启用空闲自动关闭（幂等）。

        只有在 :class:`ResourceSpec` 上设置了 ``idle_timeout > 0`` 的资源
        才会被回收；其余资源不受影响。

        :param interval: 后台检查周期（秒）。
        """
        if self._idle_reaper is None:
            from .idle import IdleReaper

            self._idle_reaper = IdleReaper(self, interval=interval)
        else:
            self._idle_reaper._interval = max(1.0, float(interval))
        return self._idle_reaper.start()

    def disable_idle_shutdown(self) -> None:
        """停用空闲自动关闭（幂等）。"""
        reaper = self._idle_reaper
        self._idle_reaper = None
        if reaper is not None:
            reaper.stop()

    def idle_status(self) -> dict:
        """空闲回收状态：回收器运行状态 + 各资源的空闲情况。"""
        reaper = self._idle_reaper
        rows = [
            {
                "name": r["name"],
                "loaded": r["loaded"],
                "idle_timeout": r["idle_timeout"],
                "idle_seconds": round(r["idle_seconds"], 1),
                "managed": r["managed"],
            }
            for r in self.list_resources()
        ]
        return {
            "enabled": reaper is not None,
            "reaper": reaper.status() if reaper is not None else None,
            "resources": rows,
        }

    def _ensure_loaded_for_task(self, info, task) -> None:
        """加载前先等待可能正在进行的空闲回收结束。

        基类实现在 resident 资源上会直接走 _do_load。若此刻另一个线程正在
        空闲回收该资源（停机是秒级阻塞动作），这里直接加载会与停机动作
        撞车 —— 请求要么打在正在被杀的服务上，要么把服务又拉起来，
        造成「刚回收完又被拉起」的抖动。

        因此这里先等回收结束；等完基类会看到 loaded=False 并正常重新加载。
        """
        name = getattr(info, "name", "")
        if name and name in self._reclaiming:
            logger.info("资源 %s 正在被空闲回收，等待回收完成后再加载", name)
            with self._condition:
                while name in self._reclaiming:
                    self._condition.wait(0.2)
        super()._ensure_loaded_for_task(info, task)

    # ── 便捷视图 ──

    def loaded_resources(self) -> list[str]:
        """当前处于已加载状态的资源名。"""
        return [r["name"] for r in self.list_resources() if r["loaded"]]

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<ResourcePool slots={self.max_concurrent} resources={len(self._specs)}>"
