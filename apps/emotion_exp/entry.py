# apps/emotion_exp/entry.py
# emotion_exp 入口模块，兼容 launcher.py

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from harness.models.openai import OpenAICompatClient
from harness.models.stub import StubChatClient
from .app import EmotionExpAgent

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = str(ROOT / ".emotion_exp.db")


def _build_client():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("[提示] 未检测到 OPENAI_API_KEY，使用本地 Stub 测试模型。")
        from harness.models.base import ChatResponse
        return StubChatClient(responses=[
            ChatResponse(content="你好！我感受到了你的问候，今天有什么想聊的吗？"),
            ChatResponse(content="听到这件事我为你感到高兴！"),
            ChatResponse(content="无论发生什么，我都一直在你身边。"),
        ])

    return OpenAICompatClient(
        api_key=api_key,
        base_url=os.environ.get("OPENAI_API_BASE", "https://api.deepseek.com/v1"),
        model=os.environ.get("MAIN_MODEL_NAME", "deepseek-chat"),
    )


async def _stream_chat(agent: EmotionExpAgent, line: str) -> None:
    dom, _ = agent.emotion.state.dominant_emotion()
    p_stat = agent.pv3.get_personality_status(agent.uid)
    aff = p_stat.get("affinity_value", 20.0)
    stage_info = p_stat.get("affinity_level", {})
    stage = stage_info.get("label", "初识")
    print(f"\n[EmotionAgent | {dom} | {stage} (亲和: {aff:.0f})]> ", end="", flush=True)
    try:
        async for chunk in agent.chat_stream(line):
            print(chunk, end="", flush=True)
        print()
    except Exception as e:
        print(f"\n[流式错误，回退普通调用]: {e}")
        reply = agent.chat(line)
        print(reply)


def main() -> None:
    db_path = os.environ.get("EMOTION_EXP_DB", DEFAULT_DB)
    client = _build_client()
    agent = EmotionExpAgent(client, db_path=db_path)

    # 预设一条常驻备忘（若无则添加）
    if not agent.topic_mgr.memos:
        agent.topic_mgr.add_memo("用户是本系统的创作者与伙伴，喜欢探索大模型前沿技术架构。")

    dom, val = agent.emotion.state.dominant_emotion()
    p_stat = agent.pv3.get_personality_status(agent.uid)
    card_id = p_stat.get("card_id", "blank_companion")
    card = agent.pv3.get_card(card_id)
    card_name = card.name if card else "初始伴侣"
    aff = p_stat.get("affinity_value", 20.0)
    stage_info = p_stat.get("affinity_level", {})
    stage = stage_info.get("label", "初识")

    print("\n==============================================")
    print(" EmotionExp Agent 已就绪 (基于 Harness 基座 + PEV3 引擎)")
    print(f" - 持久化存储已连接: {db_path}")
    print(f" - 人格系统 (PEV3): [{card_name} ({card_id})] 亲密度: {aff:.0f} | 关系阶段: {stage}")
    print(f" - 当前已恢复话题: {len(agent.topic_mgr.topics)} 个，活跃话题: {agent.topic_mgr.current_topic_id}")
    print(f" - 当前恢复心境: {dom} ({val:.2f})")
    print(" - 支持流式打字输出与确定性动力学/贝叶斯证据累积")
    print(" - 输入消息开始对话，输入 /status 查看状态，exit 退出")
    print("==============================================\n")

    while True:
        try:
            line = input("\n[User]> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n退出中...")
            break

        if not line:
            continue
        if line.lower() in ("exit", "quit"):
            break

        if line == "/status":
            st = agent.emotion.state.to_dict()
            dom, val = agent.emotion.state.dominant_emotion()
            p_stat = agent.pv3.get_personality_status(agent.uid)
            c_id = p_stat.get("card_id", "blank_companion")
            card = agent.pv3.get_card(c_id)
            c_name = card.name if card else "初始伴侣"
            aff = p_stat.get("affinity_value", 20.0)
            stage_info = p_stat.get("affinity_level", {})
            stage_label = stage_info.get("label", "初识")
            print("----------------------------------------------")
            print(f"当前外显心境: {dom} ({val:.2f})")
            print(f"五维心境向量: {st}")
            print(f"PEV3 角色卡: {c_name} ({p_stat.get('card_id')})")
            print(f"PEV3 亲密度: {aff:.1f} / 100 ({stage_label})")
            print(f"PEV3 互动轮次: {p_stat.get('total_interactions', 0)} 次")
            if p_stat.get("labels"):
                # labels 是 dict[str, str]，如 {"dim_id": "偏内向"}
                labels_dict = p_stat.get("labels", {})
                labels_list = [f"{k}:{v}" for k, v in list(labels_dict.items())[:5]]
                print(f"显著特质标签: {', '.join(labels_list)}")
            recent_evs = p_stat.get("recent_events", [])
            if recent_evs:
                print(f"最近动力学事件: {[e.get('event_type') + '/' + e.get('intensity') for e in recent_evs[:3]]}")
            print(f"已持久化话题数: {len(agent.topic_mgr.topics)}, 当前话题: {agent.topic_mgr.current_topic_id}")
            if agent.topic_mgr.current_topic_id and agent.topic_mgr.current_topic_id in agent.topic_mgr.topics:
                top = agent.topic_mgr.topics[agent.topic_mgr.current_topic_id]
                print(f"当前话题消息条数: {len(top.messages)} 条")
            print("----------------------------------------------")
            continue

        try:
            asyncio.run(_stream_chat(agent, line))
        except Exception as e:
            print(f"[运行时错误]: {e}")


if __name__ == "__main__":
    main()

