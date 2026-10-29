#!/usr/bin/env python3
# installer.py — AICF 一键安装 · 环境体检 · 首次引导
#
# 为什么这份脚本只依赖标准库（这决定了它的全部写法）：
#   用户第一次拿到仓库时，机器上一个第三方依赖都还没有。这个脚本必须
#   "开箱即跑"，所以不能 import requests / yaml / openai —— 所有需要
#   第三方库的能力，一律通过 subprocess 调 pip / git / python 完成。
#
# 三条硬约束：
#   1. 只用标准库；
#   2. 不破坏用户数据：只创建 .venv / .env / .dsn，绝不删用户的东西
#      （--reinstall 只会重建它自己建的 .venv）；
#   3. 幂等：任何一步都能单独重跑，不重复破坏已有配置。
#
# 用法：
#   python3 installer.py                     # 完整安装 + 引导（默认）
#   python3 installer.py --doctor            # 只体检，不改动任何东西
#   python3 installer.py --non-interactive    # 非交互（CI / 容器）
#   python3 installer.py --branch main       # 安装前切到指定分支
#   python3 installer.py --no-switch         # 不自动切换分支
#   python3 installer.py --reinstall         # 重建 .venv 后重装依赖
#   python3 installer.py --no-launch         # 装完不自动拉起 Web 控制台
#
# 分支策略（2026-10）：
#   main 分支只保留这个安装器作为引导页，真正的 AICF 代码在 harness-refactor。
#   因此正常安装时会**自动** git checkout 到 harness-refactor，再继续安装
#   harness + infra 与全部应用依赖；--doctor 仍然只读，不会自动切分支。

from __future__ import annotations

import argparse
import getpass
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

#: AICF_INSTALL_ROOT 供「切换分支后从 logs/installer.py 副本重跑」使用：
#: 此时脚本不在仓库根，不能再用 __file__ 的父目录当项目根。
_ENV_ROOT = os.environ.get("AICF_INSTALL_ROOT", "").strip()
ROOT = Path(_ENV_ROOT).expanduser().resolve() if _ENV_ROOT else Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
REQUIREMENTS = ROOT / "requirements.txt"
LOG_DIR = ROOT / "logs"

#: 安装器所在的引导分支 / 真正的代码分支。
BOOTSTRAP_BRANCH = "main"
DEFAULT_TARGET_BRANCH = "harness-refactor"

#: 切换分支会把 installer.py 从工作区移除（目标分支不跟踪它）。
#: 先把它读进内存，切换后如果文件消失就写一份到 logs/（已被 .gitignore 忽略）。
try:
    INSTALLER_SOURCE = Path(__file__).read_text(encoding="utf-8")
except OSError:
    INSTALLER_SOURCE = ""

MIN_PY = (3, 10)
DEFAULT_UI_PORT = 8888
DEFAULT_STUDY_PORT = 5000

#: 远程模型后端预设 —— 与 apps/dsn/onboarding.py 的 API_PROVIDERS 保持一致口径
PROVIDER_PRESETS = [
    ("DeepSeek", "https://api.deepseek.com/v1", "deepseek-chat"),
    ("OpenAI", "https://api.openai.com/v1", "gpt-4o-mini"),
    ("智谱 GLM", "https://open.bigmodel.cn/api/paas/v4", "glm-4-flash"),
    ("Moonshot Kimi", "https://api.moonshot.cn/v1", "moonshot-v1-8k"),
    ("硅基流动 SiliconFlow", "https://api.siliconflow.cn/v1", "Qwen/Qwen2.5-7B-Instruct"),
]

#: 仓库完整性清单 —— 缺任何一个都说明 clone 不完整或分支不对。
#: 取的是"框架骨架 + 每个应用的入口"，不是逐个文件穷举。
CRITICAL_FILES = (
    "main.py",
    "launcher.py",
    "apps.yaml",
    "requirements.txt",
    ".env.example",
    "harness/__init__.py",
    "harness/sdk.py",
    "harness/agent/loop.py",
    "harness/tools/__init__.py",
    "harness/context_assembly.py",
    "infra/__init__.py",
    "infra/runtime.py",
    "infra/orchestrator/base.py",
    "infra/orchestrator/router.py",
    "apps/__init__.py",
    "apps/dsn/entry.py",
    "apps/dsn_ui/entry.py",
    "apps/dsn_ui/server.py",
    "apps/dsn_ui/agent.py",
    "apps/dsn_study/entry.py",
    "apps/dsn_study/boot.py",
    "apps/coding_agent/entry.py",
    "apps/densechat/entry.py",
    "apps/emotion_exp/entry.py",
)

CRITICAL_DIRS = (
    "apps/dsn_ui/static",     # 前端构建产物：没有它 Web 控制台打不开
    "harness/tools",
    "harness/memory",
    "infra/orchestrator",
    "infra/store",
    "tests",
    "docs",
)

