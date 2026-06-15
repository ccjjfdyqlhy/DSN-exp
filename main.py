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
from datetime import datetime
from collections import deque

from rich.console import Console
from rich.text import Text
from rich.table import Table
from rich import box

try:
    from plugins.base import AsyncPlugin
except ImportError:
    AsyncPlugin = None

console = Console()

LOG_BUFFER: deque = deque(maxlen=200)
LOG_LOCK = threading.Lock()
_LOG_HANDLER_INSTALLED = False

_server_start_time = None

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
    /prompt [用户ID]   查看当前合成后的系统提示词
    /config listall   列出所有配置项 (敏感信息隐藏)
    /config set <键> <值>  动态修改配置并写入 .env
    /config undo      回退 .env 到上一版本 (最多 3 步)
     /listconfig 同 /config listall (兼容)
    /persona list                  列出所有角色卡
    /persona status <角色卡名>    查看人格动态状态
    /persona distill <角色卡名>   立即启动人格蒸馏
    /persona materials <角色卡名> 列出蒸馏素材
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
        uid_str, cid_str = parts[1], parts[2]
        round_str = parts[3] if len(parts) > 3 else None
        _cmd_memory_list(db, uid_str, cid_str, round_str)
    else:
        _cmd_memory_help()


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
            "SELECT COUNT(*) AS cnt FROM memories WHERE user_id = ?",
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
            "SELECT COUNT(*) AS cnt FROM memories WHERE user_id = ? AND chat_id = ?",
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
    """列出指定聊天的记忆条目"""
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

    memories = db.get_memories(uid, cid)
    if not memories:
        print(f"  聊天 {cid} 暂无记忆条目")
        return

    # 如果指定了 round_index，只显示该条
    if round_str is not None:
        try:
            target_round = int(round_str)
        except ValueError:
            print(f"  无效的轮次索引: {round_str}")
            return
        memories = [m for m in memories if m["round_index"] == target_round]
        if not memories:
            print(f"  聊天 {cid} 中未找到轮次 {target_round} 的记忆")
            return

    table = Table(box=box.SIMPLE, show_header=True, padding=(0, 2))
    table.add_column("轮次", style="dim", justify="right")
    table.add_column("摘要", style="bold", max_width=60)
    table.add_column("关键词", max_width=30)
    table.add_column("消息区间")
    table.add_column("创建时间", style="dim")

    for m in memories:
        msg_range = f"{m['message_start_id']}-{m['message_end_id']}" if m.get("message_start_id") else "-"
        kw_str = m.get("keywords", "") or ""
        if len(kw_str) > 28:
            kw_str = kw_str[:26] + "..."
        summary_str = m.get("summary", "") or ""
        if len(summary_str) > 58:
            summary_str = summary_str[:56] + "..."

        table.add_row(
            str(m["round_index"]),
            summary_str,
            kw_str,
            msg_range,
            m.get("created_at", "-"),
        )

    if round_str is not None:
        # 单条详情
        m = memories[0]
        details = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        details.add_column("字段", style="dim")
        details.add_column("值", style="bold")
        details.add_row("轮次", str(m["round_index"]))
        details.add_row("摘要", m.get("summary", ""))
        details.add_row("关键词", m.get("keywords", ""))
        details.add_row("消息起始ID", str(m.get("message_start_id", "-")))
        details.add_row("消息结束ID", str(m.get("message_end_id", "-")))
        details.add_row("创建时间", m.get("created_at", "-"))
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
""")


def _execute_command(line, auth_manager, db, plugin_manager, prompt_engine, config_cls=None, shutdown_event=None, personality_v3=None):
    """解析并执行命令"""
    parts = line.split(maxsplit=1)
    cmd = parts[0].lower()

    if cmd == "/newbind":
        _cmd_newbind(auth_manager)
    elif cmd == "/users":
        _cmd_users(auth_manager, db)
    elif cmd == "/status":
        _cmd_status(auth_manager, db)
    elif cmd == "/plugin":
        name = parts[1].strip() if len(parts) > 1 else None
        _cmd_plugin(plugin_manager, name)
    elif cmd == "/memory":
        args = parts[1].strip() if len(parts) > 1 else ""
        _cmd_memory(auth_manager, db, args)
    elif cmd == "/prompt":
        _cmd_prompt(prompt_engine, parts[1].strip() if len(parts) > 1 else "")
    elif cmd == "/config":
        args = parts[1].strip() if len(parts) > 1 else ""
        _cmd_config(config_cls, args)
    elif cmd == "/listconfig":
        _cmd_listconfig(config_cls)
    elif cmd == "/persona":
        args = parts[1].strip() if len(parts) > 1 else ""
        _cmd_persona(personality_v3, args)
    elif cmd == "/stop":
        print("  正在停止服务器...")
        if shutdown_event:
            shutdown_event.set()
    elif cmd == "/help":
        _cmd_help()
    else:
        print(f"  未知命令: {cmd}，输入 /help 查看可用命令")


def _cmd_persona(personality_v3, args: str):
    """人格系统管理命令: status / distill / materials"""
    parts = args.split(maxsplit=1)
    sub = parts[0].lower() if parts else ""

    if not personality_v3:
        print("  错误: PersonalitySystemV3 未初始化")
        return

    if sub not in ("status", "distill", "materials", "list"):
        print("""
  /persona 命令用法:
    /persona list                  列出所有角色卡
    /persona status <角色卡名>      查看人格动态状态（情绪、亲和度、性格向量）
    /persona distill <角色卡名>     立即启动人格蒸馏
    /persona materials <角色卡名>   列出蒸馏素材及目录内容

  示例: /persona status exa
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
                v3.mark_distillation_done()
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


def main():
    global _server_start_time
    _server_start_time = datetime.now()

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
    engine = getattr(app_module, 'engine', None)
    personality_v3 = getattr(app_module, 'personality_v3', None)
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
                _execute_command(line, auth_manager, db, plugin_manager, prompt_engine, Config, _shutdown_flag, personality_v3)
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
