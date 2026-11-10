# apps/dsn_study_cli/app.py
# 装配 + 主循环 + 按键（迁移计划 6.6）。
#
# 按键设计：
#   Space（长按）  录音 → ASR → 对话
#   s              选文档摄像头（枚举 + 每台一帧 → select_camera）
#   c              拍一张（scan/quick，进当前批次）
#   f              结束批次（scan/finish → 异步汇总 → 播报）
#   t              文字/图片输入
#   v              列出摄像头
#   q              退出
#
# 验收场景：手写卷子放摄像头 2 下 → 连拍 → 题目（含答案解析）进题库
# → 收到一次汇总播报。

from __future__ import annotations

import argparse
import base64
import contextlib
import logging
import sys
import time
from pathlib import Path

from apps.dsn_study_cli import camera, tui
from apps.dsn_study_cli.audio import VoiceRecorder
from apps.dsn_study_cli.client import StudyClient
from apps.dsn_study_cli.config import backend_base, load_config, save_config
from apps.dsn_study_cli.env import HAS_CAMERA, ensure_dirs, setup_logging
from apps.dsn_study_cli.keyboard import KeyReader
from apps.dsn_study_cli.pollers import AsyncTaskPoller, HeartbeatPoller
from apps.dsn_study_cli.tts import CuePlayer, TtsPlayer

#: 模块级 logger —— 永不为 None，任何地方都能安全 log.info()。
#: （早先写成 `None` 再由 _init_logging() 赋值，导致直接构造 StudyCliApp
#:  时 log.info 会 AttributeError。）
log = logging.getLogger("study_cli")

_logging_ready = False


def _init_logging() -> "logging.Logger":
    """初始化日志（文件 + 控制台）。

    模块级那一行 `setup_logging() if __name__ == "__main__"` 在
    `python -m apps.dsn_study_cli` 下永不成立 —— app.py 是被 import 的，
    __name__ 是 "apps.dsn_study_cli.app"。结果是边缘设备上跑了很久，
    logs/cli_*.log 却一个都没有。故统一在 main() 里显式初始化。
    """
    global _logging_ready
    if not _logging_ready:
        setup_logging()
        _logging_ready = True
    return log

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

HELP_HEADLESS = """
════════ dsn_study CLI（headless）════════
  Space   按一下开始录音，静音自动停止 → ASR → 对话 → 语音回复
  q       退出
  其他键  忽略（headless 下无屏可看）
════════════════════════════════════════
"""

HELP = """
════════════════ dsn_study CLI ════════════════
  Space(长按)  录音 → ASR → 对话
  s            选文档摄像头（VLM 自动判定哪台对文档）
  c            拍一张（进当前批次）
  f            结束批次 → 后台提取入库 → 汇总播报
  t            文字/图片输入（路径以 ~ 开头可发本地图）
  v            列出摄像头
  q            退出
═══════════════════════════════════════════════
"""


def _load_local_image(path_str: str) -> str | None:
    """本地图 → data URL（q75 已由拍摄保证；本地文件原样编码）。"""
    p = Path(path_str).expanduser()
    if not p.is_file() or p.suffix.lower() not in IMAGE_EXTS:
        return None
    mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


class KeySource:
    """按键来源。

    headless 模式优先读**物理键盘**（evdev）：CLI 由 systemd 用
    `tmux new-session -d` 拉起，stdin 是 tmux 伪终端，物理键盘的事件根本
    到不了它（必须先 attach，那就不叫无屏设备了）。evdev 是内核广播，
    不影响图形会话正常使用键盘。

    找不到物理键盘时退回终端（SSH attach 场景）。
    """

    def __init__(self, headless: bool = True):
        self._reader: KeyReader | None = None
        self._use_tui = True
        if headless:
            try:
                r = KeyReader()
                if r.open():
                    self._reader = r
                    self._use_tui = False
                    log.info("按键来源: 物理键盘 %s", r.device)
                else:
                    log.warning("未找到物理键盘，回退到终端输入")
            except Exception:   # noqa: BLE001
                log.warning("物理键盘初始化失败，回退到终端输入", exc_info=True)

    @property
    def is_physical(self) -> bool:
        return self._reader is not None

    def read(self, timeout: float = 0.1) -> str | None:
        if self._reader is not None:
            return self._reader.poll(timeout=timeout)
        return tui.read_key(timeout=timeout)

    def close(self):
        if self._reader is not None:
            self._reader.close()


