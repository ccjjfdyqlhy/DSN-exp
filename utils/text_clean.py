# utils/text_clean.py
# 文本清洗工具 — app.py 和 engine.py 共用


def clean_display(raw: str, preserve_newlines: bool = True) -> str:
    """
    移除控制标签，返回纯净显示文本。

    :param raw: 原始回复（含 <text>, <task>, <tool>, <recall>, ```action 标签）
    :param preserve_newlines: True=保留换行（用于前端流式 + 历史渲染）；False=TTS 模式全部压缩
    """
    import re

    t = raw
    t = re.sub(r'```action\s*\n.*?```', '', t, flags=re.DOTALL | re.IGNORECASE)
    t = re.sub(r'<text>(.*?)</text>', r'\1', t, flags=re.DOTALL | re.IGNORECASE)
    for tag in ("task", "tool", "recall"):
        t = re.sub(rf"<{tag}>.*?</{tag}>", '', t, flags=re.DOTALL)
    t = re.sub(r'<[^>]+>', '', t)
    if preserve_newlines:
        t = re.sub(r'[^\S\n]+', ' ', t).strip()
    else:
        t = re.sub(r'\s+', ' ', t).strip()
    return t


def clean_tts_text(raw: str) -> str:
    """
    为 TTS 合成移除所有标签，保留换行结构以便按句切分合成。

    :param raw: 原始回复
    :return: 纯文本，句子以 \\n 分隔
    """
    import re

    t = raw
    t = re.sub(r'```action\s*\n.*?```', '', t, flags=re.DOTALL | re.IGNORECASE)
    t = re.sub(r'<text>(.*?)</text>', '', t, flags=re.DOTALL | re.IGNORECASE)
    for tag in ("task", "tool", "recall"):
        t = re.sub(rf"<{tag}>.*?</{tag}>", '', t, flags=re.DOTALL)
    t = re.sub(r'<[^>]+>', '', t)
    t = re.sub(r'[^\S\n]+', ' ', t)
    t = re.sub(r'([。！？.!?])\s+', r'\1\n', t)
    t = t.strip()
    return t
