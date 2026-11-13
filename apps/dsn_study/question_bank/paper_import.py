# apps/dsn_study/question_bank/paper_import.py
# 整卷入库管线 —— 把「一套卷子」变成「题库里的题目」的一条龙。
#
# 设计目标（对应「AI 调一个工具传几个参就完成」）：
#   下载 → OCR → 判定试题/答案边界 → 抽题 → 对答案 → 入库 → 出 PDF（可选打印）
#   全流程在一个工具调用内完成，AI 不需要自己编排十几步。
#
# 两个关键修复点：
#   1. **边界判定不靠位置启发式**。gaokzx 站点给每张图打的 question/answer
#      标签是「位于前半部分/后半部分」猜出来的，实测会把答案页当成试题页
#      （2026-2027 北师大附中卷：真边界 9/21，站点切在 11/21）。
#      本模块改为**看 OCR 出来的正文**判定，OCR 与判定只花一次调用。
#   2. **抽题按页分片**，不是把整卷塞进一次 LLM 调用。九页物理卷的 OCR 文本
#      有好几万字符，一次性要 JSON 数组必然截断/解析失败。

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Optional

logger = logging.getLogger("PaperImporter")

# ── 答案页特征 ────────────────────────────────────────────────────────────
# 这些标记出现在**页首**时，该页即答案/解析页。
ANSWER_MARKERS = (
    "参考答案",
    "答案与解析",
    "参考答案与评分标准",
    "参考答案及评分标准",
    "【答案】",
    "答案速查",
    "评分标准",
    "详解",
)
# 页首扫描窗口：只看开头这么多字，避免题干里顺带提到「参考答案见答题卡」误判
_HEADER_WINDOW = 400

# OCR 提示词：一次调用同时拿到正文和"这页是不是答案页"的标记
_OCR_PROMPT = (
    "识别图片中的全部文字，按 Markdown 格式输出，保留题目编号、公式、"
    "表格与图形说明，不要臆造图片里没有的内容。\n"
    "如果这一页是参考答案/答案解析/评分标准（而不是试题本身），"
    "请在输出的最开头单独加一行 `<!-- ANSWER -->`。"
)


def _json_from_text(text: str) -> list:
    """从 LLM 输出里稳妥地取出 JSON 数组。

    直接 json.loads 很容易被一个多余逗号或代码围栏打回，
    这里做三层兜底：去围栏 → 截取最外层数组 → 修尾逗号。
    """
    if not text:
        return []
    raw = text.strip()

    # 1) 去 ``` 围栏
    if "```" in raw:
        m = re.search(r"```(?:json)?\s*(.*?)```", raw, re.S)
        if m:
            raw = m.group(1).strip()

    # 2) 直接解析
    try:
        val = json.loads(raw)
        return val if isinstance(val, list) else [val]
    except Exception:
        pass

    # 3) 截取最外层数组
    start = raw.find("[")
    end = raw.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    frag = raw[start:end + 1]

    for candidate in (frag, re.sub(r",\s*([\]}])", r"\1", frag)):
        try:
            val = json.loads(candidate)
            return val if isinstance(val, list) else [val]
        except Exception:
            continue
    return []


