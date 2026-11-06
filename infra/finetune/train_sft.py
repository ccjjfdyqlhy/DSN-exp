
# infra/finetune/train_sft.py
# **独立训练脚本**：在训练解释器（dsn-train 环境）里直接运行，不 import 仓库任何模块。
#
#   python infra/finetune/train_sft.py --spec /path/to/spec.json
#
# 为什么要独立成脚本而不是 infra.finetune.runner 的一个函数：
#   训练依赖 torch / transformers / peft / trl，
#   而 DSN 主进程**不允许 import torch**（见 infra/finetune/env.py 顶部的说明）。
#   把它做成零仓库依赖的独立脚本，训练解释器与 DSN 解释器之间只剩
#   「一个 JSON spec 进、一个 JSON 结果出」这一条缝。
#
# 结果文件（output_dir/result.json）：
#   {"status": "succeeded"|"failed", "adapter_path": "...", "metrics": {...}, "error": "..."}

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path


def _write_result(output_dir: str, payload: dict) -> None:
    try:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        with open(Path(output_dir) / "result.json", "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
    except OSError:
        pass


def _load_spec(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _build_dataset(tokenizer, records_path: str, seq_len: int):
    """把 JSONL 的 messages 套 chat template 后 tokenize。"""
    from torch.utils.data import Dataset

    class SFTDataset(Dataset):
        def __init__(self, path: str):
            self.samples: list[dict] = []
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    messages = rec.get("messages") or []
                    if not messages:
                        continue
                    # 训练期一律关掉 thinking：思考链会让序列长度爆炸，
                    # 而且教师思维链不应成为学生的模仿目标。
                    # Qwen3 的模板支持 enable_thinking 开关（实测含该关键字）。
                    try:
                        text = tokenizer.apply_chat_template(
                            messages, tokenize=False, add_generation_prompt=False,
                            enable_thinking=False,
                        )
                    except TypeError:
                        # 模板不支持该开关时退回默认渲染。
                        text = tokenizer.apply_chat_template(
                            messages, tokenize=False, add_generation_prompt=False,
                        )
                    enc = tokenizer(
                        text,
                        truncation=True,
                        max_length=seq_len,
                        padding=False,
                        return_tensors=None,
                    )
                    ids = enc["input_ids"]
                    if len(ids) < 8:
                        continue
                    self.samples.append({"input_ids": ids, "labels": list(ids)})

        def __len__(self) -> int:
            return len(self.samples)

        def __getitem__(self, idx: int) -> dict:
            return self.samples[idx]

    return SFTDataset(records_path)


def _collator(tokenizer, pad_id: int):
    def collate(features: list[dict]) -> dict:
        import torch

        max_len = max(len(f["input_ids"]) for f in features)
        input_ids, labels, attention = [], [], []
        for f in features:
            ids = list(f["input_ids"])
            lab = list(f["labels"])
            pad = max_len - len(ids)
            input_ids.append(ids + [pad_id] * pad)
            labels.append(lab + [-100] * pad)     # -100 = 不参与 loss
            attention.append([1] * len(ids) + [0] * pad)
        return {
            "input_ids": torch.tensor(input_ids, dtype=torch.long),
            "labels": torch.tensor(labels, dtype=torch.long),
            "attention_mask": torch.tensor(attention, dtype=torch.long),
        }

    return collate


def _load_model(spec: dict):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    base_model = spec["base_model"]
    dtype = getattr(torch, spec.get("dtype", "float16"))
    attn = spec.get("attn_implementation", "sdpa")

    tokenizer = AutoTokenizer.from_pretrained(base_model, trust_remote_code=False)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token

    quant_config = None
    if spec.get("method") == "qlora":
        quant_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=dtype,
        )

    # flash_attention_2 在 sm_75 上会直接抛 "No available kernel"，
    # 这里显式降级而不是让作业崩掉。
    if attn == "flash_attention_2":
        try:
            import transformers
            from transformers.utils import is_flash_attn_2_available
            if not is_flash_attn_2_available():
                print("[train_sft] flash_attention_2 不可用，降级为 sdpa", flush=True)
                attn = "sdpa"
        except Exception:
            attn = "sdpa"

    gpus = spec.get("gpus") or []
    device_map = None
    if gpus:
        device_map = {"": int(gpus[0])}

    model = AutoModelForCausalLM.from_pretrained(
        base_model,
        dtype=dtype,
        attn_implementation=attn,
        quantization_config=quant_config,
        device_map=device_map,
        trust_remote_code=False,
        low_cpu_mem_usage=True,
    )
    if not quant_config and device_map is None:
        model = model.to("cuda" if torch.cuda.is_available() else "cpu")
    return model, tokenizer


def train(spec: dict) -> dict:
    import torch
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import Trainer, TrainingArguments

    output_dir = spec["output_dir"]
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    model, tokenizer = _load_model(spec)
    method = spec.get("method", "qlora")

    if method in ("qlora", "lora"):
        if method == "qlora":
            model = prepare_model_for_kbit_training(
                model, use_gradient_checkpointing=spec.get("gradient_checkpointing", True)
            )
        lora_cfg = LoraConfig(
            r=int(spec.get("lora_rank", 16)),
            lora_alpha=int(spec.get("lora_alpha", 32)),
            lora_dropout=float(spec.get("lora_dropout", 0.05)),
            target_modules=list(spec.get("target_modules") or ["q_proj", "k_proj", "v_proj", "o_proj"]),
            bias="none",
            task_type="CAUSAL_LM",
        )
        model = get_peft_model(model, lora_cfg)
        model.print_trainable_parameters()

    train_path = (
        spec.get("train_path")
        or spec.get("dataset_path")
        or str(Path(output_dir) / "train.jsonl")
    )
    dataset = _build_dataset(tokenizer, train_path, int(spec.get("seq_len", 1024)))
    print(f"[train_sft] 训练样本数: {len(dataset)}", flush=True)
    if len(dataset) == 0:
        raise RuntimeError(f"训练集为空: {train_path}")

    args = TrainingArguments(
        output_dir=output_dir,
        num_train_epochs=float(spec.get("epochs", 2.0)),
        per_device_train_batch_size=int(spec.get("batch_size", 1)),
        gradient_accumulation_steps=int(spec.get("grad_accum", 16)),
        learning_rate=float(spec.get("lr", 2e-4)),
        logging_steps=1,
        save_strategy="no",
        report_to=[],
        bf16=False,                                   # sm_75 无原生 bf16
        fp16=True,
        gradient_checkpointing=bool(spec.get("gradient_checkpointing", True)),
        max_steps=int(spec.get("max_steps", -1)),
        seed=int(spec.get("seed", 42)),
        remove_unused_columns=False,
    )

    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=dataset,
        data_collator=_collator(tokenizer, tokenizer.pad_token_id),
    )
    started = time.time()
    result = trainer.train()
    elapsed = time.time() - started

    adapter_path = str(Path(output_dir) / "adapter")
    model.save_pretrained(adapter_path)
    tokenizer.save_pretrained(adapter_path)

    metrics = {
        "elapsed_sec": round(elapsed, 2),
        "train_samples": len(dataset),
        "train_loss": float(getattr(result, "training_loss", 0.0) or 0.0),
        "steps": int(spec.get("max_steps", -1)) if spec.get("max_steps", -1) > 0 else -1,
    }
    if torch.cuda.is_available():
        metrics["gpu_max_memory_mib"] = round(torch.cuda.max_memory_allocated() / (1024 * 1024))
    return {"adapter_path": adapter_path, "metrics": metrics}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DSN SFT 训练脚本（独立运行于训练解释器）")
    parser.add_argument("--spec", required=True, help="训练参数 JSON 路径")
    args = parser.parse_args(argv)

    spec = _load_spec(args.spec)
    output_dir = spec.get("output_dir", "./finetune-out")
    try:
        payload = train(spec)
        result = {
            "status": "succeeded",
            "adapter_path": payload["adapter_path"],
            "metrics": payload["metrics"],
            "error": "",
        }
        _write_result(output_dir, result)
        print("[train_sft] 训练完成: " + json.dumps(result, ensure_ascii=False), flush=True)
        return 0
    except Exception as exc:  # noqa: BLE001
        result = {
            "status": "failed",
            "adapter_path": "",
            "metrics": {},
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc()[-4000:],
        }
        _write_result(output_dir, result)
        print("[train_sft] 训练失败: " + result["error"], file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
