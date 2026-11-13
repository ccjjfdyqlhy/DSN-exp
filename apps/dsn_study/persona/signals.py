"""规则信号抽取 —— dsn_study 侧的**零 LLM** 事件判定。

为什么不用 LLM 判事件
---------------------
人格回写是**后台线程**，而 LLM 判定要排 provider 队列 —— 实测会把用户的
下一轮主回复拖到 50~100 秒（背景见 ``apps/dsn_study/turn_gate.py``）。
「这一轮用户是在表扬还是在抱怨」这类信号，用关键词表就能判得足够准：
判错的代价（多一条人格证据）远小于拖慢主回复的代价。

契约（``apps/dsn_study/REBUILD_SPEC.md`` §3.2）
--------------------------------------------
* 规则表：**保守** —— 宁可判 neutral，也不要把普通陈述句误判成情绪事件；
* 一次调用**最多返回 1 条**信号（避免一轮灌多条证据）；
* 命中多条时按 ``conflict > venting > complaint > thanks > praise`` 取一条；
* 关键词用**子串包含**匹配，大小写与全半角不敏感，**不引入正则依赖**。

显式答题结果与关键词命中**同池竞争**：两者都算「命中」，最终按事件优先级
只留一条。这样 ``answer_correct=True`` 且用户说「谢谢」时记的是
``thanks``（用户确实在道谢）而不是 ``praise``（用户并没有夸角色）；
反过来 ``answer_correct=True`` 但用户说「没懂」时记的是 ``complaint``。
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass

from harness.personality.events import (
    EVENT_COMPLAINT,
    EVENT_CONFLICT,
    EVENT_NEUTRAL,
    EVENT_PRAISE,
    EVENT_THANKS,
    EVENT_VENTING,
    INTENSITY_HIGH,
    INTENSITY_LOW,
    INTENSITY_MEDIUM,
)

__all__ = ["Signal", "extract_signals", "SIGNAL_PRIORITY"]


@dataclass(frozen=True)
class Signal:
    """一条语义事件信号（不含任何数值 —— 数值由 PEV3 的动力学层派生）。"""

    event_type: str      # 必须是 harness.personality.events.EVENT_TYPES 里的枚举
    intensity: str       # 'low' | 'medium' | 'high'
    valence: str         # 'positive' | 'neutral' | 'negative'
    reason: str = ""


#: 命中多条时的优先级（越靠前越优先）。
SIGNAL_PRIORITY: tuple[str, ...] = (
    EVENT_CONFLICT,
    EVENT_VENTING,
    EVENT_COMPLAINT,
    EVENT_THANKS,
    EVENT_PRAISE,
)

#: 关键词规则表：(event_type, intensity, valence, 关键词元组)。
#:
#: 顺序即优先级 —— conflict > venting > complaint > thanks。
#: praise 没有关键词规则：它只由「答题结果正确」触发（用户夸角色
#: 是一种更明确的语义事件，不靠「好棒」这类模糊词猜）。
_KEYWORD_RULES: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (EVENT_CONFLICT, INTENSITY_HIGH, "negative",
     ("生气", "你有病", "别管我", "滚")),
    (EVENT_VENTING, INTENSITY_MEDIUM, "negative",
     ("烦", "累", "不想学", "放弃", "压力")),
    (EVENT_COMPLAINT, INTENSITY_MEDIUM, "negative",
     ("搞错", "不对", "错了", "没懂", "听不懂")),
    (EVENT_THANKS, INTENSITY_MEDIUM, "positive",
     ("谢谢", "厉害", "牛", "学到了", "懂了")),
)


def _normalize(text: str) -> str:
    """归一化：全半角（NFKC）+ 大小写。

    NFKC 会把全角字母/标点折成半角（Ａ→A、！→!），casefold 处理拉丁字母。
    中文关键词不受影响，但混排的英文/标点会被统一，匹配更稳。
    """
    if not text:
        return ""
    return unicodedata.normalize("NFKC", text).casefold()


def extract_signals(user_msg: str, reply: str = "",
                    *,
                    answer_correct: bool | None = None,
                    answer_wrong: bool | None = None) -> list[Signal]:
    """从一轮对话里抽取**至多一条**语义信号。

    :param user_msg: 用户这一轮说的话（规则只看它）。
    :param reply: 助手的回复 —— 规则**不**看它（回复是结果，不是事件），
        保留这个参数是为了与 LLM 判定路径（``analyze_interaction``）签名对齐，
        以及给未来的规则留位置。
    :param answer_correct: 应用侧已知的「这次答对了」。
    :param answer_wrong: 应用侧已知的「这次答错了」。
    :returns: 长度为 0 或 1 的列表（契约要求最多一条；此处恒返回一条，
        没命中时给 ``neutral``）。
    """
    text = _normalize(user_msg or "")

    # 命中集合：event_type -> (intensity, valence, reason)
    hits: dict[str, tuple[str, str, str]] = {}

    # ① 显式答题结果（应用侧的地面真相）
    if answer_wrong is True and answer_correct is True:
        # 两个标记互相矛盾 —— 当作没给，退回关键词判定
        pass
    elif answer_wrong is True:
        hits[EVENT_COMPLAINT] = (INTENSITY_MEDIUM, "negative", "答题结果：答错")
    elif answer_correct is True:
        hits[EVENT_PRAISE] = (INTENSITY_MEDIUM, "positive", "答题结果：答对")

    # ② 关键词（子串包含）
    for event_type, intensity, valence, keywords in _KEYWORD_RULES:
        if event_type in hits:
            continue
        for kw in keywords:
            if kw in text:
                hits[event_type] = (intensity, valence, "关键词命中「%s」" % kw)
                break

    # ③ 按优先级取一条
    for event_type in SIGNAL_PRIORITY:
        found = hits.get(event_type)
        if found is None:
            continue
        intensity, valence, reason = found
        return [Signal(event_type=event_type, intensity=intensity,
                       valence=valence, reason=reason)]

    # ④ 其它 → neutral
    return [Signal(event_type=EVENT_NEUTRAL, intensity=INTENSITY_LOW,
                   valence="neutral", reason="无明确情绪信号")]
