
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


class _RewardWeightedTrainer:
    """占位：真正的类在下面按 transformers 版本动态构造。

    见 `_make_reward_weighted_trainer()`。
    """


def _make_reward_weighted_trainer():
    """构造一个「按 reward 给样本 loss 加权」的 Trainer。

    为什么需要它：光有晋级门槛是**整批准入**（过/不过），
    情绪分 0.9 和 0.3 的样本进了训练集**权重一样** —— 那"奖励"就只是句空话。
    加权之后，「好样本学得多」才真的成立。

    实现要点：
      * 逐样本算 loss（先对 token 求均值），再按 reward 加权求和 / 加权总和；
      * reward 全为 0 时退化为不加权（否则除零）；
      * **不走 Trainer 的默认 compute_loss**：它把 labels 交给模型内部算 loss，
        我们要逐样本算，所以自己接 logits 与 labels；
      * `num_items_in_batch` 之类的版本相关参数用 **kwargs 吸收 ——
        忽略它只影响 loss 的绝对尺度（梯度累积下的归一化），
        不影响**样本之间的相对权重**，而后者才是这里要的东西。

    只在数据集里**真的存在非中性 reward** 时才启用（见 `train()`），
    否则走原生 Trainer，保证旧行为一字不变。
    """
    from transformers import Trainer
    import torch
    import torch.nn.functional as F

    class RewardWeightedTrainer(Trainer):
        """按 reward 加权逐样本 loss。"""

        def compute_loss(self, model, inputs, return_outputs=False, **kwargs):
            rewards = inputs.pop("reward", None)
            if rewards is None:
                return super().compute_loss(
                    model, inputs, return_outputs=return_outputs, **kwargs
                )
            labels = inputs.pop("labels", None)
            if labels is None:
                return super().compute_loss(
                    model, inputs, return_outputs=return_outputs, **kwargs
                )

            outputs = model(**inputs)
            logits = outputs.logits
            # 与因果语言模型的标准 loss 对齐：右移一位，-100 的位置不算。
            shift_logits = logits[:, :-1, :].contiguous().float()
            shift_labels = labels[:, 1:].contiguous()
            token_loss = F.cross_entropy(
                shift_logits.view(-1, shift_logits.size(-1)),
                shift_labels.view(-1),
                reduction="none",
            ).view(shift_labels.shape)
            mask = (shift_labels != -100).float()
            per_sample = (token_loss * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1.0)

            weights = rewards.to(per_sample.dtype).clamp(min=0.0)
            if float(weights.sum()) <= 1e-6:
                # 全是 0 权重 → 退化为不加权（而不是除零）
                weights = torch.ones_like(weights)
            loss = (per_sample * weights).sum() / weights.sum()
            return (loss, outputs) if return_outputs else loss

    return RewardWeightedTrainer


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
                    # reward：行为级奖励信号（0~1，缺省 1.0 = 中性）。
                    # 训练时按它给样本的 loss 加权：「好样本学得多」。
                    try:
                        reward = float(rec.get("reward", rec.get("weight", 1.0)))
                    except (TypeError, ValueError):
                        reward = 1.0
                    self.samples.append({
                        "input_ids": ids,
                        "labels": list(ids),
                        "reward": max(0.0, min(1.0, reward)),
                    })

        def __len__(self) -> int:
            return len(self.samples)

        def __getitem__(self, idx: int) -> dict:
            return self.samples[idx]

    return SFTDataset(records_path)


def _collator(tokenizer, pad_id: int):
    def collate(features: list[dict]) -> dict:
        import torch

        max_len = max(len(f["input_ids"]) for f in features)
        input_ids, labels, attention, rewards = [], [], [], []
        for f in features:
            ids = list(f["input_ids"])
            lab = list(f["labels"])
            pad = max_len - len(ids)
            input_ids.append(ids + [pad_id] * pad)
            labels.append(lab + [-100] * pad)     # -100 = 不参与 loss
            attention.append([1] * len(ids) + [0] * pad)
            rewards.append(float(f.get("reward", 1.0)))
        return {
            "input_ids": torch.tensor(input_ids, dtype=torch.long),
            "labels": torch.tensor(labels, dtype=torch.long),
            "attention_mask": torch.tensor(attention, dtype=torch.long),
            # reward 随 batch 走，在 compute_loss 里被 pop 掉（不进 model.forward）
            "reward": torch.tensor(rewards, dtype=torch.float32),
        }

    return collate


def _prepare_for_qlora(model, *, use_gradient_checkpointing: bool = True):
    """轻量版 ``prepare_model_for_kbit_training``。

    为什么不能直接用 peft 的官方实现：它会把**所有** fp16 参数升成 fp32，
    包括 ``embed_tokens`` 和 ``lm_head``。Qwen3-8B 的词表 151936 × 隐层 4096，
    这两张表各 1.24GB(fp16)，一起升 fp32 就是**一次多花 2.32GB**——
    实测 11GB 的 2080Ti 上就是这一步把 QLoRA 顶到 OOM
    （加载后 5.67GB → 准备完 7.99GB，再加激活与 logits 就爆）。

    这里只把 **1 维参数**（LayerNorm 的 weight / bias）升成 fp32：
    它们数量少、对数值敏感，值得这份显存；embedding 与 lm_head 保持 fp16。

    其余行为与官方实现一致：冻结底座、开启梯度检查点、放开输入侧梯度
    （冻结的 embedding + 梯度检查点必须有，否则反向传播拿不到梯度）。

    实测（Qwen3-8B / 4bit nf4 / seq_len 512 / batch 1）：
        官方实现 → OOM（要 2.32GiB 连续块，只剩 72MiB）
        本实现   → 峰值 5.73GB ✅
    """
    import torch

    for param in model.parameters():
        param.requires_grad = False
    for param in model.parameters():
        if param.ndim == 1 and param.dtype in (torch.float16, torch.bfloat16):
            param.data = param.data.to(torch.float32)

    if use_gradient_checkpointing:
        kwargs = {}
        if hasattr(model, "gradient_checkpointing_enable"):
            model.gradient_checkpointing_enable(
                gradient_checkpointing_kwargs={"use_reentrant": False}
            )
        if hasattr(model, "enable_input_require_grads"):
            model.enable_input_require_grads()
    return model


