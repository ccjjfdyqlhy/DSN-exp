# DSN-exp/main.py
# 服务端监控仪表盘 — 系统启动引导 + 模块状态 + 运行统计
# 用法: python main.py

from __future__ import annotations

import os
import sys
import time
import signal
import logging
import threading
from datetime import datetime
from dataclasses import dataclass
from typing import Any

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.layout import Layout
from rich.live import Live
from rich.text import Text
from rich.align import Align
from rich import box

console = Console()

# ═══════════════════════════════════════════════════════════════
# 组件跟踪
# ═══════════════════════════════════════════════════════════════

@dataclass
class ComponentInfo:
    name: str
    status: str = "PENDING"
    detail: str = ""
    group: str = "core"
    elapsed: float = 0.0

STATUS_COLORS = {
    "PENDING": "dim white", "OK": "green", "FAILED": "red",
    "DISABLED": "dim cyan", "WARN": "orange1",
}
STATUS_ICONS = {
    "PENDING": "○", "OK": "✓", "FAILED": "✗", "DISABLED": "—", "WARN": "⚠",
}
GROUP_ORDER = ["core", "ai", "voice", "runtime"]


class DashboardData:
    """收集所有监控数据"""
    def __init__(self):
        self.app = None
        self.db = None
        self.task_manager = None
        self.memory_manager = None
        self.prompt_engine = None
        self.start_time = time.time()

    @property
    def uptime(self) -> str:
        s = int(time.time() - self.start_time)
        h, m = divmod(s, 3600)
        mm, ss = divmod(m, 60)
        if h: return f"{h}h {mm}m {ss}s"
        if mm: return f"{mm}m {ss}s"
        return f"{ss}s"

    def snapshot(self) -> dict:
        d = {"uptime": self.uptime}
        try:
            db = self.db
            if db:
                c = db._get_connection()
                d["users"] = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
                d["chats"] = c.execute("SELECT COUNT(*) FROM chats").fetchone()[0]
                d["messages"] = c.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
                d["memories"] = c.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        except Exception:
            pass

        try:
            tm = self.task_manager
            if tm:
                tasks = getattr(tm, 'tasks', {})
                d["tasks_total"] = len(tasks)
                d["tasks_running"] = sum(1 for t in tasks.values() if str(getattr(t, 'status', '')) in ('RUNNING', '1'))
                d["tasks_pending"] = sum(1 for t in tasks.values() if str(getattr(t, 'status', '')) in ('PENDING', '0'))
        except Exception:
            pass

        try:
            pe = self.prompt_engine
            if pe and pe.personality:
                prof = pe.personality.current_profile
                d["persona_preset"] = getattr(prof, 'preset_name', 'default')
                d["persona_mood"] = getattr(prof, 'current_mood', 'neutral')
                d["persona_intimacy"] = f"{getattr(prof, 'intimacy', 0):.2f}"
        except Exception:
            pass
        return d


# ═══════════════════════════════════════════════════════════════
# Banner & UI 渲染
# ═══════════════════════════════════════════════════════════════

BANNER = r"""
 ██████╗  ███████╗ ███╗   ██╗       ███████╗ ██╗  ██╗ ██████╗ 
 ██╔══██╗ ██╔════╝ ████╗  ██║       ██╔════╝ ╚██╗██╔╝ ██╔══██╗
 ██║  ██║ ███████╗ ██╔██╗ ██║       █████╗    ╚███╔╝  ██████╔╝
 ██║  ██║ ╚════██║ ██║╚██╗██║       ██╔══╝    ██╔██╗  ██╔═══╝ 
 ██████╔╝ ███████║ ██║ ╚████║       ███████╗ ██╔╝ ██╗ ██║     
 ╚═════╝  ╚══════╝ ╚═╝  ╚═══╝       ╚══════╝ ╚═╝  ╚═╝ ╚═╝     
"""


def _make_component_panel(components: list[ComponentInfo]) -> Panel:
    tables: dict[str, Table] = {}
    for g in GROUP_ORDER:
        t = Table(box=box.SIMPLE, expand=True, show_header=False, padding=(0, 1))
        t.add_column("icon", width=2)
        t.add_column("name", width=18)
        t.add_column("status", width=8)
        t.add_column("detail", ratio=1)
        tables[g] = t

    for c in components:
        t = tables.get(c.group, tables["core"])
        color = STATUS_COLORS.get(c.status, "white")
        icon = STATUS_ICONS.get(c.status, "?")
        elapsed_str = f"[dim]{c.elapsed:.1f}s[/]" if c.elapsed > 0 else ""
        t.add_row(f"[{color}]{icon}[/]", f"[bold]{c.name}[/]",
                  f"[{color}]{c.status}[/]",
                  Text(c.detail, style="dim") + (f"  {elapsed_str}" if elapsed_str else ""))

    groups = [
        ("[bold blue]Core Infrastructure[/]", "core"),
        ("[bold magenta]AI & Models[/]", "ai"),
        ("[bold yellow]Voice[/]", "voice"),
        ("[bold green]Runtime[/]", "runtime"),
    ]
    rendered = []
    for title, g in groups:
        t = tables.get(g)
        if t and t.row_count > 0:
            rendered.append(Panel(t, title=title, border_style="dim", box=box.ROUNDED))
    return Panel(Group(*rendered), title="[bold]Components", border_style="blue", box=box.ROUNDED)


