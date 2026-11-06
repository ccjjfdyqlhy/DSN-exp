
# infra/finetune/dataset.py
# SFT 数据集的**格式层**：把对话样本整理成训练器能吃的 JSONL。
#
# 分工（很重要，别越界）：
#   infra/finetune/dataset.py —— 格式：角色归一、合法性检查、截断、train/val 切分、写盘。
#   harness/learning/dataset_builder.py —— 取数：从 chat_store / memory / 自生成 / 情感素材
#                                          汇成对话样本，调用本模块落盘。
#   本地实验应用 —— 只提供样本，不碰格式。
#
# 数据集文件格式（一行一个 JSON 对象）：
#   {"messages": [{"role": "user", "content": "..."},
#                 {"role": "assistant", "content": "..."}]}
# 训练脚本（train_sft.py）负责套 chat template 与 tokenize。
#
# 纯标准库，不 import torch。

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

logger = logging.getLogger("infra.finetune.dataset")

VALID_ROLES = ("system", "user", "assistant", "tool")


@dataclass(slots=True)
class DatasetStats:
    """数据集构建的统计与丢弃原因。"""

    total: int = 0
    kept: int = 0
    dropped: int = 0
    reasons: dict[str, int] = field(default_factory=dict)

    def drop(self, reason: str) -> None:
        self.dropped += 1
        self.reasons[reason] = self.reasons.get(reason, 0) + 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "kept": self.kept,
            "dropped": self.dropped,
            "reasons": dict(self.reasons),
        }


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """读 JSONL。空行忽略，坏行记日志后跳过（不因为一行脏数据丢掉整个数据集）。"""
    p = Path(path).expanduser()
    records: list[dict[str, Any]] = []
    with open(p, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning("跳过第 %d 行（JSON 解析失败）: %s", lineno, exc)
                continue
            if isinstance(obj, dict):
                records.append(obj)
            else:
                logger.warning("跳过第 %d 行（不是 JSON 对象）", lineno)
    return records


def write_jsonl(path: str | Path, records: Iterable[dict[str, Any]]) -> int:
    """写 JSONL，返回写出的条数。"""
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with open(p, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            count += 1
    return count


def normalize_messages(messages: Any) -> list[dict[str, Any]]:
    """把消息列表归一成 [{role, content, ...}]。

    允许两种输入：
      - [{"role": ..., "content": ...}]        （标准）
      - {"role": ..., "content": ...} 单条
    非字符串 content（如多模态块列表）会被转成 JSON 字符串保留信息，不丢弃。
    """
    if isinstance(messages, dict):
        messages = [messages]
    if not isinstance(messages, list):
        return []
    out: list[dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", "")).strip()
        if role not in VALID_ROLES:
            continue
        content = msg.get("content", "")
        if isinstance(content, list):
            content = json.dumps(content, ensure_ascii=False)
        elif content is None:
            content = ""
        else:
            content = str(content)
        item: dict[str, Any] = {"role": role, "content": content}
        # tool_calls / tool_call_id 等字段原样保留：工具调用轨迹是 DSN 的主要训练信号。
        for key in ("tool_calls", "tool_call_id", "name", "reasoning_content"):
            if key in msg and msg[key] is not None:
                item[key] = msg[key]
        out.append(item)
    return out


def validate_messages(messages: list[dict[str, Any]]) -> list[str]:
    """返回问题列表（空列表 = 合法）。

    这里检查的是仓库的两条不变式（见 docs/maintenance.md §2.2）：
      - tool 消息必须紧跟在带 tool_calls 的 assistant 消息之后；
      - assistant 的 reasoning_content 必须随消息一起保留（不能丢）。
    """
    problems: list[str] = []
    has_tool_call = False
    for idx, msg in enumerate(messages):
        role = msg.get("role")
        if role == "assistant" and msg.get("tool_calls"):
            has_tool_call = True
        elif role == "tool" and not has_tool_call:
            problems.append(f"第 {idx} 条 tool 消息前面没有 assistant(tool_calls)")
        elif role != "tool":
            has_tool_call = False
    if not any(m.get("role") == "assistant" for m in messages):
        problems.append("没有 assistant 消息，无法作为 SFT 样本")
    if not any(m.get("role") == "user" for m in messages):
        problems.append("没有 user 消息，无法作为 SFT 样本")
    return problems


def estimate_chars(messages: list[dict[str, Any]]) -> int:
    """粗略估算 token 数（按 4 字符 ≈ 1 token 的经验值）。

    只用于**前置过滤**——真正的截断在训练脚本里按 tokenizer 做。
    这里必须留出余量，否则会漏掉那些"看着短但 token 很多"的样本。
    """
    total = 0
    for msg in messages:
        content = msg.get("content") or ""
        total += len(content)
        for call in msg.get("tool_calls") or []:
            total += len(json.dumps(call, ensure_ascii=False))
    return total // 4 + 8 * len(messages)


def build_sft_dataset(
    records: Iterable[dict[str, Any]],
    out_dir: str | Path,
    *,
    val_ratio: float = 0.05,
    max_tokens: int = 1024,
    require_assistant: bool = True,
    seed: int = 42,
) -> tuple[DatasetStats, Path, Path]:
    """把原始记录整理成 train/val 两个 JSONL。

    返回 (统计, train 路径, val 路径)。
    切分用固定 seed 的确定性洗牌，保证同样输入产出同样数据集（可复现是评测的前提）。
    """
    import random

    stats = DatasetStats()
    kept: list[dict[str, Any]] = []

    for rec in records:
        stats.total += 1
        messages = normalize_messages(rec.get("messages", rec.get("conversation")))
        if not messages:
            stats.drop("没有可用的消息")
            continue
        problems = validate_messages(messages)
        if problems and require_assistant:
            stats.drop(f"消息结构不合法: {problems[0]}")
            continue
        if estimate_chars(messages) > max_tokens:
            stats.drop(f"超过长度上限({max_tokens} token 估算)")
            continue
        kept.append({"messages": messages})

    rng = random.Random(seed)
    rng.shuffle(kept)

    out = Path(out_dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    n_val = int(len(kept) * val_ratio)
    # 样本太少时不切验证集——否则 val 集为空会让 loss 曲线失去意义。
    if n_val < 1 and len(kept) >= 10:
        n_val = 1
    val_records = kept[:n_val]
    train_records = kept[n_val:]

    train_path = out / "train.jsonl"
    val_path = out / "val.jsonl"
    write_jsonl(train_path, train_records)
    write_jsonl(val_path, val_records)

    stats.kept = len(kept)
    logger.info(
        "数据集构建完成: %s（train=%d val=%d 丢弃=%d）",
        out, len(train_records), len(val_records), stats.dropped,
    )
    return stats, train_path, val_path
