import numpy as np
import threading
import queue
import time
import os
import sys
import base64
import io
import pygame
import requests
from pvrecorder import PvRecorder
from funasr import AutoModel

# ---------- 配置（从 cli.py 复制）----------
SERVER_BASE_URL = "http://localhost:5000"
TOKEN_FILE = "token.enc"
KEY_FILE = "secret.key"
# -------------------------

# ---------- 识别模式开关 ----------
ASR_MODE_AUTO = False          # True: 自动语音触发模式（检测到静默后自动识别）
                              # False: 按Enter键触发模式（需手动按Enter键触发识别）
# -------------------------

# 全局打断TTS播放标志
stop_audio_playback = False

# 从 cli.py 复制的辅助函数
def get_or_create_key() -> bytes:
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "rb") as f:
            key = f.read()
    else:
        from cryptography.fernet import Fernet
        key = Fernet.generate_key()
        with open(KEY_FILE, "wb") as f:
            f.write(key)
        try:
            os.chmod(KEY_FILE, 0o600)
        except:
            pass
    return key

from cryptography.fernet import Fernet
cipher = Fernet(get_or_create_key())

def get_stored_token() -> str:
    if not os.path.exists(TOKEN_FILE):
        raise RuntimeError("未找到 token，请先运行 cli.py 登录")
    try:
        with open(TOKEN_FILE, "rb") as f:
            encrypted = f.read()
        token = cipher.decrypt(encrypted).decode()
        return token
    except Exception as e:
        raise RuntimeError(f"读取 token 失败: {e}")

def get_headers():
    token = get_stored_token()
    return {"Authorization": f"Bearer {token}"}

# 全局播放状态标志
is_playing_audio = False

def play_audio(audio_bytes: bytes, system_ref=None):
    """播放音频字节数据，使用 pygame，播放期间禁用语音识别"""
    if not audio_bytes:
        return
    global is_playing_audio, stop_audio_playback
    try:
        # 标记正在播放
        is_playing_audio = True
        if system_ref:
            system_ref.is_playing_audio = True
        
        pygame.mixer.init()
        sound = pygame.mixer.Sound(io.BytesIO(audio_bytes))
        sound.play()
        
        # 等待播放结束，但允许被打断
        while pygame.mixer.get_busy():
            if stop_audio_playback:
                pygame.mixer.stop()
                stop_audio_playback = False
                break
            pygame.time.wait(100)
        pygame.mixer.quit()
    except Exception as e:
        print(f"播放音频失败: {e}")
    finally:
        # 播放完毕后增加缓冲延迟，避免TTS残余音被录进去
        time.sleep(1.5)
        # 恢复语音识别
        is_playing_audio = False
        if system_ref:
            system_ref.is_playing_audio = False

def send_message(chat_id: int, chat_name: str, message: str, tts_enabled: bool = True, is_asr_input: bool = False) -> dict:
    payload = {"message": message, "chat_name": chat_name, "tts_enabled": tts_enabled, "is_asr_input": is_asr_input}
    if chat_id is not None:
        payload["chat_id"] = chat_id
    resp = requests.post(
        f"{SERVER_BASE_URL}/api/chat/send",
        json=payload,
        headers=get_headers(),
        timeout=60
    )
    resp.raise_for_status()
    return resp.json()

def list_chats() -> list:
    """获取聊天列表"""
    resp = requests.get(f"{SERVER_BASE_URL}/api/chat/list", headers=get_headers())
    resp.raise_for_status()
    return resp.json()["chats"]

def get_or_find_instant_chat() -> int:
    """获取或查找'即时对话'聊天，不存在则返回 None 让系统自动创建"""
    try:
        chats = list_chats()
        for chat in chats:
            if chat["chat_name"] == "即时对话":
                print(f"[已连接到聊天: 即时对话 (ID: {chat['chat_id']})]")
                return chat["chat_id"]
        # 如果不存在，返回 None，第一次 send_message 时会自动创建
        print("[将在第一次发送消息时创建: 即时对话]")
        return None
    except Exception as e:
        print(f"获取聊天列表失败: {e}")
        # 异常时也返回 None，让系统自动创建
        return None

