import os
import sys
import time
import threading
import webbrowser
import urllib.parse
import base64
import tempfile
import subprocess
import pygame
import wave
import io
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional, Dict, Any

import requests
from cryptography.fernet import Fernet

# ---------- 配置 ----------
SERVER_BASE_URL = "http://localhost:5000"
LOCAL_CALLBACK_PORT = 5001
TOKEN_FILE = "token.enc"
KEY_FILE = "secret.key"
# -------------------------

def get_or_create_key() -> bytes:
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "rb") as f:
            key = f.read()
    else:
        key = Fernet.generate_key()
        with open(KEY_FILE, "wb") as f:
            f.write(key)
        try:
            os.chmod(KEY_FILE, 0o600)
        except:
            pass
    return key

cipher = Fernet(get_or_create_key())
local_server: Optional[HTTPServer] = None
tts_enabled = True  # 默认启用 TTS


class TokenHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/callback":
            qs = urllib.parse.parse_qs(parsed.query)
            token_list = qs.get("token", [])
            if token_list:
                token = token_list[0]
                encrypted = cipher.encrypt(token.encode())
                with open(TOKEN_FILE, "wb") as f:
                    f.write(encrypted)
                self.send_response(200)
                self.send_header("Content-type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"<html><body><h1>Login Success.</h1><p>You can close this window now.</p></body></html>")
                threading.Thread(target=shutdown_server).start()
            else:
                self.send_error(400, "Missing token")
        else:
            self.send_error(404)

    def log_message(self, format, *args):
        pass


def shutdown_server():
    time.sleep(1)
    global local_server
    if local_server:
        local_server.shutdown()
        local_server.server_close()


def get_stored_token() -> Optional[str]:
    if not os.path.exists(TOKEN_FILE):
        return None
    try:
        with open(TOKEN_FILE, "rb") as f:
            encrypted = f.read()
        token = cipher.decrypt(encrypted).decode()
        return token
    except Exception as e:
        print(f"读取 token 失败: {e}")
        return None


def save_token(token: str):
    encrypted = cipher.encrypt(token.encode())
    with open(TOKEN_FILE, "wb") as f:
        f.write(encrypted)


def login():
    global local_server
    server_address = ("", LOCAL_CALLBACK_PORT)
    try:
        local_server = HTTPServer(server_address, TokenHandler)
    except OSError as e:
        print(f"无法启动本地回调服务器（端口 {LOCAL_CALLBACK_PORT} 可能被占用）: {e}")
        sys.exit(1)

    thread = threading.Thread(target=local_server.serve_forever, daemon=True)
    thread.start()

    client_redirect = f"http://localhost:{LOCAL_CALLBACK_PORT}/callback"
    try:
        resp = requests.get(
            f"{SERVER_BASE_URL}/api/auth/start",
            params={"redirect_uri": client_redirect},
            timeout=10
        )
        if resp.status_code != 200:
            raise RuntimeError(f"获取授权 URL 失败: {resp.text}")
        auth_url = resp.json()["auth_url"]
    except Exception as e:
        print(f"连接服务端失败: {e}")
        sys.exit(1)

    webbrowser.open(auth_url)
    print("请在浏览器中完成授权...")

    timeout = 120
    while timeout > 0 and not os.path.exists(TOKEN_FILE):
        time.sleep(1)
        timeout -= 1

    if not os.path.exists(TOKEN_FILE):
        print("登录超时")
        sys.exit(1)

    print("登录成功！")


def get_headers():
    token = get_stored_token()
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}

def play_audio(audio_bytes: bytes):
    """播放音频字节数据，使用 pygame 库直接播放内存中的 wav"""
    if not audio_bytes:
        return
    try:
        pygame.mixer.init()
        sound = pygame.mixer.Sound(io.BytesIO(audio_bytes))
        sound.play()
        # 等待播放结束（pygame 播放是异步的）
        while pygame.mixer.get_busy():
            pygame.time.wait(100)
        pygame.mixer.quit()
    except Exception as e:
        print(f"播放音频失败: {e}")

def send_message(chat_id: Optional[int], chat_name: str, message: str, tts_enabled: bool = True) -> Dict[str, Any]:
    payload = {"message": message, "chat_name": chat_name, "tts_enabled": tts_enabled}
    if chat_id is not None:
        payload["chat_id"] = chat_id
    resp = requests.post(
        f"{SERVER_BASE_URL}/api/chat/send",
        json=payload,
        headers=get_headers(),
        timeout=60  # 增加超时以容纳音频传输
    )
    resp.raise_for_status()
    return resp.json()


def list_chats():
    resp = requests.get(f"{SERVER_BASE_URL}/api/chat/list", headers=get_headers())
    resp.raise_for_status()
    return resp.json()["chats"]


