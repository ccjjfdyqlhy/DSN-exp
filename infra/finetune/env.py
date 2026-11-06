
# infra/finetune/env.py
# 训练解释器定位与环境体检。
#
# 铁律：**DSN 主进程不 import torch**（仓库现状：apps/ infra/ harness/ 里零 import torch，
# 只有 apps/dsn/models/asr_engine.py:92 用 sys.modules.get("torch") 做防御性检查）。
# 因此体检一律通过**子进程**跑独立探针脚本完成，主进程只拿到 JSON。
#
# 解释器选择顺序（第一个可用的胜出）：
#   1. 显式参数 python=
#   2. 环境变量 FINETUNE_PYTHON
#   3. ~/anaconda3/envs/dsn-train/bin/python   ← 训练专用环境（计划二 §6.1）
#   4. 当前解释器 sys.executable                ← 只作为诊断用，不推荐当真训练
#
# 注意第 4 条：base 环境里确实装着 torch 2.8.0.dev+cu128（实测），
# 但它是 nightly + cu128，不能当训练栈的版本锚。

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Optional

from .base import EnvironmentUnavailable

logger = logging.getLogger("infra.finetune.env")

#: 训练专用环境的默认解释器位置。
DEFAULT_TRAIN_PYTHON = "~/anaconda3/envs/dsn-train/bin/python"

#: 探针脚本与本文件同目录（独立脚本，不 import 仓库模块）。
PROBE_SCRIPT = Path(__file__).with_name("probe.py")

#: 体检建议的关键依赖。缺任何一个都会让训练直接失败，提前拦住。
REQUIRED_PACKAGES = ("transformers", "peft", "accelerate")


def resolve_python(explicit: Optional[str] = None) -> str:
    """定位训练解释器路径（不做存在性检查）。"""
    if explicit:
        return str(Path(explicit).expanduser())
    env = os.environ.get("FINETUNE_PYTHON")
    if env:
        return str(Path(env).expanduser())
    default = Path(DEFAULT_TRAIN_PYTHON).expanduser()
    if default.exists():
        return str(default)
    import sys
    return sys.executable


