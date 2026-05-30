# DSN-exp/main.py
# 服务端监控仪表盘 — 系统启动引导 + 模块状态 + 运行统计
# 用法: python main.py

from __future__ import annotations

import sys
import time
import signal
import logging
import threading
from datetime import datetime
from dataclasses import dataclass
from typing import Any
from collections import deque

try:
    import msvcrt
    _HAS_MSVCRT = True
except ImportError:
    _HAS_MSVCRT = False

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
# 系统状态 & 日志缓冲区
# ═══════════════════════════════════════════════════════════════

SYSTEM_STATUS = "待命"
SYSTEM_STATUS_COLORS = {
    "待命":       "green",
    "处理请求":   "bold yellow",
    "出现问题":   "bold red",
}
SYSTEM_STATUS_ICONS = {
    "待命":       "●",
    "处理请求":   "◉",
    "出现问题":   "◉",
}

LOG_BUFFER: deque = deque(maxlen=200)
LOG_LOCK = threading.Lock()
_current_page = 0  # 0 = dashboard, 1 = logs
_PAGE_LOCK = threading.Lock()
_LOG_HANDLER_INSTALLED = False


def set_system_status(status: str):
    global SYSTEM_STATUS
    if status in SYSTEM_STATUS_COLORS:
        SYSTEM_STATUS = status


def append_log(module: str, level: str, message: str):
    ts = datetime.now().strftime("%H:%M:%S")
    with LOG_LOCK:
        LOG_BUFFER.append((ts, module, level, message))


def get_logs_snapshot() -> list:
    with LOG_LOCK:
        return list(LOG_BUFFER)


def get_current_page() -> int:
    with _PAGE_LOCK:
        return _current_page


def set_current_page(page: int):
    global _current_page
    with _PAGE_LOCK:
        _current_page = page


def _install_log_handler():
    global _LOG_HANDLER_INSTALLED
    if _LOG_HANDLER_INSTALLED:
        return
    _LOG_HANDLER_INSTALLED = True

    class _DashboardHandler(logging.Handler):
        def emit(self, record):
            append_log(record.name, record.levelname, self.format(record))

    handler = _DashboardHandler()
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logging.root.addHandler(handler)

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
            if pe and pe.personality_v2:
                pv2 = pe.personality_v2
                presets = pv2.list_presets()
                d["persona_preset"] = presets[0]["display_name"] if presets else "default"
                d["persona_mood"] = "v2"
                d["persona_intimacy"] = f"{len(presets)} presets"
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
    layout.split(Layout(name="header", size=5),
                 Layout(name="body"),
                 Layout(name="footer", size=3))
    layout["body"].split_row(Layout(name="left", ratio=2), Layout(name="right", ratio=2))
    layout["right"].split(Layout(name="right_stats"), Layout(name="right_server"))

    status = SYSTEM_STATUS
    status_color = SYSTEM_STATUS_COLORS.get(status, "white")
    status_icon = SYSTEM_STATUS_ICONS.get(status, "●")
    status_bar = Text()
    status_bar.append(f"  {status_icon}  ", style=f"{status_color}")
    status_bar.append(f"{status}  ", style=f"bold {status_color} on black")
    header_inner = Group(
        Align.center(Text(title, style="bold cyan")),
        Align.center(status_bar),
    )
    layout["header"].update(Panel(
        header_inner,
        box=box.HEAVY, border_style="cyan"))
    layout["left"].update(_make_component_panel(components))
    layout["right_stats"].update(_make_stats_panel(stats))
    layout["right_server"].update(_make_server_panel(config))

    host = getattr(config, 'SERVER_HOST', '0.0.0.0')
    port = getattr(config, 'SERVER_PORT', 5000)
    layout["footer"].update(Panel(
        Align.center(Text(f"Tab 切换页面  |  Ctrl+C 退出  |  http://{host}:{port}/api/  |  DSN-exp v4", style="dim"), vertical="middle"),
        box=box.SIMPLE, border_style="dim"))
    return layout


_console_handler = None
_console_handler_lock = threading.Lock()


def _enable_console_logging():
    global _console_handler
    with _console_handler_lock:
        if _console_handler is not None:
            return
        _console_handler = logging.StreamHandler(sys.stderr)
        _console_handler.setLevel(logging.INFO)
        _console_handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            "%H:%M:%S"))
        logging.root.addHandler(_console_handler)


def _disable_console_logging():
    global _console_handler
    with _console_handler_lock:
        if _console_handler is not None:
            logging.root.removeHandler(_console_handler)
            _console_handler = None


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

    _install_log_handler()
    append_log("system", "INFO", "DSN-exp 系统启动完成，仪表盘已激活")
    set_system_status("待命")

    def _dashboard_refresh():
        return build_dashboard(components, data.snapshot(), Config,
                               "DSN-exp  System Dashboard")

    def _shutdown(sig, frame):
        _disable_console_logging()
        console.print("\n[yellow]Shutting down...[/]")
        if server:
            server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    keyboard_stop = threading.Event()
    page_changed = threading.Event()

    def _keyboard_listener():
        if not _HAS_MSVCRT:
            return
        while not keyboard_stop.is_set():
            try:
                if msvcrt.kbhit():
                    ch = msvcrt.getch()
                    if ch == b'\t':
                        new_page = 1 if get_current_page() == 0 else 0
                        set_current_page(new_page)
                        page_changed.set()
                        page_name = "面板" if new_page == 0 else "日志"
                        append_log("system", "INFO", f"切换到{page_name}页面")
                    elif ch == b'1':
                        set_current_page(0)
                        set_system_status("待命")
                        page_changed.set()
                        append_log("system", "INFO", "系统状态切换为: 待命")
                    elif ch == b'2':
                        set_system_status("处理请求")
                        append_log("system", "INFO", "系统状态切换为: 处理请求")
                    elif ch == b'3':
                        set_system_status("出现问题")
                        append_log("system", "WARNING", "系统状态手动切换为: 出现问题")
            except Exception:
                pass
            time.sleep(0.05)

    kb_thread = threading.Thread(target=_keyboard_listener, daemon=True, name="kb-listener")
    kb_thread.start()

    console.print("[green]All systems ready. Dashboard active.[/]")
    console.print("[dim]  Tab  切换 面板/日志  |  1/2/3 切换系统状态  |  Ctrl+C 退出[/]\n")

    def _run_live_loop():
        with Live(_dashboard_refresh(), refresh_per_second=2, screen=True) as live:
            page_changed.clear()
            while not page_changed.is_set():
                time.sleep(0.5)
                live.update(_dashboard_refresh())

    def _run_console_log_loop():
        _enable_console_logging()
        print(f"=== DSN-exp Module Logs ===  Status: {SYSTEM_STATUS}  [Tab=return, Ctrl+C=quit] ===")
        print("-" * 70)
        page_changed.clear()
        try:
            while not page_changed.is_set():
                time.sleep(0.5)
        finally:
            _disable_console_logging()

    try:
        while True:
            page = get_current_page()
            if page == 0:
                _run_live_loop()
            else:
                _run_console_log_loop()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted. Shutting down...[/]")
    except Exception as e:
        console.print(f"\n[red]Dashboard error: {e}[/]")
    finally:
        keyboard_stop.set()
        _disable_console_logging()
        try:
            if server:
                server.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()
