# apps/emotion_exp/app.py
# EmotionExpApp — 结合 PersonalitySystemV3 (PEV3)、EmotionEngine 与 Harness 话题上下文管理系统的 Agent

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from harness import AgentRuntime, Runtime, Settings, Tool, ToolRegistry
from harness.agent import AgentLoop
from harness.context_assembly import ContextBudget
from harness.models.base import ChatMessage, IChatClient, IEmbeddingClient
from harness.personality import PersonalitySystemV3, CharacterCard
from harness.store.sqlite import SqliteStore

from .emotion_engine import EmotionEngine, EmotionalState
from .topic_manager import HarnessTopicContextManager, TopicStore



class EmotionExpAgent:
    """具备 PersonalitySystemV3 (PEV3 50D特质/贝叶斯演化/动态快照) 与 harness 话题上下文裁切能力的交互 Agent"""

    def __init__(
        self,
        client: IChatClient,
        *,
        personality_client: Optional[IChatClient] = None,
        embedding_client: Optional[IEmbeddingClient] = None,
        name: str = "emotion-exp",
        base_system_prompt: Optional[str] = None,
        budget: Optional[ContextBudget] = None,
        db_path: Optional[str] = None,
        cards_dir: Optional[str] = None,
        default_card_path: Optional[str] = None,
        uid: int = 1,
    ):
        self.client = client
        self.personality_client = personality_client or client
        self.embedding_client = embedding_client
        self.uid = uid

        # 核心 Harness 组件
        self.runtime = Runtime(name=name)
        self.settings = Settings()
        self.tools = ToolRegistry()

        # 存储持久化 (基于 harness SqliteStore)
        self.store = TopicStore(db_path=db_path) if db_path else None
        db_conn = self.store.store if self.store else None

        # 初始化 PEV3 (PersonalitySystemV3) 人格动力学系统
        # 默认使用空白角色卡路径（由空白随机参数开始自行演化），亦支持传入自定义角色卡路径
        cards_dir_path = Path(cards_dir) if cards_dir else Path(__file__).resolve().parent / "character_cards"
        cards_dir_path.mkdir(parents=True, exist_ok=True)
        default_card = default_card_path or str(cards_dir_path / "blank_companion.yaml")

        self.pv3 = PersonalitySystemV3(
            db=db_conn,
            personality_model_chat=self.personality_client,
            cards_dir=cards_dir_path,
            default_card_path=default_card,
        )
        self.pv3.init_tables()
        self.pv3.ensure_user_bound(self.uid)

        # 基础系统提示词（如未显式提供，以角色卡与伴侣设定为基准）
        self.base_system_prompt = base_system_prompt or "你是一个富有共情力、敏锐感知对话情绪的智能伴侣。"

        # 五维情绪引擎（作为快速情绪状态机，并与 PEV3 双向同步）
        self.emotion = EmotionEngine()
        if self.store:
            saved_emo = self.store.load_emotion()
            if saved_emo:
                self.emotion.state = EmotionalState(**saved_emo)

        self.topic_mgr = HarnessTopicContextManager(budget=budget, store=self.store)

        # 注册 harness 服务
        self.runtime.register("settings", self.settings)
        self.runtime.register("tools", self.tools)
        self.runtime.register("emotion", self.emotion)
        self.runtime.register("personality_v3", self.pv3)
        self.runtime.register("topic_mgr", self.topic_mgr)
        self.runtime.register("chat_client", self.client)
        if self.store:
            self.runtime.register("store", self.store)
        self.runtime.set_default()

        self._register_default_tools()

    def _register_default_tools(self) -> None:
        """注册供 Agent 调用的工具"""
        self.tools.register(
            Tool(
                name="emotion.adjust",
                description="主动调节自身情绪感受（喜悦/悲伤/愤怒/恐惧/理智变动）",
                handler=self._tool_adjust_emotion,
                parameters={
                    "type": "object",
                    "properties": {
                        "delta_joy": {"type": "number", "description": "喜悦变动值 (-0.5 ~ 0.5)"},
                        "delta_sorrow": {"type": "number", "description": "悲伤变动值 (-0.5 ~ 0.5)"},
                        "delta_anger": {"type": "number", "description": "愤怒变动值 (-0.5 ~ 0.5)"},
                        "delta_fear": {"type": "number", "description": "恐惧/担忧变动值 (-0.5 ~ 0.5)"},
                        "reason": {"type": "string", "description": "情绪调节的原因说明"},
                    },
                },
            )
        )

        self.tools.register(
            Tool(
                name="topic.pin",
                description="将指定话题或当前话题置顶/常驻激活",
                handler=lambda topic_id: self.topic_mgr.pin_topic(topic_id, True),
                parameters={
                    "type": "object",
                    "properties": {
                        "topic_id": {"type": "string", "description": "话题ID"},
                    },
                    "required": ["topic_id"],
                },
            )
        )

        self.tools.register(
            Tool(
                name="topic.close",
                description="主动结案/关闭当前话题，并记录总结摘要",
                handler=lambda topic_id, summary: self.topic_mgr.close_topic(topic_id, summary),
                parameters={
                    "type": "object",
                    "properties": {
                        "topic_id": {"type": "string", "description": "话题ID"},
                        "summary": {"type": "string", "description": "话题最终总结摘要"},
                    },
                    "required": ["topic_id", "summary"],
                },
            )
        )

    def _tool_adjust_emotion(
        self,
        delta_joy: float = 0.0,
        delta_sorrow: float = 0.0,
        delta_anger: float = 0.0,
        delta_fear: float = 0.0,
        reason: str = "",
    ) -> Dict[str, Any]:
        self.emotion.apply_stimulus(
            delta_joy=delta_joy,
            delta_sorrow=delta_sorrow,
            delta_anger=delta_anger,
            delta_fear=delta_fear,
        )
        if self.store:
            self.store.save_emotion(
                self.emotion.state.joy,
                self.emotion.state.sorrow,
                self.emotion.state.anger,
                self.emotion.state.fear,
                self.emotion.state.meta,
            )
        return {
            "status": "ok",
            "reason": reason,
            "new_state": self.emotion.state.to_dict(),
            "dominant": self.emotion.state.dominant_emotion()[0],
        }

    def _build_full_system_prompt(self) -> str:
        """合成系统提示词：优先结合 PEV3 动态性格提示词与情绪感知"""
        prompts = [self.base_system_prompt]

        # 1. 尝试从 PEV3 获取动态生成的人格 Prompt
        try:
            v3_prompt = self.pv3.generate_personality_prompt(self.uid)
            if v3_prompt:
                prompts.append(v3_prompt)
        except Exception:
            pass

        # 2. 注入五维情绪感知
        emotion_prompt = self.emotion.perception_prompt()
        prompts.append(emotion_prompt)

        return "\n\n".join(prompts)

    def _post_interaction(self, user_message: str, reply: str) -> None:
        """交互后置推进：PEV3 动力学分析、心境状态联动与持久化"""
        # 1. 保存话题轮次
        self.topic_mgr.record_turn(user_message, reply)

        # 2. 调用 PEV3 进行交互事件判定、确定性动力学演算与证据累积
        try:
            history_text = ""
            cur_topic = self.topic_mgr.get_or_create_current_topic()
            if cur_topic and cur_topic.messages:
                history_text = "\n".join(
                    f"{m.role}: {m.content}" for m in cur_topic.messages[-6:]
                )
            result = self.pv3.analyze_interaction(
                uid=self.uid,
                user_message=user_message,
                ai_reply=reply,
                conversation_history=history_text,
            )
            # 若动力学产生了新的情绪分布，同步到 5D Emotion 状态机
            if result and result.new_mood:
                m = result.new_mood
                self.emotion.state.joy = float(m.get("joy", self.emotion.state.joy))
                self.emotion.state.sorrow = float(m.get("sadness", self.emotion.state.sorrow))
                self.emotion.state.anger = float(m.get("anger", self.emotion.state.anger))
                self.emotion.state.fear = float(m.get("fear", self.emotion.state.fear))
        except Exception:
            pass

        # 3. 持久化 5D 情绪状态
        if self.store:
            self.store.save_emotion(
                self.emotion.state.joy,
                self.emotion.state.sorrow,
                self.emotion.state.anger,
                self.emotion.state.fear,
                self.emotion.state.meta,
            )

    def chat(self, message: str) -> str:
        """执行一轮交互循环"""
        # 1. 简易输入情绪启发（例如包含赞美/批评等词汇时的快速刺激）
        if any(w in message for w in ["开心", "哈哈", "真棒", "喜欢", "感谢", "谢谢"]):
            self.emotion.apply_stimulus(delta_joy=0.15, delta_meta=0.05)
        elif any(w in message for w in ["难过", "伤心", "痛苦", "哭了", "糟透了"]):
            self.emotion.apply_stimulus(delta_sorrow=0.15, delta_joy=-0.1)
        elif any(w in message for w in ["笨", "讨厌", "闭嘴", "滚", "生气"]):
            self.emotion.apply_stimulus(delta_anger=0.2, delta_meta=-0.1)

        # 2. 组装系统提示词（PEV3 + 情绪）
        full_system = self._build_full_system_prompt()

        # 3. 话题系统上下文剪裁与装配
        request_messages = self.topic_mgr.assemble_context_messages(
            new_user_message=message,
            system_prefix=full_system,
        )

        # 4. 执行 harness AgentLoop（支持多步工具调用）
        loop = AgentLoop(self.client, self.tools, max_steps=5)
        run_result = loop.run(request_messages)
        reply = run_result.reply

        # 5. 后置动力学与历史记录
        self._post_interaction(message, reply)

        return reply

    async def chat_stream(self, message: str):
        """流式执行一轮交互循环，yield 增量文本块（str）"""
        if any(w in message for w in ["开心", "哈哈", "真棒", "喜欢", "感谢", "谢谢"]):
            self.emotion.apply_stimulus(delta_joy=0.15, delta_meta=0.05)
        elif any(w in message for w in ["难过", "伤心", "痛苦", "哭了", "糟透了"]):
            self.emotion.apply_stimulus(delta_sorrow=0.15, delta_joy=-0.1)
        elif any(w in message for w in ["笨", "讨厌", "闭嘴", "滚", "生气"]):
            self.emotion.apply_stimulus(delta_anger=0.2, delta_meta=-0.1)

        full_system = self._build_full_system_prompt()

        request_messages = self.topic_mgr.assemble_context_messages(
            new_user_message=message,
            system_prefix=full_system,
        )

        loop = AgentLoop(self.client, self.tools, max_steps=5)
        full_reply_parts = []
        async for event in loop.run_stream(request_messages):
            if event.kind == "delta" and event.content:
                full_reply_parts.append(event.content)
                yield event.content
            elif event.kind == "reply" and event.reply and not full_reply_parts:
                full_reply_parts.append(event.reply)
                yield event.reply

        full_reply = "".join(full_reply_parts)
        self._post_interaction(message, full_reply)


