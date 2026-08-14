# scripts/plugin.py
# ScriptPlugin — 管道钩子集成（PRE_FILTER + PRE_PROCESS + POST_PROCESS）

import logging

from harness.pipeline import Plugin, HookPoint, Context as PluginContext

logger = logging.getLogger("ScriptPlugin")


class ScriptPlugin(Plugin):
    name = "script"
    description = "剧本系统 — 引导用户/游戏/业务话术"
    version = "1.0"
    hooks = [HookPoint.PRE_FILTER, HookPoint.PRE_PROCESS, HookPoint.POST_PROCESS]
    priority = 10

    def __init__(self, engine=None, ooc=None, recorder=None, player=None):
        self._engine = engine
        self._ooc = ooc
        self._recorder = recorder
        self._player = player

    def on_load(self) -> None:
        logger.info("ScriptPlugin 已加载")

    def on_unload(self) -> None:
        logger.info("ScriptPlugin 已卸载")

    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        if hook == HookPoint.PRE_FILTER:
            return self._on_pre_filter(ctx)
        if hook == HookPoint.PRE_PROCESS:
            return self._on_pre_process(ctx)
        if hook == HookPoint.POST_PROCESS:
            return self._on_post_process(ctx)
        return ctx

    def _on_pre_filter(self, ctx: PluginContext) -> PluginContext:
        if not self._engine or not self._engine.is_active():
            return ctx

        chapter = self._engine.get_chapter()
        if not chapter:
            return ctx

        strictness = self._engine.settings.get("ooc_strictness", 0.8)
        detector_mode = self._engine.settings.get("ooc_detector", "hybrid")

        if self._ooc:
            result = self._ooc.check(
                ctx.message,
                {"name": chapter.name, "guidance": chapter.guidance},
                strictness=strictness,
                detector_mode=detector_mode,
            )
            if result.should_reject:
                ctx.filtered = True
                ctx.reply = f"[剧本模式] {result.reason}\n{result.redirect}"
                ctx.extra["script_ooc"] = True
                logger.info("OOC 硬拒绝: severity=%.2f reason=%s", result.severity, result.reason)
            elif result.severity >= 0.4:
                ctx.extra["script_ooc_soft"] = True
                ctx.extra["script_ooc_redirect"] = result.redirect
                logger.info("OOC 软提醒: severity=%.2f", result.severity)

        return ctx

    def _on_pre_process(self, ctx: PluginContext) -> PluginContext:
        if not self._engine or not self._engine.is_active():
            return ctx

        guidance = self._engine.get_guidance()
        if guidance:
            prefix = (
                "【重要指令 — 你现在处于剧本模式，必须严格按照以下指引行事】\n\n"
                f"{guidance}\n\n"
                "---\n\n"
            )
            ctx.system_prompt = prefix + ctx.system_prompt

        if ctx.extra.get("script_ooc_soft"):
            redirect = ctx.extra.get("script_ooc_redirect", "")
            if redirect:
                ctx.system_prompt = (
                    f"【注意】用户刚才的输入可能偏离了当前主题。试着自然地引导回来：{redirect}\n\n"
                    + ctx.system_prompt
                )

        if self._player and self._engine.settings.get("recordable", True):
            match = self._player.find_match(
                ctx.user_id,
                ctx.message,
                self._engine.active_script,
                self._engine.active_chapter,
                replay_mode=self._engine.settings.get("recording", {}).get("replay_mode", "exact"),
            )
            if match:
                ctx.reply = match
                ctx.extra["script_replayed"] = True
                ctx.filtered = True
                logger.info("回放命中: %s/%s", self._engine.active_script, self._engine.active_chapter)

        return ctx

    def _on_post_process(self, ctx: PluginContext) -> PluginContext:
        if not self._engine or not self._engine.is_active():
            return ctx

        if ctx.extra.get("script_replayed"):
            ctx.extra["script_progressed"] = True
            ctx.extra["script_completed"] = self._engine.is_complete()
            return ctx

        self._engine.increment_turn()

        new_points = self._engine.check_key_points(
            ctx.message, ctx.reply, ctx.extra.get("_tool_name", "")
        )
        if new_points:
            ctx.extra["script_key_points"] = new_points

        if self._recorder and self._engine.settings.get("recordable", True):
            try:
                from apps.dsn.scripts.recorder import RecordContext
                rec_ctx = RecordContext(
                    user_id=ctx.user_id,
                    script_id=self._engine.active_script,
                    chapter_id=self._engine.active_chapter,
                    key_points_met=[k for k, v in self._engine._scores.items() if v > 0],
                    user_input=ctx.message,
                    ai_reply=ctx.reply,
                    tool_calls=ctx.extra.get("_tool_name", ""),
                    replay_mode=self._engine.settings.get("recording", {}).get("replay_mode", "exact"),
                )
                self._recorder.record(rec_ctx)
            except Exception:
                logger.exception("录制失败")

        if self._engine.advance():
            ctx.extra["chapter_advanced"] = True
            logger.info("章节推进: %s", self._engine.active_chapter)

        if self._engine.is_complete():
            self._engine.stop()
            ctx.extra["script_completed"] = True
            logger.info("剧本完成: %s", self._engine.active_script)

        return ctx