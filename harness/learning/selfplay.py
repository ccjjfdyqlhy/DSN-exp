# harness/learning/selfplay.py
# 自生成数据：用「当前模型 + 情境」生成「如果发生 X，我会怎么做 + 结果」的样本。
#
# 定位（计划二 §4.4）：
#   这是「递归自我改进」的数据来源——模型自己产出自己的训练数据，
#   用来补真实对话覆盖不到的分支。它**必须在 harness 层**：
#   它需要 IChatClient 与上下文组装能力，而这两样都在框架层。
#
# ── 应用无关（硬约束）────────────────────────────────────────────
#   harness/learning 是框架层，**不含**任何具体应用的语义
#   （情感、沙箱、混沌演练、drives/affect 都只存在于本地实验应用里）。
#   所以本模块：
#     · 不造世界状态、不造 drives、不造情绪状态；
#     · 情境（Situation）一律由调用方注入——本模块只负责「把情境变成样本」；
#     · 不提供默认人格：system 提示默认空，由调用方自己给；
#     · 生成的样本直接复用 dataset_builder.Trajectory，可无缝喂给 DatasetBuilder。
#
# ── 六条纪律（每条都有测试锁住，见 tests/test_harness_selfplay.py）────
#   1. **训练标签不含思维链**：模型返回的 reasoning_content 与内联的
#      <think>…</think> 一律不进样本（内联段永远物理删除，不可协商）。
#   2. **打标记**：自生成轨迹的 source 固定为 "selfplay"，
#      评测时能分层看「自生成 vs 真实」。
#   3. **不定义目标层**：样本里不许出现 constitution / drives / affect_state /
#      survival_desire 之类的目标层内容（那层不可训练）。
#      生成**前**查情境，生成**后**查回复，查到了就丢。
#   4. **单条失败不中断整批**：某个情境的客户端调用抛异常 → 记进丢弃原因，
#      继续跑下一个。
#   5. **确定性**：同一个 seed + 同一个 client 返回序列 → 结果一致
#      （每次 generate 都按 seed 重置 rng 与去重表，去重顺序稳定）。
#   6. **纯逻辑**：不 import torch、不联网——测试可在没有 GPU、没有网络的机器上跑。
#
# ── 远端 API 的纪律 ──────────────────────────────────────────────
#   selfplay 默认用**本地**模型。要用远端 API 必须显式 allow_remote=True，
#   并且调用方必须声明 has_user_data（本次样本是否含用户数据）——
#   「开了远端但没声明有没有用户数据」一律拒绝运行；
#   情境自己声明含用户数据、而批次声明说没有时，那个情境单独被拒（不外发）。

from __future__ import annotations

import hashlib
import json
import logging
import random
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Protocol
from urllib.parse import urlparse

from infra.orchestrator.base import ChatMessage, ChatResponse

from .dataset_builder import Trajectory
from .teacher import PROTECTED_FIELDS

logger = logging.getLogger("harness.learning.selfplay")


#: 自生成轨迹的来源标记。与 dataset_builder / 评测分层对得上：
#: 评测时可以按 source 分层看「自生成 vs 真实」的指标。
SELFPLAY_SOURCE = "selfplay"

# ── 丢弃原因分桶（样本级）─────────────────────────────────────────
DROP_EMPTY = "empty"              #: 空回复
DROP_TOO_SHORT = "too_short"      #: 过短（低于 min_reply_chars）
DROP_TOO_LONG = "too_long"        #: 过长（超过 max_reply_chars）
DROP_DUPLICATE = "duplicate"      #: 同一情境下的重复回复
DROP_CLIENT_ERROR = "client_error"  #: 客户端调用异常
DROP_PROTECTED = "protected_leak"  #: 回复里混进了目标层内容

# ── 情境拒绝原因（情境级）────────────────────────────────────────
REJECT_PROTECTED = "protected_situation"      #: 情境里含目标层内容
REJECT_REMOTE_USER_DATA = "remote_user_data"  #: 情境声明含用户数据但批次未授权外发

#: 框架给的**格式**指令（不是人格）。
#: 框架层不提供人格/角色卡——人格由调用方通过 Situation.system 注入；
#: 这里只说明「要什么形状的答案」，保证样本是「怎么做 + 结果」。
DEFAULT_INSTRUCTION = (
    "请针对下面的情境作出回应：先说明你会怎么做（行动），再给出可能的结果。"
    "只输出最终内容，不要输出思考过程。"
)

