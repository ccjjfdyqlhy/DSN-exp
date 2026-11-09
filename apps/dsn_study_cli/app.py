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
import sys
import time
from pathlib import Path

from apps.dsn_study_cli import camera, tui
from apps.dsn_study_cli.audio import VoiceRecorder
from apps.dsn_study_cli.client import StudyClient
from apps.dsn_study_cli.config import backend_base, load_config, save_config
from apps.dsn_study_cli.env import HAS_CAMERA, ensure_dirs, setup_logging
from apps.dsn_study_cli.pollers import AsyncTaskPoller, HeartbeatPoller

log = setup_logging() if __name__ == "__main__" else None

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

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


class StudyCliApp:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.client = StudyClient(backend_base(cfg),
                                  token=cfg.get("token", ""),
                                  uid=cfg.get("uid", 1))
        self.client.chat_id = int(cfg.get("chat_id") or 0)
        self.async_poller = AsyncTaskPoller(self.client)
        self.client.async_poller = self.async_poller
        self.recorder = VoiceRecorder(
            device_index=int(cfg.get("mic_device_index", -1)),
            on_audio=self._on_audio_recorded,
            on_status=lambda s: print(f"\n{s}"))
        self.heartbeat = HeartbeatPoller(self.client, cfg=cfg)
        self._space_down_at = 0.0
        self._running = True

    # ── 录音回调（发送在后台线程，主循环不被阻塞） ──

    def _on_audio_recorded(self, audio_b64: str, secs: float):
        print(f"\n（录音 {secs:.1f}s，识别中…）")
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
        if self.recorder.is_recording:
            self.recorder.stop_and_send()
            print("（停止录音，识别中…）")
        else:
            print("（开始录音，再次按 Space 停止；静音 2s 自动停）")
            self.recorder.start()

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

        print(HELP)
        with tui.raw_mode():
            while self._running:
                try:
                    ch = tui.read_key(timeout=0.1)
                except KeyboardInterrupt:
                    break
                if ch is None:
                    continue
                if ch == " ":
                    self.toggle_recording()
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
        if self.client.chat_id and self.client.chat_id != self.cfg.get("chat_id"):
            self.cfg["chat_id"] = self.client.chat_id
            save_config(self.cfg)
        print("再见。")


def main(argv=None):
    parser = argparse.ArgumentParser(description="dsn_study 边缘设备客户端")
    parser.add_argument("--host", default=None, help="服务端地址")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--token", default=None, help="DSN_STUDY_TOKEN (Bearer)")
    args = parser.parse_args(argv)

    ensure_dirs()
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

    app = StudyCliApp(cfg)
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
