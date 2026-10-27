#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""export_pdf.py —— 把项目里的 .py / .md 文件导出成 PDF，供打印精读批注。

特点
  * 只导出项目自己的文件：默认走 `git ls-files`（含未跟踪但未被 .gitignore 忽略的），
    因此 temp/、__pycache__、node_modules、虚拟环境等一律不会进来。
  * .py 按源码原样排版：行号、Tab 展开、超长行折行续排（↪ 标记）、每页页眉页脚。
  * .md 做轻量渲染：标题分级、代码块灰底、引用/列表缩进、表格等宽对齐；
    正文按段落重排便于纸上阅读，去掉 ** __ ` 等行内标记但不丢内容。
  * --merge 生成合并册：封面 + 目录（带页码）+ 每份文件另起一页，页码全书连续。
  * 中文用 TrueType 字体嵌入（Noto CJK 是 CFF 轮廓，reportlab 嵌不进去，
    所以优先 Droid Sans Fallback / AR PL UMing），缺字自动降级，不会出黑块。

用法
  python3 tools/export_pdf.py                     # 逐文件导出到 pdf_export/single/
  python3 tools/export_pdf.py --merge             # 额外生成合并册
  python3 tools/export_pdf.py --merge --merged-only
  python3 tools/export_pdf.py --list              # 只看会导出哪些文件
  python3 tools/export_pdf.py --ext .py --include 'apps/*' --exclude '*test*'
  python3 tools/export_pdf.py --paper letter --margin 45 --font-size 9 --no-toc
"""

from __future__ import annotations

import argparse
import datetime
import fnmatch
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

try:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas as rl_canvas
except ImportError:  # pragma: no cover
    sys.exit("缺少 reportlab，请先安装：pip install reportlab")

__version__ = "1.1.0"

# ────────────────────────────── 纸张与配色 ──────────────────────────────

PAPERS = {
    "a4": (595.276, 841.890),
    "a3": (841.890, 1190.551),
    "letter": (612.0, 792.0),
    "b5": (498.898, 708.661),
}

BLACK = (0.10, 0.10, 0.10)
DARK2 = (0.22, 0.22, 0.22)
GRAY = (0.45, 0.45, 0.45)
LIGHT = (0.60, 0.60, 0.60)
FAINT = (0.80, 0.80, 0.80)
RULE = (0.78, 0.78, 0.78)
CODE_BG = (0.952, 0.952, 0.952)
QUOTE = (0.32, 0.36, 0.40)

# 字体候选：按顺序找，第一个能用的成为该角色的字体。
FONT_CANDIDATES = {
    "mono": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationMono-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoMono-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeMono.ttf",
    ],
    "mono_bold": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationMono-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
    ],
    "sans": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ],
    "sans_bold": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ],
    # 中文字体必须是 TrueType(glyf) 轮廓，CFF/OTF 的 Noto CJK 不行。
    "cjk": [
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
        "/usr/share/fonts/truetype/arphic/uming.ttc",
        "/usr/share/fonts/truetype/arphic/ukai.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",   # macOS
        "C:/Windows/Fonts/msyh.ttc",                     # Windows
        "C:/Windows/Fonts/simhei.ttf",
    ],
}

MD_SUFFIXES = {".md", ".markdown", ".mdx"}

BUILTIN_FALLBACK = {"mono": "Courier", "mono_bold": "Courier-Bold",
                    "sans": "Helvetica", "sans_bold": "Helvetica-Bold", "cjk": None}


# ────────────────────────────── 字体管理 ──────────────────────────────

class Fonts:
    """注册 TrueType 字体，并处理「主字体缺字 → 中文/符号字体补齐」的混排。"""

    def __init__(self, verbose: bool = True):
        self.names: dict[str, str] = {}
        self.coverage: dict[str, set[int]] = {}
        self._char_font: dict[tuple[str, int], str] = {}
        self._width_cache: dict[tuple[str, int], float] = {}
        self.notes: list[str] = []
        for key, paths in FONT_CANDIDATES.items():
            name = self._register(key, paths, verbose)
            if name:
                self.names[key] = name
            else:
                builtin = BUILTIN_FALLBACK.get(key)
                if builtin:
                    self.names[key] = builtin
                    self.notes.append(f"{key}: 未找到系统字体，退回内置 {builtin}（中文可能无法显示）")
        self.mono = self.names.get("mono", "Courier")
        self.mono_bold = self.names.get("mono_bold", self.mono)
        self.sans = self.names.get("sans", "Helvetica")
        self.sans_bold = self.names.get("sans_bold", self.sans)
        self.cjk = self.names.get("cjk")
        self.mono_w = self.width("M", self.mono, 1000.0) / 1000.0  # 等宽字体单字符宽（em）

    def _register(self, key: str, paths: list[str], verbose: bool) -> str | None:
        for p in paths:
            if not os.path.exists(p):
                continue
            font_name = "XPDF-" + key
            try:
                kwargs = {"subfontIndex": 0} if p.lower().endswith(".ttc") else {}
                tf = TTFont(font_name, p, **kwargs)
                pdfmetrics.registerFont(tf)
                coverage = set(tf.face.charToGlyph.keys())
                if not coverage:
                    continue
                self.coverage[font_name] = coverage
                if verbose:
                    print(f"  字体 {key:<10} {os.path.basename(p)}  覆盖 {len(coverage)} 字形")
                return font_name
            except Exception:
                continue
        return None

    def _covers(self, font: str, cp: int) -> bool:
        cov = self.coverage.get(font)
        if cov is None:  # 内置 Type1 字体：只当 ASCII 可用
            return cp < 0x2000
        return cp in cov

    def font_for(self, ch: str, primary: str) -> str:
        key = (primary, ord(ch))
        cached = self._char_font.get(key)
        if cached is not None:
            return cached
        cp = ord(ch)
        if self._covers(primary, cp):
            chosen = primary
        else:
            chosen = primary
            for cand in (self.cjk, self.sans, self.mono, self.sans_bold):
                if cand and cand != primary and self._covers(cand, cp):
                    chosen = cand
                    break
        self._char_font[key] = chosen
        return chosen

    def runs(self, text: str, primary: str) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for ch in text:
            f = self.font_for(ch, primary)
            if out and out[-1][0] == f:
                out[-1] = (f, out[-1][1] + ch)
            else:
                out.append((f, ch))
        return out

    def width(self, text: str, font: str, size: float) -> float:
        total = 0.0
        for ch in text:
            key = (font, ord(ch))
            w = self._width_cache.get(key)
            if w is None:
                try:
                    w = pdfmetrics.stringWidth(ch, font, 1000.0)
                except Exception:
                    w = 600.0
                self._width_cache[key] = w
            total += w
        return total * size / 1000.0

    def runs_width(self, runs: list[tuple[str, str]], size: float) -> float:
        return sum(self.width(t, f, size) for f, t in runs)


# ────────────────────────────── 版面 ──────────────────────────────

@dataclass
class Geom:
    width: float
    height: float
    left: float
    right: float
    top: float
    bottom: float

    @property
    def usable_w(self) -> float:
        return self.width - self.left - self.right

    @property
    def usable_h(self) -> float:
        return self.height - self.top - self.bottom

    @property
    def x0(self) -> float:
        return self.left

    @property
    def y_top(self) -> float:
        return self.height - self.top


@dataclass
class Page:
    items: list[tuple] = field(default_factory=list)
    kind: str = "content"      # cover | toc | content
    label: str = ""            # 页脚左侧文字

    def text(self, x, y, text, font, size, color=BLACK):
        if text:
            self.items.append(("t", x, y, text, font, size, color))

    def runs(self, x, y, runs, size, color=BLACK):
        if runs:
            self.items.append(("runs", x, y, runs, size, color))

    def rect(self, x, y, w, h, fill=None, stroke=None, lw=0.5):
        self.items.append(("rect", x, y, w, h, fill, stroke, lw))

    def line(self, x1, y1, x2, y2, color=RULE, lw=0.5):
        self.items.append(("line", x1, y1, x2, y2, color, lw))


@dataclass
class Options:
    code_size: float = 8.4
    code_leading: float = 1.34
    body_size: float = 9.6
    body_leading: float = 1.55
    line_numbers: bool = True
    tab: int = 4


def leading_for(size: float, factor: float) -> float:
    return round(size * factor, 3)


# ────────────────────────────── 文本工具 ──────────────────────────────

CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
FW = ("W", "F")


def wide(ch: str) -> bool:
    return bool(ch) and unicodedata.east_asian_width(ch) in FW


def sanitize(line: str, tab: int) -> str:
    """控制字符清理 + Tab 按列展开（与终端显示一致）。"""
    line = line.rstrip("\r\n")
    if "\t" in line:
        out, col = [], 0
        for ch in line:
            if ch == "\t":
                step = tab - (col % tab)
                out.append(" " * step)
                col += step
            else:
                out.append(ch)
                col += 2 if wide(ch) else 1
        line = "".join(out)
    if CTRL.search(line):
        line = CTRL.sub("·", line)
    return line


def display_cols(text: str) -> int:
    return sum(2 if wide(ch) else 1 for ch in text)


BREAK_CHARS = " \t,;:、，。；：)]}"


def wrap_cols(text: str, budget: int, rest_penalty: int = 0) -> list[str]:
    """按显示列宽切行（等宽字体栅格算法，中文占 2 列）。

    rest_penalty 表示续行要留出的列数（给 ↪ 这类续行标记让位），
    避免续行加上标记后超出可用宽度。
    """
    budget = max(6, budget)
    if display_cols(text) <= budget:
        return [text]
    chunks: list[str] = []
    cur: list[str] = []
    col = 0
    last_break = -1
    limit = budget
    for ch in text:
        w = 2 if wide(ch) else 1
        if cur and col + w > limit:
            if 0 < last_break < len(cur):
                chunks.append("".join(cur[:last_break]).rstrip())
                rest = cur[last_break:]
                while rest and rest[0] == " ":
                    rest.pop(0)
                cur = rest
            else:
                chunks.append("".join(cur).rstrip())
                cur = []
            col = display_cols("".join(cur))
            last_break = -1
            limit = max(6, budget - rest_penalty)
        cur.append(ch)
        col += w
        if ch in BREAK_CHARS:
            last_break = len(cur)
    if cur:
        chunks.append("".join(cur).rstrip())
    return [c for c in chunks] or [""]


def fit_text(text: str, font: str, size: float, max_w: float, F: "Fonts",
             min_size: float = 7.0, step: float = 0.4) -> tuple[str, float]:
    """缩字号，仍放不下就中间省略，保证标题/路径不会越界。"""
    s = size
    while s > min_size and F.width(text, font, s) > max_w:
        s = round(s - step, 2)
    if F.width(text, font, s) <= max_w:
        return text, s

    def build(keep: int) -> str:
        a = text[: (keep + 1) // 2]
        b = text[-(keep // 2):] if keep // 2 else ""
        return a + "…" + b

    best, lo, hi = build(1), 1, max(1, len(text) - 1)
    while lo <= hi:
        mid = (lo + hi) // 2
        if F.width(build(mid), font, s) <= max_w:
            best, lo = build(mid), mid + 1
        else:
            hi = mid - 1
    return best, s


def wrap_exact(text: str, budget_pt: float, font: str, size: float, F: Fonts) -> list[str]:
    """比例字体折行：中文按字断行、西文优先按词断行，必要时硬切。"""
    if not text:
        return [""]
    tokens: list[str] = []
    buf = ""
    for ch in text:
        if ch == " ":
            if buf:
                tokens.append(buf)
                buf = ""
            tokens.append(" ")
        elif wide(ch):
            if buf:
                tokens.append(buf)
                buf = ""
            tokens.append(ch)
        else:
            buf += ch
    if buf:
        tokens.append(buf)

    lines: list[str] = []
    cur = ""
    cur_w = 0.0
    for tok in tokens:
        if not cur and tok == " ":
            continue
        w = F.runs_width(F.runs(tok, font), size)
        if cur and cur_w + w > budget_pt:
            if tok == " ":
                lines.append(cur)
                cur, cur_w = "", 0.0
                continue
            lines.append(cur)
            cur, cur_w = tok, w
        else:
            cur += tok
            cur_w += w
        while cur_w > budget_pt and len(cur) > 1:
            cut = max(1, int(len(cur) * budget_pt / max(cur_w, 1e-6)))
            while cut > 1 and F.runs_width(F.runs(cur[:cut], font), size) > budget_pt:
                cut -= 1
            lines.append(cur[:cut])
            cur = cur[cut:]
            cur_w = F.runs_width(F.runs(cur, font), size)
    if cur.strip():
        lines.append(cur)
    return [ln.rstrip() for ln in lines] or [""]


def baseline_in(box_bottom: float, size: float, line_h: float) -> float:
    """在一个行盒内算基线位置，使字身大致垂直居中。"""
    return box_bottom + (line_h - size) * 0.5 + size * 0.235


# ────────────────────────── .py 源码排版 ──────────────────────────

def layout_code(rel: str, text: str, G: Geom, F: Fonts, opt: Options) -> list[Page]:
    size = opt.code_size
    lead = leading_for(size, opt.code_leading)
    mono_w = F.mono_w * size

    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    nums = len(lines)
    gutter = (len(str(nums)) * mono_w + 7.0) if opt.line_numbers else 0.0
    code_x = G.x0 + gutter
    budget = max(20, int((G.usable_w - gutter) / mono_w))

    title_h = lead * 1.15 + 4.0 + lead * 1.0 + 7.0   # 首页标题块
    cont_h = lead * 0.9 + 3.0
    rows_first = max(4, int((G.usable_h - title_h) // lead))
    rows_rest = max(8, int((G.usable_h - cont_h) // lead))

    records: list[tuple[int | None, str]] = []
    for i, raw in enumerate(lines, start=1):
        chunks = wrap_cols(sanitize(raw, opt.tab), budget, rest_penalty=2)
        records.append((i, chunks[0]))
        for c in chunks[1:]:
            records.append((None, c))

    pages: list[Page] = []
    idx = 0
    first = True
    while True:
        rows = rows_first if first else rows_rest
        page = Page(kind="content", label=rel)
        y = G.y_top
        if first:
            head_font = F.mono_bold or F.mono
            head_text, head_size = fit_text(rel, head_font, size + 1.4, G.usable_w, F)
            page.text(G.x0, y - head_size - 2.0, head_text, head_font, head_size, BLACK)
            y -= lead * 1.15 + 4.0
            meta = f"Python 源码 · {nums} 行"
            page.text(G.x0, y - size * 0.9, meta, F.sans, size - 0.8, GRAY)
            y -= lead * 1.0 + 7.0
            page.line(G.x0, y + 2.0, G.x0 + G.usable_w, y + 2.0, RULE, 0.6)
            y -= 3.0
        else:
            page.text(G.x0, y - size * 0.9, "（续）" + rel, F.sans, size - 1.2, LIGHT)
            y -= cont_h
        drawn = 0
        for _ in range(rows):
            if idx >= len(records):
                break
            lineno, content = records[idx]
            idx += 1
            drawn += 1
            base = y - size - (lead - size) * 0.30
            if opt.line_numbers and lineno is not None:
                num = str(lineno)
                page.text(G.x0 + gutter - 5.0 - F.width(num, F.mono, size - 1.3),
                          base, num, F.mono, size - 1.3, FAINT)
            if lineno is None:                      # 折行续行：浅灰 ↪ 标记
                page.text(code_x, base, "↪", F.mono, size, (0.78, 0.78, 0.78))
                page.runs(code_x + mono_w * 2, base, F.runs(content, F.mono), size, BLACK)
            else:
                page.runs(code_x, base, F.runs(content, F.mono), size, BLACK)
            y -= lead
        pages.append(page)
        first = False
        if idx >= len(records) or drawn == 0:
            break
    if not pages:
        pages.append(Page(kind="content", label=rel))
    return pages


# ────────────────────────── .md 轻量渲染 ──────────────────────────

MD_HEAD = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
MD_HR = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$")
MD_FENCE = re.compile(r"^\s{0,3}(```+|~~~+)(.*)$")
MD_LIST = re.compile(r"^(\s*)([-*+]|\d{1,3}[.)])\s+(.*)$")
MD_QUOTE = re.compile(r"^\s{0,3}>\s?(.*)$")
MD_TABLE = re.compile(r"^\s*\|.*\|\s*$")
MD_TABLE_SEP = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
MD_SETEXT = re.compile(r"^\s{0,3}(=+|-+)\s*$")
HEAD_SCALE = {1: 1.72, 2: 1.42, 3: 1.20, 4: 1.08, 5: 1.02, 6: 0.98}