#: 消息里合法的角色（与 infra.finetune.dataset.VALID_ROLES 对齐）。
_VALID_ROLES = ("system", "user", "assistant", "tool")

#: 判定为「本地」的 host（其余一律当作远端）。
_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "0.0.0.0", "host.docker.internal"})

#: 类名里出现这些词 → 疑似远端客户端。
_REMOTE_NAME_HINTS = ("openai", "anthropic", "deepseek", "gemini", "cloud", "remote")

#: 内联的思维链段（永远不进训练标签）。
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
#: 没闭合的 <think>（模型被截断时常见）：从标签处一路删到结尾。
_THINK_OPEN_RE = re.compile(r"<think>.*\Z", re.DOTALL | re.IGNORECASE)


class SelfPlayBoundaryError(Exception):
    """自生成越界（远端未授权 / 目标层内容 / 声明缺失）。"""


class SelfPlayClient(Protocol):
    """selfplay 需要的最小客户端接口。

    与 infra.orchestrator.base.IChatClient 同形（那里是权威定义），
    这里只是把依赖写出来，方便调用方与测试看清契约。
    """

    def invoke(
        self,
        messages: list[Any],
        tools: Optional[list[dict]] = None,
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
    ) -> ChatResponse: ...


@dataclass
class Situation:
    """一次要练习的情境。

    框架层**不造**情境：世界状态、驱动状态、情绪状态都由调用方填进来。
    """

    #: 情境描述（会作为 user 消息发给模型）。
    prompt: str
    #: 可选的既有上下文（role/content 字典），按顺序拼在 prompt 之前。
    context: list[dict] = field(default_factory=list)
    #: 可选的 system 提示（框架层不提供默认人格）。
    system: str = ""
    #: 评测时用于分层（例如 ("情绪:低落",)）。
    tags: tuple[str, ...] = ()
    #: 任意元数据；其中 "has_user_data": True 表示本情境含用户数据。
    metadata: dict = field(default_factory=dict)


@dataclass
class SelfPlayConfig:
    """自生成配置。"""

    #: 每个情境生成几条样本。
    samples_per_situation: int = 2
    temperature: float = 0.9
    max_tokens: int = 512
    timeout: float = 60.0
    #: 太短的回复不算样本。
    min_reply_chars: int = 8
    #: 太长的回复不算样本（训练时会被截断，等于浪费）。
    max_reply_chars: int = 8000
    #: 训练标签不含思维链。默认 True；False 只是把模型单独返回的
    #: reasoning_content 字段附在消息上供调试（内联的 <think> 段永远被删），
    #: dataset_builder.to_record(strip_reasoning=True) 仍会把它剥掉。
    strip_reasoning: bool = True
    #: 同一情境下的重复回复只留一条。
    dedupe: bool = True
    seed: int = 42
    #: 温度抖动幅度（0 = 不抖）。抖动由 seed 决定，因此仍然可复现。
    temperature_jitter: float = 0.0
    #: 生成时附加在 system 后的格式指令（不是人格）。空串 = 不加。
    instruction: str = DEFAULT_INSTRUCTION
    #: 是否把调用方自己的 system 提示留在训练样本里（默认留）。
    keep_system_in_sample: bool = True
    #: 远端 API 开关：默认 False。selfplay 默认用**本地**模型；
    #: 用远端 API 时必须显式打开，且调用方要声明样本含用户数据。
    allow_remote: bool = False
    #: 调用方声明：本次生成的样本是否含用户数据。
    #: allow_remote=True 时**必须**显式给出（True/False），否则拒绝运行。
    #: 单个情境可以在 metadata["has_user_data"] 里另作声明；两者不一致时
    #: 以「更保守」为准——含用户数据而批次没授权外发的情境会被单独拒掉。
    has_user_data: Optional[bool] = None
    #: 目标层字段清单（复用 teacher.PROTECTED_FIELDS，避免两处定义漂移）。
    protected_fields: tuple[str, ...] = PROTECTED_FIELDS