#: 需要用到的第三方模块 → (import 名, pip 包名, 是否必需)
REQUIRED_MODULES = (
    ("yaml", "PyYAML", True),
    ("dotenv", "python-dotenv", True),
    ("requests", "requests", True),
    ("openai", "openai", True),
    ("flask", "Flask", True),
    ("fastapi", "fastapi", True),
    ("uvicorn", "uvicorn", True),
    ("numpy", "numpy", True),
    ("psutil", "psutil", True),
    ("cv2", "opencv-python", True),
    ("cryptography", "cryptography", True),
    ("jwt", "PyJWT", True),
    ("schedule", "schedule", True),
    ("croniter", "croniter", True),
    ("rich", "rich", True),
    ("mcp", "mcp", False),      # 外部 MCP 工具桥接，延迟导入
)


# ── 终端输出 ────────────────────────────────────────────────────────

class Ansi:
    RESET = "\x1b[0m"
    BOLD = "\x1b[1m"
    DIM = "\x1b[2m"
    RED = "\x1b[31m"
    GREEN = "\x1b[32m"
    YELLOW = "\x1b[33m"
    BLUE = "\x1b[36m"
    MAGENTA = "\x1b[35m"


_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def paint(text: str, code: str) -> str:
    return f"{code}{text}{Ansi.RESET}" if _COLOR else text


def out(line: str = "") -> None:
    print(line)


def step(no: int, total: int, title: str) -> None:
    out()
    out(paint(f"━━ [{no}/{total}] {title} ", Ansi.BOLD + Ansi.BLUE) + paint("━" * 4, Ansi.BLUE))


def ok(msg: str) -> None:
    out(f"  {paint('✓', Ansi.GREEN)} {msg}")


def warn(msg: str) -> None:
    out(f"  {paint('!', Ansi.YELLOW)} {msg}")


def fail(msg: str) -> None:
    out(f"  {paint('✗', Ansi.RED)} {msg}")


def info(msg: str) -> None:
    out(f"    {paint('·', Ansi.DIM)} {msg}")


def hint(msg: str) -> None:
    out(f"    {paint('→', Ansi.DIM)} {paint(msg, Ansi.DIM)}")


# ── 小工具 ──────────────────────────────────────────────────────────

def run(cmd: list[str], cwd: Path | None = None, timeout: int | None = None,
        env: dict | None = None) -> tuple[int, str, str]:
    """执行命令，返回 (returncode, stdout, stderr)。永不抛异常。"""
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
    except FileNotFoundError:
        return 127, "", f"命令不存在: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "", f"命令超时: {' '.join(cmd)}"
    except OSError as exc:  # pragma: no cover - 极端环境
        return 1, "", str(exc)
    return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()


