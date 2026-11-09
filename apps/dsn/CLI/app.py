# apps/dsn/CLI/app.py
# 客户端装配与主事件循环。
#
# 从原 psychoscope/minimal.py 的 main()（2493-2919）重组：
#   - 组件装配 / 认证流程不变
#   - 新增 --headless：跳过键盘循环，仅运行后台组件（心跳/轮询/感知/视觉），
#     供树莓派 systemd 服务等无终端场景使用
#
# 单线程事件循环，所有输入走原始键盘（交互模式）。

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
import time
from datetime import datetime

import requests

from .audio import MusicPlayer, VoiceRecorder, _play_beep
from .camera import _enumerate_cameras
from .checkin import CheckinRecorder
from .client import DSNClient
from .config import CONFIG_FILE, load_config, prompt_backend_host, save_config
from .env import DEFAULT_PORT, log
from .pollers import AsyncTaskPoller, HeartbeatPoller
from .sensing import IdleSensingMonitor
from .tui import (_ensure_raw_mode, print_cameras, print_checkin_status,
                  print_header, print_personality, print_system_info,
                  prompt_mic_selection, raw_input, raw_mode, read_key,
                  toggle_standby)
from .vision import StreamPusher, VisionObserver


def _load_local_image(text: str) -> str:
    """输入若是本地图片路径（~/ 或绝对路径，jpg/png/webp/bmp/gif）→ 转 data URL；否则返回空串。"""
    if not (text.startswith("~") or text.startswith("/")):
        return ""
    from pathlib import Path
    p = Path(text).expanduser()
    if not p.is_file() or p.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"):
        return ""
    try:
        import base64
        mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
        if p.suffix.lower() == ".webp":
            mime = "image/webp"
        elif p.suffix.lower() == ".gif":
            mime = "image/gif"
        elif p.suffix.lower() == ".bmp":
            mime = "image/bmp"
        b64 = base64.b64encode(p.read_bytes()).decode()
        print(f"  \U0001f4b7 已附加图片: {p.name} ({p.stat().st_size // 1024} KB)")
        return f"data:{mime};base64,{b64}"
    except Exception as e:
        log.warning("读取图片失败: %s", e)
        print(f"  \u26a0\ufe0f 图片读取失败: {e}")
        return ""


def _report_cameras_background(client):
    """枚举摄像头并上报后端（多摄像头支持）——后台守护线程，避免 cv2 打开慢设备阻塞启动。"""
    try:
        cams = _enumerate_cameras()
        if cams:
            client._http_post("/api/vision/cameras", json={"cameras": cams}, timeout=15)
            log.info("已上报 %d 个摄像头到后端: %s",
                     len(cams), ", ".join(d["logical_name"] for d in cams))
    except Exception:
        log.warning("摄像头枚举/上报失败", exc_info=True)


