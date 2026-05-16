# DSN-exp/memory_recall.py
# 动态记忆召回引擎 — 关键词检索 + 细节还原
# v1.0 2026-05-16

import logging
import re
from datetime import datetime
from typing import List, Dict, Optional

from chatdbmgr import ChatDBManager

logger = logging.getLogger("MemoryRecallEngine")

# 摘要解析正则: "[关键词: kw1, kw2, kw3]" 或 "[keywords: kw1, kw2]"
_KEYWORDS_RE = re.compile(r"\[(?:关键词|keywords)\s*:\s*([^\]]+)\]", re.IGNORECASE)

MAX_DETAIL_CHARS_PER_ROUND = 4000  # 每轮细节最大字符数
MAX_TOTAL_DETAIL_CHARS = 16000     # 单次召回总字符上限


class MemoryRecallEngine:
    """
    动态记忆召回引擎。
    
    职责:
    - search(): 关键词检索，返回排序的记忆命中列表
    - get_detail(): 按轮次还原原始对话消息
    - extract_keywords_from_summary(): 从 LLM 生成的摘要中解析关键词
    - format_search_results(): 格式化检索结果（给 AI / 用户看）
    - format_detail_results(): 格式化细节还原结果
    """

    def __init__(self, db: ChatDBManager):
        self.db = db

    # ── 检索 ──

    def search(self, user_id: int, chat_id: int,
               keywords: list[str], count: int = 5,
               threshold: float = 0.3) -> List[dict]:
        """
        关键词检索记忆。
        
        返回 [{memory_id, round_index, summary, keywords, score, created_at, ...}, ...]
        """
        if not keywords:
            return []
        return self.db.search_memories(user_id, chat_id, keywords, count, threshold)

    # ── 细节还原 ──

    def get_detail(self, user_id: int, chat_id: int,
                   round_indices: list[int]) -> Dict[int, List[dict]]:
        """
        按轮次还原原始对话消息。
        
        返回 {round_index: [{role, content, timestamp}, ...]}
        """
        return self.db.get_messages_by_rounds(user_id, chat_id, round_indices)

    # ── 关键词提取 ──

    @staticmethod
    def extract_keywords_from_summary(summary: str, fallback_count: int = 5) -> str:
        """
        从 LLM 生成的摘要中解析关键词字段。
        
        格式: "摘要文本...[关键词: kw1, kw2, kw3]"
               "Summary text...[keywords: kw1, kw2, kw3]"
        
        返回逗号分隔的关键词字符串（如 "kw1,kw2,kw3"），或 ""。
        """
        match = _KEYWORDS_RE.search(summary)
        if match:
            raw = match.group(1).strip()
            kws = [kw.strip().lower() for kw in re.split(r"[,，;\s]+", raw) if kw.strip()]
            return ",".join(kws[:fallback_count])

        # 降级: 尝试从文本末尾提取逗号分隔的短词
        lines = summary.strip().split("\n")
        last_line = lines[-1].strip() if lines else ""
        if last_line and len(last_line) < 120 and "," in last_line:
            tokens = [t.strip().lower() for t in last_line.split(",") if t.strip() and len(t.strip()) < 20]
            if 2 <= len(tokens) <= 10:
                return ",".join(tokens[:fallback_count])

        return ""

    @staticmethod
    def strip_keywords_from_summary(summary: str) -> str:
        """从摘要文本中移除 [关键词: ...] 行，返回纯净摘要。"""
        return _KEYWORDS_RE.sub("", summary).strip()

    # ── 格式化输出 ──

    @staticmethod
    def format_search_results(hits: List[dict], search_keywords: list[str]) -> str:
        """
        格式化检索结果为 AI 友好的文本。
        """
        if not hits:
            kw_str = ", ".join(search_keywords) if search_keywords else ""
            return f"[记忆检索结果] 未找到与 \"{kw_str}\" 相关的记忆。"

        kw_str = ", ".join(search_keywords) if search_keywords else ""
        lines = [f"[记忆检索结果] 找到 {len(hits)} 条相关记忆 (关键词: {kw_str}):"]
        lines.append("─" * 56)

        for i, hit in enumerate(hits, 1):
            rd = hit["round_index"]
            ts = hit.get("created_at", "") or ""
            if isinstance(ts, str) and len(ts) > 10:
                ts = ts[:10]
            score = hit.get("score", 0)
            summary = MemoryRecallEngine.strip_keywords_from_summary(hit.get("summary", ""))
            # 截断摘要
            if len(summary) > 300:
                summary = summary[:300] + "..."

            msg_range = ""
            s_id = hit.get("message_start_id")
            e_id = hit.get("message_end_id")
            if s_id and e_id:
                msg_range = f"消息 #{s_id}~#{e_id}"

            lines.append(f"#{rd} ({ts}) [得分: {score:.2f}]")
            lines.append(f"  摘要: {summary}")
            if msg_range:
                lines.append(f"  {msg_range}")
            lines.append("─" * 56)

        lines.append("(使用 <recall>{\"detail\": [轮次号, ...]}</recall> 可查看完整对话)")
        return "\n".join(lines)

    @staticmethod
    def format_detail_results(detail: Dict[int, List[dict]]) -> str:
        """
        格式化细节还原结果为 AI 友好的文本。
        """
        if not detail:
            return "[记忆细节还原] 未找到对应轮次的对话记录。"

        lines = ["[记忆细节还原]"]
        total_chars = 0
        truncated = False

        for round_idx in sorted(detail.keys()):
            messages = detail[round_idx]
            if not messages:
                continue

            # 推断日期
            ts = ""
            for msg in messages:
                if msg.get("timestamp"):
                    ts = msg["timestamp"]
                    if isinstance(ts, str) and len(ts) > 10:
                        ts = ts[:10]
                    break

            lines.append(f"第{round_idx}轮 ({ts}):")
            lines.append("─" * 56)

            for msg in messages:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                role_label = "User" if role == "user" else "Agent"
                line = f"{role_label}: {content}"
                lines.append(line)
                total_chars += len(line)

                if total_chars > MAX_TOTAL_DETAIL_CHARS:
                    truncated = True
                    break

            if truncated:
                lines.append("...(内容截断)")
                break

            lines.append("─" * 56)

        return "\n".join(lines)

    @staticmethod
    def format_success_message(search_keywords: list[str], hit_count: int) -> str:
        """生成人类化的检索成功过渡语（供 AI 在回复中参考，不自动注入）。"""
        if hit_count == 0:
            return f"抱歉，我没有找到关于 {', '.join(search_keywords)} 的相关记忆。"
        elif hit_count == 1:
            return f"我想起来了，之前讨论过这个话题。"
        else:
            return f"我回忆起了 {hit_count} 段相关的对话。"

    # ── 端到端便利方法 ──

    def handle_recall(self, user_id: int, chat_id: int,
                      payload: dict) -> Optional[str]:
        """
        处理一个 <recall> 请求的完整流程。
        
        payload 格式:
          {"keywords": [...], "count": 5}     — 关键词检索
          {"detail": [1, 2, 3]}               — 细节还原
          {"keywords": [...], "detail": true} — 检索后自动展开细节
        
        返回格式化的结果字符串，或 None 表示无效请求。
        """
        keywords = payload.get("keywords", [])
        detail_indices = payload.get("detail", [])
        auto_detail = payload.get("detail") is True  # 混合模式
        count = payload.get("count", 5)

        # 模式: 细节还原
        if isinstance(detail_indices, list) and detail_indices:
            detail = self.get_detail(user_id, chat_id, detail_indices)
            return self.format_detail_results(detail)

        # 模式: 关键词检索
        if keywords:
            hits = self.search(user_id, chat_id, keywords, count)

            if not hits:
                return self.format_search_results([], keywords)

            search_text = self.format_search_results(hits, keywords)

            # 混合模式: 检索后自动展开所有命中记忆的细节
            if auto_detail and hits:
                indices = [h["round_index"] for h in hits]
                detail = self.get_detail(user_id, chat_id, indices)
                detail_text = self.format_detail_results(detail)
                return search_text + "\n\n" + detail_text

            return search_text

        return None
