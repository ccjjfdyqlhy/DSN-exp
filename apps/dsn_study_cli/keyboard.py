# apps/dsn_study_cli/keyboard.py
# 物理键盘读取（Linux evdev）—— 无屏对讲机模式的关键。
#
# 为什么不能靠终端：
#   CLI 由 systemd 用 `tmux new-session -d` 拉起，它的 stdin 是 tmux 的伪终端
#   （/dev/pts/N）。物理键盘的事件进的是物理控制台 / 图形会话，**到不了 CLI** ——
#   必须先 `tmux attach` 才收得到键，那就不是"无屏设备"该有的样子。
#
# 这里直接读 /dev/input/eventN：内核把输入事件**广播**给所有打开该设备的 fd，
# 所以既不影响图形会话正常使用键盘，也能让无屏设备独立响应按键。
#
# 不依赖 python-evdev —— 直接按 struct input_event 解析，零额外依赖。
#
# Linux 输入事件结构（64 位）：
#   struct input_event { struct timeval time; __u16 type; __u16 code; __s32 value; };
#   timeval = { tv_sec:8, tv_usec:8 } → 24 字节

from __future__ import annotations

import logging
import os
import select
import struct
import time
from pathlib import Path

logger = logging.getLogger("study_cli.keyboard")

#: struct input_event
EVENT_FMT = struct.Struct("llHHi")

EV_KEY = 0x01
EV_SYN = 0x00

#: 常用键码
KEY_SPACE = 57
KEY_Q = 16
KEY_ESC = 1

#: 默认监听键：空格（对讲机）+ q（退出）
DEFAULT_KEYS = {KEY_SPACE: " ", KEY_Q: "q", KEY_ESC: "\x1b"}

INPUT_DIR = Path("/dev/input")

#: ioctl 编码 —— EVIOCGBIT(ev, len) 读事件类型位图；
#: EVIOCGBIT(EV_KEY, len) 读该设备支持哪些键码。
#:
#: _IOC(dir,type,nr,size) = dir<<30 | type<<8 | nr | size<<16
#:   → EVIOCGBIT(ev, len) = 0x80004500 | ev | (len << 16)
#:     EVIOCGBIT(0, 8)   = 0x80084500   事件类型位图
#:     EVIOCGBIT(1, 96)  = 0x80064501   键码位图（EV_KEY=1）
EVIOCGBIT = 0x80004500
EV_KEY = 0x01
KEY_MAX = 0x2FF          # 键码位图长度（(KEY_MAX+8)//8 字节）
KEY_SPACE = 57


def _eviocgbit(ev: int, length: int) -> int:
    """EVIOCGBIT(ev, length) 的 ioctl 号。"""
    return EVIOCGBIT | ev | (length << 16)


def _supports_space(fd: int) -> bool:
    """设备是否支持 EV_KEY 且带 KEY_SPACE。

    用 EVIOCGBIT 查能力位是最准的办法，但本机 ioctl 返回 EINVAL
    （EVIOCGBIT(0,8)=0x80084500 也不行），所以这里退而求其次：
    只看 EV 能力位，查不到就按 True 放行，由上层用设备名筛选。
    """
    import fcntl
    try:
        ev_bits = fcntl.ioctl(fd, _eviocgbit(0, 8), bytearray(8))
        return bool(ev_bits[0] & (1 << EV_KEY))
    except OSError:
        return True