def inline_plain(s: str) -> str:
    """去掉 Markdown 行内标记，保留文字本身（纸上阅读 + 批注用）。

    行内代码先用占位符保护起来，避免 __init__、<task> 这类内容被误伤；
    HTML 标签也一律保留（提示词文档里的 <task> 是有意义的内容）。
    """
    spans: list[str] = []

    def protect(m: re.Match) -> str:
        spans.append(m.group(1))
        return f"\x00{len(spans) - 1}\x00"

    s = re.sub(r"`([^`]*)`", protect, s)                       # 行内代码
    s = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"[图: \1]", s)     # 图片
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", s)      # 链接
    s = re.sub(r"\*\*(?!\s)(.+?)(?<!\s)\*\*", r"\1", s)         # **粗体**
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", s)  # *斜体*
    s = re.sub(r"~~(?=\S)(.+?)(?<=\S)~~", r"\1", s)             # ~~删除线~~
    s = re.sub(r"(?<![\w_])__(?=\S)(.+?)(?<=\S)__(?![\w_])", r"\1", s)  # __粗体__
    s = re.sub(r"\x00(\d+)\x00", lambda m: spans[int(m.group(1))], s)
    return s.rstrip()


def join_para(lines: list[str]) -> str:
    """把硬换行的源文本拼回段落：中文直接相连，西文补空格。"""
    out = ""
    for ln in lines:
        if not ln.strip():
            continue
        if not out:
            out = ln
            continue
        if wide(out[-1]) or wide(ln[:1]):
            out += ln
        elif out.endswith(("-", "/", "（", "(")) and not out.endswith(" -"):
            out += ln
        else:
            out += " " + ln
    return out


