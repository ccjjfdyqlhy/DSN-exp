#!/usr/bin/env python3
"""整卷入库管线的独立验收脚本（不启 boot，跳过 TTS/ASR 等重服务）。

用法:
    python3 -m apps.dsn_study.scripts.run_paper_import --paper-id 161785 --dry-run
    python3 -m apps.dsn_study.scripts.run_paper_import --paper-id 161785 --max-pages 9 --answer-pages 2
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

from dotenv import load_dotenv  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
load_dotenv(os.path.join(_ROOT, ".env"))
load_dotenv(os.path.join(_ROOT, "apps", "dsn_study", ".env"), override=True)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def build_importer():
    from infra.models import OpenAICompatClient
    from apps.dsn_study.config import Config
    from apps.dsn_study.engine_support import LLMService
    from apps.dsn_study.db.question_bank import QuestionBankDBManager
    from apps.dsn_study.question_bank.store import QuestionStore
    from apps.dsn_study.question_bank.paper_import import PaperImporter

    client = OpenAICompatClient(
        api_key=Config.OPENAI_API_KEY,
        base_url=Config.OPENAI_API_BASE,
        model=Config.MAIN_MODEL_NAME,
        timeout=getattr(Config, "MODEL_REQUEST_TIMEOUT", 300),
    )
    db_mgr = QuestionBankDBManager(Config.QUESTION_BANK_DB_PATH)
    store = QuestionStore(db_mgr)
    llm = LLMService(client)
    workspace = os.path.join(os.path.dirname(Config.QUESTION_BANK_DB_PATH),
                             "workspace")
    return PaperImporter(question_store=store, llm=llm, workspace=workspace)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--paper-id", type=int, default=0)
    ap.add_argument("--keyword", default="")
    ap.add_argument("--subject", default="physics")
    ap.add_argument("--max-pages", type=int, default=12)
    ap.add_argument("--answer-pages", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-pdf", action="store_true")
    ap.add_argument("--out", default="/tmp/paper_import_report.json")
    args = ap.parse_args(argv)

    imp = build_importer()

    def progress(done, total, name):
        print(f"  [OCR] {done}/{total} {name}", flush=True)

    report = imp.import_paper(
        paper_id=args.paper_id,
        keyword=args.keyword,
        subject=args.subject,
        max_pages=args.max_pages,
        answer_pages=args.answer_pages,
        dry_run=args.dry_run,
        make_pdf=not args.no_pdf,
        progress=progress,
    )
    print("\n===== 报告 =====")
    print(json.dumps(report, ensure_ascii=False, indent=2)[:6000])
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print(f"\n完整报告 → {args.out}")
    return 0 if report.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
