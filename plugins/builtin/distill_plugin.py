# plugins/builtin/distill_plugin.py
# 双引擎蒸馏触发器插件 — POST_PROCESS (priority 100, 最后执行)

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta

from plugins.base import Plugin, HookPoint, PluginContext

logger = logging.getLogger("DistillPlugin")


class DistillPlugin(Plugin):
    """
    双引擎蒸馏触发插件。

    引擎 A — V3 性格蒸馏（材料驱动）:
      - 检测是否有新的经历素材导入
      - 有新材料时立即触发 V3 蒸馏（异步后台执行）
      - 蒸馏完成后更新 50 维性格向量

    引擎 B — 技能模式蒸馏（定时 + 关键词）:
      - 每 168 小时（7 天）定时触发
      - 或检测到对话关键词时触发
      - 分析聊天记录挖对话模式，产出技能草案

    POST_PROCESS 阶段 (priority 100) — 所有其他插件之后。
    """

    name = "distill"
    description = "双引擎蒸馏 — 材料驱动 V3 人格蒸馏 + 定时技能模式蒸馏"
    hooks = [HookPoint.POST_PROCESS]
    priority = 100

    # 蒸馏触发关键词
    _TRIGGER_KEYWORDS = [
        "总结学到了什么",
        "你学到了什么",
        "蒸馏技能",
        "分析对话模式",
        "生成技能草案",
        "蒸馏人格",
        "更新人格",
        "重新蒸馏",
    ]

    def __init__(self, distillation_engine=None, interval_hours: int = 168,
                 v3_system=None, card_id: str = "exa"):
        self._skill_engine = distillation_engine
        self._interval_hours = interval_hours
        self._v3 = v3_system
        self._card_id = card_id
        self._last_skill_run: datetime | None = None
        self._lock = threading.Lock()

    def on_load(self) -> None:
        if self._skill_engine is None:
            logger.warning("skill distillation_engine 未注入，技能蒸馏将跳过")
        if self._v3 is None:
            logger.warning("v3_system 未注入，V3 性格蒸馏将跳过")

    def on_hook(self, hook: HookPoint, ctx: PluginContext) -> PluginContext:
        if hook != HookPoint.POST_PROCESS:
            return ctx

        if self._v3 is not None:
            self._run_v3_distillation_if_needed()

        should_run_skill = self._check_timed_trigger()
        if not should_run_skill and ctx.message:
            for keyword in self._TRIGGER_KEYWORDS:
                if keyword in ctx.message:
                    should_run_skill = True
                    logger.info("检测到蒸馏触发关键词: %s", keyword)
                    break

        if should_run_skill and self._skill_engine is not None:
            self._run_skill_distillation_async(ctx.user_id, ctx.chat_id)

        return ctx

    # ── V3 性格蒸馏 ──

    def _run_v3_distillation_if_needed(self):
        if not self._v3.is_distillation_needed(self._card_id):
            return
        try:
            imported = self._v3.import_pending_materials(self._card_id)
            if imported > 0:
                logger.info("V3: 从 materials/%s 导入了 %d 个新素材", self._card_id, imported)
            if not self._v3.is_distillation_needed(self._card_id):
                return
            with self._lock:
                if not self._v3.is_distillation_needed(self._card_id):
                    return
                logger.info("V3: 检测到蒸馏标记，后台启动性格蒸馏 (card=%s)...", self._card_id)
                t = threading.Thread(target=self._do_v3_distill, daemon=True,
                                     name="distill-v3-worker")
                t.start()
        except Exception:
            logger.exception("V3 蒸馏检查异常")

    def _do_v3_distill(self):
        card_id = self._card_id
        logger.info("V3: 开始性格蒸馏 %s...", card_id)
        try:
            result = self._v3.distill(card_id, model_name="openai")
            if result:
                self._v3.mark_distillation_done(card_id)
                logger.info("V3: 性格蒸馏完成 version=%d dims=%d",
                             result.version, len(result.indicator_vector))
            else:
                logger.warning("V3: 蒸馏返回 None（可能指纹未变跳过）")
        except Exception:
            logger.exception("V3 蒸馏执行异常")

    # ── 技能模式蒸馏 ──

    def _check_timed_trigger(self) -> bool:
        with self._lock:
            if self._last_skill_run is None:
                self._last_skill_run = datetime.now()
                return False
            elapsed = datetime.now() - self._last_skill_run
            if elapsed >= timedelta(hours=self._interval_hours):
                self._last_skill_run = datetime.now()
                return True
        return False

    def _run_skill_distillation_async(self, user_id: int, chat_id: int) -> None:
        def _run():
            try:
                logger.info("技能蒸馏: 开始 (user=%s, chat=%s)", user_id, chat_id)
                report = self._skill_engine.run(user_id=user_id)
                drafts_count = report.get("drafts_created", 0)
                patterns_count = report.get("patterns_found", 0)
                if drafts_count > 0:
                    logger.info("技能蒸馏: 完成 — 发现 %d 个模式, 生成 %d 个草案",
                                 patterns_count, drafts_count)
                else:
                    logger.info("技能蒸馏: 完成 — 未生成新草案 (模式=%d)", patterns_count)
            except Exception:
                logger.exception("技能蒸馏执行异常")

        t = threading.Thread(target=_run, daemon=True, name="distill-skill-worker")
        t.start()