def port_free(port: int, host: str = "0.0.0.0") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def human_size(num_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num_bytes < 1024 or unit == "TB":
            return f"{num_bytes:.1f}{unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f}TB"


def ask(prompt: str, default: str = "", secret: bool = False) -> str | None:
    """问一个问题。返回 None 表示用户回车跳过或输入流已结束。"""
    suffix = paint(f"（回车用默认值：{default}）", Ansi.DIM) if default else ""
    try:
        if secret:
            raw = getpass.getpass(f"  {prompt} ").strip()
        else:
            raw = input(f"  {prompt} {suffix} ").strip()
    except (EOFError, KeyboardInterrupt):
        out()
        return None
    if raw:
        return raw
    return default if default else None


def ask_yes_no(prompt: str, default: bool = True) -> bool:
    raw = ask(prompt, "")
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("y", "yes", "是", "好", "1", "true", "ok")


# ── Git ─────────────────────────────────────────────────────────────

def git(*args: str, cwd: Path | None = None) -> tuple[int, str, str]:
    if not shutil.which("git"):
        return 127, "", "git 未安装"
    return run(["git", *args], cwd=cwd or ROOT)


def is_git_repo() -> bool:
    rc, _, _ = git("rev-parse", "--git-dir")
    return rc == 0


def current_branch() -> str:
    rc, text, _ = git("rev-parse", "--abbrev-ref", "HEAD")
    return text if rc == 0 else "(未知)"


def dirty_files() -> list[str]:
    rc, text, _ = git("status", "--porcelain")
    if rc != 0:
        return []
    return [line for line in text.splitlines() if line.strip()]


def is_legacy_layout() -> bool:
    """判断当前工作区是不是 main 的旧单体布局（没有 harness/ 与 apps/）。"""
    return not (ROOT / "harness").is_dir() or not (ROOT / "apps").is_dir()


def preserve_installer_after_switch() -> None:
    """切到 harness-refactor 后，如果 installer.py 被 git 移除，保留一份可重跑的副本。"""
    if (ROOT / "installer.py").is_file() or not INSTALLER_SOURCE:
        return
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    backup = LOG_DIR / "installer.py"
    try:
        backup.write_text(INSTALLER_SOURCE, encoding="utf-8")
    except OSError as exc:
        warn(f"无法在 logs/ 保留安装器副本：{exc}")
        return
    info(f"目标分支不跟踪 installer.py，已在 {backup.relative_to(ROOT)} 保留副本")
    hint("重跑体检：AICF_INSTALL_ROOT='{}' '{}' '{}' --doctor".format(
        ROOT, sys.executable, backup.relative_to(ROOT)))


def switch_branch(name: str, force: bool = False) -> tuple[bool, str]:
    """切到指定分支。脏工作区时默认拒绝（不静默 stash 用户改动）。"""
    rc, _, _ = git("rev-parse", "--verify", name)
    if rc != 0:
        rc, text, _ = git("fetch", "--all", "--prune")
        if rc != 0:
            return False, f"拉取远端失败: {text}"
        rc, _, _ = git("rev-parse", "--verify", f"origin/{name}")
        if rc != 0:
            return False, f"分支 {name} 不存在（本地与远端都没有）"
    if current_branch() == name:
        return True, f"已在分支 {name}"
    dirty = dirty_files()
    if dirty and not force:
        return False, (f"工作区有 {len(dirty)} 处未提交改动，拒绝自动切分支。"
                       f"请先提交/暂存，或加 --force 强制切换")
    args = ["checkout"] + (["-f"] if force else []) + [name]
    rc, text, err = git(*args)
    if rc != 0:
        return False, f"切换失败: {err or text}"
    return True, f"已切到分支 {name}"


# ── 仓库完整性 ──────────────────────────────────────────────────────

def check_integrity() -> tuple[list[str], list[str]]:
    """返回 (缺失文件, 缺失目录)。"""
    missing_files = [f for f in CRITICAL_FILES if not (ROOT / f).is_file()]
    missing_dirs = [d for d in CRITICAL_DIRS if not (ROOT / d).is_dir()]
    return missing_files, missing_dirs


def registered_entries() -> dict[str, str]:
    """从 apps.yaml 里读出 应用名 → entry 模块（简易行解析，不引入 yaml 依赖）。"""
    mapping: dict[str, str] = {}
    if not (ROOT / "apps.yaml").is_file():
        return mapping
    current = None
    for raw in (ROOT / "apps.yaml").read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if not line.startswith((" ", "\t")):
            current = line.split(":", 1)[0].strip()
            continue
        stripped = line.strip()
        if stripped.startswith("entry:") and current:
            mapping[current] = stripped.split(":", 1)[1].strip()
    return mapping


def check_registered_entries() -> list[str]:
    """apps.yaml 里登记的每个应用，其 entry 模块对应的文件必须存在。"""
    problems = []
    for app, entry in registered_entries().items():
        module_path = ROOT / (entry.replace(".", "/") + ".py")
        if not module_path.is_file():
            problems.append(f"{app} → {entry}（缺 {module_path.relative_to(ROOT)}）")
    return problems


def dead_model_profiles() -> list[tuple[str, str]]:
    """扫描 model_profiles 里指向不存在文件的本地模型（简易行解析，非完整 YAML）。"""
    profiles_dir = ROOT / "apps" / "dsn" / "model_profiles"
    dead: list[tuple[str, str]] = []
    if not profiles_dir.is_dir():
        return dead
    for yml in sorted(profiles_dir.glob("*.yaml")):
        try:
            text = yml.read_text(encoding="utf-8")
        except OSError:
            continue
        for key in ("model_path", "binary_path", "mmproj_path"):
            match = re.search(rf"^\s*{key}\s*:\s*(\S+)\s*$", text, re.MULTILINE)
            if not match:
                continue
            raw = match.group(1).strip().strip('"\'')
            if not raw or raw.startswith("$"):
                continue
            expanded = Path(os.path.expanduser(os.path.expandvars(raw)))
            if not expanded.exists():
                dead.append((yml.name, f"{key}={raw}"))
    return dead


# ── 机器探测 ────────────────────────────────────────────────────────

def probe_machine() -> dict:
    machine = {
        "platform": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "python": platform.python_version(),
        "cpu": os.cpu_count() or 0,
    }
    try:
        machine["disk_free"] = human_size(shutil.disk_usage(ROOT).free)
    except OSError:
        machine["disk_free"] = "未知"
    mem = None
    try:
        if platform.system() == "Linux":
            with open("/proc/meminfo", "r", encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("MemTotal:"):
                        mem = int(line.split()[1]) * 1024
                        break
    except (OSError, ValueError, IndexError):
        mem = None
    machine["memory"] = human_size(mem) if mem else "未知"
    gpus = []
    machine["gpu_error"] = ""
    if shutil.which("nvidia-smi"):
        rc, text, err = run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            timeout=15)
        # nvidia-smi 存在但驱动/库版本不匹配时，退出码可能仍是 0，只是输出里
        # 混进了 "Failed to initialize NVML" 之类的报错 —— 只认真正的 GPU 行。
        for line in text.splitlines():
            line = line.strip()
            if not line or "Failed" in line or "NVML" in line or "not found" in line.lower():
                continue
            if "MiB" in line or "NVIDIA" in line or "GeForce" in line:
                gpus.append(line)
        if not gpus:
            reason = (err or text).splitlines()
            machine["gpu_error"] = reason[0] if reason else "调用失败"
    machine["gpus"] = gpus
    return machine


# ── 依赖 ────────────────────────────────────────────────────────────

def venv_python() -> Path | None:
    if os.name == "nt":
        candidate = VENV_DIR / "Scripts" / "python.exe"
    else:
        candidate = VENV_DIR / "bin" / "python"
    return candidate if candidate.is_file() else None


def create_venv() -> tuple[bool, str]:
    if venv_python():
        return True, f"复用已存在的虚拟环境 {VENV_DIR.name}/"
    try:
        import venv as venv_mod
        venv_mod.EnvBuilder(with_pip=True, clear=False).create(str(VENV_DIR))
    except Exception as exc:  # noqa: BLE001 - 任何建 venv 失败都要可读
        return False, f"创建虚拟环境失败: {exc}"
    if not venv_python():
        return False, "虚拟环境创建了但找不到解释器"
    return True, f"已创建虚拟环境 {VENV_DIR.name}/"


def missing_modules(python_exe: Path) -> list[tuple[str, str, bool]]:
    """用目标解释器探测缺哪些第三方模块。返回 [(import名, pip包名, 必需)]。"""
    script = (
        "import importlib.util,json,sys\n"
        "mods=json.loads(sys.argv[1])\n"
        "out=[m for m in mods if importlib.util.find_spec(m[0]) is None]\n"
        "print(json.dumps(out))\n"
    )
    rc, text, _ = run([str(python_exe), "-c", script, json.dumps(
        [[m[0], m[1], m[2]] for m in REQUIRED_MODULES])], timeout=90)
    if rc != 0:
        return []
    try:
        raw = json.loads(text or "[]")
    except ValueError:
        return []
    return [(r[0], r[1], r[2]) for r in raw]


def framework_status(python_exe: Path) -> tuple[bool, str]:
    """确认 harness + infra 真的能被目标解释器导入（而不只是 pip 返回 0）。"""
    script = (
        "import harness, infra\n"
        "print(getattr(harness, '__version__', 'unknown'))\n"
    )
    rc, text, err = run([str(python_exe), "-c", script], cwd=ROOT, timeout=90)
    if rc != 0:
        detail = (err or text).strip().splitlines()
        return False, detail[-1] if detail else f"退出码 {rc}"
    return True, (text.strip().splitlines()[-1] if text.strip() else "unknown")


def pip_install(python_exe: Path, args: list[str], label: str) -> tuple[bool, str]:
    cmd = [str(python_exe), "-m", "pip", "install", *args]
    shown = [a.replace(str(ROOT) + "/", "").replace(str(ROOT), ".") for a in args]
    info(f"pip install {' '.join(shown)}")
    rc, text, err = run(cmd, timeout=1800)
    if rc != 0:
        tail = (err or text).strip().splitlines()
        detail = tail[-1] if tail else f"退出码 {rc}"
        return False, f"{label} 失败：{detail}"
    return True, f"{label} 完成"


# ── .env ────────────────────────────────────────────────────────────

def env_values() -> dict[str, str]:
    """读取 .env 里的键值（忽略注释行）。"""
    values: dict[str, str] = {}
    if not ENV_FILE.is_file():
        return values
    try:
        for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    except OSError:
        pass
    return values


def env_set(key: str, value: str) -> None:
    """写入/更新 .env 里的单个键，保留其余内容与注释。

    连续写多个键时不会插空行 —— 否则 provider 配置那几行会被空行割开，
    读起来像拼了好几段。
    """
    lines: list[str] = []
    if ENV_FILE.is_file():
        try:
            lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
    result: list[str] = []
    replaced = False
    for raw in lines:
        stripped = raw.strip()
        if (stripped and not stripped.startswith("#") and "=" in stripped
                and stripped.split("=", 1)[0].strip().upper() == key.upper()):
            result.append(f"{key}={value}")
            replaced = True
        else:
            result.append(raw)
    if not replaced:
        # 只在"第一次追加"且文件末尾是注释块时补一个分隔空行
        if result and result[-1].strip().startswith("#"):
            result.append("")
        result.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(result) + "\n", encoding="utf-8")
    try:
        os.chmod(ENV_FILE, 0o600)
    except OSError:
        pass