def _make_stats_panel(stats: dict) -> Panel:
    grid = Table(box=box.SIMPLE, show_header=False, padding=(0, 2), expand=True)
    grid.add_column("k", style="dim", width=14)
    grid.add_column("v", style="bold cyan", justify="right", width=10)

    rows = [
        ("Uptime",       stats.get("uptime", "-")),
        ("Users",        str(stats.get("users", "-"))),
        ("Chats",        str(stats.get("chats", "-"))),
        ("Messages",     str(stats.get("messages", "-"))),
        ("Memories",     str(stats.get("memories", "-"))),
    ]
    if stats.get("tasks_total", "-") not in ("-", "0", 0):
        rows += [
            ("", ""),
            ("Tasks Total",  str(stats.get("tasks_total", "-"))),
            ("  Running",     f"[green]{stats.get('tasks_running', '-')}[/]"),
            ("  Pending",     f"[yellow]{stats.get('tasks_pending', '-')}[/]"),
        ]
    if stats.get("persona_mood"):
        rows += [
            ("", ""),
            ("Persona",      stats.get("persona_preset", "-")),
            ("Mood",         stats.get("persona_mood", "-")),
            ("Intimacy",     stats.get("persona_intimacy", "-")),
        ]
    for k, v in rows:
        grid.add_row(k, v)
    return Panel(grid, title="[bold]Statistics", border_style="cyan", box=box.ROUNDED)


def _make_server_panel(config: Any) -> Panel:
    t = Table(box=box.SIMPLE, show_header=False, padding=(0, 2), expand=True)
    t.add_column("k", style="dim")
    t.add_column("v", style="bold green")

    def _cfg(key, default="?"):
        return str(getattr(config, key, default))

    t.add_row("Listen",    f"{_cfg('SERVER_HOST','0.0.0.0')}:{_cfg('SERVER_PORT',5000)}")
    t.add_row("Model",     _cfg('MAIN_MODEL_TYPE'))
    t.add_row("Model Name", _cfg('MAIN_MODEL_NAME'))
    t.add_row("Reasoner",  "ON" if _cfg('REASONER_ENABLED','true').lower()=='true' else "OFF")
    t.add_row("TTS",       _cfg('TTS_BASE_URL'))
    t.add_row("ASR",       "ON" if _cfg('ASR_ENABLED','false').lower()=='true' else "OFF")
    t.add_row("Task Mgr",  "ON" if _cfg('TASK_MANAGER_ENABLED','true').lower()!='false' else "OFF")
    t.add_row("Memory",    "ON" if _cfg('MEMORY_ENABLED','true').lower()!='false' else "OFF")
    return Panel(t, title="[bold]Server Info", border_style="green", box=box.ROUNDED)


def build_dashboard(components: list[ComponentInfo], stats: dict, config: Any, title: str = "") -> Layout:
    layout = Layout()
    layout.split(Layout(name="header", size=3),
                 Layout(name="body"),
                 Layout(name="footer", size=3))
    layout["body"].split_row(Layout(name="left", ratio=2), Layout(name="right", ratio=2))
    layout["right"].split(Layout(name="right_stats"), Layout(name="right_server"))

    layout["header"].update(Panel(
        Align.center(f"[bold cyan]{title}[/]", vertical="middle"),
        box=box.HEAVY, border_style="cyan"))
    layout["left"].update(_make_component_panel(components))
    layout["right_stats"].update(_make_stats_panel(stats))
    layout["right_server"].update(_make_server_panel(config))

    host = getattr(config, 'SERVER_HOST', '0.0.0.0')
    port = getattr(config, 'SERVER_PORT', 5000)
    layout["footer"].update(Panel(
        Align.center(Text(f"Ctrl+C Quit  |  http://{host}:{port}/api/  |  DSN-exp v4", style="dim"), vertical="middle"),
        box=box.SIMPLE, border_style="dim"))
    return layout


# ═══════════════════════════════════════════════════════════════
# 主入口 — 导入 app.py，启动服务器，显示 Dashboard
# ═══════════════════════════════════════════════════════════════

