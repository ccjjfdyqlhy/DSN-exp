from __future__ import annotations

import logging
import time

from plugins.base import Plugin, HookPoint, PluginContext

logger = logging.getLogger("CacheInterceptor")


class CacheInterceptorPlugin(Plugin):
    name = "cache_interceptor"
    description = "语义缓存 — 拦截重复请求，直接返回缓存结果"
    hooks = [HookPoint.PRE_FILTER, HookPoint.POST_TTS]
    priority = 0

    def __init__(self, cache_engine=None, tts_client=None):
        self._engine = cache_engine
        self._tts = tts_client

    def on_load(self) -> None:
        if self._engine is None:
            logger.warning("CacheEngine 未注入，缓存系统不可用")

    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        if hook == HookPoint.PRE_FILTER:
            self._check_observer(ctx)
            return self._try_serve_from_cache(ctx)
        elif hook == HookPoint.POST_TTS:
            return self._write_to_cache(ctx)
        return ctx

    # ── 观察窗口: 检查上一轮命中后用户是否发出纠偏信号 ──

    def _check_observer(self, ctx: PluginContext):
        if not self._engine:
            return
        observer_key = ctx.extra.get("sc_observer_key")
        observer_end = ctx.extra.get("sc_observer_end", 0.0)
        if not observer_key or time.time() > observer_end:
            return
        if self._engine.is_negative_signal(ctx.message):
            self._engine.decay_score(observer_key)

    # ── 前置拦截 ──

    def _try_serve_from_cache(self, ctx: PluginContext) -> PluginContext:
        if not self._engine:
            return ctx

        message = ctx.message.strip()
        if not message:
            return ctx

        intent_class = self._engine.classify_intent(message)
        ctx.extra["sc_intent"] = intent_class

        l1_entry = self._engine.serve_l1(intent_class)
        if l1_entry:
            ctx.reply = l1_entry["text"]
            ctx.original_reply = l1_entry["text"]
            tts_path = l1_entry.get("tts_path", "")
            if tts_path:
                audio = self._engine._store.load_tts(tts_path)
                if audio:
                    ctx.audio = audio
            self._append_to_history(ctx, message, l1_entry["text"])
            ctx.filtered = True
            ctx.extra["sc_hit"] = "l1"
            logger.info("语义缓存 L1 命中: intent=%s", intent_class)
            return ctx

        results = self._engine.search(message, intent_class=intent_class, top_k=3)
        for r in results:
            if r.score < 0.35:
                continue
            ctx.reply = r.reply_text
            ctx.original_reply = r.reply_text
            tts_path = r.reply_tts_path
            if tts_path:
                audio = self._engine._store.load_tts(tts_path)
                if audio:
                    ctx.audio = audio
            self._append_to_history(ctx, message, r.reply_text)
            ctx.filtered = True
            ctx.extra["sc_hit"] = "l2"
            ctx.extra["sc_cache_key"] = r.cache_key
            ctx.extra["sc_similarity"] = r.similarity
            ctx.extra["sc_observer_key"] = r.cache_key
            ctx.extra["sc_observer_end"] = time.time() + 30
            self._engine.record_hit(r.cache_key)
            logger.info("语义缓存 L2 命中: key=%s sim=%.4f",
                        r.cache_key, r.similarity)
            return ctx

        ctx.extra["sc_hit"] = "miss"
        return ctx

    # ── 后置写入 ──

    def _write_to_cache(self, ctx: PluginContext) -> PluginContext:
        if not self._engine:
            return ctx

        if ctx.extra.get("sc_hit") != "miss":
            return ctx

        reply = ctx.original_reply or ctx.reply
        if not reply or len(reply) < 3:
            return ctx

        message = ctx.message.strip()
        intent_class = ctx.extra.get("sc_intent", "")

        tts_audio = ctx.audio
        cache_key = self._engine.cache_response(
            user_id=ctx.user_id,
            query_text=message,
            reply_text=reply,
            intent_class=intent_class,
            tts_audio=tts_audio,
        )
        if cache_key:
            ctx.extra["sc_cached_key"] = cache_key

        return ctx

    # ── 更新对话历史 ──

    @staticmethod
    def _append_to_history(ctx: PluginContext, user_msg: str, reply: str):
        ctx.history = list(ctx.history or [])
        ctx.history.append({"role": "user", "content": user_msg})
        ctx.history.append({"role": "assistant", "content": reply})
        ctx.full_history = list(ctx.full_history or [])
        ctx.full_history.append({"role": "user", "content": user_msg})
        ctx.full_history.append({"role": "assistant", "content": reply})
