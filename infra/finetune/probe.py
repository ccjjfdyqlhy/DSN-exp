
# infra/finetune/probe.py
# 训练环境体检探针（**独立脚本，不 import 仓库任何模块**）。
#
# 为什么单独一个文件：
#   探针必须在「训练解释器」里跑（可能是 conda env dsn-train，Python 3.10 + torch 2.3.1），
#   而 DSN 主进程是另一套解释器（Python 3.12，且不允许 import torch）。
#   如果探针写成仓库模块，就得保证两个解释器都能 import 它——
#   所以这里做成零依赖的独立脚本，由 infra/finetune/env.py 用子进程调用。
#
# 输出：一行 JSON 到 stdout。任何异常都收敛成 {"error": ...}，绝不抛栈给调用方。

from __future__ import annotations

import json
import platform
import sys


def _pkg_version(name: str) -> str | None:
    try:
        mod = __import__(name)
    except Exception:
        return None
    return getattr(mod, "__version__", None)


def probe() -> dict:
    out: dict = {
        "python": sys.version.split()[0],
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "error": None,
    }

    try:
        import torch
    except Exception as exc:  # 没有 torch 就没训练可言
        out["error"] = f"torch 不可用: {exc}"
        return out

    out["torch"] = {
        "version": torch.__version__,
        "cuda_version": torch.version.cuda,
        "cuda_available": bool(torch.cuda.is_available()),
        "device_count": 0,
        "devices": [],
        "bf16_supported": False,
        "arch_list": [],
    }

    if torch.cuda.is_available():
        out["torch"]["device_count"] = torch.cuda.device_count()
        devices = []
        for idx in range(torch.cuda.device_count()):
            props = torch.cuda.get_device_properties(idx)
            devices.append({
                "index": idx,
                "name": props.name,
                "compute_capability": f"{props.major}.{props.minor}",
                "total_memory_mib": round(props.total_memory / (1024 * 1024)),
            })
        out["torch"]["devices"] = devices
        major, minor = torch.cuda.get_device_capability(0)
        out["torch"]["bf16_supported"] = bool(major >= 8)
        out["torch"]["arch_list"] = list(getattr(torch.cuda, "get_arch_list", lambda: [])())

    out["packages"] = {
        name: _pkg_version(name)
        for name in ("transformers", "peft", "trl", "accelerate", "bitsandbytes", "datasets", "safetensors")
    }

    # 架构支持：transformers 里有没有对应的模型模块。
    # 学生模型是 Qwen3-8B → qwen3（可训）；JEV/Bonsai 的底座是 qwen35/qwen3_5
    # → transformers 4.x 没有、5.x 有（架构可训，但本项目不训底座）。
    try:
        import transformers.models as tmodels
        out["qwen_arch_modules"] = sorted(n for n in dir(tmodels) if n.startswith("qwen"))
    except Exception as exc:
        out["qwen_arch_modules"] = []
        out.setdefault("warnings", []).append(f"无法枚举 transformers 模型模块: {exc}")

    # FlashAttention-2 是**真探针**，不是读标志：
    # sm_75 上强制 FLASH backend 会抛 "No available kernel"，
    # 所以这里真跑一次，把实际可用的 backend 记下来。
    out["sdpa"] = _probe_sdpa(torch)
    return out


def _probe_sdpa(torch) -> dict:
    result: dict = {"flash": None, "mem_efficient": None, "math": None, "error": None}
    try:
        from torch.nn.attention import SDPBackend, sdpa_kernel
        backends = {
            "flash": SDPBackend.FLASH_ATTENTION,
            "mem_efficient": SDPBackend.EFFICIENT_ATTENTION,
            "math": SDPBackend.MATH,
        }
        if not torch.cuda.is_available():
            result["error"] = "无 CUDA 设备，跳过 SDPA 探针"
            return result
        q = torch.zeros(1, 1, 8, 16, device="cuda", dtype=torch.float16)
        for name, backend in backends.items():
            try:
                with sdpa_kernel(backend):
                    torch.nn.functional.scaled_dot_product_attention(q, q, q, q)
                result[name] = "ok"
            except Exception as exc:
                result[name] = f"unavailable: {type(exc).__name__}: {str(exc)[:160]}"
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    return result


if __name__ == "__main__":
    try:
        payload = probe()
    except Exception as exc:  # 兜底：探针自己崩了也不能让调用方拿不到 JSON
        payload = {"error": f"{type(exc).__name__}: {exc}"}
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.write("\n")
