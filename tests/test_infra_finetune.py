
# tests/test_infra_finetune.py
# infra/finetune 训练子系统（框架层）单元测试。
#
# 覆盖：
#   1. 契约：TrainSpec 的自检、序列化往返
#   2. GGUF 元数据：私有量化类型的容错读取（对应 Bonsai-2 的 PQ2_0）
#   3. 数据集：角色归一、工具轨迹校验、train/val 切分
#   4. 环境：解释器定位、体检失败时的降级（不抛异常）
#   5. 显存闸门：独占、冲突、超时
#   6. 作业存储：晋级 / 回滚闭环
#   7. 作业管理：提交 → 失败 → 状态可见
#   8. 不变式：主进程绝不 import torch

from __future__ import annotations

import json
import logging
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from infra.finetune.base import JobState, SpecError, TrainJob, TrainSpec
from infra.finetune.dataset import (
    build_sft_dataset,
    load_jsonl,
    normalize_messages,
    validate_messages,
    write_jsonl,
)
from infra.finetune.env import environment, resolve_python
from infra.finetune.gguf import GGUFError, read_meta
from infra.finetune.runner import FinetuneManager
from infra.finetune.store import FinetuneStore
from infra.orchestrator.scheduler import DeviceBusy, DeviceGate, ModelProfile, ModelScheduler


# ════════════════════════════════════════════════════════════════════════════
# 1. 契约：TrainSpec
# ════════════════════════════════════════════════════════════════════════════

def _spec(**kw) -> TrainSpec:
    base = dict(
        base_model="Qwen/Qwen3-4B",
        dataset_path="/tmp/dsn-test/train.jsonl",
        output_dir="/tmp/dsn-test/out",
    )
    base.update(kw)
    return TrainSpec(**base)


def test_spec_defaults_are_qwen3_8b_friendly():
    """默认参数必须适配本机（单卡 11GB、sm_75）。"""
    spec = _spec()
    spec.validate()
    assert spec.method == "qlora"
    assert spec.attn_implementation == "sdpa"        # sm_75 上 FA2 不可用
    assert spec.dtype == "float16"                  # sm_75 无原生 bf16
    assert spec.enable_thinking is False            # 训练期禁止 thinking
    assert spec.max_steps == -1


def test_spec_rejects_enable_thinking():
    """训练期开 thinking 是纪律问题，必须在提交前就拦住。"""
    with pytest.raises(SpecError):
        _spec(enable_thinking=True).validate()


def test_spec_rejects_invalid_values():
    with pytest.raises(SpecError):
        _spec(base_model="").validate()
    with pytest.raises(SpecError):
        _spec(method="magic").validate()
    with pytest.raises(SpecError):
        _spec(seq_len=0).validate()
    with pytest.raises(SpecError):
        _spec(batch_size=0).validate()


def test_spec_full_finetune_clears_lora_rank():
    """full 微调时 lora_rank 必须归零，避免"看起来在做 LoRA"。"""
    spec = _spec(method="full")
    spec.validate()
    assert spec.lora_rank == 0


def test_spec_dict_roundtrip():
    spec = _spec(gpus=(0,), target_modules=("q_proj",))
    data = spec.to_dict()
    assert isinstance(data["gpus"], list)
    restored = TrainSpec.from_dict(data)
    assert restored.gpus == (0,)
    assert restored.target_modules == ("q_proj",)
    assert restored.base_model == spec.base_model


def test_spec_from_dict_ignores_unknown_keys():
    """向前兼容：旧调用方带着多余字段也不该炸。"""
    data = _spec().to_dict()
    data["future_field"] = "x"
    assert TrainSpec.from_dict(data).base_model == "Qwen/Qwen3-4B"


# ════════════════════════════════════════════════════════════════════════════
# 2. GGUF 元数据（容错私有量化类型）
# ════════════════════════════════════════════════════════════════════════════

def _gguf_string(text: str) -> bytes:
    raw = text.encode("utf-8")
    return struct.pack("<Q", len(raw)) + raw