@dataclass
class SelfPlayReport:
    """一次自生成的结果。"""

    #: 接受的轨迹（可直接喂给 DatasetBuilder.add_many）。
    trajectories: list[Trajectory] = field(default_factory=list)
    #: 输入的情境总数。
    situations: int = 0
    #: 实际发起的生成次数（尝试数）。
    attempts: int = 0
    #: 接受的样本数。
    accepted: int = 0
    #: 丢弃的样本数（= attempts - accepted）。
    dropped: int = 0
    #: 丢弃原因分桶（空回复 / 过短 / 过长 / 重复 / 客户端异常 / 目标层泄漏）。
    dropped_reasons: dict[str, int] = field(default_factory=dict)
    #: 因边界检查被拒的情境数（这些不产生 attempts）。
    rejected_situations: int = 0
    #: 情境被拒的原因分桶。
    rejected_situation_reasons: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "situations": self.situations,
            "attempts": self.attempts,
            "accepted": self.accepted,
            "dropped": self.dropped,
            "dropped_reasons": dict(self.dropped_reasons),
            "rejected_situations": self.rejected_situations,
            "rejected_situation_reasons": dict(self.rejected_situation_reasons),
            "sources": {SELFPLAY_SOURCE: self.accepted},
        }


class SelfPlayGenerator:
    """用当前模型 + 情境生成自样本。"""

    def __init__(self, client: Any, config: Optional[SelfPlayConfig] = None):
        self._client = client
        self._config = config or SelfPlayConfig()
        self._rng = random.Random(self._config.seed)
        self._remote = _looks_remote(client)
        # 远端闸门：默认只走本地模型。开了远端却没声明有没有用户数据 → 拒绝。
        if self._remote and not self._config.allow_remote:
            raise SelfPlayBoundaryError(
                "检测到客户端可能是远端 API；selfplay 默认只走本地模型，"
                "用远端必须显式 allow_remote=True"
            )

    @property
    def config(self) -> SelfPlayConfig:
        return self._config

    # ── 主流程 ──

    def generate(self, situations: Iterable[Situation]) -> SelfPlayReport:
        """对每个情境生成 samples_per_situation 条样本。

        单条失败不中断整批：客户端异常、空回复、过短、过长、重复、
        目标层泄漏都只影响那一条，其余照常跑完。
        """
        cfg = self._config
        report = SelfPlayReport()

        # 确定性：每次 generate 都按同一个 seed 重置 rng 与去重表，
        # 同样的输入 + 同样的 client 返回序列 → 同样的结果。
        self._rng = random.Random(cfg.seed)
        seen: set[str] = set()

        self._assert_remote_declared()

        items = list(situations)
        report.situations = len(items)

        for idx, situation in enumerate(items):
            if not isinstance(situation, Situation):
                raise TypeError(
                    f"generate 只接受 Situation，第 {idx} 个是 {type(situation).__name__}"
                )

            # ── 边界检查（生成前）──
            reason, detail = self._check_situation(situation)
            if reason:
                report.rejected_situations += 1
                report.rejected_situation_reasons[reason] = (
                    report.rejected_situation_reasons.get(reason, 0) + 1
                )
                logger.warning("情境 %d 被拒（%s：%s）", idx, reason, detail)
                continue

            fingerprint = _situation_fingerprint(situation)
            for sample_idx in range(max(0, cfg.samples_per_situation)):
                report.attempts += 1
                try:
                    response = self._call(situation, self._next_temperature())
                except Exception as exc:  # noqa: BLE001 - 单条失败不中断整批
                    report.dropped += 1
                    report.dropped_reasons[DROP_CLIENT_ERROR] = (
                        report.dropped_reasons.get(DROP_CLIENT_ERROR, 0) + 1
                    )
                    logger.warning("情境 %d 第 %d 次生成失败: %s", idx, sample_idx, exc)
                    continue

                text = _strip_inline_thinking(_extract_text(response))
                drop_reason = self._screen_reply(text)
                if drop_reason:
                    report.dropped += 1
                    report.dropped_reasons[drop_reason] = (
                        report.dropped_reasons.get(drop_reason, 0) + 1
                    )
                    continue

                if cfg.dedupe:
                    key = f"{fingerprint}\x00{_normalize_for_dedupe(text)}"
                    if key in seen:
                        report.dropped += 1
                        report.dropped_reasons[DROP_DUPLICATE] = (
                            report.dropped_reasons.get(DROP_DUPLICATE, 0) + 1
                        )
                        logger.debug("情境 %d 第 %d 次是重复回复，丢弃", idx, sample_idx)
                        continue
                    seen.add(key)

                report.accepted += 1
                report.trajectories.append(
                    self._build_trajectory(situation, text, idx, sample_idx, response)
                )

        logger.info(
            "自生成完成：情境 %d，尝试 %d，接受 %d，丢弃 %d",
            report.situations, report.attempts, report.accepted, report.dropped,
        )
        return report

    # ── 边界与筛选 ──

    def _assert_remote_declared(self) -> None:
        """用了远端就必须声明样本含不含用户数据。"""
        cfg = self._config
        if cfg.allow_remote and cfg.has_user_data is None:
            raise SelfPlayBoundaryError(
                "使用远端 API 时必须显式声明 has_user_data（本次样本是否含用户数据）"
            )
        if self._remote and cfg.has_user_data:
            logger.warning("自生成样本声明含用户数据且客户端为远端 API：数据出网，留痕于此")

    def _find_protected(self, text: str) -> Optional[str]:
        """文本里是否混进了目标层字段名。返回命中的字段名。"""
        if not text:
            return None
        lowered = text.lower()
        for field_name in self._config.protected_fields:
            if field_name and field_name.lower() in lowered:
                return field_name
        return None

    def _check_situation(self, situation: Situation) -> tuple[Optional[str], str]:
        """生成前的情境检查。返回 (拒绝原因, 细节)。"""
        blob = json.dumps(
            {
                "prompt": situation.prompt,
                "context": situation.context,
                "system": situation.system,
                "tags": list(situation.tags),
                "metadata": situation.metadata,
            },
            ensure_ascii=False,
            default=str,
        )
        leak = self._find_protected(blob)
        if leak:
            return REJECT_PROTECTED, f"目标层字段 {leak}"

        # 情境声明含用户数据、但批次声明说没有 → 声明不一致，这个情境不外发。
        if (
            self._remote
            and bool(situation.metadata.get("has_user_data"))
            and not self._config.has_user_data
        ):
            return REJECT_REMOTE_USER_DATA, "情境声明含用户数据，但批次未声明授权外发"
        return None, ""

    def _screen_reply(self, text: str) -> Optional[str]:
        """回复的形状检查。返回丢弃原因（None = 通过）。"""
        cfg = self._config
        stripped = text.strip()
        if not stripped:
            return DROP_EMPTY
        if len(stripped) < cfg.min_reply_chars:
            return DROP_TOO_SHORT
        if len(stripped) > cfg.max_reply_chars:
            return DROP_TOO_LONG
        if self._find_protected(stripped):
            return DROP_PROTECTED
        return None

    # ── 调用 ──

    def _call(self, situation: Situation, temperature: float) -> Any:
        """调用一次模型。任何异常都交给上层记账（单条失败不中断整批）。"""
        messages = self._build_request_messages(situation)
        try:
            return self._client.invoke(
                messages,
                temperature=temperature,
                max_tokens=self._config.max_tokens,
                timeout=self._config.timeout,
            )
        except TypeError as exc:
            # 客户端是老签名（不认这些关键字参数）→ 退到最简调用。
            if "unexpected keyword argument" not in str(exc):
                raise
            return self._client.invoke(messages)

    def _next_temperature(self) -> float:
        """本次调用的温度（抖动由 seed 决定，因此可复现）。"""
        cfg = self._config
        if cfg.temperature_jitter <= 0:
            return cfg.temperature
        delta = self._rng.uniform(-cfg.temperature_jitter, cfg.temperature_jitter)
        return max(0.0, min(2.0, cfg.temperature + delta))

    # ── 消息装配 ──

    def _build_request_messages(self, situation: Situation) -> list[ChatMessage]:
        """发给模型的消息：system（调用方的 + 格式指令）+ 上下文 + 情境。"""
        cfg = self._config
        messages: list[ChatMessage] = []
        system = _build_system_prompt(situation.system, cfg.instruction)
        if system:
            messages.append(ChatMessage(role="system", content=system))
        messages.extend(_context_messages(situation.context))
        messages.append(ChatMessage(role="user", content=situation.prompt))
        return messages

    def _build_trajectory(
        self,
        situation: Situation,
        reply: str,
        situation_index: int,
        sample_index: int,
        response: Any,
    ) -> Trajectory:
        """把一次生成变成一条可训练轨迹（source 固定为 selfplay）。

        训练样本 = 调用方的 system（可选）+ 上下文 + 情境 + assistant 回复。
        框架的格式指令**不进样本**（那是生成期的脚手架，不是情境的一部分）。
        """
        cfg = self._config
        messages: list[dict[str, Any]] = []
        if cfg.keep_system_in_sample and situation.system.strip():
            messages.append({"role": "system", "content": situation.system.strip()})
        for msg in _context_messages(situation.context):
            messages.append({"role": msg.role, "content": msg.content})
        messages.append({"role": "user", "content": situation.prompt})

        assistant: dict[str, Any] = {"role": "assistant", "content": reply}
        if not cfg.strip_reasoning:
            # 只有显式关掉纪律 1 时才把 reasoning_content 附在消息上（供调试）；
            # dataset_builder.to_record(strip_reasoning=True) 仍会把它剥掉。
            reasoning = getattr(response, "reasoning_content", None)
            if reasoning:
                assistant["reasoning_content"] = str(reasoning)
        messages.append(assistant)

        meta: dict[str, Any] = {
            "tags": list(situation.tags),
            "situation_index": situation_index,
            "sample_index": sample_index,
        }
        if situation.metadata:
            meta["metadata"] = dict(situation.metadata)
        return Trajectory(messages=messages, source=SELFPLAY_SOURCE, meta=meta)


