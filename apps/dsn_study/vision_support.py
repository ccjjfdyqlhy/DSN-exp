# apps/dsn_study/vision_support.py
# 主模型「能不能直接看图」的判定 —— 判别式探测 + 缓存 + 运行时降级。
#
# 为什么需要它：
#   AI 主动视觉（look_around）拿到的画面，有两条路可以送给模型：
#     A) 直发主模型 —— 把图作为 content parts 一起发给主模型；
#     B) VLM 转述 —— 另起一次调用，让专用视觉模型把图描述成文字，再喂主模型。
#   B 是安全的老路（主模型是纯文本模型时只有它能用），A 更省一次调用、
#   且模型看到的是原图而不是别人的转述。
#   选哪条取决于**主模型到底支不支持图片输入**。
#
# 为什么不能用「1x1 测试图 + 请回复 ok」当探测：
#   纯文本模型也会答 "ok" —— 探测图必须有**只有看图才能答对**的答案。
#   这里用「图里渲染一个 4 位数字，问这个数字是多少」：文本模型靠猜的
#   命中概率约万分之一，而真正能看图的模型会一字不差地答出来。
#
# 为什么不能靠「发失败就降级」兜底：
#   上游对「不支持图片」的两种反应差别巨大 —— 严格的网关回 400（可捕获），
#   宽松的网关/本地 llama-server 没挂 mmproj 时**回 200 + 一段幻觉描述**
#   （失败重试根本不会触发，幻觉还会被当成真的写进题库）。
#   所以判定必须**主动**做，不能等失败。
#
# 探测图是纯 Python 生成的 PNG（zlib + 手写点阵字体），不依赖 Pillow/CV。

from __future__ import annotations

import base64
import logging
import struct
import threading
import zlib
from typing import Any, Optional

logger = logging.getLogger("study.vision_support")

#: 探测图里的数字。答对这 4 位才算「模型真的看到了图」。
#: 固定值（不每次随机）是为了让探测结果可复现、可对照日志。
PROBE_DIGITS = "7391"

#: 探测问题的措辞。要点：只问数字、不给选项、不给任何提示。
PROBE_PROMPT = ("这张图片里写着一个 4 位数字。只回答这 4 位数字本身，"
                "不要解释、不要加任何别的字。")

#: 3x5 点阵数字字体（每个数字 5 行 × 3 列）。放大后足够清晰可辨。
_DIGIT_FONT: dict[str, list[str]] = {
    "0": ["111", "101", "101", "101", "111"],
    "1": ["010", "110", "010", "010", "111"],
    "2": ["111", "001", "111", "100", "111"],
    "3": ["111", "001", "111", "001", "111"],
    "4": ["101", "101", "111", "001", "001"],
    "5": ["111", "100", "111", "001", "111"],
    "6": ["111", "100", "111", "101", "111"],
    "7": ["111", "001", "010", "010", "010"],
    "8": ["111", "101", "111", "101", "111"],
    "9": ["111", "101", "111", "001", "111"],
}

_CACHE: dict[tuple[str, str], bool] = {}
_CACHE_LOCK = threading.Lock()

#: 正在进行的探测：key -> 完成信号。
#: 用 Event 而不是 set，是为了让**后到的调用方能等这次探测出结论**
#: （见 main_model_supports_images）。
_INFLIGHT: dict[tuple[str, str], threading.Event] = {}

#: 单次探测的等待上限（秒）。
#: 探测是同步的 —— 超时就当「不支持」，宁可走 VLM 转述也不能卡住对话。
PROBE_TIMEOUT = 25.0


# ── 探测图生成（纯 Python PNG） ──────────────────────────────────────

