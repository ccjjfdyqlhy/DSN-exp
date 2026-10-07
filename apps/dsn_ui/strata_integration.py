# apps/dsn_ui/strata_integration.py
"""Strata 引擎集成：把本机的 Strata 检出注册成 dsn_ui 可调度的本地模型。

## 背景

`~/Strata`（Strata 推理引擎）自带一个 OpenAI / Anthropic 兼容的服务端
（`serve/server.py`）与一个 C++/CUDA 引擎，用一份 run config
（`strata-<model>.json`）描述引擎参数，再由一段启动脚本拉起来：

    cd ~/Strata
    exec .venv/bin/python serve/server.py --engine strata \
         --config strata-coder-iq1_m.json --port 8080 --open

harness 侧把它当作与 llama.cpp 同构的**本地推理引擎**：由
`harness.orchestrator.StrataServerLauncher` 托管子进程（就绪探针、
SIGTERM→SIGKILL、显存回收），并由 ModelScheduler 统一做插槽调度。

## 发现规则

  * 目录：`DSN_STRATA_DIR` / `STRATA_DIR` / `STRATA_HOME` → 默认 `~/Strata`
  * run config：`<dir>/strata-*.json`（含 `exe` 字段的才算）
  * 解释器：优先 `<dir>/.venv/bin/python`（官方 setup 的位置）
  * 模型名：run config 的 `model_name`，注册名形如 `strata:<model_name>`

## 端口

run config 自带的 `port` 是默认值。若该端口已被**另一个已注册的本地模型**
占用，这里会自动让出（顺序探测后续端口），避免两个引擎抢同一个端口导致
「看起来加载成功、实际用的是别的模型」的静默错配。
"""

from __future__ import annotations

import logging
import socket
from pathlib import Path

from harness.orchestrator import (
    ModelSourceType,
    StrataEngineConfig,
    build_engine_config,
    default_python_for_script,
    discover_runs,
    find_strata_root,
)

logger = logging.getLogger("DSNUIStrata")

#: 默认优先级：低于 llama.cpp 的小模型（它们是交互式对话的常用选择）
DEFAULT_PRIORITY = 35


def _claimed_ports(orchestrator, *, exclude: str | None = None) -> set[int]:
    """当前已注册的本地引擎模型所占用的端口集合。"""
    ports: set[int] = set()
    with orchestrator._registry_lock:
        for name, spec in orchestrator._specs.items():
            if name == exclude:
                continue
            if spec.source_type not in (ModelSourceType.LOCAL_LLAMACPP, ModelSourceType.LOCAL_STRATA):
                continue
            cfg = spec.strata_config if spec.source_type == ModelSourceType.LOCAL_STRATA else spec.llama_config
            port = getattr(cfg, "port", None)
            if isinstance(port, int):
                ports.add(port)
    return ports


def _port_is_free(port: int, host: str = "127.0.0.1") -> bool:
    """探测端口是否空闲（TCP bind 测试）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def _pick_port(preferred: int, claimed: set[int], host: str = "127.0.0.1") -> tuple[int, str]:
    """为模型挑选可用端口。

    返回 (port, reason)：
      * 首选端口未被其它已注册模型占用 → 原样使用；
      * 被占用 → 从 preferred+1 起找第一个既没被注册、也真的空闲的端口。
    """
    if preferred not in claimed:
        return preferred, "run config 中的端口"
    port = preferred + 1
    while port < preferred + 200:
        if port not in claimed and _port_is_free(port, host):
            return port, f"原端口 {preferred} 已被其它本地模型占用，自动改用"
        port += 1
    return preferred, "未找到空闲端口，沿用原端口（可能冲突）"


def register_strata_models(
    orchestrator,
    *,
    root: Path | str | None = None,
    ctx_size: int | None = None,
    priority: int = DEFAULT_PRIORITY,
    resident: bool = False,
    request_timeout: int = 600,
    load_timeout: int = 300,
    open_browser: bool = False,
) -> list[str]:
    """扫描并把 Strata 的 run config 注册进 orchestrator。

    Returns:
        成功注册的模型名列表；未检测到 Strata 时返回空列表（正常情况，
        不影响 dsn_ui 启动）。
    """
    base = find_strata_root(root)
    if base is None:
        logger.info("未检测到 Strata 检出（%s），跳过集成", root or "~/Strata")
        return []

    runs = discover_runs(base)
    if not runs:
        logger.info("Strata 检出存在于 %s，但没有可用的 strata-*.json run config", base)
        return []

    python_path = default_python_for_script(base / "serve" / "server.py")
    registered: list[str] = []

    for run in runs:
        try:
            cfg: StrataEngineConfig = build_engine_config(
                run, python_path=python_path, open_browser=open_browser,
            )
            if ctx_size is not None:
                # 覆盖上下文长度 = 改写引擎参数（args 是唯一真相来源）
                cfg.set_ctx_size(int(ctx_size))

            port, reason = _pick_port(cfg.port, _claimed_ports(orchestrator, exclude=run.name))
            if port != cfg.port:
                logger.warning(
                    "Strata 模型 %s 的端口 %d → %d（%s）",
                    run.name, cfg.port, port, reason,
                )
                cfg.port = port

            orchestrator.register_local_strata(
                name=run.name,
                config=cfg,
                priority=priority,
                resident=resident,
                immediate=False,
                load_timeout=load_timeout,
                request_timeout=request_timeout,
            )
            registered.append(run.name)
            logger.info(
                "已注册 Strata 模型: %s (run config %s, exe %s, 端口 %d%s)",
                run.name, Path(run.config_path).name, Path(cfg.resolved_exe()).name, cfg.port,
                f", 启动脚本 {Path(run.script_name).name}" if run.script_name else "",
            )
        except Exception as e:  # noqa: BLE001 - 单个模型失败不应拖垮启动
            logger.warning("注册 Strata 模型 %s 失败: %s", run.name, e)

    return registered


def strata_status(root: Path | str | None = None) -> dict:
    """供 API 查询的 Strata 集成状态。"""
    base = find_strata_root(root)
    if base is None:
        return {
            "strata_dir": str(root or (Path.home() / "Strata")),
            "available": False,
            "server_script": None,
            "python_path": None,
            "runs": [],
        }

    server_script = base / "serve" / "server.py"
    runs = discover_runs(base)
    out = []
    for run in runs:
        try:
            cfg = build_engine_config(run)
            out.append({
                "name": run.name,
                "config_path": run.config_path,
                "script_name": run.script_name,
                "model_name": cfg.model_name,
                "exe": cfg.resolved_exe(),
                "cwd": cfg.resolved_cwd(),
                "tokenizer": cfg.resolved_tokenizer(),
                "port": cfg.port,
                "gpu": cfg.gpu,
                "ctx_size": cfg.resolved_ctx_size(),
                "command_preview": cfg.to_command_string(),
                "run_script_preview": cfg.run_script_text(),
            })
        except Exception as e:  # noqa: BLE001
            out.append({"name": run.name, "config_path": run.config_path, "error": str(e)})

    return {
        "strata_dir": str(base),
        "available": bool(runs),
        "server_script": str(server_script),
        "python_path": default_python_for_script(server_script),
        "runs": out,
    }