class StudyCliApp:
    def __init__(self, cfg: dict, headless: bool = True):
        self.cfg = cfg
        self.headless = bool(headless)
        self.client = StudyClient(backend_base(cfg),
                                  token=cfg.get("token", ""),
                                  uid=cfg.get("uid", 1))
        self.client.chat_id = int(cfg.get("chat_id") or 0)
        # TTS 播放：client 的 SSE 处理器把 (text, audio_b64) 塞进 tts_queue，
        # 这里给它一个消费者 —— 此前队列无人取，语音合成完即丢。
        self.tts = TtsPlayer(self.client.tts_queue,
                             on_play_state=self._on_tts_state)
        self.async_poller = AsyncTaskPoller(self.client,
                                            tts_queue=self.client.tts_queue)
        self.client.async_poller = self.async_poller
        self.cue = CuePlayer()
        self.recorder = VoiceRecorder(
            device_index=int(cfg.get("mic_device_index", -1)),
            on_audio=self._on_audio_recorded,
            on_status=self._on_recorder_status,
            cfg=cfg)          # 按 mic_device_name 解析，序号会随插拔漂移
        self.heartbeat = HeartbeatPoller(self.client, on_notify=self._on_notify,
                                         cfg=cfg)
        self.keys = KeySource(headless=headless)
        self._space_down_at = 0.0
        self._running = True

    # ── 状态反馈 ──

    def _say(self, text: str):
        """headless 下不打印（没屏），只记日志；TUI 模式照旧打印。"""
        if self.headless:
            log.info("%s", text)
        else:
            print(f"\n{text}")

    def _on_recorder_status(self, msg: str):
        self._say(msg)
        # 出错/丢弃这类需要用户知道的，用一声低频提示音
        if any(k in msg for k in ("失败", "太短", "不可用")):
            self.cue.beep(freq=420, ms=160)

    def _on_tts_state(self, state: str, text: str):
        """播放开始/结束 —— 播放期间麦克风必须让出来，否则自激。"""
        if state == "start":
            log.info("开始播报: %s", (text or "")[:60])
        else:
            log.info("播报结束")

    def _on_notify(self, reply: str):
        """服务端主动通知（心跳下发）。headless 下它已经在 tts 队列里播了。"""
        self._say(f"🔔 {reply}")

    # ── 录音回调（发送在后台线程，主循环不被阻塞） ──

    def _on_audio_recorded(self, audio_b64: str, secs: float):
        t0 = time.perf_counter()
        log.info("录音结束 %.1fs，开始上行 (t=%.3f)", secs, t0)
        self._say(f"（录音 {secs:.1f}s，识别中…）")
        self.client.send_audio_async(audio_b64)

    # ── 按键动作 ──

    def action_select_camera(self):
        if not HAS_CAMERA:
            print("（本机无 opencv/摄像头，无法选摄像头）")
            return
        devices = camera.enumerate_cameras(self.cfg, force=True)
        if not devices:
            print("（未枚举到摄像头）")
            return
        print(f"发现 {len(devices)} 台摄像头: "
              + ", ".join(d["logical_name"] for d in devices))
        frames = camera.capture_all_cameras(self.cfg)
        frames = [f for f in frames if f.get("image_data")]
        if not frames:
            print("（抓帧全部失败）")
            return
        out = self.client.select_camera(frames)
        if out.get("success"):
            name = out.get("logical_name", "?")
            print(f"已选定文档摄像头: {name}")
            # 显式钉住，避免下次枚举漂移
            cam_map = dict(self.cfg.get("camera_map") or {})
            cam_map.setdefault("doc",
                               camera.resolve_camera(name, self.cfg))
            self.cfg["camera_map"] = cam_map
            save_config(self.cfg)
        else:
            print(f"（选摄像头失败: {out.get('error', '?')}）")

    def action_capture_one(self):
        if not HAS_CAMERA:
            print("（本机无摄像头能力）")
            return
        data_url = camera.capture_frame("doc", self.cfg, use_cache=False) \
            or camera.capture_frame(None, self.cfg, use_cache=False)
        if not data_url:
            print("（抓帧失败）")
            return
        out = self.client.scan_quick(data_url, camera="doc")
        if out.get("success"):
            print(f"已拍摄 #{out.get('count', '?')}（photo={out.get('photo_id', '')[:8]}），"
                  f"批次 {str(out.get('batch_id', ''))[:8]} 后台提取中…")
        else:
            print(f"（拍摄失败: {out.get('error', '?')}）")

    def action_finish_batch(self):
        out = self.client.scan_finish()
        if out.get("success"):
            task_id = out.get("task_id", "")
            print(f"批次结束，共 {out.get('count', 0)} 张；汇总任务 {task_id[:16]}… "
                  f"完成后自动播报。")
            if task_id:
                self.async_poller.add_task(task_id)
        else:
            print(f"（结束批次失败: {out.get('error', '?')}）")

    def action_list_cameras(self):
        if not HAS_CAMERA:
            print("（本机无 opencv）")
            return
        devices = camera.enumerate_cameras(self.cfg)
        if not devices:
            print("（无摄像头）")
            return
        for d in devices:
            print(f"  {d['logical_name']}: /dev/video{d['index']}"
                  f" (backend={d.get('backend')})")
        cams = self.client._get("/api/vision/cameras")
        for c in cams.get("cameras", []):
            note = f" — {c['note']}" if c.get("note") else ""
            print(f"  [服务端] {c['logical_name']}{note}")

    def action_text_input(self):
        raw = tui.raw_input("\n> ").strip()
        if not raw:
            return
        image_data = ""
        # 以 ~ 或 / 开头且是图片后缀 → 本地图以多模态发送
        first = raw.split()[0] if raw.split() else ""
        if first and (first.startswith("~") or first.startswith("/")):
            data_url = _load_local_image(first)
            if data_url:
                image_data = data_url
                raw = raw[len(first):].strip() or "请看这张图片"
                print("（附带本地图片发送）")
        print("…")
        self.client.send_text(raw, image_data=image_data)

    def toggle_recording(self):
        """按一下开始录音，静音自动停；再按一下立即停并发送。

        barge-in：若 AI 正在播报，先掐掉语音再开始录 —— 否则会把
        TTS 的声音一起录进去（自激），且用户说的话根本听不清。
        """
        if self.recorder.is_recording:
            self.recorder.stop_and_send()
            self._say("（停止录音，识别中…）")
            return

        if self.tts.is_playing:
            log.info("barge-in：掐掉正在播报的语音")
            self.tts.interrupt()
            self.tts.clear_queue()

        self._say("（开始录音，静音自动停；再按一次立即停）")
        if not self.recorder.start():
            self.cue.beep(freq=420, ms=160)

    # ── 主循环 ──

    def run(self):
        # 连通性检查 + 配置回写
        if not self.client.check_backend():
            print(f"⚠️ 无法连接服务端 {self.client.base}，请检查 host/port。")
        if self.client.chat_id:
            self.cfg["chat_id"] = self.client.chat_id
            save_config(self.cfg)

        # 后台组件
        self.async_poller.start()
        self.heartbeat.start()
        self.client.start_sender()
        # ⚠️ 别漏这行：TTS 播放线程不启动，tts_queue 就永远没人取 ——
        # 服务端把音频塞进队列、客户端日志显示"音频就绪"，但**一个字都不出声**。
        self.tts.start()

        # 开机即上报摄像头台账（服务端 /api/vision/cameras 可见）
        if HAS_CAMERA:
            def _register():
                devices = camera.enumerate_cameras(self.cfg)
                if devices:
                    self.client.register_cameras([
                        {"logical_name": d["logical_name"], "index": d["index"],
                         "name": d["name"], "backend": str(d.get("backend", ""))}
                        for d in devices])
            import threading
            threading.Thread(target=_register, daemon=True,
                             name="cli-camera-register").start()

        if self.headless:
            log.info("headless 模式：只响应 Space（录音）与 q（退出）")
            print(HELP_HEADLESS)
        else:
            print(HELP)
        # 物理键盘模式下不需要终端 raw mode（也不该去动终端属性）
        ctx = (contextlib.nullcontext() if self.keys.is_physical
               else tui.raw_mode())
        with ctx:
            while self._running:
                try:
                    ch = self.keys.read(timeout=0.1)
                except KeyboardInterrupt:
                    break
                if ch is None:
                    continue
                if ch == " ":
                    self.toggle_recording()
                elif self.headless:
                    # headless 无屏可看，其余按键没有交互意义 —— 忽略。
                    if ch in ("q", "Q"):
                        break
                    continue
                elif ch == "s":
                    self.action_select_camera()
                elif ch == "c":
                    self.action_capture_one()
                elif ch == "f":
                    self.action_finish_batch()
                elif ch == "t":
                    self.action_text_input()
                elif ch == "v":
                    self.action_list_cameras()
                elif ch in ("q", "Q"):
                    break
        self.cleanup()

    def cleanup(self):
        self._running = False
        self.heartbeat.stop()
        self.async_poller.stop()
        self.tts.stop()
        self.keys.close()
        if self.client.chat_id and self.client.chat_id != self.cfg.get("chat_id"):
            self.cfg["chat_id"] = self.client.chat_id
            save_config(self.cfg)
        print("再见。")