def parse_md_blocks(text: str, tab: int) -> list[dict]:
    """把 Markdown 拆成块：heading / para / code / list / quote / table / hr / gap。"""
    src = text.split("\n")
    if src and src[-1] == "":
        src.pop()
    blocks: list[dict] = []
    i, n = 0, len(src)
    while i < n:
        raw = src[i].rstrip()

        m = MD_FENCE.match(raw)
        if m:
            lang = m.group(2).strip()
            i += 1
            code: list[str] = []
            while i < n and not MD_FENCE.match(src[i]):
                code.append(sanitize(src[i], tab))
                i += 1
            i += 1
            blocks.append({"type": "code", "lang": lang, "lines": code})
            continue

        m = MD_HEAD.match(raw)
        if m:
            blocks.append({"type": "heading", "level": len(m.group(1)),
                           "text": m.group(2).strip()})
            i += 1
            continue

        if MD_HR.match(raw):
            # 紧跟在段落文字后面的 --- 是 setext 二级标题，不是分隔线
            prev_blank = i > 0 and not src[i - 1].strip()
            if blocks and blocks[-1]["type"] == "para" and not prev_blank:
                blocks[-1] = {"type": "heading", "level": 2, "text": blocks[-1]["text"]}
            else:
                blocks.append({"type": "hr"})
            i += 1
            continue

        if MD_TABLE.match(raw) and raw.count("|") >= 2:
            rows = []
            while i < n and MD_TABLE.match(src[i].rstrip()) and src[i].count("|") >= 2:
                row = src[i].rstrip()
                if not MD_TABLE_SEP.match(row):
                    rows.append(row.strip())
                i += 1
            blocks.append({"type": "table", "lines": rows})
            continue

        if MD_QUOTE.match(raw):
            parts = []
            while i < n:
                mm = MD_QUOTE.match(src[i].rstrip())
                if not mm:
                    break
                parts.append(mm.group(1))
                i += 1
            blocks.append({"type": "quote",
                           "text": join_para([inline_plain(p) for p in parts])})
            continue

        m = MD_LIST.match(raw)
        if m:
            indent = len(m.group(1))
            parts = [m.group(3)]
            i += 1
            while i < n:
                nxt = src[i]
                if (not nxt.strip() or MD_LIST.match(nxt) or MD_HEAD.match(nxt.rstrip())
                        or MD_FENCE.match(nxt) or MD_QUOTE.match(nxt)
                        or MD_TABLE.match(nxt) or MD_HR.match(nxt.strip())):
                    break
                if len(nxt) - len(nxt.lstrip()) > indent:
                    parts.append(nxt.strip())
                    i += 1
                else:
                    break
            blocks.append({"type": "list", "indent": indent, "marker": m.group(2),
                           "text": join_para([inline_plain(p) for p in parts])})
            continue

        m = MD_SETEXT.match(raw)
        if m and blocks and blocks[-1]["type"] == "para" and i > 0 and src[i - 1].strip():
            blocks[-1] = {"type": "heading",
                          "level": 1 if m.group(1).startswith("=") else 2,
                          "text": blocks[-1]["text"]}
            i += 1
            continue

        if not raw.strip():
            blocks.append({"type": "gap"})
            i += 1
            continue

        parts = [raw.strip()]
        i += 1
        while i < n:
            nxt = src[i]
            if (not nxt.strip() or MD_HEAD.match(nxt.rstrip()) or MD_FENCE.match(nxt)
                    or MD_LIST.match(nxt) or MD_QUOTE.match(nxt) or MD_HR.match(nxt.strip())
                    or MD_SETEXT.match(nxt)
                    or (MD_TABLE.match(nxt) and nxt.count("|") >= 2)):
                break
            parts.append(nxt.strip())
            i += 1
        blocks.append({"type": "para", "text": join_para([inline_plain(p) for p in parts])})

    return clean_blocks(blocks)