def get_chat_history(chat_id: int):
    resp = requests.get(f"{SERVER_BASE_URL}/api/chat/{chat_id}", headers=get_headers())
    resp.raise_for_status()
    return resp.json()["messages"]


def print_history(messages):
    for msg in messages:
        role = "👤 用户" if msg["role"] == "user" else "🤖 助手"
        print(f"{role}: {msg['content']}")
    print()


def main():
    print("=== DeepSeek 聊天客户端（支持 TTS）===")
    token = get_stored_token()
    if not token:
        print("未检测到登录信息，开始登录流程...")
        try:
            login()
        except Exception as e:
            print(f"登录失败: {e}")
            return
    else:
        print("已使用本地 token 登录。")

    global tts_enabled
    current_chat_id = None
    current_chat_name = None

    while True:
        print("\n===== 主菜单 =====")
        print("1. 开始新对话")
        print("2. 选择历史对话")
        print("3. 退出")
        choice = input("请输入数字: ").strip()

        if choice == "1":
            name = input("请输入对话名称（留空为'未命名'）: ").strip()
            if not name:
                name = "未命名"
            print(f"进入新对话 '{name}'，输入 /exit 返回主菜单，输入 /tts {{on/off}} 切换 TTS")
            current_chat_id = None
            current_chat_name = name

            while True:
                user_msg = input("你: ")
                if user_msg.lower() == "/exit":
                    break
                if user_msg.lower().startswith("/tts"):
                    parts = user_msg.split()
                    if len(parts) == 2 and parts[1].lower() in ["on", "off"]:
                        tts_enabled = parts[1].lower() == "on"
                        status = "启用" if tts_enabled else "禁用"
                        print(f"[TTS 已{status}]")
                    else:
                        print("[用法] /tts {{on|off}}")
                    continue
                try:
                    result = send_message(current_chat_id, current_chat_name, user_msg, tts_enabled)
                    print(f"助手: {result['reply']}")
                    if result.get("tts_error"):
                        print(f"[TTS 错误] {result['tts_error']}")
                    if result.get("audio"):
                        audio_bytes = base64.b64decode(result["audio"])
                        play_audio(audio_bytes)
                    if current_chat_id is None:
                        current_chat_id = result["chat_id"]
                        print(f"[对话已保存，ID: {current_chat_id}]")
                except Exception as e:
                    print(f"发送失败: {e}")

        elif choice == "2":
            try:
                chats = list_chats()
                if not chats:
                    print("暂无历史对话。")
                    continue
                print("\n历史对话列表：")
                for idx, c in enumerate(chats, 1):
                    print(f"{idx}. {c['chat_name']} (ID: {c['chat_id']}, 消息数: {c['message_count']})")
                sel = input("请输入序号进入对话（直接回车返回）: ").strip()
                if not sel:
                    continue
                try:
                    idx = int(sel) - 1
                    if 0 <= idx < len(chats):
                        chat = chats[idx]
                        chat_id = chat["chat_id"]
                        chat_name = chat["chat_name"]
                        history = get_chat_history(chat_id)
                        print(f"\n===== 进入对话 '{chat_name}' =====")
                        print(f"[提示] 输入 /exit 返回主菜单，输入 /tts {{on/off}} 切换 TTS")
                        print_history(history)

                        current_chat_id = chat_id
                        current_chat_name = chat_name
                        while True:
                            user_msg = input("你: ")
                            if user_msg.lower() == "/exit":
                                break
                            if user_msg.lower().startswith("/tts"):
                                parts = user_msg.split()
                                if len(parts) == 2 and parts[1].lower() in ["on", "off"]:
                                    tts_enabled = parts[1].lower() == "on"
                                    status = "启用" if tts_enabled else "禁用"
                                    print(f"[TTS 已{status}]")
                                else:
                                    print("[用法] /tts {{on|off}}")
                                continue
                            try:
                                result = send_message(current_chat_id, current_chat_name, user_msg, tts_enabled)
                                print(f"助手: {result['reply']}")
                                if result.get("tts_error"):
                                    print(f"[TTS 错误] {result['tts_error']}")
                                if result.get("audio"):
                                    audio_bytes = base64.b64decode(result["audio"])
                                    play_audio(audio_bytes)
                            except Exception as e:
                                print(f"发送失败: {e}")
                    else:
                        print("无效序号")
                except ValueError:
                    print("请输入数字")
            except Exception as e:
                print(f"获取历史对话失败: {e}")

        elif choice == "3":
            print("再见！")
            break
        else:
            print("无效选择，请重新输入")


if __name__ == "__main__":
    try:
        main()
    finally:
        if local_server:
            local_server.shutdown()
            local_server.server_close()