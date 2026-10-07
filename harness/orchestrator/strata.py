# harness/orchestrator/strata.py
# Strata 推理引擎（本地 MoE 引擎 + OpenAI/Anthropic 兼容服务端）支持模块。
#
# 与 llama.cpp 的关系
# ------------------
# Strata 是另一个**本地推理引擎**，它的服务端 `serve/server.py` 提供与
# llama-server 完全兼容的 HTTP API（/health、/props、/slots、/v1/models、
# /v1/chat/completions、/v1/messages、/v1/responses）。因此对 harness 而言
# 两者的差别只有「怎么把服务拉起来」：
#
#   llama.cpp :  <llama-server> --model X --ctx-size N ...
#   Strata    :  <python> <Strata>/serve/server.py --engine strata --config strata-<name>.json --port N
#
# Strata 自己再根据 run config（JSON）拉起它的 C++/CUDA 引擎进程，
# 这正是它启动脚本 `run-<model>.sh` 做的事：
#
#     cd "<Strata>"
#     exec "<venv>/python" "<Strata>/serve/server.py" --engine strata --config "<Strata>/strata-<name>.json" --port 8080 --open
#
# 本模块把这条命令行「结构化」：读 run config JSON → 生成同样语义的命令行，
# 交给 LocalServerLauncher 管理子进程生命周期（就绪探针、优雅停机、显存回收、
# ModelScheduler 插槽协作），并提供 StrataChat / StrataEmbeddingClient 客户端。
#
# run config JSON 的键（实测自 ~/Strata/strata-coder-iq1_m.json）：
#
#     exe        引擎可执行文件（C++/CUDA 二进制）
#     args       传给引擎的参数数组（--pack/--native/--ple-gguf/--expert-profile/...）
#     cwd        引擎工作目录
#     tokenizer  tokenizer 目录（serve/server.py 用来加载分词器与 chat template）
#     model_name /v1/models 里暴露的模型名
#     log        引擎日志文件（serve/server.py 把引擎 stderr 重定向到这里）
#     lib_dirs   追加到 LD_LIBRARY_PATH 的目录（CUDA 运行库等）
#     gpu        GPU 序号，整数/字符串/列表；多个表示层切分（引擎侧 --layer-split）
#     port       监听端口（serve/server.py 只认 --port，故本模块总是显式传）
#
# 除已知键外的一切（backend、vision、expert_profile_save、sampling、
# cors_origins、mcp_servers、host、api_key、aliases、idle_unload_s……）都原样
# 保留在 extra 里并写回文件，绝不丢失用户自己的设置。

from __future__ import annotations

import contextlib
import json
import logging
import os
import shlex
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .local_chat import OpenAICompatChat, OpenAICompatEmbeddingClient
from .local_engine import LocalServerLauncher

logger = logging.getLogger("Strata")

#: run config 里由本模块管理的键；其余键一律原样保留（见 extra）
_KNOWN_KEYS = {
    "exe", "args", "cwd", "tokenizer", "model_name", "log", "lib_dirs", "gpu", "port",
}

#: 查找 run config 时按优先级尝试的文件名模式
RUN_CONFIG_GLOBS = ("strata-*.json", "*strata*.json")


def default_python_for_script(script: str | os.PathLike[str]) -> str:
    """推断该 Strata 检出应该用哪个 Python 解释器。

    与官方启动脚本一致：优先同目录下的 `.venv`（setup.py 安装依赖的位置），
    否则回退到 POSIX 约定的 `bin/python`，最后回退当前解释器。
    """
    root = Path(script).resolve().parent.parent  # <Strata>/serve/server.py -> <Strata>
    for candidate in (
        root / ".venv" / "bin" / "python",
        root / ".venv" / "Scripts" / "python.exe",   # Windows
        root / "venv" / "bin" / "python",
    ):
        if candidate.is_file():
            return str(candidate)
    return sys.executable


def _absolutize(path: str, cwd: str | None) -> str:
    """把相对路径按 run config 的 cwd 解析为绝对路径（Strata 侧同样的规则）。"""
    if not path:
        return path
    expanded = os.path.expanduser(os.path.expandvars(path))
    if os.path.isabs(expanded):
        return os.path.normpath(expanded)
    return os.path.normpath(os.path.join(cwd or ".", expanded))


