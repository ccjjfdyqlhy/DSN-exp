# DSN-exp/main.py
# 服务端启动引导 — 日志输出 + 命令行交互
# 用法: python main.py

from __future__ import annotations

import os
import sys
import time
import signal
import shutil
import logging
import threading
from pathlib import Path
from datetime import datetime, timedelta
from collections import deque

from tasks import TaskManager, TaskStatus, TaskType

# ── 首次启动检测：必须在任何可能触发 config.py 的 import 之前执行 ──
_ENV_PATH = Path(__file__).parent / ".env"


def _is_env_configured() -> bool:
    if not _ENV_PATH.exists():
        return False
    try:
        with open(_ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped.startswith("#") or "=" not in stripped:
                    continue
                k, v = stripped.split("=", 1)
                if k.strip().upper() == "DEEPSEEK_API_KEY":
                    val = v.strip()
                    return bool(val and val != "sk-your-key-here")
    except Exception:
        return False
    return False


if not _is_env_configured():
    print("\n  ⚠ 检测到未配置状态，进入引导流程...\n")
    try:
        from onboarding import run as run_onboarding
        success = run_onboarding()
    except ImportError as e:
        print(f"\n  ❌ 无法加载引导模块: {e}")
        sys.exit(1)
    if not success:
        print("\n  配置未完成，退出。")
        sys.exit(0)
    print("\n  ✓ 配置完成，正在启动完整系统...\n")


from rich.console import Console
from rich.text import Text
from rich.table import Table
from rich import box

try:
    from prompt.personality_v3.traits import TRAIT_MAP
    _TRAIT_NAMES: dict[str, str] = {t.tid: t.name for t in TRAIT_MAP.values()}
except ImportError:
    _TRAIT_NAMES = {}

try:
    from plugins.base import AsyncPlugin
except ImportError:
    AsyncPlugin = None

console = Console()

LOG_BUFFER: deque = deque(maxlen=200)
LOG_LOCK = threading.Lock()
_LOG_HANDLER_INSTALLED = False

_server_start_time = None
_engine = None  # DSNEngine 实例，供 memory/index 等命令使用

_ENV_PATH = Path(__file__).parent / ".env"
_MAX_ENV_BACKUPS = 3


def _env_backup_rotate():
    """轮转备份: .env → .env.bak.0, .env.bak.0 → .env.bak.1, ..."""
    for i in range(_MAX_ENV_BACKUPS - 1, -1, -1):
        src = _ENV_PATH.parent / f".env.bak.{i}"
        dst = _ENV_PATH.parent / f".env.bak.{i + 1}"
        if src.exists():
            if dst == _ENV_PATH.parent / f".env.bak.{_MAX_ENV_BACKUPS}":
                dst.unlink(missing_ok=True)
            shutil.move(str(src), str(dst))
    if _ENV_PATH.exists():
        shutil.copy2(str(_ENV_PATH), str(_ENV_PATH.parent / ".env.bak.0"))


def _env_backup_restore():
    """恢复最近备份: .env.bak.0 → .env，其余前移"""
    bak0 = _ENV_PATH.parent / ".env.bak.0"
    if not bak0.exists():
        return False
    shutil.copy2(str(bak0), str(_ENV_PATH))
    for i in range(_MAX_ENV_BACKUPS):
        src = _ENV_PATH.parent / f".env.bak.{i + 1}"
        dst = _ENV_PATH.parent / f".env.bak.{i}"
        if src.exists():
            shutil.move(str(src), str(dst))
        else:
            dst.unlink(missing_ok=True)
            break
    return True


def _env_backup_count() -> int:
    n = 0
    for i in range(_MAX_ENV_BACKUPS):
        if (_ENV_PATH.parent / f".env.bak.{i}").exists():
            n += 1
    return n


def _check_port_available(host: str, port: int):
    import subprocess
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((host, port))
        s.close()
        return
    except OSError:
        pass

    console.print(f"\n[yellow]端口 {port} 已被占用，正在查询占用进程……[/]")

    try:
        result = subprocess.run(
            ["ss", "-tlnp", f"sport = :{port}"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.strip().split("\n")[1:]:
            parts = line.split()
            if len(parts) >= 6:
                pid_info = parts[-1]
                if "pid=" in pid_info:
                    pid = pid_info.split("pid=")[-1].split(",")[0]
                    try:
                        pname = subprocess.run(
                            ["ps", "-p", pid, "-o", "comm="],
                            capture_output=True, text=True, timeout=3,
                        ).stdout.strip()
                    except Exception:
                        pname = "?"
                    console.print(f"  PID={pid}  进程={pname}")
    except Exception:
        pass

    try:
        result = subprocess.run(
            ["lsof", "-i", f":{port}", "-P", "-n"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.strip().split("\n")[1:]:
            parts = line.split()
            if len(parts) >= 2:
                console.print(f"  lsof: {' '.join(parts)}")
    except Exception:
        pass

    raise OSError(f"Address already in use: {host}:{port}")


def _env_write(key: str, value: str):
    """将 key=value 写入 .env 文件（更新已有行或追加）"""
    env_key = key.upper()
    lines: list[str] = []
    found = False

    if _ENV_PATH.exists():
        with open(_ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.lstrip()
                if stripped.startswith("#") or stripped == "":
                    lines.append(line)
                    continue
                if "=" in stripped:
                    k = stripped.split("=", 1)[0].strip()
                    if k.upper() == env_key:
                        lines.append(f"{key}={value}\n")
                        found = True
                        continue
                lines.append(line)
    else:
        lines.append("# DSN-exp .env (auto-generated)\n")

    if not found:
        lines.append(f"{key}={value}\n")

    with open(_ENV_PATH, "w", encoding="utf-8") as f:
        f.writelines(lines)


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
        if any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
               for h in logging.root.handlers):
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
    global _server_start_time
    print("\n  --- 服务器状态 ---")

    uptime_str = ""
    if _server_start_time:
        delta = datetime.now() - _server_start_time
        days = delta.days
        hours, rem = divmod(delta.seconds, 3600)
        mins, secs = divmod(rem, 60)
        parts = []
        if days: parts.append(f"{days}d")
        if hours: parts.append(f"{hours}h")
        if mins: parts.append(f"{mins}m")
        parts.append(f"{secs}s")
        uptime_str = f"  Uptime: {' '.join(parts)}"
        print(uptime_str)

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


SENSITIVE_CONFIG_KEYS = {
    "DEEPSEEK_API_KEY", "LITTLESKIN_CLIENT_SECRET",
    "LITTLESKIN_CLIENT_ID", "JWT_SECRET",
}

READONLY_CONFIG_KEYS = {
    "DEEPSEEK_API_KEY", "LITTLESKIN_CLIENT_SECRET",
    "LITTLESKIN_CLIENT_ID", "JWT_SECRET", "SERVER_HOST",
    "SERVER_PORT", "LOCAL_CALLBACK_PORT",
}


def _mask_value(key: str, val) -> str:
    if key in SENSITIVE_CONFIG_KEYS:
        if not val:
            return "(未设置)"
        s = str(val)
        if len(s) <= 8:
            return "*" * len(s)
        return s[:4] + "*" * (len(s) - 8) + s[-4:]
    return str(val)


def _try_convert(value_str: str, target_type):
    """尝试将字符串转换为目标类型，失败返回 None"""
    if target_type is bool:
        lowered = value_str.lower()
        if lowered in ("true", "1", "yes"):
            return True
        elif lowered in ("false", "0", "no"):
            return False
        return None
    try:
        return target_type(value_str)
    except (ValueError, TypeError):
        return None


def _cmd_config(config_cls, args: str):
    """配置管理: listall / set <key> <value> / undo"""
    if config_cls is None:
        print("  错误: Config 不可用")
        return

    parts = args.split(maxsplit=2)
    sub = parts[0].lower() if parts else ""

    if sub == "listall":
        _cmd_config_listall(config_cls)
    elif sub == "set":
        if len(parts) < 3:
            print("  用法: /config set <配置项> <值>")
            print("  示例: /config set MEMORY_ENABLED false")
            return
        key = parts[1]
        val_str = parts[2]
        _cmd_config_set(config_cls, key, val_str)
    elif sub == "undo":
        _cmd_config_undo()
    else:
        print("""
  /config 子命令:
    /config listall         列出所有配置项 (敏感信息隐藏)
    /config set <键> <值>   动态修改配置并写入 .env
    /config undo            回退 .env 到上一版本 (最多 3 步)

  示例:
    /config set MEMORY_ENABLED false
    /config set NARRATIVE_MODEL google/gemma-3-4b
    /config undo
""")


def _cmd_config_listall(config_cls):
    """列出所有配置项"""
    print("\n  [bold]当前配置项[/]")
    table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    table.add_column("配置项", style="bold")
    table.add_column("值", style="dim")
    table.add_column("敏感", justify="center")

    for key in sorted(dir(config_cls)):
        if key.startswith("_"):
            continue
        val = getattr(config_cls, key, None)
        if callable(val):
            continue
        is_sensitive = key in SENSITIVE_CONFIG_KEYS
        tag = "[red]Y[/]" if is_sensitive else ""
        table.add_row(key, _mask_value(key, val), tag)

    console.print(table)
    print()


def _cmd_config_set(config_cls, key: str, val_str: str):
    """动态设置配置项，同步写入 .env"""
    if not hasattr(config_cls, key):
        print(f"  错误: 配置项 '{key}' 不存在")
        return

    if key in READONLY_CONFIG_KEYS:
        print(f"  错误: '{key}' 是敏感/只读配置项，禁止通过 /config 修改")
        return

    current_val = getattr(config_cls, key)
    if callable(current_val):
        print(f"  错误: '{key}' 不是配置值")
        return

    target_type = type(current_val)
    new_val = _try_convert(val_str, target_type)

    if new_val is None:
        type_name = target_type.__name__
        print(f"  错误: 类型不匹配 — '{key}' 需要 {type_name} 类型，无法将 '{val_str}' 转为 {type_name}")
        return

    _env_backup_rotate()
    _env_write(key, str(new_val))
    setattr(config_cls, key, new_val)
    append_log("system", "INFO", f"配置变更: {key} = {new_val} (原值: {current_val})")
    print(f"  [green]OK[/] {key} = {new_val} (原值: {current_val})")


def _cmd_config_undo():
    """回退 .env 到上一个备份版本"""
    count = _env_backup_count()
    if count == 0:
        print("  没有可回退的备份")
        return

    if _env_backup_restore():
        remaining = _env_backup_count()
        print(f"  [green]已回退[/] 到上一版本 (剩余 {remaining} 个历史版本)")

        from dotenv import load_dotenv
        load_dotenv(_ENV_PATH, override=True)
        print("  [dim]注意: .env 已恢复，部分配置需重启服务器后完全生效[/]")
        append_log("system", "INFO", "配置已回退到上一版本")
    else:
        print("  回退失败")


def _cmd_listconfig(config_cls):
    """列出所有配置项，敏感信息隐藏 (兼容旧指令)"""
    _cmd_config_listall(config_cls)


def _cmd_export(db, args: str):
    """导出聊天记录/记忆摘要到 JSON 文件"""
    parts = args.split()
    if len(parts) < 4:
        print("""
  用法:
    /export chats <用户ID> <聊天ID> <输出路径>      导出聊天记录
    /export memories <用户ID> <聊天ID> <输出路径>    导出记忆摘要
    /export messages <用户ID> <聊天ID> <输出路径>    同 /export chats
""")
        return

    sub = parts[0].lower()
    try:
        uid = int(parts[1])
        cid = int(parts[2])
    except ValueError:
        print("  无效的用户 ID 或聊天 ID")
        return
    out_path = parts[3]

    import json, os
    from utils.crypto import MessageCipher
    cipher = db._cipher

    conn = db._get_connection()

    if sub in ("chats", "messages"):
        rows = conn.execute(
            "SELECT message_id, role, content, round_index, timestamp FROM messages "
            "WHERE chat_id = ? ORDER BY message_id ASC",
            (cid,),
        ).fetchall()
        if not rows:
            print("  未找到聊天记录")
            return
        data = []
        for r in rows:
            data.append({
                "message_id": r["message_id"],
                "role": r["role"],
                "content": cipher.decrypt(uid, r["content"] or ""),
                "round_index": r["round_index"],
                "timestamp": r["timestamp"],
            })
        export = {
            "type": "chat_messages",
            "user_id": uid,
            "chat_id": cid,
            "exported_at": datetime.now().isoformat(),
            "count": len(data),
            "messages": data,
        }
    elif sub == "memories":
        rows = conn.execute(
            "SELECT id, round, content, created_at, type FROM memory_v2 "
            "WHERE user_id = ? AND chat_id = ? ORDER BY id ASC",
            (uid, cid),
        ).fetchall()
        if not rows:
            print("  未找到记忆摘要")
            return
        data = []
        for r in rows:
            entry = {
                "id": r["id"],
                "round": r["round"],
                "type": r["type"],
                "content": cipher.decrypt(uid, r["content"] or ""),
                "created_at": r["created_at"],
            }
            data.append(entry)
        export = {
            "type": "memory_summaries",
            "user_id": uid,
            "chat_id": cid,
            "exported_at": datetime.now().isoformat(),
            "count": len(data),
            "memories": data,
        }
    else:
        print(f"  未知导出类型: {sub}")
        return

    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(export, f, ensure_ascii=False, indent=2)
        print(f"  ✓ 已导出 {len(data)} 条到 {out_path}")
    except Exception as e:
        print(f"  ❌ 写入失败: {e}")


def _cmd_import(db, args: str):
    """从 JSON 文件导入聊天记录/记忆摘要"""
    parts = args.split()
    if len(parts) < 4:
        print("""
  用法:
    /import memories <用户ID> <聊天ID> <输入路径>    导入记忆摘要
    /import messages <用户ID> <聊天ID> <输入路径>     导入聊天记录
""")
        return

    sub = parts[0].lower()
    try:
        uid = int(parts[1])
        cid = int(parts[2])
    except ValueError:
        print("  无效的用户 ID 或聊天 ID")
        return
    in_path = parts[3]

    import json
    try:
        with open(in_path, "r", encoding="utf-8") as f:
            export = json.load(f)
    except Exception as e:
        print(f"  ❌ 读取失败: {e}")
        return

    conn = db._get_connection()
    cipher = db._cipher

    if sub == "memories":
        items = export.get("memories", [])
        if not items:
            print("  文件中无记忆数据")
            return
        count = 0
        for item in items:
            encrypted = cipher.encrypt(uid, item.get("content", ""))
            round_ = item.get("round")
            typ = item.get("type", "exp")
            created = item.get("created_at")
            conn.execute(
                "INSERT INTO memory_v2 (user_id, chat_id, type, round, content, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (uid, cid, typ, round_, encrypted, created),
            )
            count += 1
        conn.commit()
        print(f"  ✓ 已导入 {count} 条记忆摘要")

    elif sub in ("chats", "messages"):
        items = export.get("messages", [])
        if not items:
            print("  文件中无聊天记录")
            return
        count = 0
        for item in items:
            encrypted = cipher.encrypt(uid, item.get("content", ""))
            role = item.get("role", "user")
            ri = item.get("round_index")
            ts = item.get("timestamp")
            conn.execute(
                "INSERT INTO messages (chat_id, role, content, round_index, timestamp) "
                "VALUES (?, ?, ?, ?, ?)",
                (cid, role, encrypted, ri, ts),
            )
            count += 1
        conn.commit()
        print(f"  ✓ 已导入 {count} 条聊天记录")
    else:
        print(f"  未知导入类型: {sub}")


def _cmd_reminder(db, args: str):
    """提醒任务管理 CLI"""
    parts = args.split()
    sub = parts[0].lower() if parts else ""

    global _engine
    tm = _engine.task_manager if _engine else None

    if sub in ("list", "ls"):
        uid = int(parts[1]) if len(parts) > 1 else None
        cid = int(parts[2]) if len(parts) > 2 else None

        if tm is None:
            print("  错误: TaskManager 未初始化")
            return

        conn = db._get_connection()
        where = []
        params: list = []
        if uid is not None:
            where.append("user_id = ?")
            params.append(uid)
        if cid is not None:
            where.append("chat_id = ?")
            params.append(cid)
        w = "WHERE " + " AND ".join(where) if where else ""
        rows = conn.execute(
            f"SELECT task_id, task_type, user_id, chat_id, priority, scheduled_time, "
            f"status, interval_seconds, skip_count, created_at FROM tasks {w} "
            f"ORDER BY priority DESC, scheduled_time ASC LIMIT 50",
            params,
        ).fetchall()

        if not rows:
            print("  无匹配的提醒任务")
            return

        from rich.table import Table
        from rich.console import Console
        table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
        table.add_column("ID", style="dim", max_width=10)
        table.add_column("类型")
        table.add_column("时间", style="dim")
        table.add_column("间隔")
        table.add_column("状态")
        table.add_column("跳过")

        for r in rows:
            tid = r["task_id"][:8]
            typ = r["task_type"]
            ts = (r["scheduled_time"] or "")[:19]
            iv = ""
            if r["interval_seconds"]:
                s = r["interval_seconds"]
                if s >= 86400: iv = f"{s//86400}d"
                elif s >= 3600: iv = f"{s//3600}h"
                elif s >= 60: iv = f"{s//60}m"
                else: iv = f"{s}s"
            status = r["status"]
            skip = str(r["skip_count"]) if r["skip_count"] else ""
            table.add_row(tid, typ, ts, iv, status, skip)

        Console().print(table)
        print(f"\n  命令: /reminder cancel <id> | /reminder skip <id>")

    elif sub == "cancel":
        if len(parts) < 2:
            print("  用法: /reminder cancel <task_id>")
            return
        tid = parts[1]
        if tm:
            if tid in tm.tasks:
                task = tm.tasks[tid]
                task.status = TaskStatus.CANCELLED
                task.completed_at = datetime.now()
                tm._save_task(task)
                print(f"  已取消: {tid[:8]}")
            else:
                # partial ID match
                matched = [k for k in tm.tasks if k.startswith(tid)]
                if len(matched) == 1:
                    task = tm.tasks[matched[0]]
                    task.status = TaskStatus.CANCELLED
                    task.completed_at = datetime.now()
                    tm._save_task(task)
                    print(f"  已取消: {matched[0][:8]}")
                elif matched:
                    print("  多个匹配, 请使用完整 ID")
                else:
                    print("  任务不存在")
        else:
            print("  TaskManager 不可用")

    elif sub == "skip":
        if len(parts) < 2:
            print("  用法: /reminder skip <task_id>")
            return
        tid = parts[1]
        if tm and tid in tm.tasks:
            task = tm.tasks[tid]
            if task.task_type == TaskType.HABIT:
                # 跳过本次，调度下一个
                task.skip_count += 1
                task.status = TaskStatus.SKIPPED
                task.completed_at = datetime.now()
                tm._save_task(task)
                # 立即排下一个
                task.scheduled_time = datetime.now() + timedelta(seconds=task.interval_seconds)
                task.status = TaskStatus.PENDING
                task.result = None
                task.error = None
                tm._save_task(task)
                tm._schedule_reminder_task(task)
                print(f"  已跳过本次: {tid[:8]}, 下次: {(task.scheduled_time or '').strftime('%H:%M:%S') if task.scheduled_time else '?'}")
            else:
                task.status = TaskStatus.SKIPPED
                task.completed_at = datetime.now()
                tm._save_task(task)
                print(f"  已跳过: {tid[:8]}")
        else:
            print("  任务不存在")

    else:
        print("""
  /reminder 命令用法:
    /reminder list [用户ID] [聊天ID]      列出提醒任务
    /reminder cancel <task_id>            取消指定提醒
    /reminder skip <task_id>              跳过本次触发 (仅 HABIT 类型可重新排入)
""")


def _cmd_plan(db, args: str):
    """计划系统 CLI: list / create / today / check"""
    from db.plan_engine import PlanEngine
    from db.plan_store import PlanStore

    if not db:
        print("  错误: 数据库不可用")
        return

    store = PlanStore(db)
    engine = PlanEngine(store)
    parts = args.split()
    sub = parts[0].lower() if parts else ""

    if sub == "list":
        global _engine
        uid = int(parts[1]) if len(parts) > 1 else 0
        if uid == 0 and _engine:
            uid = int(input("  用户ID: ").strip())
        goals = store.list_goals(uid)
        if not goals:
            print("  无目标")
            return
        for g in goals:
            phases = " ".join(f"{p.title}({p.status})" for p in g.phases) if g.phases else "(无阶段)"
            print(f"  [{g.status}] {g.title} ({g.progress:.0%})")
            print(f"    phases: {phases}")

    elif sub == "create":
        uid = int(parts[1]) if len(parts) > 1 else int(input("  用户ID: ").strip())
        title = input("  目标标题: ").strip()
        desc = input("  描述 (可选): ").strip()
        deadline = input("  截止日期 (可选 YYYY-MM-DD): ").strip()
        goal = engine.create_goal(uid, title, desc, deadline)
        print(f"  ✓ 已创建: {goal.goal_id[:8]} {title}")

    elif sub == "today":
        uid = int(parts[1]) if len(parts) > 1 else 0
        if uid == 0 and _engine:
            uid = int(input("  用户ID: ").strip())
        from datetime import date
        today = date.today().isoformat()
        summary = engine.daily_summary(uid, today)
        print(f"  今日计划 ({today})")
        print(f"  完成: {summary['done']}/{summary['total']} ({summary['progress']:.0%})")
        for t in summary["tasks"]:
            icon = "☑" if t["status"] == "done" else "⏭" if t["status"] == "skipped" else "☐"
            print(f"    {icon} {t['title']}")

    elif sub == "check":
        tid = parts[1] if len(parts) > 1 else input("  task_id: ").strip()
        note = input("  备注 (可选): ").strip()
        engine.check_off(tid, note)
        print(f"  ✓ 已标记完成")

    else:
        print("""
  /plan 命令用法:
    /plan list <用户ID>          列出目标
    /plan create <用户ID>        创建目标 (交互式)
    /plan today [用户ID]         查看今日计划
    /plan check <task_id>        标记任务完成
""")


def _cmd_help():
    """显示帮助信息"""
    print("""
  可用命令 (必须以 / 开头):
    /newbind    生成新的设备配对码
    /users      列出所有注册用户
    /status     显示服务器状态摘要
    /plugin     列出所有插件及运行状态
    /plugin <名称>  查询指定插件的详细信息
    /memory users    列出用户及记忆统计
    /memory chats <用户ID>  列出用户的聊天
    /memory list <用户ID> <聊天ID> [轮次]  列出/查看记忆
    /memory reindex start [用户ID] [聊天ID]   对记忆建立向量索引(覆盖旧索引)
    /memory query <用户ID> <聊天ID> <关键词...> [--after 日期] [--before 日期] [--date 日期]  搜索记忆
    /memory rebuild latest <N>    重建最近 N 轮摘要
    /memory rebuild latest <用户ID> <聊天ID> <N>    指定聊天的最近 N 轮
    /memory rebuild span <用户ID> <聊天ID> <起始> <结束>  指定轮次范围重建
    /prompt [用户ID]   查看当前合成后的系统提示词
    /config listall   列出所有配置项 (敏感信息隐藏)
    /config set <键> <值>  动态修改配置并写入 .env
    /config undo      回退 .env 到上一版本 (最多 3 步)
     /listconfig 同 /config listall (兼容)
    /persona list                  列出所有角色卡
    /persona status <角色卡名>    查看人格动态状态
    /persona distill <角色卡名>   立即启动人格蒸馏
    /persona materials <角色卡名> 列出蒸馏素材
    /persona rollback <角色卡名> 列出备份快照并回滚
    /hibernate check             查看待机策略+活跃度分布
    /hibernate archive <时间>    设定下次整理时间
    /hibernate sleep             立刻进入待机
    /export chats <用户ID> <聊天ID> <路径>   导出聊天记录为 JSON
    /export memories <用户ID> <聊天ID> <路径> 导出记忆摘要为 JSON
    /import memories <用户ID> <聊天ID> <路径> 从 JSON 导入记忆摘要
    /import messages <用户ID> <聊天ID> <路径> 从 JSON 导入聊天记录
    /reminder list [用户ID] [聊天ID]    列出提醒任务
    /reminder cancel <task_id>          取消提醒
    /reminder skip <task_id>            跳过本次触发
    /detail chats    切换聊天详细模式 (显示完整模型请求/响应)
    /detail actions  切换动作详细模式 (显示动作执行详情)
    /timer      切换管线阶段计时 (后端控制台输出各阶段耗时)
    /stop       安全停止服务器 (等同于 Ctrl+C)
    /help       显示此帮助信息

  其他输入将被转发给驻守模型 (如果已启用)。
""")


def _cmd_plugin(plugin_manager, name: str = None):
    """列出所有插件或查询指定插件详情"""
    if not plugin_manager:
        print("  错误: PluginManager 不可用")
        return

    plugins = plugin_manager.list_plugins()
    if not plugins:
        print("  暂无已注册插件")
        return

    if name:
        p = plugin_manager.get(name)
        if not p:
            print(f"  插件 '{name}' 未找到")
            available = [pl["name"] for pl in plugins]
            print(f"  可用插件: {', '.join(available)}")
            return

        table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        table.add_column("属性", style="dim")
        table.add_column("值", style="bold")
        table.add_row("名称", p.name)
        table.add_row("描述", p.description)
        table.add_row("版本", p.version)
        table.add_row("钩子", ", ".join(h.value for h in p.hooks))
        table.add_row("优先级", str(p.priority))
        table.add_row("启用", "Y" if plugin_manager.is_enabled(p.name) else "N")
        table.add_row("异步", "Y" if AsyncPlugin and isinstance(p, AsyncPlugin) else "N")
        console.print(f"\n  [bold]插件详情: {name}[/]")
        console.print(table)
        return

    table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    table.add_column("名称", style="bold")
    table.add_column("启用")
    table.add_column("优先级")
    table.add_column("钩子", style="dim")
    table.add_column("异步")
    table.add_column("版本", style="dim")

    for pl in plugins:
        hooks_str = ", ".join(pl["hooks"])
        table.add_row(
            pl["name"],
            "Y" if pl["enabled"] else "N",
            str(pl["priority"]),
            hooks_str,
            "Y" if pl.get("is_async") else "",
            pl["version"],
        )

    console.print(f"\n  [bold]已注册插件 ({len(plugins)} 个)[/]")
    console.print(table)


def _cmd_memory(auth_manager, db, args: str):
    """记忆系统管理命令"""
    parts = args.split()
    sub = parts[0].lower() if parts else ""

    if not db:
        print("  错误: 数据库不可用")
        return

    if sub == "users":
        _cmd_memory_users(auth_manager, db)
    elif sub == "chats":
        if len(parts) < 2:
            print("  用法: /memory chats <用户ID>")
            return
        _cmd_memory_chats(db, parts[1])
    elif sub == "list":
        if len(parts) < 3:
            print("  用法: /memory list <用户ID> <聊天ID> [轮次索引]")
            return
        uid_str = parts[1]
        cid_str = parts[2]
        round_str = parts[3] if len(parts) > 3 else None
        _cmd_memory_list(db, uid_str, cid_str, round_str)
    elif sub == "reindex":
        _cmd_memory_reindex(parts)
    elif sub == "query":
        _cmd_memory_query(db, parts)
    elif sub == "rebuild":
        _cmd_memory_rebuild(db, parts)
    else:
        _cmd_memory_help()


def _cmd_memory_reindex(parts: list[str]):
    """重建所有词嵌入 (覆盖旧索引)"""
    subsub = parts[1].lower() if len(parts) > 1 else ""

    if subsub != "start":
        print("""
  用法:
    /memory reindex start                    — 重建所有记忆的词嵌入 (覆盖旧索引)
    /memory reindex start <用户ID>           — 重建指定用户的词嵌入
    /memory reindex start <用户ID> <聊天ID>  — 重建指定聊天的词嵌入
""")
        return

    global _engine
    if _engine is None or _engine.memory_system is None:
        print("  错误: MemorySystem 未初始化")
        return

    ms = _engine.memory_system
    if not ms._embedding_enabled:
        print("  错误: embedding 未启用 (MEMORY_EMBEDDING_ENABLED=false)")
        print("  请设置环境变量 MEMORY_EMBEDDING_ENABLED=true 后重启")
        return

    uid = int(parts[2]) if len(parts) > 2 else None
    cid = int(parts[3]) if len(parts) > 3 else None

    def _run_index():
        print("  开始索引旧记忆...")
        try:
            for processed, total, preview, skipped in ms.reindex_embeddings(
                user_id=uid, chat_id=cid
            ):
                print(f"\r  进度: [{processed}/{total}] {preview[:40]:40s}", end="")
            print(f"\n  完成! 共处理 {total - skipped if 'total' in dir() else 0} 条, 跳过 {skipped if 'skipped' in dir() else 0} 条")
        except Exception as e:
            print(f"\n  索引异常: {e}")

    t = threading.Thread(target=_run_index, daemon=True)
    t.start()
    print("  索引线程已启动 (后台运行)...")


def _cmd_memory_query(db, parts: list[str]):
    """查询记忆: 按关键词 或 --date / --after / --before 时间范围"""
    if len(parts) < 4:
        print("""
  用法:
    /memory query <用户ID> <聊天ID> <关键词>
    /memory query <用户ID> <聊天ID> --after 2026-01-01
    /memory query <用户ID> <聊天ID> 关键词 --before 2026-06-01
    /memory query <用户ID> <聊天ID> --date 2026-06-18
""")
        return

    try:
        uid = int(parts[1])
        cid = int(parts[2])
    except ValueError:
        print("  无效的用户 ID 或聊天 ID")
        return

    # 解析过滤参数
    # 解析过滤参数
    from datetime import datetime as dt, timedelta

    tokens = parts[3:]
    keywords: list[str] = []
    date_after: str | None = None
    date_before: str | None = None

    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t == "--after" and i + 1 < len(tokens):
            date_after = tokens[i + 1]
            i += 2
        elif t == "--before" and i + 1 < len(tokens):
            date_before = tokens[i + 1]
            i += 2
        elif t == "--date" and i + 1 < len(tokens):
            date_after = tokens[i + 1]
            try:
                d = dt.strptime(tokens[i + 1], "%Y-%m-%d")
                date_before = (d + timedelta(days=1)).strftime("%Y-%m-%d")
            except ValueError:
                pass
            i += 2
        else:
            keywords.append(t)
            i += 1

    # ---- 向量检索分支 ----
    global _engine
    ms = _engine.memory_system if _engine else None
    use_vector = ms is not None and ms._embedding_enabled and keywords

    if use_vector:
        embedding_query = " ".join(keywords)
        limit = 20
        hits = ms.search(uid, cid, keywords, limit=limit, embedding_query=embedding_query)
        if not hits:
            print("  未找到匹配的记忆")
            return

        from rich.table import Table
        from rich.console import Console
        console = Console()

        table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
        table.add_column("轮次", justify="right")
        table.add_column("匹配度")
        table.add_column("摘要", style="bold", max_width=60)
        table.add_column("时间", style="dim")

        for m in hits:
            rd = m.get("round") or "-"
            score = f"{m['score']:.2f}"
            summary = m["content"][:80].replace("\n", " ")
            ts = (m["created_at"] or "")[:19]
            table.add_row(str(rd), score, summary, ts)

        console.print(table)
        return

    # ---- 纯 SQL 回退 (无向量或无关键词) ----
    conn = db._get_connection()
    sql = (
        "SELECT id, round, content, created_at FROM memory_v2 "
        "WHERE user_id = ? AND chat_id = ?"
    )
    params: list = [uid, cid]

    if date_after:
        sql += " AND created_at >= ?"
        params.append(date_after)
    if date_before:
        sql += " AND created_at < ?"
        params.append(date_before)

    sql += " ORDER BY id DESC LIMIT 50"

    rows = conn.execute(sql, params).fetchall()
    if not rows:
        print("  未找到匹配的记忆")
        return

    from utils.crypto import MessageCipher
    cipher = db._cipher

    results = []
    for r in rows:
        content = cipher.decrypt(uid, r["content"] or "")
        if not content:
            continue
        if keywords and not any(kw.lower() in content.lower() for kw in keywords):
            continue
        results.append({
            "id": r["id"],
            "round": r["round"],
            "content": content,
            "created_at": r["created_at"],
        })

    if not results:
        print("  未找到匹配的记忆")
        return

    from rich.table import Table
    from rich.console import Console
    console = Console()

    table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    table.add_column("ID", style="dim", justify="right")
    table.add_column("轮次", justify="right")
    table.add_column("摘要", style="bold", max_width=60)
    table.add_column("时间", style="dim")

    for m in results:
        summary = m["content"][:80].replace("\n", " ")
        ts = (m["created_at"] or "")[:19]
        table.add_row(str(m["id"]), str(m["round"] or "-"), summary, ts)

    console.print(table)


def _cmd_memory_rebuild(db, parts: list[str]):
    """重建摘要: /memory rebuild latest <N> 或 /memory rebuild span <起始轮次> <结束轮次>"""
    if len(parts) < 4:
        print("""
  用法:
    /memory rebuild latest <N>                         — 重建最近 N 轮摘要
    /memory rebuild latest <用户ID> <聊天ID> <N>       — 重建指定聊天的最近 N 轮
    /memory rebuild span <用户ID> <聊天ID> <起始> <结束> — 重建指定轮次范围的摘要
""")
        return

    global _engine
    ms = _engine.memory_system if _engine else None
    if ms is None:
        print("  错误: MemorySystem 未初始化")
        return

    mode = parts[1].lower()

    if mode not in ("latest", "span"):
        print("  用法: /memory rebuild latest <N> | /memory rebuild span <起始> <结束>")
        return

    # 解析参数
    try:
        if mode == "latest":
            if len(parts) == 5:
                uid = int(parts[2])
                cid = int(parts[3])
                n = int(parts[4])
            elif len(parts) == 3:
                uid = None
                cid = None
                n = int(parts[2])
            else:
                print("  参数错误")
                return
        else:  # span
            uid = int(parts[2])
            cid = int(parts[3])
            start_round = int(parts[4])
            end_round = int(parts[5]) if len(parts) > 5 else start_round
    except ValueError:
        print("  无效的参数，用户ID/聊天ID/轮次必须为整数")
        return

    if n < 1 if mode == "latest" else start_round < 1 or end_round < start_round:
        print("  参数范围无效")
        return

    # 查询匹配的 memory_v2 条目
    conn = db._get_connection()
    from utils.crypto import MessageCipher
    cipher = db._cipher

    if mode == "latest":
        if uid is not None:
            rows = conn.execute(
                "SELECT id, user_id, chat_id, round, content, created_at FROM memory_v2 "
                "WHERE user_id = ? AND chat_id = ? AND type = 'exp' "
                "ORDER BY round DESC LIMIT ?",
                (uid, cid, n),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, user_id, chat_id, round, content, created_at FROM memory_v2 "
                "WHERE type = 'exp' ORDER BY round DESC LIMIT ?",
                (n,),
            ).fetchall()
    else:  # span
        rows = conn.execute(
            "SELECT id, user_id, chat_id, round, content, created_at FROM memory_v2 "
            "WHERE user_id = ? AND chat_id = ? AND type = 'exp' "
            "AND round BETWEEN ? AND ? ORDER BY round ASC",
            (uid, cid, start_round, end_round),
        ).fetchall()

    if not rows:
        print("  未找到匹配的记忆")
        return

    # 显示端点摘要
    entries = []
    for r in rows:
        content = cipher.decrypt(r["user_id"], r["content"] or "")
        entries.append({
            "id": r["id"], "user_id": r["user_id"], "chat_id": r["chat_id"],
            "round": r["round"], "content": content, "created_at": r["created_at"],
        })

    from rich.table import Table
    from rich.console import Console
    console = Console()

    start = entries[0]
    end = entries[-1]
    print(f"\n  范围: {mode} ({len(entries)} 条)")
    print(f"  ─── 端点当前摘要 ───")
    print(f"  起始 (轮次 {start['round']}): {start['content'][:100]}")
    if len(entries) > 1:
        print(f"  结束 (轮次 {end['round']}): {end['content'][:100]}")
    else:
        print(f"  单条轮次 {start['round']}: {start['content'][:100]}")

    # 确认
    try:
        confirm = input("\n  确认覆盖这些摘要？(y/N): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        confirm = "n"
    if confirm != "y":
        print("  已取消")
        return

    # 执行重建
    rebuild_list = [(e["user_id"], e["chat_id"], e["round"], e["id"]) for e in entries]

    def _run():
        try:
            for processed, total, preview, err in ms.rebuild_summaries(rebuild_list):
                tag = f"[{err}]" if err else ""
                print(f"\r  进度: [{processed}/{total}] {preview[:40]:40s} {tag}", end="")
            print(f"\n  完成! 已重建 {total} 条摘要")
        except Exception as e:
            print(f"\n  重建异常: {e}")

    import threading
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    print("  重建线程已启动 (后台运行)...")


def _cmd_memory_users(auth_manager, db):
    """列出所有用户及其聊天/记忆统计"""
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
    table.add_column("聊天数")
    table.add_column("记忆数")

    conn = db._get_connection()
    for u in users:
        uid = u["uid"]
        chat_row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM chats WHERE user_id = ? AND chat_name != '__steward__'",
            (uid,),
        ).fetchone()
        mem_row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM memory_v2 WHERE user_id = ? AND type = 'exp'",
            (uid,),
        ).fetchone()
        table.add_row(
            str(uid),
            u["display_name"],
            str(chat_row["cnt"]) if chat_row else "0",
            str(mem_row["cnt"]) if mem_row else "0",
        )
    console.print(table)


def _cmd_memory_chats(db, uid_str: str):
    """列出指定用户的所有聊天"""
    try:
        uid = int(uid_str)
    except ValueError:
        print(f"  无效的用户 ID: {uid_str}")
        return

    chats = db.list_chats(uid)
    if not chats:
        print(f"  用户 {uid} 暂无聊天会话")
        return

    table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    table.add_column("聊天ID", style="dim")
    table.add_column("名称", style="bold")
    table.add_column("消息数")
    table.add_column("创建时间")

    conn = db._get_connection()
    for c in chats:
        cid = c["chat_id"]
        mem_row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM memory_v2 WHERE user_id = ? AND chat_id = ? AND type = 'exp'",
            (uid, cid),
        ).fetchone()
        mem_count = f" ({mem_row['cnt']} 记忆)" if mem_row and mem_row["cnt"] > 0 else ""
        table.add_row(
            str(cid),
            c["chat_name"] + mem_count,
            str(c["message_count"]),
            c["created_at"],
        )
    console.print(table)


def _cmd_memory_list(db, uid_str: str, cid_str: str, round_str: str | None):
    """列出指定聊天的记忆条目 (基于 memory_v2)"""
    try:
        uid = int(uid_str)
        cid = int(cid_str)
    except ValueError:
        print("  无效的用户 ID 或聊天 ID")
        return

    # 验证聊天所有权
    conn = db._get_connection()
    row = conn.execute(
        "SELECT 1 FROM chats WHERE chat_id = ? AND user_id = ? AND chat_name != '__steward__'",
        (cid, uid),
    ).fetchone()
    if not row:
        print(f"  用户 {uid} 无权访问聊天 {cid}")
        return

    from utils.crypto import MessageCipher
    cipher = db._cipher

    if round_str is not None:
        try:
            target_round = int(round_str)
        except ValueError:
            print(f"  无效的轮次索引: {round_str}")
            return
        rows = conn.execute(
            "SELECT id, round, content, created_at, type FROM memory_v2 "
            "WHERE user_id = ? AND chat_id = ? AND type = 'exp' AND round = ? "
            "ORDER BY id ASC",
            (uid, cid, target_round),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, round, content, created_at, type FROM memory_v2 "
            "WHERE user_id = ? AND chat_id = ? AND type = 'exp' "
            "ORDER BY round ASC, id ASC",
            (uid, cid),
        ).fetchall()

    if not rows:
        print(f"  聊天 {cid} 暂无记忆条目")
        return

    entries = []
    for r in rows:
        content = cipher.decrypt(uid, r["content"] or "")
        entries.append({
            "id": r["id"],
            "round": r["round"],
            "content": content or "",
            "created_at": r["created_at"],
            "type": r["type"],
        })

    table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    table.add_column("轮次", style="dim", justify="right")
    table.add_column("摘要", style="bold", max_width=60)
    table.add_column("创建时间", style="dim")

    for m in entries:
        summary = m["content"]
        if len(summary) > 58:
            summary = summary[:56] + "..."
        table.add_row(
            str(m["round"] or "-"),
            summary,
            (m["created_at"] or "")[:19],
        )

    if round_str is not None and entries:
        m = entries[0]
        details = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        details.add_column("字段", style="dim")
        details.add_column("值", style="bold")
        details.add_row("ID", str(m["id"]))
        details.add_row("轮次", str(m["round"] or "-"))
        details.add_row("摘要", m["content"])
        details.add_row("类型", m["type"])
        details.add_row("创建时间", m.get("created_at", "")[:19] if m.get("created_at") else "-")
        console.print(details)
    else:
        console.print(table)


def _cmd_prompt(prompt_engine, args: str):
    """获取当前最终合成后的系统提示词"""
    if not prompt_engine:
        print("  错误: PromptEngine 不可用")
        return

    uid_str = args.strip() if args else "0"
    try:
        uid = int(uid_str)
    except ValueError:
        print(f"  无效的用户 ID: {uid_str}")
        return

    user_info = {"uid": uid, "nickname": f"User_{uid}"}
    try:
        prompt = prompt_engine.build_system_prompt(user_info)
    except Exception as e:
        print(f"  构建提示词失败: {e}")
        return

    if not prompt:
        print("  提示词为空")
        return

    print(f"\n  [bold]System Prompt (uid={uid}) — {len(prompt)} 字符[/]\n")
    print(prompt)
    print(f"\n  [dim]── 共 {len(prompt)} 字符 ──[/]\n")


def _cmd_memory_help():
    """显示 memory 命令帮助"""
    print("""
  /memory 命令用法:
    /memory users                    列出所有用户及其聊天/记忆统计
    /memory chats <用户ID>           列出指定用户的所有聊天
    /memory list <用户ID> <聊天ID>   列出指定聊天的所有记忆
    /memory list <用户ID> <聊天ID> <轮次>  查看指定轮次的记忆详情
    /memory reindex start [用户ID] [聊天ID]   对记忆建立向量索引(覆盖旧索引)
    /memory query <用户ID> <聊天ID> <关键词...>  按关键词搜索记忆
    /memory query <用户ID> <聊天ID> --date 2026-06-18   按日期筛选
    /memory query <用户ID> <聊天ID> --after 2026-01-01 --before 2026-07-01
    /memory rebuild latest <N>                      重建最近 N 轮摘要 (全部用户)
    /memory rebuild latest <用户ID> <聊天ID> <N>    重建指定聊天的最近 N 轮
    /memory rebuild span <用户ID> <聊天ID> <起始> <结束>  重建指定轮次范围
""")


def _cmd_detail(arg: str = ""):
    """切换详细模式，显示完整的模型请求和响应内容"""
    from models import DETAIL_CHATS, DETAIL_ACTIONS, toggle_detail_chats, toggle_detail_actions
    
    arg = arg.strip().lower()
    
    if arg == "chats":
        new_state = toggle_detail_chats()
        state_text = "开启" if new_state else "关闭"
        print(f"  聊天详细模式已{state_text}")
        if new_state:
            print("  现在将显示所有模型请求的完整发送内容和生成内容")
        else:
            print("  已恢复默认的精简输出模式")
    elif arg == "actions":
        new_state = toggle_detail_actions()
        state_text = "开启" if new_state else "关闭"
        print(f"  动作详细模式已{state_text}")
        if new_state:
            print("  现在将显示 AI 执行动作的原始输入和系统反馈")
        else:
            print("  已恢复默认的精简输出模式")
    else:
        print("  /detail 用法:")
        print("    /detail chats    切换聊天详细模式 (显示完整模型请求/响应)")
        print("    /detail actions  切换动作详细模式 (显示动作执行详情)")
        print()
        print(f"  当前状态:")
        print(f"    聊天详细模式: {'开启' if DETAIL_CHATS else '关闭'}")
        print(f"    动作详细模式: {'开启' if DETAIL_ACTIONS else '关闭'}")


def _execute_command(line, auth_manager, db, plugin_manager, prompt_engine, config_cls=None, shutdown_event=None, personality_v3=None, maint_system=None):
    parts = line.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd == "/stop":
        print("  正在停止服务器...")
        if shutdown_event:
            shutdown_event.set()
        return

    if cmd == "/hibernate":
        _cmd_hibernate(maint_system, arg)
        return

    handler = _CMD_TABLE.get(cmd)
    if handler:
        handler(auth_manager, db, plugin_manager, prompt_engine, config_cls, personality_v3, arg)
    else:
        print(f"  未知命令: {cmd}，输入 /help 查看可用命令")


def _h_newbind(am, db, pm, pe, cc, pv, arg):
    _cmd_newbind(am)

def _h_users(am, db, pm, pe, cc, pv, arg):
    _cmd_users(am, db)

def _h_status(am, db, pm, pe, cc, pv, arg):
    _cmd_status(am, db)

def _h_plugin(am, db, pm, pe, cc, pv, arg):
    _cmd_plugin(pm, arg or None)

def _h_memory(am, db, pm, pe, cc, pv, arg):
    _cmd_memory(am, db, arg)

def _h_prompt(am, db, pm, pe, cc, pv, arg):
    _cmd_prompt(pe, arg)

def _h_config(am, db, pm, pe, cc, pv, arg):
    _cmd_config(cc, arg)

def _h_listconfig(am, db, pm, pe, cc, pv, arg):
    _cmd_listconfig(cc)

def _h_persona(am, db, pm, pe, cc, pv, arg):
    _cmd_persona(pv, arg)

def _h_help(am, db, pm, pe, cc, pv, arg):
    _cmd_help()


def _h_export(am, db, pm, pe, cc, pv, arg):
    _cmd_export(db, arg)


def _h_import(am, db, pm, pe, cc, pv, arg):
    _cmd_import(db, arg)


def _h_reminder(am, db, pm, pe, cc, pv, arg):
    _cmd_reminder(db, arg)


def _h_plan(am, db, pm, pe, cc, pv, arg):
    _cmd_plan(db, arg)


def _h_detail(am, db, pm, pe, cc, pv, arg):
    _cmd_detail(arg)


def _h_timer(am, db, pm, pe, cc, pv, arg):
    from plugins.pipeline import toggle_timer
    enabled = toggle_timer()
    state = "开启" if enabled else "关闭"
    print(f"  ⏱ 管线阶段计时已{state}")
    print(f"  后续每次请求将在后端控制台输出各阶段耗时")


_CMD_TABLE = {
    "/newbind": _h_newbind,
    "/users": _h_users,
    "/status": _h_status,
    "/plugin": _h_plugin,
    "/memory": _h_memory,
    "/prompt": _h_prompt,
    "/config": _h_config,
    "/listconfig": _h_listconfig,
    "/persona": _h_persona,
    "/export": _h_export,
    "/import": _h_import,
    "/reminder": _h_reminder,
    "/plan": _h_plan,
    "/detail": _h_detail,
    "/timer": _h_timer,
    "/help": _h_help,
}


def _cmd_persona(personality_v3, args: str):
    """人格系统管理命令: status / distill / materials"""
    parts = args.split(maxsplit=1)
    sub = parts[0].lower() if parts else ""

    if not personality_v3:
        print("  错误: PersonalitySystemV3 未初始化")
        return

    if sub not in ("status", "distill", "materials", "list", "rollback"):
        print("""
  /persona 命令用法:
    /persona list                  列出所有角色卡
    /persona status <角色卡名>      查看人格动态状态（情绪、亲和度、性格向量）
    /persona distill <角色卡名>     立即启动人格蒸馏
    /persona materials <角色卡名>   列出蒸馏素材及目录内容
    /persona rollback <角色卡名>    列出备份快照并回滚

  示例: /persona status exa
        /persona rollback exa
""")
        return

    if sub == "list":
        _persona_list(personality_v3)
        return

    card_id = parts[1].strip() if len(parts) > 1 else "exa"
    if sub == "status":
        _persona_status(personality_v3, card_id)
    elif sub == "distill":
        _persona_distill(personality_v3, card_id)
    elif sub == "materials":
        _persona_materials(personality_v3, card_id)
    elif sub == "rollback":
        rollback_parts = card_id.split()
        if len(rollback_parts) >= 2:
            _persona_do_rollback(personality_v3, f"{rollback_parts[0]} {rollback_parts[1]}")
        else:
            _persona_rollback(personality_v3, rollback_parts[0])


def _persona_status(v3, card_id: str):
    card = v3.get_card(card_id)
    d = v3.get_distillation(card_id)
    if not card:
        print(f"  角色卡 '{card_id}' 不存在")
        return

    print(f"\n  [bold]角色卡: {card.display_name or card.name} (id={card_id})[/]")
    print(f"  版本: {card.version}  描述: {card.description}")
    print(f"  经历素材数: {len(card.experiences)}  语料条目: {len(card.corpus)}")
    print(f"  蒸馏状态: {'已就绪' if d else '未蒸馏'}")

    if d:
        print(f"    指纹: {d.content_fingerprint[:30]}...  版本: {d.version}")
        print(f"    模型: {d.model_used}  蒸馏时间: {d.created_at}")
        print(f"    向量维度: {len(d.indicator_vector)}")

        table = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
        table.add_column("ID", style="dim")
        table.add_column("名称")
        table.add_column("值", justify="right")
        table.add_column("倾向", max_width=30)
        for tid in sorted(d.indicator_vector):
            val = d.indicator_vector[tid]
            bar = "█" * int(val * 20)
            label = ""
            if val < 0.3:
                label = "[dim]↓低[/] " + bar
            elif val > 0.7:
                label = "[bold]↑高[/] " + bar
            else:
                label = bar
            table.add_row(tid, _TRAIT_NAMES.get(tid, ""), f"{val:.2f}", label)
        console.print(table)
    print()


def _persona_distill(v3, card_id: str):
    card = v3.get_card(card_id)
    if not card:
        print(f"  角色卡 '{card_id}' 不存在")
        return

    print(f"\n  开始蒸馏 {card_id}（后台执行，请查看日志）...")
    append_log("system", "INFO", f"管理员触发蒸馏: {card_id}")

    import threading as _th
    def _run():
        try:
            d = v3.distill(card_id, model_name="deepseek")
            if d:
                v3.mark_distillation_done(card_id)
                append_log("system", "INFO",
                           f"蒸馏完成: {card_id} version={d.version} dims={len(d.indicator_vector)}")
            else:
                append_log("system", "WARNING",
                           f"蒸馏跳过: {card_id}（指纹未变或已是最新）")
        except Exception as e:
            append_log("system", "ERROR", f"蒸馏失败: {card_id} error={e}")

    _th.Thread(target=_run, daemon=True, name="persona-distill-cli").start()
    print(f"  蒸馏已提交，完成时会输出日志。\n")



def _persona_list(v3):
    cards = v3.list_cards()
    if not cards:
        print("  无角色卡")
        return

    table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    table.add_column("ID", style="bold")
    table.add_column("显示名")
    table.add_column("版本")
    table.add_column("作者", style="dim")
    table.add_column("蒸馏状态")
    table.add_column("素材数")

    for c in cards:
        cid = c.get("card_id", "?")
        d = v3.get_distillation(cid)
        card = v3.get_card(cid)
        exp_count = len(card.experiences) if card else 0
        distill_status = f"v{d.version}" if d else "未蒸馏"
        table.add_row(
            cid,
            c.get("display_name", c.get("name", "")),
            c.get("version", ""),
            c.get("author", ""),
            distill_status,
            str(exp_count),
        )

    console.print(f"\n  [bold]角色卡列表 ({len(cards)} 张)[/]")
    console.print(table)
    print()


def _persona_materials(v3, card_id: str):
    card = v3.get_card(card_id)
    if not card:
        print(f"  角色卡 '{card_id}' 不存在")
        return

    materials_dir = Path(__file__).parent / "character_cards" / "materials" / card_id
    print(f"\n  [bold]{card_id} 素材[/]")
    print(f"  素材目录: {materials_dir}")
    print(f"  目录存在: {'Y' if materials_dir.exists() else 'N'}")

    files = sorted(materials_dir.glob("*.txt")) if materials_dir.exists() else []
    print(f"  待处理文件: {len(files)}")
    for f in files:
        size = f.stat().st_size
        print(f"    {f.name} ({size} bytes)")

    experiences = card.experiences
    print(f"\n  已导入经历: {len(experiences)} 条")
    for e in experiences:
        src = e.file or "文本输入"
        summary_preview = (e.summary or e.text or "")[:80]
        print(f"    [{e.original_length}字] {src}")
        if summary_preview:
            print(f"      {summary_preview}...")
    print()


def _persona_rollback(v3, card_id: str):
    backups = v3.list_backups(card_id)
    if not backups:
        print(f"  角色卡 '{card_id}' 无备份快照")
        return

    print(f"\n  [bold]{card_id} 备份快照 ({len(backups)} 个)[/]")
    table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    table.add_column("#", style="dim", justify="right")
    table.add_column("时间戳", style="bold")
    table.add_column("时间", style="dim")
    table.add_column("大小")

    for i, b in enumerate(backups[:20], 1):
        table.add_row(
            str(i),
            b["timestamp"],
            b["time"][:19].replace("T", " ") if "T" in b["time"] else b["time"][:19],
            f"{b['size']} B",
        )
    console.print(table)

    if len(backups) > 20:
        print(f"  ... 还有 {len(backups) - 20} 个快照未显示")

    print(f"\n  回滚指令: /persona rollback {card_id} <时间戳>")
    print(f"  示例: /persona rollback exa {backups[0]['timestamp']}")


# 扩展 _cmd_persona() 处理 rollback <timestamp>
# rollback 已经被调度到 _persona_rollback(), 需要区分列出和回滚

# 实际上，rollback 子指令需要处理两个参数: card_id + timestamp
# 在当前架构中，_persona_rollback(v3, card_id) 只收到 card_id
# 而 parts[1] 包含了 "rollback exa 20260616_223941" 这样的完整参数字符串

def _persona_do_rollback(v3, args: str):
    """执行回滚到指定快照"""
    parts = args.split()
    if len(parts) < 2:
        print("  用法: /persona rollback <角色卡名> <时间戳>")
        return
    card_id = parts[0]
    ts = parts[1]
    if v3.restore_backup(card_id, ts):
        print(f"  [green]已回滚 {card_id} 到快照 {ts}[/]")
        print(f"  已标记蒸馏待处理，下次对话时自动运行")
    else:
        print(f"  [red]回滚失败: 快照 {ts} 不存在或损坏[/]")


def _cmd_hibernate(ms, args: str):
    parts = args.split(maxsplit=1)
    sub = parts[0].lower() if parts else ""

    if not ms:
        console.print("  错误: 维护系统不可用")
        return

    if sub not in ("check", "archive", "sleep"):
        console.print("""
  /hibernate 命令用法:
    /hibernate check              查看当前策略、活跃度分布、预估下次维护时间
    /hibernate archive <时间>      手动设定下次整理时间 (now / 7d / 3h / 30m / 600)
    /hibernate sleep               立即进入待机模式

  示例:
    /hibernate archive now        立刻启动整理流程
    /hibernate archive 3h         3 小时后启动整理
    /hibernate archive 600        600 秒后启动整理
""")
        return

    if sub == "check":
        _cmd_hibernate_check(ms)
    elif sub == "archive":
        arg = parts[1].strip() if len(parts) > 1 else ""
        _cmd_hibernate_archive(ms, arg)
    elif sub == "sleep":
        _cmd_hibernate_sleep(ms)


def _cmd_hibernate_check(ms):
    from maintenance import config as mc
    from datetime import datetime

    state = ms.state.state.value
    strategy = mc.SCHEDULE_STRATEGY
    tracker = ms.tracker

    console.print(f"\n  [bold]待机节律状态[/]")
    console.print(f"  服务器状态: {state}")
    console.print(f"  调度策略: {strategy}")

    if strategy == "fixed":
        console.print(f"  固定整理时间: 每天 {mc.FIXED_HOUR}:00")
    else:
        window = tracker.best_idle_window(mc.PREDICTIVE_MIN_FREE_HOURS, mc.PREDICTIVE_MAX_HOUR)
        if window:
            console.print(f"  预估最佳空闲窗口: {window[0]}:00 ~ {window[1]}:00")
        console.print(f"  待机超时: {mc.IDLE_TIMEOUT_MINUTES} 分钟无请求")

    tm = tracker.minutes_since_last_request()
    console.print(f"  距离上次请求: {tm} 分钟")
    console.print(f"  总请求数: {tracker.request_count()}")

    # 24h progress bar
    now = datetime.now()
    console.print(f"\n  [bold]24h 活跃度分布 (当前 {now.hour:02d}:{now.minute:02d})[/]")

    buf = tracker._buffer
    bucket_counts = [sum(buf.get(m, [0]*7)) for m in range(1440)]
    max_req = max(bucket_counts, default=1)

    step = 20
    segs = []
    for h in range(24):
        for m in range(0, 60, step):
            total = sum(bucket_counts[h*60 + m: h*60 + m + step])
            ratio = total / max(max_req, 1)
            if ratio > 0.7: ch = '█'
            elif ratio > 0.3: ch = '▓'
            elif ratio > 0.05: ch = '▒'
            else: ch = '.'
            segs.append(ch)
    bar = ''.join(segs)

    tick_line = ''
    ticks = ['0h','2h','4h','6h','8h','10h','12h','14h','16h','18h','20h','22h']
    for i, t in enumerate(ticks):
        tick_line += t.ljust(len(bar) // 12)
    console.print(f"\n  {tick_line[:len(bar)]}")
    console.print(f"  {bar}")

    colored = Text()
    clr = {'.': 'dim', '▒': 'bright_black', '▓': 'yellow', '█': 'green'}
    for ch in bar:
        colored.append(ch, style=clr.get(ch, 'dim'))
    console.print("  ", colored)

    console.print(f"\n  [bright_black]▒ 冷淡[/]  [yellow]▓ 中等[/]  [green]█ 活跃[/]  [dim]. 休眠[/]")
    window = tracker.best_idle_window(3, 8) if strategy == "predictive" else (mc.FIXED_HOUR, mc.FIXED_HOUR+3)
    if window:
        console.print(f"  下次维护预估: 今天 {window[0]}:00 ~ {window[1]}:00")
    tm_now = tracker.minutes_since_last_request()
    if mc.IDLE_TIMEOUT_MINUTES > 0 and tm_now < mc.IDLE_TIMEOUT_MINUTES:
        eta = mc.IDLE_TIMEOUT_MINUTES - tm_now
        console.print(f"  下次待机预估: {eta} 分钟后（如无新请求）")
    console.print()


def _cmd_hibernate_archive(ms, arg: str):
    if not arg:
        console.print("  用法: /hibernate archive <now | 7d | 3h | 30m | 600>")
        return

    import re, time as _time
    if arg.lower() == "now":
        if not ms.trigger_maintenance():
            console.print(f"  无法启动整理（当前状态: {ms.state.state.value}）")
        else:
            console.print("  [green]整理流程已启动[/]")
        return

    m = re.match(r'^(\d+)\s*(d|h|m)?$', arg, re.IGNORECASE)
    if not m:
        console.print(f"  时间格式错误: {arg}")
        return

    amount = int(m.group(1))
    unit = (m.group(2) or 's').lower()
    multipliers = {'d': 86400, 'h': 3600, 'm': 60, 's': 1}
    seconds = amount * multipliers.get(unit, 1)

    from datetime import datetime, timedelta
    target = datetime.now() + timedelta(seconds=seconds)
    ms._next_maint_at = target
    console.print(f"  [green]已设定下次整理时间: {target.strftime('%Y-%m-%d %H:%M:%S')}"
          f" (={amount}{unit})[/]")
    append_log("system", "INFO", f"管理员设定下次整理时间: {target.isoformat()} ({arg})")


def _cmd_hibernate_sleep(ms):
    if not ms.trigger_standby():
        console.print(f"  无法进入待机（当前状态: {ms.state.state.value}）")
    else:
        console.print("  [green]已进入待机模式[/]")


def main():
    global _server_start_time
    _server_start_time = datetime.now()

    console.print(Text(BANNER, style="bold cyan"))
    console.print("[bold]Booting system... (importing app.py)[/]\n")

    try:
        from api import app as app_module
    except Exception as e:
        console.print(f"[red]Failed to import app.py: {e}[/]")
        sys.exit(1)

    Config = app_module.Config
    flask_app = app_module.app
    auth_manager = flask_app.config.get("AUTH_MANAGER")
    db = app_module.db
    engine = getattr(app_module, 'engine', None)
    global _engine
    _engine = engine
    personality_v3 = getattr(app_module, 'personality_v3', None)
    maint_system = getattr(app_module, 'maint_system', None)
    plugin_manager = engine.plugin_manager if engine else None
    prompt_engine = engine.prompt_engine if engine else None

    # ── 启动提示 ──
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
        _check_port_available(host, port)
        from werkzeug.serving import make_server
        server = make_server(host, port, flask_app, threaded=True)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.name = "flask-server"
        server_thread.start()
        time.sleep(0.5)
    except OSError as e:
        if "Address already in use" in str(e):
            console.print(f"\n[red]端口 {port} 已被占用，详情见上方报告[/]\n")
        else:
            console.print(f"[red]Failed to start HTTP server: {e}[/]")
        return
    except Exception as e:
        console.print(f"[red]Failed to start HTTP server: {e}[/]")

    # ── 驻守模型 ──
    steward = None
    if getattr(Config, "STEWARD_ENABLED", True):
        try:
            from utils.steward import StewardModel
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
                _execute_command(line, auth_manager, db, plugin_manager, prompt_engine, Config, _shutdown_flag, personality_v3, maint_system)
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
