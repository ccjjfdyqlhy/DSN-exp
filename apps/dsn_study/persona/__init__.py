"""dsn_study 人格内核（薄层）。

底座是 ``harness/personality``（PEV3）—— 动力学、证据、审计、落库、
缓存分桶、兜底串都在那边，**本包不重写人格引擎**。这里只做
dsn_study 侧的四件事：

  * **卡片管理** —— ``persona/cards/``（版本化，进 git）+ 切换；
  * **信号抽取** —— ``signals.py``：零 LLM 的规则事件判定；
  * **提示词呈现** —— ``engine.PersonaEngine.prompt_block()``：
    档案正文 + 关系阶段 + 偏离基线的特质，≤800 字；
  * **API 数据形状** —— ``engine.PersonaEngine.status()``。

红线 R6：人格系统的任何故障都只能降级，**绝不能让整轮对话失败**。

契约见 ``apps/dsn_study/REBUILD_SPEC.md`` §3。
"""

from __future__ import annotations

from .compat import PersonaCompat
from .engine import (
    DEFAULT_CARD_ID,
    DEFAULT_CARDS_DIR,
    MAX_PROMPT_CHARS,
    TRAIT_DEVIATION_THRESHOLD,
    PersonaEngine,
)
from .signals import SIGNAL_PRIORITY, Signal, extract_signals

__all__ = [
    "PersonaEngine",
    "PersonaCompat",
    "Signal",
    "extract_signals",
    "SIGNAL_PRIORITY",
    "MAX_PROMPT_CHARS",
    "TRAIT_DEVIATION_THRESHOLD",
    "DEFAULT_CARDS_DIR",
    "DEFAULT_CARD_ID",
]
