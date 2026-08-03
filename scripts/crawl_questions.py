# scripts/crawl_questions.py
# 批量爬取题目入库 — 渠道框架 + 去重 + 入库
#
# 用法:
#   python scripts/crawl_questions.py --source http://example.com/api/questions --subject math
#   python scripts/crawl_questions.py --file ./questions.json --subject math --dry-run
#   python scripts/crawl_questions.py --list-sources
#
# 思路:
#   1. Source 抽象渠道（JSON API / 本地文件 / 自定义回调），统一输出原始题 dict
#   2. normalize 把渠道字段映射为题库标准字段
#   3. 按 content 精确去重（复用 QuestionStore.find_by_content）
#   4. 通过 QuestionStore 批量入库
#   5. 支持 --dry-run 预览、--limit 限量、--source-subject 强制学科

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Callable

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("crawl_questions")


# ── 渠道抽象 ──

class QuestionSource:
    """渠道基类：fetch() 返回原始题目列表。"""

    def __init__(self, **config):
        self.config = config

    def fetch(self) -> list[dict]:
        raise NotImplementedError


class JsonApiSource(QuestionSource):
    """JSON API 渠道：GET url，从 json 路径取题目列表。

    config:
      url: 接口地址
      list_key: 题目列表字段路径，如 "data" / "data.list" / "items"
      headers: dict 额外请求头
      page_key / page_size_key: 分页字段名（可选），配合 max_pages
      max_pages: 最多翻页数（默认 1）
    """

    def fetch(self) -> list[dict]:
        import urllib.request

        url = self.config["url"]
        list_key = self.config.get("list_key", "data")
        headers = self.config.get("headers", {}) or {}
        page_key = self.config.get("page_key")
        page_size_key = self.config.get("page_size_key")
        max_pages = int(self.config.get("max_pages", 1))
        page_size = int(self.config.get("page_size", 50))

        all_items: list[dict] = []
        page = 1
        while page <= max_pages:
            u = url
            if page_key:
                sep = "&" if "?" in u else "?"
                u = f"{u}{sep}{page_key}={page}&{page_size_key or 'page_size'}={page_size}"
            req = urllib.request.Request(u, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=self.config.get("timeout", 15)) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
            except Exception as e:
                logger.warning("拉取失败 (page=%d): %s", page, e)
                break

            items = self._dig(data, list_key)
            if not items:
                break
            all_items.extend(items if isinstance(items, list) else [items])

            if not page_key:
                break
            if len(items) < page_size:
                break
            page += 1
            logger.info("已拉取 %d 页，累计 %d 条", page - 1, len(all_items))

        logger.info("JsonApiSource 共获取 %d 条原始记录", len(all_items))
        return all_items

    @staticmethod
    def _dig(data, path: str):
        if not path:
            return data
        cur = data
        for part in path.split("."):
            if isinstance(cur, dict):
                cur = cur.get(part)
            elif isinstance(cur, list) and part.isdigit():
                idx = int(part)
                cur = cur[idx] if idx < len(cur) else None
            else:
                return None
        return cur


class JsonFileSource(QuestionSource):
    """本地 JSON/JSONL 文件渠道。config: file / list_key"""

    def fetch(self) -> list[dict]:
        file = self.config["file"]
        list_key = self.config.get("list_key", "")
        with open(file, encoding="utf-8") as f:
            data = json.load(f)
        items = JsonApiSource._dig(data, list_key) if list_key else data
        if not isinstance(items, list):
            raise ValueError(f"{file} 未解析出题目列表")
        logger.info("JsonFileSource 从 %s 读取 %d 条", file, len(items))
        return items


class RawTextSource(QuestionSource):
    """纯文本渠道：按行/分隔符切分原始文本，交给 normalize 回调解析。

    config: text 或 file / parser(可调用)
    """

    def fetch(self) -> list[dict]:
        if self.config.get("file"):
            with open(self.config["file"], encoding="utf-8") as f:
                text = f.read()
        else:
            text = self.config.get("text", "")
        parser = self.config.get("parser")
        if parser:
            return parser(text, self.config)
        blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
        logger.info("RawTextSource 切分出 %d 块", len(blocks))
        return [{"raw": b} for b in blocks]


