#!/usr/bin/env python3
"""apps/dsn_study/scripts/purge_test_conversations.py — 清掉对话/记忆里的合成测试痕迹。

背景:
    dsn_study 的库里混着两类东西：
      * **真实使用痕迹** —— 真的在学习的对话、真的拍过的卷子、真的记下的备忘；
      * **自动化测试留下的合成痕迹** —— 「你好」「1+1」「测试回复」
        「能否听到」这类成串的假对话，外加关话题时写死的占位摘要
        （「与【X】相关的过往探讨」）。

    后者会被 `assemble_topic_context` 当成 `[话题回顾]` 注入 system prompt，
    于是主AI 每次对话都带着一条固定不变的假记忆 —— 本机就是
    「找一套最新的高三物理期中卷子做」那条。

删什么:
  * 话题库（topics.db）
      - 全部用户发言都在「合成测试语料表」里的话题（连同消息、
        compressed_chunks、sessions 行）；
      - `--drop-keyword` 命中的话题（默认含「物理卷子」那条 —— 用户点名要删）。
  * 题库（study_question_bank.db）
      - chat_rounds 里用户发言是合成测试语料的轮次；
      - memory_v2 里内容命中「测试特征」的 exp 行（保留 memo 与真实学习对话）。

不删（真实痕迹）:
  * memory_v2 的 memo 行、真实学习对话的 exp 摘要（如「二次函数吃力」）；
  * 题库、计划、打卡、图谱等与对话无关的数据。

用法:
    python3 -m apps.dsn_study.scripts.purge_test_conversations            # 预演
    python3 -m apps.dsn_study.scripts.purge_test_conversations --apply    # 真删（先备份）
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sqlite3
import sys
import time

# ── 合成测试语料（精确匹配用户发言）────────────────────────────────
CANNED_USER_MESSAGES = {
    "你好", "打个招呼", "你好。", "你好，你好，测试测试。", "1+1",
    "今天要做什么？", "今天这道题做完了",
    "帮我创建一个目标：AgentLoop 闭环目标",
    "题库里有哪些数学题？", "我有哪些学习目标？",
    "随便说点什么", "太棒了，这道题终于搞懂了，谢谢！", "再问一次",
    "这道题的第二问，怎么用动能定理？", "用一句话说明动能定理怎么用",
    "测试你能听到吗？", "可以听到吗？", "喂喂喂，你能听到吗？",
    "你好你好你好，能听到吗？", "你好，你能听到我吗？",
    "说一句话", "说一句话测试语音", "用一句话介绍一下你自己，说完停。",
    "今天天气怎么样", "今天天气怎么样？一句话回答。",
    "测试一下大请求埋点，这是一句普通的话",
    "你好，现在进行测试，你要能听见，请回复我。",
    "你能看到摄像头里面的东西吗？",
    "请调用视觉工具 look_around 看看摄像头里现在有什么",
    "请用视觉工具 look_around 看看摄像头 cam0 里现在有什么，只描述这个摄像头",
    "请用视觉工具 look_around 看看摄像头 doc 里现在有什么，只描述这个摄像头",
    "请用视觉工具 look_around 看看摄像头 doc 现在拍到了什么，一句话概括",
    "请用视觉工具 look_around 看看摄像头 desk 现在拍到了什么，一句话概括",
    "请原样朗读这一句，不要多说别的：这道题的第二问怎么用动能定理",
    "调用 list_printers 工具列出当前可用的打印机",
    "这问题我答不了，没接天气工具，查不了实时的。",
    "这个问题我答不了，没接天气工具查不了实时的你窗户那边看一眼，比我猜准。"
    "桌上是高二数学期末卷，还是那张海淀高三物理，我这边都记着要接着做就说。",
}

# ── exp 摘要里的测试特征（命中即视为合成痕迹）──────────────────────
#  注意别把**真实**的学习对话误伤：比如「计划 93 条是测试数据」那种
#  讨论脏数据的对话是真实使用痕迹，不能因为出现「测试」两个字就删。
TEST_EXP_PATTERNS = [
    re.compile(p) for p in (
        r"1\+1", r"介绍自己", r"能否听到", r"能不能听到", r"听得到吗", r"听到",
        r"听见了", r"说一句", r"一句话", r"招呼", r"天气", r"look_around",
        r"视觉工具", r"摄像头", r"朗读", r"随口测试",
        r"测试(回复|能听到|大请求|你能)", r"search_questions",
        r"鼓励", r"英语",
    )
]

#: 用户点名要删的记忆关键词（默认那条「找一套…物理期中卷子做」）
DEFAULT_DROP_KEYWORDS = ("卷子",)


def _default_study_db() -> str:
    from apps.dsn_study.config import Config
    return os.path.abspath(Config.QUESTION_BANK_DB_PATH)


def _default_topics_db() -> str:
    from apps.dsn_study.config import Config
    base = os.path.abspath(Config.QUESTION_BANK_DB_PATH)
    return os.path.join(os.path.dirname(base), "topics.db")


def _backup(path: str) -> str:
    backup_dir = os.path.join(os.path.dirname(path), "backups")
    os.makedirs(backup_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(backup_dir, "%s.%s.bak" % (os.path.basename(path), stamp))
    shutil.copy2(path, dst)
    return dst


def _is_test_user_msg(text: str) -> bool:
    return (text or "").strip() in CANNED_USER_MESSAGES


def _plan_topics(conn, drop_keywords):
    """返回要删的话题 id 列表 + 原因。"""
    plan = []
    topics = conn.execute(
        "SELECT topic_id, title FROM study_topics ORDER BY last_active_at DESC"
    ).fetchall()
    for topic_id, title in topics:
        users = [c.strip() for (c,) in conn.execute(
            "SELECT content FROM study_topic_messages WHERE topic_id=? AND role='user'",
            (topic_id,)).fetchall()]
        if users and all(_is_test_user_msg(u) for u in users):
            plan.append((topic_id, title, "合成测试话题（用户发言全为测试语料）"))
            continue
        if any(k in (title or "") for k in drop_keywords):
            plan.append((topic_id, title, "命中要删除的关键词（用户点名）"))
    return plan


def _plan_chat_rounds(conn, drop_keywords):
    plan = []
    for rid, umsg, areply in conn.execute(
            "SELECT id, user_msg, assistant_reply FROM chat_rounds").fetchall():
        if _is_test_user_msg(umsg):
            plan.append((rid, umsg, "合成测试轮次"))
        elif any(k in (umsg or "") for k in drop_keywords):
            plan.append((rid, umsg, "命中要删除的关键词（用户点名）"))
    return plan


def _plan_exps(conn, drop_keywords=None):
    """exp 摘要：只按「测试特征」判定。

    关键词（用户点名要删的那条）不套在这里 —— 摘要里出现「卷子」的
    多半是**真实**的画面描述，误伤代价大于收益。
    """
    plan = []
    for mid, ctype, content in conn.execute(
            "SELECT id, type, content FROM memory_v2").fetchall():
        if ctype != "exp":
            continue
        if any(p.search(content or "") for p in TEST_EXP_PATTERNS):
            plan.append((mid, content, "exp 摘要命中测试特征"))
    return plan


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="清理 dsn_study 对话/记忆里的合成测试痕迹")
    ap.add_argument("--study-db", default=None, help="题库路径（含 chat_rounds / memory_v2）")
    ap.add_argument("--topics-db", default=None, help="话题库路径")
    ap.add_argument("--apply", action="store_true", help="真正删除（默认只预演）")
    ap.add_argument("--no-backup", action="store_true", help="跳过备份")
    ap.add_argument("--drop-keyword", action="append", default=None,
                    help="额外要删除的关键词（可重复）；默认含「物理卷子」")
    args = ap.parse_args(argv)

    drop_keywords = tuple(args.drop_keyword) if args.drop_keyword else DEFAULT_DROP_KEYWORDS
    study_db = os.path.abspath(args.study_db or _default_study_db())
    topics_db = os.path.abspath(args.topics_db or _default_topics_db())

    print("要删除的关键词: %s\n" % (", ".join(drop_keywords),))

    # ── 话题库 ──
    tconn = sqlite3.connect(topics_db)
    topic_plan = _plan_topics(tconn, drop_keywords)
    print("── 话题库 %s ──" % topics_db)
    for tid, title, why in topic_plan:
        print("  ✗ %s | %s —— %s" % (tid[:16], title[:28], why))
    if not topic_plan:
        print("  （无）")

    # ── 题库 ──
    sconn = sqlite3.connect(study_db)
    round_plan = _plan_chat_rounds(sconn, drop_keywords)
    exp_plan = _plan_exps(sconn, drop_keywords)
    print("\n── 题库 %s ──" % study_db)
    for rid, umsg, why in round_plan:
        print("  ✗ chat_round #%d | %s —— %s" % (rid, (umsg or "")[:36], why))
    for mid, content, why in exp_plan:
        print("  ✗ memory_v2 #%d | %s —— %s" % (mid, (content or "")[:36], why))
    keep_exp = sconn.execute(
        "SELECT count(*) FROM memory_v2 WHERE type='exp'").fetchone()[0] - len(exp_plan)
    keep_memo = sconn.execute(
        "SELECT count(*) FROM memory_v2 WHERE type='memo'").fetchone()[0]
    print("  保留：exp %d 行、memo %d 行" % (keep_exp, keep_memo))

    if not args.apply:
        print("\n预演结束。加 --apply 执行实际删除。")
        tconn.close()
        sconn.close()
        return 0

    if not args.no_backup:
        for p in (topics_db, study_db):
            if os.path.isfile(p):
                print("已备份 → %s" % _backup(p))

    # ── 执行：话题 ──
    for tid, _title, _why in topic_plan:
        tconn.execute("DELETE FROM study_topic_messages WHERE topic_id=?", (tid,))
        tconn.execute("DELETE FROM study_topics WHERE topic_id=?", (tid,))
        tconn.execute("DELETE FROM compressed_chunks WHERE session_id=?", (tid,))
        tconn.execute("DELETE FROM sessions WHERE id=?", (tid,))
    tconn.commit()
    tconn.close()

    # ── 执行：轮次与 exp ──
    for rid, _u, _w in round_plan:
        sconn.execute("DELETE FROM chat_rounds WHERE id=?", (rid,))
    for mid, _c, _w in exp_plan:
        sconn.execute("DELETE FROM memory_v2 WHERE id=?", (mid,))
    # 嵌入只保留仍有记忆行对应的那几条
    sconn.execute(
        "DELETE FROM memory_embeds WHERE NOT EXISTS ("
        " SELECT 1 FROM memory_v2 m WHERE m.user_id = memory_embeds.user_id"
        " AND m.chat_id = memory_embeds.chat_id AND m.round = memory_embeds.round)")
    sconn.commit()
    left_r = sconn.execute("SELECT count(*) FROM chat_rounds").fetchone()[0]
    left_e = sconn.execute("SELECT count(*) FROM memory_v2").fetchone()[0]
    sconn.close()

    print("\n完成。话题删除 %d 个、轮次删除 %d 条、exp 删除 %d 行。" % (
        len(topic_plan), len(round_plan), len(exp_plan)))
    print("剩余：chat_rounds %d 条、memory_v2 %d 行。" % (left_r, left_e))
    return 0


if __name__ == "__main__":
    sys.exit(main())
