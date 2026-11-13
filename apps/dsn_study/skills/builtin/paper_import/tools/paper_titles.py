# apps/dsn_study/skills/builtin/paper_import/tools/paper_titles.py
"""分隔标题页生成（合卷时每科前插一页）。

纯 PIL 实现，不引新依赖；找不到中文字体时退回英文标签，避免出方框。
"""

from __future__ import annotations

import logging
import os
import tempfile

logger = logging.getLogger("PaperTitles")

#: 候选中文字体（按优先级）
FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
    "/usr/share/fonts/truetype/arphic/ukai.ttc",
]
FONT_BOLD_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
    "/usr/share/fonts/truetype/arphic/uming.ttc",
]

#: A4 @150dpi
PAGE_W, PAGE_H = 1240, 1754


def _pick(candidates: list) -> str:
    for path in candidates:
        if os.path.isfile(path):
            return path
    return ""


def make_title_page(subject: str, lines: list = None, tmp_dir: str = "") -> str:
    """生成一张 A4 比例的分隔标题页，返回 JPEG 路径。"""
    from PIL import Image, ImageDraw, ImageFont

    lines = list(lines or [])
    font_path = _pick(FONT_CANDIDATES)
    bold_path = _pick(FONT_BOLD_CANDIDATES) or font_path
    if not font_path:
        logger.warning("找不到中文字体，标题页退回英文")
        subject = subject
        lines = lines or []

    img = Image.new("RGB", (PAGE_W, PAGE_H), "white")
    draw = ImageDraw.Draw(img)
    try:
        f_big = ImageFont.truetype(bold_path, 96) if bold_path else ImageFont.load_default()
        f_mid = ImageFont.truetype(font_path, 44) if font_path else ImageFont.load_default()
        f_small = ImageFont.truetype(font_path, 34) if font_path else ImageFont.load_default()
    except Exception as exc:
        logger.warning("字体加载失败: %s", exc)
        f_big = f_mid = f_small = ImageFont.load_default()

    def center(text: str, font, y: int, fill="black"):
        bbox = draw.textbbox((0, 0), text, font=font)
        draw.text(((PAGE_W - (bbox[2] - bbox[0])) / 2, y), text, font=font, fill=fill)

    header = "2026-2027 学年 · 北京市朝阳区 · 高三上学期期中"
    center(header, f_small, int(PAGE_H * 0.12))
    center(subject, f_big, int(PAGE_H * 0.30))
    y = int(PAGE_H * 0.30) + 190
    for line in lines:
        center(line, f_mid, y)
        y += 70

    tmp_dir = tmp_dir or tempfile.gettempdir()
    os.makedirs(tmp_dir, exist_ok=True)
    path = os.path.join(tmp_dir, "_title_%s.jpg" % subject)
    img.save(path, "JPEG", quality=88)
    return path
