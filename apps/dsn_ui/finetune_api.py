# apps/dsn_ui/finetune_api.py
"""微调工坊 HTTP API —— /api/finetune/*。

定位：**本地实验用的门面层**。它只做三件事——
  1. 把 infra.finetune 的公开 API（submit/status/list/promote/rollback）翻译成 HTTP；
  2. 把阻塞调用（子进程体检、SQLite、子进程训练）挪到线程池，绝不冻结事件循环；
  3. 把框架层异常翻译成前端能直接显示的错误文案。

三层纪律（docs/architecture.md）：apps/ → harness/ → infra/ 单向依赖。
本模块只依赖 infra.finetune（框架层），不 import 任何 harness/ 应用层的东西，
也不自己实现训练逻辑——那些都在 infra/finetune/ 里。

边界：
  * 主进程**不 import torch**——训练跑在独立解释器里（infra/finetune/train_sft.py）；
  * 显存由编排器的 DeviceGate 仲裁，本模块不自己管卡；
  * 提交作业前会做两道拦截：参数自检 + 架构可训练性检查（都在 infra 层）。

本文件属于 apps/ 层，按本地专用策略**不上 GitHub**（.git/local-only-policy.txt）。
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("DSNUIServer")

#: 作业目录根：默认 ~/dsn-finetune（与 infra.finetune.runner 的默认一致）。
DEFAULT_ROOT = os.environ.get("FINETUNE_ROOT", "~/dsn-finetune")

#: 日志回显的最大行数（防止把几 MB 的训练日志塞进前端）。
MAX_LOG_TAIL = 400

_manager = None
_manager_lock = threading.Lock()


def get_manager():
    """取全局唯一的 FinetuneManager（懒创建）。

    为什么是全局单例：训练作业是**跨请求的长任务**——提交后要能立刻查状态，
    几分钟后还能查日志，还要能晋级/回滚。管理器若按请求创建，
    作业登记、显存排队、单 worker 执行器都会跟着重建，状态就断了。
    """
    global _manager
    with _manager_lock:
        if _manager is None:
            from infra.finetune.runner import FinetuneManager
            from infra.finetune.store import FinetuneStore

            root = Path(DEFAULT_ROOT).expanduser()
            root.mkdir(parents=True, exist_ok=True)
            # 作业登记落盘：默认 FinetuneStore 是 :memory:，进程一重启历史就断了，
            # 前端会看不到昨天跑过的作业。路径由 apps 层决定（框架层不规定存哪）。
            db_path = Path(
                os.environ.get("FINETUNE_DB", str(root / "jobs.db"))
            ).expanduser()
            _manager = FinetuneManager(
                store=FinetuneStore(db_path), root=root,
            )
            logger.info("微调管理器已初始化: root=%s db=%s", root, db_path)
        return _manager


def _read_log_tail(log_path: str, max_lines: int) -> str:
    """读日志尾部。文件不存在或读失败都返回空串，不让前端炸掉。"""
    if not log_path or max_lines <= 0:
        return ""
    path = Path(log_path).expanduser()
    if not path.is_file():
        return ""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError as exc:
        logger.warning("读取训练日志失败 %s: %s", path, exc)
        return ""
    return "".join(lines[-max_lines:])


def _error_response(exc: Exception, *, status: int = 500) -> JSONResponse:
    """把框架层异常翻译成前端可显示的错误。

    400 = 调用方写错了（参数非法、作业不存在）；
    503 = 环境不可用（训练解释器/torch/CUDA 缺失）。
    """
    from infra.finetune.base import EnvironmentUnavailable, FinetuneError, SpecError

    if isinstance(exc, (SpecError, TypeError)):
        status = 400
    elif isinstance(exc, EnvironmentUnavailable):
        status = 503
    elif isinstance(exc, ValueError):
        status = 400
    elif isinstance(exc, FinetuneError):
        status = 500
    logger.warning("微调 API 失败: %s: %s", type(exc).__name__, exc)
    return JSONResponse(status_code=status, content={"error": str(exc) or exc.__class__.__name__})


def register_finetune_routes(app: FastAPI) -> None:
    """把微调工坊路由注册到 FastAPI app。

    调用方必须在 SPA catch-all（GET /{full_path:path}）**之前**调用本函数，
    否则请求会被 catch-all 吞掉、返回 index.html 而不是 JSON。
    """

    # ── 环境体检 ──────────────────────────────────────────────
    @app.get("/api/finetune/env")
    async def finetune_env():
        """训练环境体检（子进程探针，可能要几秒）。"""
        from infra.finetune.env import environment

        try:
            report = await asyncio.to_thread(environment)
        except Exception as exc:  # noqa: BLE001
            return _error_response(exc)
        return report

    @app.get("/api/finetune/environment")
    async def finetune_environment_alias():
        """/env 的别名（计划稿 §5 里写的就是 /environment）。"""
        return await finetune_env()

    # ── 显存占用 ──────────────────────────────────────────────
    @app.get("/api/finetune/devices")
    async def finetune_devices():
        """DeviceGate 的占用情况：空闲卡、被谁占了。"""
        try:
            from infra.orchestrator.scheduler import ModelScheduler

            gate = ModelScheduler.get_instance().device_gate
            return {
                "device_count": gate.device_count,
                "free": gate.free_devices(),
                "occupancy": gate.occupancy(),
            }
        except Exception as exc:  # noqa: BLE001
            return _error_response(exc)

    # ── 作业列表 / 详情 ───────────────────────────────────────
    @app.get("/api/finetune/jobs")
    async def finetune_jobs(limit: int = 50):
        try:
            manager = get_manager()
            jobs = await asyncio.to_thread(manager.list_jobs, max(1, min(limit, 200)))
            return {"jobs": [j.to_dict() for j in jobs]}
        except Exception as exc:  # noqa: BLE001
            return _error_response(exc)

    @app.get("/api/finetune/jobs/{job_id}")
    async def finetune_job(job_id: str, log_tail: int = 0):
        """作业详情。log_tail>0 时附带日志尾部（行）。"""
        try:
            manager = get_manager()
            job = await asyncio.to_thread(manager.status, job_id)
            if job is None:
                return JSONResponse(
                    status_code=404, content={"error": f"作业不存在: {job_id}"}
                )
            tail = await asyncio.to_thread(
                _read_log_tail, job.log_path, min(max(log_tail, 0), MAX_LOG_TAIL)
            )
            return {"job": job.to_dict(), "log": tail}
        except Exception as exc:  # noqa: BLE001
            return _error_response(exc)

    @app.get("/api/finetune/jobs/{job_id}/logs")
    async def finetune_job_logs(job_id: str, tail: int = 200):
        """只取日志尾部（计划稿 §5 的 /jobs/{id}/logs?tail=200）。"""
        try:
            manager = get_manager()
            job = await asyncio.to_thread(manager.status, job_id)
            if job is None:
                return JSONResponse(
                    status_code=404, content={"error": f"作业不存在: {job_id}"}
                )
            text = await asyncio.to_thread(
                _read_log_tail, job.log_path, min(max(tail, 0), MAX_LOG_TAIL)
            )
            return {"job_id": job_id, "log": text, "log_path": job.log_path}
        except Exception as exc:  # noqa: BLE001
            return _error_response(exc)

    # ── 提交训练 ──────────────────────────────────────────────
    @app.post("/api/finetune/jobs")
    async def finetune_submit(request: Request):
        """提交一次训练。

        body 是 TrainSpec 的子集（缺省值由 infra 层补齐）。
        非法参数在**提交前**就被拦住，不会浪费一次 GPU 作业。
        """
        from infra.finetune.base import TrainSpec

        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        if not isinstance(body, dict):
            return JSONResponse(status_code=400, content={"error": "请求体必须是 JSON 对象"})

        # 只接受 TrainSpec 认识的字段，避免前端传错字段名时静默忽略。
        known = set(TrainSpec.__dataclass_fields__)  # type: ignore[attr-defined]
        unknown = [k for k in body if k not in known]
        if unknown:
            return JSONResponse(
                status_code=400, content={"error": f"未知参数: {', '.join(sorted(unknown))}"}
            )

        # 必填字段先自己查一遍：dataclass 构造器只会抛 TypeError（500），
        # 而"少填了 dataset_path"是调用方的错，应该是 400 + 人话。
        required = ("base_model", "dataset_path", "output_dir")
        missing = [f for f in required if not str(body.get(f) or "").strip()]
        if missing:
            return JSONResponse(
                status_code=400, content={"error": f"缺少必填参数: {', '.join(missing)}"}
            )

        try:
            spec = TrainSpec.from_dict(body)
            manager = get_manager()
            job = await asyncio.to_thread(manager.submit, spec)
        except Exception as exc:  # noqa: BLE001
            return _error_response(exc)
        return {"job": job.to_dict()}

    # ── 晋级 / 回滚 ───────────────────────────────────────────
    @app.post("/api/finetune/jobs/{job_id}/promote")
    async def finetune_promote(job_id: str, request: Request):
        """把某个成功作业的适配器晋级为槽位的生效版本。"""
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        slot = (body or {}).get("slot") or "student"
        try:
            manager = get_manager()
            result = await asyncio.to_thread(manager.promote, job_id, slot)
        except Exception as exc:  # noqa: BLE001
            return _error_response(exc)
        return result

    @app.post("/api/finetune/rollback")
    async def finetune_rollback(request: Request):
        """回滚槽位到上一个适配器。"""
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        slot = (body or {}).get("slot") or "student"
        try:
            manager = get_manager()
            result = await asyncio.to_thread(manager.rollback, slot)
        except Exception as exc:  # noqa: BLE001
            return _error_response(exc)
        return result

    @app.get("/api/finetune/adapters")
    async def finetune_adapters():
        """适配器清单：已成功产出的适配器 + 当前槽位归属。"""
        try:
            manager = get_manager()
            jobs = await asyncio.to_thread(manager.list_jobs, 200)
            adapters = [
                {
                    "job_id": j.id,
                    "adapter_path": j.adapter_path,
                    "base_model": j.spec.base_model,
                    "method": j.spec.method,
                    "created_at": j.finished_at or j.created_at,
                    "metrics": j.metrics,
                }
                for j in jobs
                if j.state.value == "succeeded" and j.adapter_path
            ]
            store = getattr(manager, "_store", None)
            slots = store.slots() if store is not None else []
            return {"adapters": adapters, "slots": slots}
        except Exception as exc:  # noqa: BLE001
            return _error_response(exc)

    @app.post("/api/finetune/adapters/{job_id}/activate")
    async def finetune_activate(job_id: str, request: Request):
        """把适配器设为生效版本（计划稿 §5 的 activate；等价于 promote）。"""
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        slot = (body or {}).get("slot") or "student"
        try:
            manager = get_manager()
            result = await asyncio.to_thread(manager.promote, job_id, slot)
        except Exception as exc:  # noqa: BLE001
            return _error_response(exc)
        return result

    @app.post("/api/finetune/adapters/{job_id}/rollback")
    async def finetune_adapter_rollback(job_id: str, request: Request):
        """回滚槽位到上一个适配器（计划稿 §5 的 rollback）。"""
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            body = {}
        slot = (body or {}).get("slot") or "student"
        try:
            manager = get_manager()
            result = await asyncio.to_thread(manager.rollback, slot)
        except Exception as exc:  # noqa: BLE001
            return _error_response(exc)
        return result

    @app.get("/api/finetune/slots")
    async def finetune_slots():
        """槽位登记：哪个适配器当前生效、上一个是谁。"""
        try:
            manager = get_manager()
            store = getattr(manager, "_store", None)
            slots = store.slots() if store is not None else []
            return {"slots": slots}
        except Exception as exc:  # noqa: BLE001
            return _error_response(exc)
