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

from apps.dsn_ui.logging_setup import log_exception

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


class SummaryModelChat:
    """把 orchestrator 上的任意模型适配成 PV3 / 摘要所需的 chat 客户端。

    PV3 的 PersonalityJudge 与 DistillationEngine 期望一个具备
    send_message()/invoke() 的对象；这里用「专门配置的摘要模型」实现，
    使得摘要与人格分析可以走独立（通常更便宜/更快）的模型，
    而不占用对话主模型。

    未配置专用模型时 model_name 为 None，available=False，
    调用方据此回退（PV3 -> 启发式；摘要 -> 跳过）。
    """

    def __init__(
        self,
        orchestrator: ModelOrchestrator,
        model_name: Optional[str] = None,
        max_tokens: int = 1500,
    ):
        self.orchestrator = orchestrator
        self.model_name = model_name
        # PV3 的 _send_with_temp 会临时改写这两个属性，保留以便其生效
        self.temperature: Optional[float] = None
        self.max_tokens = max_tokens

    @property
    def available(self) -> bool:
        return bool(self.model_name)

    def send_message(self, prompt: str, **kwargs) -> str:
        """单轮文本调用（PV3 judge / distillation 使用）。"""
        if not self.model_name:
            raise RuntimeError("未配置专用的摘要/分析模型")
        resp = self.orchestrator.invoke(
            [ChatMessage.user(prompt)],
            model_name=self.model_name,
            temperature=kwargs.get("temperature", self.temperature),
            max_tokens=kwargs.get("max_tokens", self.max_tokens),
        )
        return resp.content or ""

    def invoke(self, messages, **kwargs) -> ChatResponse:
        if not self.model_name:
            raise RuntimeError("未配置专用的摘要/分析模型")
        return self.orchestrator.invoke(
            messages,
            model_name=self.model_name,
            temperature=kwargs.get("temperature", self.temperature),
            max_tokens=kwargs.get("max_tokens", self.max_tokens),
        )

    def complete(self, prompt: str, **kwargs) -> str:
        return self.send_message(prompt, **kwargs)


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

        # 上下文充满后的策略（三选一，可由设置页切换）
        #   drop_oldest  直接丢弃本会话最早的上下文
        #   compact_all  把全部内容压缩成一份摘要
        #   topic_merge  走记忆系统的话题合并（旧话题摘要 + 保留近期原文）
        self._context_overflow_strategy: str = self._load_context_strategy()
        # 专用摘要 / 人格V3分析模型（为空表示沿用当前对话模型）
        self._summary_model_name: Optional[str] = self._load_summary_model()
        # 触发阈值：上下文字符数达到 ctx_size * 该比例时触发策略
        self._context_trigger_ratio: float = self._load_context_trigger_ratio()

        # 基础系统设定
        self.base_system_prompt = "你是一个富有共情力、思维敏锐、乐于助人的智能全能伴侣。"

        # AgentLoop 自主循环步数上限（0 = 不限制），可由设置页面调整
        self._max_steps: int = self._load_max_steps()
        # 工具输出弹性截断字符数上限
        self._tool_max_output_chars: int = self._load_tool_max_output_chars()
        self.tool_coordinator.set_max_output_chars(self._tool_max_output_chars)

        # 把已配置的专用摘要/分析模型绑定到 PV3。
        # 历史实现传入 personality_model_chat=None 且从不更新，
        # 导致 analyze_interaction 永久退化为启发式、摘要任务无人可用。
        self._rebind_summary_model()

    # ── AgentLoop 步数设置 ──

    def _settings_file(self) -> Path:
        return self.data_dir / "agent_settings.json"

    def _load_max_steps(self) -> int:
        """从持久化设置读取 AgentLoop 步数上限（默认 0 = 不限制）。

        历史默认值是 5，会让复杂的多步任务在「思考-动作」进行到一半时被
        截断；改为一律默认不限制，需要限制时由用户在设置页显式指定。
        """
        default = 0
        try:
            f = self._settings_file()
            if f.exists():
                raw = json.loads(f.read_text(encoding="utf-8"))
                val = int(raw.get("max_steps", default))
                return val if 0 <= val <= 10000 else default
        except Exception as e:
            logger.debug("读取 agent_settings 失败: %s", e)
        return default

    def get_max_steps(self) -> int:
        return self._max_steps

    # ── 上下文充满策略 / 专用摘要模型 ──

    VALID_CONTEXT_STRATEGIES = ("drop_oldest", "compact_all", "topic_merge")

    def _load_context_strategy(self) -> str:
        """读取上下文充满后的策略，默认 topic_merge（保持历史行为）。"""
        default = "topic_merge"
        try:
            f = self._settings_file()
            if f.exists():
                raw = json.loads(f.read_text(encoding="utf-8"))
                val = str(raw.get("context_overflow_strategy", default))
                return val if val in self.VALID_CONTEXT_STRATEGIES else default
        except Exception as e:
            logger.debug("读取 context_overflow_strategy 失败: %s", e)
        return default

    def get_context_strategy(self) -> str:
        return self._context_overflow_strategy

    def set_context_strategy(self, strategy: str) -> str:
        val = str(strategy)
        if val not in self.VALID_CONTEXT_STRATEGIES:
            raise ValueError(
                f"未知的上下文策略: {val}，可选 {self.VALID_CONTEXT_STRATEGIES}"
            )
        self._context_overflow_strategy = val
        self._save_settings()
        logger.info("上下文充满策略已设置为: %s", val)
        return val

    def _load_context_trigger_ratio(self) -> float:
        """触发阈值比例（相对模型上下文长度），默认 0.75。"""
        default = 0.75
        try:
            f = self._settings_file()
            if f.exists():
                raw = json.loads(f.read_text(encoding="utf-8"))
                val = float(raw.get("context_trigger_ratio", default))
                return val if 0.1 <= val <= 1.0 else default
        except Exception as e:
            logger.debug("读取 context_trigger_ratio 失败: %s", e)
        return default

    def get_context_trigger_ratio(self) -> float:
        return self._context_trigger_ratio

    def set_context_trigger_ratio(self, ratio: float) -> float:
        val = max(0.1, min(1.0, float(ratio)))
        self._context_trigger_ratio = val
        self._save_settings()
        return val

    def _load_summary_model(self) -> Optional[str]:
        """读取专用摘要/分析模型名；空字符串或缺失表示未配置。"""
        try:
            f = self._settings_file()
            if f.exists():
                raw = json.loads(f.read_text(encoding="utf-8"))
                val = raw.get("summary_model", "")
                val = str(val).strip() if val else ""
                return val or None
        except Exception as e:
            logger.debug("读取 summary_model 失败: %s", e)
        return None

    def get_summary_model(self) -> Optional[str]:
        return self._summary_model_name

    def set_summary_model(self, model_name: Optional[str]) -> Optional[str]:
        """设置专用摘要/人格分析模型，并立即重绑定 PV3。

        传空字符串/None 表示取消专用模型，PV3 将回退到启发式、
        摘要任务跳过（与历史行为一致）。
        """
        val = (str(model_name).strip() if model_name else "") or None
        self._summary_model_name = val
        self._save_settings()
        self._rebind_summary_model()
        logger.info("专用摘要/分析模型已设置为: %s", val or "(未配置)")
        return val

    def _rebind_summary_model(self) -> None:
        """把专用模型绑定到 PV3（人格分析）与摘要器。"""
        try:
            chat = SummaryModelChat(self.orchestrator, self._summary_model_name)
            self.pv3.set_personality_model(chat if chat.available else None)
            logger.info(
                "PV3 人格分析模型绑定: %s",
                self._summary_model_name or "(未配置，将使用启发式分类)",
            )
        except Exception as e:  # noqa: BLE001
            log_exception(logger, "绑定 PV3 分析模型失败", e)

    def _resolve_summary_model(self, fallback_model: str) -> str:
        """摘要调用使用的模型：优先专用模型，否则回退当前对话模型。"""
        return self._summary_model_name or fallback_model

    def _load_tool_max_output_chars(self) -> int:
        """从持久化设置读取工具最大输出字符数（默认 6000）。"""
        default = 6000
        try:
            f = self._settings_file()
            if f.exists():
                raw = json.loads(f.read_text(encoding="utf-8"))
                val = int(raw.get("tool_max_output_chars", default))
                return val if 500 <= val <= 200000 else default
        except Exception as e:
            logger.debug("读取 tool_max_output_chars 失败: %s", e)
        return default

    def get_tool_max_output_chars(self) -> int:
        return self._tool_max_output_chars

    def set_tool_max_output_chars(self, chars: int) -> None:
        """更新并持久化工具最大输出字符数，同时更新工具执行环境。"""
        val = max(500, min(200000, int(chars)))
        self._tool_max_output_chars = val
        self.tool_coordinator.set_max_output_chars(val)
        self._save_settings()

    def set_max_steps(self, steps: int) -> None:
        """更新并持久化 AgentLoop 步数上限（0 = 不限制）。"""
        val = max(0, min(10000, int(steps)))
        self._max_steps = val
        self._save_settings()

    def _save_settings(self) -> None:
        try:
            f = self._settings_file()
            f.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "max_steps": self._max_steps,
                "tool_max_output_chars": self._tool_max_output_chars,
                "context_overflow_strategy": self._context_overflow_strategy,
                "context_trigger_ratio": self._context_trigger_ratio,
                "summary_model": self._summary_model_name or "",
            }
            f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.warning("保存 agent_settings 失败: %s", e)

    # 为 prompt 预留的输出预算比例：max_tokens 至少要给输入留出空间，
    # 否则 input + max_tokens > ctx_size，llama-server 会直接返回 HTTP 500
    # （表现为 SSE 一起手就 "500 Server Error"，没有任何模型输出）。
    _OUTPUT_BUDGET_RATIO = 0.5

    def _resolve_max_tokens(
        self, requested: Optional[int], model_ctx: int
    ) -> int:
        """计算安全的 max_tokens。

        历史实现直接把 max_tokens 设为整个上下文长度，导致任何非空 prompt
        都会让 input+output 超出 ctx_size 而被 llama-server 拒绝（HTTP 500）。
        这里为输入预留至少一半上下文；用户显式指定的值也会被夹到安全上限内。
        """
        if model_ctx and model_ctx > 0:
            safe_cap = max(256, int(model_ctx * self._OUTPUT_BUDGET_RATIO))
        else:
            safe_cap = 4096

        if requested is not None and requested > 0:
            if requested > safe_cap:
                logger.warning(
                    "请求的 max_tokens=%d 超过安全上限 %d（上下文 %d 的一半），已夹取",
                    requested, safe_cap, model_ctx,
                )
                return safe_cap
            return requested
        return safe_cap

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
                # 保留多模态结构（image_url 等），不能拍平 —— 否则图像丢失。
                from apps.dsn_ui.integration_api import openai_content_to_parts
                content = openai_content_to_parts(content)
            if role == "user":
                # 纯文本走 ChatMessage.user；多模态直接构造以保留 parts
                if isinstance(content, str):
                    out.append(ChatMessage.user(content))
                else:
                    out.append(ChatMessage(role="user", content=content))
            elif role == "assistant":
                out.append(ChatMessage.assistant(
                    content if isinstance(content, str) else str(content)))
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
        logger.debug(
            "_post_turn 开始: user_chars=%d reply_chars=%d",
            len(user_text or ""), len(reply_text or ""),
        )
        # 1. 话题记忆保存
        try:
            self.topic_mgr.record_turn(user_text, reply_text)
        except Exception as e:  # noqa: BLE001
            # 话题记忆写入失败不应影响主回复，但必须留下完整栈。
            log_exception(logger, "_post_turn: record_turn 失败", e)

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

    # ── 上下文充满策略 ──

    def _context_char_budget(self, model_ctx: int) -> int:
        """本次请求触发策略的字符阈值。

        以模型上下文长度为基准，按用户配置的比例换算成字符数
        （约 1 token ≈ 2 字符的经验值，保守留出输出空间）。
        """
        ratio = self._context_trigger_ratio
        return max(1000, int(model_ctx * 2.0 * ratio))

    def _apply_context_strategy(
        self,
        model_name: str,
        model_ctx: int,
        user_msg: str,
    ) -> bool:
        """按配置的策略处理"上下文充满"。

        返回 True 表示已对历史做了压缩/裁剪，调用方需要重新装配上下文。
        """
        strategy = self._context_overflow_strategy
        limit = self._context_char_budget(model_ctx)

        try:
            if strategy == "drop_oldest":
                changed = self.topic_mgr.drop_oldest_if_needed(limit)
            elif strategy == "compact_all":
                changed = self.topic_mgr.compact_all_if_needed(
                    limit, self._make_summarizer(model_name)
                )
            else:  # topic_merge
                changed = self.topic_mgr.compact_topic_if_needed(
                    limit, self._make_summarizer(model_name)
                )
        except Exception as e:  # noqa: BLE001 - 策略失败不能拖垮整轮对话
            log_exception(logger, f"上下文策略 {strategy} 执行失败", e)
            return False

        if changed:
            logger.info("上下文策略 %s 已生效（阈值 %d 字符）", strategy, limit)
        else:
            logger.debug("上下文策略 %s 未触发（阈值 %d 字符）", strategy, limit)
        return changed

    def _make_summarizer(self, model_name: str) -> Callable[[str], str]:
        """构造摘要函数：优先使用专用摘要模型，否则回退当前对话模型。"""
        target_model = self._resolve_summary_model(model_name)

        def _summarize(hist_text: str) -> str:
            try:
                summary_prompt = [
                    ChatMessage.system(
                        "你是一个专业的会话总结助手。请简明扼要地总结以下前序历史对话"
                        "与工具执行进展，保留核心结论、事实与当前任务状态，"
                        "用于压缩上下文释放空间："
                    ),
                    ChatMessage.user(hist_text),
                ]
                resp = self.orchestrator.invoke(
                    summary_prompt, model_name=target_model, max_tokens=1500
                )
                logger.info(
                    "摘要完成: model=%s input_chars=%d output_chars=%d",
                    target_model, len(hist_text), len(resp.content or ""),
                )
                return resp.content or ""
            except Exception as ex:  # noqa: BLE001
                log_exception(
                    logger, f"摘要调用失败(model={target_model})，本次跳过压缩", ex
                )
                return ""

        return _summarize

    async def chat_stream(
        self,
        messages_raw: List[Dict[str, Any]],
        model_name: str,
        temperature: Optional[float] = None,
        execution_mode: bool = False,
        system_prompt_override: Optional[str] = None,
        max_tokens: Optional[int] = None,
        max_steps: Optional[int] = None,
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
            # 这一段会遍历 topic_mgr.topics（dict）。若其它协程在遍历过程中
            # 增删话题，就会抛 "dictionary changed size during iteration"。
            # 因此记录进入/退出与话题规模，便于把异常定位到这一层。
            logger.debug(
                "上下文装配开始: topics=%d memos=%d current=%s",
                len(self.topic_mgr.topics), len(self.topic_mgr.memos),
                self.topic_mgr.current_topic_id,
            )
            try:
                context_msgs = self.topic_mgr.assemble_context_messages(
                    new_user_message=user_msg or "你好",
                    system_prefix=system_prompt,
                )
            except Exception as e:  # noqa: BLE001
                log_exception(
                    logger,
                    "上下文装配失败(topic_mgr.assemble_context_messages)",
                    e,
                )
                raise
            logger.debug("上下文装配完成: messages=%d", len(context_msgs))

        model_ctx = self.orchestrator.get_model_ctx_size(model_name)
        eff_max_tokens = self._resolve_max_tokens(max_tokens, model_ctx)

        # 上下文溢出智能自愈：按用户选择的策略处理（见 _apply_context_strategy）
        if system_prompt_override is None:
            if self._apply_context_strategy(
                model_name=model_name,
                model_ctx=model_ctx,
                user_msg=user_msg,
            ):
                # 策略生效后重新组装上下文，释放空间
                context_msgs = self.topic_mgr.assemble_context_messages(
                    new_user_message=user_msg or "你好",
                    system_prefix=system_prompt,
                )

        client = OrchestratorChatClientWrapper(
            self.orchestrator,
            model_name=model_name,
            temperature=temperature,
            max_tokens=eff_max_tokens,
        )

        # 弹性上下文统计先于首轮推理产出，供前端用量环立即展示预算结构
        yield {"type": "context_stats", "stats": self.topic_mgr.get_assembly_stats()}

        full_reply_parts = []
        turn_posted = False

        try:
            if execution_mode:
                # 启用技能工具体系与 AgentLoop（优先使用单次请求指定的 max_steps，否则使用全局持久化设置）
                effective_steps = self._max_steps if (max_steps is None or max_steps < 0) else max_steps
                loop = AgentLoop(
                    client=client,
                    tools=self.tool_coordinator.tool_reg,
                    toolbox=self.tool_coordinator.toolbox,
                    max_steps=effective_steps,
                    max_output_chars=self._tool_max_output_chars,
                )

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
                    elif ev.kind == "done":
                        # 终态信号：hit_max 表示模型在步数耗尽后由收束轮给出答复。
                        # 必须透传，否则前端无法区分「正常完成」与「被步数截断」。
                        yield {
                            "type": "done",
                            "hit_max": bool(ev.hit_max),
                            "round": ev.round,
                        }

                full_reply = "".join(full_reply_parts)
                self._post_turn(user_msg, full_reply)
                turn_posted = True
            else:
                # 纯对话模式（由话题记忆装配上下文后流式推理）
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
                        r_delta = chunk.get("reasoning_content") or chunk.get("reasoning")
                        if r_delta:
                            yield {"type": "reasoning", "content": r_delta}
                        if chunk.get("tool_calls"):
                            yield {"type": "tool_calls", "tool_calls": chunk["tool_calls"]}
                        if chunk.get("timings"):
                            yield {"type": "timings", "timings": chunk["timings"]}
                        if chunk.get("usage"):
                            yield {"type": "usage", "usage": chunk["usage"]}

                # 关键：纯对话模式同样必须发出终态信号。
                # 上层 server 依赖 done 生成标准 OpenAI 终态块
                # （choices[0].finish_reason），缺失会导致严格客户端报
                # "Stream ended without finish_reason"。
                # 历史实现只在 execution_mode 分支转发 done，纯对话分支
                # 直接静默结束 —— 这正是该报错的根因。
                yield {"type": "done", "hit_max": False, "round": 1}

                full_reply = "".join(full_reply_parts)
                self._post_turn(user_msg, full_reply)
                turn_posted = True
        finally:
            # 关键保障：即使中途报错（如 Response ended prematurely）或用户手动终止，
            # 只要产生了部分回复或执行进展，立即记入话题记忆，确保用户发送「继续」时具有连续上下文！
            if not turn_posted and (full_reply_parts or user_msg):
                partial_reply = "".join(full_reply_parts) or "…[生成中断]"
                try:
                    self._post_turn(user_msg, partial_reply)
                except Exception as ex:
                    log_exception(logger, "中断轮次记忆补偿记录失败", ex)
            logger.debug(
                "chat_stream 退出: turn_posted=%s reply_chars=%d",
                turn_posted, sum(len(p) for p in full_reply_parts),
            )

    def chat_invoke(
        self,
        messages_raw: List[Dict[str, Any]],
        model_name: str,
        temperature: Optional[float] = None,
        execution_mode: bool = False,
        system_prompt_override: Optional[str] = None,
        max_tokens: Optional[int] = None,
        max_steps: Optional[int] = None,
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
        eff_max_tokens = self._resolve_max_tokens(max_tokens, model_ctx)
        client = OrchestratorChatClientWrapper(
            self.orchestrator,
            model_name=model_name,
            temperature=temperature,
            max_tokens=eff_max_tokens,
        )

        if execution_mode:
            effective_steps = self._max_steps if (max_steps is None or max_steps < 0) else max_steps
            loop = AgentLoop(
                client=client,
                tools=self.tool_coordinator.tool_reg,
                toolbox=self.tool_coordinator.toolbox,
                max_steps=effective_steps,
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