def env_has_placeholder_key() -> bool:
    """检测 .env 里是否还是 .env.example 的占位密钥。"""
    value = env_values().get("OPENAI_API_KEY", "")
    return bool(value) and value == "sk-your-key-here"


def write_env_stub() -> None:
    """写一份"未配置后端"的 .env —— 不放假密钥，只放引导注释。"""
    body = """# ── AICF 最小配置（由 installer.py 生成）─────────────────────────
# 当前尚未配置模型后端。
#
# dsn_ui 可以正常启动（界面、资源管理、模型列表都能用），但对话需要先接入后端。
# 两种接入方式，任选其一：
#
#   A. 图形界面（推荐）：启动 Web 控制台 → 右上角「设置 → Provider」
#      → 填 Base URL 与 API Key → 保存。无需改本文件。
#
#   B. 直接编辑本文件：取消下面四行的注释并填写。
#
# MAIN_MODEL_TYPE=openai
# MAIN_MODEL_NAME=
# OPENAI_API_BASE=
# OPENAI_API_KEY=
#
# 完整配置项见 .env.example（绝大多数都有默认值）。
"""
    ENV_FILE.write_text(body, encoding="utf-8")
    try:
        os.chmod(ENV_FILE, 0o600)
    except OSError:
        pass


# ── 交互引导 ────────────────────────────────────────────────────────

