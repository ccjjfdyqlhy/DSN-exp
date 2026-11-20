# harness/voice —— 全模态的交互层（roadmap 段 5：开口即达）。
#
# 框架之前只有**语音资源层**（infra/resources：ASR/TTS 进程池、显存感知、
# 空闲回收），没有**交互层** —— 流式逐句朗读、假语音过滤、感知模式
# （连续通话，沉默 = 在听）、心跳（空闲主动开口）全在私有应用里。
# 这个包把交互逻辑下沉到框架，应用只提供 IO 端口：
#
#   streaming.SentenceStreamSpeaker   流式逐句朗读（合成一句播一句）
#   filter.HeuristicSpeechFilter      假语音兜底过滤（1B 分类器是端口）
#   session.VoiceSession              感知模式主循环 + 心跳主动开口
#
# 依赖方向：本包不 import infra —— TTS/ASR 进程归资源池管，应用把
# 客户端适配成端口（TTSClientPort / ASRPort / AudioSinkPort）插进来。
# 所以交互逻辑可以离线测试，不需要起真的语音模型。

from .filter import (
    CompositeSpeechFilter,
    HeuristicSpeechFilter,
    SpeechFilterPort,
    SpeechVerdict,
)
from .session import ASRPort, Heartbeat, SessionState, VoiceIO, VoiceSession, VoiceTurn
from .streaming import (
    AudioSinkPort,
    SentenceSplitter,
    SentenceStreamSpeaker,
    TTSClientPort,
)

__all__ = [
    # 流式朗读
    'SentenceSplitter',
    'SentenceStreamSpeaker',
    'TTSClientPort',
    'AudioSinkPort',
    # 假语音过滤
    'SpeechFilterPort',
    'SpeechVerdict',
    'HeuristicSpeechFilter',
    'CompositeSpeechFilter',
    # 感知模式与心跳
    'ASRPort',
    'VoiceIO',
    'VoiceSession',
    'VoiceTurn',
    'SessionState',
    'Heartbeat',
]
