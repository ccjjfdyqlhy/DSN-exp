# model_scheduler.py
# 模型共存调度器 — 限制同时加载的大语言模型数量，LRU 驱逐 + 自动换入换出

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from typing import Callable, Optional

import requests

logger = logging.getLogger("ModelScheduler")


# 延迟导入，避免循环依赖
def _get_lm_load_unload():
    from models import _load_lmstudio_model, _unload_lmstudio_model
    return _load_lmstudio_model, _unload_lmstudio_model


def _get_loaded_models(base_url: str) -> list[str]:
    """查询 LMStudio 当前已加载的模型名称列表。GET /v1/models"""
    try:
        url = f"{base_url}/v1/models"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        models = []
        for m in data.get("data", []):
            mid = m.get("id", "")
            if mid:
                models.append(mid)
        return models
    except Exception:
        return []


class ModelInfo:
    """单个模型的注册信息"""

    __slots__ = ("name", "base_url", "load_fn", "unload_fn", "resident",
                 "loaded", "refcount", "last_used")

    def __init__(self, name: str, base_url: str, load_fn: Callable,
                 unload_fn: Callable, resident: bool = False):
        self.name = name
        self.base_url = base_url
        self.load_fn = load_fn      # () → bool
        self.unload_fn = unload_fn  # () → bool
        self.resident = resident    # 常驻模型，不被 LRU 驱逐
        self.loaded = False
        self.refcount = 0
        self.last_used = 0.0