def _apply_cuda_visible_devices(spec: dict) -> list[int]:
    """把请求的物理卡映射成进程内的 0..n-1（CUDA_VISIBLE_DEVICES）。

    为什么不能只靠 device_map={"": g}：那只决定**模型权重**放哪，
    而 HF Trainer 仍按 args.device（默认 cuda:0）放优化器状态与激活。
    实测过这种错位：模型在物理 GPU 1、训练状态却在物理 GPU 0，
    而编排器的 DeviceGate 记的是"占了 GPU 1"——闸门与实际用卡对不上，
    两个作业可能同时挤到同一张卡上。

    返回请求的卡号列表。
    """
    gpus = [int(g) for g in (spec.get("gpus") or [])]
    if gpus:
        os.environ["CUDA_VISIBLE_DEVICES"] = ",".join(str(g) for g in gpus)
    return gpus


def _load_model(spec: dict):
    gpus = _apply_cuda_visible_devices(spec)

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    device_map = "auto" if len(gpus) > 1 else ({"": 0} if gpus else None)
    print(
        f"[train_sft] CUDA_VISIBLE_DEVICES={os.environ.get('CUDA_VISIBLE_DEVICES', '(未设置)')} "
        f"可见卡数={torch.cuda.device_count()} device_map={device_map}",
        flush=True,
    )

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

    device_map = None

    model = AutoModelForCausalLM.from_pretrained(
        base_model,
        dtype=dtype,
        attn_implementation=attn,
        quantization_config=quant_config,
        device_map=device_map,
        trust_remote_code=False,
        low_cpu_mem_usage=True,
    )
    # 训练期必须关掉 KV cache。
    #
    # 原因不是省显存本身，而是：transformers 看到 use_cache=True 会**拒绝启用
    # 梯度检查点**（它只在推理时需要缓存）。于是 36 层的激活被全量留在显存里——
    # 实测 8B QLoRA 在 seq_len=512 时就是因此多吃了约 4GB，
    # 在 11GB 卡上直接 OOM（Tried to allocate 298 MiB / 只剩 72 MiB）。
    # 关掉之后激活只留每层边界，显存回落到几 GB。
    model.config.use_cache = False
    if hasattr(model, "generation_config") and model.generation_config is not None:
        model.generation_config.use_cache = False
    if not quant_config and device_map is None:
        model = model.to("cuda" if torch.cuda.is_available() else "cpu")
    return model, tokenizer


def train(spec: dict) -> dict:
    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import Trainer, TrainingArguments

    output_dir = spec["output_dir"]
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    model, tokenizer = _load_model(spec)
    method = spec.get("method", "qlora")

    if method in ("qlora", "lora"):
        if method == "qlora":
            model = _prepare_for_qlora(
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

    # 只有数据集里**真的存在非中性 reward** 时才换成加权 Trainer，
    # 否则走原生 Trainer —— 保证旧数据集（无 reward）的训练行为一字不变。
    rewards = [float(s.get("reward", 1.0)) for s in getattr(dataset, "samples", [])]
    has_rewards = any(abs(r - 1.0) > 1e-6 for r in rewards)
    trainer_cls = _make_reward_weighted_trainer() if has_rewards else Trainer
    if has_rewards:
        print(
            f"[train_sft] 启用 reward 加权：{len(rewards)} 条样本，"
            f"reward 均值 {sum(rewards) / max(len(rewards), 1):.3f} "
            f"min {min(rewards):.3f} max {max(rewards):.3f}",
            flush=True,
        )

    trainer = trainer_cls(
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

    # 实际步数从 trainer.state 取——spec 里的 max_steps 只是"上限"，
    # 按 epochs 跑完时它通常是 -1，拿它当步数只会得到一个恒定的 -1。
    global_step = int(getattr(getattr(trainer, "state", None), "global_step", 0) or 0)
    metrics = {
        "elapsed_sec": round(elapsed, 2),
        "train_samples": len(dataset),
        "reward_weighted": bool(has_rewards),
        "reward_mean": round(sum(rewards) / len(rewards), 4) if rewards else 1.0,
        "reward_min": round(min(rewards), 4) if rewards else 1.0,
        "reward_max": round(max(rewards), 4) if rewards else 1.0,
        "train_loss": float(getattr(result, "training_loss", 0.0) or 0.0),
        "steps": global_step,
        "epochs": round(float(getattr(getattr(trainer, "state", None), "epoch", 0.0) or 0.0), 3),
        "learning_rate": float(getattr(trainer, "args", None).learning_rate or 0.0) if getattr(trainer, "args", None) else 0.0,
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

    # 必须在**任何** torch / transformers 导入之前设置：
    # transformers 的导入会触发 torch.cuda.is_available()，
    # 那一次调用就把 CUDA 运行时初始化了（设备列表就此固定），
    # 此后再改 os.environ 就没用了——实测就是这样：
    #   设了 CUDA_VISIBLE_DEVICES=1，但 torch 仍能看到 2 张卡。
    _apply_cuda_visible_devices(spec)
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