def list_keyboards() -> list[tuple[str, str]]:
    """列出可用的键盘 evdev 设备 → [(设备路径, 名称)]。

    过滤条件：Handlers 同时含 "kbd" 与 "event"（真正的按键矩阵），
    **且**设备能力里确实有 KEY_SPACE（排除 USB 麦克风/摄像头这类
    也注册了 kbd handler 的 HID 设备）。
    """
    out: list[tuple[str, str]] = []
    try:
        text = Path("/proc/bus/input/devices").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return out
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        # /proc/bus/input/devices 每行是 "<单字母前缀>: <值>"
        #   N=Name  H=Handlers  P=Phys  S=Sysfs  U=Uniq
        fields = {}
        for line in block.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                fields[k.strip()] = v.strip()
        name = fields.get("N", "")
        handlers = fields.get("H", "")
        if "kbd" not in handlers or "event" not in handlers:
            continue
        # 名字里带 keyboard 的才是真键盘 —— USB 麦克风/摄像头也会注册
        # kbd handler（HID 协议），光看 Handlers 会选错。
        if "keyboard" not in name.lower():
            continue
        for h in handlers.split():
            if not h.startswith("event"):
                continue
            path = INPUT_DIR / h
            if not path.exists():
                continue
            try:
                fd = os.open(str(path), os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                continue
            try:
                if _supports_space(fd):
                    out.append((str(path), name))
            finally:
                os.close(fd)
    return out


class KeyReader:
    """从 evdev 设备读按键。

    :param keys: {键码: 字符} 映射
    :param device: 指定设备路径（None = 自动挑第一个键盘）
    """

    def __init__(self, keys: dict[int, str] | None = None,
                 device: str | None = None):
        self._keys = dict(keys or DEFAULT_KEYS)
        self._fd = None
        self._path = device
        self._closed = False

    # ── 生命周期 ──

    def open(self) -> bool:
        """打开设备。成功返回 True。"""
        if self._fd is not None:
            return True
        candidates = []
        if self._path:
            candidates.append(self._path)
        else:
            candidates = [p for p, _ in list_keyboards()]
        for path in candidates:
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            except OSError as e:
                logger.warning("打开键盘设备失败 %s: %s", path, e)
                continue
            self._fd = fd
            self._path = path
            logger.info("键盘设备已打开: %s", path)
            return True
        logger.warning("没有可用的键盘设备（/dev/input 下找不到 kbd 设备）")
        return False

    def close(self):
        self._closed = True
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None

    @property
    def device(self) -> str:
        return self._path or ""

    # ── 读事件 ──

    def _reopen(self, why: str) -> None:
        """设备失效后重新打开（USB reset / 拔插会让旧 inode 失效）。

        关键：evdev 设备被"删除"后，select() 会**立即返回**（fd 仍可读但
        读出来是空的），如果只是 continue，主循环会 100% 空转烧 CPU，
        而且永远收不到新事件 —— 实测踩过：键盘触发 USB reset 后，
        CLI 一直收不到按键，CPU 却跑满。
        """
        logger.warning("键盘设备失效（%s）：%s —— 尝试重新打开", why, self._path)
        was = self._path
        self.close()
        time.sleep(0.5)
        if self.open():
            logger.info("键盘设备已重新打开: %s（原先 %s）", self._path, was)
        else:
            logger.warning("暂时找不到键盘设备，稍后重试")

    def poll(self, timeout: float = 0.2) -> str | None:
        """读一个按键；超时返回 None。

        只上报"按下"沿（value==1），松开沿忽略 —— 按一下开始录音即可。
        """
        if self._fd is None:
            if not self.open():
                # 设备暂时不在：退避，别空转
                time.sleep(min(timeout, 0.5))
                return None
        try:
            r, _, _ = select.select([self._fd], [], [], timeout)
        except (OSError, ValueError) as e:
            self._reopen("select 失败: %s" % e)
            return None
        if not r:
            return None
        try:
            data = os.read(self._fd, EVENT_FMT.size * 64)
        except BlockingIOError:
            return None
        except OSError as e:
            self._reopen("读失败: %s" % e)
            return None
        if not data:
            # 设备被删除/重枚举：select 一直说可读，读出来却是空的
            self._reopen("读到空数据（设备可能已重枚举）")
            return None
        n = len(data) // EVENT_FMT.size
        for i in range(n):
            # struct input_event 有 5 个字段：tv_sec, tv_usec, type, code, value
            _sec, _usec, typ, code, val = EVENT_FMT.unpack_from(
                data, i * EVENT_FMT.size)
            if typ != EV_KEY:
                continue
            if val != 1:      # 0=松开, 2=自动重复 —— 都忽略
                continue
            ch = self._keys.get(code)
            if ch is not None:
                logger.info("键盘事件: code=%d → %r", code, ch)
                return ch
        return None

    def wait_key(self, timeout: float | None = None) -> str | None:
        """阻塞等一个按键；timeout=None 表示一直等。"""
        deadline = None if timeout is None else (timeout + _now())
        while not self._closed:
            if deadline is not None and _now() >= deadline:
                return None
            ch = self.poll(timeout=0.2)
            if ch is not None:
                return ch
        return None


def _now() -> float:
    import time
    return time.monotonic()
