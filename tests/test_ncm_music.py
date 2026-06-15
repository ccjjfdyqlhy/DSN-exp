#!/usr/bin/env python3
"""NCM 音乐技能交互式测试"""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from skills.builtin.ncm_music.tools.ncm_api import NCMApi


def main():
    api = NCMApi()
    print(f"音乐目录: {api._music_dir}")
    print()

    while True:
        # 1. 搜索
        keyword = input("搜索关键词 (q 退出): ").strip()
        if not keyword:
            continue
        if keyword.lower() == "q":
            print("再见！")
            break

        print(f"搜索中...")
        r = api.search_song(keyword=keyword, num=8)
        if not r["success"]:
            print(f"  搜索失败: {r.get('error')}")
            continue

        songs = r.get("songs", [])
        if not songs:
            print("  未找到结果")
            continue

        print(f"\n  找到 {len(songs)} 首:\n")
        for i, s in enumerate(songs):
            duration = s.get("duration", "?")
            singer = s.get("singer", "?")
            quality = s.get("quality", "")
            print(f"  [{i+1}] {s['name']} — {singer}  {duration}  {quality}")

        # 2. 选择
        print()
        choice = input(f"选一首下载 (1-{len(songs)}, b=返回, q=退出): ").strip()
        if choice.lower() == "q":
            print("再见！")
            break
        if choice.lower() == "b":
            continue
        try:
            idx = int(choice) - 1
            if idx < 0 or idx >= len(songs):
                print("  序号无效")
                continue
        except ValueError:
            print("  请输入数字")
            continue

        song = songs[idx]
        print(f"\n  已选择: {song['name']} — {song['singer']}")

        # 3. 获取 URL 并下载
        # 先尝试获取播放链接
        print("  获取播放链接...")
        url_r = api.get_song_url(keyword=f"{song['name']} {song['singer']}", choose=1, download=True)

        if not url_r["success"]:
            print(f"  获取链接失败: {url_r.get('error')}")
            continue

        if not url_r.get("has_playable_url"):
            print(f"  ⚠ {url_r.get('note', '该歌曲暂无播放链接')}")
            # 仍然尝试获取歌词
            print("  尝试获取歌词...")
            lr = api.get_lyrics(song_id=song["id"], save=True)
            if lr["success"]:
                saved = lr.get("saved_to", {})
                print(f"  歌词已保存: {saved.get('txt_path', '?')}")
                print(f"  歌词预览: {lr['data']['plain'][:120]}...")
            continue

        dl = url_r.get("downloaded", {})
        if dl.get("success"):
            print(f"  ✅ 下载完成: {dl.get('filename')} ({dl.get('size_human')})")
            print(f"  路径: {dl.get('path')}")
        else:
            print(f"  ❌ 下载失败: {dl.get('error')}")

        # 4. 获取歌词
        print("  获取歌词...")
        lr = api.get_lyrics(song_id=song["id"], save=True)
        if lr["success"]:
            saved = lr.get("saved_to", {})
            print(f"  歌词已保存: {saved.get('lrc_path', '?')}")
            plain = lr["data"]["plain"]
            preview = plain[:150].replace("\n", " | ")
            print(f"  歌词预览: {preview}...")
        else:
            print(f"  歌词获取失败: {lr.get('error')}")

        print()
        again = input("继续搜索? (y/n, 默认 y): ").strip().lower()
        if again == "n":
            print("再见！")
            break
        print()


if __name__ == "__main__":
    main()
