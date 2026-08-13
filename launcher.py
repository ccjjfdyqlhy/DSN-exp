# launcher.py
# DSN-exp Harness 应用启动器。
#
# 项目根目录由 harness 框架代码占领；具体应用以 AppBundle / App 包形式
# 存在于 apps/ 下。本启动器负责"选择并运行"某个应用。
#
# 入口选择优先级:
#   1. 启动参数  --app <name>
#   2. 配置文件  apps.yaml（{app: {entry: "apps.foo.entry", description: ...}}）
#   3. 环境变量  DSN_APP=<name>
#   4. 默认      dsn
#
# 约定: 应用包 apps/<name>/ 提供 entry 模块，含 main() 可调用对象。

from __future__ import annotations

import argparse
import importlib
import os
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent
APPS_CONFIG = ROOT / "apps.yaml"

_DEFAULT_APP = "dsn"

# 应用清单（若存在 apps.yaml 则以其覆盖）
APPS: dict[str, dict[str, Any]] = {
    "dsn": {
        "entry": "apps.dsn.entry",
        "description": "DSN 语音陪伴应用（默认）",
        "default": True,
    },
    "coding_agent": {
        "entry": "apps.coding_agent.entry",
        "description": "基于 harness 的 coding agent 示例",
    },
    "text_agent": {
        "entry": "apps.text_agent.entry",
        "description": "harness 参考应用（纯文本 agent）",
    },
}


def load_apps_config() -> None:
    if APPS_CONFIG.exists():
        try:
            import yaml
            data = yaml.safe_load(APPS_CONFIG.read_text(encoding="utf-8")) or {}
            for name, cfg in data.items():
                if isinstance(cfg, dict):
                    cfg.setdefault("entry", f"apps.{name}.entry")
                    APPS.setdefault(name, cfg)
        except Exception:  # noqa: BLE001
            pass


def resolve_entry(name: str) -> Callable[[], Any]:
    cfg = APPS.get(name)
    if cfg is None:
        raise SystemExit(
            f"未知应用: {name!r}\n可用: {', '.join(sorted(APPS))}")
    module_name = cfg["entry"]
    mod = importlib.import_module(module_name)
    return getattr(mod, "main")


def list_apps() -> str:
    lines = []
    for name, cfg in sorted(APPS.items()):
        marker = " *" if cfg.get("default") else ""
        lines.append(f"  {name:<14}{marker}  {cfg.get('description', '')}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    load_apps_config()
    parser = argparse.ArgumentParser(
        prog="dsn-harness",
        description="DSN-exp Harness 应用启动器 — 默认启动 DSN 语音陪伴应用。",
    )
    parser.add_argument("--app", default=None,
                        help="要启动的应用名（默认 dsn，可用 DSN_APP 环境变量覆盖）")
    parser.add_argument("--list", action="store_true", help="列出可用应用")
    parser.add_argument("app_args", nargs="*", help="透传给应用的参数")
    args = parser.parse_args(argv)

    if args.list:
        print(list_apps())
        return

    name = args.app or os.environ.get("DSN_APP") or _DEFAULT_APP
    sys.argv = [sys.argv[0]] + args.app_args
    entry = resolve_entry(name)
    entry()


if __name__ == "__main__":
    main()