def build_parser() -> argparse.ArgumentParser:
    """命令行参数（抽出来便于测试断言默认值）。"""
    parser = argparse.ArgumentParser(description="dsn_study 边缘设备客户端")
    parser.add_argument("--host", default=None, help="服务端地址")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--token", default=None, help="DSN_STUDY_TOKEN (Bearer)")
    # 默认 headless：设备常常不接显示器，此时"按 Space 说话"才是唯一有意义的交互。
    # --tui 保留原来的完整按键菜单（有屏时用）。
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--headless", dest="headless", action="store_true",
                       default=True, help="headless 模式（默认）：只响应 Space/q")
    group.add_argument("--tui", dest="headless", action="store_false",
                       help="完整 TUI 模式：显示按键菜单")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    ensure_dirs()
    _init_logging()
    cfg = load_config()
    if args.host:
        cfg["backend_host"] = args.host
    if args.port:
        cfg["port"] = args.port
    if args.token:
        cfg["token"] = args.token
    if not cfg.get("backend_host"):
        # 首次运行询问一次，之后落盘
        try:
            cfg["backend_host"] = tui.raw_input(
                f"服务端地址 [{cfg.get('backend_host') or '127.0.0.1'}]: ").strip() \
                or "127.0.0.1"
        except Exception:   # noqa: BLE001 - 无交互环境用默认值
            cfg["backend_host"] = "127.0.0.1"
    save_config(cfg)

    app = StudyCliApp(cfg, headless=args.headless)
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