def clean_blocks(blocks: list[dict]) -> list[dict]:
    """去掉与标题重复表达分隔的分隔线，合并连续空行，剔除首尾空行。"""
    out: list[dict] = []
    for idx, b in enumerate(blocks):
        if b["type"] == "hr":
            nxt = next((x["type"] for x in blocks[idx + 1:]
                        if x["type"] != "gap"), None)
            prv = next((x["type"] for x in reversed(blocks[:idx])
                        if x["type"] != "gap"), None)
            if nxt == "heading" or prv == "heading" or nxt is None:
                continue          # 标题本身已足够分隔
        if b["type"] == "gap" and (not out or out[-1]["type"] == "gap"):
            continue
        out.append(b)
    while out and out[-1]["type"] == "gap":
        out.pop()
    return out


def layout_md(rel: str, text: str, G: Geom, F: Fonts, opt: Options) -> list[Page]:
    size = opt.body_size
    lead = leading_for(size, opt.body_leading)
    code_size = max(6.5, size - 1.3)
    code_lead = leading_for(code_size, 1.30)
    mono_w = F.mono_w * code_size
    ind = 13.0          # 引用/列表缩进
    cont_h = lead * 0.95 + 4.0

    pages: list[Page] = []
    page = Page(kind="content", label=rel)
    y = G.y_top

    def new_page():
        nonlocal page, y
        pages.append(page)
        page = Page(kind="content", label=rel)
        y = G.y_top
        page.text(G.x0, y - size * 0.95, "（续）" + rel, F.sans, size - 1.9, LIGHT)
        y -= cont_h

    def take(h: float) -> None:
        nonlocal y
        if y - h < G.bottom:
            new_page()
        y -= h

    def put_lines(lines: list[str], font: str, sz: float, lh: float,
                  x: float = G.x0, color=BLACK) -> None:
        for ln in lines:
            take(lh)
            page.runs(x, baseline_in(y, sz, lh), F.runs(ln, font), sz, color)

    # 文件抬头
    title_text, title_size = fit_text(rel, F.sans_bold, size + 4.5, G.usable_w, F,
                                      min_size=10.0)
    page.text(G.x0, y - title_size, title_text, F.sans_bold, title_size, BLACK)
    y -= title_size + 7.0
    total_lines = text.count("\n") + 1
    page.text(G.x0, y - size * 0.85, f"Markdown 文档 · 约 {total_lines} 行",
              F.sans, size - 1.9, GRAY)
    y -= size * 1.25 + 5.0
    page.line(G.x0, y, G.x0 + G.usable_w, y, RULE, 0.9)
    y -= 9.0

    prev = None
    gap = False
    for b in parse_md_blocks(text, opt.tab):
        t = b["type"]

        if t == "gap":
            gap = True
            continue

        if t == "heading":
            hs = size * HEAD_SCALE.get(b["level"], 1.0)
            hl = leading_for(hs, 1.34)
            before = 0.0
            if prev is not None:
                before = hl * (0.78 if b["level"] <= 2 else 0.52)
                if gap:
                    before += hl * 0.18
            lines = wrap_exact(b["text"], G.usable_w, F.sans_bold, hs, F)
            under = 4.5 if b["level"] <= 2 else 0.0
            need = before + hl * len(lines) + under + hl * 0.28
            if y - need < G.bottom and page.items:
                new_page()
                before = 0.0
            take(before)
            put_lines(lines, F.sans_bold, hs, hl, color=BLACK if b["level"] <= 3 else DARK2)
            if under:
                take(under)
                w = G.usable_w if b["level"] == 1 else G.usable_w * 0.5
                page.line(G.x0, y + 2.5, G.x0 + w, y + 2.5,
                          RULE if b["level"] == 1 else (0.88, 0.88, 0.88),
                          0.9 if b["level"] == 1 else 0.5)
            take(hl * 0.28)

        elif t == "para":
            before = lead * (0.5 if gap else 0.0)
            if prev is not None and not gap and prev in ("para", "list", "quote", "table"):
                before = lead * 0.22
            take(before)
            put_lines(wrap_exact(b["text"], G.usable_w, F.sans, size, F), F.sans, size, lead)

        elif t == "code":
            budget = max(16, int((G.usable_w - 16.0) / mono_w))
            rows = []
            for bl in b["lines"]:
                for k, chunk in enumerate(wrap_cols(bl, budget, rest_penalty=2)):
                    rows.append(("" if k == 0 else "↪ ", chunk))
            take(code_lead * (0.55 if prev is not None else 0.0))
            if b["lang"]:
                take(code_lead * 0.92)
                page.text(G.x0 + 3.0, baseline_in(y, code_size - 1.0, code_lead * 0.92),
                          b["lang"], F.sans, code_size - 1.0, LIGHT)
            for k, (mark, chunk) in enumerate(rows):
                take(code_lead)
                page.rect(G.x0, y + 1.2, G.usable_w, code_lead, fill=CODE_BG)
                if mark:
                    page.text(G.x0 + 6.0, baseline_in(y, code_size, code_lead), mark,
                              F.mono, code_size, LIGHT)
                page.runs(G.x0 + 6.0 + (mono_w * 2 if mark else 0.0),
                          baseline_in(y, code_size, code_lead),
                          F.runs(chunk, F.mono), code_size, BLACK)
            take(code_lead * 0.45)

        elif t == "list":
            extra = min(b["indent"], 12) * size * 0.22
            x = G.x0 + ind + extra
            text_in = f"{b['marker']} {b['text']}"
            lines = wrap_exact(text_in, G.usable_w - ind - extra, F.sans, size, F)
            before = 0.0 if prev == "list" else lead * (0.32 if prev is not None else 0.0)
            take(before)
            put_lines(lines, F.sans, size, lead, x=x)

        elif t == "quote":
            take(lead * (0.42 if prev is not None else 0.0))
            lines = wrap_exact(b["text"], G.usable_w - ind, F.sans, size, F)
            top = y
            for ln in lines:
                take(lead)
                page.runs(G.x0 + ind, baseline_in(y, size, lead), F.runs(ln, F.sans),
                          size, QUOTE)
            page.rect(G.x0 + 2.0, y + 1.0, 2.4, top - y, fill=(0.80, 0.82, 0.86))
            take(lead * 0.2)

        elif t == "table":
            cs = max(6.0, code_size - 0.5)
            cl = leading_for(cs, 1.32)
            budget = max(16, int((G.usable_w - 6.0) / (F.mono_w * cs)))
            take(cl * (0.5 if prev is not None else 0.0))
            for row in b["lines"]:
                for chunk in wrap_cols(row, budget):
                    take(cl)
                    page.runs(G.x0 + 3.0, baseline_in(y, cs, cl), F.runs(chunk, F.mono),
                              cs, BLACK)
            take(cl * 0.35)

        elif t == "hr":
            take(lead * 0.40)
            page.line(G.x0, y + lead * 0.5, G.x0 + G.usable_w, y + lead * 0.5, RULE, 0.6)
            take(lead * 0.42)

        prev = t
        gap = False

    if not pages or page.items:
        pages.append(page)
    return pages