@dataclass
class StrataEngineConfig:
    """Strata 引擎启动配置与命令行合成器。

    字段分两类：
      * 与 run config JSON 一一对应的**引擎配置**（exe/args/cwd/tokenizer/...）；
      * 由 harness 管理的**服务端参数**（python_path/server_script/port/host/...），
        这些对应 `serve/server.py` 自己的命令行开关。
    """

    # ── 服务端（serve/server.py）──
    python_path: str = ""
    server_script: str = ""
    host: str = "127.0.0.1"
    port: int = 8080
    #: Strata 自己的启动脚本名（仅用于展示与生成同名 .sh）
    script_name: str | None = None
    #: 启动时用浏览器打开 Strata 自带页面
    open_browser: bool = False
    #: 仅启动 API、首个请求再加载模型（Strata 的 --lazy，文本模型专用）
    lazy: bool = False
    api_key: str | None = None
    mcp_config: str | None = None
    idle_unload_s: float | None = None
    min_free_vram_mib: int | None = None
    slot_save_path: str | None = None
    #: serve/server.py 的其它开关（原样追加在管理的参数之后）
    server_extra_args: list[str] = field(default_factory=list)

    # ── 引擎（run config JSON）──
    config_path: str = ""
    exe: str = ""
    args: list[str] = field(default_factory=list)
    cwd: str = ""
    tokenizer: str = ""
    model_name: str = ""
    log: str = ""
    lib_dirs: list[str] = field(default_factory=list)
    gpu: Any = None
    #: run config 中不属于上述字段的一切（原样保留，写回时不丢失）
    extra: dict = field(default_factory=dict)

    # ── 路径解析 ──

    def resolved_script(self) -> str:
        if not self.server_script:
            return ""
        return _absolutize(self.server_script, self.cwd or None)

    def resolved_python(self) -> str:
        script = self.resolved_script()
        if self.python_path:
            return _absolutize(self.python_path, self.cwd or None)
        if script:
            return default_python_for_script(script)
        return sys.executable

    def resolved_config_path(self) -> str:
        return _absolutize(self.config_path, self.cwd or None) if self.config_path else ""

    def resolved_cwd(self) -> str:
        if self.cwd:
            return _absolutize(self.cwd, None)
        script = self.resolved_script()
        if script:
            return str(Path(script).resolve().parent.parent)
        return os.getcwd()

    def resolved_tokenizer(self) -> str:
        return _absolutize(self.tokenizer, self.resolved_cwd()) if self.tokenizer else ""

    def resolved_log(self) -> str:
        return _absolutize(self.log, self.resolved_cwd()) if self.log else ""

    def resolved_exe(self) -> str:
        return _absolutize(self.exe, self.resolved_cwd()) if self.exe else ""

    def resolved_lib_dirs(self) -> list[str]:
        return [
            d for d in (
                _absolutize(x, self.resolved_cwd()) for x in (self.lib_dirs or []) if str(x).strip()
            )
            if Path(d).is_dir()
        ]

    def gpu_list(self) -> list[int]:
        """GPU 序号列表：接受 2 / "2" / [0,1] / "0,1"。

        run config 里也可能是 false / 空值（表示“不指定，由引擎自己决定”）。
        """
        g = self.gpu
        if g is None or g == "" or isinstance(g, bool):
            return []
        if isinstance(g, str):
            return [int(x) for x in g.replace(",", " ").split() if x.strip().lstrip("-").isdigit()]
        if isinstance(g, (list, tuple)):
            out: list[int] = []
            for x in g:
                out.extend(self.__class__(gpu=x).gpu_list())
            return out
        try:
            return [int(g)]
        except (TypeError, ValueError):
            return []

    # ── 命令行合成 ──

    def engine_args(self) -> list[str]:
        """run config 的 args，并保证 CUDA_VISIBLE_DEVICES 之外的多卡层切分生效。"""
        args = [str(a) for a in (self.args or [])]
        return args

    def build_command(self) -> list[str]:
        """合成完整的服务端命令行（等价于官方 run-<model>.sh 的 exec 行）。"""
        script = self.resolved_script()
        cmd: list[str] = [self.resolved_python(), script,
                          "--engine", "strata"]
        cfg_path = self.resolved_config_path()
        if cfg_path:
            cmd += ["--config", cfg_path]
        cmd += ["--port", str(int(self.port))]
        if self.host and self.host != "127.0.0.1":
            cmd += ["--host", str(self.host)]
        if self.api_key:
            cmd += ["--api-key", str(self.api_key)]
        if self.lazy:
            cmd.append("--lazy")
        if self.open_browser:
            cmd.append("--open")
        if self.mcp_config:
            cmd += ["--mcp-config", _absolutize(self.mcp_config, self.resolved_cwd())]
        if self.idle_unload_s:
            cmd += ["--idle-unload", str(float(self.idle_unload_s))]
        if self.min_free_vram_mib:
            cmd += ["--min-free-vram-mib", str(int(self.min_free_vram_mib))]
        if self.slot_save_path:
            cmd += ["--slot-save-path", _absolutize(self.slot_save_path, self.resolved_cwd())]
        tok = self.resolved_tokenizer()
        if tok:
            cmd += ["--tokenizer", tok]
        # 显式 GPU 选择：run config 的 gpu 供引擎用（serve/server.py 也会读），
        # 这里再传一遍 --gpu，使「只改 harness 里的 gpu」也能立刻生效。
        gpus = self.gpu_list()
        if gpus:
            cmd += ["--gpu", ",".join(str(i) for i in gpus)]
        if self.server_extra_args:
            cmd += [str(a) for a in self.server_extra_args]
        return cmd

    def to_command_string(self) -> str:
        """合成可直接在终端运行的命令行字符串（等价于 run-<model>.sh）。"""
        return " ".join(shlex.quote(a) for a in self.build_command())

    def run_script_text(self) -> str:
        """生成与官方 run-<model>.sh 同等语义的启动脚本。

        保留这份能力是为了「所见即所得」：用户可以把 harness 里调好的参数
        直接落成一个可脱离 harness 运行的脚本。
        """
        lines = [
            "#!/bin/sh",
            f'cd "{self.resolved_cwd()}"',
            "exec " + self.to_command_string(),
            "",
        ]
        return "\n".join(lines)

    # ── run config JSON 读写 ──

    def effective_config_dict(self) -> dict:
        """当前内存配置对应的 run config JSON（保留未知键）。"""
        cfg = dict(self.extra or {})
        if self.exe:
            cfg["exe"] = self.resolved_exe()
        cfg["args"] = self.engine_args()
        cfg["cwd"] = self.resolved_cwd()
        if self.tokenizer:
            cfg["tokenizer"] = self.resolved_tokenizer()
        if self.model_name:
            cfg["model_name"] = self.model_name
        if self.log:
            cfg["log"] = self.resolved_log()
        if self.lib_dirs:
            cfg["lib_dirs"] = list(self.lib_dirs)
        if self.gpu not in (None, ""):
            cfg["gpu"] = self.gpu
        cfg["port"] = int(self.port)
        return cfg

    def save_config(self, path: str | os.PathLike[str] | None = None, backup: bool = True) -> Path:
        """把当前配置写回 run config JSON（原子替换，默认留一份 .bak）。"""
        target = Path(path or self.resolved_config_path())
        if not str(target):
            raise ValueError("未指定 run config 路径，无法保存")
        data = self.effective_config_dict()
        if backup and target.exists():
            try:
                shutil.copyfile(target, str(target) + ".bak")
            except OSError as e:
                logger.warning("备份 run config 失败（继续保存）: %s", e)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, target)
        logger.info("已写入 Strata run config: %s", target)
        return target

    @classmethod
    def from_dict(cls, data: dict, *, base_dir: str | os.PathLike[str] | None = None) -> StrataEngineConfig:
        """从 run config 字典构造（base_dir 用于解析相对的 config/server 路径）。"""
        data = dict(data or {})
        known = {k: data.pop(k, None) for k in list(_KNOWN_KEYS)}
        cfg = cls(
            config_path=str(base_dir or ""),
            exe=known.get("exe") or "",
            args=list(known.get("args") or []),
            cwd=known.get("cwd") or (str(base_dir) if base_dir else ""),
            tokenizer=known.get("tokenizer") or "",
            model_name=known.get("model_name") or "",
            log=known.get("log") or "",
            lib_dirs=list(known.get("lib_dirs") or []),
            gpu=known.get("gpu"),
            port=int(known.get("port") or 8080),
            extra={k: v for k, v in data.items() if v is not None},
        )
        # 服务端字段也可能写在 run config 里（Strata 原生支持这些键）
        for key in ("host", "api_key", "mcp_servers", "idle_unload_s", "lazy_load",
                    "min_free_vram_mib", "slot_save_path"):
            if key in cfg.extra and key not in ("mcp_servers",):
                cfg.extra.setdefault(key, cfg.extra[key])
        if isinstance(cfg.extra.get("idle_unload_s"), (int, float)):
            cfg.idle_unload_s = float(cfg.extra["idle_unload_s"])
        if isinstance(cfg.extra.get("min_free_vram_mib"), int):
            cfg.min_free_vram_mib = int(cfg.extra["min_free_vram_mib"])
        if bool(cfg.extra.get("lazy_load")):  # JSON 布尔
            cfg.lazy = True
        return cfg

    @classmethod
    def load(cls, config_path: str | os.PathLike[str]) -> StrataEngineConfig:
        """读取 run config JSON 并构造配置（路径写进 config_path 字段）。"""
        p = Path(config_path).expanduser()
        try:
            text = p.read_text(encoding="utf-8-sig")
        except OSError as e:
            raise FileNotFoundError(f"无法读取 Strata run config {p}: {e}") from e
        try:
            raw = json.loads(text)
        except ValueError as e:
            raise ValueError(f"Strata run config {p} 不是合法 JSON: {e}") from e
        if not isinstance(raw, dict):
            raise TypeError(f"{p.name} 不是 JSON 对象")
        cfg = cls.from_dict(raw, base_dir=str(p))
        cfg.config_path = str(p)
        return cfg

    def resolved_ctx_size(self) -> int | None:
        """上下文长度：从引擎参数 --max-context / --ctx-size / -c 推导，无则 None。

        上下文长度只有一个来源 —— run config 的 args（引擎实际读的就是它），
        所以这里始终现算，不缓存，避免 UI 显示与真实加载不一致。
        """
        args = self.engine_args()
        for flag in ("--max-context", "--ctx-size", "-c"):
            if flag in args[:-1]:
                with contextlib.suppress(TypeError, ValueError):
                    return int(args[args.index(flag) + 1])
        return None

    def set_ctx_size(self, size: int | None) -> None:
        """改写引擎参数里的上下文长度（等价于编辑 run config 的 args）。

        size 为 None 或 <=0 时移除该参数（交给引擎自己的默认值）。
        """
        args = [str(a) for a in self.args or []]
        for flag in ("--max-context", "--ctx-size", "-c"):
            while flag in args[:-1]:
                i = args.index(flag)
                del args[i:i + 2]
        if size is not None and int(size) > 0:
            args += ["--max-context", str(int(size))]
        self.args = args

    def to_dict(self) -> dict:
        """导出给 UI / API 的结构化配置（含解析后的路径与命令行预览）。"""
        return {
            "engine": "strata",
            "python_path": self.python_path,
            "server_script": self.server_script,
            "config_path": self.resolved_config_path(),
            "host": self.host,
            "port": self.port,
            "open_browser": self.open_browser,
            "lazy": self.lazy,
            "api_key": bool(self.api_key),
            "idle_unload_s": self.idle_unload_s,
            "min_free_vram_mib": self.min_free_vram_mib,
            "slot_save_path": self.slot_save_path,
            "mcp_config": self.mcp_config,
            "server_extra_args": list(self.server_extra_args),
            "exe": self.resolved_exe(),
            "args": self.engine_args(),
            "cwd": self.resolved_cwd(),
            "tokenizer": self.resolved_tokenizer(),
            "model_name": self.model_name,
            "log": self.resolved_log(),
            "lib_dirs": list(self.lib_dirs or []),
            "gpu": self.gpu,
            "ctx_size": self.resolved_ctx_size(),
            "command_preview": self.to_command_string(),
        }


