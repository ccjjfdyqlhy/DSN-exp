
# DSN-exp/memory.py
# UPD v2_260324

import threading
from concurrent.futures import ThreadPoolExecutor, Future
from typing import List, Dict, Any, Optional

from config import Config
from chatdbmgr import ChatDBManager
from models import LMSummaryModel


class MemoryManager:
    def __init__(
        self,
        db: ChatDBManager,
        summary_model: Optional[LMSummaryModel] = None,
        max_workers: int = 2,
    ):
        self.db = db
        self.summary_model = summary_model or LMSummaryModel()
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.lock = threading.Lock()

    def record_dialog_and_summary(self,
                                  user_id: int,
                                  chat_id: int,
                                  round_index: int,
                                  messages: List[Dict[str, str]],
                                  async_mode: bool = True) -> Optional[Future]:
        """在保存对话后生成摘要记忆。"""
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
            with self.lock:
                memory_id = self.db.save_memory(user_id, chat_id, round_index, summary)
            return memory_id
        except Exception as e:
            # 仅记录错误，不抛给主流程
            print(f"MemoryManager 生成摘要失败: {e}")
            return None

    def assemble_context(self, user_id: int, chat_id: int, full_history: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """拼接上下文：超过阈值后逐步用记忆摘要替换远端消息。"""
        # 取记忆按轮次
        memories = self.db.get_memories(user_id, chat_id)
        window = Config.MEMORY_CONTEXT_WINDOW_SIZE
        threshold = int(window * Config.MEMORY_REPLACE_THRESHOLD_RATIO)

        # 所有历史（不含系统）
        payload = [m.copy() for m in full_history]
        if len(payload) <= threshold or not memories:
            return payload

        # 从最远消息开始替换，将最旧 round 替换为 memory.summary，并以 role=system表示记忆
        # 这里策略：将远部区段清掉并转为一个或多个记忆消息
        replace_count = len(payload) - threshold
        remain = payload[replace_count:]
        old_segment = payload[:replace_count]

        memory_msgs = []
        for mem in memories:
            memory_msgs.append({"role": "system", "content": f"记忆摘要：{mem['summary']}"})

        return memory_msgs + remain

    def shutdown(self):
        self.executor.shutdown(wait=False)
