# apps/coding_agent/__main__.py
# 终端入口: python -m apps.coding_agent
#
# 用 OpenAI 兼容 API 驱动 coding agent（无需任何 DSN 依赖）。

from __future__ import annotations

import os
from pathlib import Path

from infra.models.openai import OpenAICompatClient

# 与其他应用保持一致：优先读取仓库根目录的 .env。
# 这样 onboarding.py 写入的模型配置对 `python -m apps.coding_agent` 也生效。
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except ImportError:  # 没装 python-dotenv 时仍然可以直接用环境变量
    pass


def _build_client() -> OpenAICompatClient:
    return OpenAICompatClient(
        api_key=os.environ.get("OPENAI_API_KEY", ""),
        base_url=os.environ.get("OPENAI_API_BASE", "https://api.deepseek.com/v1"),
        model=os.environ.get("MAIN_MODEL_NAME", "deepseek-v4-flash"),
    )


def main() -> None:
    from .app import CodingAgent

    agent = CodingAgent(_build_client())
    agent.enable_persistence(db_path=os.environ.get("CODING_AGENT_DB", ":memory:"))

    print("CodingAgent 已启动。输入问题，Ctrl+C 退出。")
    print(f"工具: {sorted(agent.agent.tools.names())}")
    while True:
        try:
            line = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line in ("exit", "quit"):
            break
        try:
            print(agent.chat(line))
        except Exception as e:  # noqa: BLE001
            print(f"[错误] {e}")


if __name__ == "__main__":
    main()
