---
name: ncm_music_examples
category: capabilities
priority: 55
---

## 点歌示例

用户: "点一首勾指起誓"
→ `<tool>ncm_music.search_song</tool>` keyword="勾指起誓" num=3
→ "找到了《勾指起誓》- 洛天依Official/ilem · 3分3秒 · HQ 320k"

用户: "搜周杰伦的歌"
→ `<tool>ncm_music.search_song</tool>` keyword="周杰伦" num=5
→ "搜到周杰伦的几首：1.晴天 2.七里香 3.稻香 4.夜曲 5.青花瓷，想听哪首？"

用户: "把刚才那首下到本地"
→ `<tool>ncm_music.get_song_url</tool>` song_id=上次歌曲ID download=true
→ "已下载《勾指起誓》- 洛天依到本地 music/ 文件夹 (12.3MB)"

用户: "这首歌的歌词"
→ `<tool>ncm_music.get_lyrics</tool>` song_id=上下文歌曲ID save=true
→ 展示歌词 + "歌词已保存到本地"

用户: "无损来一首 一路向北"
→ `<tool>ncm_music.search_song</tool>` keyword="一路向北" quality=5
→ "找到了《一路向北》- 周杰伦 · SQ 无损品质"

用户: "本地下了多少歌了"
→ `<tool>ncm_music.list_downloaded</tool>`
→ "本地已下载 12 首歌、8 份歌词"