# ── 文本工具 ──

def _content_to_text(content: Any) -> str:
    """把 content 归一成文本（支持多模态 parts 列表）。"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return str(content)


def _extract_text(response: Any) -> str:
    """从各种响应形态里取文本（ChatResponse / OpenAI 风格 dict / 裸字符串）。"""
    if response is None:
        return ""
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        choices = response.get("choices") or []
        if choices:
            message = choices[0].get("message") or {}
            if isinstance(message.get("content"), (str, list)):
                return _content_to_text(message["content"])
        return _content_to_text(response.get("content"))
    content = getattr(response, "content", None)
    if content is not None:
        return _content_to_text(content)
    return str(response)


def _strip_inline_thinking(text: str) -> str:
    """删掉内联的思维链段。

    纪律 1：思维链不得成为训练标签，所以这里在入样本前物理删除。
    注意**不**像 teacher 那样剥 ``` 代码围栏——教师的输出是 JSON，
    而自生成的回复是自然语言，代码块是合法内容。
    """
    if not text:
        return ""
    out = _THINK_BLOCK_RE.sub("", text)
    out = _THINK_OPEN_RE.sub("", out)
    return out.strip()


def _normalize_for_dedupe(text: str) -> str:
    """去重用的归一化：折叠空白，首尾去空格（大小写敏感）。"""
    return " ".join(text.split())


def _build_system_prompt(situation_system: str, instruction: str) -> str:
    """system = 调用方的提示 + 框架的格式指令。"""
    parts = []
    if situation_system and situation_system.strip():
        parts.append(situation_system.strip())
    if instruction and instruction.strip():
        parts.append(instruction.strip())
    return "\n\n".join(parts)


def _context_messages(context: Iterable[dict]) -> list[ChatMessage]:
    """把既有上下文归一成消息（role 非法或 system 的条目跳过）。"""
    out: list[ChatMessage] = []
    for raw in context or []:
        if not isinstance(raw, dict):
            continue
        role = str(raw.get("role", "")).strip()
        if role not in _VALID_ROLES or role == "system":
            # system 统一由 Situation.system 提供，避免出现两条 system。
            continue
        content = raw.get("content", "")
        if isinstance(content, (list, tuple)):
            content = json.dumps(content, ensure_ascii=False)
        out.append(ChatMessage(role=role, content=str(content or "")))
    return out


def _situation_fingerprint(situation: Situation) -> str:
    """情境指纹：同一个情境（prompt+context+system 相同）下的重复回复只留一条。"""
    blob = json.dumps(
        {
            "prompt": situation.prompt,
            "context": situation.context,
            "system": situation.system,
        },
        ensure_ascii=False,
        default=str,
        sort_keys=True,
    )
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


# ── 远端/本地判定 ──

def _client_base_url(client: Any) -> str:
    """尽力取出客户端的 base_url（远端/本地判定的第一依据）。"""
    for attr in ("base_url", "api_base", "_base_url"):
        value = getattr(client, attr, None)
        if isinstance(value, str) and value:
            return value
    inner = getattr(client, "_client", None)
    if inner is not None:
        value = getattr(inner, "base_url", None)
        if value is not None:
            return str(value)
    return ""


def _looks_remote(client: Any) -> bool:
    """判断客户端是不是远端 API（保守：证据不足就当本地）。

    判定顺序：
      1. 客户端显式声明 is_remote → 听它的；
      2. 有 base_url → 看 host 是不是本机；
      3. 带 api_key → 远端；
      4. 类名里出现 openai/anthropic/... → 远端。
    """
    explicit = getattr(client, "is_remote", None)
    if explicit is not None:
        return bool(explicit)

    url = _client_base_url(client)
    if url:
        host = (urlparse(url).hostname or "").lower()
        if host:
            return host not in _LOCAL_HOSTS

    if getattr(client, "api_key", None):
        return True

    name = type(client).__name__.lower()
    return any(hint in name for hint in _REMOTE_NAME_HINTS)