def intro() -> None:
    line = "─" * 66
    out(paint(line, Ansi.MAGENTA))
    out(paint("  AICF — Agent Infrastructure Cybernetics Framework", Ansi.BOLD + Ansi.MAGENTA))
    out(paint("  一个完全跑在本地的智能体底座", Ansi.MAGENTA))
    out(paint(line, Ansi.MAGENTA))
    out()
    out(paint("  三层结构，依赖单向向下：", Ansi.BOLD))
    out("    apps/     业务应用   语音陪伴 · Web 控制台 · 学习助手 · 示例")
    out("      ▼")
    out("    harness/  Agent 核心 循环 · 工具 · 上下文 · 记忆 · 人格 · SDK")
    out("      ▼")
    out("    infra/    基础设施  模型编排 · 存储 · 网关 · 鉴权 · 策略")
    out()
    out(paint("  一句话：infra 管资源，harness 管思考，apps 管场景。", Ansi.DIM))
    out()
    out("  接下来这个脚本会依次完成：")
    out("    1. 检查运行环境")
    out(f"    2. 自动切换到 {DEFAULT_TARGET_BRANCH} 分支（main 只是安装引导）")
    out("    3. 校验仓库完整性")
    out("    4. 探测机器配置（Python / 内存 / 磁盘 / GPU / 端口）")
    out("    5. 建立虚拟环境并安装依赖（harness + infra + 应用依赖）")
    out("    6. 生成 .env、引导接入模型后端并启动 Web 控制台")
    out()


def interactive_provider_setup() -> bool:
    """引导配置远程模型后端。返回是否成功写入。"""
    out()
    out(paint("  ── 接入模型后端 ──", Ansi.BOLD))
    out("  [1] 远程 API（OpenAI 兼容：DeepSeek / OpenAI / GLM / Kimi …）")
    out("  [2] 本地 llama.cpp（需要自己准备 GGUF 与 llama-server）")
    out("  [3] 稍后再说（先启动界面，之后在「设置 → Provider」里配）")
    choice = ask("请选择", "3")
    if choice is None:
        return False
    choice = choice.strip()

    if choice == "1":
        out()
        for idx, (name, base, model) in enumerate(PROVIDER_PRESETS, start=1):
            out(f"    [{idx}] {name:<22} {base}  ({model})")
        out(f"    [{len(PROVIDER_PRESETS) + 1}] 自定义端点")
        pick = ask("选哪个", "1")
        idx = int(pick) if pick and pick.isdigit() else 1
        if 1 <= idx <= len(PROVIDER_PRESETS):
            name, base, model = PROVIDER_PRESETS[idx - 1]
        else:
            name = "自定义"
            base = ask("Base URL（不含 /chat/completions）", "") or ""
            model = ask("模型名", "") or ""
        key = ask("API Key（不回显）", "", secret=True)
        if not key:
            warn("没填 Key，跳过接入配置")
            return False
        env_set("MAIN_MODEL_TYPE", "openai")
        env_set("MAIN_MODEL_NAME", model or name)
        env_set("OPENAI_API_BASE", base)
        env_set("OPENAI_API_KEY", key)
        ok(f"已写入 .env：{name} / {model}")
        return True

    if choice == "2":
        out()
        out("  本地模型需要三样东西：")
        out("    1. 编译好的 llama-server（默认找 ~/llama.cpp/build/bin/llama-server）")
        out("    2. 一个 GGUF 权重文件")
        out("    3. 一份模型描述 YAML —— 照抄 apps/dsn/model_profiles.example/ 里的模板")
        out()
        out(paint("  完整步骤见 docs/getting-started.md 第 3.2 节。", Ansi.DIM))
        hint("也可以稍后在 Web 控制台的「接入新实例」向导里扫描本地 GGUF 自动完成")
        return False

    hint("随时可在 Web 控制台「设置 → Provider」里补配置")
    return False


