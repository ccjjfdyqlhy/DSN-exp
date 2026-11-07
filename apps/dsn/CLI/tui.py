# apps/dsn/CLI/tui.py
# 终端交互：原始模式 / 非阻塞按键 / 交互输入 / 界面输出函数。
#
# 从原 psychoscope/minimal.py 抽出（290-420 终端原语 + 2322-2486 输出函数），
# prompt_mic_selection 也归入此处（UI 交互，麦克风枚举来自 audio 模块）。

from __future__ import annotations

import logging
import os
import select
import sys
from contextlib import contextmanager

from .audio import _list_microphones
from . import camera as _camera
from .camera import CAMERA_DEVICE_ID, _capture_and_save_frame, _enumerate_cameras
from .config import load_config, save_config
from .env import DEFAULT_HOST, DEFAULT_PORT, TEMP_DIR


# ════════════════════════════════════════════════════════════════
# 终端原始模式原语
# ════════════════════════════════════════════════════════════════

class TerminalState:
    """保存终端原始模式状态，保证退出时恢复。"""
    def __init__(self):
        self.fd = None
        self.old_attr = None
        self._is_windows = os.name == "nt"

    def enter_raw(self):
        if self._is_windows:
            self._enter_windows()
        else:
            self._enter_unix()

    def exit_raw(self):
        if self._is_windows:
            self._exit_windows()
        else:
            self._exit_unix()

    def _enter_unix(self):
        import termios, tty
        self.fd = sys.stdin.fileno()
        self.old_attr = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        self.raw_attr = termios.tcgetattr(self.fd)  # 保存 setcbreak 后的完整属性

    def _exit_unix(self):
        import termios
        if self.old_attr is not None:
            try:
                termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old_attr)
            except Exception:
                logging.getLogger(__name__).warning("Set operation failed", exc_info=True)
        self.old_attr = None

    def _enter_windows(self):
        import msvcrt
        # Windows 下无需特殊设置，msvcrt.kbhit() + getch() 可用

    def _exit_windows(self):
        pass


_RAW_ATTRS = None
_RAW_FD = None


@contextmanager
def raw_mode():
    """上下文管理器：进入原始模式 → yield → 保证恢复。"""
    ts = TerminalState()
    global _RAW_ATTRS, _RAW_FD
    try:
        ts.enter_raw()
        _RAW_ATTRS = getattr(ts, 'raw_attr', None)
        _RAW_FD = ts.fd
        yield ts
    finally:
        _RAW_ATTRS = None
        _RAW_FD = None
        ts.exit_raw()


def _ensure_raw_mode():
    """完整恢复 setcbreak 后的终端属性（VLC 等可能破坏部分标志位）。"""
    if _RAW_ATTRS is not None and _RAW_FD is not None:
        try:
            import termios
            termios.tcsetattr(_RAW_FD, termios.TCSADRAIN, _RAW_ATTRS)
        except Exception:
            logging.getLogger(__name__).warning("Set operation failed", exc_info=True)


def read_key(timeout: float = 0.1) -> str | None:
    """非阻塞读一个按键，超时返回 None。"""
    if os.name == "nt":
        import msvcrt
        if msvcrt.kbhit():
            ch = msvcrt.getch()
            if ch == b'\xe0':
                ch = msvcrt.getch()
                return None
            try:
                return ch.decode("utf-8", errors="replace")
            except Exception:
                return None
        return None

    try:
        fd = sys.stdin.fileno()
        r, _, _ = select.select([fd], [], [], timeout)
        if r:
            raw = os.read(fd, 1)
            if not raw:
                return None
            return raw.decode("utf-8", errors="replace")
        return None
    except (OSError, ValueError, select.error):
        return None


def raw_input(prompt: str = "") -> str:
    """在原始终端模式下读取一行输入（支持退格，Enter 确认）。"""
    buf: list[str] = []
    if prompt:
        print(prompt, end="", flush=True)
    while True:
        ch = read_key(timeout=None)  # 阻塞读
        if ch is None:
            continue
        if ch == "\r" or ch == "\n":
            print()
            return "".join(buf)
        elif ch == "\x7f" or ch == "\b":  # 退格
            if buf:
                buf.pop()
                sys.stdout.write("\b \b")
                sys.stdout.flush()
        elif ch == "\x03":  # Ctrl+C
            raise KeyboardInterrupt
        elif ch == "\x04":  # Ctrl+D
            return "".join(buf)
        elif ch.isprintable() or ord(ch) >= 32:
            buf.append(ch)
            sys.stdout.write(ch)
            sys.stdout.flush()