def subprocess_env() -> dict[str, str]:
    """训练子进程的环境变量。

    HF_ENDPOINT 默认指向 hf-mirror：本机 huggingface.co 的 DNS 被污染
    （解析到一个 Facebook AS，直连 https 返回 000，实测）。
    """
    env = dict(os.environ)
    env.setdefault(
        "HF_ENDPOINT", os.environ.get("FINETUNE_HF_ENDPOINT", "https://hf-mirror.com")
    )
    env.setdefault(
        "HF_HOME",
        os.environ.get("FINETUNE_HF_HOME", str(Path("~/.cache/huggingface").expanduser())),
    )
    env.setdefault("TOKENIZERS_PARALLELISM", "false")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def environment(python: Optional[str] = None, *, timeout: float = 120.0) -> dict[str, Any]:
    """体检训练环境。**永不抛异常**——DSN 主进程必须能正常启动。

    返回结构::

        {
          "available": bool,          # 能不能拿来训练
          "reason": str,              # 不可用时的原因
          "python": str,              # 实际使用的解释器
          "torch": {...},             # torch / cuda / 设备 / bf16 / arch_list
          "packages": {...},          # transformers / peft / trl / ... 的版本
          "sdpa": {...},              # FA2 / mem_efficient / math 的真探针结果
          "warnings": [...],
        }
    """
    py = resolve_python(python)
    result: dict[str, Any] = {
        "available": False,
        "reason": "",
        "python": py,
        "warnings": [],
    }

    if not Path(py).exists():
        result["reason"] = f"训练解释器不存在: {py}"
        return result

    try:
        proc = subprocess.run(
            [py, str(PROBE_SCRIPT)],
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
    except subprocess.TimeoutExpired:
        result["reason"] = f"体检超时（{timeout}s）"
        return result
    except OSError as exc:
        result["reason"] = f"无法启动训练解释器: {exc}"
        return result

    stdout = (proc.stdout or "").strip()
    if not stdout:
        result["reason"] = f"探针没有输出（exit={proc.returncode}）: {(proc.stderr or '')[-300:]}"
        return result

    try:
        payload = json.loads(stdout.splitlines()[-1])
    except json.JSONDecodeError as exc:
        result["reason"] = f"探针输出不是合法 JSON: {exc}; 原始输出前 200 字: {stdout[:200]}"
        return result

    if payload.get("error"):
        result["reason"] = str(payload["error"])
        result["torch"] = payload.get("torch")
        result["packages"] = payload.get("packages")
        return result

    result.update({
        "torch": payload.get("torch", {}),
        "packages": payload.get("packages", {}),
        "sdpa": payload.get("sdpa", {}),
        "qwen_arch_modules": payload.get("qwen_arch_modules", []),
        "warnings": payload.get("warnings", []),
    })

    missing = [p for p in REQUIRED_PACKAGES if not result["packages"].get(p)]
    if missing:
        result["reason"] = f"缺少训练依赖: {', '.join(missing)}"
        return result

    torch_info = result["torch"]
    if not torch_info.get("cuda_available"):
        result["reason"] = "CUDA 不可用"
        return result

    # FA2 不可用不是致命问题（sm_75 上本来就没有），但必须提醒，
    # 因为很多训练脚本默认 attn_implementation="flash_attention_2"。
    sdpa = result.get("sdpa", {})
    if sdpa.get("flash") and sdpa["flash"] != "ok":
        result["warnings"].append(
            "FlashAttention-2 不可用（sm_75 正常现象），请使用 sdpa / mem_efficient"
        )

    result["available"] = True
    return result


def require_environment(python: Optional[str] = None, **kwargs: Any) -> dict[str, Any]:
    """同 environment()，但不可用时抛 EnvironmentUnavailable。

    用于「提交训练作业」这种必须硬失败的路径。
    """
    report = environment(python, **kwargs)
    if not report.get("available"):
        raise EnvironmentUnavailable(report.get("reason") or "训练环境不可用")
    return report


def check_model_support(model_id: str, *, python: Optional[str] = None) -> dict[str, Any]:
    """检查学生模型的架构是否被当前 transformers 支持。

    用 transformers 的 AutoConfig 真正加载一次配置——
    架构不被支持时这里就会失败，比等训练跑起来再炸便宜得多。

    已知事实（2026-11-06 实测）：
      - `qwen3`（Qwen3-4B / 8B / 14B）→ transformers 支持 ✓ → 本项目的学生模型；
      - `qwen3_5`（Qwen3.5-* / Qwen3.8-27B，llama.cpp 侧架构名 qwen35）
        → transformers **4.57.6 没有、5.20.2 有**（`models/qwen3_5` 存在，
          `Qwen3_5ForCausalLM` 可用）→ 架构上可训；
      - 但 **Bonsai-2 / JEV-27B-VL 自身不可训练**：本机只有它们的 GGUF，
        没有 HF 权重（底座可训 ≠ 它们可训）。
    """
    py = resolve_python(python)
    if not Path(py).exists():
        return {"supported": False, "reason": f"训练解释器不存在: {py}"}

    script = (
        "import json,re,sys\n"
        "try:\n"
        "    from transformers import AutoConfig\n"
        "    cfg=AutoConfig.from_pretrained(sys.argv[1])\n"
        "    print(json.dumps({'ok':True,'model_type':cfg.model_type,\n"
        "        'architectures':list(getattr(cfg,'architectures',[]) or [])}))\n"
        "except Exception as exc:\n"
        "    msg=str(exc)\n"
        "    m=re.search(r'([A-Za-z0-9_]+) is not a supported model type', msg)\n"
        "    print(json.dumps({'ok':False,'error_type':type(exc).__name__,\n"
        "        'error':msg[:400],\n"
        "        'unsupported_model_type': m.group(1) if m else None}))\n"
    )
    try:
        proc = subprocess.run(
            [py, "-c", script, model_id],
            capture_output=True, text=True, timeout=180,
            env=subprocess_env(),
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {"supported": False, "kind": "env", "reason": f"加载模型配置失败: {exc}"}

    if proc.returncode != 0:
        # 子进程本身没跑起来（解释器坏了 / transformers 导入失败）→ 环境问题。
        return {
            "supported": False,
            "kind": "env",
            "reason": (proc.stderr or "").strip()[-400:] or f"exit={proc.returncode}",
        }
    try:
        info = json.loads((proc.stdout or "").strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError) as exc:
        return {"supported": False, "kind": "env", "reason": f"无法解析模型配置输出: {exc}"}

    if info.get("ok"):
        return {
            "supported": True,
            "kind": "ok",
            "model_type": info.get("model_type"),
            "architectures": info.get("architectures") or [],
        }

    unsupported = info.get("unsupported_model_type")
    if unsupported:
        # 架构不被支持 —— 这是**架构结论**，与环境无关。
        return {
            "supported": False,
            "kind": "arch",
            "model_type": unsupported,
            "reason": info.get("error") or f"{unsupported} 不被当前 transformers 支持",
        }
    # 其他异常（404 / 网络 / 权重没下载）→ 环境问题，不能据此断言架构不支持。
    return {
        "supported": False,
        "kind": "env",
        "reason": info.get("error") or info.get("error_type") or "未知原因",
    }