# 从 test_funasr.py 复制并修改的 RealtimeSpeechSystem 类
class RealtimeSpeechSystem:
    def __init__(self, 
                 sample_rate=16000,
                 silence_threshold=500,
                 frame_length=512):
        self.sample_rate = sample_rate
        self.silence_threshold = silence_threshold / 1000
        self.frame_length = frame_length
        
        # 状态变量
        self.is_recording = False
        self.is_speaking = False
        self.speech_frames = []
        self.silence_start = None
        self.audio_queue = queue.Queue()
        self.waiting_for_input = False
        self.is_playing_audio = False  # TTS 播放中标志
        self.chat_id = None
        self.chat_name = "即时对话"
        self.recognize_triggered = False  # Enter键触发标志
        
        # 初始化FunASR模型
        print("正在加载FunASR模型...")
        self.model = AutoModel(
            model="paraformer-zh",
            model_revision="v2.0.4",
            vad_model="fsmn-vad",
            vad_model_revision="v2.0.4",
            punc_model="ct-punc-c",
            punc_model_revision="v2.0.4",
            device="cuda",
            disable_update=True,
            disable_pbar=True
        )
        print("模型加载完成")
        
        # 获取麦克风设备列表
        self._list_audio_devices()
        self.device_index = -1
        
    def _list_audio_devices(self):
        print("\n可用音频设备:")
        for idx, device in enumerate(PvRecorder.get_available_devices()):
            print(f"  [{idx}] {device}")
        print()
        
    def start(self):
        self.is_recording = True
        self.recorder = PvRecorder(
            device_index=self.device_index,
            frame_length=self.frame_length
        )
        self.audio_thread = threading.Thread(target=self._audio_capture)
        self.audio_thread.start()
        self.process_thread = threading.Thread(target=self._process_audio)
        self.process_thread.start()
        
        # 如果是按Enter键触发模式，启动输入监听线程
        if not ASR_MODE_AUTO:
            self.input_thread = threading.Thread(target=self._listen_enter_key, daemon=True)
            self.input_thread.start()
            print("语音识别系统已启动，按 Enter 键触发识别")
        else:
            print("语音识别系统已启动，等待语音输入...")
        
    def stop(self):
        self.is_recording = False
        self.recorder.delete()
        self.audio_thread.join()
        self.process_thread.join()
        print("系统已停止")
        
    def _audio_capture(self):
        try:
            self.recorder.start()
            while self.is_recording:
                # 在自动模式下，播放TTS时跳过语音识别；按键模式下允许中断
                if self.is_playing_audio and ASR_MODE_AUTO:
                    self.recorder.read()
                    continue
                
                frame = self.recorder.read()
                audio_np = np.array(frame, dtype=np.int16).astype(np.float32) / 32768.0
                
                # 计算能量判断是否有人声
                energy = np.sqrt(np.mean(audio_np**2))
                
                # VAD逻辑
                if energy > 0.01:
                    if not self.is_speaking:
                        self.is_speaking = True
                        self.speech_frames = []
                        self.silence_start = None
                        print("\n[检测到语音]")
                    
                    self.speech_frames.append(audio_np)
                    self.silence_start = None
                    
                else:
                    if self.is_speaking:
                        if self.silence_start is None:
                            self.silence_start = time.time()
                        elif time.time() - self.silence_start > 1.0:
                            self.is_speaking = False
                            # 自动模式：直接识别；按键模式：等待触发标志
                            if ASR_MODE_AUTO:
                                print("[语音结束，准备识别]")
                                if self.speech_frames:
                                    speech_audio = np.concatenate(self.speech_frames)
                                    self._recognize_and_send(speech_audio)
                            elif self.recognize_triggered:
                                print("[已按Enter，开始识别]")
                                if self.speech_frames:
                                    speech_audio = np.concatenate(self.speech_frames)
                                    self._recognize_and_send(speech_audio)
                                self.recognize_triggered = False
                            self.speech_frames = []
                            self.silence_start = None
        except Exception as e:
            print(f"音频采集错误: {e}")
        finally:
            self.recorder.stop()
        
    def _recognize_and_send(self, audio):
        """识别音频并发送给AI"""
        try:
            print("[识别中...]")
            res = self.model.generate(
                input=audio,
                use_itn=True,
                batch_size_s=60,
                language="zh"
            )
            if res and len(res) > 0:
                text = res[0].get("text", "").strip()
                if text:
                    print(f"\n[识别结果] {text}")
                    # 直接发送给AI，由过滤模型决定是否处理
                    self._send_to_ai(text)
        except Exception as e:
            print(f"识别错误: {e}")
        
    def _listen_enter_key(self):
        """监听 Enter 键激发识别（按键模式）"""
        global stop_audio_playback
        while self.is_recording:
            try:
                input()
                # 如果TTS正在播放，打断它；否则检查是否有语音
                if self.is_playing_audio:
                    print("[打断TTS] 启用语音识别")
                    stop_audio_playback = True
                    # 清空当前积累的音频帧，重新开始录音
                    self.speech_frames = []
                    self.is_speaking = False
                    self.recognize_triggered = True
                elif self.is_speaking:
                    self.recognize_triggered = True
                    print("[Enter 扣下] 将执行识别")
                else:
                    print("[暂无语音] 请先说话...")
            except (EOFError, KeyboardInterrupt):
                break
        
    def _process_audio(self):
        # 保持此方法，但不进行任何操作（为了保持线程结构一致）
        while self.is_recording:
            time.sleep(0.1)
                
    def _send_to_ai(self, text):
        try:
            # 新增：标记为ASR输入
            result = send_message(self.chat_id, self.chat_name, text, tts_enabled=True, is_asr_input=True)
            if result.get("filtered"):
                # 被过滤，不显示回复
                print(f"[过滤] 识别文本被过滤: {text}")
            else:
                print(f"助手: {result['reply']}")
                # 第一次发送时更新 chat_id
                if self.chat_id is None:
                    self.chat_id = result.get("chat_id")
                if result.get("audio"):
                    audio_bytes = base64.b64decode(result["audio"])
                    play_audio(audio_bytes, system_ref=self)
        except Exception as e:
            print(f"发送失败: {e}")

# 主函数
if __name__ == "__main__":
    try:
        # 初始化聊天
        chat_id = get_or_find_instant_chat()
        
        system = RealtimeSpeechSystem(
            silence_threshold=500
        )
        system.chat_id = chat_id
        
        system.start()
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n用户中断")
        system.stop()
    except Exception as e:
        print(f"启动失败: {e}")
        sys.exit(1)