# ════════════════════════════════════════════════════════════════
# 麦克风选择交互
# ════════════════════════════════════════════════════════════════

def prompt_mic_selection(cfg: dict):
    """列出所有麦克风并让用户选择（回车取消），把选择持久化到配置文件。"""
    devices = _list_microphones()
    if len(devices) <= 1:
        return

    current = cfg.get("mic_device_index")
    print("\n  检测到多个麦克风:")
    for i, name in enumerate(devices):
        marker = "  ← 当前" if i == current else ""
        print(f"    [{i}] {name}{marker}")
    while True:
        choice = raw_input(f"  选择麦克风 [0-{len(devices)-1}]（回车保持默认）: ").strip()
        if choice == "":
            return
        try:
            idx = int(choice)
        except ValueError:
            print("  无效输入，请重试")
            continue
        if 0 <= idx < len(devices):
            cfg["mic_device_index"] = idx
            save_config(cfg)
            print(f"  已选择麦克风: {devices[idx]} (device index={idx})")
            return
        print("  无效选择，请重试")


# ════════════════════════════════════════════════════════════════
# 界面输出函数
# ════════════════════════════════════════════════════════════════

def print_header(cfg: dict, client=None, locked: bool = False):
    print("=" * 43)
    print("        DSN-exp  Minimal Client")
    print("=" * 43)
    uid = cfg.get("uid", "?")
    name = cfg.get("display_name", "?")
    host = cfg.get("host", f"{DEFAULT_HOST}:{DEFAULT_PORT}")
    print(f"  Backend : {host}")
    print(f"  User    : uid={uid} ({name})")
    if locked:
        print("  \U0001f512 Panel locked")
    print("=" * 43)
    print("  -- 对话 / 录音 --")
    print("  [Enter]  开始/停止录音        [t] 文本输入")
    print("  [r]      手动心跳/查看提醒    [=] 异步任务")
    print("  [k]      跳过最近提醒         [f] 静音当前闹钟")
    print("  -- 状态 / 管理 --")
    print("  [p]      人格状态             [i] 系统信息")
    print("  [l]      闹钟状态             [c] 打卡状态")
    print("  [s]      切换待机             [v] 列出摄像头")
    print("  [g]      选择麦克风           [d] 打卡录制")
    print("  [a x2]   锁定/解锁面板        [b x2] 音乐模式")
    print("  [h/?]    显示帮助             [q/Ctrl+C] 退出")
    print("  -- 音乐模式 --")
    print("  [d/e/f]  上一首/播放暂停/下一首 [n/m] 音量-/+")
    print("=" * 43)
    print()


def print_personality(client):
    try:
        resp = client._http_get("/api/personality/status")
        if resp.status_code != 200:
            print(f"  Failed HTTP {resp.status_code}")
            return
        data = resp.json()
        mood = data.get("mood", {})
        aff = data.get("affinity_value", 0)
        lvl = data.get("affinity_level", {})
        interactions = data.get("total_interactions", 0)
        card = data.get("card_id", "")

        joy = mood.get("joy", 0.5)
        sad = mood.get("sadness", 0.2)
        ang = mood.get("anger", 0.1)
        fear = mood.get("fear", 0.15)

        print(f"\n  --- Personality Status ---")
        print(f"  Card      : {card}")
        print(f"  Interacts : {interactions}")
        print(f"  Affinity  : {aff:.0f}/100 ({lvl.get('label', '?')})")
        print(f"  Mood      : joy={joy:.2f} sad={sad:.2f} ang={ang:.2f} fear={fear:.2f}")
        print(f"  --------------------------")
    except Exception as e:
        print(f"  Error: {e}")


