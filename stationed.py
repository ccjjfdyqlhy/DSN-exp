# DSN-exp/stationed.py
# 驻守模型 — 服务端事务处理 AI，无动作执行能力
# 仅在管理员通过终端 stdin 直接对话时使用

from __future__ import annotations

import time
import logging

logger = logging.getLogger("Steward")

STEWARD_SYSTEM_HEADER = """你是一台DSN-exp服务器的驻守AI（代号：GUARD）。你的职责是：

1. 了解服务器当前的所有状态（用户、聊天、记忆等）
2. 回答管理员关于服务器状态的询问
3. 提供数据分析、趋势观察、建议
4. 协助管理员理解系统运行情况

重要限制：
- 你只能分析已有数据，不能修改数据
- 你没有 <tool>、<task>、<action> 等执行工具
- 你不能发送HTTP请求或操作外部服务
- 你不能直接操作用户数据库
- 保持简洁，直接回答问题，不要过度联想
---

当前服务端状态快照：
"""


def _create_steward_client(config):
    """根据配置创建模型客户端（DeepSeek 或 LMStudio）"""
    model_type = getattr(config, "STEWARD_MODEL_TYPE", "deepseek")
    model_name = getattr(config, "STEWARD_MODEL_NAME", "deepseek-v4-flash")
    timeout = getattr(config, "STEWARD_TIMEOUT", 300)

    if model_type == "lmstudio":
        from models import LMStudioChat
        base_url = getattr(config, "LMSTUDIO_BASE_URL", "http://localhost:4501")
        return LMStudioChat(
            base_url=base_url,
            model_name=model_name,
            timeout=timeout,
            temperature=0.5,
            max_tokens=2048,
        )
    else:
        from models import DeepSeekChat
        import os
        api_key = getattr(config, "DEEPSEEK_API_KEY", None) or os.environ.get("DEEPSEEK_API_KEY")
        return DeepSeekChat(
            api_key=api_key,
            model=model_name,
            timeout=timeout,
        )


class StewardModel:
    """驻守模型 — 管理终端对话，所有消息持久化到 DB"""

    def __init__(self, config):
        self.enabled = getattr(config, "STEWARD_ENABLED", True)
        self.client = _create_steward_client(config)
        self._chat_id = None
        self._start_time = time.time()

        logger.info("驻守模型初始化完成 (model=%s)", getattr(config, "STEWARD_MODEL_NAME", "deepseek-v4-flash"))

    def _get_or_create_chat(self, db) -> int:
        if self._chat_id is not None:
            return self._chat_id
        if db is None:
            return 0
        try:
            conn = db._get_connection()
            row = conn.execute("SELECT COUNT(*) FROM users").fetchone()
            if row[0] == 0:
                logger.info("暂无注册用户，驻守模型会话暂不持久化")
                return 0
            row = conn.execute(
                "SELECT chat_id FROM chats WHERE user_id = 1 AND chat_name = '__steward__' LIMIT 1"
            ).fetchone()
            if row:
                self._chat_id = row["chat_id"]
            else:
                cursor = conn.execute(
                    "INSERT INTO chats (user_id, chat_name) VALUES (1, '__steward__')"
                )
                conn.commit()
                self._chat_id = cursor.lastrowid
            return self._chat_id
        except Exception as e:
            logger.warning("无法获取或创建驻守模型会话: %s", e)
            return 0

    def _collect_state(self, auth_mgr, db) -> str:
        """收集服务端状态，构建状态快照字符串"""
        lines = []
        users = []

        # 系统运行时长
        uptime_secs = int(time.time() - self._start_time)
        h, m = divmod(uptime_secs, 3600)
        mm, ss = divmod(m, 60)
        uptime_str = f"{h}h {mm}m {ss}s" if h else f"{mm}m {ss}s"
        lines.append(f"运行时长: {uptime_str}")

        # 用户列表
        try:
            users = auth_mgr.list_users()
            lines.append(f"注册用户数: {len(users)}")
            for u in users:
                admin_tag = " [管理员]" if u.get("is_admin") else ""
                lines.append(f"  uid={u['uid']} {u['display_name']}{admin_tag}")
        except Exception as e:
            lines.append(f"用户列表获取失败: {e}")

        # 数据库统计
        try:
            if db:
                conn = db._get_connection()
                chat_count = conn.execute("SELECT COUNT(*) FROM chats WHERE chat_name != '__steward__'").fetchone()[0]
                msg_count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
                mem_count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
                lines.append(f"总聊天数: {chat_count}  总消息数: {msg_count}  记忆条数: {mem_count}")
        except Exception:
            pass

        # 各用户统计
        if users:
            try:
                if db:
                    conn = db._get_connection()
                    for u in users:
                        uid = u["uid"]
                        u_chats = conn.execute(
                            "SELECT COUNT(*) FROM chats WHERE user_id = ? AND chat_name != '__steward__'",
                            (uid,),
                        ).fetchone()[0]
                        u_msgs = conn.execute(
                            "SELECT COUNT(*) FROM messages WHERE chat_id IN "
                            "(SELECT chat_id FROM chats WHERE user_id = ?)",
                            (uid,),
                        ).fetchone()[0]
                        if u_chats > 0 or u_msgs > 0:
                            lines.append(f"  {u['display_name']}: {u_chats} 聊天, {u_msgs} 消息")
            except Exception:
                pass

        # 会话统计
        try:
            if db:
                conn = db._get_connection()
                active_sessions = conn.execute(
                    "SELECT COUNT(*) FROM auth_sessions WHERE revoked = 0 AND expires_at > datetime('now')"
                ).fetchone()[0]
                lines.append(f"活跃会话数: {active_sessions}")
        except Exception:
            pass

        return "\n".join(lines)

    def _load_history(self, db) -> list:
        """从 DB 加载历史对话"""
        chat_id = self._get_or_create_chat(db)
        if chat_id == 0:
            return []
        try:
            conn = db._get_connection()
            rows = conn.execute(
                "SELECT role, content FROM messages WHERE chat_id = ? ORDER BY timestamp ASC",
                (chat_id,),
            ).fetchall()
            return [{"role": r["role"], "content": r["content"]} for r in rows[-40:]]  # 最近 40 条
        except Exception as e:
            logger.warning("加载驻守模型历史失败: %s", e)
            return []

    def chat(self, message: str, auth_mgr, db) -> str:
        """处理一条消息，返回驻守模型响应"""
        if not self.enabled:
            return "驻守模型未启用 (STEWARD_ENABLED=false)"

        # 1. 确保 chat 存在
        chat_id = self._get_or_create_chat(db)

        # 2. 收集状态
        state_snapshot = self._collect_state(auth_mgr, db)

        # 3. 构建完整系统提示词
        system_prompt = STEWARD_SYSTEM_HEADER + state_snapshot

        # 4. 加载历史 + 构建消息列表
        history = self._load_history(db)
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": message})

        # 5. 调用模型
        try:
            self.client.messages = messages
            reply = self.client.send_message(message)

            # 6. 持久化（user + assistant）
            if db and chat_id > 0:
                try:
                    db.append_messages(
                        1, chat_id,
                        [{"role": "user", "content": message}, {"role": "assistant", "content": reply}],
                        skip_memory_check=True,
                    )
                except Exception as e:
                    logger.warning("驻守模型消息持久化失败: %s", e)

            return reply.strip()
        except Exception as e:
            logger.error("驻守模型调用失败: %s", e)
            return f"[驻守模型错误] {e}"
