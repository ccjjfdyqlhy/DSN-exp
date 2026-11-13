# infra/decision/jev.py
"""Discovery and launch configuration for JEV-27B-VL, the System-1 decision model.
#
# ## Why this module exists
#
# JEV is a dual-system hybrid model and both systems share one set of weights:
#
#   * **System 1 (decision)** - a typed-decision head fused into the weights at
#     training time. Give it a closed option set and it writes the answer
#     distribution onto the probability of the next token in a single forward
#     pass, with no reasoning text. The logprobs channel reads that
#     distribution (see infra/decision/client.py).
#
#   * **System 2 (chat)** - ordinary autoregressive generation.
#
# "Where the model lives, how it starts and on which port" is a resource
# question (process, port, VRAM, disk), so by the layering rule it belongs to
# infra. This logic used to live in apps/dsn_ui/jev_integration.py, which meant
# only dsn_ui could use the model and dsn_study had to copy the file. Two
# copies drift (port conflicts, one half of a VRAM change updated). It now
# lives in infra and the app layer only registers the model with the
# orchestrator.
#
# ## Hard constraints (read before changing anything)
#
# 1. **n_gpu_layers is fixed at 99.** JEV uses the qwen35 architecture (Gated
#    Delta Net linear attention) and the fused GDN kernel in llama.cpp only
#    exists for CUDA. Leaving layer 0 on the CPU disables it and every layer
#    then synchronises across the PCIe bus. Measured on this machine (dual
#    RTX 2080 Ti):
#        -ngl 47  ->   3.79 tok/s
#        -ngl 99  ->  27.43 tok/s   <- must be 99
#    So the value takes no environment override: making it configurable only
#    invites someone to set "just enough", which costs 7x speed.
#
# 2. **mmproj_no_offload is on** (--no-mmproj-offload). The weights fill both
#    cards (about 10.5G and 9.7G), so there is no room left for the clip
#    vision encoder: a 768x768 image encodes to 576 image tokens and
#    clip_encode then fails with `CUDA error: out of memory` and **kills the
#    whole llama-server process** (not an error response, a dead process).
#    Keeping the projector on the CPU frees about 1.1GiB and a large image
#    decision then works (Y probability 0.9969, process stable). The price is
#    slower image preprocessing, which is fine for a single System-1 forward
#    pass.
#
# 3. **It owns both cards.** The Q4_K_M weights are 16.5G and occupy roughly
#    10.5G and 9.7G once loaded, so it cannot share the machine with Bonsai-2-27B
#    and needs a port of its own.
"""

from __future__ import annotations

import logging
import os
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from infra.orchestrator import LlamaServerConfig

logger = logging.getLogger("Jev")

#: Default model root, overridable with DSN_JEV_MODEL_ROOT.
DEFAULT_MODEL_ROOT = Path.home() / "qwen_weights"

#: Default llama-server binary. JEV needs the system llama.cpp build, not the
#: one bundled with Bonsai (that one is a ternary quantisation build and does
#: not guarantee qwen35 support).
DEFAULT_BINARY = Path.home() / "llama.cpp" / "build" / "bin" / "llama-server"

#: Default port for JEV. Avoids Bonsai (8080) and Strata (8081).
DEFAULT_PORT = 8090

#: n_gpu_layers is fixed at 99, see the module docstring.
FIXED_N_GPU_LAYERS = 99

#: Default context size. At 32K the prefill decay is only 8% and the VRAM on
#: both cards still fits.
DEFAULT_CTX_SIZE = 32768

#: Default dual card split. Even split across two 11G cards.
DEFAULT_TENSOR_SPLIT = "11,11"

#: File names that are not a main model and are skipped while scanning.
_AUX_PATTERNS = ("mmproj", "dspark", "dflash", "drafter", "kv-bias", "kv_bias")


@dataclass
class JevModel:
    """One JEV model found on disk."""

    name: str                 # registry name, for example jev:JEV-27B-VL
    model_path: str           # the main GGUF
    mmproj_path: Optional[str]  # vision projector, absent means text only
    directory: str            # name of the containing directory

    @property
    def is_multimodal(self) -> bool:
        return bool(self.mmproj_path)


def resolve_model_root(model_root: Optional[Path | str] = None) -> Path:
    """Resolve the model root (argument, then environment, then default)."""
    if model_root:
        return Path(model_root).expanduser()
    env = os.getenv("DSN_JEV_MODEL_ROOT") or os.getenv("JEV_MODEL_ROOT")
    if env:
        return Path(env).expanduser()
    return DEFAULT_MODEL_ROOT


