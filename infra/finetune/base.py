
# infra/finetune/base.py
# 训练子系统的基础契约：作业状态、训练参数、产物描述。
#
# 这个文件是「本地应用」与「GitHub 上的框架层」之间的唯一契约：
# 本地实验应用（apps/dsn_bonsai 等）只允许通过这里的类型与 infra.finetune 的
# 公开函数提交训练、查询状态、取回产物——不允许直接 import 训练后端。
#
# 为什么要独立成契约：
#   1. 应用层不碰 torch：DSN 主进程保持零 torch 依赖（见 apps/dsn/models/asr_engine.py:92
#      的既有约定：只用 sys.modules.get("torch") 做防御性检查）。
#   2. 训练参数与后端解耦：换后端（peft / llama.cpp / unsloth）不改调用方。
#   3. 状态机集中：候选→评测→晋级→回滚的生命周期只有一处定义。
#
# 生命周期（候选态 → 终态）：
#   QUEUED → RUNNING → SUCCEEDED
#                    ↘ FAILED
#           ↘ CANCELLED
#   SUCCEEDED 之后由 harness/learning 的 promotion 决定
#   candidate → staged → active → archived / rolled_back（晋级规则在 harness 层，不在这里）。

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional


class JobState(Enum):
    """训练作业状态。"""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def done(self) -> bool:
        return self in (JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED)


class FinetuneError(Exception):
    """训练子系统的统一异常。

    分两类：
      - 配置类（EnvironmentUnavailable / SpecError）：调用方的问题，应当在提交前就拦住；
      - 运行类（TrainingFailed / Cancelled）：作业跑挂了，错误信息里必须带日志路径。
    """


class EnvironmentUnavailable(FinetuneError):
    """训练解释器或依赖不可用。"""


class SpecError(FinetuneError):
    """训练参数非法。"""


class TrainingFailed(FinetuneError):
    """训练进程非零退出。"""


@dataclass(slots=True)
class TrainSpec:
    """一次训练作业的完整参数（与后端无关）。

    默认值按本机实测硬件（2×RTX 2080Ti / sm_75 / 22GB）选过：
      - 4bit QLoRA：8B 模型的 fp16 权重 16GB，双卡虽够但没有余量；
      - seq_len 1024：11GB 单卡的现实上限，长轨迹在数据集层截断/打包，不靠加 seq_len；
      - float16 + sdpa：sm_75 没有原生 bf16，FA2 在 sm_75 上直接报
        "No available kernel"（本机 sm_75 实测）；
      - enable_thinking=False：thinking 是推理期的事，训练期一律走短轨迹的 non-thinking 模板。
    """

    base_model: str
    dataset_path: str
    output_dir: str
    #: 实际用于训练的数据文件（train.jsonl）。留空则用 dataset_path。
    #: 单独列出来是因为数据集构建器会产出 train/val 两个文件，
    #: 训练用 train、评测用 val，混用会让 val 损失失去意义。
    train_path: str = ""
    method: str = "qlora"                      # qlora | lora | full
    lora_rank: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.05
    target_modules: tuple[str, ...] = ("q_proj", "k_proj", "v_proj", "o_proj")
    seq_len: int = 1024
    batch_size: int = 1
    grad_accum: int = 16
    lr: float = 2e-4
    epochs: float = 2.0
    dtype: str = "float16"
    attn_implementation: str = "sdpa"
    gradient_checkpointing: bool = True
    enable_thinking: bool = False              # 训练期固定 False
    max_steps: int = -1                        # >0 时覆盖 epochs，用于冒烟测试
    gpus: tuple[int, ...] = ()                # 空 = 全部 GPU
    seed: int = 42
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转成可 JSON 序列化的形式（tuple → list）。"""
        data = asdict(self)
        data["target_modules"] = list(self.target_modules)
        data["gpus"] = list(self.gpus)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TrainSpec":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        kwargs = {k: v for k, v in data.items() if k in known}
        if "target_modules" in kwargs:
            kwargs["target_modules"] = tuple(kwargs["target_modules"])
        if "gpus" in kwargs:
            kwargs["gpus"] = tuple(kwargs["gpus"])
        return cls(**kwargs)

    def validate(self) -> None:
        """提交前的参数自检。非法就抛 SpecError，不要浪费一次 GPU 作业。"""
        if not self.base_model:
            raise SpecError("base_model 不能为空")
        if not self.dataset_path:
            raise SpecError("dataset_path 不能为空")
        if not self.output_dir:
            raise SpecError("output_dir 不能为空")
        if self.method not in ("qlora", "lora", "full"):
            raise SpecError(f"未知的训练方法: {self.method}")
        if self.method == "full" and self.lora_rank:
            # full 微调不用 LoRA 参数，留着会让人误以为 LoRA 生效了。
            self.lora_rank = 0
        if self.seq_len <= 0:
            raise SpecError("seq_len 必须为正")
        if self.batch_size <= 0 or self.grad_accum <= 0:
            raise SpecError("batch_size / grad_accum 必须为正")
        if self.enable_thinking:
            # 这是本项目的一条纪律而不是偏好：训练期开 thinking 会让序列长度爆炸，
            # 且教师思维链会污染学生（思维链剥离见 harness/learning/dataset_builder.py）。
            raise SpecError("训练期不允许开启 thinking（enable_thinking 必须为 False）")
        if self.base_model.lower().endswith(".gguf"):
            # GGUF 是量化推理格式，训练必须用 HF 权重。
            # 这条同时挡住了 Bonsai-2 / JEV-27B-VL：本机它们**只有** GGUF
            # （Bonsai 的 PQ2_0 还是上游读不了的私有量化类型），没有可训的 HF 权重。
            raise SpecError(
                f"base_model 不能是 GGUF 文件（{self.base_model}）："
                "训练需要 HF 格式权重；Bonsai-2 / JEV-27B-VL 属于不可训练的一类"
            )


@dataclass(slots=True)
class TrainJob:
    """一个训练作业的状态快照。"""

    id: str
    spec: TrainSpec
    state: JobState = JobState.QUEUED
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    adapter_path: str = ""                     # 训练产出的 LoRA 适配器目录
    log_path: str = ""                         # 训练日志
    error: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def done(self) -> bool:
        return self.state.done

    @property
    def duration(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.finished_at if self.finished_at is not None else time.time()
        return end - self.started_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "state": self.state.value,
            "spec": self.spec.to_dict(),
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "adapter_path": self.adapter_path,
            "log_path": self.log_path,
            "error": self.error,
            "metrics": dict(self.metrics),
            "duration": self.duration,
        }


def new_job_id() -> str:
    """生成作业 id。带时间前缀是为了让日志目录天然按时间排序。"""
    return f"job-{int(time.time())}-{uuid.uuid4().hex[:6]}"
