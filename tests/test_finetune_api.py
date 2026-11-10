# tests/test_finetune_api.py
"""微调工坊 HTTP 门面（apps/dsn_ui/finetune_api.py）的接口测试。

注意：按本地专用策略，本文件**不上 GitHub**（.git/local-only-policy.txt 里的
`tests/test_finetune_api*`）。它测的是 apps/ 层的东西，属于本地实验。

覆盖：
  * 环境体检 / 显存占用 / 作业列表 / 槽位表 的读接口；
  * 提交接口的参数拦截（未知字段、缺必填、GGUF 底座）；
  * 一次**真的**训练（2 步 QLoRA 冒烟）→ 查状态 → 看日志 → 晋级 → 回滚。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# 本机冒烟数据（由之前的实跑产出）。缺失时整条训练用例跳过。
SMOKE_DATASET = Path(os.environ.get("FINETUNE_SMOKE_DATASET", "~/dsn-finetune/smoke-data/train.jsonl")).expanduser()
SMOKE_BASE = Path(os.environ.get("FINETUNE_SMOKE_BASE", "~/qwen_weights/HF/Qwen3-4B")).expanduser()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """建一个只挂微调路由的最小 app。

    刻意**不**起完整的 DSNUIEngine：这里只测门面本身。
    """
    monkeypatch.setenv("FINETUNE_ROOT", str(tmp_path / "root"))
    monkeypatch.setenv("FINETUNE_DB", str(tmp_path / "jobs.db"))

    import apps.dsn_ui.finetune_api as api

    api._manager = None  # 每个用例一个干净的全局管理器
    app = FastAPI()
    api.register_finetune_routes(app)
    with TestClient(app) as c:
        yield c
    api._manager = None


def test_env_endpoint(client):
    resp = client.get("/api/finetune/env")
    assert resp.status_code == 200
    data = resp.json()
    assert "available" in data
    assert "python" in data
    assert isinstance(data.get("warnings", []), list)
    # 环境不可用时必须给出原因（前端要显示红条）
    if not data["available"]:
        assert data["reason"]


def test_devices_endpoint(client):
    resp = client.get("/api/finetune/devices")
    assert resp.status_code == 200
    data = resp.json()
    assert data["device_count"] >= 1
    assert isinstance(data["free"], list)


def test_jobs_list_empty(client):
    resp = client.get("/api/finetune/jobs")
    assert resp.status_code == 200
    assert resp.json()["jobs"] == []


def test_slots_endpoint(client):
    resp = client.get("/api/finetune/slots")
    assert resp.status_code == 200
    assert isinstance(resp.json()["slots"], list)


def test_submit_rejects_unknown_field(client):
    resp = client.post("/api/finetune/jobs", json={"base_model": "x", "nope": 1})
    assert resp.status_code == 400
    assert "未知参数" in resp.json()["error"]


def test_submit_rejects_missing_required(client):
    resp = client.post("/api/finetune/jobs", json={"base_model": "Qwen/Qwen3-4B"})
    assert resp.status_code == 400
    assert resp.json()["error"]


def test_submit_rejects_gguf_base(client):
    """GGUF 底座必须在提交前就被挡住（不能等训练跑起来才炸）。"""
    resp = client.post(
        "/api/finetune/jobs",
        json={
            "base_model": "/tmp/some-model.gguf",
            "dataset_path": str(SMOKE_DATASET),
            "output_dir": "/tmp/out",
        },
    )
    assert resp.status_code == 400
    assert "GGUF" in resp.json()["error"]


@pytest.mark.skipif(
    not (SMOKE_DATASET.is_file() and SMOKE_BASE.is_dir()),
    reason="本机没有冒烟数据集或 4B 权重，跳过真实训练用例",
)
def test_submit_train_promote_rollback(client, tmp_path):
    """端到端：提交 → 训练成功 → 查日志 → 晋级 → 回滚。"""
    out_dir = tmp_path / "out"
    resp = client.post(
        "/api/finetune/jobs",
        json={
            "base_model": str(SMOKE_BASE),
            "dataset_path": str(SMOKE_DATASET),
            "output_dir": str(out_dir),
            "method": "qlora",
            "max_steps": 2,
            "epochs": 1.0,
            "seq_len": 512,
        },
    )
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["job"]["id"]
    assert resp.json()["job"]["state"] in ("queued", "running")

    # 等训练结束（2 步冒烟，通常十几秒内）
    final = None
    for _ in range(600):
        detail = client.get(f"/api/finetune/jobs/{job_id}", params={"log_tail": 50}).json()
        final = detail["job"]
        if final["state"] in ("succeeded", "failed", "cancelled"):
            break
        import time

        time.sleep(0.5)

    assert final is not None
    assert final["state"] == "succeeded", final.get("error")
    assert final["adapter_path"]
    assert "elapsed_sec" in final["metrics"]

    # 日志尾部可读
    detail = client.get(f"/api/finetune/jobs/{job_id}", params={"log_tail": 50}).json()
    assert detail["log"]

    # 晋级 → 槽位表更新
    promo = client.post(f"/api/finetune/jobs/{job_id}/promote", json={"slot": "student"})
    assert promo.status_code == 200
    assert promo.json()["job_id"] == job_id
    slots = client.get("/api/finetune/slots").json()["slots"]
    assert any(s["slot"] == "student" and s["job_id"] == job_id for s in slots)

    # 回滚：没有上一个版本时 rolled_back=False，但必须给出原因
    rb = client.post("/api/finetune/rollback", json={"slot": "student"})
    assert rb.status_code == 200
    assert rb.json()["rolled_back"] is False


def test_job_not_found(client):
    resp = client.get("/api/finetune/jobs/does-not-exist")
    assert resp.status_code == 404
    assert "作业不存在" in resp.json()["error"]


def test_promote_unknown_job(client):
    resp = client.post("/api/finetune/jobs/nope/promote", json={"slot": "student"})
    assert resp.status_code == 400
    assert "作业不存在" in resp.json()["error"]
