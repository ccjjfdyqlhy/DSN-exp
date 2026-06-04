# world/plugin.py
# WorldPlugin — 世界模型插件 PRE_PROCESS + POST_PROCESS

from __future__ import annotations

import logging
from typing import Optional

from plugins.base import Plugin, HookPoint, PluginContext

logger = logging.getLogger("WorldPlugin")


class WorldPlugin(Plugin):
    """
    叙事世界插件。

    PRE_PROCESS:  将世界状态注入 system prompt（让主模型看到世界环境）
    POST_PROCESS: 生成叙事旁白 + 更新世界状态（时间前进、事件记录、工具→房间移动）
    """

    name = "world"
    description = "叙事世界模型 — 世界状态注入 + 旁白生成"
    hooks = [HookPoint.PRE_PROCESS, HookPoint.POST_PROCESS]
    priority = 15

    def __init__(
        self,
        world_engine=None,
        world_state_manager=None,
        narrative_model=None,
        personality_v2=None,
    ):
        self._engine = world_engine
        self._state_mgr = world_state_manager
        self._narrator = narrative_model
        self._persona = personality_v2

    def on_load(self) -> None:
        if self._engine is None:
            logger.warning("world_engine 未注入")
        else:
            logger.info("WorldPlugin 已加载: engine=%s, narrator=%s",
                         "OK" if self._engine else "MISSING",
                         "OK" if self._narrator else "MISSING")
        if self._narrator is None:
            logger.warning("narrative_model 未注入（旁白功能禁用）")

    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        if hook == HookPoint.PRE_PROCESS:
            return self._on_pre_process(ctx)
        if hook == HookPoint.POST_PROCESS:
            return self._on_post_process(ctx)
        return ctx

    # ── PRE_PROCESS ──

    def _on_pre_process(self, ctx: PluginContext) -> PluginContext:
        if self._engine is None or self._state_mgr is None:
            return ctx

        snapshot = self._state_mgr.get_snapshot()
        world_prompt = self._build_world_prompt(snapshot)
        if world_prompt and ctx.system_prompt:
            ctx.system_prompt = world_prompt + "\n\n" + ctx.system_prompt
            ctx.extra["world_snapshot"] = snapshot
            t = snapshot.get("time", {})
            logger.info("PRE_PROCESS: 世界环境已注入 (季节=%s, 房间=%s, 天气=%s)",
                        t.get("season_name", ""),
                        snapshot.get("location", {}).get("name", ""),
                        snapshot.get("weather", {}).get("current", ""))

        return ctx

    # ── POST_PROCESS ──

    def _on_post_process(self, ctx: PluginContext) -> PluginContext:
        if self._engine is None:
            return ctx

        self._update_location_from_tools(ctx)

        if self._narrator is not None:
            snapshot = self._state_mgr.get_snapshot() if self._state_mgr else self._engine.get_full_state()
            world_context = self._engine.get_complete_context()
            mood_label = self._get_mood_label(ctx)

            narrative = self._narrator.narrate(
                user_msg=ctx.message,
                main_reply=ctx.original_reply or ctx.reply or "",
                world_context=world_context,
                mood_label=mood_label,
            )
            if narrative:
                ctx.extra["narrative"] = narrative
                ctx.extra["narrative_speaker"] = "narrator"
                logger.info("POST_PROCESS: 旁白已生成 (%d 字) — %s...",
                            len(narrative), narrative[:60])
            else:
                logger.debug("POST_PROCESS: 旁白生成返回空文本")

        # Interaction events
        update = self._build_interaction_update(ctx)
        for evt in self._engine.check_interaction_events(update):
            self._engine.record_event(evt.get("text", ""), "interaction")

        self._engine.tick()
        return ctx

    # ── Internal ──

    def _build_world_prompt(self, snapshot: dict) -> str:
        if self._engine is None:
            return ""
        return self._engine.get_state_prompt()

    def _update_location_from_tools(self, ctx: PluginContext) -> None:
        reply = ctx.original_reply or ctx.reply or ""
        import re
        tool_pat = re.compile(r"<tool>\s*\{[^}]*\"skill\":\s*\"(\w+)\"", re.DOTALL)
        action_pat = re.compile(r"\"action_type\":\s*\"(\w+)\"", re.DOTALL)

        skills_found = tool_pat.findall(reply)
        actions_found = action_pat.findall(reply)

        moved = False
        for skill in skills_found:
            room = self._engine.map_tool_to_room(skill)
            if room != self._engine._current_location:
                self._engine.move_to(room, reason=f"调用工具 {skill}")
                logger.info("Tool→Room: %s -> %s", skill, room)
                moved = True
                break
        if not moved:
            for action in actions_found:
                room = self._engine.map_tool_to_room(action)
                if room != self._engine._current_location:
                    self._engine.move_to(room, reason=f"执行 {action} 操作")
                    logger.info("Action→Room: %s -> %s", action, room)
                    break

    def _get_mood_label(self, ctx: PluginContext) -> str:
        if self._persona is None:
            return ""
        try:
            state = self._persona.get_state(ctx.user_id)
            return state.get("mood", {}).get("label", "")
        except Exception:
            return ""

    def _build_interaction_update(self, ctx: PluginContext) -> dict:
        update = {}
        if self._persona:
            try:
                st = self._persona.get_state(ctx.user_id)
                aff = st.get("affinity", {})
                update["affinity_level"] = aff.get("level", 0)
                update["mood_label"] = st.get("mood", {}).get("label", "")
            except Exception:
                pass
        # Detect affinity level up
        prev = self._engine._prev_affinity_level if hasattr(self._engine, "_prev_affinity_level") else 0
        current = update.get("affinity_level", 0)
        update["affinity_just_leveled_up"] = current > prev
        if hasattr(self._engine, "_prev_affinity_level"):
            self._engine._prev_affinity_level = current

        # Detect mood shift
        prev_mood = self._engine._prev_mood_label if hasattr(self._engine, "_prev_mood_label") else ""
        update["mood_changed_suddenly"] = update.get("mood_label", "") != prev_mood
        if hasattr(self._engine, "_prev_mood_label"):
            self._engine._prev_mood_label = update.get("mood_label", "")

        # First tool use
        reply = ctx.original_reply or ctx.reply or ""
        has_tool = "<tool>" in reply or "\"action_type\"" in reply
        first = (not getattr(self._engine, "_first_tool_used", False)) and has_tool
        update["first_tool_use"] = first
        if first and hasattr(self._engine, "_first_tool_used"):
            self._engine._first_tool_used = True

        return update
