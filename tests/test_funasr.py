import numpy as np
import threading
import queue
import time
from funasr import AutoModel
from pvrecorder import PvRecorder

class RealtimeSpeechSystem:
    def __init__(self, 
                 keywords=None,
                 trigger_callback=None,
                 sample_rate=16000,
                 silence_threshold=500,
                 frame_length=512):  # PvRecorder使用帧长度而不是chunk_size
        """
        初始化实时语音识别系统（使用PvRecorder替代PyAudio）
        """
        self.keywords = keywords or []
        self.trigger_callback = trigger_callback
        self.sample_rate = sample_rate
        self.silence_threshold = silence_threshold / 1000
        self.frame_length = frame_length  # 每帧采样点数，512约32ms
        
        # 状态变量
        self.is_recording = False
        self.is_speaking = False
        self.speech_frames = []
        self.silence_start = None
        self.audio_queue = queue.Queue()
        
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
        
        # 选择设备索引（-1表示默认）
        self.device_index = -1
        
    def _list_audio_devices(self):
        """列出可用的音频设备"""
        print("\n可用音频设备:")
        for idx, device in enumerate(PvRecorder.get_available_devices()):
            print(f"  [{idx}] {device}")
        print()
        
    def start(self):
        """启动实时识别系统"""
        self.is_recording = True
        
        # 创建录音器
        self.recorder = PvRecorder(
            device_index=self.device_index,
            frame_length=self.frame_length
        )
        
        # 启动音频采集线程
        self.audio_thread = threading.Thread(target=self._audio_capture)
        self.audio_thread.start()
        
        # 启动识别处理线程
        self.process_thread = threading.Thread(target=self._process_audio)
        self.process_thread.start()
        
        print("语音识别系统已启动，等待语音输入...")
        print(f"关键词检测: {self.keywords}")
        
    def stop(self):
        """停止系统"""
        self.is_recording = False
        self.recorder.delete()
        self.audio_thread.join()
        self.process_thread.join()
        print("系统已停止")
        
    def _audio_capture(self):
        """音频采集线程：持续从麦克风读取音频"""
        try:
            self.recorder.start()
            
            while self.is_recording:
                # 读取一帧音频（已转换为int16格式）
                frame = self.recorder.read()
                
                # 转换为numpy数组用于能量计算
                audio_np = np.array(frame, dtype=np.int16).astype(np.float32) / 32768.0
                
                # 计算能量判断是否有人声
                energy = np.sqrt(np.mean(audio_np**2))
                
                # VAD逻辑
                if energy > 0.01:  # 有声音
                    if not self.is_speaking:
                        # 语音开始
                        self.is_speaking = True
                        self.speech_frames = []
                        self.silence_start = None
                        print("\n[检测到语音]")
                    
                    self.speech_frames.append(audio_np)
                    self.silence_start = None  # 重置静音计时器
                    
                else:  # 静音
                    if self.is_speaking:
                        if self.silence_start is None:
                            self.silence_start = time.time()
                        elif time.time() - self.silence_start > 5.0:  # 改为 5 秒
                            # 静音时间超过 5 秒，语音结束
                            self.is_speaking = False
                            print("[语音结束，准备识别]")
                            if self.speech_frames:
                                speech_audio = np.concatenate(self.speech_frames)
                                self.audio_queue.put(speech_audio)
                            self.speech_frames = []
                            self.silence_start = None
                            
        except Exception as e:
            print(f"音频采集错误: {e}")
        finally:
            self.recorder.stop()
        
    def _process_audio(self):
        """处理线程：对语音片段进行识别和关键词检测"""
        while self.is_recording:
            try:
                audio = self.audio_queue.get(timeout=0.5)
                
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
                        self._check_keywords(text)
                        
            except queue.Empty:
                continue
            except Exception as e:
                print(f"识别错误: {e}")
                
    def _check_keywords(self, text):
        """检测文本中是否包含关键词并触发操作"""
        if not self.keywords:
            return
            
        matched = [kw for kw in self.keywords if kw in text]
        
        if matched and self.trigger_callback:
            print(f"\n🚨 关键词触发: {matched}")
            self.trigger_callback(text, matched)
            
    def set_keywords(self, keywords):
        """动态更新关键词列表"""
        self.keywords = keywords
        print(f"关键词已更新: {keywords}")


def on_keyword_detected(text, matched_keywords):
    """关键词触发时的回调函数"""
    print(f"🎯 执行触发操作！识别文本: {text}, 命中词: {matched_keywords}")
    # 在这里添加你的自定义操作


if __name__ == "__main__":
    system = RealtimeSpeechSystem(
        keywords=["报警", "紧急", "help", "救命"],
        trigger_callback=on_keyword_detected,
        silence_threshold=500
    )
    
    try:
        system.start()
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n用户中断")
        system.stop()