@dataclass
class StrataRun:
    """发现到的一份 Strata 检出 + run config。"""

    root: str                 # Strata 根目录（含 serve/server.py）
    server_script: str        # <root>/serve/server.py
    config_path: str          # <root>/strata-<model>.json
    script_name: str | None   # run-<model>.sh（若存在）
    name: str                 # 注册进 orchestrator 的模型名

    @property
    def is_valid(self) -> bool:
        return bool(self.server_script) and bool(self.config_path)


def find_strata_root(start: str | os.PathLike[str] | None = None) -> Path | None:
    """定位 Strata 检出目录（含 serve/server.py）。

    顺序：显式参数 → 环境变量 DSN_STRATA_DIR / STRATA_DIR →
    默认候选 ~/Strata → 通过 PATH 上的 `strata` 命令反查。
    """
    candidates: list[Path] = []
    if start:
        candidates.append(Path(start).expanduser())
    for env in ("DSN_STRATA_DIR", "STRATA_DIR", "STRATA_HOME"):
        if os.getenv(env):
            candidates.append(Path(os.getenv(env, "")).expanduser())
    candidates.append(Path.home() / "Strata")

    for c in candidates:
        if (c / "serve" / "server.py").is_file():
            return c.resolve()

    exe = shutil.which("strata")
    if exe:
        p = Path(exe).resolve()
        for parent in [p.parent, *p.parents]:
            if (parent / "serve" / "server.py").is_file():
                return parent
    return None


