# DSN-exp/memory_recall.py
# 动态记忆召回引擎 — 全文检索 + 细节还原
# v2.0 2026-06-13

import logging
from datetime import datetime
from typing import List, Dict, Optional

from chatdbmgr import ChatDBManager

logger = logging.getLogger("MemoryRecallEngine")

MAX_DETAIL_CHARS_PER_ROUND = 4000
MAX_TOTAL_DETAIL_CHARS = 16000


class MemoryRecallEngine:
    """动态记忆召回引擎。全文搜索记忆摘要 + 按轮次还原对话。"""

    def __init__(self, db: ChatDBManager):
        self.db = db

    def search(self, user_id: int, chat_id: int,
               keywords: list[str], count: int = 5,
               threshold: float = 0.3) -> List[dict]:
        if not keywords:
            return []
        return self.db.search_memories(user_id, chat_id, keywords, count, threshold)

    def get_detail(self, user_id: int, chat_id: int,
                   round_indices: list[int]) -> Dict[int, List[dict]]:
        return self.db.get_messages_by_rounds(user_id, chat_id, round_indices)

    @staticmethod
    def _format_timedelta(ts_str: str) -> str:
        """将创建时间戳转为可读的时间差标注"""
        if not ts_str:
            return ""
        try:
            fmt = "%Y-%m-%d %H:%M:%S"
            if len(ts_str) <= 10:
                fmt = "%Y-%m-%d"
            ts = datetime.strptime(ts_str[:19] if len(ts_str) > 19 else ts_str, fmt)
            delta = datetime.now() - ts
            if delta.days > 30:
                return f"{delta.days // 30}个月前"
            elif delta.days > 0:
                return f"{delta.days}天前"
            elif delta.seconds > 3600:
                return f"{delta.seconds // 3600}小时前"
            elif delta.seconds > 60:
                return f"{delta.seconds // 60}分钟前"
            else:
                return "刚刚"
        except Exception:
            return ""

    @staticmethod
    def format_search_results(hits: List[dict], search_keywords: list[str]) -> str:
        if not hits:
            kw_str = ", ".join(search_keywords) if search_keywords else ""
            return f"[记忆检索结果] 未找到与 \"{kw_str}\" 相关的记忆。请调整关键词重试。"

        kw_str = ", ".join(search_keywords) if search_keywords else ""
        lines = [f"[记忆检索结果] 找到 {len(hits)} 条相关记忆 (关键词: {kw_str}):"]
        lines.append("─" * 56)

        for i, hit in enumerate(hits, 1):
            rd = hit["round_index"]
            ts = hit.get("created_at", "") or ""
            date_str = ts[:10] if isinstance(ts, str) and len(ts) > 10 else ts
            ago = MemoryRecallEngine._format_timedelta(ts)
            time_label = f"{date_str} ({ago})" if ago else date_str
            score = hit.get("score", 0)
            summary = hit.get("summary", "")
            if len(summary) > 200:
                summary = summary[:200] + "..."

            msg_range = ""
            s_id = hit.get("message_start_id")
            e_id = hit.get("message_end_id")
            if s_id and e_id:
                msg_range = f"消息 #{s_id}~#{e_id}"

            lines.append(f"第{rd}轮 · {time_label} · 匹配度: {score:.2f}")
            lines.append(f"  {summary}")
            if msg_range:
                lines.append(f"  {msg_range}")
            lines.append("─" * 56)

        lines.append("(使用 <recall>{\"detail\": [轮次号, ...]}</recall> 可查看完整对话)")
        return "\n".join(lines)

    @staticmethod
    def format_detail_results(detail: Dict[int, List[dict]]) -> str:
        if not detail:
            return "[记忆细节还原] 未找到对应轮次的对话记录。"

        lines = ["[记忆细节还原]"]
        total_chars = 0
        truncated = False

        for round_idx in sorted(detail.keys()):
            messages = detail[round_idx]
            if not messages:
                continue

            ts = ""
            for msg in messages:
                if msg.get("timestamp"):
                    ts = msg["timestamp"]
                    if isinstance(ts, str) and len(ts) > 10:
                        ts = ts[:10]
                    break

            ago = MemoryRecallEngine._format_timedelta(ts)
            time_label = f"{ts} ({ago})" if ago else ts
            lines.append(f"第{round_idx}轮 ({time_label}):")
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
        if hit_count == 0:
            return f"抱歉，我没有找到关于 {', '.join(search_keywords)} 的相关记忆。"
        elif hit_count == 1:
            return "我想起来了，之前讨论过这个话题。"
        else:
            return f"我回忆起了 {hit_count} 段相关的对话。"

    def handle_recall(self, user_id: int, chat_id: int,
                      payload: dict) -> Optional[str]:
        keywords = payload.get("keywords", [])
        detail_indices = payload.get("detail", [])
        auto_detail = payload.get("detail") is True
        count = payload.get("count", 5)

        if isinstance(detail_indices, list) and detail_indices:
            detail = self.get_detail(user_id, chat_id, detail_indices)
            return self.format_detail_results(detail)

        if keywords:
            hits = self.search(user_id, chat_id, keywords, count)
            if not hits:
                return self.format_search_results([], keywords)

            search_text = self.format_search_results(hits, keywords)

            if auto_detail and hits:
                indices = [h["round_index"] for h in hits]
                detail = self.get_detail(user_id, chat_id, indices)
                detail_text = self.format_detail_results(detail)
                return search_text + "\n\n" + detail_text

            return search_text

        return None
