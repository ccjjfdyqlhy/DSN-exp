#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wheel_smoke.py —— 发布前的「装出来真的能用」闸门。

## 为什么要有这个闸门

0.6.2 是这个项目栽过的最贵的一次：它**成功发布到了 PyPI**，但那个包里
既没有 console_scripts 入口点（`aicf` 命令不存在），也没有随包分发的评测集
（`aicf eval --dataset basic` 直接找不到文件）。于是 README 上「九十秒上手」
的每一条命令，在每一个真实用户手上都是 command not found。

pip 装到的版本和仓库里的版本不一致，而**没有任何一道门**会发现这件事：
源码树里的测试全绿（测的是源码，不是 wheel），CI 的 build 作业只看
`twine check`（只验元数据，不验内容）。

所以这里补的就是那道缺的门：构建出 wheel，装进一个**全新的虚拟环境**，
然后按 README 的说法去用它 —— 用的不是源码，是真正会被用户装到的那份字节。

## 检查项

1. wheel 里的顶层包只有 `aicf` —— 不许再占用 `harness` / `infra` 这两个
   别人已经用了的名字。
2. `aicf --version` 能跑，且打印的版本与 pyproject 声明的一致。
3. `aicf tool list` 能跑，且真的列出了工具。
4. `aicf eval --dataset basic` 能跑，且**读到了随包分发的数据集**。
5. `from aicf.harness import create_agent, tool` 能 import。

## 用法

    python scripts/wheel_smoke.py --wheel dist/aicf_core-1.0.0-py3-none-any.whl

不传 --wheel 时会自动取 dist/ 里最新的 wheel。退出码 0 = 通过，
非 0 = 阻断（release workflow 会因此拒绝发布）。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


# ── 小工具 ────────────────────────────────────────────────
def _declared_version() -> str:
    """从 pyproject.toml 里读声明的版本（不引第三方依赖）。"""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        raise SystemExit("pyproject.toml 里找不到 version")
    return match.group(1)


def _run(cmd: list[str], cwd: str | None = None, timeout: int = 300) -> tuple[int, str, str]:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr


# ── 各项检查 ──────────────────────────────────────────────
def check_top_level_packages(wheel: Path) -> tuple[bool, str]:
    """wheel 的顶层包必须只有 aicf。

    这条守的是「装一个包，坏三个环境」：顶层多出一个 harness/infra，
    就会和同名包在用户的 site-packages 里打架。
    """
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        tops = sorted({n.split("/")[0] for n in names if not n.startswith("aicf_core")})
        leftovers = [t for t in tops if t not in {"aicf"}]
    if leftovers:
        return False, f"顶层出现了计划外的包：{leftovers}（只允许 aicf）"
    if "aicf" not in tops:
        return False, f"wheel 里没有 aicf 包，顶层是 {tops}"
    return True, f"顶层只有 {tops}"


def check_entry_point(wheel: Path) -> tuple[bool, str]:
    """wheel 必须声明 console_scripts，否则装完没有 aicf 命令。"""
    with zipfile.ZipFile(wheel) as archive:
        entries = [n for n in archive.namelist() if n.endswith("entry_points.txt")]
        if not entries:
            return False, "wheel 里没有 entry_points.txt —— 装完不会有 aicf 命令"
        content = archive.read(entries[0]).decode("utf-8")
    if "console_scripts" not in content:
        return False, f"entry_points.txt 里没有 console_scripts：{content.strip()!r}"
    if not re.search(r"^aicf\s*=", content, re.MULTILINE):
        return False, f"console_scripts 里没有 aicf 条目：{content.strip()!r}"
    return True, "console_scripts 里有 aicf"


def check_datasets_shipped(wheel: Path) -> tuple[bool, str]:
    """评测集必须随包分发 —— README 说它「ships with the package」。"""
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
    datasets = [n for n in names if n.endswith(".yaml") and "datasets/" in n]
    if not datasets:
        return False, "wheel 里没有随包分发的数据集（aicf/harness/datasets/*.yaml）"
    return True, f"随包数据集 {len(datasets)} 个"


