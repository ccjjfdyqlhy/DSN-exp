# apps/dsn_study/skills/builtin/gaokzx/tools/gaokzx_tools.py
# 高考在线（gaokzx.com）试题 / 答案抓取工具。
#
# ── 站点逆向结论（实测确认；要改解析逻辑前请先复测，别凭猜）────────────
#
# 1) 站点是 Nuxt SSR，前端调的是**同源 JSON API**，base = https://www.gaokzx.com/api
#
# 2) **必须带请求头 sourceType: GAOKZX**。
#    不带这个头，API 会返回「自主选拔在线(zizzs)」站的数据，文章 id 完全对不上
#    （实测 id=160690 在两个站是不同文章）。所有请求都带 sourceType + 桌面 UA + Referer。
#
# 3) 文章详情（GET）
#    GET /api/informationManagement/app/info?id=<articleId>
#    → {"code":200,"data":{...}}
#    data 关键字段：
#      title        标题
#      content      正文 HTML，里面用 `<!-- pagebreak -->` 把正文切成若干「页」
#                   （前端就是 split 这个标记做分页），**每个分页通常含 1 张扫描图**
#      contentModule 附件列表，元素形如
#                   {"fileName":"2026北京一七一中初一（上）期中数学   无答案.pdf",
#                    "fileUrl":"https://cdn.gaokzx.com/..."}
#                   —— 可下载的 PDF（试题/答案打包版），fileName 里带「有答案」「无答案」
#      releaseTime / columnClassIds / pagePath / oldUrl
#    正文里的扫描图 CDN 文件名形如
#      _1794026731565_2026北京一七一中初一（上）期中数学   无答案_011794026730815.png
#    —— 中间那段是卷名，**「无答案」/「有答案」就写在这里**，是判别试题图/答案图的第一信号。
#
# 4) 关键字搜索（POST，JSON body）
#    POST /api/informationManagement/app/pageSearch
#    body: {"searchName":"<关键词>","searchType":0,"type":2,"pageNum":1,"pageSize":20}
#    → data.records / data.total
#    - 参数名必须是 searchName / searchType：实测 title / keyword / titleLike 一律无效。
#    - type=2 只要「试题」类文章；不传会混入资讯文章。
#    - 匹配是模糊的（近似 OR），返回里会混进不相关的文章，所以调用方必须自己按标题相似度筛。
#
# 5) 按栏目浏览（POST，JSON body）
#    POST /api/informationManagement/app/page
#    body: {"columnId":314,"type":2,"pageNum":1,"pageSize":20}
#    - columnId 必须是 **int**：传字符串 "314" 会被忽略（实测）。
#      314=试题库（type=2 时 total≈28441）、139=高考真题、145=期中期末
#    - 同为 data.records + data.total；columnClassId 无效。
#
# 6) 文章 URL
#    搜索结果里的 pagePath 是 "/gk/shitiku" 这种路径 → https://www.gaokzx.com/gk/shitiku/161882.html
#    详情接口里的 pagePath 往往是栏目 id（"314"），这时要从 columnClassIds 还原；
#    老文章（如 2019 年的）真实路径在 oldUrl（"/c/201910"）里。
#
# 7) 试题图 / 答案图的判别（多信号，见 _classify_image）：
#    ① 文件名关键词：无答案 → 试题图；有答案 / 文件名以「答案」结尾 → 含答案的扫描集
#    ② 正文该分页前后文字出现「参考答案 / 答案解析 / 评分标准」等 → 答案页
#    ③ 分页位置（答案一般在后半段）
#    实测：抽样 26 篇试题文章，每篇正文里的扫描件**要么全是「无答案」要么全是「有答案」**，
#    不会一篇里两种混排；所以「有答案」= 这一整套扫描件里带答案（答案通常在扫描集后半部分）。
#
# ── 礼貌抓取 ────────────────────────────────────────────────────────────
# 这是别人的站点：每次请求之间 sleep（默认 0.8s，环境变量 GAOKZX_DELAY 可调），
# 网络异常 / 5xx 最多重试 2 次并指数退避，429 尊重 Retry-After。

from __future__ import annotations

import difflib
import html as html_mod
import json
import logging
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote, urlparse

import requests

logger = logging.getLogger("skill.gaokzx")

# ── 站点常量 ────────────────────────────────────────────────────────────
SITE_BASE = "https://www.gaokzx.com"
API_BASE = SITE_BASE + "/api"
INFO_API = API_BASE + "/informationManagement/app/info"          # 文章详情（GET）
SEARCH_API = API_BASE + "/informationManagement/app/pageSearch"  # 关键字搜索（POST）
COLUMN_API = API_BASE + "/informationManagement/app/page"        # 栏目浏览（POST）

COLUMN_QUESTION_BANK = 314   # 试题库（实测 total≈28441）
COLUMN_GAOKAO_REAL = 139     # 高考真题
COLUMN_MIDTERM_FINAL = 145   # 期中期末

# 桌面 Chrome UA —— 站点对移动 UA / 无 UA 的响应不一样
DESKTOP_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")

DEFAULT_TIMEOUT = 20.0   # 单次请求超时（秒），环境变量 GAOKZX_TIMEOUT 可覆盖
DEFAULT_DELAY = 0.8      # 两次请求之间的最小间隔（秒），环境变量 GAOKZX_DELAY 可覆盖
MAX_RETRY = 2            # 失败后最多重试 2 次（合计 3 次尝试）
BODY_CHECK_LIMIT = 5     # find_answer_paper 最多体检几个候选的正文（少打站点）
BACKOFF_BASE = 1.0       # 退避基数：第 n 次重试等 BACKOFF_BASE * 2^n 秒

# 正文分页标记：前端就是 split 这个字符串做分页
PAGEBREAK = "<!-- pagebreak -->"

# 正文里出现这些词，说明该页（或该段）是答案页
ANSWER_TEXT_MARKERS = (
    "参考答案", "答案解析", "答案与解析", "答案及解析", "答案详解",
    "试题答案", "参考答案及评分", "评分标准", "答案与评分",
)
# 「试题及答案」这种整句里也带「答案」，但它不是答案页标记，故单独排除
_QUESTION_PHRASE = "试题及答案"

# 装饰图（二维码 / 加群图 / 打包下载按钮）特征：文件名里带这些词
DECORATION_KEYWORDS = ("打包下载", "备考群", "升学群", "二维码", "扫码", "qrcode")

_IMG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_ATTR_RE = re.compile(r"""([\w:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+))""")
_TAG_RE = re.compile(r"<[^>]+>")
_ID_IN_URL_RE = re.compile(r"/(\d{4,})\.html")   # 文章 URL 形如 .../gk/shitiku/161882.html
_DIGITS_RE = re.compile(r"(\d{4,})")
# 学年标识：'2026-2027学年' 优先，退到单个 4 位年份（'2026年高考'）。
# 找答案文章时必须比对学年 —— 否则"2025-2026学年"的旧卷会被当成
# "2026-2027学年"的配套答案，标题相似度再高也是错的。
_YEAR_RANGE_RE = re.compile(r"(20\d{2})\s*[-—~－至]\s*(20\d{2})")
_YEAR_RE = re.compile(r"(20\d{2})")
# 独立答案文章的标题特征：含「答案」但不含「试题及答案」（后者是「试卷+答案打包」的意思）
_ANSWER_ONLY_TITLE_RE = re.compile(r"(参考答案|答案解析|答案与解析|试题答案|答案)")
_COMBINED_TITLE_RE = re.compile(r"(试题及答案|及答案|含答案|试卷及答案)")
# 高考卷标题里的固定成分：用来把长标题切成可独立匹配的词（见 _keyword_from_title）
_GRAMMAR_RE = re.compile(
    r"(上学期|下学期|第一学期|第二学期|适应性考试|高一年级|高二年级|高三年级|"
    r"初一年级|初二年级|初三年级|一年级|二年级|三年级|四年级|五年级|六年级|"
    r"七年级|八年级|九年级|高一|高二|高三|初一|初二|初三|"
    r"数学|语文|英语|物理|化学|生物|政治|历史|地理|道法|信息技术|"
    r"期中|期末|月考|周考|一模|二模|三模|高考|中考|统考|模拟|联考|"
    r"学年|学期|年级|上|下)"
)