class ModelScheduler:
    """
    模型共存调度器（全局单例，线程安全）。

    职责：
    - 限制同时加载的非 resident 语言模型数量（不超过 max_concurrent）
    - 请求到来时自动加载所需模型，必要时驱逐 LRU 模型
    - 被驱逐模型的 refcount=0（完成中的请求不受影响，下次请求时重新加载）

    用法：
        scheduler = ModelScheduler.get_instance()
        scheduler.register("gemma", "http://localhost:4501",
                           load_fn=lambda: ..., unload_fn=lambda: ...)
        with scheduler.use("gemma"):
            # 模型已确保加载，执行业务逻辑
            result = chat_api_call()
    """

    _instance: Optional["ModelScheduler"] = None

    # ------------------------------------------------------------------
    # 单例
    # ------------------------------------------------------------------

    @classmethod
    def get_instance(cls) -> "ModelScheduler":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls):
        """仅供测试使用"""
        cls._instance = None

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------

    def __init__(self, max_concurrent: int = 1):
        from config import Config
        self.max_concurrent = max_concurrent or Config.MAX_CONCURRENT_LM_MODELS
        self._lock = threading.RLock()
        self._models: dict[str, ModelInfo] = {}
        self._lru_order: list[str] = []     # 最久未用排前面
        self._load_wait_events: dict[str, threading.Event] = {}
        # 自动注册嵌入模型为 resident（不占 max_concurrent 名额）
        from config import Config as _Cfg
        emb_model = _Cfg.MEMORY_EMBEDDING_MODEL
        if emb_model and _Cfg.MEMORY_EMBEDDING_ENABLED:
            self.register(
                model_name=emb_model,
                base_url=_Cfg.LMSTUDIO_BASE_URL,
                load_fn=lambda: _load_lmstudio_model(_Cfg.LMSTUDIO_BASE_URL, emb_model, "embedding"),
                unload_fn=lambda: _unload_lmstudio_model(_Cfg.LMSTUDIO_BASE_URL, emb_model),
                resident=True,
            )
        logger.info("ModelScheduler 已初始化 (max_concurrent=%d)", self.max_concurrent)

    # ------------------------------------------------------------------
    # 注册
    # ------------------------------------------------------------------

    def register(self, model_name: str, base_url: str,
                 load_fn: Callable, unload_fn: Callable,
                 resident: bool = False):
        """注册一个模型。可重复调用，幂等。"""
        with self._lock:
            if model_name in self._models:
                return
            self._models[model_name] = ModelInfo(
                name=model_name, base_url=base_url,
                load_fn=load_fn, unload_fn=unload_fn,
                resident=resident,
            )
            self._load_wait_events[model_name] = threading.Event()
            self._load_wait_events[model_name].set()  # not loading initially
            logger.info("已注册模型: %s (base=%s resident=%s)", model_name, base_url, resident)

    def mark_preloaded(self, model_name: str):
        """标记模型为开机已加载（由 boot 预加载逻辑调用）"""
        with self._lock:
            info = self._models.get(model_name)
            if info:
                info.loaded = True
                info.last_used = time.time()
                logger.info("标记预加载模型: %s", model_name)

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    @contextmanager
    def use(self, model_name: str, timeout: float = 300):
        """
        上下文管理器：确保 model_name 已加载，执行业务代码。

        用法:
            with scheduler.use("deepseek-ocr"):
                result = ocr_model.do_ocr()
        """
        if model_name not in self._models:
            raise ValueError(f"模型未注册: {model_name}")

        self._acquire(model_name, timeout)
        try:
            yield
        finally:
            self._release(model_name)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _acquire(self, model_name: str, timeout: float):
        """获取模型使用权，必要时加载 / 驱逐其他模型"""
        deadline = time.time() + timeout
        info = self._models[model_name]

        with self._lock:
            if info.loaded:
                info.refcount += 1
                info.last_used = time.time()
                self._bump_lru(model_name)
                return

            # 需要加载：如果已经满员，驱逐一个
            while time.time() < deadline:
                loaded_non_resident = [
                    n for n in self._lru_order
                    if self._models[n].loaded and not self._models[n].resident
                ]
                if len(loaded_non_resident) < self.max_concurrent:
                    break

                # 找 refcount=0 的 LRU 模型驱逐
                victim = None
                for n in self._lru_order:
                    m = self._models[n]
                    if m.loaded and not m.resident and m.refcount == 0:
                        victim = n
                        break

                if victim:
                    self._do_unload(victim)
                    continue

                # 全部 busy，等一下再试
                self._lock.release()
                time.sleep(0.3)
                self._lock.acquire()

            if time.time() >= deadline:
                raise TimeoutError(f"无法在 {timeout}s 内获取模型 {model_name} 的使用权")

            # 加载目标模型
            self._do_load(model_name)
            info.refcount = 1
            info.last_used = time.time()

    def _release(self, model_name: str):
        """释放模型使用权（不立即卸载）"""
        with self._lock:
            info = self._models[model_name]
            info.refcount = max(0, info.refcount - 1)
            info.last_used = time.time()

    def _do_load(self, model_name: str):
        """加载模型（调用方持有锁）"""
        info = self._models[model_name]
        if info.loaded:
            return
        logger.info("正在加载模型: %s ...", model_name)
        try:
            ok = info.load_fn()
            if ok:
                info.loaded = True
                self._bump_lru(model_name)
                logger.info("模型加载完成: %s", model_name)
            else:
                logger.error("模型加载失败: %s", model_name)
                raise RuntimeError(f"模型 {model_name} 加载失败")
        except Exception:
            logger.exception("模型加载异常: %s", model_name)
            raise

    def _do_unload(self, model_name: str):
        """卸载模型（调用方持有锁）"""
        info = self._models[model_name]
        if not info.loaded:
            return
        if info.refcount > 0:
            return  # 还有使用方，不卸载
        logger.info("正在卸载模型: %s (LRU驱逐)", model_name)
        try:
            info.unload_fn()
        except Exception:
            logger.exception("模型卸载异常: %s", model_name)
        info.loaded = False
        if model_name in self._lru_order:
            self._lru_order.remove(model_name)

    def _bump_lru(self, model_name: str):
        """将模型移到 LRU 列表末尾（最近使用）"""
        if model_name in self._lru_order:
            self._lru_order.remove(model_name)
        self._lru_order.append(model_name)