def _gguf_value(value) -> bytes:
    """按 GGUF v3 的 value 类型编码一个值。"""
    if isinstance(value, bool):
        return struct.pack("<I", 7) + struct.pack("<B", 1 if value else 0)
    if isinstance(value, int):
        return struct.pack("<I", 4) + struct.pack("<I", value)     # UINT32
    if isinstance(value, float):
        return struct.pack("<I", 6) + struct.pack("<f", value)     # FLOAT32
    if isinstance(value, str):
        return struct.pack("<I", 8) + _gguf_string(value)
    if isinstance(value, list):
        out = struct.pack("<I", 9) + struct.pack("<I", 8)          # ARRAY + STRING
        out += struct.pack("<Q", len(value))
        for item in value:
            out += _gguf_string(item)
        return out
    raise TypeError(type(value))


def _gguf_bytes(kv: dict, tensors: list[tuple[str, int]]) -> bytes:
    out = b"GGUF" + struct.pack("<I", 3)
    out += struct.pack("<Q", len(tensors))
    out += struct.pack("<Q", len(kv))
    for key, value in kv.items():
        out += _gguf_string(key) + _gguf_value(value)
    for name, type_id in tensors:
        out += _gguf_string(name)
        out += struct.pack("<I", 1) + struct.pack("<Q", 16)
        out += struct.pack("<I", type_id) + struct.pack("<Q", 0)
    return out


def test_gguf_reads_private_quant_type_without_raising(tmp_path: Path):
    """Bonsai-2 的 PQ2_0（type id 142）必须被容错读取，而不是抛异常。"""
    path = tmp_path / "bonsai.gguf"
    path.write_bytes(_gguf_bytes(
        {
            "general.architecture": "qwen35",
            "general.name": "Ternary-Bonsai-2-27B-PQ2_0",
            "general.file_type": 141,
        },
        [("token_embd.weight", 142), ("blk.0.attn_q.weight", 142)],
    ))
    meta = read_meta(path)
    assert meta.architecture == "qwen35"
    assert meta.file_type == 141
    assert meta.tensor_count == 2
    assert meta.unknown_type_ids == {142}
    compatible, reasons = meta.upstream_compatible()
    assert compatible is False
    assert reasons and "142" in reasons[0]


def test_gguf_reads_standard_quant_type(tmp_path: Path):
    """标准量化（Q4_K=12）应判为上游兼容。"""
    path = tmp_path / "jev.gguf"
    path.write_bytes(_gguf_bytes(
        {"general.architecture": "qwen35", "general.file_type": 15},
        [("token_embd.weight", 12)],
    ))
    meta = read_meta(path)
    assert meta.unknown_type_ids == set()
    assert meta.upstream_compatible()[0] is True


def test_gguf_array_order_is_correct(tmp_path: Path):
    """数组的"先类型后数量"顺序读反就会把 KV 解析成乱码。"""
    path = tmp_path / "tags.gguf"
    path.write_bytes(_gguf_bytes(
        {"general.tags": ["jev", "system-one", "system-two"], "general.architecture": "qwen35"},
        [],
    ))
    meta = read_meta(path)
    assert meta.kv["general.tags"] == ["jev", "system-one", "system-two"]
    assert meta.kv["general.architecture"] == "qwen35"


def test_gguf_rejects_non_gguf(tmp_path: Path):
    path = tmp_path / "bad.gguf"
    path.write_bytes(b"NOPE" + b"\x00" * 32)
    with pytest.raises(GGUFError):
        read_meta(path)


def test_gguf_missing_file():
    with pytest.raises(GGUFError):
        read_meta("/tmp/dsn-not-exists-xyz.gguf")


# ════════════════════════════════════════════════════════════════════════════
# 3. 数据集
# ════════════════════════════════════════════════════════════════════════════

def test_normalize_messages_keeps_tool_calls():
    msgs = normalize_messages([
        {"role": "user", "content": "查一下天气"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "1", "function": {"name": "w"}}]},
        {"role": "tool", "content": "晴", "tool_call_id": "1"},
        {"role": "assistant", "content": "今天晴。"},
    ])
    assert [m["role"] for m in msgs] == ["user", "assistant", "tool", "assistant"]
    assert msgs[1]["tool_calls"][0]["id"] == "1"
    assert msgs[2]["tool_call_id"] == "1"