class PaperImporter:
    """整卷导入管线。"""

    def __init__(self, question_store=None, llm=None, workspace=None,
                 gaokzx=None):
        self._store = question_store
        self._llm = llm
        self._workspace = workspace
        self._gaokzx = gaokzx
        #: 当前持有的本地 VLM 租约（None = 未持有）。import_paper 会在整个
        #: OCR 阶段持有一次，避免每页都去借还一次。
        self._vlm_lease = None

    # ─────────────────────────────────────────────────────────────
    # 0. 依赖
    # ─────────────────────────────────────────────────────────────
    def _gaokzx_tool(self):
        if self._gaokzx is None:
            from apps.dsn_study.skills.builtin.gaokzx.tools.gaokzx_tools import (
                GaokzxTool,
            )
            self._gaokzx = GaokzxTool()
        return self._gaokzx

    def _workspace_dir(self) -> str:
        base = self._workspace or ".dsn/workspace"
        os.makedirs(base, exist_ok=True)
        return os.path.abspath(base)

    # ─────────────────────────────────────────────────────────────
    # 1. 定位试卷
    # ─────────────────────────────────────────────────────────────
    def resolve_paper(self, paper_id: int = 0, keyword: str = "") -> dict:
        """按 id 或关键词定位一套试卷。"""
        tool = self._gaokzx_tool()
        if paper_id:
            info = tool.inspect_paper(paper_id=paper_id)
            if not info.get("success"):
                return {"success": False, "error": info.get("error", "解析试卷失败")}
            return {
                "success": True,
                "paper_id": int(paper_id),
                "title": info.get("title", ""),
                "url": info.get("url", ""),
                "pdfs": info.get("pdfs", []),
            }

        keyword = (keyword or "").strip()
        if not keyword:
            return {"success": False, "error": "需要 paper_id 或 keyword 之一"}

        found = tool.search_papers(keyword=keyword, page=1, page_size=20)
        if not found.get("success"):
            return {"success": False, "error": found.get("error", "搜索失败")}
        papers = found.get("papers") or []
        if not papers:
            return {"success": False, "error": f"没有搜到试卷: {keyword}"}

        # 优先选标题里带「试题」且带「答案」的（通常是完整卷），否则取第一条
        def _rank(p: dict) -> tuple:
            t = p.get("title", "")
            return (0 if ("答案" in t) else 1, 0 if "试题" in t else 1)

        papers.sort(key=_rank)
        pick = papers[0]
        info = tool.inspect_paper(paper_id=int(pick["id"]))
        return {
            "success": True,
            "paper_id": int(pick["id"]),
            "title": info.get("title") or pick.get("title", ""),
            "url": info.get("url") or pick.get("url", ""),
            "pdfs": info.get("pdfs", []),
            "candidates": [p.get("title", "") for p in papers[:5]],
        }

    # ─────────────────────────────────────────────────────────────
    # 2. 下载图片
    # ─────────────────────────────────────────────────────────────
    def download(self, paper_id: int) -> dict:
        tool = self._gaokzx_tool()
        res = tool.download_images(paper_id=int(paper_id), kind="all")
        if not res.get("success"):
            return {"success": False, "error": res.get("error", "下载失败")}

        # download_images 是幂等的：本次新下载的进 saved，已存在且大小一致的
        # 进 skipped。**两个都要收**，否则第二次运行会一张图都拿不到。
        entries = list(res.get("saved") or []) + list(res.get("skipped") or [])
        d = res.get("dir") or ""

        def _pick(kind: str) -> list[str]:
            got = [e for e in entries
                   if e.get("kind") == kind and e.get("path")]
            # 按文件名里的序号排序（question_01 < question_10）
            got.sort(key=lambda e: os.path.basename(e["path"]))
            return [e["path"] for e in got]

        q = _pick("question")
        a = _pick("answer")
        # 站点把部分图片标成 unknown，兜底按文件名收
        if not q and not a:
            rest = sorted({e["path"] for e in entries if e.get("path")})
            q = [p for p in rest if "question" in os.path.basename(p)]
            a = [p for p in rest if "answer" in os.path.basename(p)]

        return {"success": True, "dir": d, "question_files": q, "answer_files": a,
                "count": len(q) + len(a),
                "newly_saved": len(res.get("saved") or []),
                "reused": len(res.get("skipped") or []),
                "failed": res.get("failed") or []}

    # ─────────────────────────────────────────────────────────────
    # 3. OCR（本地 VLM，带磁盘缓存，断点可续）
    # ─────────────────────────────────────────────────────────────
    def _vlm_ctx(self):
        """本地 VLM 的租约上下文（可重入）。

        import_paper 会在整个 OCR 阶段持有一次租约；ocr_pages 单独被调用时
        （比如验收脚本）自己临时借一次。借租约的动作**就是按需拉起**的地方。
        """
        from contextlib import nullcontext

        from apps.dsn_study.models.vlm_service import vlm_lease

        if self._vlm_lease is not None:
            return nullcontext(self._vlm_lease)
        return vlm_lease()

    def ocr_pages(self, files: list[str], cache_dir: str = "",
                  progress: Optional[Any] = None) -> list[dict]:
        """逐页 OCR，返回 [{file, md, marked_answer}]。

        OCR 走**本地** Bonsai llama-server（不再打云端视觉 API）：
        对照评测显示两者精准度基本打平，但本地页码更稳、选项更分行，
        且试卷内容不外传。服务不常驻 —— 首次 OCR 时按需拉起（约 40s 冷启动）。

        OCR 结果落盘为同名 .md，重复运行直接复用 —— 一套卷子 OCR 一次要几分钟。
        **全部命中缓存时完全不碰模型**（不会白等一次冷启动）。
        """
        cache_dir = cache_dir or os.path.join(self._workspace_dir(), "ocr")
        os.makedirs(cache_dir, exist_ok=True)

        results: dict[str, dict] = {}
        pending: list[str] = []

        # ① 先取缓存命中的页 —— 这一步**不**触发任何模型加载
        for f in files:
            stem = os.path.splitext(os.path.basename(f))[0]
            md_path = os.path.join(cache_dir, stem + ".md")
            md = ""
            if os.path.isfile(md_path):
                try:
                    with open(md_path, encoding="utf-8") as fh:
                        md = fh.read()
                except OSError:
                    md = ""
            if md.strip():
                results[f] = {"file": f, "md": md,
                              "marked_answer": "<!-- ANSWER -->" in md}
            else:
                pending.append(f)

        # ② 剩下的才需要本地 VLM（借租约 = 按需拉起）
        if pending:
            with self._vlm_ctx():
                from apps.dsn_study.models.vlm_service import local_vision_model

                vm = local_vision_model()

                for idx, f in enumerate(pending):
                    stem = os.path.splitext(os.path.basename(f))[0]
                    md_path = os.path.join(cache_dir, stem + ".md")
                    try:
                        data_url = vm.encode_image(f)
                        md = vm.ask(data_url, _OCR_PROMPT, max_tokens=4096,
                                    temperature=0.1)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("OCR 失败 %s: %s",
                                       os.path.basename(f), e)
                        results[f] = {"file": f, "md": "", "marked_answer": False,
                                      "error": str(e)}
                        continue

                    md = md or ""
                    try:
                        with open(md_path, "w", encoding="utf-8") as fh:
                            fh.write(md)
                    except OSError:
                        pass
                    results[f] = {"file": f, "md": md,
                                  "marked_answer": "<!-- ANSWER -->" in md}
                    if progress:
                        try:
                            progress(idx + 1, len(pending),
                                     os.path.basename(f))
                        except Exception:  # noqa: BLE001
                            pass

        return [results[f] for f in files if f in results]

    # ─────────────────────────────────────────────────────────────
    # 4. 边界判定（看内容，不看位置）
    # ─────────────────────────────────────────────────────────────
    @staticmethod
    def _page_is_answer(page: dict) -> Optional[str]:
        """这一页是不是答案页？返回命中的判据说明，不是则 None。"""
        if page.get("marked_answer"):
            return "OCR 标记"
        head = (page.get("md") or "")[:_HEADER_WINDOW]
        for marker in ANSWER_MARKERS:
            if marker in head:
                return f"页首出现「{marker}」"
        return None

    def _ocr_until_boundary(self, files: list[str],
                            progress: Optional[Any] = None) -> tuple[list[dict], dict]:
        """顺序 OCR 试题区，认出第一页答案就停。

        :param progress: 进度回调 (done, total, name)
        :return: (已 OCR 的页面列表, 边界信息)
        """
        scanned: list[dict] = []
        total = len(files)
        for i, f in enumerate(files):
            # 单页调用 ocr_pages 会让它以为只有 1 页 —— 这里把进度折算成
            # 「总共第几页」，否则进度条永远显示 1/1（曾经的真·瑕疵）。
            def _cb(done: int, _total: int, name: str, _i: int = i) -> None:
                if progress:
                    progress(_i + done, total, name)

            pages = self.ocr_pages([f], progress=_cb)
            if not pages:
                continue
            page = pages[0]
            scanned.append(page)
            why = self._page_is_answer(page)
            if why:
                return scanned, {"boundary": i, "method": "content",
                                 "detail": f"第 {i + 1} 页判定为答案页（{why}）"}
        return scanned, {"boundary": len(scanned), "method": "fallback_all",
                         "detail": "试题区未发现答案页特征"}

    @staticmethod
    def detect_boundary(pages: list[dict]) -> dict:
        """返回 {boundary, method, detail}：boundary = 试题页数。

        判据优先级：
          a. OCR 提示词打上的 <!-- ANSWER --> 标记
          b. 页首出现「参考答案/评分标准/详解」等标记
        """
        if not pages:
            return {"boundary": 0, "method": "none", "detail": "没有页面"}

        # a) 显式标记
        for i, p in enumerate(pages):
            if p.get("marked_answer"):
                return {"boundary": i, "method": "ocr_marker",
                        "detail": f"第 {i + 1} 页被 OCR 标记为答案页"}

        # b) 页首文本特征
        for i, p in enumerate(pages):
            head = (p.get("md") or "")[:_HEADER_WINDOW]
            for marker in ANSWER_MARKERS:
                if marker in head:
                    return {"boundary": i, "method": "text_marker",
                            "detail": f"第 {i + 1} 页页首出现「{marker}」"}

        return {"boundary": len(pages), "method": "fallback_all",
                "detail": "未找到答案页特征，整份按试题处理"}

    # ─────────────────────────────────────────────────────────────
    # 5. 抽题
    # ─────────────────────────────────────────────────────────────
    _EXTRACT_PROMPT = (
        "下面是一份试卷的其中一页。请只提取**在本页开始**的题目，返回 JSON 数组。\n"
        "\n"
        "判定规则（很重要）：\n"
        "1. 只抽题号标记出现在本页的题。若某题没有题号，则只抽它的题干文字**从本页开头"
        "出现的第一个字**开始的那道题。\n"
        "2. 若某题的题干其实是从**上一页延续下来的**（本页开头是它的后半段、选项或"
        "「根据上述信息…」这类承前设问），**不要抽它** —— 它在下一页的抽取里已经处理过。\n"
        "3. 若某题在本页开始、但在本页结束时还没写完（选项跑到下一页），"
        "就如实抽取本页已有的部分，不要编造后面的内容。\n"
        "\n"
        "每个元素包含：\n"
        "- number: 题号（字符串，如 \"12\"；没有则空串）\n"
        "- content: 题干（字符串，含公式，保留原文表述）\n"
        "- options: 选项数组（选择题才有，否则空数组），形如 [\"A. ...\", \"B. ...\"]\n"
        "- type_name: 题型（选择题/填空题/解答题/判断题）\n"
        "- subtype: 子类型（单选/多选/填空/计算/证明/简答/判断）\n"
        "- difficulty: 难度 1-5（整数）\n"
        "- tags: 标签数组\n"
        "- knowledge_points: 知识点数组（如 [\"牛顿第二定律\", \"受力分析\"]）\n\n"
        "只输出纯 JSON 数组，不要任何解释文字。\n\n"
        "【本页文本】\n{text}\n"
        "{next_hint}"
    )

    # 去重键用：剥掉 LaTeX、markdown、标点，只留实义字符
    # 判重所需的最小公共长度（归一化后的字符数）。
    #
    # 为什么是 18 而不是更大的数：跨页题被抽两次时，**残缺的那份可能只有
    # 二十来个字**（例：「如图所示，两个带等量正电的点电荷位于 M、N 两点上，」）
    # —— 阈值定 24 时它会被当成独立的一题，题库里就多出一道半截的重复题。
    # 18 个归一化后的中文字符（标点/空格/LaTeX 记号都已剥掉）已经足够独特，
    # 几乎不可能是两道不同题的共同开头。
    _DEDUPE_MIN_LEN = 18

    @staticmethod
    def _dedupe_key(text: str, n: int = 60) -> str:
        """去重键：只剥掉标记符号，**保留文字本身**。

        同一道题两次抽取的写法差异主要在 $…$ / markdown 记号上
        （`$m$` vs `m`），所以这里把公式定界符和命令去掉，
        但保留下标、数字这些实义内容，否则两边会被削成不同的串。
        """
        t = text or ""
        t = re.sub(r"\\(?:text|mathrm|mathbf|,|;|!|\s)", "", t)   # LaTeX 命令
        t = re.sub(r"\\[a-zA-Z]+", "", t)
        t = t.replace("$", "").replace("\\", "")
        t = re.sub(r"[{}]", "", t)                                # 公式花括号
        t = re.sub(r"\*\*|__|`{1,3}|#{1,6}\s?", "", t)
        t = re.sub(r"[【】\[\]（）()「」《》<>]", "", t)
        t = re.sub(r"[，。、；：！？,.;:!?\"'“”‘’\s　]", "", t)
        # 常见希腊字母：OCR 有时给符号、有时给转义名
        for greek in ("theta", "alpha", "beta", "gamma", "lambda", "mu",
                      "omega", "pi", "rho", "sigma", "phi", "delta"):
            t = t.replace(greek, "")
        # Unicode 希腊字母（θ α β …）也一并去掉，避免一边是符号一边是空
        t = re.sub(r"[\u0370-\u03ff\u2200-\u22ff]", "", t)
        # 数学记号归一化：同一公式两次 OCR 常给出不同写法
        #   10^7 / 10^{7} / 10⁷、~ / ～ / \sim、· / × 等
        t = re.sub(r"[\^_]", "", t)              # 上下标标记
        t = re.sub(r"[~～∼≈·×*÷]", "", t)         # 约等号/乘号等
        t = t.replace("\\sim", "")
        t = re.sub(r"[⁰¹²³⁴⁵⁶⁷⁸⁹]", "", t)        # 上标数字
        return t[:n].lower()

    @staticmethod
    def _dedupe_questions(questions: list[dict]) -> list[dict]:
        """跨页去重。

        一道题横跨两页时会被抽两次（一次是题干、一次是后半段/选项）。
        判重键用「剥离 LaTeX 和标点后的题干前缀」—— 同一道题两次抽取
        的 LaTeX 写法常有出入（$m$ vs m），不归一化就会漏判。
        命中时**合并**：题干取更长的一份，其余字段缺失的补上。

        注意：同一道题两次抽取的文本长度可能不同（一次截在题号处、
        一次带完整题干），所以判定用**前缀包含**而不是等值 ——
        两个键里短的那个是长的那个的前缀，就算同一道题。
        """
        def key_of(q: dict) -> str:
            return PaperImporter._dedupe_key(q.get("content") or "")

        merged: dict[str, dict] = {}
        order: list[str] = []

        def _find_same(k: str) -> Optional[str]:
            """在已有键里找「同题」：一个键是另一个的前缀，且短的那个够长。"""
            if k in merged:
                return k
            min_len = PaperImporter._DEDUPE_MIN_LEN
            for exist in order:
                short, long_ = (k, exist) if len(k) <= len(exist) else (exist, k)
                if len(short) >= min_len and long_.startswith(short):
                    return exist
            return None

        for q in questions:
            k = key_of(q)
            if not k:
                continue
            hit = _find_same(k)
            if hit is None:
                merged[k] = dict(q)
                order.append(k)
                continue
            old = merged[hit]
            # 合并后统一挂在**较长的键**下，避免后续同类题因为键变短而漏判
            target = hit if len(hit) >= len(k) else k
            if target != hit:
                merged[target] = merged.pop(hit)
                order[order.index(hit)] = target
            old = merged[target]
            # 题干取更长的那份
            if len(q.get("content") or "") > len(old.get("content") or ""):
                old["content"] = q["content"]
            # 选项/答案/解析/知识点：缺失的补上
            for field in ("options", "answer", "explanation", "tags",
                          "knowledge_points", "type_name", "subtype"):
                if not old.get(field) and q.get(field):
                    old[field] = q[field]
            if not old.get("number") and q.get("number"):
                old["number"] = q["number"]
        return [merged[k] for k in order]

    # ── 题号：从 OCR 原文按位置确定，不采信模型给的编号 ──
    # 模型给续页题编号会出错（把上一题的号重复用），编号一错，
    # 后面按编号对答案就会把别的题的答案配过来 —— 题库里存错答案
    # 比存空答案更糟。所以改成从 OCR 原文里按「题号标记的位置」回填。
    _NUM_MARK_PATTERNS = (
        re.compile(r"\*\*\s*(\d{1,3})\s*[.．、]\s*\*\*"),          # **7.**
        re.compile(r"(?m)^\s*(\d{1,3})\s*[.．、]\s+"),            # 9. 水平面上…
        re.compile(r"(?<!\d)(\d{1,3})\s*[.．、]\s*(?=\S)"),       # 兜底
    )

    @staticmethod
    def _number_markers(md: str) -> list[tuple[int, str]]:
        """返回 [(位置, 题号)]，按位置升序。"""
        marks: list[tuple[int, str]] = []
        for pat in PaperImporter._NUM_MARK_PATTERNS:
            for m in pat.finditer(md):
                marks.append((m.start(), m.group(1)))
        # 同位置保留先命中的（第一个模式优先），再按位置排序
        seen: dict[int, str] = {}
        for pos, num in sorted(marks, key=lambda x: x[0]):
            seen.setdefault(pos, num)
        return sorted(((p, n) for p, n in seen.items()))

    @staticmethod
    def _clean_for_anchor(text: str) -> str:
        """把题干洗成可以在 OCR 原文中定位的锚点串。"""
        t = text or ""
        t = re.sub(r"\$[^$]*\$", "", t)        # 去 LaTeX 行内公式
        t = re.sub(r"【[^】]*】", "", t)         # 去图注
        t = re.sub(r"[*_`#>\\]", "", t)         # 去 markdown 记号
        t = re.sub(r"[\s　]+", "", t)
        return t[:12]

    @staticmethod
    def _find_anchor(md: str, anchor: str) -> Optional[int]:
        """在 OCR 原文中定位锚点（容忍字符间有空白）。"""
        if len(anchor) < 4:
            return None
        pat = r"\s*".join(re.escape(ch) for ch in anchor)
        m = re.search(pat, md)
        return m.start() if m else None

    @classmethod
    def _assign_numbers(cls, questions: list[dict], md: str,
                        prev_md: str = "") -> None:
        """按题号标记的位置给抽出来的题回填题号（原地修改）。

        跨页的题（题干在上一页、选项在下一页）在当前页找不到锚点，
        这时回上一页找 —— 它的题号就是上一页那道题的号。
        """
        sources = [(md, cls._number_markers(md))]
        if prev_md:
            sources.append((prev_md, cls._number_markers(prev_md)))

        for q in questions:
            anchor = cls._clean_for_anchor(q.get("content") or "")
            for src_md, marks in sources:
                if not marks:
                    continue
                pos = cls._find_anchor(src_md, anchor)
                if pos is None:
                    continue
                num = None
                for mpos, mnum in marks:
                    if mpos <= pos:
                        num = mnum
                    else:
                        break
                if num:
                    q["number"] = num
                break

    def extract_questions(self, pages: list[dict], subject: str = "physics",
                          tail_context: str = "") -> tuple[list[dict], list[str]]:
        """逐页抽题。返回 (questions, errors)。"""
        if not self._llm:
            return [], ["模型服务未就绪"]
        questions: list[dict] = []
        errors: list[str] = []
        prev_tail = tail_context
        prev_md = ""

        for i, p in enumerate(pages):
            md = (p.get("md") or "").strip()
            if not md:
                continue
            # 衔接上下文给**下一页开头**：让模型知道哪些承前内容属于上一页的题，
            # 从而不会把跨页题当成本页的新题重复抽一遍。
            # （早先给的是上一页末尾，反而诱导模型把续页题再抽一次。）
            next_hint = ""
            if i + 1 < len(pages):
                nxt = (pages[i + 1].get("md") or "").strip()[:200]
                if nxt:
                    next_hint = (f"\n【下一页开头，仅用于判断本页末尾的题是否延续，"
                                 f"不要据此抽题】\n{nxt}\n")
            try:
                resp = self._llm.send_message(
                    self._EXTRACT_PROMPT.format(text=md, next_hint=next_hint),
                    timeout=180)
            except Exception as e:  # noqa: BLE001
                errors.append(f"{os.path.basename(p.get('file', ''))}: {e}")
                continue
            got = _json_from_text(resp)
            if not got:
                errors.append(f"{os.path.basename(p.get('file', ''))}: 未解析出 JSON")
            for q in got:
                if isinstance(q, dict) and (q.get("content") or "").strip():
                    q.setdefault("subject", subject)
                    q["_page"] = i + 1
                    questions.append(q)
            # 题号从 OCR 原文回填（覆盖模型给的编号）；
            # 当前页找不到的跨页题，回上一页找
            self._assign_numbers([q for q in got if isinstance(q, dict)], md,
                                 prev_md)
            prev_md = md
        return self._dedupe_questions(questions), errors

    _ANSWER_PROMPT = (
        "从下面的参考答案/解析文本中提取**答案对照表**，返回 JSON 对象。\n"
        '形如 {{"1": "A", "2": "B", "13": "4m/s^2"}}。\n'
        "只输出纯 JSON 对象，不要解释。\n\n"
        "文本：\n{text}"
    )

    def extract_answer_key(self, pages: list[dict]) -> dict[str, str]:
        """从答案页提取 题号 → 答案 的对照表。"""
        if not self._llm:
            return {}
        merged: dict[str, str] = {}
        for p in pages:
            md = (p.get("md") or "").strip()
            if not md:
                continue
            try:
                resp = self._llm.send_message(
                    self._ANSWER_PROMPT.format(text=md), timeout=180)
            except Exception as e:  # noqa: BLE001
                logger.warning("答案表提取失败: %s", e)
                continue
            raw = resp.strip()
            m = re.search(r"\{.*\}", raw, re.S)
            if not m:
                continue
            try:
                obj = json.loads(m.group(0))
            except Exception:
                try:
                    obj = json.loads(re.sub(r",\s*([\]}])", r"\1", m.group(0)))
                except Exception:
                    continue
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k is not None and v is not None:
                        merged[str(k).strip()] = str(v).strip()
        return merged

    # ─────────────────────────────────────────────────────────────
    # 6. 入库
    # ─────────────────────────────────────────────────────────────
    def commit(self, questions: list[dict], subject: str = "physics",
               user_id: int = 1, dry_run: bool = False,
               source: str = "paper_import",
               metadata: Optional[dict] = None) -> dict:
        if not self._store:
            return {"success": False, "error": "题库未就绪"}
        if not questions:
            return {"success": False, "error": "没有可入库的题目"}
        meta = dict(metadata or {})

        conn = self._store._db._get_connection()
        row = conn.execute(
            "SELECT subject_id FROM subjects WHERE code = ?", (subject,)).fetchone()
        if not row:
            return {"success": False, "error": f"学科 {subject} 不存在"}
        subject_id = row["subject_id"]

        def _type_id(name: str, subtype: str) -> int:
            r = conn.execute(
                "SELECT type_id FROM question_types WHERE name = ? AND subtype = ?",
                (name, subtype)).fetchone()
            if r:
                return r["type_id"]
            if not subtype:
                r = conn.execute(
                    "SELECT type_id FROM question_types WHERE name = ? LIMIT 1",
                    (name,)).fetchone()
                if r:
                    return r["type_id"]
            cur = conn.execute(
                "INSERT INTO question_types (name, subtype, scoring_mode) "
                "VALUES (?, ?, 'llm')", (name, subtype))
            conn.commit()
            return cur.lastrowid

        added, errors, ids = 0, [], []
        skipped_dup = 0
        # 库级去重：同一份卷子重复导入不会产生副本。
        # 口径与内存去重一致（归一化 + 前缀匹配），这样重复跑导入不会翻倍。
        existing_keys: list[str] = []
        if not dry_run:
            try:
                rows = conn.execute(
                    "SELECT q.content FROM questions q "
                    "JOIN subjects s ON q.subject_id = s.subject_id "
                    "WHERE s.code = ?", (subject,)).fetchall()
                existing_keys = [self._dedupe_key(r[0]) for r in rows if r[0]]
            except Exception:  # noqa: BLE001 - 去重失败不阻断入库
                existing_keys = []

        def _is_dup(k: str) -> bool:
            min_len = self._DEDUPE_MIN_LEN
            for exist in existing_keys:
                short, long_ = (k, exist) if len(k) <= len(exist) else (exist, k)
                if len(short) >= min_len and long_.startswith(short):
                    return True
            return False

        for q in questions:
            content = (q.get("content") or "").strip()
            if not content:
                continue
            k = self._dedupe_key(content)
            if not dry_run and _is_dup(k):
                skipped_dup += 1
                continue
            existing_keys.append(k)
            if dry_run:
                added += 1
                continue
            try:
                qid = self._store.create_question({
                    "subject_id": subject_id,
                    "type_id": _type_id(q.get("type_name") or "解答题",
                                        q.get("subtype") or ""),
                    "source": source,
                    "difficulty": int(q.get("difficulty") or 3),
                    "content": content,
                    "options": q.get("options") or [],
                    "answer": q.get("answer") or "",
                    "explanation": q.get("explanation") or "",
                    "tags": q.get("tags") or [],
                    "knowledge_points": q.get("knowledge_points") or [],
                    "metadata": {**meta, "number": str(q.get("number") or ""),
                                 "page": q.get("_page", 0)},
                })
                added += 1
                ids.append(qid)
            except Exception as e:  # noqa: BLE001
                errors.append(str(e))

        return {"success": True, "questions_added": added,
                "question_ids": ids, "errors": errors, "dry_run": dry_run,
                "skipped_duplicates": skipped_dup}

    # ─────────────────────────────────────────────────────────────
    # 7. PDF
    # ─────────────────────────────────────────────────────────────
    @staticmethod
    def _jpeg_info(data: bytes) -> tuple[int, int, int]:
        """从 JPEG 的 SOF 标记里读 (宽, 高, 组件数)。

        不依赖 PIL —— 这台机器上 Pillow 的 JPEG 编码器与系统 libjpeg 版本
        不匹配（encoder error -2），而且站点下发的 JPEG 数据流是截断的，
        交给 PIL 重新编码只会更糟。直接解析字节最稳。
        """
        i = 2
        n = len(data)
        while i + 9 < n:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            if marker == 0xD9 or marker == 0xDA:      # EOI / SOS
                break
            seg_len = int.from_bytes(data[i + 2:i + 4], "big")
            # SOF0..SOF15，排除 DHT(C4)/JPG(C8)/DAC(CC)
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                          0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                height = int.from_bytes(data[i + 5:i + 7], "big")
                width = int.from_bytes(data[i + 7:i + 9], "big")
                comps = data[i + 9]
                return width, height, comps
            i += 2 + seg_len
        raise ValueError("不是有效的 JPEG（找不到 SOF 标记）")

    #: 常用纸张尺寸（PDF 点，1pt = 1/72 英寸）
    PAGE_SIZES = {
        "A4": (595.28, 841.89),
        "A3": (841.89, 1190.55),
        "Letter": (612.0, 792.0),
    }

    @staticmethod
    def build_pdf(files: list[str], out_path: str, page_size: str = "",
                  margin_pt: float = 14.17) -> dict:
        """把一组 JPEG 拼成一份多页 PDF。

        直接把原始 JPEG 字节以 DCTDecode 嵌进 PDF，不重新编码：
          * 绕开本机 Pillow 那个坏掉的 JPEG 编码器；
          * 站点下发的 JPEG 数据流是截断的，原样嵌入最不容易崩；
          * 无损，速度快。

        :param page_size: 页面尺寸。
            ``""``（默认）= **用图片原始像素当页面尺寸**（历史行为：
            扫描件 1654×2339 → 就是一个 58×82cm 的巨页）；
            ``"A4"`` = 统一 A4 纵向，图片**等比缩放居中**，四周留
            ``margin_pt``（默认 5mm）。
            ⚠️ **要打印就必须用 A4**：双面「长边翻转」只有在所有页面
            尺寸一致时才配得齐，原始尺寸的巨页会让正反面错位。
        """
        if not files:
            return {"success": False, "error": "没有图片"}
        try:
            pw = ph = 0.0
            if page_size:
                key = page_size.strip().upper()
                if key not in PaperImporter.PAGE_SIZES:
                    return {"success": False,
                            "error": "不支持的页面尺寸: %s" % page_size}
                pw, ph = PaperImporter.PAGE_SIZES[key]

            objects: list[bytes] = []       # objects[0] 是 1 号对象

            def add(body: bytes) -> int:
                objects.append(body)
                return len(objects)          # 对象号从 1 开始

            # 预留：1=Catalog 2=Pages；其余按顺序追加
            objects.append(b"")              # 1
            objects.append(b"")              # 2

            page_ids: list[int] = []
            for path in files:
                with open(path, "rb") as fh:
                    blob = fh.read()
                width, height, comps = PaperImporter._jpeg_info(blob)
                color = "/DeviceGray" if comps == 1 else "/DeviceRGB"

                if pw:
                    # 等比缩放到页面内（留 margin），居中
                    avail_w = max(1.0, pw - 2 * margin_pt)
                    avail_h = max(1.0, ph - 2 * margin_pt)
                    scale = min(avail_w / width, avail_h / height)
                    dw, dh = width * scale, height * scale
                    tx, ty = (pw - dw) / 2.0, (ph - dh) / 2.0
                    box_w, box_h = pw, ph
                    content = (f"q {dw:.3f} 0 0 {dh:.3f} {tx:.3f} {ty:.3f} cm "
                               f"/Im0 Do Q").encode()
                else:
                    box_w, box_h = width, height
                    content = (f"q {width} 0 0 {height} 0 0 cm /Im0 Do Q").encode()

                img_id = add(
                    b"<< /Type /XObject /Subtype /Image /Width %d /Height %d "
                    b"/ColorSpace %s /BitsPerComponent 8 /Filter /DCTDecode "
                    b"/Length %d >>\nstream\n"
                    % (width, height, color.encode(), len(blob))
                    + blob + b"\nendstream"
                )
                content_id = add(
                    b"<< /Length %d >>\nstream\n" % len(content) + content
                    + b"\nendstream"
                )
                page_id = add(
                    b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.2f %.2f] "
                    b"/Resources << /XObject << /Im0 %d 0 R >> >> "
                    b"/Contents %d 0 R >>" % (box_w, box_h, img_id, content_id)
                )
                page_ids.append(page_id)

            kids = b" ".join(b"%d 0 R" % pid for pid in page_ids)
            objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
            objects[1] = (b"<< /Type /Pages /Kids [" + kids
                          + b"] /Count %d >>" % len(page_ids))

            # 序列化 + xref
            out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
            offsets = [0] * (len(objects) + 1)
            for idx, body in enumerate(objects, start=1):
                offsets[idx] = len(out)
                out += b"%d 0 obj\n" % idx + body + b"\nendobj\n"

            xref_pos = len(out)
            n = len(objects) + 1
            out += b"xref\n0 %d\n" % n
            out += b"0000000000 65535 f \n"
            for idx in range(1, n):
                out += b"%010d 00000 n \n" % offsets[idx]
            out += (b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
                    % (n, xref_pos))

            os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
            with open(out_path, "wb") as fh:
                fh.write(bytes(out))
            return {"success": True, "path": out_path, "pages": len(page_ids),
                    "page_size": page_size or "auto",
                    "bytes": len(out)}
        except Exception as e:  # noqa: BLE001
            logger.exception("生成 PDF 失败")
            return {"success": False, "error": f"生成 PDF 失败: {e}"}

    # ─────────────────────────────────────────────────────────────
    # 8. 一站式入口
    # ─────────────────────────────────────────────────────────────
    def import_paper(self, paper_id: int = 0, keyword: str = "",
                     subject: str = "physics", max_pages: int = 12,
                     answer_pages: int = 0, dry_run: bool = False,
                     make_pdf: bool = True, user_id: int = 1,
                     title: str = "",
                     progress: Optional[Any] = None) -> dict:
        """一套卷子 → 题库。全流程一次调用完成。

        :param paper_id: 试卷 id；0 表示用 keyword 搜
        :param keyword: 搜索关键词（如「2026 高三 物理 期中」）
        :param subject: 学科代码
        :param max_pages: 最多处理多少页试题
        :param answer_pages: 额外 OCR 多少页答案页用于对答案（0=不对答案）
        :param dry_run: 只抽题不入库
        :param make_pdf: 是否生成试卷/答案 PDF
        :param progress: OCR 进度回调 (done, total, name)
        """
        t0 = time.time()
        report: dict[str, Any] = {"success": False, "steps": {}}

        # ① 定位
        paper = self.resolve_paper(paper_id=paper_id, keyword=keyword)
        if not paper.get("success"):
            return {"success": False, "error": paper.get("error"),
                    "steps": {"resolve": paper}}
        pid = paper["paper_id"]
        report["paper"] = {"id": pid, "title": paper.get("title", ""),
                           "url": paper.get("url", "")}
        report["steps"]["resolve"] = paper

        # ② 下载
        dl = self.download(pid)
        if not dl.get("success"):
            return {"success": False, "error": dl.get("error"),
                    "steps": {"download": dl}, "paper": report["paper"]}
        report["steps"]["download"] = {"dir": dl["dir"], "count": dl["count"]}

        q_files = dl["question_files"]
        a_files = dl["answer_files"]

        # ③ OCR 试题区 —— 顺序扫，**一旦认出答案页就停**。
        #    注意顺序很关键：边界判定必须看到边界那一页，所以不能先按
        #    max_pages 截断 —— 早先的版本正是在这里把「第一页答案」裁掉了，
        #    导致边界算成 2 而不是真实的 9。max_pages 只用来限制**抽题**工作量。
        #
        #    OCR 走本地 VLM：这里借一次租约，**按需拉起**就发生在这一刻；
        #    整个 OCR 阶段共用这一份租约（每页单独借还没有额外开销，但语义
        #    上更清楚：这段推理全程由同一个本地服务完成）。
        from apps.dsn_study.models.vlm_service import vlm_lease

        try:
            with vlm_lease() as lease:
                self._vlm_lease = lease
                try:
                    q_pages, bound = self._ocr_until_boundary(q_files,
                                                             progress=progress)
                    b = bound["boundary"]
                    question_pages = q_pages[:b] if b < len(q_pages) else q_pages
                    # 被站点误标成 question 的答案页（位于边界之后）+ 站点标对的答案页
                    misfiled = q_pages[b:] if b < len(q_pages) else []
                    answer_pages_all = misfiled + self.ocr_pages(a_files)
                finally:
                    self._vlm_lease = None
        except Exception as e:  # noqa: BLE001
            return {"success": False,
                    "error": f"本地 OCR 不可用：{e}",
                    "steps": report["steps"], "paper": report["paper"]}

        report["steps"]["boundary"] = bound
        report["steps"]["ocr"] = {
            "engine": "local-vlm",
            "question_area_ocr": len(q_pages),
            "question_pages": len(question_pages),
            "answer_pages": len(answer_pages_all),
            "misfiled_as_question": len(misfiled),
        }

        if not question_pages:
            return {"success": False,
                    "error": "边界判定把全部页面都判成了答案页，请检查 OCR 结果",
                    "steps": report["steps"], "paper": report["paper"]}

        # ⑤ 抽题（只处理前 max_pages 页试题，省掉后面没必要的 LLM 调用）
        extract_targets = question_pages[:max_pages] if max_pages else question_pages
        questions, q_errors = self.extract_questions(extract_targets, subject=subject)
        report["steps"]["extract"] = {
            "questions_found": len(questions), "errors": q_errors[:10],
            "pages_extracted": len(extract_targets),
            "pages_skipped": len(question_pages) - len(extract_targets)}

        # ⑥ 对答案
        answer_key: dict[str, str] = {}
        if answer_pages > 0 and answer_pages_all:
            sel = answer_pages_all[:answer_pages]
            answer_key = self.extract_answer_key(sel)
            filled = 0
            for q in questions:
                num = str(q.get("number") or "").strip()
                if num and num in answer_key and not q.get("answer"):
                    q["answer"] = answer_key[num]
                    filled += 1
            report["steps"]["answer_key"] = {
                "pages_used": len(sel), "entries": len(answer_key),
                "matched_to_questions": filled}

        # ⑦ 入库
        cm = self.commit(questions, subject=subject, user_id=user_id,
                         dry_run=dry_run,
                         metadata={
                             "paper_id": pid,
                             "paper_title": paper.get("title", ""),
                             "paper_url": paper.get("url", ""),
                         })
        report["steps"]["commit"] = cm

        # ⑧ PDF
        if make_pdf:
            out_dir = os.path.join(self._workspace_dir(), "papers")
            safe = re.sub(r"[^\w一-鿿-]+", "_",
                           (title or paper.get("title") or f"paper_{pid}"))[:60]
            pdfs = {}
            if question_pages:
                pdfs["question"] = self.build_pdf(
                    [p["file"] for p in question_pages],
                    os.path.join(out_dir, f"{safe}_试卷.pdf"))
            if answer_pages_all:
                pdfs["answer"] = self.build_pdf(
                    [p["file"] for p in answer_pages_all],
                    os.path.join(out_dir, f"{safe}_答案.pdf"))
            report["steps"]["pdf"] = pdfs

        report["success"] = bool(cm.get("success"))
        report["questions_found"] = len(questions)
        report["questions_added"] = cm.get("questions_added", 0)
        report["dry_run"] = dry_run
        report["elapsed_sec"] = round(time.time() - t0, 1)
        # 预演时带上题目预览，方便人工核对抽取质量
        if dry_run:
            report["questions_preview"] = [
                {k: q.get(k) for k in
                 ("number", "type_name", "subtype", "difficulty", "answer",
                  "content", "options", "knowledge_points")}
                for q in questions[:60]
            ]
        report["paper"] = report["paper"]
        return report
