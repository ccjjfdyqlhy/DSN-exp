
# harness/learning/dataset_builder.py
# 从 agent **自己**的轨迹里构建监督微调数据集。
#
# 与 infra/finetune/dataset.py 的分工：
#   infra 那边负责**格式**（角色归一、切分、写盘）；
#   这边负责**取数与筛选**（从哪来、哪些能要、哪些必须扔）。
#
# 三条硬规则（每条都对应一个真实的坑）：
#   1. **只收 agent 自己产生的轨迹**。教师生成的、别的模型生成的，
#      都不能直接进训练集——那是在教学生模仿别人的风格而不是自己的能力。
#   2. **推理内容不进标签**。agent 自己的 reasoning_content 在训练样本里被剥掉：
#      训练期关 thinking（见 infra/finetune/base.py 的 enable_thinking 约束），
#      标签里留着思维链会让模型学会"输出思维链"而不是"给出答案"。
#      注意这与线上协议无关——线上 reasoning_content 仍要完整往返
#      （见 docs/maintenance.md §2.2 的不变式）。
#   3. **工具轨迹必须完整**。tool 消息前面必须是没有 tool_calls 的 assistant
#      （否则是"凭空出现的工具结果"），出现这种就整条丢掉。
#
# 数据来源（都可选，按需混用）：
#   - SessionStore（infra/store/chat_store.py）：线上真实对话；
#   - 自生成轨迹（selfplay）：用学生模型自己跑任务产生；
#   - 教师改写轨迹（teacher.refine_trajectory）：在自生成轨迹上做质量提升。

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from infra.finetune.dataset import DatasetStats, build_sft_dataset, normalize_messages, validate_messages

logger = logging.getLogger("harness.learning.dataset_builder")

#: 训练样本里要剥掉的字段（推理内容不进标签）。
STRIP_FIELDS = ("reasoning_content", "reasoning", "thinking")


@dataclass
class Trajectory:
    """一条待建样本的轨迹。

    source 用来标记来源，评测时可以按来源分层看指标
    （自生成的分数高不代表真实对话上表现好）。
    """

    messages: list[dict]
    source: str = "chat"
    meta: dict[str, Any] = field(default_factory=dict)

    def to_record(self, *, strip_reasoning: bool = True) -> dict[str, Any]:
        """转成 infra.finetune.dataset 认识的 {"messages": [...]} 记录。"""
        msgs = normalize_messages(self.messages)
        if strip_reasoning:
            for msg in msgs:
                for key in STRIP_FIELDS:
                    msg.pop(key, None)
        return {"messages": msgs, "source": self.source, **({"meta": self.meta} if self.meta else {})}


@dataclass
class BuildReport:
    """构建报告。"""

    stats: DatasetStats
    train_path: Optional[Path] = None
    val_path: Optional[Path] = None
    sources: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stats": self.stats.to_dict(),
            "train_path": str(self.train_path) if self.train_path else "",
            "val_path": str(self.val_path) if self.val_path else "",
            "sources": dict(self.sources),
        }


class DatasetBuilder:
    """轨迹收集器 + 数据集构建器。"""

    def __init__(
        self,
        out_dir: str | Path,
        *,
        strip_reasoning: bool = True,
        require_tool_integrity: bool = True,
        max_tokens: int = 1024,
        val_ratio: float = 0.05,
        seed: int = 42,
    ):
        self.out_dir = Path(out_dir).expanduser()
        self.strip_reasoning = strip_reasoning
        self.require_tool_integrity = require_tool_integrity
        self.max_tokens = max_tokens
        self.val_ratio = val_ratio
        self.seed = seed
        self._trajectories: list[Trajectory] = []
        self._sources: dict[str, int] = {}

    # ── 收集 ──

    def add(self, trajectory: Trajectory) -> bool:
        """加入一条轨迹。返回是否被接受（结构不合法的会被拒绝并记账）。"""
        if not trajectory.messages:
            self._sources[trajectory.source] = self._sources.get(trajectory.source, 0)
            return False
        if self.require_tool_integrity:
            problems = validate_messages(normalize_messages(trajectory.messages))
            if problems:
                logger.info("丢弃轨迹（结构不合法）: %s", problems[0])
                self._sources[trajectory.source] = self._sources.get(trajectory.source, 0)
                return False
        self._trajectories.append(trajectory)
        self._sources[trajectory.source] = self._sources.get(trajectory.source, 0) + 1
        return True

    def add_many(self, trajectories: Iterable[Trajectory]) -> int:
        return sum(1 for t in trajectories if self.add(t))

    def from_messages(self, messages: list[dict], *, source: str = "chat") -> bool:
        """从一段消息（线上会话的一轮）加入一条轨迹。"""
        return self.add(Trajectory(messages=list(messages), source=source))

    def from_session(self, store, session_id: str, *, source: str = "chat") -> bool:
        """从 SessionStore 取一个会话的完整消息并加入。

        store 需要提供 load_messages(session_id) -> list[ChatMessage]（或 dict）。
        """
        raw = store.load_messages(session_id)
        messages: list[dict] = []
        for msg in raw or []:
            if isinstance(msg, dict):
                messages.append(msg)
                continue
            item: dict[str, Any] = {
                "role": getattr(msg, "role", "user"),
                "content": getattr(msg, "content", "") or "",
            }
            tool_calls = getattr(msg, "tool_calls", None)
            if tool_calls:
                item["tool_calls"] = tool_calls
            tool_call_id = getattr(msg, "tool_call_id", None)
            if tool_call_id:
                item["tool_call_id"] = tool_call_id
            reasoning = getattr(msg, "reasoning_content", None)
            if reasoning:
                item["reasoning_content"] = reasoning
            messages.append(item)
        return self.add(Trajectory(messages=messages, source=source))

    # ── 构建 ──

    def build(self) -> BuildReport:
        """落盘 train/val JSONL。"""
        records = [t.to_record(strip_reasoning=self.strip_reasoning) for t in self._trajectories]
        stats, train_path, val_path = build_sft_dataset(
            records,
            self.out_dir,
            val_ratio=self.val_ratio,
            max_tokens=self.max_tokens,
            require_assistant=True,
            seed=self.seed,
        )
        logger.info("数据集构建完成: %s", self.out_dir)
        return BuildReport(stats=stats, train_path=train_path, val_path=val_path,
                           sources=dict(self._sources))

    @property
    def size(self) -> int:
        return len(self._trajectories)