def test_normalize_messages_drops_invalid_roles():
    msgs = normalize_messages([{"role": "system", "content": "s"}, {"role": "bogus", "content": "x"}])
    assert [m["role"] for m in msgs] == ["system"]


def test_validate_messages_flags_orphan_tool_message():
    """tool 消息必须跟在 assistant(tool_calls) 之后（仓库不变式）。"""
    problems = validate_messages([
        {"role": "user", "content": "hi"},
        {"role": "tool", "content": "x"},
        {"role": "assistant", "content": "y"},
    ])
    assert problems
    assert "tool" in problems[0]


def test_validate_messages_requires_user_and_assistant():
    problems = validate_messages([{"role": "user", "content": "hi"}])
    assert any("assistant" in p for p in problems)


def test_build_sft_dataset_splits_and_reports(tmp_path: Path):
    records = [
        {"messages": [
            {"role": "user", "content": f"问题{i}"},
            {"role": "assistant", "content": f"回答{i}"},
        ]}
        for i in range(20)
    ]
    # 一条超长样本应被丢弃
    records.append({"messages": [
        {"role": "user", "content": "x" * 20000},
        {"role": "assistant", "content": "y"},
    ]})
    stats, train_path, val_path = build_sft_dataset(records, tmp_path, val_ratio=0.1, max_tokens=128)
    assert stats.total == 21
    assert stats.kept == 20
    assert stats.dropped == 1
    assert any("长度" in r for r in stats.reasons)
    assert len(load_jsonl(train_path)) + len(load_jsonl(val_path)) == 20
    assert len(load_jsonl(val_path)) == 2
    assert val_path.exists() and train_path.exists()


def test_write_and_load_jsonl_skips_broken_lines(tmp_path: Path):
    path = tmp_path / "x.jsonl"
    path.write_text('{"a": 1}\n\nnot-json\n{"b": 2}\n', encoding="utf-8")
    assert load_jsonl(path) == [{"a": 1}, {"b": 2}]


def test_write_jsonl_roundtrip(tmp_path: Path):
    path = tmp_path / "y.jsonl"
    assert write_jsonl(path, [{"k": "值"}]) == 1
    assert json.loads(path.read_text(encoding="utf-8").strip())["k"] == "值"


# ════════════════════════════════════════════════════════════════════════════
# 4. 环境体检
# ════════════════════════════════════════════════════════════════════════════

def test_resolve_python_prefers_explicit(monkeypatch):
    monkeypatch.setenv("FINETUNE_PYTHON", "/tmp/from-env/python")
    assert resolve_python("/tmp/explicit/python") == "/tmp/explicit/python"


def test_resolve_python_uses_env(monkeypatch):
    monkeypatch.setenv("FINETUNE_PYTHON", "/tmp/from-env/python")
    assert resolve_python() == "/tmp/from-env/python"


def test_environment_reports_missing_interpreter_without_raising():
    """体检失败必须降级成报告，不能让 DSN 主进程崩。"""
    report = environment("/tmp/dsn-definitely-missing/python")
    assert report["available"] is False
    assert "不存在" in report["reason"]


def test_environment_has_expected_keys(monkeypatch):
    report = environment(sys.executable, timeout=60)
    assert set(["available", "reason", "python", "torch", "packages"]).issubset(report.keys())
    assert report["python"] == sys.executable


# ════════════════════════════════════════════════════════════════════════════
# 5. 显存闸门
# ════════════════════════════════════════════════════════════════════════════

def test_device_gate_claim_and_release():
    gate = DeviceGate(device_count=2)
    lease = gate.claim((0,), "model-a", reason="loaded")
    assert gate.free_devices() == [1]
    assert gate.occupancy()["0"]["holder"] == "model-a"
    gate.release(lease)
    assert gate.free_devices() == [0, 1]


def test_device_gate_conflict_raises():
    gate = DeviceGate(device_count=2)
    gate.claim((0,), "model-a")
    with pytest.raises(DeviceBusy):
        gate.claim((0,), "model-b")


def test_device_gate_acquire_waits_then_times_out():
    gate = DeviceGate(device_count=1)
    gate.claim((0,), "model-a")
    with pytest.raises(DeviceBusy):
        gate.acquire((0,), "train-1", timeout=0.2)