# ── 启动 Web 控制台 ─────────────────────────────────────────────────

def launch_ui(python_exe: Path, port: int) -> tuple[int | None, Path]:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / "dsn_ui.log"
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    with open(log_path, "w", encoding="utf-8") as log_fh:
        proc = subprocess.Popen(
            [str(python_exe), "-m", "apps.dsn_ui.server",
             "--host", "0.0.0.0", "--port", str(port), "--slots", "2"],
            cwd=str(ROOT), env=env, stdout=log_fh, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
    return proc.pid, log_path


def wait_health(port: int, timeout: float = 45.0) -> bool:
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}/api/health"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError, ValueError):
            pass
        time.sleep(1.0)
    return False


# ── 各步骤 ──────────────────────────────────────────────────────────

def step_environment() -> bool:
    step(1, 5, "检查运行环境")
    version = sys.version_info
    if version[:2] < MIN_PY:
        fail(f"Python 版本过低：{version.major}.{version.minor}，需要 >= {MIN_PY[0]}.{MIN_PY[1]}")
        hint("建议用 pyenv / conda 装一个 3.10 以上版本")
        return False
    ok(f"Python {version.major}.{version.minor}.{version.micro}")
    if not shutil.which("git"):
        warn("未找到 git（不影响使用，但无法自动切分支 / 更新）")
    else:
        ok("git 可用")
    if not shutil.which("pip") and not venv_python():
        warn("未找到 pip（安装依赖会失败）")
    else:
        ok("pip 可用")
    return True


def step_git(branch: str | None, force: bool, auto_switch: bool = True) -> bool:
    step(2, 5, "仓库状态与分支")
    target = branch or (DEFAULT_TARGET_BRANCH if auto_switch else None)

    if not shutil.which("git"):
        if is_legacy_layout():
            fail("当前是 main 的旧单体布局，但没有 git，无法自动切到 "
                 f"{DEFAULT_TARGET_BRANCH}")
            hint("请安装 git 后重试，或手动下载 harness-refactor 分支的压缩包")
            return False
        info("跳过（无 git）")
        return True
    if not is_git_repo():
        if is_legacy_layout():
            fail("当前目录不是 git 仓库，且看起来是旧单体布局")
            hint(f"请从 {DEFAULT_TARGET_BRANCH} 分支重新 clone / 下载")
            return False
        info("这不是 git 仓库（可能从压缩包解压安装），跳过分支检查")
        return True

    ok(f"当前分支：{current_branch()}")
    dirty = dirty_files()
    if dirty:
        warn(f"工作区有 {len(dirty)} 处未提交改动（不影响安装，但切分支会被拒绝）")
        for line in dirty[:5]:
            info(line)

    if target:
        if current_branch() == target:
            ok(f"已在目标分支 {target}")
        else:
            info(f"安装需要 {target} 分支，正在自动切换…")
            switched, message = switch_branch(target, force=force)
            (ok if switched else fail)(message)
            if not switched:
                if dirty and not force:
                    hint("请先提交/暂存改动，或加 --force 强制切换")
                return False
            preserve_installer_after_switch()
        if is_legacy_layout():
            fail(f"已切到 {target}，但仍缺少 harness/ 或 apps/ 目录")
            hint("目标分支可能不完整；请检查远程分支内容后重试")
            return False
    else:
        if is_legacy_layout():
            fail("这个仓库看起来是旧版本（单体布局，没有 harness/ 目录）")
            hint(f"去掉 --no-switch 以自动切到 {DEFAULT_TARGET_BRANCH}，"
                 f"或运行：git checkout {DEFAULT_TARGET_BRANCH}")
            return False
        hint("已禁用自动切分支；如需切换：python3 installer.py --branch <名字>")

    rc, text, _ = git("remote", "-v")
    if rc == 0 and text:
        info(f"远端：{text.splitlines()[0].split()[0]}")
    return True