def _render_digits(digits: str, scale: int = 12, gap: int = 1,
                   pad: int = 8) -> list[list[int]]:
    """把数字串渲染成灰度像素矩阵（0=黑，255=白）。"""
    glyph_w, glyph_h = 3, 5
    cell_w = (glyph_w + gap) * scale
    width = pad * 2 + cell_w * len(digits) - gap * scale
    height = pad * 2 + glyph_h * scale
    # 全白底
    pixels = [[255] * width for _ in range(height)]
    for idx, ch in enumerate(digits):
        rows = _DIGIT_FONT.get(ch)
        if not rows:
            continue
        ox = pad + idx * cell_w
        oy = pad
        for gy, row in enumerate(rows):
            for gx, bit in enumerate(row):
                if bit != "1":
                    continue
                for sy in range(scale):
                    py = oy + gy * scale + sy
                    if py >= height:
                        continue
                    line = pixels[py]
                    for sx in range(scale):
                        px = ox + gx * scale + sx
                        if 0 <= px < width:
                            line[px] = 0
    return pixels


def _encode_png_gray(pixels: list[list[int]]) -> bytes:
    """把灰度矩阵编码成 8 位灰度 PNG（无调色板、无滤波）。"""

    def _chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    height = len(pixels)
    width = len(pixels[0]) if height else 0
    raw = b"".join(b"\x00" + bytes(row) for row in pixels)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(raw, 9))
            + _chunk(b"IEND", b""))


def probe_image_data_url() -> str:
    """探测图的 data URL（含数字的 PNG）。"""
    png = _encode_png_gray(_render_digits(PROBE_DIGITS))
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


# ── 能力判定 ─────────────────────────────────────────────────────────

def _key(model_name: str, base_url: str) -> tuple[str, str]:
    return (str(base_url or ""), str(model_name or ""))


def _config_override() -> Optional[bool]:
    """读 MAIN_MODEL_SUPPORTS_IMAGE 的显式覆盖。

    返回 None 表示「没配置，按探测结果走」。
    """
    try:
        from apps.dsn_study.config import Config
        raw = str(getattr(Config, "MAIN_MODEL_SUPPORTS_IMAGE", "auto") or "auto")
    except Exception:   # noqa: BLE001 - 配置不可用时按 auto 处理
        return None
    low = raw.strip().lower()
    if low in ("true", "yes", "on", "1"):
        return True
    if low in ("false", "no", "off", "0"):
        return False
    return None


def _probe_enabled() -> bool:
    try:
        from apps.dsn_study.config import Config
        return bool(getattr(Config, "MAIN_MODEL_IMAGE_PROBE", True))
    except Exception:   # noqa: BLE001
        return True


def direct_to_main_enabled() -> bool:
    """是否允许「把图直接发给主模型」。

    VISION_DIRECT_TO_MAIN：
      * ``on``  —— 一律直发（不探测）；
      * ``off`` —— 一律走 VLM 转述（老路）；
      * ``auto``—— 主模型经判定支持图片就直发，否则走 VLM 转述。
    """
    try:
        from apps.dsn_study.config import Config
        raw = str(getattr(Config, "VISION_DIRECT_TO_MAIN", "auto") or "auto")
    except Exception:   # noqa: BLE001
        return False
    low = raw.strip().lower()
    if low in ("on", "true", "yes", "1"):
        return True
    if low in ("off", "false", "no", "0"):
        return False
    return True   # auto：具体走哪条由能力判定决定


def _run_probe(chat_client: Any, model_name: str) -> bool:
    """真发一次探测请求：图里是 4 位数字，答对才算支持图片。"""
    from infra.models.base import ChatMessage

    data_url = probe_image_data_url()
    # 图片在前、文字在后 —— 与 apps/dsn_study 的 VisionModel.ask 保持一致
    # （infra/orchestrator/vision.py:101-107）。
    message = ChatMessage(role="user", content=[
        {"type": "image_url", "image_url": {"url": data_url}},
        {"type": "text", "text": PROBE_PROMPT},
    ])
    resp = chat_client.invoke([message])
    answer = str(getattr(resp, "content", "") or "")
    compact = answer.replace(" ", "").replace("\n", "")
    hit = PROBE_DIGITS in compact
    logger.info("主模型图片能力探测: model=%s 回答=%r → %s",
                model_name, answer[:60], "支持图片" if hit else "不支持图片")
    return hit


