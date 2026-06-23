---
name: ncm_music_examples
category: capabilities
priority: 55
---

## 点歌示例

用户: "点一首勾指起誓"
→
<tool>
{
  "skill": "ncm_music",
  "tool": "search_song",
  "params": {"keyword": "勾指起誓", "num": 3}
}
</tool>
→ "找到了《勾指起誓》- 洛天依Official/ilem · 3分3秒 · HQ 320k"

用户: "搜周杰伦的歌"
→
<tool>
{
  "skill": "ncm_music",
  "tool": "search_song",
  "params": {"keyword": "周杰伦", "num": 5}
}
</tool>
→ "搜到周杰伦的几首：1.晴天 2.七里香 3.稻香 4.夜曲 5.青花瓷，想听哪首？"

用户: "把刚才那首下到本地"
→
<tool>
{
  "skill": "ncm_music",
  "tool": "get_song_url",
  "params": {"song_id": "上次歌曲ID", "download": true}
}
</tool>
→ "已下载《勾指起誓》- 洛天依到本地 music/ 文件夹 (12.3MB)"

用户: "这首歌的歌词"
→
<tool>
{
  "skill": "ncm_music",
  "tool": "get_lyrics",
  "params": {"song_id": "上下文歌曲ID", "save": true}
}
</tool>
→ 展示歌词 + "歌词已保存到本地"

用户: "无损来一首 一路向北"
→
<tool>
{
  "skill": "ncm_music",
  "tool": "search_song",
  "params": {"keyword": "一路向北", "quality": 5}
}
</tool>
→ "找到了《一路向北》- 周杰伦 · SQ 无损品质"

用户: "本地下了多少歌了"
→
<tool>
{
  "skill": "ncm_music",
  "tool": "list_downloaded",
  "params": {}
}
</tool>
→ "本地已下载 12 首歌、8 份歌词"