def step_integrity() -> bool:
    step(3, 5, "仓库完整性")
    missing_files, missing_dirs = check_integrity()
    entry_problems = check_registered_entries()
    total_missing = len(missing_files) + len(missing_dirs) + len(entry_problems)
    if total_missing == 0:
        ok(f"关键文件与目录齐全（校验 {len(CRITICAL_FILES)} 个文件 / "
           f"{len(CRITICAL_DIRS)} 个目录）")
    else:
        fail(f"仓库不完整，缺 {total_missing} 项：")
        for item in missing_files:
            fail(f"缺文件：{item}")
        for item in missing_dirs:
            fail(f"缺目录：{item}")
        for item in entry_problems:
            fail(f"apps.yaml 登记的应用无入口：{item}")
        hint("多半是 clone 不完整或分支不对；试试 git fetch --all 后重新 checkout")
        return False
    dead = dead_model_profiles()
    if dead:
        warn(f"{len(dead)} 处模型路径在本机不存在（不影响启动，加载该模型时会失败）：")
        for name, detail in dead[:6]:
            info(f"{name}: {detail}")
        hint("在 Web 控制台「接入新实例」里改路径，或删除对应 profile")
    else:
        ok("模型 profile 路径检查通过")
    return True


def step_machine() -> dict:
    step(4, 5, "机器配置")
    machine = probe_machine()
    ok(f"系统：{machine['platform']}")
    ok(f"CPU 核数：{machine['cpu']}    内存：{machine['memory']}    "
       f"可用磁盘：{machine['disk_free']}")
    if machine["gpus"]:
        for gpu in machine["gpus"]:
            ok(f"GPU：{gpu}")
    elif machine.get("gpu_error"):
        warn(f"检测到 nvidia-smi，但查询失败：{machine['gpu_error']}")
        info("常见原因：驱动与 CUDA 库版本不匹配（nvidia-smi 报错即为佐证）")
        info("纯 CPU 也能跑，只是本地模型会慢很多")
    else:
        info("未检测到 NVIDIA GPU（纯 CPU 也能跑，但本地模型会慢很多）")
    if port_free(DEFAULT_UI_PORT):
        ok(f"端口 {DEFAULT_UI_PORT} 可用（Web 控制台）")
    else:
        warn(f"端口 {DEFAULT_UI_PORT} 已被占用 —— 启动时会失败，可换端口")
    if not port_free(DEFAULT_STUDY_PORT):
        info(f"端口 {DEFAULT_STUDY_PORT} 被占用（dsn / dsn_study 默认端口）")
    return machine


def step_dependencies(no_venv: bool, reinstall: bool, doctor_only: bool) -> Path | None:
    step(5, 5, "安装依赖")
    if doctor_only:
        target = venv_python() or Path(sys.executable)
        missing = missing_modules(target)
        if not missing:
            ok("依赖齐全")
        else:
            for mod, pkg, required in missing:
                (fail if required else warn)(f"缺少 {pkg}（import {mod}）")
            hint("执行 python3 installer.py 安装缺失依赖")
        return target

    if reinstall and VENV_DIR.exists():
        info(f"重建虚拟环境 {VENV_DIR.name}/ …")
        shutil.rmtree(VENV_DIR, ignore_errors=True)

    if no_venv:
        target = Path(sys.executable)
        info(f"使用当前解释器：{target}")
    else:
        created, message = create_venv()
        (ok if created else fail)(message)
        if not created:
            hint("也可以加 --no-venv 直接装进当前解释器")
            return None
        target = venv_python()
        if target is None:
            fail("找不到虚拟环境里的解释器")
            return None

    pip_ok, pip_msg = pip_install(target, ["--upgrade", "pip"], "升级 pip")
    (ok if pip_ok else warn)(pip_msg)

    if REQUIREMENTS.is_file():
        req_ok, req_msg = pip_install(target, ["-r", str(REQUIREMENTS)], "安装 requirements.txt")
        if not req_ok:
            fail(req_msg)
            hint("国内网络可加镜像：pip install -r requirements.txt "
                 "-i https://pypi.tuna.tsinghua.edu.cn/simple")
            return None
        ok(req_msg)
    else:
        warn(f"找不到 {REQUIREMENTS.name}")

    editable_ok, editable_msg = pip_install(target, ["-e", str(ROOT)], "以可编辑模式安装框架")
    (ok if editable_ok else warn)(editable_msg)
    if not editable_ok:
        hint("框架未装成可编辑模式不影响启动，但代码改动不会生效")

    missing = missing_modules(target)
    hard = [m for m in missing if m[2]]
    soft = [m for m in missing if not m[2]]
    if hard:
        for mod, pkg, _ in hard:
            fail(f"仍缺少 {pkg}（import {mod}）")
    else:
        ok("必需依赖已全部就位")
    for mod, pkg, _ in soft:
        warn(f"可选依赖 {pkg} 缺失（相关功能不可用，不影响启动）")

    fw_ok, fw_detail = framework_status(target)
    if fw_ok:
        ok(f"harness + infra 可导入（harness {fw_detail}）")
    else:
        fail(f"harness / infra 导入失败：{fw_detail}")
        hint("试试：pip install -e . ；若刚切到 harness-refactor，请确认仓库完整")
        return None
    return target


