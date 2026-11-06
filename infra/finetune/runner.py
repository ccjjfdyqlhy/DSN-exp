
# infra/finetune/runner.py
# 训练作业的执行与编排：排队 → 等卡 → 起子进程训练 → 落库。
#
# 复用仓库既有的通用任务系统（infra/tasks）：
#   - 训练作业就是一个 Task（type = "finetune.train"）；
#   - 用 TaskExecutorRegistry 跑，**专用一个只有 1 个 worker 的注册表**——
#     训练在本机天然是串行的（本机 2×2080Ti，同时跑两个 QLoRA 必 OOM）。
# 不用 TaskScheduler 的原因：它按时间/间隔触发任务，而训练是"提交一次、跑一次"。
#
# 子进程边界（铁律）：
#   DSN 主进程**不 import torch**。训练在独立解释器里以独立脚本运行，
#   主进程只负责：写 spec.json、拉起进程、收日志、读 result.json。

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Optional

from ..tasks.base import Task, TaskExecutor, TaskStatus
from ..tasks.registry import TaskExecutorRegistry
from .base import (
    JobState,
    SpecError,
    TrainJob,
    TrainSpec,
    TrainingFailed,
    new_job_id,
)
from .env import check_model_support, environment, resolve_python, subprocess_env
from .store import FinetuneStore

logger = logging.getLogger("infra.finetune.runner")

#: 训练脚本（独立脚本，不 import 仓库模块）。
TRAIN_SCRIPT = Path(__file__).with_name("train_sft.py")

#: 作业根目录：默认放在用户主目录下，避免撑爆系统盘（实测 / 只剩 7.8G）。
DEFAULT_ROOT = Path("~/dsn-finetune").expanduser()