# ────────────────────────── 封面 / 目录 / 渲染 ──────────────────────────

def cover_page(title: str, subtitle: str, stats: list[str], G: Geom, F: Fonts) -> Page:
    page = Page(kind="cover")
    y = G.height * 0.72
    tsize = 25.0
    for ln in wrap_exact(title, G.usable_w, F.sans_bold, tsize, F):
        page.runs(G.x0, y - tsize, F.runs(ln, F.sans_bold), tsize, BLACK)
        y -= tsize * 1.32
    y -= 8
    page.line(G.x0, y, G.x0 + G.usable_w, y, BLACK, 1.1)
    y -= 26
    for ln in wrap_exact(subtitle, G.usable_w, F.sans, 11.5, F):
        page.runs(G.x0, y - 11.5, F.runs(ln, F.sans), 11.5, QUOTE)
        y -= 11.5 * 1.55
    y -= 24
    for s in stats:
        page.runs(G.x0, y - 9.8, F.runs(s, F.sans), 9.8, GRAY)
        y -= 9.8 * 1.85
    return page


def toc_entries_per_page(G: Geom, tsize: float, tl: float) -> int:
    return max(6, int((G.usable_h - tl * 2.4) // tl))


def toc_pages(entries: list[tuple[str, int, str]], G: Geom, F: Fonts) -> list[Page]:
    tsize = 9.6
    tl = leading_for(tsize, 1.5)
    per_page = toc_entries_per_page(G, tsize, tl)
    pages: list[Page] = []
    for start in range(0, len(entries), per_page):
        chunk = entries[start:start + per_page]
        page = Page(kind="toc", label="目录")
        y = G.y_top
        if not pages:
            page.text(G.x0, y - 16.0, "目录", F.sans_bold, 16.0, BLACK)
            y -= 16.0 + 9.0
            page.line(G.x0, y, G.x0 + G.usable_w, y, BLACK, 0.9)
            y -= 13.0
        else:
            page.text(G.x0, y - 10.0, "目录（续）", F.sans, 10.0, GRAY)
            y -= tl * 2.4
        for path, num, kind in chunk:
            pageno = str(num)
            num_w = F.width(pageno, F.sans, tsize)
            size_p = tsize - 0.4
            path, size_p = fit_text(path, F.sans, size_p,
                                    G.usable_w - num_w - 16.0, F, min_size=7.0)
            path_w = F.width(path, F.sans, size_p)
            left = G.usable_w - num_w
            page.runs(G.x0, y - tsize, F.runs(path, F.sans), size_p, DARK2)
            dots_w = G.usable_w - path_w - num_w - 14.0
            if dots_w > 10:
                dot_w = max(F.width("·", F.sans, tsize), 0.1)
                n = int(dots_w / dot_w)
                page.text(G.x0 + path_w + 7.0, y - tsize, "·" * n, F.sans, tsize,
                          (0.70, 0.70, 0.70))
            page.text(G.x0 + left, y - tsize, pageno, F.sans, tsize, DARK2)
            y -= tl
        pages.append(page)
    return pages or [Page(kind="toc", label="目录")]


def draw_page(c: rl_canvas.Canvas, page: Page, G: Geom, F: Fonts,
              pageno: int, total: int, footer: bool = True) -> None:
    for item in page.items:
        op = item[0]
        if op == "t":
            _, x, y, text, font, size, color = item
            c.setFillColorRGB(*color)
            c.setFont(font, size)
            c.drawString(x, y, text)
        elif op == "runs":
            _, x, y, runs, size, color = item
            c.setFillColorRGB(*color)
            for f, t in runs:
                c.setFont(f, size)
                c.drawString(x, y, t)
                x += F.width(t, f, size)
        elif op == "rect":
            _, x, y, w, h, fill, stroke, lw = item
            if fill:
                c.setFillColorRGB(*fill)
                c.rect(x, y, w, h, stroke=0, fill=1)
            if stroke:
                c.setStrokeColorRGB(*stroke)
                c.setLineWidth(lw)
                c.rect(x, y, w, h, stroke=1, fill=0)
        elif op == "line":
            _, x1, y1, x2, y2, color, lw = item
            c.setStrokeColorRGB(*color)
            c.setLineWidth(lw)
            c.line(x1, y1, x2, y2)

    if not footer or page.kind == "cover":
        return
    fs = 7.2
    c.setFillColorRGB(*LIGHT)
    c.setFont(F.sans, fs)
    label = page.label
    while label and F.width(label, F.sans, fs) > G.usable_w - 70.0:
        label = label[:-3] + "…" if len(label) > 3 else ""
    c.drawString(G.x0, G.bottom - 17.0, label)
    c.drawRightString(G.x0 + G.usable_w, G.bottom - 17.0, f"{pageno} / {total}")
    c.setStrokeColorRGB(*RULE)
    c.setLineWidth(0.4)
    c.line(G.x0, G.bottom - 9.0, G.x0 + G.usable_w, G.bottom - 9.0)


def write_pdf(path: Path, pages: list[Page], G: Geom, F: Fonts, meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    c = rl_canvas.Canvas(str(path), pagesize=(G.width, G.height))
    c.setTitle(meta.get("title", path.stem))
    c.setAuthor(meta.get("author", ""))
    c.setSubject(meta.get("subject", ""))
    total = len(pages)
    for i, page in enumerate(pages, start=1):
        draw_page(c, page, G, F, i, total)
        c.showPage()
    c.save()


# ────────────────────────── 文件发现 ──────────────────────────

DEFAULT_SKIP_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", "node_modules", ".venv", "venv", "env",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", "site-packages",
    "build", "dist", ".idea", ".vscode", "pdf_export",
}


def _git(root: Path, *args: str, timeout: int = 180) -> subprocess.CompletedProcess | None:
    if not shutil.which("git"):
        return None
    try:
        return subprocess.run(["git", "-C", str(root), *args],
                              capture_output=True, timeout=timeout)
    except Exception:
        return None


def _is_git_repo(root: Path) -> bool:
    r = _git(root, "rev-parse", "--is-inside-work-tree", timeout=20)
    return bool(r and r.returncode == 0 and r.stdout.strip() == b"true")


def discover(root: Path, exts: list[str], use_git: bool,
             include: list[str], exclude: list[str]) -> tuple[list[str], str]:
    """返回 (相对路径列表, 发现方式说明)。默认只取项目自己的文件。"""
    files: list[str] = []
    how = ""
    if use_git and _is_git_repo(root):
        how = "git ls-files（已排除 .gitignore 里的目录/文件）"
        r = _git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard",
                 "--", *[f"*{e}" for e in exts])
        if r is not None and r.returncode == 0:
            for raw in r.stdout.split(b"\0"):
                if not raw:
                    continue
                rel = raw.decode("utf-8", "surrogateescape")
                if (root / rel).is_file():
                    files.append(rel)
        elif not shutil.which("git"):
            how = ""
    if not files:
        how = how or "目录遍历（按内置忽略规则）"
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d not in DEFAULT_SKIP_DIRS)
            for fn in sorted(filenames):
                if any(fn.endswith(e) for e in exts):
                    files.append(Path(os.path.relpath(os.path.join(dirpath, fn), root)).as_posix())

    def keep(rel: str) -> bool:
        if include and not any(
                fnmatch.fnmatch(rel, p) or fnmatch.fnmatch("/" + rel, p)
                or fnmatch.fnmatch(rel, p.rstrip("/") + "/*") for p in include):
            return False
        return not any(fnmatch.fnmatch(rel, p) for p in exclude)

    return sorted({f for f in files if keep(f)}), how


