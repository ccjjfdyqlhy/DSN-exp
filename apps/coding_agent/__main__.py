# apps/coding_agent/__main__.py
# 终端入口: python -m apps.coding_agent
#
# 用 OpenAI 兼容 API 驱动 coding agent（无需任何 DSN 依赖）。

from __future__ import annotations

import os

from harness.models.openai import OpenAICompatClient


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
