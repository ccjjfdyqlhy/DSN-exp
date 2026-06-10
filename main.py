# DSN-exp/main.py
# 服务端启动引导 — 日志输出 + 命令行交互
# 用法: python main.py

from __future__ import annotations

import sys
import time
import signal
import logging
import threading
from datetime import datetime
from collections import deque

from rich.console import Console
from rich.text import Text
from rich.table import Table
from rich import box

console = Console()

LOG_BUFFER: deque = deque(maxlen=200)
LOG_LOCK = threading.Lock()
_LOG_HANDLER_INSTALLED = False


def append_log(module: str, level: str, message: str):
    ts = datetime.now().strftime("%H:%M:%S")
    with LOG_LOCK:
        LOG_BUFFER.append((ts, module, level, message))


def get_logs_snapshot() -> list:
    with LOG_LOCK:
        return list(LOG_BUFFER)


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


BANNER = r"""
 ██████╗  ███████╗ ███╗   ██╗       ███████╗ ██╗  ██╗ ██████╗
 ██╔══██╗ ██╔════╝ ████╗  ██║       ██╔════╝ ╚██╗██╔╝ ██╔══██╗
 ██║  ██║ ███████╗ ██╔██╗ ██║       █████╗    ╚███╔╝  ██████╔╝
 ██║  ██║ ╚════██║ ██║╚██╗██║       ██╔══╝    ██╔██╗  ██╔═══╝
 ██████╔╝ ███████║ ██║ ╚████║       ███████╗ ██╔╝ ██╗ ██║
 ╚═════╝  ╚══════╝ ╚═╝  ╚═══╝       ╚══════╝ ╚═╝  ╚═╝ ╚═╝
"""

# ── 命令处理 ──

def _cmd_newbind(auth_manager):
    """生成新配对码"""
    if not auth_manager:
        print("  错误: AuthManager 不可用")
        return
    if auth_manager.pairing.is_active():
        print("  已存在未使用的配对码，先使用或等待过期后再生成")
        return
    code = auth_manager.pairing.generate()
    append_log("system", "INFO", f"管理员生成新配对码: {code}")
    print(f"\n  {'='*50}")
    print(f"  新配对码: {code}")
    print(f"  有效期: {getattr(auth_manager.pairing, '_timeout', 300) // 60} 分钟")
    print(f"  请在 webUI 中完成配对")
    print(f"  {'='*50}\n")


def _cmd_users(auth_manager, db):
    """列出所有注册用户"""
    if not auth_manager:
        print("  错误: AuthManager 不可用")
        return
    users = auth_manager.list_users()
    if not users:
        print("  暂无注册用户")
        return

    table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    table.add_column("UID", style="dim")
    table.add_column("显示名", style="bold")
    table.add_column("管理员")
    table.add_column("注册时间", style="dim")

    try:
        conn = db._get_connection()
        for u in users:
            row = conn.execute(
                "SELECT created_at FROM users WHERE uid = ?", (u["uid"],)
            ).fetchone()
            created_at = row["created_at"] if row else "-"
            table.add_row(
                str(u["uid"]),
                u["display_name"],
                "Y" if u.get("is_admin") else "",
                created_at,
            )
    except Exception:
        for u in users:
            table.add_row(
                str(u["uid"]),
                u["display_name"],
                "Y" if u.get("is_admin") else "",
                "-",
            )

    console.print(table)


def _cmd_status(auth_manager, db):
    """显示服务器状态摘要"""
    print("\n  --- 服务器状态 ---")
    _cmd_users(auth_manager, db)

    if db:
        try:
            conn = db._get_connection()
            chats = conn.execute(
                "SELECT COUNT(*) FROM chats WHERE chat_name != '__steward__'"
            ).fetchone()[0]
            msgs = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            sessions = conn.execute(
                "SELECT COUNT(*) FROM auth_sessions WHERE revoked = 0 AND expires_at > datetime('now')"
            ).fetchone()[0]
            print(f"  总聊天数: {chats}  总消息数: {msgs}  活跃会话: {sessions}")
        except Exception:
            pass

    if auth_manager and auth_manager.pairing.is_active():
        print("  [配对码] 存在未使用的配对码")


def _cmd_help():
    """显示帮助信息"""
    print("""
  可用命令 (必须以 / 开头):
    /newbind   生成新的设备配对码
    /users     列出所有注册用户
    /status    显示服务器状态摘要
    /help      显示此帮助信息

  其他输入将被转发给驻守模型 (如果已启用)。
""")


