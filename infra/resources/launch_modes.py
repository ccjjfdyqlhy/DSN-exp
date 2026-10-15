# infra/resources/launch_modes.py
# 启动策略 —— 托管型外周服务（TTS / ASR sidecar 等）的三种拉起方式。
#
# 背景：此前 HTTPServiceLauncher 只接受一条裸 argv（start_command），调用方必须自己
# 拼解释器路径。apps/dsn/models/resource_setup.py 用 sys.executable 拼命令行，于是
# GPT-SoVITS 被 base env 的 python 拉起 —— 缺 fast_langdetect / split_lang / peft /
# opencc 等依赖，必然启动失败。
#
# 三种模式：
#   * COMMAND —— 直接以 argv 拉起子进程（最原始、最可控）。
#   * CONDA   —— 在指定 conda 环境内运行 argv；本质是
#                `conda run -n <env> --no-capture-output <argv>`，
#                因此对上层仍是一条普通命令行，可复用 LocalServerLauncher 的子进程机制。
#   * DOCKER  —— 以 detached 容器运行；没有本地子进程可监管，
#                由 DockerServiceLauncher 用 docker CLI 管理生命周期。
#
# 本模块只有纯数据与路径解析，可无副作用导入，不依赖 torch/funasr/docker。

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class LaunchMode(str, Enum):
    """托管型服务的启动方式。"""

    COMMAND = "command"
    CONDA = "conda"
    DOCKER = "docker"

    @classmethod
    def parse(cls, value: "LaunchMode | str | None") -> "LaunchMode":
        """宽松解析模式字符串（大小写不敏感，接受常见别名）。"""
        if isinstance(value, cls):
            return value
        raw = str(value or "").strip().lower()
        aliases = {
            "command": cls.COMMAND, "cmd": cls.COMMAND, "process": cls.COMMAND,
            "conda": cls.CONDA, "env": cls.CONDA, "conda-env": cls.CONDA, "conda_env": cls.CONDA,
            "docker": cls.DOCKER, "container": cls.DOCKER,
        }
        if raw in aliases:
            return aliases[raw]
        valid = ", ".join(m.value for m in cls)
        raise ValueError(f"未知的启动模式: {value!r}（可选: {valid}）")


def resolve_conda_exe(conda_exe: str = "conda") -> str | None:
    """解析 conda 可执行文件路径；找不到返回 None。

    依次尝试：显式路径 -> PATH -> 常见的 anaconda/miniconda 安装位置。
    """
    candidate = str(conda_exe or "conda").strip() or "conda"
    expanded = os.path.expanduser(os.path.expandvars(candidate))
    if os.path.isabs(expanded) or os.sep in expanded:
        return expanded if os.path.exists(expanded) else None
    found = shutil.which(expanded)
    if found:
        return found
    env_exe = os.environ.get("CONDA_EXE")
    if env_exe and os.path.exists(env_exe):
        return env_exe
    for guess in (
        "/home/darkstar/anaconda3/bin/conda",
        os.path.expanduser("~/anaconda3/bin/conda"),
        os.path.expanduser("~/miniconda3/bin/conda"),
        "/opt/conda/bin/conda",
    ):
        if os.path.exists(guess):
            return guess
    return None


def conda_root(conda_exe: str = "conda") -> Path | None:
    """从 conda 可执行文件路径推断 conda 根目录（<root>/bin/conda）。"""
    resolved = resolve_conda_exe(conda_exe)
    if not resolved:
        return None
    root = Path(resolved).resolve().parent.parent
    return root if root.is_dir() else None


def conda_env_dir(conda_env: str | None, conda_exe: str = "conda") -> Path | None:
    """返回指定 env 的目录；无法推断或 env 为 base 时返回 None。"""
    if not conda_env or conda_env in ("base", "root"):
        return None
    root = conda_root(conda_exe)
    if root is None:
        return None
    return root / "envs" / conda_env


