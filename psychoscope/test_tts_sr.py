#!/usr/bin/env python3
# psychoscope/test_tts_sr.py
# 读取 temp/ 目录下的 TTS WAV 文件，打印采样率等信息
#
# 用法: python test_tts_sr.py

import os
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
TTS_DIR = HERE / "temp"


def scan():
    """扫描 temp/ 目录中的所有 .wav 文件，读取并打印采样率"""
    if not TTS_DIR.exists():
        print(f" temp/ 目录不存在，请先运行 minimal.py 产生一些 TTS 音频")
        return None

    wav_files = sorted(TTS_DIR.glob("*.wav"))
    if not wav_files:
        print(f" temp/ 中没有 .wav 文件，请先运行 minimal.py 说几句话")
        return None

    rates = {}
    total_duration = 0.0
    for f in wav_files:
        with wave.open(str(f), 'rb') as wf:
            sr = wf.getframerate()
            ch = wf.getnchannels()
            sw = wf.getsampwidth()
            frames = wf.getnframes()
            dur = frames / sr if sr > 0 else 0
            total_duration += dur
            key = f"sr={sr} ch={ch} bits={sw*8}"
            rates[key] = rates.get(key, 0) + 1
            print(f"  {f.name:30s}  {sr}Hz  {ch}ch  {sw*8}bit  {frames} frames  {dur:.2f}s")

    print(f"\n  共 {len(wav_files)} 个文件, 总时长 {total_duration:.1f}s")
    print(f"\n  采样率分布:")
    for key, count in rates.items():
        print(f"    {key}: {count} 个")
    return rates


if __name__ == "__main__":
    scan()
