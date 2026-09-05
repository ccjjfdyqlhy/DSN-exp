# tests/test_emotion_exp.py
# 针对 apps/emotion_exp 的自动化单元与集成测试

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness.context_assembly import ContextBudget
from harness.models.stub import StubChatClient
from apps.emotion_exp.emotion_engine import EmotionEngine, EmotionalState
from apps.emotion_exp.topic_manager import HarnessTopicContextManager
from apps.emotion_exp.app import EmotionExpAgent


class TestEmotionExp(unittest.TestCase):
    def test_emotion_engine_dynamics(self):
        engine = EmotionEngine(EmotionalState(joy=0.5, meta=0.5))
        # 受到愉悦刺激
        engine.apply_stimulus(delta_joy=0.3)
        self.assertGreater(engine.state.joy, 0.7)
        dom, val = engine.state.dominant_emotion()
        self.assertEqual(dom, "开心")

        # 情绪衰减测试
        engine.decay()
        self.assertLess(engine.state.joy, 0.8)

    def test_topic_manager_segmented_assembly(self):
        budget = ContextBudget(memo_chars=100, summary_chars=200, verbatim_chars=500)
        mgr = HarnessTopicContextManager(budget=budget)
        mgr.add_memo("全局常驻备忘：主人喜欢喝咖啡。")

        # 第一轮对话
        mgr.record_turn("你好，我想聊聊宇宙。", "宇宙浩瀚无垠。")
        cur_id = mgr.current_topic_id
        self.assertIsNotNone(cur_id)

        # 组装上下文验证
        msgs = mgr.assemble_context_messages("黑洞是什么？", system_prefix="你是助手。")
        # 验证消息条目包含 system, memo, verbatim, user 等
        contents = [m.content for m in msgs]
        self.assertTrue(any("全局常驻备忘" in c for c in contents))
        self.assertTrue(any("宇宙浩瀚无垠" in c for c in contents))
        self.assertEqual(msgs[-1].content, "黑洞是什么？")

        # 测试关闭话题与生成摘要
        mgr.close_topic(cur_id, summary="讨论了宇宙的起源与范围。")
        self.assertEqual(mgr.topics[cur_id].status, "closed")

    def test_emotion_agent_chat_loop(self):
        from harness.models.base import ChatResponse
        stub_client = StubChatClient(responses=[ChatResponse(content="收到，今天心情很好！")])
        agent = EmotionExpAgent(stub_client)
        agent.topic_mgr.add_memo("重要设定：Agent是一个温柔的助手。")

        # 发送开心消息，触发刺激
        reply = agent.chat("太棒了，今天真开心！")
        self.assertEqual(reply, "收到，今天心情很好！")
        self.assertGreater(agent.emotion.state.joy, 0.6)

    def test_persistence_reload(self):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            db_path = tmp.name
            from harness.models.base import ChatResponse
            stub_client = StubChatClient(responses=[
                ChatResponse(content="我记住了！"),
                ChatResponse(content="恢复后依然记得。"),
            ])
            # 第一次启动 agent
            agent1 = EmotionExpAgent(stub_client, db_path=db_path)
            agent1.topic_mgr.add_memo("持久化备忘：喜欢量子力学")
            agent1.chat("记录这条对话")
            agent1.emotion.apply_stimulus(delta_joy=0.2)
            if agent1.store:
                agent1.store.save_emotion(
                    agent1.emotion.state.joy,
                    agent1.emotion.state.sorrow,
                    agent1.emotion.state.anger,
                    agent1.emotion.state.fear,
                    agent1.emotion.state.meta,
                )

            cur_tid = agent1.topic_mgr.current_topic_id

            # 第二次启动 agent，重新从 db 加载
            agent2 = EmotionExpAgent(stub_client, db_path=db_path)
            self.assertEqual(len(agent2.topic_mgr.memos), 1)
            self.assertIn("喜欢量子力学", agent2.topic_mgr.memos[0])
            self.assertIn(cur_tid, agent2.topic_mgr.topics)
            self.assertEqual(len(agent2.topic_mgr.topics[cur_tid].messages), 2)
            self.assertAlmostEqual(agent2.emotion.state.joy, agent1.emotion.state.joy, places=2)

    def test_stream_chat(self):
        import asyncio
        from harness.models.base import ChatResponse
        stub_client = StubChatClient(responses=[ChatResponse(content="流式回复测试文本")])
        agent = EmotionExpAgent(stub_client)

        chunks = []
        async def _run():
            async for chunk in agent.chat_stream("你好"):
                chunks.append(chunk)

        asyncio.run(_run())
        self.assertEqual("".join(chunks), "流式回复测试文本")

        # 检查话题记录
        cur_topic = agent.topic_mgr.get_or_create_current_topic()
        self.assertEqual(len(cur_topic.messages), 2)


    def test_pev3_integration(self):
        """测试 PEV3 引擎在 EmotionExpAgent 中的无缝协同"""
        import tempfile
        from harness.personality import CharacterCard, NaturalLanguage
        from harness.models.base import ChatResponse

        with tempfile.TemporaryDirectory() as tmpdir:
            cards_dir = os.path.join(tmpdir, "cards")
            os.makedirs(cards_dir, exist_ok=True)
            db_path = os.path.join(tmpdir, "test.db")

            # 写入一张测试角色卡
            card = CharacterCard(
                card_id="test_bot",
                name="小艾",
                display_name="小艾",
                natural_language=NaturalLanguage(
                    personality="性格温柔善解人意，喜欢与人探讨科学哲学。",
                    speech_style="语气温和而略带调皮。",
                ),
            )
            card.to_yaml_file(os.path.join(cards_dir, "test_bot.yaml"))

            stub_client = StubChatClient(responses=[
                ChatResponse(content="Personality Section:\n小艾现在心情不错"),
                ChatResponse(content="很高兴能和你交流！"),
                ChatResponse(content='{"event_type": "praise", "intensity": "high", "valence": "positive", "attribution": "用户赞赏", "analysis": "积极反馈"}'),
            ])

            agent = EmotionExpAgent(
                client=stub_client,
                personality_client=stub_client,
                cards_dir=cards_dir,
                default_card_path=os.path.join(cards_dir, "test_bot.yaml"),
                db_path=db_path,
                uid=1,
            )

            # 1. 验证角色卡与绑定状态
            self.assertEqual(agent.pv3.get_personality_status(1)["card_id"], "test_bot")

            # 2. 验证系统提示词中包含角色卡内容与情绪感知
            sys_prompt = agent._build_full_system_prompt()
            self.assertIn("【当前内心状态】", sys_prompt)

            # 3. 产生一轮对话并触发动力学分析与事件审计
            reply = agent.chat("你真棒！")
            self.assertEqual(reply, "很高兴能和你交流！")

            # 4. 验证亲密度和心境发生演化
            stat = agent.pv3.get_personality_status(1)
            self.assertGreaterEqual(stat.get("total_interactions", 0), 1)
            recent_audit = agent.pv3.get_recent_events(uid=1)
            self.assertGreaterEqual(len(recent_audit), 1)
            self.assertEqual(recent_audit[0]["event_type"], "praise")

    def test_blank_card_evolution_default(self):
        """测试空白角色卡（随机性格参数）默认启动与自演化能力"""
        import tempfile
        from harness.personality import CharacterCard, random_indicator_vector
        from harness.models.base import ChatResponse

        with tempfile.TemporaryDirectory() as tmpdir:
            cards_dir = os.path.join(tmpdir, "cards")
            db_path = os.path.join(tmpdir, "test_blank.db")

            stub_client = StubChatClient(responses=[
                ChatResponse(content="Personality Section:\n空白伴侣感知中"),
                ChatResponse(content="我是你的新伙伴，很高兴认识你！"),
                ChatResponse(content='{"event_type": "personal_sharing", "intensity": "high", "valence": "positive", "attribution": "深度倾诉", "analysis": "信任建立"}'),
            ])

            # 在没有任何角色卡的情况下启动，默认自动生成空白角色卡（随机性格参数）
            agent = EmotionExpAgent(
                client=stub_client,
                personality_client=stub_client,
                cards_dir=cards_dir,
                db_path=db_path,
                uid=101,
            )

            # 1. 验证默认绑定的角色卡为 blank_companion，且具备随机化的 50 维特质
            stat = agent.pv3.get_personality_status(101)
            self.assertEqual(stat["card_id"], "blank_companion")
            card = agent.pv3.get_card("blank_companion")
            self.assertIsNotNone(card)
            self.assertTrue(len(card.manual_overrides) >= 50)
            self.assertEqual(card.name, "初始伴侣")

            # 2. 初始快照能正确承载随机性格参数
            full_stat = agent.pv3.get_personality_full(101)
            self.assertIn("A1", full_stat["indicator_vector"])

            # 3. 对话交互并触发贝叶斯累积演化
            reply = agent.chat("我今天心里有些秘密想跟你分享...")
            self.assertEqual(reply, "我是你的新伙伴，很高兴认识你！")

            # 4. 验证演化证据已被记录且成熟度开始计算
            stat_after = agent.pv3.get_personality_status(101)
            self.assertGreaterEqual(stat_after.get("total_interactions", 0), 1)
            self.assertGreaterEqual(stat_after.get("evidence_total", 0), 1)
            self.assertIsNotNone(stat_after.get("maturity"))

            # 5. 验证主动调用 create_blank_card 和 consolidate 机制
            blank2 = agent.pv3.create_blank_card("custom_blank", name="自定白纸", seed=12345)
            self.assertEqual(blank2.card_id, "custom_blank")
            self.assertTrue(os.path.exists(os.path.join(cards_dir, "custom_blank.yaml")))


if __name__ == "__main__":
    unittest.main()