def resolve_binary(binary: Optional[Path | str] = None) -> Optional[str]:
    """Locate the llama-server binary.

    JEV needs the system llama.cpp build (the one bundled with Bonsai is a
    ternary quantisation build and does not guarantee qwen35 support). Returns
    None when nothing is found.
    """
    if binary:
        p = Path(binary).expanduser()
        return str(p) if p.is_file() and os.access(p, os.X_OK) else None

    env = os.getenv("DSN_JEV_BIN")
    if env:
        p = Path(env).expanduser()
        if p.is_file() and os.access(p, os.X_OK):
            logger.info("using the explicit JEV binary: %s", p)
            return str(p)
        logger.warning("DSN_JEV_BIN is not executable, falling back to detection: %s", env)

    if DEFAULT_BINARY.is_file() and os.access(DEFAULT_BINARY, os.X_OK):
        logger.info("found the system llama-server: %s", DEFAULT_BINARY)
        return str(DEFAULT_BINARY)

    logger.info("no usable llama-server found (JEV needs the system llama.cpp build)")
    return None


def _is_auxiliary(path: Path) -> bool:
    """Whether the file is an auxiliary GGUF (projector, draft, kv bias)."""
    name = path.name.lower()
    return any(p in name for p in _AUX_PATTERNS)


def _port_is_free(port: int, host: str = "127.0.0.1") -> bool:
    """Whether the port can actually be bound."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def pick_port(preferred: int, claimed: set[int], host: str = "127.0.0.1") -> tuple[int, str]:
    """Pick a free port for the model.

    Returns (port, reason):
      * the preferred port is not claimed by another model, so it is used as is;
      * otherwise the first port from preferred+1 that is neither claimed nor
        bound is taken.

    JEV must never share a port with Bonsai, otherwise the System-1 identity
    check (model_path in /props) talks to the wrong model.
    """
    if preferred not in claimed:
        return preferred, "the configured port"
    port = preferred + 1
    while port < preferred + 200:
        if port not in claimed and _port_is_free(port, host):
            return port, f"port {preferred} is taken by another local model, moved"
        port += 1
    return preferred, "no free port found, keeping the original one"


def scan_jev_models(model_root: Optional[Path | str] = None) -> list[JevModel]:
    """Scan the model root for every usable main model (with its projector)."""
    root = resolve_model_root(model_root)
    if not root.is_dir():
        logger.info("the JEV model root does not exist: %s", root)
        return []

    found: list[JevModel] = []
    seen: set[str] = set()

    for gguf in sorted(root.rglob("*.gguf")):
        if _is_auxiliary(gguf):
            continue
        key = str(gguf.resolve())
        if key in seen:
            continue
        seen.add(key)

        mmproj = None
        for cand in sorted(gguf.parent.glob("*mmproj*.gguf")):
            mmproj = str(cand)
            break

        directory = gguf.parent.name
        name = f"jev:{directory}"
        # Disambiguate on the file name when the directory name collides.
        if any(m.name == name for m in found):
            name = f"{name}:{gguf.stem[:20]}"

        found.append(JevModel(
            name=name,
            model_path=str(gguf),
            mmproj_path=mmproj,
            directory=directory,
        ))

    logger.info(
        "JEV scan finished: %d models (%d with vision)",
        len(found), sum(1 for m in found if m.is_multimodal),
    )
    return found


def build_jev_config(
    model: JevModel,
    binary_path: str,
    *,
    port: int = DEFAULT_PORT,
    ctx_size: int = DEFAULT_CTX_SIZE,
    n_gpu_layers: int = FIXED_N_GPU_LAYERS,
    tensor_split: str = DEFAULT_TENSOR_SPLIT,
    no_kv_offload: bool = False,
) -> LlamaServerConfig:
    """Build the llama-server launch configuration for a JEV model.

    The key points are in the module docstring: n_gpu_layers fixed at 99, the
    projector on the CPU, both cards taken, and jinja for native OpenAI style
    multi turn chat.

    ``no_kv_offload=True`` keeps the KV cache in system memory instead of VRAM.
    It frees 1-2GB when VRAM is tight (the price is that attention has to read
    the KV cache across PCIe, which slows it down). The weights alone fill both
    cards, so this knob trades "does it start at all" against "how fast it
    runs".
    """
    return LlamaServerConfig(
        binary_path=binary_path,
        model_path=model.model_path,
        host="127.0.0.1",
        port=port,
        n_gpu_layers=n_gpu_layers,
        tensor_split=tensor_split,
        ctx_size=ctx_size,
        jinja=True,
        flash_attn="on",
        mmproj_path=model.mmproj_path,
        mmproj_no_offload=True,
        no_kv_offload=no_kv_offload,
    )