def _run_headless(components, client, cfg) -> None:
    """无终端模式：后台组件照常运行，等 SIGINT/SIGTERM 或 Ctrl+C 退出。"""
    stop_event = threading.Event()

    def _stop(sig, frame):
        stop_event.set()

    signal.signal(signal.SIGINT, _stop)
    try:
        signal.signal(signal.SIGTERM, _stop)
    except (ValueError, OSError):
        pass

    print("  Headless 模式：后台组件运行中（心跳/轮询/感知/视觉），Ctrl+C 或 SIGTERM 退出")
    try:
        while not stop_event.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--pairing", default="")
    parser.add_argument("--no-auth", action="store_true",
                        help="跳过配对认证（面向 dsn_study 等本地无认证后端）")
    parser.add_argument("--headless", action="store_true",
                        help="无终端模式：跳过键盘循环，仅运行后台组件（心跳/轮询/感知/视觉）")
    args = parser.parse_args()

    # 尽早注册 SIGINT，确保任何阻塞（含 cv2 摄像头枚举）期间 ^C 都能生效
    def _early_sigint(sig, frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGINT, _early_sigint)

    cfg = load_config()

    # 后端地址解析：CLI --host > 配置文件 backend_host > 首次启动询问并持久化；端口固定 5000
    host = args.host
    if not host:
        host = (cfg.get("backend_host") or "").strip()
    if not host:
        if args.headless:
            print("  [ERROR] headless 模式需要预先配置 backend_host 或传 --host（无法交互询问）")
            sys.exit(1)
        host = prompt_backend_host(cfg)

    cfg["host"] = f"{host}:{args.port}"

    # no_auth 必须**在构造时传入**：DSNClient.__init__ 把 self._no_auth 定下来，
    # 而 send_text/send_audio/send_async 依据它决定是否直接 return None。
    # 此前只在下面设 client.uid = 1、没传 no_auth → self._no_auth 恒 False →
    # --no-auth 模式下所有对话与语音发送**静默失效**（无任何报错）。
    client = DSNClient(host, args.port, no_auth=args.no_auth)

    print(f"  Backend: http://{host}:{args.port}")
    try:
        r = requests.get(f"http://{host}:{args.port}/api/auth/status", timeout=5)
        if r.status_code == 200:
            st = r.json()
            methods = [k for k, v in st.get("methods", {}).items() if v]
            print(f"  Connected, methods: {', '.join(methods)}")
        else:
            print(f"  HTTP {r.status_code}")
    except Exception as e:
        print(f"  Connection check error: {e}")
        sys.exit(1)

    # 首次启动（无配置文件）或尚未选定麦克风：若检测到多个麦克风则询问用户选择并持久化
    if not CONFIG_FILE.exists() or "mic_device_index" not in cfg:
        if not args.headless:
            prompt_mic_selection(cfg)

    display_name = cfg.get("display_name", "")
    pairing_code = args.pairing

    # 预处理 --pairing：尝试自动认证，否则进入交互式注册
    if not pairing_code:
        cfg_file = load_config()
        if cfg_file.get("api_key"):
            pairing_code = "cached"

    if args.no_auth:
        # 无认证后端（dsn_study 本地单用户垫片）：跳过配对，直接放行。
        # _no_auth 已在构造时传入（否则发送路径会静默 return None）。
        client.uid = 1
        print("  无认证模式 (--no-auth)：跳过配对流程")
    elif args.headless:
        # 无终端：不弹交互注册，认证失败即退出（systemd 场景配置应预先就绪）
        ok = client.authenticate(code=pairing_code, name=display_name)
        if not ok:
            print("  [ERROR] headless 认证失败（无 api_key 或 pairing code 失效）")
            sys.exit(1)
    else:
        while True:
            ok = client.authenticate(code=pairing_code, name=display_name)
            if ok:
                break

            print("\n  ========================================")
            print("            DSN-exp Registration")
            print("  ========================================")
            pairing_code = input("  Pairing Code: ").strip()
            if not display_name:
                display_name = input("  Your Name: ").strip()
            if not pairing_code:
                sys.exit(1)

    cfg = load_config()
    cfg["uid"] = client.uid
    cfg["display_name"] = client.display_name
    if client.chat_id:
        cfg["chat_id"] = client.chat_id
    save_config(cfg)

    # 初始化所有组件
    recorder = VoiceRecorder(client)
    sensing_mon = IdleSensingMonitor(client, recorder)
    checkin_rec = CheckinRecorder(client)
    vision_obs = VisionObserver(client)
    stream_pusher = StreamPusher(client)
    reminder = HeartbeatPoller(client, client._tts_queue, vision_observer=vision_obs,
                               sensing_monitor=sensing_mon, stream_pusher=stream_pusher)
    reminder.start()
    async_poller = AsyncTaskPoller(client, client._tts_queue)
    async_poller.start()
    client.async_poller = async_poller

    threading.Thread(target=_report_cameras_background, args=(client,), daemon=True,
                     name="camera-report").start()

    player = MusicPlayer(client, cfg.get("uid", 1))
    player.start_poll()
    client._player = player

    components = {
        "vision_obs": vision_obs,
        "sensing_mon": sensing_mon,
        "player": player,
        "async_poller": async_poller,
        "reminder": reminder,
        "recorder": recorder,
        "checkin_rec": checkin_rec,
    }

    if args.headless:
        try:
            _run_headless(components, client, cfg)
        finally:
            _cleanup(components, client, cfg)
        return

    # 状态变量
    running = True
    locked = False
    _music_mode = False
    _music_was_playing = False
    _recording_session = False
    _auto_stop_ts = 0.0
    _last_a_ts = 0.0
    _last_b_ts = 0.0
    _DOUBLE_CLICK_WINDOW = 0.5

    print_header(cfg, client)
    print("  Ready! Press Enter to toggle recording...\n")

    def _sigint(sig, frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGINT, _sigint)

    # ── 主事件循环 ──
    with raw_mode():
        try:
            while running:
                ch = read_key(timeout=0.1)

                # ── 静音/超时自动停止：capture loop 已将 _recording 置为 False ──
                if _recording_session and not recorder.is_recording and recorder.has_frames:
                    _ensure_raw_mode()
                    print("\n  (auto-stopped by silence)")
                    recorder.stop_and_send()
                    _play_beep(client, 440)
                    print()
                    _ensure_raw_mode()
                    _recording_session = False
                    _auto_stop_ts = time.time()
                    if _music_was_playing and player.state == "paused":
                        player.toggle()
                    _music_was_playing = False

                if ch is None:
                    continue

                # ── 双击 'a' 锁定/解锁 ──
                if ch.lower() == "a":
                    now = time.time()
                    if now - _last_a_ts < _DOUBLE_CLICK_WINDOW:
                        locked = not locked
                        if locked:
                            if _recording_session:
                                recorder.stop_and_send()
                                _play_beep(client, 440)
                                _recording_session = False
                                if _music_was_playing and player.state == "paused":
                                    player.toggle()
                                _music_was_playing = False
                            print("\n  \U0001f512 Panel locked")
                        else:
                            print("\n  \U0001f513 Panel unlocked")
                        _last_a_ts = 0.0
                        continue
                    _last_a_ts = now
                    continue

                # ── 双击 'b' 切换音乐模式 ──
                if ch.lower() == "b":
                    now = time.time()
                    if now - _last_b_ts < _DOUBLE_CLICK_WINDOW:
                        _music_mode = not _music_mode
                        if _music_mode:
                            player.load_playlist()
                            _play_beep(client, 880)
                            print("\n  \u266a Music Mode")
                        else:
                            print("\n  Exited Music Mode")
                            _play_beep(client, 440)
                        _last_b_ts = 0.0
                        continue
                    _last_b_ts = now
                    continue

                # ── 锁定时忽略除 'a' 外所有输入 ──
                if locked:
                    continue

                # ── Enter: toggle 开始/停止录音 ──
                if ch in ("\r", "\n"):
                    if client.is_sending:
                        print("\n  \u23f3 上一轮对话还在发送中，请稍候...")
                        continue
                    if not _recording_session:
                        # 刚自动停止则忽略本次 Enter，避免误启动新录音
                        if time.time() - _auto_stop_ts < 1.0:
                            continue
                        _music_was_playing = _music_mode and player.state == "playing"
                        if _music_was_playing:
                            player.toggle()
                        print("\n  Recording... (press Enter to stop)")
                        _play_beep(client, 880)
                        recorder.start()
                        _recording_session = True
                    else:
                        recorder.stop_and_send()
                        _play_beep(client, 440)
                        _ensure_raw_mode()
                        print()
                        _ensure_raw_mode()
                        _recording_session = False
                        if _music_was_playing and player.state == "paused":
                            player.toggle()
                        _music_was_playing = False

                # ── q / Ctrl+C: 退出 ──
                elif ch.lower() == "q":
                    if _recording_session:
                        recorder.stop_and_send()
                        _play_beep(client, 440)
                        _recording_session = False
                    break

                # ── p: 人格状态 ──
                elif ch.lower() == "p":
                    print_personality(client)

                # ── v: 列出所有可用摄像头 ──
                elif ch.lower() == "v":
                    print_cameras(client)

                # ── g: 选择/更换麦克风 ──
                elif ch.lower() == "g":
                    prompt_mic_selection(load_config())

                # ── s: standby ──
                elif ch.lower() == "s":
                    toggle_standby(client)

                # ── d: 打卡 (check-in) — 主摄像头录像 + 麦克风录音，再按停止上传 ──
                # 注意：音乐模式下 d 是上一首，需让位给后面的音乐分支。
                elif ch.lower() == "d" and not _music_mode:
                    if checkin_rec.is_recording:
                        checkin_rec.stop()
                    else:
                        checkin_rec.start()

                # ── c: 打卡状态 ──
                elif ch.lower() == "c":
                    print_checkin_status(client)

                # ── i: 系统信息 ──
                elif ch.lower() == "i":
                    print_system_info(client)

                # ── k: 跳过提醒 ──
                elif ch.lower() == "k":
                    if not reminder.skip_latest():
                        print("\n  No recent reminder to skip")

                # ── r: 手动心跳 ──
                elif ch.lower() == "r":
                    reminder.sync_now()
                    try:
                        resp = client._http_get("/api/reminder/list")
                        if resp.status_code == 200:
                            reminders = resp.json().get("reminders", [])
                            now = datetime.now()
                            upcoming = []
                            for r in reminders:
                                try:
                                    st = datetime.fromisoformat(r["scheduled_time"])
                                    if st > now:
                                        upcoming.append(r)
                                except Exception:
                                    continue
                            upcoming.sort(key=lambda r: r.get("scheduled_time", ""))
                            print(f"\n  Reminders: {len(reminders)} total, {len(upcoming)} upcoming")
                            for r in upcoming[:5]:
                                tlabel = reminder._type_label(r.get("task_type", ""))
                                st = r.get("scheduled_time", "")[:16].replace("T", " ")
                                print(f"    [{tlabel}] {st}  {r.get('text', '')[:50]}")
                    except Exception as e:
                        log.warning("Reminder list failed: %s", e)

                    try:
                        resp = client._http_get("/api/alarms")
                        if resp.status_code == 200:
                            alarms = resp.json().get("alarms", [])
                            if alarms:
                                print(f"  Alarms: {len(alarms)} total")
                                for a in alarms:
                                    wd = ",".join(a["days"]) if a["days"] else "每天"
                                    status = "开" if a["enabled"] else "关"
                                    print(f"    \u23f0 {a['time']} [{wd}] {a['message'][:40]} ({status})")
                        resp2 = client._http_get("/api/alarms/now")
                        if resp2.status_code == 200:
                            nxt = resp2.json().get("next_alarm")
                            if nxt:
                                cd = nxt.get("countdown", "?")
                                icon = "\u26a1已触发" if nxt.get("fired") else "\U0001f514等待"
                                print(f"    {icon} 下次: {nxt['date']}({nxt['weekday']}) {nxt['time']} 剩{cd}")
                    except Exception as e:
                        log.warning("Alarm list failed: %s", e)

                # ── h / ?: 帮助 ──
                elif ch.lower() in ("h", "?"):
                    print_header(cfg, client, locked)

                # ── f: 静音闹钟 ──
                elif ch.lower() == "f":
                    last_ids = list(reminder._last_triggered.keys())
                    dismissed = False
                    for tid in reversed(last_ids):
                        if tid.startswith("alarm_"):
                            alarm_id = tid[6:]
                            try:
                                resp = client._http_post(f"/api/alarms/{alarm_id}/dismiss")
                                if resp.status_code == 200:
                                    print(f"\n  \U0001f515 闹钟 {alarm_id} 已静音")
                                    dismissed = True
                                    break
                            except Exception:
                                logging.getLogger(__name__).warning("Operation failed", exc_info=True)
                    if not dismissed:
                        try:
                            resp = client._http_get("/api/alarms/now")
                            if resp.status_code == 200:
                                nxt = resp.json().get("next_alarm")
                                if nxt and nxt.get("fired"):
                                    resp2 = client._http_post(f"/api/alarms/{nxt['id']}/dismiss")
                                    if resp2.status_code == 200:
                                        print(f"\n  \U0001f515 闹钟 {nxt['id']} 已静音")
                                        dismissed = True
                        except Exception:
                            logging.getLogger(__name__).warning("Operation failed", exc_info=True)
                    if not dismissed:
                        print(f"\n  \U0001f515 无活跃闹钟可静音")
                    client.stop_tts()

                # ── l: 闹钟状态 ──
                elif ch.lower() == "l":
                    try:
                        resp = client._http_get("/api/alarms")
                        if resp.status_code == 200:
                            alarms = resp.json().get("alarms", [])
                            print(f"\n  \u23f0 Alarms: {len(alarms)} total")
                            for a in alarms:
                                wd = ",".join(a["days"]) if a["days"] else "每天"
                                status = "\u2705" if a["enabled"] else "\u26d4"
                                snd = f" \U0001f50a{a['sound']}" if a.get("sound") else ""
                                print(f"    {status} {a['id']} {a['time']} [{wd}] {a['message']}{snd}")
                        resp2 = client._http_get("/api/alarms/now")
                        if resp2.status_code == 200:
                            nxt = resp2.json().get("next_alarm")
                            if nxt:
                                cd = nxt.get("countdown", "?")
                                icon = "\u26a1" if nxt.get("fired") else "\U0001f514"
                                print(f"    {icon} 下次: {nxt['date']}({nxt['weekday']}) {nxt['time']} 剩{cd}")
                            else:
                                print(f"    \u23f0 无待触发闹钟")
                        resp3 = client._http_get("/api/alarms/status")
                        if resp3.status_code == 200:
                            st = resp3.json()
                            print(f"    \U0001f4ca 今日触发: {st.get('fired_today', 0)} 次")
                    except Exception as e:
                        print(f"\n  Alarm status failed: {e}")

                # ── t: 文本/图片输入（流式 SSE + TTS）──
                # 输入以 ~ 或 / 开头且指向本地图片文件时 → 以图片+附言发送（多模态）
                elif ch.lower() == "t":
                    text = raw_input("  Text/Image Input: ").strip()
                    if text:
                        if client.is_sending:
                            print("\n  \u23f3 上一轮对话还在发送中，请稍候...")
                        else:
                            image_data = _load_local_image(text)
                            if image_data:
                                note = raw_input("  附言(可空): ").strip()
                                client.send_text_async(note or "请看这张图片", image_data=image_data)
                            else:
                                client.send_text_async(text)

                # ── =: 异步任务 ──
                elif ch == "=":
                    text = raw_input("  Async Task: ").strip()
                    if text:
                        task_id = client.send_async(text)
                        if task_id:
                            async_poller.add_task(task_id)

                # ── 音乐模式音量 ──
                elif ch.lower() == "n":
                    if _music_mode:
                        v = max(0.0, player._volume - 0.1)
                        player.audio_set_volume(v)
                        _play_beep(client, 400)
                        print(f"\n  \u266a Vol: {v:.0%}")

                elif ch.lower() == "m":
                    if _music_mode:
                        v = min(1.0, player._volume + 0.1)
                        player.audio_set_volume(v)
                        _play_beep(client, 800)
                        print(f"\n  \u266a Vol: {v:.0%}")

                # ── 音乐模式控制 ──
                elif _music_mode and ch.lower() == "d":
                    player.prev()
                    _play_beep(client, 600)
                    print(f"\n  \u266a Prev \u2192 {player.current_index + 1}/{len(player.playlist)}")
                elif _music_mode and ch.lower() == "e":
                    player.toggle()
                    _play_beep(client, 800 if player.state == "playing" else 400)
                    print(f"\n  \u266a {'▶' if player.state == 'playing' else '⏸'} {player.state}")
                elif _music_mode and ch.lower() == "f":
                    player.next()
                    _play_beep(client, 600)
                    print(f"\n  \u266a Next \u2192 {player.current_index + 1}/{len(player.playlist)}")
                elif ch.lower() in ("b", "c", "d", "e", "f"):
                    pass

        except KeyboardInterrupt:
            pass
        finally:
            _cleanup(components, client, cfg)


def _cleanup(components: dict, client: DSNClient, cfg: dict) -> None:
    """统一退出清理：停后台组件、冲刷录音、持久化 chat_id。"""
    try:
        components["vision_obs"].stop()
        components["sensing_mon"].stop()
        components["player"].cleanup()
        components["async_poller"].stop()
        components["reminder"].stop()
        if components["checkin_rec"].is_recording:
            components["checkin_rec"].stop()
        recorder = components["recorder"]
        if recorder.is_recording or recorder.has_frames:
            recorder.stop_and_send()
        if client.chat_id:
            cfg["chat_id"] = client.chat_id
            save_config(cfg)
    except Exception:
        log.warning("退出清理异常", exc_info=True)
    print("\n  Goodbye")
