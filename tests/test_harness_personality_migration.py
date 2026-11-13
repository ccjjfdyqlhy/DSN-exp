# -*- coding: utf-8 -*-
"""harness 人格持久层的**旧库升级路径**测试。

背景：``personality_evidence`` 表原先没有 ``pending`` 列（固化计数只在内存里），
修好之后新增该列。线上库是旧结构 —— 升级路径必须可靠，
否则"重启即失忆"会换个方式继续存在。
"""

from __future__ import annotations

import sqlite3

import pytest


def _old_schema_db(tmp_path):
    """造一个"旧结构"的证据表（与线上库一致）。"""
    path = tmp_path / "old.db"
    conn = sqlite3.connect(str(path))
    conn.execute(
        """CREATE TABLE IF NOT EXISTS personality_evidence (
               card_id TEXT PRIMARY KEY,
               mu_json TEXT NOT NULL DEFAULT '{}',
               sigma_json TEXT NOT NULL DEFAULT '{}',
               counts_json TEXT NOT NULL DEFAULT '{}',
               updated_at TEXT NOT NULL DEFAULT (datetime('now'))
           )""")
    conn.commit()
    conn.close()
    return path


def test_pending_column_is_added_to_old_db(tmp_path):
    """旧库补列：``pending`` 必须被加上，且已有数据不丢。"""
    from harness.personality.evidence_accumulator import EvidenceAccumulator

    path = _old_schema_db(tmp_path)
    conn = sqlite3.connect(str(path))
    conn.execute(
        "INSERT INTO personality_evidence (card_id, mu_json, sigma_json, counts_json) "
        "VALUES ('study_tutor', '{\"A1\": 0.7}', '{\"A1\": 0.1}', '{\"A1\": 3}')")
    conn.commit()
    conn.close()

    acc = EvidenceAccumulator(db=sqlite3.connect(str(path)))
    acc.init_tables()

    conn = sqlite3.connect(str(path))
    cols = [r[1] for r in conn.execute("PRAGMA table_info(personality_evidence)").fetchall()]
    assert "pending" in cols, "旧库没有补上 pending 列: %s" % cols
    row = conn.execute(
        "SELECT mu_json, counts_json FROM personality_evidence WHERE card_id='study_tutor'"
    ).fetchone()
    assert row is not None, "补列把已有数据弄没了"
    assert "0.7" in row[0], "已有 mu 被覆盖: %s" % (row,)
    conn.close()


def test_evidence_state_survives_new_instance(tmp_path):
    """证据状态在新实例里能恢复（DB 是真源，不是内存）。"""
    from harness.personality.evidence_accumulator import EvidenceAccumulator
    from harness.personality.events import PerceptionRecord

    path = tmp_path / "state.db"
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row

    acc = EvidenceAccumulator(db=conn)
    acc.init_tables()
    acc.add_evidence("card1", PerceptionRecord(event_type="praise"), {})
    acc.flush_card("card1")        # PEV3 的调用链里每轮都会 flush
    mu_before = acc.get_mu("card1")
    total_before = acc.get_total("card1")
    assert total_before > 0

    # 新实例（= 重启）→ 必须能从 DB 读回
    acc2 = EvidenceAccumulator(db=conn)
    acc2.init_tables()
    mu_after = acc2.get_mu("card1")
    assert mu_after == mu_before, "重启后特质向量不一致"
    assert acc2.get_total("card1") == total_before
    conn.close()
