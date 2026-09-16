# apps/dsn_ui/agent.py
"""DSN-UI 综合 Agent 引擎：
整合弹性话题记忆（TopicManager + SegmentedContextAssembler）、情绪动力学（EmotionEngine）、
人格特质系统（PersonalitySystemV3）、harness 工具系统（ToolboxManager 两阶段激活）与模型推理。
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

from apps.dsn_ui.emotion import DSNUIEmotionEngine, EmotionalState
from apps.dsn_ui.tools import DSNUIToolCoordinator
from apps.dsn_ui.topic_manager import DSNUITopicContextManager, DSNUITopicStore
from harness.agent.loop import AgentLoop, StreamEvent
from harness.agent.adapters import NativeToolCallAdapter
from harness.orchestrator import (
    ChatMessage,
    ChatResponse,
    IChatClient,
    ModelOrchestrator,
    ToolCall,
)
from harness.personality import PersonalitySystemV3
from harness.store.sqlite import SqliteStore

logger = logging.getLogger("DSNUIAgent")


class OrchestratorChatClientWrapper(IChatClient):
    """将 ModelOrchestrator 包装为标准 IChatClient 接口。"""

    def __init__(
        self,
        orchestrator: ModelOrchestrator,
        model_name: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ):
        self.orchestrator = orchestrator
        self.model_name = model_name
        self.temperature = temperature
        # 默认最大输出 tokens 设为当前加载模型支持的上下文长度
        self.max_tokens = max_tokens or orchestrator.get_model_ctx_size(model_name)

    def invoke(self, messages: list[ChatMessage], tools: Optional[list[dict]] = None, **kwargs) -> ChatResponse:
        eff_tokens = kwargs.get("max_tokens") or self.max_tokens
        return self.orchestrator.invoke(
            messages,
            model_name=self.model_name,
            temperature=self.temperature,
            max_tokens=eff_tokens,
            tools=tools,
            **kwargs,
        )

    async def stream(self, messages: list[ChatMessage], tools: Optional[list[dict]] = None, **kwargs) -> AsyncGenerator[Any, None]:
        eff_tokens = kwargs.get("max_tokens") or self.max_tokens
        kwargs["max_tokens"] = eff_tokens
        agen = self.orchestrator.stream(
            messages,
            model_name=self.model_name,
            temperature=self.temperature,
            tools=tools,
            **kwargs,
        )
        async for chunk in agen:
            yield chunk


class DSNUIAgentCoordinator:
    """DSN-UI 核心 Agent 调度中枢。"""

    def __init__(
        self,
        orchestrator: ModelOrchestrator,
        workspace_root: Path,
        data_dir: Optional[Path] = None,
        on_topic_converged: Optional[Callable[[str, str], None]] = None,
    ):
        self.orchestrator = orchestrator
        self.workspace_root = workspace_root
        self.data_dir = data_dir or (workspace_root / "apps" / "dsn_ui" / "data")
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.db_path = str(self.data_dir / "dsn_ui_memory.db")
        self.sqlite_store = SqliteStore(self.db_path)
        self.topic_store = DSNUITopicStore(store=self.sqlite_store)

        # 1. 话题上下文记忆管理器
        self.topic_mgr = DSNUITopicContextManager(
            store=self.topic_store,
            on_topic_converged=on_topic_converged,
        )

        # 2. 5D 情绪引擎
        self.emotion_engine = DSNUIEmotionEngine()
        saved_emo = self.topic_store.load_emotion()
        if saved_emo:
            self.emotion_engine.state = EmotionalState(**saved_emo)

        # 3. 工具协调器（纯 harness 工具 + 两阶段 toolbox 激活）
        self.tool_coordinator = DSNUIToolCoordinator(workspace_root=self.workspace_root)

        # 4. 人格动力学系统 PEV3
        cards_dir = workspace_root / "apps" / "dsn_ui" / "character_cards"
        cards_dir.mkdir(parents=True, exist_ok=True)
        default_card = str(cards_dir / "blank_companion.yaml")
        self.pv3 = PersonalitySystemV3(
            db=self.sqlite_store.get_connection(),
            personality_model_chat=None,
            cards_dir=cards_dir,
            default_card_path=default_card,
        )
        self.pv3.init_tables()
        self.uid = 1
        self.pv3.ensure_user_bound(self.uid)

        # 基础系统设定
        self.base_system_prompt = "你是一个富有共情力、思维敏锐、乐于助人的智能全能伴侣。"

        # AgentLoop 自主循环步数上限（0 = 不限制），可由设置页面调整
        self._max_steps: int = self._load_max_steps()

    # ── AgentLoop 步数设置 ──

    def _settings_file(self) -> Path:
        return self.data_dir / "agent_settings.json"

    def _load_max_steps(self) -> int:
        """从持久化设置读取 AgentLoop 步数上限（默认 5，0 = 不限制）。"""
        default = 5
        try:
            f = self._settings_file()
            if f.exists():
                raw = json.loads(f.read_text(encoding="utf-8"))
                val = int(raw.get("max_steps", default))
                return val if 0 <= val <= 100 else default
        except Exception as e:
            logger.debug("读取 agent_settings 失败: %s", e)
        return default

    def get_max_steps(self) -> int:
        return self._max_steps

    def set_max_steps(self, steps: int) -> None:
        """更新并持久化 AgentLoop 步数上限（0 = 不限制）。"""
        val = max(0, min(100, int(steps)))
        self._max_steps = val
        try:
            f = self._settings_file()
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps({"max_steps": val}, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.warning("保存 agent_settings 失败: %s", e)

    def get_emotion_summary(self) -> str:
        return self.emotion_engine.summary_text()

    def get_emotion_state(self) -> dict:
        return self.emotion_engine.state.to_dict()

    def get_context_stats(self) -> dict:
        """最近一次弹性上下文装配的统计（预算/折叠/截断）。"""
        return self.topic_mgr.get_assembly_stats()

    @staticmethod
    def _build_override_messages(messages_raw: List[Dict[str, Any]], system_prompt: str) -> List[ChatMessage]:
        """自定义系统提示词模式：直接使用客户端消息，替换其 system 段。"""
        out: List[ChatMessage] = [ChatMessage.system(system_prompt)]
        for m in messages_raw:
            role = m.get("role", "user")
            if role == "system":
                continue
            content = m.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    p.get("text", "") for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                )
            if role == "user":
                out.append(ChatMessage.user(str(content)))
            elif role == "assistant":
                out.append(ChatMessage.assistant(str(content)))
        return out

    def assemble_system_prompt(self, execution_mode: bool = False) -> str:
        prompts = [self.base_system_prompt]

        # 1. PEV3 动态人格 Prompt
        try:
            p_prompt = self.pv3.generate_personality_prompt(self.uid)
            if p_prompt:
                prompts.append(p_prompt)
        except Exception as e:
            logger.debug("PEV3 prompt generation skipped: %s", e)

        # 2. 情绪感知 Prompt
        emo_prompt = self.emotion_engine.perception_prompt()
        if emo_prompt:
            prompts.append(emo_prompt)

        # 3. 工具 / 执行模式 Prompt
        # 工具 schema 由 toolbox 两阶段下发，这里只负责说明「如何用」：
        # 先激活（toolbox 索引）再调用，避免一次性注入全部 schema。
        if execution_mode:
            prompts.append(
                "【执行模式已开启】你已接入 harness 工具箱（toolbox）。"
                "可用工具不会一次性全部下发：请先调用 toolbox 工具激活本次任务需要的工具 id，"
                "再调用这些工具。当用户提出具体任务、查找、计算或操作需求时，"
                "请主动激活并调用合适的工具，并基于工具输出给出精准回答。"
            )
        else:
            prompts.append("【执行模式已关闭】当前处于纯对话模式。")

        return "\n\n".join(prompts)

    def _post_turn(self, user_text: str, reply_text: str) -> None:
        """交互后置：记录轮次、演化特质与持久化情绪。"""
        # 1. 话题记忆保存
        self.topic_mgr.record_turn(user_text, reply_text)

        # 2. PEV3 动力学分析
        try:
            cur_topic = self.topic_mgr.get_or_create_current_topic()
            hist_text = ""
            if cur_topic and cur_topic.messages:
                hist_text = "\n".join(f"{m.role}: {m.content}" for m in cur_topic.messages[-6:])
            res = self.pv3.analyze_interaction(
                uid=self.uid,
                user_message=user_text,
                ai_reply=reply_text,
                conversation_history=hist_text,
            )
            if res and res.new_mood:
                m = res.new_mood
                self.emotion_engine.state.joy = float(m.get("joy", self.emotion_engine.state.joy))
                self.emotion_engine.state.sorrow = float(m.get("sadness", self.emotion_engine.state.sorrow))
                self.emotion_engine.state.anger = float(m.get("anger", self.emotion_engine.state.anger))
                self.emotion_engine.state.fear = float(m.get("fear", self.emotion_engine.state.fear))
        except Exception as e:
            logger.debug("PEV3 post-turn analysis error: %s", e)

        # 3. 持久化情绪
        st = self.emotion_engine.state
        self.topic_store.save_emotion(st.joy, st.sorrow, st.anger, st.fear, st.meta)

    async def chat_stream(
        self,
        messages_raw: List[Dict[str, Any]],
        model_name: str,
        temperature: Optional[float] = None,
        execution_mode: bool = False,
        system_prompt_override: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """通过 Agent 循环流式生成回复，支持记忆组装、情绪演化与工具调用。

        system_prompt_override 非 None 时，用该文本替代 harness 动态组装的
        提示词生态（话题记忆/情绪/工具箱指令不再注入），即用户自定义超驰。
        """
        # 提取用户最新输入（streaming 入口）
        user_msg = ""
        for m in reversed(messages_raw):
            if m.get("role") == "user":
                c = m.get("content", "")
                if isinstance(c, list):
                    user_msg = " ".join(part.get("text", "") for part in c if isinstance(part, dict))
                else:
                    user_msg = str(c)
                break

        # 1. 情绪启发式刺激
        if user_msg:
            self.emotion_engine.evaluate_text_stimulus(user_msg)

        # 2. 系统提示词合成：自定义超驰优先，否则由 harness 动态组装
        if system_prompt_override is not None:
            system_prompt = system_prompt_override
            # 超驰模式下不走话题记忆装配，客户端消息即完整上下文
            context_msgs = self._build_override_messages(messages_raw, system_prompt)
        else:
            system_prompt = self.assemble_system_prompt(execution_mode=execution_mode)

        if system_prompt_override is None:
            # 3. 话题记忆弹性剪裁组装
            context_msgs = self.topic_mgr.assemble_context_messages(
                new_user_message=user_msg or "你好",
                system_prefix=system_prompt,
            )

        model_ctx = self.orchestrator.get_model_ctx_size(model_name)
        eff_max_tokens = max_tokens if (max_tokens is not None and max_tokens > 0) else model_ctx
        client = OrchestratorChatClientWrapper(
            self.orchestrator,
            model_name=model_name,
            temperature=temperature,
            max_tokens=eff_max_tokens,
        )

        # 弹性上下文统计先于首轮推理产出，供前端用量环立即展示预算结构
        yield {"type": "context_stats", "stats": self.topic_mgr.get_assembly_stats()}

        if execution_mode:
            # 启用技能工具体系与 AgentLoop
            loop = AgentLoop(
                client=client,
                tools=self.tool_coordinator.tool_reg,
                toolbox=self.tool_coordinator.toolbox,
                max_steps=self._max_steps,
            )

            full_reply_parts = []
            async for ev in loop.run_stream(context_msgs):
                if ev.kind == "round_start":
                    # 轮次边界：前端据此为每一轮开启独立的 assistant 消息，
                    # 从而正确呈现「思考-动作-思考-动作-最终回答」的分行顺序。
                    yield {"type": "round_start", "round": ev.round}
                elif ev.kind == "delta" and ev.content:
                    full_reply_parts.append(ev.content)
                    yield {"type": "delta", "content": ev.content}
                elif ev.kind == "reasoning" and ev.content:
                    yield {"type": "reasoning", "content": ev.content}
                elif ev.kind == "tool_call" and ev.tool_call:
                    yield {"type": "tool_call", "tool_call": ev.tool_call}
                elif ev.kind == "tool_result" and ev.tool_result:
                    yield {"type": "tool_result", "tool_result": ev.tool_result}
                elif ev.kind in ("timings", "usage") and ev.timings:
                    yield {"type": ev.kind, "timings": ev.timings}
                elif ev.kind == "reply" and ev.reply and not full_reply_parts:
                    full_reply_parts.append(ev.reply)
                    yield {"type": "delta", "content": ev.reply}

            full_reply = "".join(full_reply_parts)
            self._post_turn(user_msg, full_reply)
        else:
            # 纯对话模式（由话题记忆装配上下文后流式推理）
            full_reply_parts = []
            agen = self.orchestrator.stream(
                context_msgs,
                model_name=model_name,
                temperature=temperature,
                max_tokens=eff_max_tokens,
            )
            async for chunk in agen:
                if isinstance(chunk, str):
                    full_reply_parts.append(chunk)
                    yield {"type": "delta", "content": chunk}
                elif isinstance(chunk, dict):
                    # 思维链字段命名各 provider 不一（reasoning / reasoning_content），
                    # 与 AgentLoop 保持同样兼容，否则本地模型思考过程不显示。
                    r_delta = chunk.get("reasoning_content") or chunk.get("reasoning")
                    if r_delta:
                        yield {"type": "reasoning", "content": r_delta}
                    if chunk.get("tool_calls"):
                        yield {"type": "tool_calls", "tool_calls": chunk["tool_calls"]}
                    # 透传 provider 用量：llama-server 提供 timings 时前端可显示真实
                    # token 占用；若未提供，前端退化为按字符统计弹性上下文。
                    if chunk.get("timings"):
                        yield {"type": "timings", "timings": chunk["timings"]}
                    if chunk.get("usage"):
                        yield {"type": "usage", "usage": chunk["usage"]}

            full_reply = "".join(full_reply_parts)
            self._post_turn(user_msg, full_reply)

    def chat_invoke(
        self,
        messages_raw: List[Dict[str, Any]],
        model_name: str,
        temperature: Optional[float] = None,
        execution_mode: bool = False,
        system_prompt_override: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> ChatResponse:
        """非流式调用入口。"""
        user_msg = ""
        for m in reversed(messages_raw):
            if m.get("role") == "user":
                c = m.get("content", "")
                if isinstance(c, list):
                    user_msg = " ".join(part.get("text", "") for part in c if isinstance(part, dict))
                else:
                    user_msg = str(c)
                break

        if user_msg:
            self.emotion_engine.evaluate_text_stimulus(user_msg)

        if system_prompt_override is not None:
            context_msgs = self._build_override_messages(messages_raw, system_prompt_override)
        else:
            system_prompt = self.assemble_system_prompt(execution_mode=execution_mode)
            context_msgs = self.topic_mgr.assemble_context_messages(
                new_user_message=user_msg or "你好",
                system_prefix=system_prompt,
            )

        model_ctx = self.orchestrator.get_model_ctx_size(model_name)
        eff_max_tokens = max_tokens if (max_tokens is not None and max_tokens > 0) else model_ctx
        client = OrchestratorChatClientWrapper(
            self.orchestrator,
            model_name=model_name,
            temperature=temperature,
            max_tokens=eff_max_tokens,
        )

        if execution_mode:
            loop = AgentLoop(
                client=client,
                tools=self.tool_coordinator.tool_reg,
                toolbox=self.tool_coordinator.toolbox,
                max_steps=self._max_steps,
            )
            res = loop.run(context_msgs)
            self._post_turn(user_msg, res.reply)
            return ChatResponse(content=res.reply)
        else:
            resp = self.orchestrator.invoke(
                context_msgs,
                model_name=model_name,
                temperature=temperature,
                max_tokens=eff_max_tokens,
            )
            self._post_turn(user_msg, resp.content)
            return resp
