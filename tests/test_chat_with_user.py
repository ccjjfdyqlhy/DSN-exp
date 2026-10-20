# tests/test_chat_with_user.py
# 手动联调脚本：真实登录 littleskin → 拉取用户 → 发一次对话 → 落库。
#
# 这是一个**需要真实凭据与网络**的手动脚本，不是单元测试：
#   * 它在导入期就会执行（pytest 收集时也会跑模块级代码）；
#   * 没有可断言的输出，失败方式不确定。
#
# 安全说明（2026-10 修复）：
#   原文件把 littleskin 的 client_secret 与一个 sk- 开头的 API Key 明文写死在这里，
#   且该文件已被 git 跟踪 —— 等同凭据泄漏。现已全部改为从环境变量读取。
#   **历史提交里仍残留旧值，相关凭据必须轮换后才算处置完毕。**
#
# 用法:
#   export DSN_LITTLESKIN_CLIENT_ID=...
#   export DSN_LITTLESKIN_CLIENT_SECRET=...
#   export OPENAI_API_KEY=...
#   python tests/test_chat_with_user.py
#
# 未设置必需环境变量时脚本会直接退出（exit 0），不会失败、也不会发起网络请求。

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _require(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


def main() -> int:
    client_id = _require("DSN_LITTLESKIN_CLIENT_ID")
    client_secret = _require("DSN_LITTLESKIN_CLIENT_SECRET")
    api_key = _require("OPENAI_API_KEY")

    missing = [
        name
        for name, value in (
            ("DSN_LITTLESKIN_CLIENT_ID", client_id),
            ("DSN_LITTLESKIN_CLIENT_SECRET", client_secret),
            ("OPENAI_API_KEY", api_key),
        )
        if not value
    ]
    if missing:
        print("跳过：缺少环境变量 " + ", ".join(missing))
        print("这是手动联调脚本，需要真实凭据；详见文件头注释。")
        return 0

    from apps.dsn.api.auth import UserManager
    from apps.dsn.db.chat import ChatDBManager
    from apps.dsn.models import OpenAIChat

    # 1. 登录
    um = UserManager(client_id=int(client_id), client_secret=client_secret)
    user_info = um.login(timeout=120)
    if not user_info:
        print("登录失败或超时")
        return 1

    uid = user_info["uid"]
    nickname = user_info["nickname"]

    # 2. 同步用户到数据库
    db = ChatDBManager()
    db.add_or_update_user(uid, nickname)

    try:
        # 3. 进行对话
        chat = OpenAIChat(api_key=api_key)
        chat.send_message("你好")
        chat.send_message("介绍一下自己")

        # 4. 保存对话历史
        history = chat.get_history()
        chat_id = db.save_chat_history(uid, "初次对话", history)
        print(f"聊天已保存，ID: {chat_id}")

        # 5. 列出该用户的所有聊天
        for c in db.list_chats(uid):
            print(f"聊天: {c['chat_name']} (ID: {c['chat_id']}), 消息数: {c['message_count']}")
    finally:
        db.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
