
# DSN-exp/memory.py
# UPD v3_260328

import re
import threading
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, Future
from typing import List, Dict, Any, Optional

from config import Config
from chatdbmgr import ChatDBManager
from models import LMSummaryModel
from memory_recall import MemoryRecallEngine

_RECALL_TAG_RE = re.compile(r"<recall>\s*(.*?)\s*</recall>", re.DOTALL)


class MemoryManager:
    def __init__(
        self,
        db: ChatDBManager,
        summary_model: Optional[LMSummaryModel] = None,
        max_workers: int = 2,
    ):
        self.db = db
        self.summary_model = summary_model or LMSummaryModel()
        self.recall_engine = MemoryRecallEngine(db)
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.lock = threading.Lock()
        self.logger = logging.getLogger(__name__)

    def record_dialog_and_summary(self,
                                  user_id: int,
                                  chat_id: int,
                                  round_index: int,
                                  messages: List[Dict[str, str]],
                                  async_mode: bool = True) -> Optional[Future]:
        """在保存对话后生成摘要记忆。"""
        # 检查消息是否标记为跳过记忆化
        for msg in messages:
            if msg.get("skip_memory", False):
                self.logger.info(f"消息标记为跳过记忆化，不生成摘要 - 用户ID: {user_id}, 聊天ID: {chat_id}, 轮次: {round_index}")
                return None
        
        if async_mode and Config.MEMORY_ASYNC_ENABLED:
            return self.executor.submit(self._do_summary, user_id, chat_id, round_index, messages)
        else:
            return self._do_summary(user_id, chat_id, round_index, messages)

    def _do_summary(self,
                    user_id: int,
                    chat_id: int,
                    round_index: int,
                    messages: List[Dict[str, str]]) -> Optional[int]:
        try:
            summary = self.summary_model.summarize_dialog(messages, max_length=Config.MEMORY_SUMMARY_LENGTH)
            if not summary:
                return None

            msg_start_id, msg_end_id = self.db.get_last_message_ids(chat_id, count=len(messages))

            with self.lock:
                memory_id = self.db.save_memory(
                    user_id, chat_id, round_index,
                    summary,
                    keywords="",
                    message_start_id=msg_start_id,
                    message_end_id=msg_end_id,
                )
            return memory_id
        except Exception as e:
            import logging
            logging.getLogger(__name__).error("MemoryManager 生成摘要失败: %s", e)
            try:
                with self.lock:
                    memory_id = self.db.save_memory(user_id, chat_id, round_index, summary)
                return memory_id
            except Exception as e2:
                import logging
                logging.getLogger(__name__).error("MemoryManager 生成摘要(fallback)也失败: %s", e2)
                return None

    def assemble_context(self, user_id: int, chat_id: int, full_history: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """拼接上下文：超过阈值后逐步用记忆摘要替换远端消息。"""
        # 取记忆按轮次
        memories = self.db.get_memories(user_id, chat_id)
        window = Config.MEMORY_CONTEXT_WINDOW_SIZE
        threshold = int(window * Config.MEMORY_REPLACE_THRESHOLD_RATIO)

        # 记录当前上下文状态
        self.logger.info(f"开始拼接上下文 - 用户ID: {user_id}, 聊天ID: {chat_id}")
        self.logger.info(f"当前历史消息数: {len(full_history)}, 记忆窗口大小: {window}, 替换阈值: {threshold}")
        self.logger.info(f"可用记忆数量: {len(memories)}")

        # 所有历史（不含系统）
        if len(full_history) <= threshold or not memories:
            self.logger.info(f"未触发记忆替换 - 历史消息数({len(full_history)}) <= 阈值({threshold}) 或 无可用记忆")
            return full_history

        payload = [m.copy() for m in full_history]

        # 从最远消息开始替换，将最旧 round 替换为 memory.summary，并以 role=system表示记忆
        replace_count = len(payload) - threshold
        remain = payload[replace_count:]
        old_segment = payload[:replace_count]

        self.logger.info(f"触发记忆替换 - 将替换 {replace_count} 条远端消息，保留 {len(remain)} 条近期消息")
        self.logger.info(f"已记忆化位于前 {replace_count} 轮的 {len(memories)} 条消息摘要")
        
        if old_segment:
            for i, msg in enumerate(old_segment[:3]):
                role = msg.get('role', 'unknown')
                content_preview = msg.get('content', '')[:50] + ('...' if len(msg.get('content', '')) > 50 else '')

        memory_msgs = []
        now = datetime.now()
        for mem in memories:
            rd = mem.get("round_index", "?")
            ts = mem.get("created_at", "")
            ago = ""
            if ts:
                try:
                    ts_str = str(ts)[:19] if len(str(ts)) > 19 else str(ts)
                    fmt = "%Y-%m-%d %H:%M:%S" if len(ts_str) > 10 else "%Y-%m-%d"
                    t = datetime.strptime(ts_str, fmt)
                    delta = now - t
                    if delta.days > 0:
                        ago = f"{delta.days}天前"
                    elif delta.seconds > 3600:
                        ago = f"{delta.seconds // 3600}小时前"
                    else:
                        ago = f"{delta.seconds // 60}分钟前"
                except Exception:
                    pass
            time_label = f"{ts} ({ago})" if ago else str(ts) if ts else ""
            header = f"[记忆 · 轮次{rd}" + (f" · {time_label}" if time_label else "") + "]"
            summary_text = mem.get("summary", "")
            memory_msgs.append({"role": "system", "content": f"{header} {summary_text}"})

        self.logger.info(f"拼接完成 - 最终上下文: {len(memory_msgs)} 条记忆 + {len(remain)} 条近期消息 = {len(memory_msgs) + len(remain)} 条消息")
        return memory_msgs + remain

    def process_recall_tags(self, user_id: int, chat_id: int, reply_text: str) -> str:
        """
        处理回复文本中的 <recall> 标签，替换为检索/细节结果。
        供 app.py 和 RecallPlugin 共用。
        """
        import json as json_mod

        matches = list(_RECALL_TAG_RE.finditer(reply_text))
        if not matches:
            return reply_text

        results = []
        for match in matches:
            try:
                payload = json_mod.loads(match.group(1).strip())
            except json_mod.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue

            result = self.recall_engine.handle_recall(user_id, chat_id, payload)
            if result:
                results.append(result)

        cleaned = _RECALL_TAG_RE.sub("", reply_text).strip()
        if results:
            cleaned += "\n\n" + "\n\n".join(results)
        return cleaned

    def shutdown(self):
        self.executor.shutdown(wait=False)