def read_text(path: Path) -> tuple[str, str | None]:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc), None if enc == "utf-8" else f"以 {enc} 解码"
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace"), "含无法解码字节，已用替换符"


# ────────────────────────── 主流程 ──────────────────────────

def parse_margin(s: str) -> tuple[float, float, float, float]:
    parts = [p for p in re.split(r"[,\s]+", s.strip()) if p]
    try:
        vals = [float(p) for p in parts]
    except ValueError:
        raise argparse.ArgumentTypeError("margin 需为数字，或 上,右,下,左 四个数字")
    if len(vals) == 1:
        return vals[0], vals[0], vals[0], vals[0]
    if len(vals) == 4:
        return vals[0], vals[1], vals[2], vals[3]
    raise argparse.ArgumentTypeError("margin 需为 1 个或 4 个数字")


def _git_rev(root: Path) -> str:
    r = _git(root, "rev-parse", "--short", "HEAD", timeout=15)
    if not r or r.returncode != 0:
        return ""
    sha = r.stdout.decode().strip()
    b = _git(root, "rev-parse", "--abbrev-ref", "HEAD", timeout=15)
    branch = b.stdout.decode().strip() if b and b.returncode == 0 else ""
    return f"{branch}@{sha}" if branch and branch != "HEAD" else sha


