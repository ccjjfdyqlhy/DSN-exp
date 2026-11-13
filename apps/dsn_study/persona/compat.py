# apps/dsn_study/persona/compat.py
"""PEV3 形状的兼容层 —— 让 API 与面板**零改动**地切到新的 PersonaEngine。

为什么需要：dsn_study 的 `/api/personality/*` 与面板 `/api/admin/persona/*`
对外暴露的是 PEV3 的方法名（``get_personality_status`` /
``get_personality_full`` / ``list_cards`` / ``bind_user_card`` /
``generate_personality_prompt``）。重建之后内部换成了 PersonaEngine，
但**对外契约不能变**（红线 R15：路由、状态码、错误体全部不变）。

这一层把新引擎适配成旧形状，只做转发，不含业务逻辑。
"""

from __future__ import annotations

import logging

from .engine import PersonaEngine

logger = logging.getLogger("StudyPersonaCompat")


class PersonaCompat:
    """把 :class:`PersonaEngine` 适配成 PEV3 的方法形状。"""

    def __init__(self, engine: PersonaEngine, pv3=None):
        self._engine = engine
        self._pv3 = pv3

    # ── PEV3 形状 ──

    def get_personality_status(self, uid: int) -> dict:
        """人格状态（PEV3 的字段形状 + 新引擎补充的偏离特质）。"""
        data = {}
        if self._pv3 is not None:
            try:
                raw = self._pv3.get_personality_status(uid) or {}
                if isinstance(raw, dict):
                    data.update(raw)
            except Exception:   # noqa: BLE001
                logger.warning("人格状态读取失败（降级）", exc_info=True)
        if not data:
            try:
                data = dict(self._engine.status(uid))
            except Exception:   # noqa: BLE001
                logger.warning("人格状态降级读取失败", exc_info=True)
                data = {"uid": int(uid)}
        data.setdefault("uid", int(uid))
        # 新引擎的偏离特质（只给有意义的偏离项，不给全量 50 维）
        try:
            status = self._engine.status(uid)
            if isinstance(status, dict) and status.get("traits"):
                data["deviant_traits"] = status["traits"]
        except Exception:   # noqa: BLE001
            pass
        return data

    def get_personality_full(self, uid: int) -> dict:
        """全量状态（含 50 维向量）—— 调试用。"""
        if self._pv3 is not None:
            try:
                raw = self._pv3.get_personality_full(uid)
                if isinstance(raw, dict):
                    return raw
            except Exception:   # noqa: BLE001
                logger.warning("人格全量读取失败（降级）", exc_info=True)
        return self.get_personality_status(uid)

    def list_cards(self) -> list[dict]:
        """可用角色卡清单。"""
        try:
            return self._engine.cards() or []
        except Exception:   # noqa: BLE001
            logger.warning("角色卡清单读取失败（降级为空）", exc_info=True)
            return []

    def bind_user_card(self, uid: int, card_id: str) -> bool:
        """切换用户绑定的角色卡。"""
        try:
            return bool(self._engine.switch(uid, card_id))
        except Exception:   # noqa: BLE001
            logger.warning("角色卡切换失败（降级为失败）", exc_info=True)
            return False

    def generate_personality_prompt(self, uid: int) -> str:
        """当前注入 system prompt 的人格段落。"""
        try:
            return self._engine.prompt_block(uid) or ""
        except Exception:   # noqa: BLE001
            logger.warning("人格提示词生成失败（降级为空）", exc_info=True)
            return ""