def check_installed_cli(venv_python: Path, expected_version: str) -> tuple[bool, str]:
    """在干净虚拟环境里跑 README 上的命令。"""
    exe = venv_python.parent / "aicf"
    if not exe.exists():
        return False, f"装完没有 aicf 命令（{exe} 不存在）"

    code, out, err = _run([str(exe), "--version"])
    if code != 0:
        return False, f"aicf --version 退出码 {code}：{(err or out).strip()[:200]}"
    printed = out.strip()
    if printed != expected_version:
        return False, f"aicf --version 打印 {printed!r}，期望 {expected_version!r}"

    code, out, err = _run([str(exe), "tool", "list"])
    if code != 0:
        return False, f"aicf tool list 退出码 {code}：{(err or out).strip()[:200]}"
    rows = [line for line in out.splitlines() if line.strip()]
    if len(rows) < 2:
        return False, f"aicf tool list 没有列出工具（只有 {len(rows)} 行）"
    if not re.search(r"\beffect\b", out):
        return False, "aicf tool list 的输出里没有 effect 列 —— 工具目录没渲染出来"
    return True, f"aicf tool list 列出了 {len(rows) - 1} 个工具"


def check_eval_dataset(venv_python: Path) -> tuple[bool, str]:
    """aicf eval 必须能读到随包分发的数据集。

    注意：这里只验「跑得起来、数据集读到了」，**不验用例通过**。
    离线桩模型不会调工具，用例本来就该失败；用例通过与否是 CI 评测层的事。
    """
    exe = venv_python.parent / "aicf"
    with tempfile.TemporaryDirectory() as empty:
        code, out, err = _run([str(exe), "eval", "--dataset", "basic", "--traces", empty])
    combined = out + err
    if code not in (0, 1):
        return False, f"aicf eval 异常退出（{code}）：{combined.strip()[:200]}"
    if "basic" not in combined:
        return False, f"aicf eval 的输出里看不到数据集 basic：{combined.strip()[:200]}"
    if "找不到" in combined or "FileNotFoundError" in combined:
        return False, f"aicf eval 没找到随包数据集：{combined.strip()[:200]}"
    return True, "aicf eval 读到了随包数据集 basic"


def check_public_import(venv_python: Path, cwd: Path) -> tuple[bool, str]:
    """README 给的公开 import 路径必须真的能 import。

    同样在中性目录里跑：仓库根目录下 import 会命中源码树，而不是装出来的包。
    """
    code = (
        "from aicf.harness import create_agent, tool;"
        "from aicf.infra.models.base import IChatClient;"
        "import aicf; print(aicf.__version__)"
    )
    code_rc, out, err = _run([str(venv_python), "-c", code], cwd=str(cwd))
    if code_rc != 0:
        return False, f"公开 import 失败：{(err or out).strip()[:300]}"
    return True, f"公开 import 正常（aicf.__version__ = {out.strip()}）"


def check_installed_metadata(venv_python: Path, expected_version: str,
                            cwd: Path) -> tuple[bool, str]:
    """已安装发行版的元数据版本必须与 pyproject 一致。

    注意 cwd：``python -c`` 会把当前目录放进 sys.path[0]。如果这段代码跑在
    仓库根目录，本地构建残留的 ``aicf_core.egg-info``（版本可能是旧的）会
    遮蔽 venv 里真正的 dist-info，读出一个**假的不一致**。闸门会误报，
    误报的闸门等于没有闸门 —— 所以这段必须在一个中性目录里跑。
    """
    code, out, err = _run([
        str(venv_python), "-c",
        "import importlib.metadata as m; print(m.version('aicf-core'))",
    ], cwd=str(cwd))
    if code != 0:
        return False, f"读不到已安装版本：{(err or out).strip()[:200]}"
    installed = out.strip()
    if installed != expected_version:
        return False, f"已安装版本 {installed!r} != 声明版本 {expected_version!r}"
    return True, f"已安装版本 {installed}"