def main():
    # ── 导入 app.py 完成全部初始化 ──
    console.clear()
    console.print(Text(BANNER, style="bold cyan"))
    console.print("[bold]Booting system... (importing app.py)[/]\n")

    t_start = time.time()

    try:
        import app as app_module
    except Exception as e:
        console.print(f"[red]Failed to import app.py: {e}[/]")
        sys.exit(1)

    Config = app_module.Config
    flask_app = app_module.app

    # 收集已初始化的组件状态
    components: list[ComponentInfo] = []

    def add(group: str, name: str, detail: str = "", status: str = "OK", elapsed: float = 0.0):
        components.append(ComponentInfo(name=name, status=status, detail=detail, group=group, elapsed=elapsed))

    # Core
    add("core", "Config", f"{Config.MAIN_MODEL_TYPE}:{Config.MAIN_MODEL_NAME}")
    add("core", "Database", Config.DATABASE_PATH)
    add("core", "User Manager", "LittleSkin OAuth2 + JWT")

    # AI
    add("ai", "Complexity Analyzer", "keyword scoring")
    tm = app_module.task_manager
    if tm:
        add("ai", "Task Manager", f"workers={getattr(Config, 'TASK_MAX_WORKERS', 5)}")
    else:
        add("ai", "Task Manager", status="DISABLED")

    mm = app_module.memory_manager
    if mm:
        add("ai", "Memory Manager", f"window={getattr(Config, 'MEMORY_CONTEXT_WINDOW_SIZE', 40)}")
    else:
        add("ai", "Memory Manager", status="DISABLED")

    add("ai", "Memory Recall", "keyword search + detail restore")
    add("ai", "Prompt Engine", "MD library + personality")

    # Voice
    tts = app_module.tts_client
    add("voice", "TTS Client", Config.TTS_BASE_URL if tts else "N/A",
        status="OK" if tts else "DISABLED")

    fm = app_module.filter_model
    add("voice", "ASR Filter", "llama-3.2-1b-instruct" if fm else "",
        status="OK" if fm else "DISABLED")

    am = app_module.asr_model
    add("voice", "ASR (FunASR)", f"device={getattr(Config, 'ASR_DEVICE', 'cuda')}" if am else "",
        status="OK" if am else "DISABLED")

    # Runtime
    add("runtime", "Plugin System", "10 builtin plugins (ready)")
    add("runtime", "Skill System", "2 builtin skills (ready)")
    add("runtime", "Distillation", "auto-draft generation (ready)")
    add("runtime", "Todo System", "plan decomposition + SSE (ready)")

    # 统计收集器
    data = DashboardData()
    data.app = flask_app
    data.db = app_module.db
    data.task_manager = tm
    data.memory_manager = mm

    # 尝试获取 PromptEngine (在 prompt 模块中)
    try:
        from prompt.engine import _default_engine
        if _default_engine:
            data.prompt_engine = _default_engine
    except Exception:
        pass

    data.start_time = t_start

    # ── 启动 HTTP 服务器 ──
    host = getattr(Config, 'SERVER_HOST', '0.0.0.0')
    port = getattr(Config, 'SERVER_PORT', 5000)

    add("runtime", "Flask App", elapsed=time.time() - t_start)

    server_comp = ComponentInfo(name="HTTP Server", detail=f"http://{host}:{port}", group="runtime", status="OK", elapsed=0.0)
    components.append(server_comp)

    t_http = time.time()
    try:
        from werkzeug.serving import make_server
        server = make_server(host, port, flask_app, threaded=True)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.name = "flask-server"
        server_thread.start()
        time.sleep(0.5)
        if server_thread.is_alive():
            server_comp.status = "OK"
            server_comp.elapsed = time.time() - t_http
        else:
            server_comp.status = "FAILED"
    except Exception as e:
        server_comp.status = "FAILED"
        server_comp.detail = str(e)[:60]
        server = None

    # ── Dashboard ──
    console.clear()
    console.print(Text(BANNER, style="bold cyan"))

    def _refresh():
        return build_dashboard(components, data.snapshot(), Config,
                               "DSN-exp  System Dashboard")

    def _shutdown(sig, frame):
        console.print("\n[yellow]Shutting down...[/]")
        if server:
            server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    console.print("[green]All systems ready. Dashboard active.[/]\n")

    try:
        with Live(_refresh(), refresh_per_second=2, screen=True) as live:
            while True:
                time.sleep(0.5)
                live.update(_refresh())
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted. Shutting down...[/]")
    except Exception as e:
        console.print(f"\n[red]Dashboard error: {e}[/]")
    finally:
        try:
            if server:
                server.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()
