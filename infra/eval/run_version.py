# infra/eval/run_version.py
# RunVersion：一次实验的**冻结快照**。
#
# ── 为什么必须是「冻结快照」而不是「一个 git 分支名」？ ──
# 评测结论只有在「结论所依据的那份代码/数据」还在时才成立。
# 记一个分支名，两周后分支前进了，历史评测报告就再也复现不出来；
# 记一个 commit 还不够 —— 同一 commit 下，agent.yaml 可能被改过、
# 数据集可能扩了 case、模型可能悄悄换成了小一号的。
#
# 所以 RunVersion 冻结的是**内容**：
#   commit      —— 代码
#   artifact_yaml —— agent 定义（存内容，不存路径）
#   dataset_hash —— 评测集内容哈希
#   model       —— 模型标识
#   tool_versions —— 工具版本
#
# 有了这五样，任何一份历史评测报告都能被复现与追责：
# 「这条 case 为什么挂了」→ 回到这个快照 → 看当时的 artifact 与工具版本。

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional

#: 默认的 artifact 路径（相对仓库根）。
DEFAULT_ARTIFACT = "agents/research.yaml"


def _canonical(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def git_commit(repo_root: Optional[str | Path] = None) -> str:
    """取当前 commit（取不到就返回空串，不抛异常）。

    不抛异常是刻意的：CI 里跑评测时可能没有 .git 目录
    （源码包安装的场景），这时评测仍然应该能跑。
    """
    root = Path(repo_root) if repo_root else Path(__file__).resolve().parents[2]
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if out.returncode != 0:
        return ""
    return out.stdout.strip()


@dataclass(frozen=True)
class RunVersion:
    """一次被冻结的评测配置。

    frozen=True：快照一旦生成就不许改 —— 改了就不是同一个快照了。
    （注意：它含 dict 字段所以不可 hash；需要身份请用 :meth:`content_hash`。）
    """

    id: str
    commit: str = ""
    #: agent artifact 的**内容**（不是路径）。
    artifact_yaml: str = ""
    artifact_path: str = ""
    dataset_id: str = ""
    dataset_hash: str = ""
    model: str = ""
    tool_versions: Mapping[str, str] = field(default_factory=dict)
    label: str = ""
    created_at: float = 0.0
    extra: Mapping[str, Any] = field(default_factory=dict)

    def content_hash(self) -> str:
        """快照内容的哈希 —— 用来判断两次运行是不是同一份配置。"""
        payload = {
            "commit": self.commit,
            "artifact_yaml": self.artifact_yaml,
            "dataset_id": self.dataset_id,
            "dataset_hash": self.dataset_hash,
            "model": self.model,
            "tool_versions": dict(self.tool_versions),
        }
        return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()

    def matches_dataset(self, dataset_hash: str) -> bool:
        """快照里的数据集是否与给定哈希一致。"""
        return bool(dataset_hash) and self.dataset_hash == dataset_hash

    def diff(self, other: "RunVersion") -> dict[str, tuple[Any, Any]]:
        """两个快照的差异（用于报告里说清「这次到底改了什么」）。"""
        out: dict[str, tuple[Any, Any]] = {}
        pairs = (
            ("commit", self.commit, other.commit),
            ("artifact_yaml", self.artifact_yaml, other.artifact_yaml),
            ("dataset_id", self.dataset_id, other.dataset_id),
            ("dataset_hash", self.dataset_hash, other.dataset_hash),
            ("model", self.model, other.model),
            ("tool_versions", dict(self.tool_versions), dict(other.tool_versions)),
        )
        for name, a, b in pairs:
            if a != b:
                out[name] = (a, b)
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "commit": self.commit,
            "artifact_yaml": self.artifact_yaml,
            "artifact_path": self.artifact_path,
            "dataset_id": self.dataset_id,
            "dataset_hash": self.dataset_hash,
            "model": self.model,
            "tool_versions": dict(self.tool_versions),
            "label": self.label,
            "created_at": self.created_at,
            "extra": dict(self.extra),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RunVersion":
        return cls(
            id=str(data.get("id") or ""),
            commit=str(data.get("commit") or ""),
            artifact_yaml=str(data.get("artifact_yaml") or ""),
            artifact_path=str(data.get("artifact_path") or ""),
            dataset_id=str(data.get("dataset_id") or ""),
            dataset_hash=str(data.get("dataset_hash") or ""),
            model=str(data.get("model") or ""),
            tool_versions=dict(data.get("tool_versions") or {}),
            label=str(data.get("label") or ""),
            created_at=float(data.get("created_at") or 0.0),
            extra=dict(data.get("extra") or {}),
        )


def capture_run_version(
    *,
    dataset: Any = None,
    artifact_path: str | Path = "",
    artifact_yaml: str = "",
    model: str = "",
    tool_versions: Mapping[str, str] | None = None,
    commit: str = "",
    label: str = "",
    repo_root: str | Path = "",
    extra: Mapping[str, Any] | None = None,
) -> RunVersion:
    """抓一份 RunVersion 快照。

    :param dataset: EvalDataset（会取它的 id 与内容哈希）。
    :param artifact_path: agent 定义文件路径；**读取内容**冻结进快照。
    :param artifact_yaml: 直接给内容（与 artifact_path 二选一）。
    :param model: 模型标识，例如 ``openai/gpt-4o-mini``。
    :param tool_versions: 工具名 → 版本。
    """
    path_text = str(artifact_path or "")
    if not artifact_yaml and path_text:
        p = Path(path_text)
        if p.exists():
            artifact_yaml = p.read_text(encoding="utf-8")
        # 路径不存在不算致命：快照里记下路径，commit 仍能定位代码。
    if not commit:
        commit = git_commit(repo_root)

    dataset_id = ""
    dataset_hash = ""
    if dataset is not None:
        dataset_id = getattr(dataset, "id", "") or ""
        dataset_hash = getattr(dataset, "hash", "") or ""

    rv = RunVersion(
        id="",  # 下面按内容哈希生成
        commit=commit,
        artifact_yaml=artifact_yaml,
        artifact_path=path_text,
        dataset_id=dataset_id,
        dataset_hash=dataset_hash,
        model=model,
        tool_versions=dict(tool_versions or {}),
        label=label,
        created_at=time.time(),
        extra=dict(extra or {}),
    )
    # id 由内容哈希派生：同样的配置 → 同样的 id（可复现）。
    rv = RunVersion(
        id=f"rv_{rv.content_hash()[:12]}",
        commit=rv.commit,
        artifact_yaml=rv.artifact_yaml,
        artifact_path=rv.artifact_path,
        dataset_id=rv.dataset_id,
        dataset_hash=rv.dataset_hash,
        model=rv.model,
        tool_versions=rv.tool_versions,
        label=rv.label,
        created_at=rv.created_at,
        extra=rv.extra,
    )
    return rv
