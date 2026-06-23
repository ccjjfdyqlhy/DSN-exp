# self_evolution entry.py
# 独立入口 — 启动即按 schedule 运行 AI 代码贡献任务

import os
import sys
import logging
import argparse

# 确保可以从项目根目录 import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from engine import DSNEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

logger = logging.getLogger("self_evolution")


def main():
    parser = argparse.ArgumentParser(description="EVO - 自我演化 AI 代码贡献者")
    parser.add_argument(
        "--mode", choices=["scheduled", "once", "interactive"], default=None,
        help="运行模式 (默认读取 subapp.yaml 中的配置)",
    )
    parser.add_argument(
        "--repo", type=str, default=None,
        help="目标 GitHub 仓库 URL（覆盖默认）",
    )
    parser.add_argument(
        "--message", "-m", type=str, default=None,
        help="单次对话消息（--mode once 使用）",
    )
    args = parser.parse_args()

    subapp_dir = os.path.dirname(os.path.abspath(__file__))
    logger.info("启动 SubApp 目录: %s", subapp_dir)

    engine = DSNEngine(subapp_path=subapp_dir)

    info = engine.get_info()
    logger.info("引擎就绪: %s v%s, model=%s, skills=%d",
                info["name"], info["version"], info["model"],
                len(info["skills"]))

    mode = args.mode or engine._cfg.mode

    if mode == "once":
        message = args.message or engine._cfg.schedule_prompt or "请分析仓库并做出代码改进"
        logger.info("单次执行: %s", message[:80])
        result = engine.chat(message=message, user_id=0, chat_name="oneshot")
        print("\n", "-" * 60)
        print("回复:", result["reply"][:2000])
        print("-" * 60)

    elif mode == "interactive":
        print("EVO 交互模式 - 输入消息对话 (输入 /quit 退出)")
        chat_id = engine.create_chat(user_id=0, chat_name="interactive")
        history = []
        while True:
            try:
                msg = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if msg.lower() == "/quit":
                break
            if not msg:
                continue
            result = engine.chat(
                message=msg, user_id=0, chat_id=chat_id,
                history=history, chat_name="interactive",
            )
            history = engine.get_history(user_id=0, chat_id=chat_id)
            print("\n", result["reply"][:2000])

    elif mode == "scheduled":
        import schedule
        import time

        from utils.subapp_loader import load_subapp_config
        cfg = load_subapp_config(subapp_dir)

        target_repo = args.repo or cfg.extra.get("_raw", {}).get("repo", "")
        cron_expr = args.cron if hasattr(args, 'cron') and args.cron else cfg.schedule_cron

        if not cron_expr:
            logger.error("scheduled 模式需要设置 schedule.cron")
            return

        logger.info("定时调度: %s", cron_expr)

        prompt = cfg.schedule_prompt
        if target_repo:
            prompt = f"目标仓库: {target_repo}\n\n{prompt}"

        chat_id = engine.create_chat(user_id=0, chat_name="daily_pr")

        def daily_job():
            logger.info("=== 每日 PR 任务触发 ===")
            try:
                result = engine.chat(
                    message=prompt, user_id=0, chat_id=chat_id,
                    chat_name="daily_pr", agent_active=True,
                )
                logger.info("任务完成: %s", result.get("reply", "")[:100])
                steps = result.get("extra", {}).get("agent_steps_executed", 0)
                logger.info("Agent 步数: %d", steps)
            except Exception as e:
                logger.error("任务失败: %s", e)

        parts = cron_expr.strip().split()
        if len(parts) == 5:
            hh, mm = parts[1].zfill(2), parts[0].zfill(2)
        else:
            hh, mm = "09", "00"

        schedule.every().day.at(f"{hh}:{mm}").do(daily_job)
        logger.info("下次执行时间: 每天 %s:%s", hh, mm)

        daily_job()

        while True:
            schedule.run_pending()
            time.sleep(30)

    else:
        logger.error("未知运行模式: %s", mode)


if __name__ == "__main__":
    main()