def _execute_command(line, auth_manager, db):
    """解析并执行命令"""
    parts = line.split(maxsplit=1)
    cmd = parts[0].lower()

    if cmd == "/newbind":
        _cmd_newbind(auth_manager)
    elif cmd == "/users":
        _cmd_users(auth_manager, db)
    elif cmd == "/status":
        _cmd_status(auth_manager, db)
    elif cmd == "/help":
        _cmd_help()
    else:
        print(f"  未知命令: {cmd}，输入 /help 查看可用命令")


# ── 主入口 ──

def main():
    console.print(Text(BANNER, style="bold cyan"))
    console.print("[bold]Booting system... (importing app.py)[/]\n")

    try:
        import app as app_module
    except Exception as e:
        console.print(f"[red]Failed to import app.py: {e}[/]")
        sys.exit(1)

    Config = app_module.Config
    flask_app = app_module.app
    auth_manager = flask_app.config.get("AUTH_MANAGER")
    db = app_module.db

    # ── 启动提示（替代旧自动配对码） ──
    try:
        if auth_manager and auth_manager._user_count() == 0:
            console.print(
                "[yellow]  首次启动: 在控制台输入 [bold]/newbind[/] 生成配对码[/]\n"
            )
    except Exception:
        pass

    # ── 启动 HTTP 服务器 ──
    host = getattr(Config, "SERVER_HOST", "0.0.0.0")
    port = getattr(Config, "SERVER_PORT", 5000)

    server = None
    try:
        from werkzeug.serving import make_server
        server = make_server(host, port, flask_app, threaded=True)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.name = "flask-server"
        server_thread.start()
        time.sleep(0.5)
    except Exception as e:
        console.print(f"[red]Failed to start HTTP server: {e}[/]")

    # ── 驻守模型 ──
    steward = None
    if getattr(Config, "STEWARD_ENABLED", True):
        try:
            from stationed import StewardModel
            steward = StewardModel(Config)
            console.print(
                "[green]驻守模型就绪[/] "
                f"({getattr(Config, 'STEWARD_MODEL_TYPE', 'deepseek')}:"
                f"{getattr(Config, 'STEWARD_MODEL_NAME', 'deepseek-v4-flash')})"
            )
            append_log("system", "INFO", "驻守模型已就绪")
        except Exception as e:
            console.print(f"[yellow]驻守模型初始化失败: {e}[/]")

    # ── 日志 ──
    _install_log_handler()
    append_log("system", "INFO", "DSN-exp 系统启动完成")

    _shutdown_flag = threading.Event()

    def _sigterm_handler(sig, frame):
        _shutdown_flag.set()

    signal.signal(signal.SIGTERM, _sigterm_handler)

    console.print(f"[green]Server started.[/]")
    console.print(
        "[dim]  "
        f"http://{host}:{port}/api/  |  /help  |  Ctrl+C 退出"
        "[/]"
    )

    _enable_console_logging()
    print(f"=== DSN-exp Module Logs ===  http://{host}:{port}/api/  [/help | Ctrl+C=quit] ===")
    print("-" * 70)

    def _handle_steward_chat(text):
        if steward is None or not steward.enabled:
            print("[驻守模型未启用，输入 /help 查看可用命令]")
            return
        try:
            reply = steward.chat(text, auth_manager, db)
            print(f"\n[GUARD] {reply}\n")
            append_log("Steward", "INFO", f"用户: {text[:60]}... -> {reply[:60]}...")
        except Exception as e:
            print(f"\n[驻守模型错误] {e}\n")

    try:
        while not _shutdown_flag.is_set():
            try:
                line = sys.stdin.readline()
            except (EOFError, OSError):
                _shutdown_flag.set()
                break

            if not line:
                time.sleep(0.1)
                continue

            line = line.strip()
            if not line:
                continue

            if line.startswith("/"):
                _execute_command(line, auth_manager, db)
            else:
                _handle_steward_chat(line)

    except KeyboardInterrupt:
        pass
    except Exception as e:
        console.print(f"\n[red]Error: {e}[/]")
    finally:
        _disable_console_logging()
        try:
            if server:
                server.shutdown()
        except Exception:
            pass
        console.print("\n[yellow]Shutting down...[/]")


if __name__ == "__main__":
    main()