# 标题里要剥掉的噪声词，用于生成搜索关键词
_TITLE_NOISE = (
    "试题及答案", "试卷及答案", "试题及解析", "试题", "试卷", "及答案", "答案",
    "解析", "汇总", "合集", "（含答案）", "(含答案)", "无答案", "有答案",
)


class GaokzxTool:
    """高考在线抓取：搜索 / 解析 / 找答案文章 / 下载试题与答案图。"""

    # 能力声明：harness 按能力名注入实例属性（_workspace = WorkspaceManager）
    needs = {"workspace": "_workspace"}

    def __init__(self):
        self._workspace = None
        self._session = None
        self._last_request_at = 0.0

    # ══════════════════════════════════════════════════════════════════
    # 对外工具方法
    # ══════════════════════════════════════════════════════════════════

    def search_papers(self, keyword: str, page: int = 1,
                      page_size: int = 20) -> dict:
        """按关键词搜索试题文章。

        :param keyword: 搜索关键词，如「一七一中 初一 数学 期中」
        :param page: 页码，从 1 开始
        :param page_size: 每页条数，默认 20
        :return: {success, keyword, total, page, page_size, papers:[...]}
        """
        try:
            keyword = str(keyword or "").strip()
            if not keyword:
                return {"success": False, "error": "关键词不能为空"}

            page = max(1, int(page or 1))
            page_size = min(max(1, int(page_size or 20)), 50)  # 上限 50，别把人家打挂

            ok, data, err = self._search(keyword, page, page_size)
            records = list(data.get("records") or []) if ok else []
            total = data.get("total") if ok else 0

            # 搜索接口是模糊匹配，命中 0 时退一步：直接翻「试题库」栏目自己按标题过滤
            if ok and not records:
                fallback = self._column_fallback(keyword)
                if fallback:
                    records = fallback
                    total = len(fallback)
                    logger.info("搜索无结果，改用试题库栏目兜底: %d 条", len(records))

            papers = [self._record_to_paper(r) for r in records]
            return {
                "success": True,
                "keyword": keyword,
                "total": int(total or 0),
                "page": page,
                "page_size": page_size,
                "papers": papers,
                "hint": "搜索是模糊匹配，结果里可能混进不相关文章；"
                        "标题含「试题及答案」通常表示这套卷把答案也包含进来了。",
            }
        except Exception as e:      # 兜底：绝不把异常抛给 AgentLoop
            logger.exception("search_papers 失败")
            return {"success": False, "error": f"搜索失败: {e}"}

    def inspect_paper(self, paper_id: int = 0, url: str = "") -> dict:
        """解析文章详情：分页、试题图/答案图清单、附件 PDF（**不下载图片**）。

        :param paper_id: 文章 id（数字）
        :param url: 文章网页 URL，与 paper_id 至少给一个
        :return: {success, id, title, url, page_count, images, pdfs, summary, ...}
        """
        try:
            pid = self._resolve_paper_id(paper_id, url)
            if not pid:
                return {"success": False,
                        "error": "需要提供 paper_id 或 url（url 形如 "
                                 "https://www.gaokzx.com/gk/shitiku/161882.html）"}

            ok, data, err = self._get_info(pid)
            if not ok:
                return {"success": False, "error": err, "id": pid}

            parsed = self._parse_article(data)
            images = parsed["images"]
            q_cnt = sum(1 for i in images if i["kind"] == "question")
            a_cnt = sum(1 for i in images if i["kind"] == "answer")
            u_cnt = sum(1 for i in images if i["kind"] == "unknown")

            return {
                "success": True,
                "id": pid,
                "title": data.get("title", ""),
                "url": parsed["url"],
                "page_count": parsed["page_count"],
                "images": images,
                "pdfs": parsed["pdfs"],
                "summary": parsed["summary"],
                "release_time": data.get("releaseTime", ""),
                "column": parsed["column"],
                "question_count": q_cnt,
                "answer_count": a_cnt,
                "unknown_count": u_cnt,
                "decorations": parsed["decorations"],
                "scan_set": parsed["scan_set"],
            }
        except Exception as e:
            logger.exception("inspect_paper 失败")
            return {"success": False, "error": f"解析文章失败: {e}"}

    def find_answer_paper(self, paper_id: int = 0, title: str = "") -> dict:
        """给试题文章找配套的答案文章。

        先看本文档自己有没有答案材料（正文「有答案」扫描件 / 答案 PDF），
        没有再用标题派生的关键词去站内搜，按标题相似度 + 「答案特征」挑候选。

        :param paper_id: 试题文章 id（数字），与 title 至少给一个
        :param title: 试题标题（不传 paper_id 时直接给标题也行）
        :return: {success, query, candidates:[...], best:{...}|None, note}
        """
        try:
            src_title = str(title or "").strip()
            src_id = self._resolve_paper_id(paper_id, "")
            src_info = None

            if src_id:
                ok, data, err = self._get_info(src_id)
                if not ok:
                    return {"success": False, "error": err, "id": src_id}
                src_info = data
                src_title = src_title or str(data.get("title", ""))
            if not src_title:
                return {"success": False, "error": "需要提供 paper_id 或 title"}

            # ── 候选来源 1：本文档自带的答案材料 ──
            candidates: list[dict] = []
            if src_info:
                self._collect_self_answer_candidate(src_id, src_info, candidates)

            # ── 候选来源 2：站内搜索（标题派生关键词）──
            query = self._keyword_from_title(src_title)
            seen_ids = {c["id"] for c in candidates}
            if src_id:
                seen_ids.add(src_id)

            src_year = self._academic_year(src_title)
            src_school = self._school_token(src_title)
            records = self._gather_search_records(src_title, query)
            for rec in records:
                rid = self._to_int(rec.get("id"))
                if rid is None or rid in seen_ids:
                    continue
                cand_title = str(rec.get("title", ""))
                score = self._title_similarity(src_title, cand_title)
                reason = f"标题相似度 {score:.2f}"
                # 学年必须对得上：跨学年的旧卷标题相似度很高，
                # 但作为"配套答案"是错的，所以重罚。
                cand_year = self._academic_year(cand_title)
                if src_year and cand_year:
                    if cand_year != src_year:
                        score -= 0.35
                        reason += f"；学年不一致（{src_year} vs {cand_year}）"
                    else:
                        score += 0.08
                        reason += f"；学年一致（{src_year}）"
                elif src_year and not cand_year:
                    score -= 0.05
                    reason += "；候选标题里没有学年信息"
                # 学校名是试卷身份最强的信号：同校 ≫ 隔壁学校
                cand_school = self._school_token(cand_title)
                if src_school and cand_school:
                    if cand_school == src_school:
                        score += 0.15
                        reason += f"；同校（{cand_school}）"
                    else:
                        score -= 0.15
                        reason += f"；学校不同（{cand_school}）"
                if self._is_answer_title(cand_title):
                    score += 0.12
                    reason += "；标题是独立答案文章形态"
                if self._is_combined_title(cand_title):
                    score -= 0.06
                    reason += "；标题为「试题及答案」打包形态（答案可能就在本文内）"
                if "汇总" in cand_title:
                    score -= 0.05
                    reason += "；汇总文章（非单篇试卷）"
                cand = self._record_to_paper(rec)
                candidates.append({
                    "id": cand["id"],
                    "title": cand["title"],
                    "url": cand["url"],
                    "score": round(min(score, 1.0), 3),
                    "reason": reason,
                    "from": "search",
                })
                seen_ids.add(cand["id"])

            # ── 候选来源 3：正文里链接到的答案类文章 ──
            if src_info:
                self._collect_link_answer_candidates(src_id, src_info, candidates)

            candidates.sort(key=lambda c: c.get("score", 0.0), reverse=True)
            top = candidates[:8]

            # 正文里有答案图的候选加分（正文里答案图多 → 更可能是答案文章）。
            # 只体检前几个候选，别为了打分把人家站点翻个底朝天。
            for cand in top[:BODY_CHECK_LIMIT]:
                if cand.get("from") == "search" and cand["score"] >= 0.5:
                    self._boost_by_body(cand)
            candidates.sort(key=lambda c: c.get("score", 0.0), reverse=True)
            top = candidates[:8]

            best = None
            if top:
                cand = top[0]
                if cand.get("is_answer"):
                    best = cand
                    if cand["score"] < 0.5:
                        cand["note"] = "相似度偏低，仅作参考"
                else:
                    # 相似但不是答案文章 —— 只标记，不给 best（不瞎猜）
                    cand["nearest"] = True

            note = ""
            if best is None:
                note = ("没有找到可信的独立答案文章。"
                        "多数文章的答案就放在本文的「有答案」扫描件或附件 PDF 里，"
                        "请先看 inspect_paper 返回的 pdfs / scan_set；"
                        "确实需要另一篇时，可拿关键词自行 search_papers 再核对。")
            else:
                note = f"最佳候选：{best['title']}（{best['reason']}）"

            return {
                "success": True,
                "query": query,
                "source_id": src_id,
                "source_title": src_title,
                "candidates": top,
                "best": best,
                "note": note,
            }
        except Exception as e:
            logger.exception("find_answer_paper 失败")
            return {"success": False, "error": f"查找答案文章失败: {e}"}

    # ══════════════════════════════════════════════════════════════
    # 批量：并发下载 + 快速分界判定
    # ══════════════════════════════════════════════════════════════

    @staticmethod
    def create() -> "GaokzxTool":
        """造一个**带工作区**的工具实例。

        不带工作区时图片会落到临时目录（``/tmp/dsn_gaokzx/...``），
        与 app 的工作区脱节 —— 脚本/工具直接调用时务必用这个工厂方法。
        """
        tool = GaokzxTool()
        try:
            from apps.dsn_study.config import Config
            from apps.dsn_study.workspace import WorkspaceManager
            tool._workspace = WorkspaceManager(Config.WORKSPACE_DIR)
        except Exception as e:
            logger.warning("工作区不可用（图片将落到临时目录）: %s", e)
        return tool

    def download_bundle(self, papers: list, user_id: int = 1,
                        concurrency: int = 4) -> dict:
        """并发下载多套卷子的图片。

        :param papers: [{"subject": "语文", "paper_id": 161613}, ...]
        :param concurrency: 科目级并发度（默认 4，克制一点别把站点打挂）
        :return: {success, results: [{subject, paper_id, question, answer, dir}], ...}
        """
        from concurrent.futures import ThreadPoolExecutor
        items = []
        for entry in papers or []:
            if isinstance(entry, dict):
                subject = str(entry.get("subject") or entry.get("name") or "")
                pid = entry.get("paper_id") or entry.get("id") or 0
            else:
                subject, pid = "", entry
            pid = int(pid or 0)
            if not pid:
                continue
            items.append((subject, pid))
        if not items:
            return {"success": False, "error": "没有可下载的卷子"}

        results = []

        def _one(subject, pid):
            q = self.download_images(pid, kind="question", user_id=user_id)
            a = self.download_images(pid, kind="answer", user_id=user_id)
            return {"subject": subject, "paper_id": pid,
                    "question": {"ok": q.get("success"),
                                 "saved": len(q.get("saved") or []),
                                 "failed": len(q.get("failed") or []),
                                 "dir": q.get("dir")},
                    "answer": {"ok": a.get("success"),
                               "saved": len(a.get("saved") or []),
                               "failed": len(a.get("failed") or []),
                               "dir": a.get("dir")},
                    "note": q.get("note") or a.get("note") or ""}

        with ThreadPoolExecutor(max_workers=min(max(1, concurrency), len(items))) as ex:
            futs = [ex.submit(_one, subj, pid) for subj, pid in items]
            for fut in futs:
                try:
                    results.append(fut.result())
                except Exception as exc:
                    logger.warning("下载失败: %s", exc)
        return {"success": True, "results": results,
                "total_images": sum((r["question"]["saved"] + r["answer"]["saved"])
                                    for r in results)}

    def classify_papers(self, papers: list, user_id: int = 1,
                        use_vision: bool = True, cache_path: str = None,
                        concurrency: int = 6, max_inflight: int = 3,
                        workers: int = 4) -> dict:
        """判定每套卷子的「试题 / 答案」分界。

        比逐页判定快得多：
          * 二分定位分界（O(log n) 次模型调用）
          * 科目级并行
          * 送模型前缩图 + 只要一个字的输出
          * 按图片内容哈希缓存，重复处理直接命中

        :param papers: [{"subject": "语文", "paper_id": 161613}, ...]
        :param use_vision: False = 不调模型，用站点自带的位置启发式（快但不准）
        :param cache_path: 判定缓存路径
        :return: {success, results: [{subject, paper_id, boundary, mode, ...}]}
        """
        from .page_classifier import PageClassifier

        items = []
        for entry in papers or []:
            if isinstance(entry, dict):
                subject = str(entry.get("subject") or entry.get("name") or "")
                pid = int(entry.get("paper_id") or entry.get("id") or 0)
            else:
                subject, pid = "", int(entry or 0)
            if pid:
                items.append((subject, pid))
        if not items:
            return {"success": False, "error": "没有待判定的卷子"}

        paths: dict[str, list[str]] = {}
        for subject, pid in items:
            out_dir, _ = self._target_dir(user_id, pid)
            # ⚠️ **必须按文档顺序**排：question_* 在前、answer_* 在后。
            # 直接 sorted(glob) 会把 answer_* 排到前面（字母序），
            # 于是二分拿到的是**乱序**页面 → 分界点算出来是错的。
            q = sorted(str(p) for p in out_dir.glob("question_*.jpg"))
            a = sorted(str(p) for p in out_dir.glob("answer_*.jpg"))
            files = q + a
            if files:
                paths[f"{subject}|{pid}"] = files

        if not use_vision:
            # 位置启发式（站点侧同款逻辑）：只快，不准
            out = []
            for subject, pid in items:
                key = f"{subject}|{pid}"
                files = paths.get(key, [])
                n = len(files)
                boundary = int(n * 0.6) if n else 0
                out.append({"subject": subject, "paper_id": pid,
                            "total_pages": n, "boundary": boundary,
                            "mode": "heuristic", "monotone": True})
            return {"success": True, "results": out, "stats": {"模型调用": 0}}

        ask_fn = self._vision_ask()
        if ask_fn is None:
            return {"success": False,
                    "error": "视觉模型不可用（无法判定题/答分界）"}

        clf = PageClassifier(ask_fn, concurrency=concurrency,
                             cache_path=cache_path,
                             max_inflight=max_inflight, workers=workers)
        res = clf.classify_bundle(paths)
        out = []
        for subject, pid in items:
            key = f"{subject}|{pid}"
            r = res.get(key) or {}
            files = paths.get(key, [])
            out.append({"subject": subject, "paper_id": pid,
                        "total_pages": len(files),
                        "boundary": r.get("boundary", 0),
                        "mode": r.get("mode", "?"),
                        "monotone": r.get("monotone", True)})
        return {"success": True, "results": out, "stats": clf.stats()}

    def _vision_ask(self):
        """视觉判定入口（app 的 VisionModel）。拿不到就返回 None。"""
        try:
            from apps.dsn_study.models.clients import VisionModel
            # 超时给短一点：厂商侧排队时快失败好过卡 120 秒
            vm = VisionModel(timeout=30)

            def _ask(data_url: str, prompt: str) -> str:
                return vm.ask(data_url, prompt, max_tokens=8, temperature=0.0)
            return _ask
        except Exception as exc:
            logger.warning("视觉模型不可用: %s", exc)
            return None

    def download_images(self, paper_id: int, kind: str = "question",
                        user_id: int = 0, max_images: int = 0) -> dict:
        """下载文章里的试题图 / 答案图到工作区。

        :param paper_id: 文章 id（数字，或直接给文章 URL 字符串也行）
        :param kind: question=只要试题图 / answer=只要答案图 / all=全都要
        :param user_id: 用户 id，默认 1
        :param max_images: 最多下载几张，0=不限
        :return: {success, saved, skipped, count, dir, ...}
        """
        try:
            pid = self._resolve_paper_id(paper_id, "")
            if not pid:
                return {"success": False, "error": "需要提供 paper_id"}

            kind = (kind or "question").strip().lower()
            if kind not in ("question", "answer", "all"):
                return {"success": False,
                        "error": f"kind 只能是 question / answer / all，收到 {kind!r}"}

            ok, data, err = self._get_info(pid)
            if not ok:
                return {"success": False, "error": err, "id": pid}

            parsed = self._parse_article(data)
            images = parsed["images"]
            if kind == "all":
                wanted = [i for i in images if i["kind"] != "unknown"]
                wanted += [i for i in images if i["kind"] == "unknown"]
            else:
                wanted = [i for i in images if i["kind"] == kind]

            note = ""
            kind_fallback = False
            if not wanted and kind == "question" and parsed["scan_set"] == "with_answers":
                # 这套扫描件把**试题和答案一起**扫了进去（文件名带「有答案」），
                # 站点没有分页级拆分信息，所以整包记为 answer。
                # 用户要"试题图片"时，给 0 张等于什么都没干 —— 这里回退成
                # 下这套扫描件（里面本来就有试题页），并在 note 里说清楚。
                wanted = [i for i in images if i["kind"] == "answer"]
                kind_fallback = bool(wanted)
                if kind_fallback:
                    note = ("本文是「有答案」版本：试题页和答案页在**同一套**扫描件里，"
                            "站点未提供分页级拆分，这里按整包下载（文件名仍记为 answer）。"
                            "若要纯试题页，请找同系列的「无答案」文章。")
            if not wanted:
                note = note or (
                    f"该文章没有标记为 {kind} 的图片。"
                    f"（共 {len(images)} 张扫描图："
                    f"试题 {parsed['question_count']} / 答案 {parsed['answer_count']}"
                    f" / 未知 {parsed['unknown_count']}）")
                if parsed["scan_set"] == "with_answers" and kind == "question":
                    note += " 本文是「有答案」版本，整套扫描件统一记为 answer；" \
                            "如需纯试题，请找同系列的「无答案」文章。"

            try:
                max_images = int(max_images or 0)
            except (TypeError, ValueError):
                max_images = 0
            truncated = 0
            if max_images > 0 and len(wanted) > max_images:
                truncated = len(wanted) - max_images
                wanted = wanted[:max_images]

            out_dir, fallback = self._target_dir(user_id, pid)
            out_dir.mkdir(parents=True, exist_ok=True)
            manifest = self._read_manifest(out_dir)

            saved, skipped, failed = [], [], []
            counters: dict[str, int] = {}
            for img in wanted:
                img_kind = img["kind"] if img["kind"] in ("question", "answer") else "unknown"
                counters[img_kind] = counters.get(img_kind, 0) + 1
                fname = f"{img_kind}_{counters[img_kind]:02d}{self._ext_of(img['url'])}"
                target = out_dir / fname

                # 幂等：manifest 记着同一 URL 且本地文件大小一致 → 跳过
                rec = manifest.get(img["url"]) or {}
                if target.exists() and rec.get("file") == fname and \
                        target.stat().st_size == rec.get("bytes"):
                    skipped.append({"path": str(target), "url": img["url"],
                                    "kind": img_kind, "bytes": rec.get("bytes", 0),
                                    "reason": "已存在且大小一致"})
                    continue

                ok2, blob, err2 = self._request("GET", img["url"], binary=True,
                                                timeout=60)
                if not ok2:
                    failed.append({"url": img["url"], "error": err2})
                    continue

                # 下载完发现本地已有同样大小的文件 → 不重复写盘
                if target.exists() and target.stat().st_size == len(blob):
                    skipped.append({"path": str(target), "url": img["url"],
                                    "kind": img_kind, "bytes": len(blob),
                                    "reason": "已存在且大小一致"})
                    manifest[img["url"]] = {"file": fname, "bytes": len(blob)}
                    continue

                try:
                    target.write_bytes(blob)
                except OSError as e:
                    failed.append({"url": img["url"], "error": f"写盘失败: {e}"})
                    continue

                manifest[img["url"]] = {"file": fname, "bytes": len(blob)}
                saved.append({"path": str(target), "url": img["url"],
                              "kind": img_kind, "bytes": len(blob),
                              "page": img.get("page")})

            self._write_manifest(out_dir, manifest)

            logger.info("download_images: id=%s kind=%s 保存 %d 跳过 %d 失败 %d",
                        pid, kind, len(saved), len(skipped), len(failed))
            return {
                "success": True,
                "id": pid,
                "title": data.get("title", ""),
                "kind": kind,
                "dir": str(out_dir),
                "count": len(saved),
                "saved": saved,
                "skipped": skipped,
                "failed": failed,
                "total_matched": len(images),
                "workspace_fallback": fallback,
                "kind_fallback": kind_fallback,
                "note": note,
            }
        except Exception as e:
            logger.exception("download_images 失败")
            return {"success": False, "error": f"下载失败: {e}"}

    # ══════════════════════════════════════════════════════════════════
    # HTTP 层：统一 session + 限速 + 重试
    # ══════════════════════════════════════════════════════════════════

    @staticmethod
    def _user_agent() -> str:
        """UA：默认桌面 Chrome，可用 skill.env / 环境变量 GAOKZX_USER_AGENT 覆盖。"""
        return os.environ.get("GAOKZX_USER_AGENT") or DESKTOP_UA

    @staticmethod
    def _timeout() -> float:
        """单次请求超时（秒）：默认 20，可用 GAOKZX_TIMEOUT 覆盖。"""
        try:
            val = float(os.environ.get("GAOKZX_TIMEOUT", DEFAULT_TIMEOUT))
        except (TypeError, ValueError):
            val = DEFAULT_TIMEOUT
        return val if val > 0 else DEFAULT_TIMEOUT

    def _ensure_session(self) -> requests.Session:
        if self._session is None:
            s = requests.Session()
            s.headers.update({
                # 关键：不带这个头会拿到「自主选拔在线」站的数据，文章 id 对不上
                "sourceType": "GAOKZX",
                "User-Agent": self._user_agent(),
                "Referer": SITE_BASE + "/",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9",
            })
            self._session = s
            logger.info("gaokzx session 已就绪")
        return self._session

    @staticmethod
    def _delay() -> float:
        """请求间隔（秒），环境变量 GAOKZX_DELAY 可覆盖。"""
        try:
            val = float(os.environ.get("GAOKZX_DELAY", DEFAULT_DELAY))
        except (TypeError, ValueError):
            val = DEFAULT_DELAY
        return max(0.0, val)

    def _throttle(self) -> None:
        """保证两次请求之间至少间隔 _delay() 秒。"""
        gap = self._delay()
        if gap <= 0:
            return
        elapsed = time.time() - self._last_request_at
        if self._last_request_at and elapsed < gap:
            time.sleep(gap - elapsed)
        self._last_request_at = time.time()

    def _request(self, method: str, url: str, *, params: Optional[dict] = None,
                 json_body: Optional[dict] = None, binary: bool = False,
                 timeout: Optional[float] = None) -> tuple[bool, Any, str]:
        """统一的 HTTP 入口：限速 + 重试 + 退避。

        :return: (ok, data, err) —— data 在 binary=True 时是 bytes，否则是 dict
        """
        session = self._ensure_session()
        timeout = float(timeout or self._timeout())
        last_err = ""

        for attempt in range(MAX_RETRY + 1):
            self._throttle()
            try:
                resp = session.request(method, url, params=params, json=json_body,
                                       timeout=timeout)
            except requests.RequestException as e:
                last_err = f"网络异常: {e}"
                logger.warning("gaokzx 请求失败(%s/%s): %s", attempt + 1,
                               MAX_RETRY + 1, e)
                if attempt < MAX_RETRY:
                    time.sleep(BACKOFF_BASE * (2 ** attempt))
                continue

            code = resp.status_code

            # 429：尊重 Retry-After
            if code == 429:
                retry_after = resp.headers.get("Retry-After", "")
                wait = 0.0
                try:
                    wait = float(retry_after)
                except (TypeError, ValueError):
                    wait = float(BACKOFF_BASE * (2 ** attempt))
                last_err = "被限流（HTTP 429）"
                logger.warning("gaokzx 被限流，等待 %.1fs", wait)
                if attempt < MAX_RETRY:
                    time.sleep(min(wait, 30.0))
                    continue
                break

            # 5xx：服务端错误，退避重试
            if 500 <= code < 600:
                last_err = f"服务端错误 HTTP {code}"
                logger.warning("gaokzx %s，%s", last_err, url)
                if attempt < MAX_RETRY:
                    time.sleep(BACKOFF_BASE * (2 ** attempt))
                    continue
                break

            if code >= 400:
                return False, None, f"HTTP {code}"

            if binary:
                return True, resp.content, ""

            try:
                payload = resp.json()
            except ValueError:
                return False, None, "响应不是合法 JSON"

            # 接口业务码（实测正常是 200）
            biz = payload.get("code")
            if biz is not None and str(biz) != "200":
                msg = payload.get("msg") or payload.get("message") or ""
                return False, None, f"接口返回 code={biz} {msg}".strip()
            return True, payload, ""

        return False, None, last_err or "请求失败"

    def _get_info(self, paper_id: int) -> tuple[bool, dict, str]:
        """文章详情。"""
        ok, payload, err = self._request("GET", INFO_API, params={"id": paper_id})
        if not ok:
            return False, {}, err
        data = payload.get("data")
        if not isinstance(data, dict):
            return False, {}, "详情接口没有返回 data"
        return True, data, ""

    def _search(self, keyword: str, page: int = 1,
                page_size: int = 20) -> tuple[bool, dict, str]:
        """关键字搜索（POST）。参数名只能是 searchName / searchType。"""
        body = {
            "searchName": keyword,
            "searchType": 0,
            "type": 2,          # 只要「试题」类文章，不传会混入资讯
            "pageNum": page,
            "pageSize": page_size,
        }
        ok, payload, err = self._request("POST", SEARCH_API, json_body=body)
        if not ok:
            return False, {}, err
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            return False, {}, "搜索接口没有返回 data"
        return True, data, ""

    def _browse_column(self, column_id: int, page: int = 1,
                       page_size: int = 20) -> tuple[bool, dict, str]:
        """按栏目浏览（POST）。columnId 必须是 int，传字符串会被忽略。"""
        body = {
            "columnId": int(column_id),
            "type": 2,
            "pageNum": page,
            "pageSize": page_size,
        }
        ok, payload, err = self._request("POST", COLUMN_API, json_body=body)
        if not ok:
            return False, {}, err
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            return False, {}, "栏目接口没有返回 data"
        return True, data, ""

    def _column_fallback(self, keyword: str, max_pages: int = 3) -> list:
        """搜索无命中时的兜底：翻「试题库」栏目，按关键词过滤标题。"""
        tokens = [t for t in re.split(r"[\s,，、]+", keyword) if len(t) >= 2]
        hits, seen = [], set()
        for page in range(1, max_pages + 1):
            ok, data, err = self._browse_column(COLUMN_QUESTION_BANK, page, 20)
            if not ok:
                logger.warning("栏目兜底第 %s 页失败: %s", page, err)
                break
            records = data.get("records") or []
            if not records:
                break
            for rec in records:
                title = str(rec.get("title", ""))
                if tokens:
                    hit = all(t in title for t in tokens)
                else:
                    hit = keyword in title
                rid = self._to_int(rec.get("id"))
                if hit and rid is not None and rid not in seen:
                    seen.add(rid)
                    hits.append(rec)
        return hits

    # ══════════════════════════════════════════════════════════════════
    # 解析层
    # ══════════════════════════════════════════════════════════════════

    def _parse_article(self, data: dict) -> dict:
        """把详情接口的 data 解析成图片 / PDF 清单。"""
        content = str(data.get("content") or "")
        pages = content.split(PAGEBREAK) if content else []
        page_texts = [self._html_to_text(p) for p in pages]

        # 答案分页起点：正文里第一次出现「参考答案 / 答案解析」等标题的那一页
        answer_start: Optional[int] = None
        for i, text in enumerate(page_texts):
            if self._has_answer_marker(text):
                answer_start = i
                break

        raw: list[dict] = []
        for pi, chunk in enumerate(pages):
            for tag in _IMG_RE.findall(chunk):
                attrs = self._parse_img_attrs(tag)
                src = (attrs.get("src") or "").strip()
                if not src:
                    continue
                raw.append({
                    "page": pi + 1,
                    "src": src,
                    "attrs": attrs,
                    "text": page_texts[pi],
                })

        # 装饰图（二维码 / 加群图 / 打包下载按钮）单独摘出去，别混进试题图
        content_images, decorations = [], []
        for item in raw:
            fname = self._url_filename(item["src"])
            if self._is_decoration(item, fname):
                decorations.append({
                    "url": item["src"], "page": item["page"], "file_name": fname,
                    "kind_reason": self._decoration_reason(item, fname),
                })
            else:
                content_images.append(item)

        images = []
        for idx, item in enumerate(content_images):
            fname = self._url_filename(item["src"])
            # 位置信号要用「在扫描件序列里的序号」，这里显式传进去
            item["_index"] = idx
            kind, reason, confidence = self._classify_image(
                item, fname, len(content_images), answer_start)
            images.append({
                "index": idx + 1,
                "url": item["src"],
                "kind": kind,
                "kind_reason": reason,
                "confidence": confidence,
                "page": item["page"],
                "file_name": fname,
                "alt": item["attrs"].get("alt", ""),
            })

        pdfs, module_decorations = self._parse_modules(data)
        decorations.extend(module_decorations)

        question_count = sum(1 for i in images if i["kind"] == "question")
        answer_count = sum(1 for i in images if i["kind"] == "answer")
        unknown_count = sum(1 for i in images if i["kind"] == "unknown")

        # 这套卷是「有答案」还是「无答案」版本（看正文扫描件的文件名）
        scan_set = "unknown"
        for img in images:
            if "无答案" in img["file_name"]:
                scan_set = "without_answers"
                break
            if "有答案" in img["file_name"]:
                scan_set = "with_answers"
                break

        url = self._build_url(data.get("id"), data)
        summary = self._build_summary(data, images, pdfs, question_count,
                                      answer_count, unknown_count, scan_set)
        column = self._column_name(data.get("columnClassIds"))

        return {
            "images": images,
            "decorations": decorations,
            "pdfs": pdfs,
            "page_count": len(pages),
            "url": url,
            "summary": summary,
            "column": column,
            "scan_set": scan_set,
            "question_count": question_count,
            "answer_count": answer_count,
            "unknown_count": unknown_count,
        }

    def _parse_modules(self, data: dict) -> tuple[list, list]:
        """解析 contentModule 附件：PDF 归 pdfs，二维码/打包下载按钮归 decorations。"""
        pdfs, decorations = [], []
        for mod in (data.get("contentModule") or []):
            if not isinstance(mod, dict):
                continue
            file_name = str(mod.get("fileName") or "")
            file_url = str(mod.get("fileUrl") or "")
            if not file_url:
                continue
            # 带 qrcode 字段 / 文件名含「打包下载」的是页面上的二维码按钮，不是资料
            if mod.get("qrcode") or any(k in file_name for k in DECORATION_KEYWORDS):
                decorations.append({
                    "url": file_url, "file_name": file_name,
                    "kind_reason": "页面二维码 / 打包下载按钮，非试题资料",
                })
                continue
            kind, reason = self._classify_by_name(file_name)
            pdfs.append({
                "file_name": file_name,
                "url": file_url,
                "kind": kind,
                "kind_reason": reason,
            })
        return pdfs, decorations

    def _classify_image(self, item: dict, fname: str, total: int,
                        answer_start: Optional[int]) -> tuple[str, str, str]:
        """判别一张扫描图是试题图还是答案图（多信号）。

        返回 (kind, kind_reason, confidence)
        """
        page = item["page"]
        text = item.get("text", "")
        marker = self._answer_marker_in(text)

        # ① 文件名信号（最权威）：文件名写明了这一页属于哪一套扫描件
        #    「无答案」= 这一套扫描件根本不含答案 → 试题图
        if "无答案" in fname:
            reason = "文件名含「无答案」（这套扫描件不含答案）"
            if marker:
                reason += f"；本页正文虽出现「{marker}」，但以文件名为准"
            return "question", reason, "high"

        # ② 文件名含「有答案」= 这套扫描件带答案（答案通常在扫描集后半部分）
        if "有答案" in fname or fname.endswith("答案"):
            if answer_start is not None and page < answer_start + 1:
                return ("question",
                        f"文件名含「有答案」，但本页在正文答案段"
                        f"（第 {answer_start + 1} 页）之前，按试题页处理",
                        "medium")
            return "answer", "文件名含「有答案」（这套扫描件含答案）", "medium"

        # ③ 正文文字信号：文件名无线索时，看本页有没有「参考答案 / 答案解析」标题
        if marker:
            return "answer", f"第 {page} 页正文出现「{marker}」标题", "high"

        # ④ 位置信号：没有任何文件名线索时，才用位置兜底
        pos = (item.get("_index", 0) / max(1, total - 1)) if total > 1 else 0.0
        if total >= 4 and pos >= 0.6:
            return "answer", f"文件名无线索，且位于后半部分（第 {page}/{total} 页）", "low"
        if total >= 2:
            return "question", f"文件名无线索，且位于前半部分（第 {page}/{total} 页）", "low"
        return "unknown", "文件名与位置都无线索，无法判定", "low"

    @staticmethod
    def _classify_by_name(name: str) -> tuple[str, str]:
        """只按文件名判别（附件 PDF 用）。"""
        if "无答案" in name:
            return "question", "文件名含「无答案」"
        if "有答案" in name or name.endswith("答案"):
            return "answer", "文件名含「有答案」"
        return "unknown", "文件名无答案相关关键词"

    @staticmethod
    def _has_answer_marker(text: str) -> bool:
        return GaokzxTool._answer_marker_in(text) is not None

    @staticmethod
    def _answer_marker_in(text: str) -> Optional[str]:
        """返回命中的答案标记词；「试题及答案」这种整句不算答案页标记。"""
        if not text:
            return None
        probe = text.replace(_QUESTION_PHRASE, "")
        for marker in ANSWER_TEXT_MARKERS:
            if marker in probe:
                return marker
        return None

    @staticmethod
    def _is_decoration(item: dict, fname: str) -> bool:
        """二维码 / 加群图 / 打包下载按钮 —— 不是试题资料。"""
        if any(k in fname for k in DECORATION_KEYWORDS):
            return True
        attrs = item.get("attrs") or {}
        # 站点正文里的试题扫描图是 width="100%"，二维码是 width="80" height="80"
        try:
            w = int(str(attrs.get("width", "")).strip().rstrip("%"))
            h = int(str(attrs.get("height", "")).strip().rstrip("%"))
            if w > 0 and h > 0 and w <= 200 and h <= 200:
                return True
        except (TypeError, ValueError):
            pass
        return False

    @staticmethod
    def _decoration_reason(item: dict, fname: str) -> str:
        for k in DECORATION_KEYWORDS:
            if k in fname:
                return f"文件名含「{k}」（二维码 / 加群图 / 打包下载按钮）"
        attrs = item.get("attrs") or {}
        return (f"小尺寸图片（width={attrs.get('width', '?')} "
                f"height={attrs.get('height', '?')}），应为二维码 / 装饰图")

    @staticmethod
    def _html_to_text(html: str) -> str:
        """正则去标签（不引 bs4 —— 依赖里没有）。"""
        if not html:
            return ""
        text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
        text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</h\d>|</tr>|</li>|</td>",
                      "\n", text)
        text = _TAG_RE.sub(" ", text)
        text = html_mod.unescape(text)
        text = re.sub(r"[ \t\xa0\u3000]+", " ", text)
        text = re.sub(r"\n{2,}", "\n", text)
        return text.strip()

    @staticmethod
    def _parse_img_attrs(tag: str) -> dict:
        attrs = {}
        for m in _ATTR_RE.finditer(tag):
            name = m.group(1).lower()
            value = m.group(2) or m.group(3) or m.group(4) or ""
            attrs[name] = value
        return attrs

    @staticmethod
    def _url_filename(url: str) -> str:
        """取 URL 里的文件名并把百分号编码还原成中文（用于判别「无答案」等）。"""
        try:
            path = urlparse(url).path
        except ValueError:
            path = url
        return unquote(path.split("/")[-1])

    @staticmethod
    def _ext_of(url: str) -> str:
        """按 URL 推断图片扩展名，认不出就用 .jpg。"""
        name = GaokzxTool._url_filename(url).lower()
        for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif",
                    ".tiff"):
            if name.endswith(ext):
                return ".jpg" if ext == ".jpeg" else ext
        return ".jpg"

    # ══════════════════════════════════════════════════════════════════
    # URL / id / 标题处理
    # ══════════════════════════════════════════════════════════════════

    def _build_url(self, article_id: Any, data: dict) -> str:
        """拼文章网页 URL。

        详情接口里 pagePath 常常是栏目 id（"314"），这时要从 columnClassIds 还原；
        老文章的真实路径在 oldUrl（"/c/201910"）里。
        """
        aid = self._to_int(article_id)
        if aid is None:
            return SITE_BASE

        page_path = str(data.get("pagePath") or "").strip()
        old_url = str(data.get("oldUrl") or "").strip()

        # ① oldUrl：老文章的真实栏目路径，最准
        if old_url.startswith("/"):
            return f"{SITE_BASE}{old_url.rstrip('/')}/{aid}.html"

        # ② pagePath 是真路径时直接用（搜索结果里就是 "/gk/shitiku"）
        if page_path.startswith("/"):
            return f"{SITE_BASE}{page_path.rstrip('/')}/{aid}.html"

        # ③ 从栏目信息还原：firstColumnData 是 "/shitiku"，站点固定加 "/gk" 前缀
        for col in (data.get("columnClassIds") or []):
            if not isinstance(col, dict):
                continue
            seg = str(col.get("firstColumnData") or "").strip()
            if seg.startswith("/gk"):
                return f"{SITE_BASE}{seg.rstrip('/')}/{aid}.html"
            if seg.startswith("/"):
                return f"{SITE_BASE}/gk{seg.rstrip('/')}/{aid}.html"

        # ④ 兜底
        return f"{SITE_BASE}/gk/shitiku/{aid}.html"

    def _record_to_paper(self, rec: dict) -> dict:
        """搜索/栏目结果 → 统一的 paper 结构。"""
        title = str(rec.get("title") or "")
        aid = self._to_int(rec.get("id"))
        url = self._build_url(aid, {
            "pagePath": rec.get("pagePath"),
            "oldUrl": rec.get("oldUrl"),
            "columnClassIds": rec.get("columnClassIds"),
        })
        return {
            "id": aid,
            "title": title,
            "url": url,
            "release_time": str(rec.get("releaseTime") or ""),
            # 标题里有「答案」字样 → 给个提示（注意「试题及答案」也是答案文章）
            "has_answer_hint": "答案" in title,
            "is_answer_only_hint": self._is_answer_title(title),
            "column": self._column_name(rec.get("columnClassIds")),
            "type": rec.get("type"),
        }

    @staticmethod
    def _column_name(column_class_ids: Any) -> str:
        """栏目名（试题库 / 期中期末 …）。"""
        if not isinstance(column_class_ids, list):
            return ""
        parts = []
        for col in column_class_ids:
            if not isinstance(col, dict):
                continue
            for key in ("firstName", "secondName"):
                name = str(col.get(key) or "").strip()
                if name and name not in parts:
                    parts.append(name)
        return " / ".join(parts)

    @staticmethod
    def _is_answer_title(title: str) -> bool:
        """标题是不是「独立答案文章」形态（含答案，但不含「试题及答案」）。"""
        if not title:
            return False
        if _COMBINED_TITLE_RE.search(title):
            return False
        return bool(_ANSWER_ONLY_TITLE_RE.search(title))

    @staticmethod
    def _is_combined_title(title: str) -> bool:
        return bool(_COMBINED_TITLE_RE.search(title or ""))

    @staticmethod
    def _to_int(value: Any) -> Optional[int]:
        """宽松转 int（接口里 id 有时是 str 有时是 int）。"""
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        text = str(value).strip()
        m = _DIGITS_RE.search(text)
        return int(m.group(1)) if m else None

    def _resolve_paper_id(self, paper_id: Any, url: str = "") -> Optional[int]:
        """从 paper_id / url 里解析文章 id。"""
        # url 优先（url 里的 id 最可靠）
        url = str(url or "").strip()
        if url:
            m = _ID_IN_URL_RE.search(url)
            if m:
                return int(m.group(1))
            m = _DIGITS_RE.search(url)
            if m:
                return int(m.group(1))
        if paper_id in (None, "", 0):
            return None
        # paper_id 也可能是直接粘的 URL 字符串
        if isinstance(paper_id, str) and ("/" in paper_id or "." in paper_id):
            m = _ID_IN_URL_RE.search(paper_id) or _DIGITS_RE.search(paper_id)
            return int(m.group(1)) if m else None
        return self._to_int(paper_id)

    @staticmethod
    def _academic_year(title: str) -> Optional[str]:
        """取标题里的学年标识：'2026-2027' 优先，否则取第一个 4 位年份。"""
        text = str(title or "")
        m = _YEAR_RANGE_RE.search(text)
        if m:
            return f"{m.group(1)}-{m.group(2)}"
        m = _YEAR_RE.search(text)
        if m:
            return m.group(1)
        return None

    @staticmethod
    def _norm_title(title: str) -> str:
        """标题归一化：去空白与标点，用于相似度比较。"""
        text = re.sub(r"[\s\u3000]+", "", title or "")
        text = re.sub(r"[（）()【】\[\]「」《》,，。.、:：;；!！?？\-—_/\\|]+", "", text)
        return text.lower()

    @staticmethod
    def _school_token(title: str) -> str:
        """从标题里取学校名。

        标题的固定结构是「[学年] 学校名 + 年级 + 学期 + 考试类型 + 学科」，
        所以「第一个年级/学科/考试类词之前的那一段」就是学校名。
        学校名是试卷身份最强的信号（比年份、比相似度都强）。
        """
        text = title or ""
        text = re.sub(r"^(19|20)\d{2}(\s*[-—~至]\s*(19|20)?\d{2})?\s*学年", "", text)
        for noise in _TITLE_NOISE:
            text = text.replace(noise, " ")
        m = _GRAMMAR_RE.search(text)
        school = (text[:m.start()] if m else text).strip()
        return re.sub(r"\s+", "", school)

    @staticmethod
    def _strip_years(text: str) -> str:
        """去掉年份（2026-2027学年 → 学年）。同一套卷的历年版本应该高度相似。"""
        return re.sub(r"(19|20)\d{2}(\s*[-—~至]\s*(19|20)?\d{2})?", "", text or "")

    @classmethod
    def _title_similarity(cls, a: str, b: str) -> float:
        """标题相似度：0.65 * 序列相似度 + 0.35 * 字符集重合度。

        再掺一份「去年份」的相似度（权重 0.4）：同一套卷的历年版本
        （2025-2026学年… / 2026-2027学年…）应当比「隔壁学校同年同科」更接近。
        """
        na, nb = cls._norm_title(a), cls._norm_title(b)
        if not na or not nb:
            return 0.0
        seq = difflib.SequenceMatcher(None, na, nb).ratio()
        sa, sb = set(na), set(nb)
        jac = len(sa & sb) / max(1, len(sa | sb))
        base = 0.65 * seq + 0.35 * jac

        ya, yb = cls._strip_years(a), cls._strip_years(b)
        if ya and yb and ya != a and yb != b:
            na2, nb2 = cls._norm_title(ya), cls._norm_title(yb)
            if na2 and nb2:
                seq2 = difflib.SequenceMatcher(None, na2, nb2).ratio()
                sa2, sb2 = set(na2), set(nb2)
                jac2 = len(sa2 & sb2) / max(1, len(sa2 | sb2))
                base = 0.6 * base + 0.4 * (0.65 * seq2 + 0.35 * jac2)
        return base

    @staticmethod
    def _keyword_from_title(title: str) -> str:
        """从标题派生搜索关键词：剥掉「试题 / 及答案 / 汇总」等噪声，再切成词。

        实测站内搜索对**整串关键词**是短语精确匹配（"…一七一中初一上学期期中数学"
        只命中本文 1 条）；空格分隔的词才是宽匹配（"北京一七一中 初一 数学" → 22055 条）。
        所以这里按高考卷的固定成分（年级 / 学科 / 考试类型 / 学期）把标题切开。
        """
        text = title or ""
        # 先去掉开头���学年份（"2026-2027学年北京…" → "北京…"）：
        # 带年份的查询只捞得到当年那一批，同一套卷的历年版本就看不见了
        text = re.sub(r"^(19|20)\d{2}(\s*[-—~至]\s*(19|20)?\d{2})?\s*学年", "", text)
        for noise in _TITLE_NOISE:
            text = text.replace(noise, " ")
        # 在固定成分词前后插空格，把长标题切成可独立匹配的词
        text = _GRAMMAR_RE.sub(r" \1 ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text or (title or "").strip()

    # ══════════════════════════════════════════════════════════════════
    # find_answer_paper 的候选收集
    # ══════════════════════════════════════════════════════════════════

    def _gather_search_records(self, src_title: str, query: str) -> list:
        """把候选文章捞回来。

        实测站内搜索加的词越多，结果越被限制在「最新那一批」：
          "北京一七一中 初一 上学期 期中 数学" → 前 20 条全是 2026-2027 的
          "北京一七一中 初一"                 → 同一学校的历年版本都排在前面
        所以这里同时用「完整切词」和「前两个词（学校+年级）」各搜一遍再合并，
        同一套卷的历年版本才捞得到。
        """
        queries = []
        if query:
            queries.append(query)
        core = " ".join((query or "").split()[:2])
        if core and core != query:
            queries.append(core)

        records, seen = [], set()
        for q in queries:
            for page in (1, 2):
                ok, data, err = self._search(q, page, 20)
                if not ok:
                    logger.warning("find_answer_paper 搜索失败(q=%s): %s", q, err)
                    break
                rows = data.get("records") or []
                for rec in rows:
                    rid = self._to_int(rec.get("id"))
                    if rid is None or rid in seen:
                        continue
                    seen.add(rid)
                    records.append(rec)
                if len(rows) < 20:
                    break
        return records

    def _collect_self_answer_candidate(self, src_id: int, data: dict,
                                       candidates: list) -> None:
        """本文档自带的答案材料（正文「有答案」扫描件 / 答案 PDF）也算候选。"""
        parsed = self._parse_article(data)
        answer_imgs = [i for i in parsed["images"] if i["kind"] == "answer"]
        answer_pdfs = [p for p in parsed["pdfs"] if p["kind"] == "answer"]
        if not answer_imgs and not answer_pdfs:
            return
        bits = []
        if answer_imgs:
            bits.append(f"正文有 {len(answer_imgs)} 张含答案扫描件")
        if answer_pdfs:
            bits.append(f"附件有 {len(answer_pdfs)} 个答案 PDF")
        candidates.append({
            "id": src_id,
            "title": str(data.get("title") or ""),
            "url": parsed["url"],
            "score": 0.9,
            "reason": "；".join(bits) + "（答案就在本文内，不必另找）",
            "is_answer": True,
            "from": "self",
        })

    def _collect_link_answer_candidates(self, src_id: int, data: dict,
                                        candidates: list) -> None:
        """正文里链到的答案类文章（如「XX试题答案」汇总）也算候选。"""
        content = str(data.get("content") or "")
        seen = {c["id"] for c in candidates}
        for href, text in re.findall(r'<a[^>]*?href="([^"]+)"[^>]*>(.*?)</a>',
                                     content, re.S):
            label = _TAG_RE.sub("", text).strip()
            if not label or len(label) < 4:
                continue
            if not self._is_answer_title(label):
                continue
            m = _ID_IN_URL_RE.search(href)
            if not m:
                continue
            rid = int(m.group(1))
            if rid == src_id or rid in seen:
                continue
            seen.add(rid)
            candidates.append({
                "id": rid,
                "title": label,
                "url": f"{SITE_BASE}{href}" if href.startswith("/") else href,
                "score": 0.6,
                "reason": "本文正文里链接到的答案类文章",
                "is_answer": True,
                "from": "link",
            })

    def _boost_by_body(self, cand: dict) -> None:
        """候选正文里答案图多 → 加分（这才是真的「答案文章」）。"""
        ok, data, err = self._get_info(cand["id"])
        if not ok:
            return
        parsed = self._parse_article(data)
        answer_imgs = sum(1 for i in parsed["images"] if i["kind"] == "answer")
        question_imgs = sum(1 for i in parsed["images"] if i["kind"] == "question")
        answer_pdfs = sum(1 for x in parsed["pdfs"] if x["kind"] == "answer")
        if answer_imgs or answer_pdfs:
            cand["score"] = round(min(1.0, cand["score"] + 0.15), 3)
            if answer_imgs:
                cand["reason"] += f"；正文有 {answer_imgs} 张答案图"
            if answer_pdfs:
                cand["reason"] += f"；附件有 {answer_pdfs} 个答案 PDF"
            cand["is_answer"] = True
            if question_imgs == 0 and not answer_pdfs:
                cand["reason"] += "（纯答案文章）"
        cand["answer_images"] = answer_imgs
        cand["question_images"] = question_imgs
        cand["answer_pdfs"] = answer_pdfs

    # ══════════════════════════════════════════════════════════════════
    # 工作区落盘
    # ══════════════════════════════════════════════════════════════════

    def _target_dir(self, user_id: int, paper_id: int) -> tuple[Path, bool]:
        """落盘目录：<workspace>/users/<uid>/gaokzx/<paper_id>/。

        workspace 能力是 harness 按 needs 注入的，可能注入失败（能力缺失 /
        应用没注册 workspace）—— 这时退到临时目录，并把 fallback 标出来。
        """
        uid = user_id or 1
        ws = self._workspace
        if ws is None:
            # 兼容：某些老路径按能力名直接注入到 .workspace
            ws = getattr(self, "workspace", None)
        if ws is not None:
            try:
                base = ws.user_subdir(uid, "gaokzx")
                return Path(base) / str(paper_id), False
            except Exception as e:
                logger.warning("工作区不可用（%s），退到临时目录", e)
        fallback_dir = Path(tempfile.gettempdir()) / "dsn_gaokzx" / str(uid) / \
            "gaokzx" / str(paper_id)
        return fallback_dir, True

    @staticmethod
    def _read_manifest(out_dir: Path) -> dict:
        """读取下载清单（记录 url → 文件名/大小，用于幂等跳过）。"""
        path = out_dir / "_manifest.json"
        try:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except Exception as e:
            logger.warning("读取 manifest 失败: %s", e)
        return {}

    @staticmethod
    def _write_manifest(out_dir: Path, manifest: dict) -> None:
        try:
            (out_dir / "_manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception as e:
            logger.warning("写 manifest 失败: %s", e)

    @staticmethod
    def _build_summary(data: dict, images: list, pdfs: list, q_cnt: int,
                       a_cnt: int, u_cnt: int, scan_set: str) -> str:
        """一句话摘要，给 AI 看。"""
        title = str(data.get("title") or "")
        parts = [f"《{title}》", f"正文 {len(images)} 张扫描图"]
        parts.append(f"（试题 {q_cnt} / 答案 {a_cnt} / 未知 {u_cnt}）")
        if pdfs:
            p_q = sum(1 for p in pdfs if p["kind"] == "question")
            p_a = sum(1 for p in pdfs if p["kind"] == "answer")
            parts.append(f"、附件 PDF {len(pdfs)} 个（试题 {p_q} / 答案 {p_a}）")
        summary = "".join(parts) + "。"

        answer_pdfs = [p for p in pdfs if p["kind"] == "answer"]
        if scan_set == "without_answers":
            if answer_pdfs:
                summary += ("扫描件文件名含「无答案」（正文只给了试题版），"
                            f"但附件里有答案 PDF「{answer_pdfs[0]['file_name']}」，"
                            "要答案直接下附件。")
            else:
                summary += ("扫描件文件名含「无答案」，本文只给试题；"
                            "答案可能未随文发布，可用 find_answer_paper 找独立答案文章。")
        elif scan_set == "with_answers":
            summary += ("扫描件文件名含「有答案」，这套卷把答案也扫进来了"
                        "（答案通常在扫描集后半部分），试题与答案可能是同一批图片。")
        elif images:
            summary += "扫描件文件名里没有答案标记，试题/答案只能靠正文标题与位置推断。"
        return summary
