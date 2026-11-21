# harness/voice/filter.py
# ASR 假语音过滤（roadmap 段 5）：「这是不是真语音」在进模型之前先答一遍。
#
# ── 为什么要有这道闸 ──
# 连续通话（感知模式）下，环境噪声 / 电视声 / 半截气音都会被 ASR 转成
# 文本 —— 它们会变成「用户发言」进对话史，然后模型对着空气认真回答。
# 真产品里的做法是一个小分类器（1B 级）判「真语音 / 噪声」；
# 在框架层，分类器是**端口**（应用有就插），默认给一套无依赖的
# 启发式规则兜底 —— 规则拦不住的会漏过去，但**绝不误伤正常发言**
# （宁可放进一句噪声，不可掐掉一句真话）。
#
# 语义是「建议」不是「判决」：调用方可以带 `allow_rejected=True`
# 把被拒文本继续传下去（只是打上标记）—— 因为漏一句噪声的代价
# 是一次傻回答，错杀一句真话的代价是用户再也不说话。

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Protocol

__all__ = [
    'SpeechFilterPort',
    'SpeechVerdict',
    'HeuristicSpeechFilter',
    'CompositeSpeechFilter',
]

# ── 判定结果 ────────────────────────────────────────────────


@dataclass(frozen=True)
class SpeechVerdict:
    """一次过滤的判定。"""

    accepted: bool
    reason: str = ''            # 拒绝原因（accepted=True 时为空）
    confidence: float = 1.0     # 0~1；启发式的置信度是人为分级的

    @classmethod
    def ok(cls, confidence: float = 1.0) -> 'SpeechVerdict':
        return cls(accepted=True, confidence=confidence)

    @classmethod
    def reject(cls, reason: str, confidence: float = 1.0) -> 'SpeechVerdict':
        return cls(accepted=False, reason=reason, confidence=confidence)


class SpeechFilterPort(Protocol):
    """分类器端口 —— 应用的 1B 分类器实现这个形状即可。"""

    def classify(self, text: str, *, audio: Optional[bytes] = None) -> SpeechVerdict:
        ...


# ── 启发式兜底 ──────────────────────────────────────────────

#: 可读字符（字母 / CJK / 常见数字语境）之外的东西
_PRONOUNCEABLE = re.compile(r'[\w\u4e00-\u9fff]')
#: 同一 token 高频重复（啊啊啊啊 / 嗯嗯嗯嗯嗯嗯）
_REPEATED_RUN = re.compile(r'^(.{1,3}?)\1{4,}$', re.UNICODE)


class HeuristicSpeechFilter:
    """无依赖的假语音兜底规则（故意保守 —— 拦得狠不如拦得准）。

    拦四类：
      1. 太短：剥掉标点后不足 min_chars（感知模式下的咳嗽 / 碰撞声）；
      2. 无可读内容：几乎全是标点 / 符号 / 数字外的乱码；
      3. 机械重复：同一小段连续重复 ≥5 次（哼鸣 / 麦克风啸叫转写）；
      4. 辅音堆：拉丁字母长串里没有元音（键盘乱敲）。

    不拦：
      - 正常长度的一句话，哪怕只有一个词（"停"、"继续" 都是合法指令）；
      - 纯数字 / 时间（"123456" 可能是验证码口述）—— 有可读字符就过。
    """

    def __init__(self, *, min_chars: int = 1):
        # min_chars=1：单个 CJK 字就是完整的词（「停」「嗯」都是合法指令），
        # 不能按「至少两个字符」误杀。拉丁字母单词天然 ≥1。
        self.min_chars = max(1, min_chars)

    def classify(self, text: str, *, audio: Optional[bytes] = None) -> SpeechVerdict:
        stripped = (text or '').strip()
        if not stripped:
            return SpeechVerdict.reject('empty')
        if len(_PRONOUNCEABLE.sub('', stripped)) > len(stripped) * 0.8:
            return SpeechVerdict.reject('mostly_symbols', confidence=0.8)
        if len(_PRONOUNCEABLE.findall(stripped)) < self.min_chars:
            return SpeechVerdict.reject('too_short', confidence=0.7)
        if _REPEATED_RUN.match(stripped):
            return SpeechVerdict.reject('repeated_run', confidence=0.85)
        for run in re.findall(r'[a-zA-Z]{6,}', stripped):
            if not re.search(r'[aeiouAEIOU]', run):
                return SpeechVerdict.reject('consonant_run', confidence=0.75)
        return SpeechVerdict.ok(confidence=0.6)


class CompositeSpeechFilter:
    """端口优先，启发式兜底。

    语义（写死，不做成开关）：
      - 有分类器端口：端口的判定就是结果（端口挂了 → 退化为启发式）；
      - 没有端口：启发式就是结果。
    """

    def __init__(self, port: Optional[SpeechFilterPort] = None,
                 fallback: Optional[HeuristicSpeechFilter] = None):
        self.port = port
        self.fallback = fallback or HeuristicSpeechFilter()

    def classify(self, text: str, *, audio: Optional[bytes] = None) -> SpeechVerdict:
        if self.port is not None:
            try:
                return self.port.classify(text, audio=audio)
            except Exception:  # noqa: BLE001 —— 分类器故障不能卡死通话
                pass
        return self.fallback.classify(text, audio=audio)
