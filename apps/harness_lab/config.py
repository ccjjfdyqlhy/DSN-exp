# apps/harness_lab/config.py
"""验证台配置 —— 运行期求值（不像 dsn_study 的 Config 那样是 import 期快照）。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
#: 验证台自带的角色卡模板（复制进每个场景的隔离目录）
CARDS_SRC_DIR = Path(__file__).resolve().parent / "cards"
#: 默认输出目录
DEFAULT_OUTPUT_DIR = REPO_ROOT / ".dsn" / "harness_lab"


@dataclass
class LabConfig:
    """一次验证运行的全部参数。"""

    output_dir: Path = DEFAULT_OUTPUT_DIR
    llm_mode: str = "scripted"        # scripted | live
    honor_max_tokens: bool = True      # 桩是否如实遵守 max_tokens（对照组关掉）
    keep_workspace: bool = True        # 保留场景工作区（便于事后翻证据）
    uid: int = 1
    only: tuple[str, ...] = field(default_factory=tuple)   # 只跑这些场景
    verbose: bool = False

    @property
    def is_live(self) -> bool:
        return self.llm_mode == "live"

    def scenario_dir(self, scenario_id: str) -> Path:
        return self.output_dir / "workspaces" / scenario_id

    @classmethod
    def from_args(cls, args) -> "LabConfig":
        out = Path(args.out).expanduser().resolve() if args.out else DEFAULT_OUTPUT_DIR
        return cls(
            output_dir=out,
            llm_mode="live" if getattr(args, "llm", "scripted") == "live" else "scripted",
            honor_max_tokens=not getattr(args, "no_truncate", False),
            keep_workspace=not getattr(args, "clean", False),
            uid=int(getattr(args, "uid", 1) or 1),
            only=tuple(getattr(args, "scenario", ()) or ()),
            verbose=bool(getattr(args, "verbose", False)),
        )

    def ensure_dirs(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "workspaces").mkdir(parents=True, exist_ok=True)

    def describe(self) -> dict:
        return {
            "output_dir": str(self.output_dir),
            "llm_mode": self.llm_mode,
            "honor_max_tokens": self.honor_max_tokens,
            "uid": self.uid,
            "only": list(self.only),
        }


def live_credentials_available() -> bool:
    """真实模式是否具备基本凭据（不校验有效性，只看有没有配）。"""
    return bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("LLMSTUDIO_BASE_URL"))
