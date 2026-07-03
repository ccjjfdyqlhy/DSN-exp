import vlc
import time

# 创建播放器
p = vlc.MediaPlayer("/home/darkstar/DSN-exp/logs/tts_history/20260622_193100_121_e0b0b658_sync.wav")

# 获取媒体时长（必须先设置媒体并解析元数据）
media = p.get_media()          # 获取当前媒体对象
media.parse()                  # 解析元数据（阻塞，确保时长可用）
duration_ms = media.get_duration()  # 时长（毫秒）

if duration_ms <= 0:
    print("无法获取音频时长，可能文件无效或格式不支持")
    p.release()
    exit(1)

duration_sec = duration_ms / 1000.0
print(f"音频时长：{duration_sec:.2f} 秒")

# 开始播放
p.play()

# 等待播放完成（加上一点点缓冲时间，确保尾部音频播放完整）
time.sleep(duration_sec + 0.2)

# 停止并释放资源
p.stop()
p.release()
print("播放完成，资源已释放。")