def main_model_supports_images(chat_client: Any, model_name: str = "",
                                base_url: str = "") -> bool:
    """主模型是否支持图片输入。

    判定顺序：显式配置覆盖 → 缓存 → 探测。
    探测失败（异常/超时）一律按**不支持**处理 —— 宁可走 VLM 转述，
    也不能把图发给一个可能只是假装能看的模型。
    """
    override = _config_override()
    if override is not None:
        return override

    key = _key(model_name, base_url)
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached is not None:
            return cached
        event = _INFLIGHT.get(key)
        owner = event is None
        if owner:
            event = threading.Event()
            _INFLIGHT[key] = event

    if not owner:
        # 已有探测在跑（多半是开机预探测）—— **等它出结论**。
        #
        # 为什么不直接按「不支持」返回：那样同一次启动里，开机后第一次
        # 主动视觉会走 VLM 转述老路，而后一次走直发 —— 两次判定不一致，
        # 且表现为「偶发」，最难查。等待是有界的（探测本身也有界）。
        logger.debug("等待进行中的主模型图片能力探测 (model=%s)", model_name)
        event.wait(timeout=PROBE_TIMEOUT)
        with _CACHE_LOCK:
            cached = _CACHE.get(key)
        if cached is not None:
            return cached
        logger.warning("等待主模型图片能力探测超时（%.0fs），按不支持处理 (model=%s)",
                       PROBE_TIMEOUT, model_name)
        return False

    if not _probe_enabled():
        logger.info("主模型图片能力探测已关闭，按不支持处理 (model=%s)", model_name)
        with _CACHE_LOCK:
            _CACHE[key] = False
            _INFLIGHT.pop(key, None)
        event.set()
        return False

    if chat_client is None:
        with _CACHE_LOCK:
            _INFLIGHT.pop(key, None)
        event.set()
        return False

    outcome: dict[str, Any] = {}

    def _work() -> None:
        try:
            outcome["v"] = bool(_run_probe(chat_client, model_name))
        except Exception as exc:   # noqa: BLE001 - 探测失败不能拖垮调用方
            logger.warning("主模型图片能力探测失败，按不支持处理 (model=%s): %s",
                           model_name, exc)
            outcome["v"] = False
        finally:
            with _CACHE_LOCK:
                _CACHE[key] = outcome.get("v", False)
                _INFLIGHT.pop(key, None)
            event.set()

    worker = threading.Thread(target=_work, daemon=True,
                              name="vision-image-probe")
    worker.start()
    worker.join(timeout=PROBE_TIMEOUT)
    if "v" not in outcome:
        # 超时：线程还在跑，它完成后会自己写缓存并 set(event)。
        # 本次按「不支持」处理（保守），下一次调用就能命中缓存。
        logger.warning("主模型图片能力探测超时（%.0fs），本次按不支持处理 (model=%s)",
                       PROBE_TIMEOUT, model_name)
        return False
    return bool(outcome["v"])


def mark_image_unsupported(model_name: str = "", base_url: str = "") -> None:
    """运行时降级：把该模型标记为「不支持图片」，后续一律走 VLM 转述。

    用于「探测说支持、实际调用却报错」的情况 —— 比如换了网关或模型名。
    """
    key = _key(model_name, base_url)
    with _CACHE_LOCK:
        _CACHE[key] = False
    logger.warning("主模型图片支持已降级为「不支持」，后续走 VLM 转述 (model=%s)",
                   model_name)


def reset_image_support_cache() -> None:
    """清空判定缓存（测试用 / 换模型后手动刷新）。"""
    with _CACHE_LOCK:
        _CACHE.clear()
        for ev in _INFLIGHT.values():
            ev.set()
        _INFLIGHT.clear()