def _safe_name(s: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", s).strip("_") or "project"


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="export_pdf.py",
        description="把项目里的 .py / .md 导出成 PDF（可合并成一册），用于打印精读批注。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
               "  python3 tools/export_pdf.py --merge\n"
               "  python3 tools/export_pdf.py --ext .md --merged-only -o md_pdf\n"
               "  python3 tools/export_pdf.py --include 'harness/*' --merge\n")
    ap.add_argument("root", nargs="?", default=".", help="项目根目录（默认当前目录）")
    ap.add_argument("-o", "--out", default="pdf_export", help="输出目录（默认 pdf_export）")
    ap.add_argument("--ext", default=".py,.md", help="导出哪些扩展名，逗号分隔（默认 .py,.md）")
    ap.add_argument("--include", action="append", default=[], metavar="GLOB",
                    help="只导出匹配的文件（可多次，相对路径 glob）")
    ap.add_argument("--exclude", action="append", default=[], metavar="GLOB",
                    help="排除匹配的文件（可多次）")
    ap.add_argument("--no-git", action="store_true", help="不用 git 列举，直接遍历目录")
    ap.add_argument("--merge", action="store_true", help="额外生成合并册（封面 + 目录）")
    ap.add_argument("--merged-only", action="store_true", help="只生成合并册，不导出单文件")
    ap.add_argument("--no-cover", action="store_true", help="合并册不加封面")
    ap.add_argument("--no-toc", action="store_true", help="合并册不加目录")
    ap.add_argument("--title", default=None, help="封面标题（默认用项目目录名）")
    ap.add_argument("--paper", default="a4", choices=sorted(PAPERS), help="纸张（默认 a4）")
    ap.add_argument("--landscape", action="store_true", help="横向")
    ap.add_argument("--margin", default="46,42,44,46", type=parse_margin,
                    help="页边距 上,右,下,左（默认 46,42,44,46，留白供批注）")
    ap.add_argument("--font-size", type=float, default=8.4, help="代码字号（默认 8.4）")
    ap.add_argument("--line-spacing", type=float, default=1.34, help="代码行距倍数（默认 1.34）")
    ap.add_argument("--body-size", type=float, default=9.6, help="Markdown 正文字号（默认 9.6）")
    ap.add_argument("--no-line-numbers", action="store_true", help="不打印代码行号")
    ap.add_argument("--tab", type=int, default=4, help="Tab 展开宽度（默认 4）")
    ap.add_argument("--list", action="store_true", help="只列出将要导出的文件，不生成 PDF")
    ap.add_argument("--quiet", action="store_true", help="减少输出")
    ap.add_argument("--version", action="version", version=f"export_pdf.py {__version__}")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        print(f"✗ 不是目录：{root}", file=sys.stderr)
        return 2
    out_dir = Path(args.out).expanduser()
    if not out_dir.is_absolute():
        out_dir = (root / out_dir).resolve()

    exts = [e if e.startswith(".") else "." + e
            for e in args.ext.replace(" ", "").split(",") if e]

    files, how = discover(root, exts, not args.no_git, args.include, args.exclude)
    if not files:
        print("✗ 没有找到可导出的文件（试试 --no-git，或检查 --ext / --include 过滤条件）")
        return 1

    by_ext: dict[str, int] = {}
    for f in files:
        by_ext[Path(f).suffix] = by_ext.get(Path(f).suffix, 0) + 1
    summary = "、".join(f"{k} × {v}" for k, v in sorted(by_ext.items()))

    if args.list:
        print(f"项目根目录：{root}")
        print(f"发现方式：{how}")
        print(f"共 {len(files)} 个文件（{summary}）：")
        for f in files:
            print("  " + f)
        return 0

    if not args.quiet:
        print(f"项目：{root}")
        print(f"发现方式：{how}")
        print(f"文件：{len(files)} 个（{summary}）")

    F = Fonts(verbose=not args.quiet)
    for note in F.notes:
        print(f"! {note}", file=sys.stderr)

    pw, ph = PAPERS[args.paper]
    if args.landscape:
        pw, ph = ph, pw
    mt, mr, mb, ml = args.margin
    G = Geom(pw, ph, ml, mr, mt, mb)
    opt = Options(code_size=args.font_size, code_leading=args.line_spacing,
                  body_size=args.body_size, line_numbers=not args.no_line_numbers,
                  tab=args.tab)

    # —— 排版 ——
    t0 = datetime.datetime.now()
    warnings: list[str] = []
    laid: list[tuple[str, list[Page]]] = []
    for rel in files:
        try:
            text, note = read_text(root / rel)
            if note:
                warnings.append(f"{rel}：{note}")
        except Exception as exc:
            warnings.append(f"{rel}：读取失败（{exc}），已跳过")
            continue
        is_md = Path(rel).suffix.lower() in MD_SUFFIXES
        pages = layout_md(rel, text, G, F, opt) if is_md \
            else layout_code(rel, text, G, F, opt)
        laid.append((rel, pages))
        if not args.quiet:
            print(f"  排版 {rel}  {len(pages)} 页")

    if not laid:
        print("✗ 没有任何文件排版成功", file=sys.stderr)
        return 1

    # —— 单文件导出 ——
    singles = not args.merged_only
    if singles:
        for rel, pages in laid:
            write_pdf(out_dir / "single" / (rel + ".pdf"), pages, G, F,
                      {"title": rel, "subject": "项目源码打印本",
                       "author": args.title or root.name})
        if not args.quiet:
            print(f"✓ 单文件 PDF：{len(laid)} 个 → {out_dir / 'single'}")

    # —— 合并册 ——
    merged_path = None
    if args.merge or args.merged_only:
        title = args.title or f"{root.name} 源码打印本"
        head_pages: list[Page] = []
        if not args.no_cover:
            stats = [f"文件 {len(laid)} 份（{summary}）",
                     f"纸张 {args.paper.upper()}{' 横向' if args.landscape else ''}"
                     f"，页边距 {mt:g}/{mr:g}/{mb:g}/{ml:g} pt",
                     f"生成时间 {t0:%Y-%m-%d %H:%M}"]
            rev = _git_rev(root)
            if rev:
                stats.append(f"版本 {rev}")
            head_pages.append(cover_page(
                title, "用于打印精读与批注（.py 源码 + .md 文档）", stats, G, F))

        toc_count = 0
        if not args.no_toc:
            tsize, tl = 9.6, leading_for(9.6, 1.5)
            per_page = toc_entries_per_page(G, tsize, tl)
            toc_count = max(1, -(-len(laid) // per_page))

        entries: list[tuple[str, int, str]] = []
        start = len(head_pages) + toc_count
        for rel, pages in laid:
            start += 1
            entries.append((rel, start, Path(rel).suffix))
            start += len(pages) - 1
        if toc_count:
            head_pages.extend(toc_pages(entries, G, F))

        all_pages = head_pages + [pg for _, pages in laid for pg in pages]
        merged_path = out_dir / f"{_safe_name(root.name)}-all.pdf"
        write_pdf(merged_path, all_pages, G, F,
                  {"title": title, "subject": "项目源码打印本", "author": root.name})
        if not args.quiet:
            print(f"✓ 合并册：{len(all_pages)} 页 → {merged_path}")

    dur = (datetime.datetime.now() - t0).total_seconds()
    print(f"\n完成，用时 {dur:.1f}s")
    if merged_path:
        print(f"合并册：{merged_path}")
    if singles:
        print(f"单文件目录：{out_dir / 'single'}")
    if warnings:
        print(f"\n提示（{len(warnings)} 条）：")
        for w in warnings[:15]:
            print("  - " + w)
        if len(warnings) > 15:
            print(f"  … 其余 {len(warnings) - 15} 条略")
    return 0


if __name__ == "__main__":
    sys.exit(main())