class FinetuneManager:
    """训练作业管理器——本文件是 infra/finetune 的服务层入口。

    公开 API（本地应用与 harness 只用这几个）：
        submit(spec) → TrainJob     提交作业（异步执行，立刻返回）
        status(job_id) → TrainJob   查单个作业
        list_jobs() → list[TrainJob] 列出作业
        promote(job_id, slot) → dict  把适配器晋级到槽位
        rollback(slot) → dict         回滚槽位到上一个适配器
    """

    def __init__(
        self,
        *,
        store: Optional[FinetuneStore] = None,
        python: Optional[str] = None,
        root: Optional[str | Path] = None,
        device_timeout: Optional[float] = None,
        scheduler=None,
    ):
        self._store = store or FinetuneStore()
        self._python = python
        self._root = Path(root).expanduser() if root else DEFAULT_ROOT
        self._root.mkdir(parents=True, exist_ok=True)
        self._device_timeout = (
            device_timeout if device_timeout is not None
            else float(os.environ.get("FINETUNE_DEVICE_TIMEOUT", "3600"))
        )
        self._scheduler = scheduler
        self._lock = threading.RLock()
        self._jobs: dict[str, TrainJob] = {}
        # 单 worker：训练必须串行。
        self._registry = TaskExecutorRegistry(max_workers=1)
        self._registry.register(self._make_executor(), replace=True)

    # ── 公开 API ──

    def submit(self, spec: TrainSpec) -> TrainJob:
        """提交训练作业。立即返回（QUEUED 状态），训练在后台线程里跑。

        提交前会做两道拦截：
          1. `TrainSpec.validate()` —— 参数自检（**含 GGUF 拦截**）；
          2. **架构可行性检查** —— 用训练解释器里的 transformers 真正加载一次模型配置，
             确认它的架构被支持；不支持就在提交阶段报错，而不是等训练跑起来才炸。

        关于"Bonsai-2 / JEV-27B-VL 不可训练"：
        本机这两个模型**只有 GGUF**（Bonsai 的 PQ2_0 还是上游读不了的私有量化类型），
        所以第 1 道闸就挡住了它们；它们的底座 `Qwen3.8-27B`（model_type `qwen3_5`）
        在 transformers 5.20.2 下**架构上是可训的**——但训底座产不出 Bonsai 的三值化/
        旋转基，也产不出 JEV 的 VL 塔与 System-1 决策头，所以本项目只走
        `qwen3` 家族的学生线（这条边界不可动摇）。
        """
        spec.validate()
        self._assert_trainable(spec)

        job = TrainJob(id=new_job_id(), spec=spec, state=JobState.QUEUED)
        with self._lock:
            self._jobs[job.id] = job
        self._store.save_job(job)

        task = Task(type="finetune.train", params={"job_id": job.id})
        self._registry.submit(task, callback=self._on_task_done)
        logger.info("训练作业已提交: %s base=%s dataset=%s", job.id, spec.base_model, spec.dataset_path)
        return job

    def _assert_trainable(self, spec: TrainSpec) -> None:
        """确认学生模型的架构当前可训练。不可训练就直接拒绝提交。

        只在拿到**明确的架构结论**时才拒绝提交：
        解释器缺失、网络不通、权重没下载这些是环境问题，
        它们由作业里的环境体检去报告，不该在这里被误判成"架构不可训"。
        """
        info = check_model_support(spec.base_model, python=self._python)
        model_type = info.get("model_type")
        if info.get("supported"):
            self._warn_if_base_family(spec, model_type)
            logger.info("模型架构检查通过: %s (%s)", spec.base_model, model_type)
            return

        kind = info.get("kind")
        reason = str(info.get("reason") or "未知原因")

        if kind == "env" or (kind is None and not model_type):
            logger.warning(
                "模型架构检查无法完成（环境问题，交由作业体检处理）: %s — %s", spec.base_model, reason
            )
            return

        if model_type in ("qwen3_5", "qwen35", "qwen4_exp"):
            # 实测：transformers 5.20.2 支持 qwen3_5（models/qwen3_5 存在）。
            # 但 Bonsai-2 / JEV-27B-VL 这类 27B 只以 GGUF 形式存在（没有 HF 权重），
            # 已经被 GGUF 拦截挡住；走到这里的说明用户显式指定了一个 qwen3_5 的 HF 仓库
            # （如底座 Qwen/Qwen3.8-27B）。**允许**，但把话说清楚：训它不会得到 Bonsai/JEV。
            self._warn_if_base_family(spec, model_type)
            return
        raise SpecError(
            f"模型 {spec.base_model} 的架构 {model_type} 当前不可训练: {reason}"
        )

    @staticmethod
    def _warn_if_base_family(spec: TrainSpec, model_type: Optional[str]) -> None:
        """`qwen3_5` = Bonsai-2 / JEV-27B-VL 的底座家族，提醒一句。"""
        if model_type not in ("qwen3_5", "qwen35", "qwen4_exp"):
            return
        logger.warning(
            "模型 %s 是 %s 架构（Bonsai-2 / JEV-27B-VL 的底座家族）：架构可训，"
            "但训练产物只是底座，不会带上 Bonsai 的三值化/旋转基或 JEV 的 VL 塔与决策头",
            spec.base_model, model_type,
        )

    def status(self, job_id: str) -> Optional[TrainJob]:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is not None:
            return job
        return self._store.get_job(job_id)

    def list_jobs(self, limit: int = 50) -> list[TrainJob]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
        if jobs:
            return jobs[:limit]
        return self._store.list_jobs(limit)

    def promote(self, job_id: str, slot: str) -> dict[str, Any]:
        """把某个成功作业的适配器晋级为槽位的生效版本。"""
        job = self.status(job_id)
        if job is None:
            raise ValueError(f"作业不存在: {job_id}")
        if job.state != JobState.SUCCEEDED:
            raise ValueError(f"作业未成功，不能晋级: {job_id} ({job.state.value})")
        return self._store.promote(slot, job_id)

    def rollback(self, slot: str) -> dict[str, Any]:
        """回滚槽位到上一个适配器。"""
        return self._store.rollback(slot)

    def wait(self, job_id: str, timeout: float = 3600.0) -> Optional[TrainJob]:
        """阻塞等待作业结束（主要给测试和命令行用）。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            job = self.status(job_id)
            if job is not None and job.done:
                return job
            time.sleep(0.2)
        return self.status(job_id)

    def shutdown(self) -> None:
        self._registry.shutdown(wait=False)

    # ── 内部 ──

    def _on_task_done(self, task: Task) -> None:
        job_id = task.params.get("job_id")
        if not job_id:
            return
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return
        if task.status == TaskStatus.FAILED and job.state == JobState.RUNNING:
            job.state = JobState.FAILED
            job.error = task.error or "训练任务失败"
            job.finished_at = time.time()
            self._store.save_job(job)

    def _make_executor(self):
        manager = self

        class _Executor(TaskExecutor):
            type = "finetune.train"

            def execute(self, task: Task) -> Any:
                job_id = task.params.get("job_id")
                job = manager.status(job_id)
                if job is None:
                    raise TrainingFailed(f"作业不存在: {job_id}")
                return manager._run_job(job)

        return _Executor()

    def _run_job(self, job: TrainJob) -> dict[str, Any]:
        """真正跑一次训练：体检 → 等卡 → 子进程训练 → 收结果。"""
        job.state = JobState.RUNNING
        job.started_at = time.time()
        self._store.save_job(job)

        spec = job.spec
        output_dir = Path(spec.output_dir).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
        log_path = output_dir / "train.log"
        job.log_path = str(log_path)

        # 1) 环境体检：解释器/torch/依赖不对就别浪费卡。
        report = environment(self._python)
        if not report.get("available"):
            job.state = JobState.FAILED
            job.error = f"训练环境不可用: {report.get('reason')}"
            job.finished_at = time.time()
            self._store.save_job(job)
            raise TrainingFailed(job.error)

        # 2) 等显卡：显存由编排器的闸门仲裁（JEV 独占双卡时训练必须排队）。
        lease = self._acquire_devices(job)
        try:
            # 3) 写 spec 并起子进程。
            spec_path = output_dir / "spec.json"
            spec_path.write_text(
                json.dumps(spec.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
            )
            cmd = [
                resolve_python(self._python),
                str(TRAIN_SCRIPT),
                "--spec", str(spec_path),
            ]
            env = self._subprocess_env()
            logger.info("启动训练: %s", " ".join(cmd))
            with open(log_path, "w", encoding="utf-8") as log_fh:
                log_fh.write(f"# cmd: {' '.join(cmd)}\n")
                log_fh.flush()
                proc = subprocess.run(
                    cmd, stdout=log_fh, stderr=subprocess.STDOUT, env=env, check=False,
                )
            # 4) 收结果。
            result_path = output_dir / "result.json"
            result = {}
            if result_path.exists():
                try:
                    result = json.loads(result_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    result = {}
        finally:
            if lease is not None:
                self._release_devices(lease)

        if proc.returncode != 0 or result.get("status") != "succeeded":
            job.state = JobState.FAILED
            job.error = result.get("error") or f"训练进程退出码 {proc.returncode}，日志: {log_path}"
            job.finished_at = time.time()
            self._store.save_job(job)
            raise TrainingFailed(job.error)

        job.state = JobState.SUCCEEDED
        job.adapter_path = result.get("adapter_path", "")
        job.metrics = result.get("metrics", {})
        job.finished_at = time.time()
        self._store.save_job(job)
        logger.info("训练完成: %s 用时 %.1fs", job.id, job.duration)
        return {"adapter_path": job.adapter_path, "metrics": job.metrics}

    def _acquire_devices(self, job: TrainJob):
        """申请显存租约。拿不到就排队等（timeout 由 FINETUNE_DEVICE_TIMEOUT 控制）。"""
        try:
            from ..orchestrator.scheduler import ModelScheduler
        except Exception:
            logger.warning("无法导入编排器，跳过显存闸门", exc_info=True)
            return None

        scheduler = self._scheduler or ModelScheduler.get_instance()
        gate = scheduler.device_gate
        requested = tuple(job.spec.gpus) if job.spec.gpus else ()
        if not requested:
            # 没指定就用当前空闲的卡；一张都没有就等任意一张空出来。
            free = tuple(gate.free_devices())
            if not free:
                logger.info("等待空闲显卡（作业 %s）", job.id)
                return gate.acquire_any(
                    f"finetune:{job.id}", reason=job.spec.base_model,
                    timeout=self._device_timeout,
                )
            requested = free

        return gate.acquire(
            requested, f"finetune:{job.id}", reason=job.spec.base_model,
            timeout=self._device_timeout,
        )

    def _release_devices(self, lease) -> None:
        try:
            from ..orchestrator.scheduler import ModelScheduler
        except Exception:
            return
        scheduler = self._scheduler or ModelScheduler.get_instance()
        scheduler.device_gate.release(lease)

    @staticmethod
    def _subprocess_env() -> dict[str, str]:
        """子进程环境变量（HF_ENDPOINT 指向 hf-mirror 等）。"""
        return subprocess_env()