def conda_env_exists(conda_env: str | None, conda_exe: str = "conda") -> bool:
    """判断 conda env 是否存在（base 视为始终存在）。"""
    if not conda_env or conda_env in ("base", "root"):
        return True
    env_dir = conda_env_dir(conda_env, conda_exe)
    if env_dir is None:
        # 根目录不可推断时无法证伪，交由后续启动步骤报错
        return True
    return env_dir.is_dir()


def env_python(conda_env: str | None = None, conda_exe: str = "conda") -> str | None:
    """返回 conda env 内的 python 解释器绝对路径；无法确定时返回 None。

    CONDA 模式下用它把 argv[0] 固定到目标环境的解释器，避免
    `conda run` 之外的任何 PATH 歧义。
    """
    root = conda_root(conda_exe)
    if root is None:
        return None
    if not conda_env or conda_env in ("base", "root"):
        candidates = [root / "bin" / "python", root / "python.exe"]
    else:
        candidates = [
            root / "envs" / conda_env / "bin" / "python",
            root / "envs" / conda_env / "python.exe",
        ]
    for path in candidates:
        if path.exists():
            return str(path)
    return None


#: `env -C` 能力探测结果缓存（GNU coreutils ≥ 8.28 才支持）
_ENV_CHDIR_CAPABLE: bool | None = None


def env_supports_chdir() -> bool:
    """判断本机 `env` 是否支持 `-C/--chdir`（结果缓存）。"""
    global _ENV_CHDIR_CAPABLE
    if _ENV_CHDIR_CAPABLE is None:
        capable = False
        if os.name == "posix" and shutil.which("env"):
            try:
                probe = subprocess.run(
                    ["env", "-C", os.getcwd(), "true"],
                    capture_output=True, timeout=5, check=False,
                )
                capable = probe.returncode == 0
            except Exception:  # noqa: BLE001 - 探测失败即视为不支持
                capable = False
        _ENV_CHDIR_CAPABLE = capable
    return _ENV_CHDIR_CAPABLE


def env_chdir_prefix(cwd: str | None) -> list[str]:
    """返回 `["env", "-C", cwd]`；环境不支持时返回空列表（调用方退化处理）。"""
    if not cwd:
        return []
    if not env_supports_chdir():
        return []
    return ["env", "-C", str(cwd)]