# ── 主流程 ────────────────────────────────────────────────
def pick_wheel(explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit)
        if not path.exists():
            raise SystemExit(f"找不到 wheel：{path}")
        return path
    wheels = sorted((ROOT / "dist").glob("*.whl"), key=lambda p: p.stat().st_mtime)
    if not wheels:
        raise SystemExit("dist/ 里没有 wheel，先构建：python -m build")
    return wheels[-1]


def main() -> int:
    parser = argparse.ArgumentParser(description="发布前的 wheel 冒烟闸门")
    parser.add_argument("--wheel", help="要检查的 wheel；默认取 dist/ 里最新的")
    parser.add_argument("--keep", action="store_true", help="保留临时虚拟环境（调试用）")
    args = parser.parse_args()

    wheel = pick_wheel(args.wheel)
    expected = _declared_version()
    print(f"wheel        : {wheel}")
    print(f"声明版本     : {expected}")
    print("-" * 68)

    failures: list[str] = []

    # ① 不装就能查的部分（快，先查）
    for name, fn in [
        ("顶层包只有 aicf", lambda: check_top_level_packages(wheel)),
        ("console_scripts 入口点", lambda: check_entry_point(wheel)),
        ("评测集随包分发", lambda: check_datasets_shipped(wheel)),
    ]:
        ok, detail = fn()
        print(f"{'PASS' if ok else 'FAIL'}  {name:<24} {detail}")
        if not ok:
            failures.append(f"{name}：{detail}")

    # ② 装进干净环境再查（慢，但才是用户看到的东西）
    tmpdir = tempfile.mkdtemp(prefix="aicf-wheel-smoke-")
    venv_dir = Path(tmpdir) / "venv"
    print("-" * 68)
    print(f"创建干净虚拟环境：{venv_dir}")
    code, out, err = _run([sys.executable, "-m", "venv", str(venv_dir)], timeout=300)
    if code != 0:
        print(f"FAIL  创建虚拟环境失败：{(err or out).strip()[:300]}")
        return 1
    venv_python = venv_dir / "bin" / "python"
    if not venv_python.exists():
        venv_python = venv_dir / "Scripts" / "python.exe"

    print(f"安装 wheel：{wheel.name}")
    code, out, err = _run(
        [str(venv_python), "-m", "pip", "install", "--quiet", "--upgrade", "pip"],
        timeout=600,
    )
    code, out, err = _run(
        [str(venv_python), "-m", "pip", "install", "--quiet", str(wheel)], timeout=900
    )
    if code != 0:
        print(f"FAIL  安装 wheel 失败：{(err or out).strip()[-800:]}")
        return 1
    print("-" * 68)

    # 中性工作目录：既不是仓库根（那里有源码树和本地 egg-info），
    # 也不是用户目录 —— 闸门要验的是「装出来的包」，不是「当前目录里的东西」。
    neutral = Path(tmpdir) / "workdir"
    neutral.mkdir(parents=True, exist_ok=True)

    for name, fn in [
        ("已安装版本一致", lambda: check_installed_metadata(venv_python, expected, neutral)),
        ("aicf --version / tool list", lambda: check_installed_cli(venv_python, expected)),
        ("aicf eval 能读随包数据集", lambda: check_eval_dataset(venv_python)),
        ("公开 import 路径", lambda: check_public_import(venv_python, neutral)),
    ]:
        ok, detail = fn()
        print(f"{'PASS' if ok else 'FAIL'}  {name:<24} {detail}")
        if not ok:
            failures.append(f"{name}：{detail}")

    print("-" * 68)
    if failures:
        print(f"✗ 闸门未通过（{len(failures)} 项）：")
        for item in failures:
            print(f"   - {item}")
        print("   修好再发布。这个闸门存在的理由：0.6.2 就是带着这些缺陷发到 PyPI 的。")
        return 1
    print("✓ 闸门通过：装出来的 wheel 能按 README 的说法用。")

    if not args.keep:
        subprocess.run(["rm", "-rf", str(tmpdir)], check=False)
    else:
        print(f"临时环境保留在：{tmpdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
