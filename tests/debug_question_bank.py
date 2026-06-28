#!/usr/bin/env python3
"""题库调试工具 — 直接读取 SQLite，不需启动 DSN 系统。

用法:
  python tests/debug_question_bank.py                  # 交互模式
  python tests/debug_question_bank.py list             # 列出所有题目
  python tests/debug_question_bank.py list --subject math
  python tests/debug_question_bank.py get 3            # 查看第 3 题
  python tests/debug_question_bank.py search "首都"    # 全文搜索
  python tests/debug_question_bank.py subjects         # 科目列表
  python tests/debug_question_bank.py types            # 题型列表
  python tests/debug_question_bank.py count            # 各科统计
  python tests/debug_question_bank.py errors           # 错题记录
  python tests/debug_question_bank.py exams            # 试卷列表
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DB_PATH = PROJECT_ROOT / ".dsn" / "question_bank.db"


class QuestionBankDebugger:
    def __init__(self, db_path: str = str(DB_PATH)):
        self._db_path = db_path
        if not os.path.exists(db_path):
            print(f"[错误] 题库数据库不存在: {db_path}")
            print("请先启动系统生成数据库，或检查路径。")
            sys.exit(1)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # ── 查询方法 ──

    def get_subjects(self) -> list[dict]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM subjects ORDER BY subject_id"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_question_types(self) -> list[dict]:
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM question_types ORDER BY type_id"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_question(self, qid: int) -> dict | None:
        conn = self._conn()
        row = conn.execute(
            "SELECT q.*, s.name AS subject_name, s.code AS subject_code, "
            "t.name AS type_name, t.subtype AS type_subtype "
            "FROM questions q "
            "JOIN subjects s ON q.subject_id = s.subject_id "
            "JOIN question_types t ON q.type_id = t.type_id "
            "WHERE q.question_id = ?", (qid,)
        ).fetchone()
        conn.close()
        if not row:
            return None
        return self._decode_row(dict(row))

    def list_questions(self, subject: str = None, limit: int = 50, offset: int = 0) -> list[dict]:
        conn = self._conn()
        query = """
            SELECT q.question_id, q.content, q.difficulty, q.source,
                   s.name AS subject_name, s.code AS subject_code,
                   t.name AS type_name, t.subtype AS type_subtype,
                   q.tags, q.created_at
            FROM questions q
            JOIN subjects s ON q.subject_id = s.subject_id
            JOIN question_types t ON q.type_id = t.type_id
        """
        params = []
        if subject:
            query += " WHERE s.code = ?"
            params.append(subject)
        query += " ORDER BY q.question_id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return [self._decode_row(dict(r)) for r in rows]

    def search_questions(self, keyword: str, limit: int = 20) -> list[dict]:
        conn = self._conn()
        like = f"%{keyword}%"
        rows = conn.execute(
            """SELECT q.question_id, q.content, q.difficulty,
                      s.name AS subject_name, t.name AS type_name
               FROM questions q
               JOIN subjects s ON q.subject_id = s.subject_id
               JOIN question_types t ON q.type_id = t.type_id
               WHERE q.content LIKE ? OR q.tags LIKE ? OR q.answer LIKE ?
               ORDER BY q.question_id DESC LIMIT ?""",
            (like, like, like, limit),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def count_by_subject(self) -> list[dict]:
        conn = self._conn()
        rows = conn.execute(
            """SELECT s.subject_id, s.name, s.code,
                      COUNT(q.question_id) AS total
               FROM subjects s
               LEFT JOIN questions q ON s.subject_id = q.subject_id
               GROUP BY s.subject_id ORDER BY s.subject_id"""
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_error_logs(self, limit: int = 20) -> list[dict]:
        conn = self._conn()
        rows = conn.execute(
            """SELECT e.*, q.content AS question_content, q.question_id,
                      s.name AS subject_name
               FROM error_logs e
               JOIN questions q ON e.question_id = q.question_id
               JOIN subjects s ON q.subject_id = s.subject_id
               ORDER BY e.created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_exam_papers(self, limit: int = 10) -> list[dict]:
        conn = self._conn()
        rows = conn.execute(
            """SELECT p.*, s.name AS subject_name
               FROM exam_papers p
               JOIN subjects s ON p.subject_id = s.subject_id
               ORDER BY p.created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        conn.close()
        papers = []
        for r in rows:
            p = dict(r)
            try:
                p["question_ids"] = json.loads(p["question_ids"])
            except (json.JSONDecodeError, TypeError):
                p["question_ids"] = []
            papers.append(p)
        return papers

    # ── 格式化 ──

    @staticmethod
    def _decode_row(row: dict) -> dict:
        for field in ["options", "answer", "tags", "knowledge_points", "metadata"]:
            if field in row and isinstance(row[field], str):
                try:
                    row[field] = json.loads(row[field])
                except (json.JSONDecodeError, TypeError):
                    pass
        return row

    @staticmethod
    def _fmt_tags(tags) -> str:
        if isinstance(tags, list):
            return ", ".join(tags) if tags else "—"
        return str(tags) if tags else "—"

    @staticmethod
    def _fmt_answer(answer) -> str:
        if isinstance(answer, (list, dict)):
            return json.dumps(answer, ensure_ascii=False)
        return str(answer)

    def _print_question_summary(self, q: dict):
        tid = q["question_id"]
        content = q.get("content", "")[:60]
        subj = q.get("subject_code") or q.get("subject_name", "?")
        tname = q.get("type_name", "?")
        diff = q.get("difficulty", "?")
        print(f"  #{tid:<4} [{diff}★] {subj}/{tname}  {content}")

    def _print_question_detail(self, q: dict):
        print(f"  题目 ID:      {q['question_id']}")
        print(f"  科目:         {q.get('subject_name', '?')} ({q.get('subject_code', '?')})")
        print(f"  题型:         {q.get('type_name', '?')} / {q.get('type_subtype', '—')}")
        print(f"  难度:         {q['difficulty']} / 5")
        print(f"  来源:         {q.get('source', '—')}")
        print(f"  内容:")
        for line in q.get("content", "").split("\n"):
            print(f"    {line}")
        if q.get("options"):
            print(f"  选项:")
            for opt in q["options"]:
                print(f"    - {opt}")
        print(f"  答案:         {self._fmt_answer(q.get('answer', ''))}")
        if q.get("explanation"):
            print(f"  解析:         {q['explanation']}")
        print(f"  标签:         {self._fmt_tags(q.get('tags', []))}")
        print(f"  知识点:       {self._fmt_tags(q.get('knowledge_points', []))}")
        print(f"  创建时间:     {q.get('created_at', '—')}")

    # ── 命令行命令 ──

    def cmd_subjects(self):
        subjects = self.get_subjects()
        if not subjects:
            print("  (无科目)")
            return
        print(f"  共 {len(subjects)} 个科目:")
        for s in subjects:
            print(f"    #{s['subject_id']}  {s['name']}  (code: {s['code']})")

    def cmd_types(self):
        types = self.get_question_types()
        if not types:
            print("  (无题型)")
            return
        print(f"  共 {len(types)} 个题型:")
        for t in types:
            subtype = f" / {t['subtype']}" if t.get("subtype") else ""
            print(f"    #{t['type_id']}  {t['name']}{subtype}  [{t.get('scoring_mode', 'exact')}]")

    def cmd_count(self):
        stats = self.count_by_subject()
        total = 0
        print(f"  {'科目':<12} {'代码':<8} {'题目数':<6}")
        print(f"  {'-'*30}")
        for s in stats:
            print(f"  {s['name']:<12} {s['code']:<8} {s['total']:<6}")
            total += s["total"]
        print(f"  {'-'*30}")
        print(f"  合计: {total} 题")

    def cmd_list(self, args):
        questions = self.list_questions(
            subject=args.subject, limit=args.limit, offset=args.offset or 0,
        )
        if not questions:
            print("  (无题目)")
            return
        print(f"  共 {len(questions)} 题:")
        for q in questions:
            self._print_question_summary(q)

    def cmd_get(self, args):
        q = self.get_question(args.id)
        if not q:
            print(f"  题目 #{args.id} 不存在")
            return
        self._print_question_detail(q)

    def cmd_search(self, args):
        results = self.search_questions(args.keyword, limit=args.limit)
        if not results:
            print(f"  未找到包含「{args.keyword}」的题目")
            return
        print(f"  找到 {len(results)} 题:")
        for r in results:
            print(f"    #{r['question_id']}  [{r['difficulty']}★] {r.get('type_name', '?')}  {r.get('content', '')[:80]}")

    def cmd_errors(self, args):
        logs = self.get_error_logs(limit=args.limit)
        if not logs:
            print("  (无错题记录)")
            return
        print(f"  最近 {len(logs)} 条错题记录:")
        for log in logs:
            content = (log.get("question_content") or "")[:50]
            mastered = "✓" if log.get("mastered") else "✗"
            print(f"    #{log['log_id']} Q{log['question_id']} [{mastered}] "
                  f"{log.get('subject_name', '?')}  {content}")
            if log.get("error_type") or log.get("error_reason"):
                print(f"      类型: {log.get('error_type', '—')}  原因: {log.get('error_reason', '—')}")

    def cmd_exams(self, args):
        papers = self.get_exam_papers(limit=args.limit)
        if not papers:
            print("  (无试卷)")
            return
        print(f"  最近 {len(papers)} 份试卷:")
        for p in papers:
            n_qs = len(p.get("question_ids", []))
            print(f"    #{p['paper_id']}  {p['title']}  "
                  f"[{p.get('subject_name', '?')}]  "
                  f"{n_qs}题  {p.get('difficulty', '?')}★  "
                  f"{p.get('total_score', '?')}分")
            if p.get("time_limit_min"):
                print(f"      时限: {p['time_limit_min']}分钟  "
                      f"创建: {p.get('created_at', '—')}")

    # ── 交互模式 ──

    def interactive(self):
        print("=" * 60)
        print("  题库调试工具 (交互模式)")
        print("  直接读取 SQLite，无需启动 DSN 系统")
        print(f"  数据库: {self._db_path}")
        print("=" * 60)
        stats = self.count_by_subject()
        total = sum(s["total"] for s in stats)
        if stats:
            parts = [f"{s['code']}={s['total']}" for s in stats]
            print(f"  题库: {total} 题 ({', '.join(parts)})")
        print()

        commands = {
            "list":    "列出题目 (可加 --subject math --limit 10)",
            "get":     "查看题目详情  get <id>",
            "search":  "搜索题目  search <关键词>",
            "subjects":"科目列表",
            "types":   "题型列表",
            "count":   "各科统计",
            "errors":  "错题记录",
            "exams":   "试卷列表",
            "help":    "显示此帮助",
            "q":       "退出",
        }

        while True:
            print("-" * 60)
            try:
                line = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not line:
                continue
            if line.lower() in ("q", "quit", "exit"):
                break
            if line.lower() in ("help", "?"):
                print("  可用命令:")
                for cmd, desc in commands.items():
                    print(f"    {cmd:<10} {desc}")
                continue

            parts = line.split()
            cmd = parts[0]
            rest = parts[1:]

            try:
                if cmd == "subjects":
                    self.cmd_subjects()
                elif cmd == "types":
                    self.cmd_types()
                elif cmd == "count":
                    self.cmd_count()
                elif cmd == "list":
                    class FakeArgs:
                        subject = None
                        limit = 20
                        offset = 0
                    i = 0
                    while i < len(rest):
                        if rest[i] == "--subject" and i + 1 < len(rest):
                            FakeArgs.subject = rest[i + 1]
                            i += 2
                        elif rest[i] == "--limit" and i + 1 < len(rest):
                            FakeArgs.limit = int(rest[i + 1])
                            i += 2
                        elif rest[i] == "--offset" and i + 1 < len(rest):
                            FakeArgs.offset = int(rest[i + 1])
                            i += 2
                        else:
                            i += 1
                    self.cmd_list(FakeArgs)
                elif cmd == "get":
                    if not rest:
                        print("  用法: get <题目ID>")
                        continue
                    class FakeArgsGet:
                        id = int(rest[0])
                    self.cmd_get(FakeArgsGet)
                elif cmd == "search":
                    kw = " ".join(rest) if rest else ""
                    if not kw:
                        print("  用法: search <关键词>")
                        continue
                    class FakeArgsSearch:
                        keyword = kw
                        limit = 20
                    self.cmd_search(FakeArgsSearch)
                elif cmd == "errors":
                    class FakeArgsErrors:
                        limit = 20
                    self.cmd_errors(FakeArgsErrors)
                elif cmd == "exams":
                    class FakeArgsExams:
                        limit = 10
                    self.cmd_exams(FakeArgsExams)
                else:
                    print(f"  未知命令: {cmd}  (输入 help 查看可用命令)")
            except Exception as e:
                print(f"  [错误] {e}")


def main():
    parser = argparse.ArgumentParser(description="题库调试工具")
    parser.add_argument("command", nargs="?", default=None,
                        help="命令: list / get / search / subjects / types / count / errors / exams")
    parser.add_argument("args", nargs=argparse.REMAINDER,
                        help="参数: 对于 get 是题目ID; 对于 search 是关键; 其余用 --key value")

    args = parser.parse_args()

    debugger = QuestionBankDebugger()

    if args.command is None:
        debugger.interactive()
        return

    cmd = args.command.lower()

    # 将剩余参数解析为 key=value 或 --key value 或 位置参数
    rest = args.args

    if cmd == "subjects":
        debugger.cmd_subjects()
    elif cmd == "types":
        debugger.cmd_types()
    elif cmd == "count":
        debugger.cmd_count()
    elif cmd == "list":
        class ListArgs:
            subject = None
            limit = 50
            offset = 0
        i = 0
        while i < len(rest):
            if rest[i] == "--subject" and i + 1 < len(rest):
                ListArgs.subject = rest[i + 1]
                i += 2
            elif rest[i] == "--limit" and i + 1 < len(rest):
                ListArgs.limit = int(rest[i + 1])
                i += 2
            elif rest[i] == "--offset" and i + 1 < len(rest):
                ListArgs.offset = int(rest[i + 1])
                i += 2
            else:
                i += 1
        debugger.cmd_list(ListArgs)
    elif cmd == "get":
        if not rest:
            print("用法: python debug_question_bank.py get <题目ID>")
            sys.exit(1)
        class GetArgs:
            id = int(rest[0])
        debugger.cmd_get(GetArgs)
    elif cmd == "search":
        kw = rest[0] if rest else ""
        if not kw:
            print("用法: python debug_question_bank.py search <关键词>")
            sys.exit(1)
        class SearchArgs:
            keyword = kw
            limit = 20
        debugger.cmd_search(SearchArgs)
    elif cmd == "errors":
        class ErrorsArgs:
            limit = 20
        debugger.cmd_errors(ErrorsArgs)
    elif cmd == "exams":
        class ExamsArgs:
            limit = 10
        debugger.cmd_exams(ExamsArgs)
    else:
        print(f"未知命令: {cmd}")
        print("可用命令: list / get / search / subjects / types / count / errors / exams")
        sys.exit(1)


if __name__ == "__main__":
    main()