def test_device_gate_acquire_any_waits_for_any_device():
    gate = DeviceGate(device_count=2)
    gate.claim((0,), "model-a")
    lease = gate.acquire_any("train-1", timeout=1.0)
    assert lease.device_ids == (1,)


def test_device_gate_release_holder():
    gate = DeviceGate(device_count=2)
    gate.claim((0,), "model-a")
    gate.claim((1,), "model-a")
    gate.release_holder("model-a")
    assert gate.free_devices() == [0, 1]


def test_scheduler_device_claim_for_full_offload():
    """-ngl 99（全量分层）必须被判定为独占双卡。"""
    sched = ModelScheduler()
    profile = ModelProfile(engine="llama_cpp", llama_config={"n_gpu_layers": -1})
    assert sched._devices_for_profile(profile) == (0, 1)


def test_scheduler_partial_offload_does_not_claim():
    sched = ModelScheduler()
    profile = ModelProfile(engine="llama_cpp", llama_config={"n_gpu_layers": 17})
    assert sched._devices_for_profile(profile) == ()


def test_scheduler_explicit_devices():
    sched = ModelScheduler()
    profile = ModelProfile(engine="llama_cpp", llama_config={"devices": [1]})
    assert sched._devices_for_profile(profile) == (1,)


# ════════════════════════════════════════════════════════════════════════════
# 6. 作业存储：晋级 / 回滚
# ════════════════════════════════════════════════════════════════════════════

def _job(job_id: str, state=JobState.SUCCEEDED) -> TrainJob:
    return TrainJob(id=job_id, spec=_spec(), state=state, adapter_path=f"/tmp/{job_id}")


def test_store_promote_and_rollback():
    store = FinetuneStore()
    store.save_job(_job("j1"))
    store.save_job(_job("j2"))
    first = store.promote("slot", "j1")
    assert first["previous_job_id"] == ""
    second = store.promote("slot", "j2")
    assert second["previous_job_id"] == "j1"
    assert store.active("slot") == "j2"
    back = store.rollback("slot")
    assert back["rolled_back"] is True
    assert store.active("slot") == "j1"


def test_store_rollback_without_previous():
    store = FinetuneStore()
    store.save_job(_job("j1"))
    store.promote("slot", "j1")
    assert store.rollback("slot")["rolled_back"] is False


def test_store_list_and_get():
    store = FinetuneStore()
    store.save_job(_job("j1"))
    store.save_job(_job("j2"))
    assert [j.id for j in store.list_jobs()] == ["j2", "j1"] or {j.id for j in store.list_jobs()} == {"j1", "j2"}
    assert store.get_job("j1").state == JobState.SUCCEEDED
    assert store.get_job("nope") is None


# ════════════════════════════════════════════════════════════════════════════
# 7. 作业管理
# ════════════════════════════════════════════════════════════════════════════

def test_manager_submit_failure_is_visible(tmp_path: Path, caplog):
    """训练解释器不存在时，作业必须落到 FAILED 并带原因，而不是静默挂住。"""
    # 这个用例会故意触发一次任务失败；把任务层的日志压掉，免得污染测试输出。
    caplog.set_level(logging.CRITICAL, logger="infra.tasks")
    manager = FinetuneManager(
        store=FinetuneStore(),
        python="/tmp/dsn-definitely-missing/python",
        root=tmp_path,
        device_timeout=1.0,
    )
    spec = _spec(dataset_path=str(tmp_path / "train.jsonl"), output_dir=str(tmp_path / "out"))
    job = manager.submit(spec)
    assert job.id
    done = manager.wait(job.id, timeout=60)
    assert done is not None and done.state == JobState.FAILED
    assert "环境" in done.error or "解释器" in done.error
    manager.shutdown()


def test_manager_rejects_invalid_spec(tmp_path: Path):
    manager = FinetuneManager(store=FinetuneStore(), root=tmp_path)
    with pytest.raises(SpecError):
        manager.submit(_spec(enable_thinking=True))
    manager.shutdown()