def discover_runs(
    root: str | os.PathLike[str] | None = None,
    *,
    prefix: str = "strata:",
) -> list[StrataRun]:
    """扫描 Strata 目录下的 run config，产出可注册的模型条目。

    只认「同一目录下同时存在 serve/server.py 与 strata-*.json」的组合；
    模型名默认取 run config 的 model_name（缺失时用文件名）。
    """
    base = Path(root).expanduser() if root else find_strata_root()
    if base is None or not base.is_dir():
        return []

    server_script = base / "serve" / "server.py"
    if not server_script.is_file():
        return []

    found: dict[str, Path] = {}
    for pattern in RUN_CONFIG_GLOBS:
        for path in sorted(base.glob(pattern)):
            if path.name.endswith(".bak") or path.name.endswith(".tmp"):
                continue
            found.setdefault(str(path.resolve()), path)
        if found:
            break

    runs: list[StrataRun] = []
    for path in found.values():
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as e:
            logger.warning("跳过无法解析的 Strata run config %s: %s", path, e)
            continue
        if not isinstance(raw, dict) or not raw.get("exe"):
            continue
        model_name = str(raw.get("model_name") or path.stem)
        stem = path.stem.removeprefix("strata-")
        script = base / f"run-{stem}.sh"
        runs.append(StrataRun(
            root=str(base.resolve()),
            server_script=str(server_script.resolve()),
            config_path=str(path.resolve()),
            script_name=str(script) if script.is_file() else None,
            name=f"{prefix}{model_name}",
        ))
    return runs


