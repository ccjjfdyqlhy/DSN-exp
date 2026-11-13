# apps/dsn_study/skills/builtin/paper_import/tools/paper_import_tools.py
# 整卷入库技能 —— 给 AI 的单工具入口。
#
# 设计意图：这类活儿（找一套卷子、下载、OCR、切页、抽题、入库）如果让模型
# 自己用十几步工具调用去拼，很容易在中间某步卡死或者把答案页混进试题页。
# 这里封装成**一个工具**：传几个参数，整条链路跑完。

from __future__ import annotations

import logging
import os

logger = logging.getLogger("skill.paper_import")


class PaperImportTool:
    """整卷 → 题库，一条龙。

    依赖注入:
        question_store —— 题库存储（写库）
        llm            —— 主模型服务（抽题 / 对答案）
        workspace      —— 工作区（图片、OCR 缓存、PDF 落盘）
    """

    # 语义能力 → 实例属性名（harness 按此注入）
    needs = {
        "question_store": "_store",
        "llm": "_llm",
        "workspace": "_workspace",
    }

    def __init__(self):
        self._store = None
        self._llm = None
        self._workspace = None

    def _importer(self):
        from apps.dsn_study.question_bank.paper_import import PaperImporter
        return PaperImporter(question_store=self._store, llm=self._llm,
                             workspace=self._workspace)

    @staticmethod
    def _progress(done: int, total: int, name: str) -> None:
        """OCR 进度（本地 VLM 逐页识别，约 30~60s/页）。"""
        logger.info("OCR 进度 %d/%d %s", done, total, name)

    def import_paper(self, paper_id: int = 0, keyword: str = "",
                     subject: str = "physics", max_pages: int = 12,
                     answer_pages: int = 0, dry_run: bool = False,
                     make_pdf: bool = True, user_id: int = 1) -> dict:
        """把一套试卷下载、OCR、切分试题/答案、抽题并入库（可选出 PDF）。

        OCR 走**本地** Bonsai 视觉模型（不进云端）。服务不常驻：第一次
        调用时按需拉起（约 40s 冷启动），整卷 OCR 约 30~60s/页。

        :param paper_id: 试卷 id（gaokzx 文章 id）；传 0 则用 keyword 搜索
        :param keyword: 搜索关键词，如「2026 高三 物理 期中」；paper_id=0 时必填
        :param subject: 学科代码（physics/math/chemistry/english/chinese/biology）
        :param max_pages: 最多处理多少页试题（OCR 成本随页数线性增长）
        :param answer_pages: 额外 OCR 多少页答案页用于回填答案（0=不对答案）
        :param dry_run: True 只抽题不入库，用于先看效果
        :param make_pdf: 是否同时生成试卷/答案 PDF
        :param user_id: 用户 id
        :return: {success, paper, questions_found, questions_added, steps, elapsed_sec}
        """
        if not paper_id and not (keyword or "").strip():
            return {"success": False, "error": "需要 paper_id 或 keyword 之一"}

        importer = self._importer()
        try:
            return importer.import_paper(
                paper_id=int(paper_id or 0),
                keyword=(keyword or "").strip(),
                subject=subject or "physics",
                max_pages=int(max_pages or 12),
                answer_pages=int(answer_pages or 0),
                dry_run=bool(dry_run),
                make_pdf=bool(make_pdf),
                user_id=int(user_id or 1),
                progress=self._progress,
            )
        except Exception as e:  # noqa: BLE001 - 绝不让异常冒到 AgentLoop
            logger.exception("整卷导入失败")
            return {"success": False, "error": f"整卷导入失败: {e}"}

    def vlm_status(self) -> dict:
        """查看本地视觉模型（入库 OCR 用）的状态。

        返回是否启用、是否托管（按需拉起）、当前是否已加载、用的哪个模型
        与投影器、以及最近一次启动命令行。OCR 出问题时先用它排查。
        """
        try:
            from apps.dsn_study.models.vlm_service import vlm_status as _status
            info = _status()
            info["success"] = True
            return info
        except Exception as e:  # noqa: BLE001
            logger.exception("查询本地 VLM 状态失败")
            return {"success": False, "error": str(e)}

    # ─────────────────────────────────────────────────────────────
    # 整卷合集：下载 → 分卷判定 → 拆试题/答案 → 合成 A4 PDF
    # ─────────────────────────────────────────────────────────────

    def prepare_bundle(self, papers: list, out_dir: str = "",
                       user_id: int = 1, make_pdf: bool = True,
                       use_vision: bool = True, concurrency: int = 4,
                       title_prefix: str = "", separator_pages: bool = True,
                       print_pdf: bool = False, skip_download: bool = False) -> dict:
        """把多套卷子准备成一份可打印的合卷 PDF（**默认不打印**）。

        流程：
          1. 并发下载各科图片（gaokzx.download_bundle）
          2. **快速判定**每套卷子的题/答分界（gaokzx.classify_papers：
             二分 + 并行 + 缩图 + 缓存，比逐页判定快一个数量级）
          3. 按分界拆成 ``试题/<科目>/`` 与 ``答案/<科目>/``（两份分开）
          4. 每科前插一页分隔标题，合成 A4 PDF
             （试卷一份、答案一份，**互不混排**）

        :param papers: [{"subject": "语文", "paper_id": 161613}, ...]
        :param out_dir: 输出目录；留空用工作区 papers/
        :param make_pdf: 是否合成 PDF
        :param use_vision: False = 用位置启发式判定（快但不准，仅调试用）
        :param concurrency: 下载并发度
        :param separator_pages: 每科前是否插入分隔标题页
        :param skip_download: True = 复用已下载的图片（秒级，用于重判/重合成）
        :param print_pdf: **默认 False** —— 准备完不送印，要打请显式传 True
        :return: {success, out_dir, question_pdf, answer_pdf, pages, ...}
        """
        import os
        import shutil
        import time

        t0 = time.time()
        items = []
        for entry in papers or []:
            if isinstance(entry, dict):
                subject = str(entry.get("subject") or entry.get("name") or "").strip()
                pid = int(entry.get("paper_id") or entry.get("id") or 0)
            else:
                subject, pid = "", int(entry or 0)
            if pid and subject:
                items.append({"subject": subject, "paper_id": pid})
        if not items:
            return {"success": False, "error": "papers 参数需要 [{subject, paper_id}]"}

        from apps.dsn_study.skills.builtin.gaokzx.tools.gaokzx_tools import GaokzxTool
        gz = GaokzxTool.create()

        if not out_dir:
            out_dir = os.path.join(os.getcwd(), ".dsn", "papers",
                                   "bundle")
        out_dir = os.path.abspath(out_dir)
        os.makedirs(out_dir, exist_ok=True)

        # ① 下载（skip_download=True = 复用已有图片，秒级）
        if skip_download:
            dl = {"success": True, "total_images": 0, "results": [
                {"subject": it["subject"], "paper_id": it["paper_id"],
                 "dir": str(gz._target_dir(user_id, it["paper_id"])[0])}
                for it in items]}
        else:
            dl = gz.download_bundle(items, user_id=user_id,
                                    concurrency=concurrency)
        if not dl.get("success"):
            return {"success": False, "error": dl.get("error") or "下载失败"}

        # ② 判定分界
        cache_path = os.path.join(out_dir, ".classify_cache.json")
        cl = gz.classify_papers(items, user_id=user_id, use_vision=use_vision,
                                 cache_path=cache_path, concurrency=6)
        if not cl.get("success"):
            return {"success": False, "error": cl.get("error") or "判定失败"}

        # ③ 拆试题 / 答案
        detail = []
        q_files: list[str] = []
        a_files: list[str] = []
        for item, res in zip(items, cl.get("results") or []):
            subject = item["subject"]
            pid = item["paper_id"]
            src_dir, _ = gz._target_dir(user_id, pid)
            # 文档顺序：question_* 在前、answer_* 在后（与 classify_papers 一致）
            doc_order = (sorted(src_dir.glob("question_*.jpg"))
                         + sorted(src_dir.glob("answer_*.jpg")))
            boundary = int(res.get("boundary") or 0)
            qd = os.path.join(out_dir, "试题", subject)
            ad = os.path.join(out_dir, "答案", subject)
            os.makedirs(qd, exist_ok=True)
            os.makedirs(ad, exist_ok=True)
            qi = ai = 0
            for idx, src in enumerate(doc_order):
                if idx < boundary:
                    qi += 1
                    dst = os.path.join(qd, "%s_%02d.jpg" % (subject, qi))
                    q_files.append(dst)
                else:
                    ai += 1
                    dst = os.path.join(ad, "%s_%02d.jpg" % (subject, ai))
                    a_files.append(dst)
                if not os.path.exists(dst):
                    shutil.copy2(str(src), dst)
            detail.append({"subject": subject, "paper_id": pid,
                           "total": len(doc_order), "boundary": boundary,
                           "question_pages": qi, "answer_pages": ai,
                           "mode": res.get("mode")})

        # ④ 合成 PDF（试题一份、答案一份，分开）
        out = {"success": True, "out_dir": out_dir, "details": detail,
               "stats": cl.get("stats") or {}, "downloads": dl.get("results") or [],
               "question_pages": len(q_files), "answer_pages": len(a_files)}
        if make_pdf and q_files:
            from apps.dsn_study.question_bank.paper_import import PaperImporter
            q_list, a_list = list(q_files), list(a_files)
            if separator_pages:
                prefix = title_prefix or "合卷"
                q_list = self._interleave_titles(q_list, detail, prefix, "（试题卷）")
                a_list = self._interleave_titles(a_list, detail, prefix, "（答案）")
            qpdf = os.path.join(out_dir, "%s_试题.pdf" % (title_prefix or "合卷"))
            apdf = os.path.join(out_dir, "%s_答案.pdf" % (title_prefix or "合卷"))
            out["question_pdf"] = qpdf
            out["answer_pdf"] = apdf
            out["question_pdf_result"] = PaperImporter.build_pdf(q_list, qpdf,
                                                                 page_size="A4")
            out["answer_pdf_result"] = PaperImporter.build_pdf(a_list, apdf,
                                                               page_size="A4")

        out["elapsed_sec"] = round(time.time() - t0, 1)

        # ⑤ 打印（默认不做）
        if print_pdf and out.get("question_pdf"):
            out["print"] = self.print_duplex(out["question_pdf"], phase="first")
        else:
            out["print"] = {"skipped": True,
                            "hint": "准备完成，未打印（传 print_pdf=True 才送印）"}
        return out

    @staticmethod
    def _interleave_titles(files: list, detail: list, prefix: str,
                           suffix: str) -> list:
        """在每科前面插入一张分隔标题页。"""
        from apps.dsn_study.document.printer import PrinterTool  # noqa: F401
        from apps.dsn_study.skills.builtin.paper_import.tools.paper_titles import (
            make_title_page,
        )
        out: list[str] = []
        by_subject = {}
        for f in files:
            subject = os.path.basename(f).rsplit("_", 1)[0]
            by_subject.setdefault(subject, []).append(f)
        for item in detail:
            subject = item["subject"]
            group = by_subject.get(subject) or []
            if not group:
                continue
            tp = make_title_page(subject, [prefix, suffix],
                                 tmp_dir=os.path.dirname(group[0]))
            out.append(tp)
            out.extend(group)
        return out

    def print_paper(self, pdf_path: str, printer_name: str = "",
                    page_range: str = "", copies: int = 1) -> dict:
        """打印一份已生成的 PDF（自动处理 CUPS 目录权限问题）。

        :param pdf_path: PDF 路径
        :param printer_name: 打印机名；留空用默认打印机
        :param page_range: 页码范围，如 "1" / "1-3"；留空打印全部
        :param copies: 份数
        """
        try:
            from apps.dsn_study.document.printer import PrinterTool
            return PrinterTool.print_file(
                pdf_path,
                printer_name=printer_name or None,
                copies=int(copies or 1),
                page_range=page_range or None,
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("打印失败")
            return {"success": False, "error": f"打印失败: {e}"}

    def print_duplex(self, pdf_path: str, phase: str = "first",
                     printer_name: str = "", copies: int = 1,
                     reverse_back: bool = False) -> dict:
        """单面打印机的**手动双面**打印：先打正面，人工翻纸后再打背面。

        这台 Canon G3010LAN 没有自动双面单元，驱动也没有 Windows 上那套
        「长边翻转」策略，所以双面必须靠人翻纸，分两步走：

            phase="first"  → 打印奇数页（正面），返回结果里带 next_action，
                             照着它转述给用户，让用户翻纸插回去
            phase="second" → 打印偶数页（背面），双面完成

        :param pdf_path: PDF 路径
        :param phase: "first"（正面/奇数页）或 "second"（背面/偶数页）
        :param printer_name: 打印机名；留空用默认
        :param copies: 份数
        :param reverse_back: 背面页序反转。出纸顺序与正面相反时置 true，
            否则背面会配错纸。
        """
        try:
            from apps.dsn_study.document.printer import PrinterTool
            return PrinterTool.print_duplex(
                pdf_path,
                printer_name=printer_name or None,
                phase=phase or "first",
                copies=int(copies or 1),
                reverse_back=bool(reverse_back),
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("双面打印失败")
            return {"success": False, "error": f"双面打印失败: {e}"}

    def pending_flip(self) -> dict:
        """查看当前有哪些作业正等着「翻面打印背面」。"""
        try:
            from apps.dsn_study.document.printer import PrinterTool
            jobs = PrinterTool.pending_flip_jobs()
            return {"success": True, "pending": jobs, "count": len(jobs)}
        except Exception as e:  # noqa: BLE001
            logger.exception("查询待翻面作业失败")
            return {"success": False, "error": str(e)}
