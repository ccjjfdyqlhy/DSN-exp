
# DSN-exp/memory.py
# UPD v2_260326

import threading
import logging
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
        self.logger = logging.getLogger(__name__)

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
            import logging
            logging.getLogger(__name__).error(f"MemoryManager 生成摘要失败: {e}")
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
        payload = [m.copy() for m in full_history]
        if len(payload) <= threshold or not memories:
            self.logger.info(f"未触发记忆替换 - 历史消息数({len(payload)}) <= 阈值({threshold}) 或 无可用记忆")
            return payload

        # 从最远消息开始替换，将最旧 round 替换为 memory.summary，并以 role=system表示记忆
        # 这里策略：将远部区段清掉并转为一个或多个记忆消息
        replace_count = len(payload) - threshold
        remain = payload[replace_count:]
        old_segment = payload[:replace_count]

        # 记录替换详情
        self.logger.info(f"触发记忆替换 - 将替换 {replace_count} 条远端消息，保留 {len(remain)} 条近期消息")
        self.logger.info(f"已记忆化位于前 {replace_count} 轮的 {len(memories)} 条消息摘要")
        
        # 记录被替换的消息摘要（前几条）
        if old_segment:
            for i, msg in enumerate(old_segment[:3]):  # 只记录前3条被替换的消息
                role = msg.get('role', 'unknown')
                content_preview = msg.get('content', '')[:50] + ('...' if len(msg.get('content', '')) > 50 else '')
                self.logger.info(f"被替换消息 {i+1}: [{role}] {content_preview}")
            if len(old_segment) > 3:
                self.logger.info(f"... 还有 {len(old_segment) - 3} 条消息被替换")

        memory_msgs = []
        for mem in memories:
            memory_msgs.append({"role": "system", "content": f"记忆摘要：{mem['summary']}"})
            # 记录记忆摘要内容
            summary_preview = mem['summary'][:80] + ('...' if len(mem['summary']) > 80 else '')
            self.logger.info(f"记忆摘要 {len(memory_msgs)}: {summary_preview}")

        self.logger.info(f"拼接完成 - 最终上下文: {len(memory_msgs)} 条记忆 + {len(remain)} 条近期消息 = {len(memory_msgs) + len(remain)} 条消息")
        return memory_msgs + remain

    def shutdown(self):
        self.executor.shutdown(wait=False)