def print_cameras(client=None, save_shots: bool = True):
    """列出本机所有可用摄像头及其逻辑名/备注，并对每台抓一帧保存到 temp。"""
    print(f"\n  --- Cameras ---")
    # 读 camera 模块的当前属性，而不是 import 时拷进来的快照：
    # HAS_CAMERA / cv2 来自 env，测试与运行时都可能替换 camera 模块上的这两个名字。
    if not _camera.HAS_CAMERA:
        print("  opencv-python 未安装，无法枚举摄像头")
        return

    cams = _enumerate_cameras()
    if not cams:
        print("  未检测到任何可用摄像头")
        return

    # 尝试拉取后端登记的备注（若有客户端引用）
    notes: dict[str, str] = {}
    if client is not None:
        try:
            resp = client._http_get("/api/vision/cameras", timeout=10)
            if resp.status_code == 200:
                for c in resp.json().get("cameras", []):
                    if c.get("note"):
                        notes[c["logical_name"]] = c["note"]
        except Exception:
            pass

    for c in cams:
        note = notes.get(c["logical_name"], "")
        marker = "  ← 主摄像头" if c["index"] == CAMERA_DEVICE_ID else ""
        line = f"  {c['logical_name']}: device{c['index']} (index={c['index']}){marker}"
        if note:
            line += f"  [备注: {note}]"
        print(line)

    # 对每台摄像头各拍一帧保存到 temp（测试效果 / 排查用）
    if save_shots:
        print("  正在逐台拍照保存到 temp/ ...")
        for c in cams:
            saved = _capture_and_save_frame(c["index"], TEMP_DIR)
            if saved:
                print(f"    ✓ {c['logical_name']} → {saved.name}")
            else:
                print(f"    ✗ {c['logical_name']} 抓帧失败")
    print("  --------------------------")


def toggle_standby(client):
    try:
        resp = client._http_post("/api/maintenance/toggle_standby", timeout=10)
        state = resp.json().get("state", "?")
        print(f"  Server State: {state}")
    except Exception as e:
        print(f"  Error: {e}")


def print_checkin_status(client):
    print("\n  --- Check-in (打卡) ---")
    try:
        resp = client._http_get("/api/checkin/status", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            date = data.get("checkin_date", "")
            time_ = data.get("checkin_time", "")
            if data.get("checked_in"):
                print(f"  今日已打卡  ({date} {time_})")
            else:
                print(f"  今日未打卡  ({date})")
            print(f"  累计打卡 {data.get('total_days', 0)} 天")
        else:
            print(f"  查询失败 HTTP {resp.status_code}")
    except Exception as e:
        print(f"  查询异常: {e}")


def print_system_info(client):
    from .pollers import HeartbeatPoller  # 延迟导入：仅用其 _type_label 静态映射

    print(f"\n  --- System Info ---")
    try:
        resp = client._http_get("/api/maintenance/status")
        if resp.status_code == 200:
            st = resp.json()
            print(f"  Server   : {st.get('state', '?')}")
            idle = st.get("idle_minutes", 0)
            if idle:
                print(f"  Idle     : {idle} min")
    except Exception:
        logging.getLogger(__name__).warning("Operation failed", exc_info=True)

    try:
        resp = client._http_get("/api/todo/list")
        if resp.status_code == 200:
            todos = resp.json().get("todos", [])
            active = [t for t in todos if t.get("status") == "pending"]
            print(f"  Todos    : {len(active)} pending / {len(todos)} total")
    except Exception:
        logging.getLogger(__name__).warning("Operation failed", exc_info=True)

    try:
        resp = client._http_get("/api/reminder/list")
        if resp.status_code == 200:
            reminders = resp.json().get("reminders", [])
            if reminders:
                print(f"  Reminders: {len(reminders)} pending")
                for r in reminders[:5]:
                    tlabel = HeartbeatPoller._type_label(r.get("task_type", ""))
                    st = r.get("scheduled_time", "")[:16].replace("T", " ")
                    print(f"    [{tlabel}] {st}  {r.get('text', '')[:40]}")
    except Exception:
        logging.getLogger(__name__).warning("Get operation failed", exc_info=True)

    print(f"  ---------------------\n")