# ── 主流程 ──────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="installer.py",
        description="AICF 一键安装 · 环境体检 · 首次引导",
    )
    parser.add_argument("--doctor", action="store_true",
                        help="只做体检，不改动任何东西")
    parser.add_argument("--non-interactive", action="store_true",
                        help="不提问，全部用默认值（CI / 容器）")
    parser.add_argument("--branch", default=None,
                        help=f"安装前切换到指定分支（默认自动切到 {DEFAULT_TARGET_BRANCH}）")
    parser.add_argument("--no-switch", action="store_true",
                        help="不自动切换分支（仅在已经位于目标分支时使用）")
    parser.add_argument("--force", action="store_true",
                        help="切分支时强制丢弃工作区改动")
    parser.add_argument("--no-venv", action="store_true",
                        help="不建虚拟环境，直接装进当前解释器")
    parser.add_argument("--reinstall", action="store_true",
                        help="重建 .venv 后重装依赖")
    parser.add_argument("--no-launch", action="store_true",
                        help="装完不自动拉起 Web 控制台")
    parser.add_argument("--port", type=int, default=DEFAULT_UI_PORT,
                        help=f"Web 控制台端口（默认 {DEFAULT_UI_PORT}）")
    args = parser.parse_args(argv)

    interactive = not (args.non_interactive or args.doctor or not sys.stdin.isatty())

    out()
    if args.doctor:
        out(paint("  AICF 环境体检", Ansi.BOLD))
        out()
        ok_env = step_environment()
        ok_git = step_git(args.branch, args.force, auto_switch=False)
        ok_files = step_integrity()
        step_machine()
        step_dependencies(args.no_venv, args.reinstall, doctor_only=True)
        out()
        if ok_env and ok_git and ok_files:
            ok(paint("体检通过：环境满足运行要求", Ansi.GREEN))
            return 0
        fail("体检未通过：请按上面的 ✗ 项处理后重试")
        return 1

    intro()

    if not step_environment():
        return 1
    if not step_git(args.branch, args.force, auto_switch=not args.no_switch):
        return 1
    if not step_integrity():
        return 1
    step_machine()

    python_exe = step_dependencies(args.no_venv, args.reinstall, doctor_only=False)
    if python_exe is None:
        out()
        fail("依赖安装未完成，已中止")
        return 1

    # ── .env ──
    out()
    out(paint("  ── 配置文件 ──", Ansi.BOLD))
    had_env = ENV_FILE.is_file()
    if had_env:
        ok(f".env 已存在（{ENV_FILE.stat().st_size} 字节），不覆盖")
        if env_has_placeholder_key():
            warn(".env 里的 OPENAI_API_KEY 还是占位符 sk-your-key-here")
            hint("它会被判定为「未配置」，请替换成真实密钥")
        if env_values().get("OPENAI_API_KEY"):
            ok("已配置远程模型后端")
    else:
        write_env_stub()
        ok(f"已生成 {ENV_FILE.name}（未填假密钥 —— 空的比假的更能暴露问题）")

    if interactive and not (had_env and env_values().get("OPENAI_API_KEY")):
        interactive_provider_setup()
    elif not interactive:
        hint("非交互模式：跳过模型后端配置")

    # ── 启动 ──
    out()
    out(paint("  ── 启动 Web 控制台 ──", Ansi.BOLD))
    launch = not args.no_launch
    if interactive and launch:
        launch = ask_yes_no("现在就启动 Web 控制台吗？", True)
    if not launch:
        hint(f"稍后手动启动：{venv_python() or Path(sys.executable)} "
             f"-m apps.dsn_ui.server --port {args.port}")
        return 0

    if not port_free(args.port):
        fail(f"端口 {args.port} 已被占用")
        hint(f"换一个端口：python3 installer.py --port {args.port + 1}")
        return 1

    pid, log_path = launch_ui(python_exe, args.port)
    if pid is None:
        fail("启动失败")
        return 1
    info(f"进程 PID {pid}，日志：{log_path.relative_to(ROOT)}")
    if wait_health(args.port):
        ok(paint(f"Web 控制台已就绪 →  http://127.0.0.1:{args.port}", Ansi.GREEN + Ansi.BOLD))
    else:
        warn(f"健康检查超时，但进程可能仍在启动（看 {log_path.relative_to(ROOT)}）")
    out()
    out(paint("  下一步：", Ansi.BOLD))
    out(f"    1. 浏览器打开  http://127.0.0.1:{args.port}")
    out("    2. 右上角「设置 → Provider」接入模型后端")
    out("    3. 在「模型」页签添加本地 GGUF（需要 llama-server）")
    out()
    out(paint(f"  停止控制台：kill {pid}", Ansi.DIM))
    out()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        sys.exit(130)