def build_engine_config(
    run: StrataRun,
    *,
    port: int | None = None,
    host: str | None = None,
    python_path: str | None = None,
    open_browser: bool = False,
) -> StrataEngineConfig:
    """由发现结果构造引擎配置（run config 的键原样保留）。"""
    cfg = StrataEngineConfig.load(run.config_path)
    cfg.server_script = run.server_script
    cfg.python_path = python_path or default_python_for_script(run.server_script)
    cfg.script_name = run.script_name
    cfg.open_browser = open_browser
    if port is not None:
        cfg.port = int(port)
    if host:
        cfg.host = host
    cfg.model_name = cfg.model_name or run.name
    return cfg


class StrataServerLauncher(LocalServerLauncher):
    """Strata 服务端子进程生命周期管理器。

    实际拉起的进程是 `python serve/server.py`，它再拉起 Strata 的 C++ 引擎。
    两者同属一个进程组，因此 stop() 的 killpg 会一起收掉（显存随之释放）。
    """

    engine_label = "Strata"
    ready_paths = ("/health", "/v1/models")

    def __init__(self, config: StrataEngineConfig, log_file: str | Path | None = None):
        super().__init__(log_file=log_file or (config.resolved_log() or None))
        self.config = config

    @property
    def base_url(self) -> str:
        return f"http://{self.config.host}:{self.config.port}"

    def build_command(self) -> list[str]:
        return self.config.build_command()

    def api_key(self) -> str | None:
        return self.config.api_key

    def child_env(self) -> dict:
        """子进程环境：CUDA/GPU 选择 + LD_LIBRARY_PATH + run config 自带的 env。"""
        env: dict[str, str] = {}
        gpus = self.config.gpu_list()
        if gpus:
            env["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
            env["CUDA_VISIBLE_DEVICES"] = ",".join(str(i) for i in gpus)
        dirs = self.config.resolved_lib_dirs()
        if dirs:
            existing = os.environ.get("LD_LIBRARY_PATH", "")
            env["LD_LIBRARY_PATH"] = os.pathsep.join(dirs + ([existing] if existing else []))
        raw = self.config.extra.get("env")
        if isinstance(raw, dict):
            env.update({str(k): str(v) for k, v in raw.items()})
        return env

    def describe_target(self) -> str:
        return f"Strata 引擎 ({self.config.model_name or Path(self.config.resolved_exe()).name})"

    def preflight(self) -> None:
        """启动前校验：服务端脚本、解释器、引擎二进制、run config、tokenizer。"""
        script = self.config.resolved_script()
        if not script:
            raise FileNotFoundError(
                "未配置 Strata 服务端脚本路径（serve/server.py）。\n"
                "请在模型设置里指定 Strata 检出目录，或设置环境变量 DSN_STRATA_DIR。"
            )
        if not os.path.isfile(script):
            raise FileNotFoundError(f"未找到 Strata 服务端脚本: {script}")

        python = self.config.resolved_python()
        if python and os.path.sep in python and not os.path.exists(python):
            raise FileNotFoundError(
                f"未找到 Strata 的 Python 解释器: {python}\n"
                f"请确认 {Path(script).resolve().parent.parent} 下的 .venv 已安装（setup.sh / START-HERE）。"
            )

        cfg_path = self.config.resolved_config_path()
        if not cfg_path:
            raise FileNotFoundError("未配置 Strata run config（strata-<model>.json）路径。")
        if not os.path.isfile(cfg_path):
            raise FileNotFoundError(f"未找到 Strata run config: {cfg_path}")

        exe = self.config.resolved_exe()
        if not exe:
            raise ValueError(f"run config {Path(cfg_path).name} 里没有 exe 字段（引擎可执行文件）。")
        if not os.path.isfile(exe):
            raise FileNotFoundError(f"未找到 Strata 引擎可执行文件: {exe}")
        if os.name != "nt":
            try:
                executable = os.access(exe, os.X_OK)
            except OSError as e:                       # 路径畸形（如内嵌 \0）
                raise PermissionError(f"无法校验 Strata 引擎可执行权限: {exe} ({e})") from e
            if not executable:
                raise PermissionError(f"Strata 引擎不可执行（缺少 +x）: {exe}")

        if not (Path(self.config.resolved_cwd()) / "serve").is_dir():
            logger.warning("Strata cwd 下没有 serve/ 目录: %s", self.config.resolved_cwd())

        tok = self.config.resolved_tokenizer()
        if tok and not Path(tok).is_dir():
            logger.warning("Strata tokenizer 目录不存在: %s（启动时 Strata 会自行报错）", tok)
        cwd_note = self.config.resolved_cwd()
        logger.info(
            "Strata 预检通过: engine=%s cwd=%s port=%s gpu=%s",
            exe, cwd_note, self.config.port, self.config.gpu_list() or "all",
        )


class StrataChat(OpenAICompatChat):
    """Strata 服务端的对话客户端（OpenAI 兼容 /v1/chat/completions）。"""

    def __init__(self, *args: Any, **kwargs: Any):
        kwargs.setdefault("label", "Strata")
        super().__init__(*args, **kwargs)


class StrataEmbeddingClient(OpenAICompatEmbeddingClient):
    """Strata 向量客户端占位。

    实测（build 2026-10）serve/server.py **没有** /v1/embeddings 端点，
    因此本类只保留接口形状：调用会得到明确的 404 说明，而不是静默返回空向量。
    若将来的 Strata 版本补上该端点，本类无需改动即可工作。
    """

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)

    def embed(self, texts: list[str]) -> list[list[float]]:
        logger.warning(
            "Strata 服务端未提供 /v1/embeddings；如需本地向量请使用 llama.cpp "
            "(--embeddings) 或独立嵌入模型。"
        )
        return super().embed(texts)