def test_spec_rejects_gguf_base_model(tmp_path: Path):
    """GGUF 起点必须被拒绝——Bonsai-2 / JEV-27B-VL 本机只有 GGUF。"""
    spec = _spec(output_dir=str(tmp_path / "out"))
    spec.base_model = "/home/darkstar/Bonsai-demo/models/bonsai2-gguf/27B/Ternary-Bonsai-2-27B-PQ2_0.gguf"
    with pytest.raises(SpecError, match="GGUF"):
        spec.validate()


def test_manager_rejects_unsupported_architecture(tmp_path: Path, monkeypatch):
    """架构不被 transformers 支持时，**提交阶段**就要拒绝（不浪费 GPU 作业）。"""
    def _fake_support(model_id, python=None):
        return {
            "supported": False,
            "kind": "arch",
            "reason": "FooBar is not a supported model type",
            "model_type": "foo_bar",
        }

    monkeypatch.setattr("infra.finetune.runner.check_model_support", _fake_support)
    manager = FinetuneManager(
        store=FinetuneStore(),
        python="/tmp/dsn-definitely-missing/python",
        root=tmp_path,
    )
    with pytest.raises(SpecError, match="foo_bar"):
        manager.submit(_spec(output_dir=str(tmp_path / "out")))
    manager.shutdown()


def test_manager_allows_qwen35_base_but_warns(tmp_path: Path, monkeypatch, caplog):
    """qwen3_5 底座：架构可训（transformers 5.x 有该模块）→ 允许提交，但要提醒。

    训底座产不出 Bonsai / JEV 的能力，所以只警告不拦截。
    """
    def _fake_support(model_id, python=None):
        return {"supported": True, "kind": "ok", "model_type": "qwen3_5"}

    monkeypatch.setattr("infra.finetune.runner.check_model_support", _fake_support)
    manager = FinetuneManager(
        store=FinetuneStore(),
        python="/tmp/dsn-definitely-missing/python",
        root=tmp_path,
    )
    with caplog.at_level(logging.WARNING, logger="infra.finetune.runner"):
        manager.submit(_spec(output_dir=str(tmp_path / "out")))
    assert any("qwen3_5" in rec.getMessage() for rec in caplog.records)
    manager.shutdown()


def test_manager_skips_arch_gate_when_env_is_broken(tmp_path: Path, monkeypatch):
    """环境问题（解释器缺失/网络不通）不能被误判成"架构不可训"。"""
    def _fake_support(model_id, python=None):
        return {"supported": False, "kind": "env", "reason": "训练解释器不存在"}

    monkeypatch.setattr("infra.finetune.runner.check_model_support", _fake_support)
    manager = FinetuneManager(
        store=FinetuneStore(),
        python="/tmp/dsn-definitely-missing/python",
        root=tmp_path,
    )
    job = manager.submit(_spec(output_dir=str(tmp_path / "out")))  # 不应抛异常
    assert job.id
    manager.shutdown()


def test_manager_promote_requires_success(tmp_path: Path, caplog):
    caplog.set_level(logging.CRITICAL, logger="infra.tasks")
    # 用不存在的解释器，让作业立刻失败——**不要真的拉起训练进程**。
    manager = FinetuneManager(
        store=FinetuneStore(),
        python="/tmp/dsn-definitely-missing/python",
        root=tmp_path,
        device_timeout=1.0,
    )
    failed = manager.submit(_spec(output_dir=str(tmp_path / "out")))
    manager.wait(failed.id, timeout=60)
    with pytest.raises(ValueError):
        manager.promote(failed.id, "slot")
    manager.shutdown()


# ════════════════════════════════════════════════════════════════════════════
# 8. 不变式：DSN 主进程绝不 import torch
# ════════════════════════════════════════════════════════════════════════════

def test_importing_finetune_does_not_import_torch():
    """训练依赖必须留在子进程里；主进程 import 一次都不能碰 torch。"""
    code = (
        "import sys;"
        "sys.path.insert(0, %r);"
        "import infra.finetune;"
        "import infra.finetune.runner;"
        "assert 'torch' not in sys.modules, sorted(m for m in sys.modules if 'torch' in m)"
        % str(Path(__file__).resolve().parents[1])
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