# ── 标准化映射 ──

DEFAULT_FIELD_MAP = {
    # 渠道字段名 → 题库标准字段
    "title": "content",
    "question": "content",
    "stem": "content",
    "content": "content",
    "question_text": "content",
    "options": "options",
    "choices": "options",
    "answer": "answer",
    "correct_answer": "answer",
    "explanation": "explanation",
    "analysis": "explanation",
    "difficulty": "difficulty",
    "difficulty_level": "difficulty",
    "tags": "tags",
    "knowledge_points": "knowledge_points",
    "knowledge": "knowledge_points",
    "type_name": "type_name",
    "question_type": "type_name",
    "subtype": "subtype",
}


def default_normalize(raw: dict, field_map: dict = None, subject: str = None) -> dict:
    """把渠道原始字段映射为题库标准字段，未识别字段丢弃。"""
    fm = {**(field_map or {}), **DEFAULT_FIELD_MAP}
    out = {}
    for src_key, dst_key in fm.items():
        if src_key in raw and raw[src_key] not in (None, ""):
            out[dst_key] = raw[src_key]

    content = out.get("content", "")
    if isinstance(content, str):
        content = content.strip()
        # 去掉首部题号如 "1." "12." "1、"
        import re
        content = re.sub(r"^\s*\d+[\.、]\s*", "", content)
    if not content:
        return None

    out["content"] = content
    if isinstance(out.get("options"), list):
        out["options"] = [str(o).strip() for o in out["options"] if str(o).strip()]
    if subject and "subject" not in out:
        out["subject"] = subject
    return out


# ── 主流程 ──

def import_questions(questions: list[dict], store, tm, subject: str,
                     dry_run: bool = False, max_import: int = None,
                     dedup: bool = True, source: str = "crawl") -> dict:
    """按 content 去重后批量入库。questions 为已标准化的 dict 列表。"""
    stats = {"total": len(questions), "skipped_dup": 0, "added": 0,
             "errors": [], "added_ids": []}

    subject_info = tm.get_subject_by_code(subject) if subject else None
    if subject and not subject_info:
        return {"error": f"学科 {subject} 不存在（可用模板：3/6/9_subjects）"}

    if max_import:
        questions = questions[:max_import]

    for i, q in enumerate(questions):
        try:
            if dedup and store.find_by_content(q.get("content", ""), subject=subject):
                stats["skipped_dup"] += 1
                continue

            data = {
                "subject_id": (subject_info or {}).get("subject_id", 0),
                "type_id": _resolve_type_id(q, tm),
                "source": source,
                "difficulty": q.get("difficulty", 3),
                "content": q.get("content", ""),
                "options": q.get("options", []),
                "answer": q.get("answer", ""),
                "explanation": q.get("explanation", ""),
                "tags": q.get("tags", []),
                "knowledge_points": q.get("knowledge_points", []),
                "metadata": {"source": source, "origin_index": i},
            }
            if dry_run:
                stats["added"] += 1
                stats["added_ids"].append(None)
                continue
            qid = store.create_question(data)
            stats["added"] += 1
            stats["added_ids"].append(qid)
        except Exception as e:
            stats["errors"].append({"index": i, "error": str(e)})

    logger.info("导入统计: %s", stats)
    return stats


def _resolve_type_id(q: dict, tm) -> int:
    type_name = q.get("type_name", "解答题")
    subtype = q.get("subtype", "")
    type_id = tm.get_type_id(type_name, subtype)
    if not type_id:
        type_id = tm.get_type_id(type_name)
    return type_id or 1


# ── CLI ──