@dataclass
class LaunchSpec:
    """一个托管型服务的启动描述符（纯数据）。

    COMMAND/CONDA 由 LocalServerLauncher 监管子进程；DOCKER 由
    DockerServiceLauncher 用 `docker` CLI 管理容器。
    """

    mode: LaunchMode = LaunchMode.COMMAND

    #: COMMAND/CONDA 的 argv；DOCKER 模式下是容器内要执行的命令
    command: list[str] | None = None
    #: 服务工作目录。**必须显式生效**：LocalServerLauncher 不会把 cwd 传给 Popen，
    #: 因此本类在合成 argv 时自己落实 cwd（见 build_argv）。
    cwd: str | None = None
    env: dict[str, str] = field(default_factory=dict)

    # ── CONDA ──
    conda_env: str | None = None
    #: conda 可执行文件，可给绝对路径
    conda_exe: str = "conda"
    #: 加上 --no-capture-output，让子进程日志实时可见
    conda_no_capture: bool = True
    #: 用 `conda run --cwd <dir>` 落实工作目录（conda ≥ 4.9 支持）
    conda_use_cwd: bool = True

    # ── COMMAND ──
    #: 用 `env -C <dir>` 前缀落实工作目录（GNU coreutils ≥ 8.28）
    command_use_cwd: bool = True

    # ── DOCKER ──
    docker_image: str | None = None
    docker_container_name: str | None = None
    #: 形如 ["--gpus", "all", "-v", "/x:/y"]
    docker_args: list[str] = field(default_factory=list)
    #: 形如 ["9880:9880"]
    docker_ports: list[str] = field(default_factory=list)
    #: 启动前先 docker pull
    docker_pull: bool = False
    #: stop 时顺带 docker rm（默认只停不删）
    docker_rm_on_stop: bool = False

    def __post_init__(self) -> None:
        self.mode = LaunchMode.parse(self.mode)
        if self.command is not None:
            self.command = [str(c) for c in self.command if str(c) != ""]
        self.docker_args = [str(a) for a in (self.docker_args or [])]
        self.docker_ports = [str(p) for p in (self.docker_ports or [])]
        self.env = {str(k): str(v) for k, v in (self.env or {}).items()}

    # ── 判定 ──

    def is_managed(self) -> bool:
        """本 spec 是否描述了一个「需要拉起」的服务（否则为 adopt 模式）。"""
        if self.mode is LaunchMode.DOCKER:
            return bool(self.docker_image)
        return bool(self.command)

    # ── 命令行合成 ──

    def docker_run_args(self) -> list[str]:
        """docker run 的参数（不含开头的 docker 可执行文件本身）。"""
        if self.mode is not LaunchMode.DOCKER:
            raise ValueError("docker_run_args() 仅适用于 DOCKER 模式")
        args = ["run", "-d"]
        if self.docker_container_name:
            args += ["--name", str(self.docker_container_name)]
        if self.cwd:
            # 容器内工作目录（docker run -w）
            args += ["-w", str(self.cwd)]
        for port in self.docker_ports:
            args += ["-p", port]
        args += list(self.docker_args)
        if self.docker_image:
            args.append(str(self.docker_image))
        args += list(self.command or [])
        return args

    def build_argv(self) -> list[str]:
        """合成最终要执行的完整 argv（DOCKER 模式含开头的 docker）。

        工作目录的处理是本模块的重点：LocalServerLauncher 只接受 Popen 的
        stdout/stderr/env，**从不传 cwd**，所以调用方给的 cwd 会被静默忽略。
        很多服务（如 GPT-SoVITS）依赖 `os.getcwd()` 与相对路径定位权重，
        cwd 错了就报 ModuleNotFoundError。因此这里在 argv 层面明确落实 cwd：
          * CONDA   -> `conda run --cwd <dir>`
          * COMMAND -> `env -C <dir> ...`
          * DOCKER  -> `docker run -w <dir>`
        """
        if self.mode is LaunchMode.COMMAND:
            argv = list(self.command or [])
            if self.cwd and self.command_use_cwd:
                prefix = env_chdir_prefix(self.cwd)
                if prefix:
                    argv = prefix + argv
            return argv
        if self.mode is LaunchMode.CONDA:
            if not self.conda_env:
                raise ValueError("CONDA 模式必须提供 conda_env")
            argv = [self.conda_exe, "run", "-n", self.conda_env]
            if self.cwd and self.conda_use_cwd:
                argv += ["--cwd", str(self.cwd)]
            if self.conda_no_capture:
                argv.append("--no-capture-output")
            argv.extend(self.command or [])
            return argv
        if self.mode is LaunchMode.DOCKER:
            return ["docker"] + self.docker_run_args()
        return list(self.command or [])

    def describe(self) -> str:
        """人类可读描述（用于日志）。"""
        if self.mode is LaunchMode.COMMAND:
            return "command: " + " ".join(shlex.quote(c) for c in (self.command or []))
        if self.mode is LaunchMode.CONDA:
            return f"conda[{self.conda_env}] via {self.conda_exe}: " + " ".join(
                shlex.quote(c) for c in (self.command or [])
            )
        if self.mode is LaunchMode.DOCKER:
            return (
                f"docker: image={self.docker_image or '(unset)'} "
                f"name={self.docker_container_name or '(auto)'}"
            )
        return self.mode.value

    def describe_argv(self) -> str:
        """shell 可复现形式的命令行。"""
        try:
            argv = self.build_argv()
        except Exception:  # noqa: BLE001 - 仅用于展示
            return self.describe()
        return " ".join(shlex.quote(c) for c in argv)