def build_sources(args) -> list[QuestionSource]:
    sources = []
    if args.source:
        sources.append(JsonApiSource(
            url=args.source, list_key=args.list_key,
            page_key=args.page_key, page_size_key=args.page_size_key,
            max_pages=args.max_pages, page_size=args.page_size,
            headers=(json.loads(args.headers) if args.headers else None),
        ))
    if args.file:
        sources.append(JsonFileSource(file=args.file, list_key=args.list_key))
    if args.text:
        sources.append(RawTextSource(text=args.text))
    if args.sources_file:
        with open(args.sources_file, encoding="utf-8") as f:
            for spec in json.load(f):
                kind = spec.get("type", "json_api")
                if kind == "json_api":
                    sources.append(JsonApiSource(**spec.get("config", {})))
                elif kind == "json_file":
                    sources.append(JsonFileSource(**spec.get("config", {})))
                elif kind == "raw_text":
                    sources.append(RawTextSource(**spec.get("config", {})))
                else:
                    logger.warning("未知渠道类型: %s", kind)
    return sources


def main(argv=None):
    parser = argparse.ArgumentParser(description="批量爬取题目入库")
    parser.add_argument("--source", help="JSON API 地址")
    parser.add_argument("--file", help="本地 JSON/JSONL 文件")
    parser.add_argument("--text", help="原始文本")
    parser.add_argument("--sources-file", help="渠道配置文件 (json)")
    parser.add_argument("--list-key", default="", help="题目列表字段路径，如 data / data.list")
    parser.add_argument("--page-key", default="", help="分页字段名")
    parser.add_argument("--page-size-key", default="", help="分页大小字段名")
    parser.add_argument("--page-size", type=int, default=50)
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--headers", default="", help="JSON headers")
    parser.add_argument("--subject", default="", help="学科代码，缺省时用每条记录的 subject 字段")
    parser.add_argument("--field-map", default="", help="字段映射 json")
    parser.add_argument("--dry-run", action="store_true", help="只预览不入库")
    parser.add_argument("--limit", type=int, default=0, help="最多入库条数")
    parser.add_argument("--no-dedup", action="store_true", help="关闭去重")
    parser.add_argument("--source-tag", default="crawl", help="来源标记")
    args = parser.parse_args(argv)

    from db.question_bank import QuestionBankDBManager
    from question_bank.store import QuestionStore
    from question_bank.template_manager import SubjectTemplateManager

    db = QuestionBankDBManager()
    tm = SubjectTemplateManager(db=db)
    tm.init_builtin_templates()
    if not tm.has_subjects():
        tm.apply_template("6_subjects")
    store = QuestionStore(db=db)

    field_map = json.loads(args.field_map) if args.field_map else None

    sources = build_sources(args)
    if not sources:
        parser.print_help()
        return 1

    raw_all = []
    for src in sources:
        raw_all.extend(src.fetch())

    normalized = []
    for raw in raw_all:
        if not isinstance(raw, dict):
            continue
        q = default_normalize(raw, field_map=field_map, subject=args.subject)
        if q:
            normalized.append(q)

    logger.info("标准化后共 %d 题", len(normalized))

    if args.dry_run:
        for i, q in enumerate(normalized[:20], 1):
            print(f"  [{i}] [{q.get('subject','-')}] {q.get('content','')[:80]}")
        print(f"\n(预览模式) 共 {len(normalized)} 题可导入")

    stats = import_questions(
        normalized, store, tm, subject=args.subject,
        dry_run=args.dry_run, max_import=args.limit,
        dedup=not args.no_dedup, source=args.source_tag,
    )
    if "error" in stats:
        print(f"✗ {stats['error']}")
        return 1

    print(f"\n 总数: {stats['total']} | 已入库: {stats['added']} "
          f"| 去重跳过: {stats['skipped_dup']} | 失败: {len(stats['errors'])}")
    for err in stats["errors"][:10]:
        print(f"   ✗ 第{err['index']}条: {err['error']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
