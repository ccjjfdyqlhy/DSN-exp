---
name: ncm_music_examples
category: capabilities
priority: 55
---

## 登录示例

用户: "怎么登录网易云"
→
"网易云音乐功能需要登录才能使用高音质和下载。
有两种方式：

**方式一（推荐）**：让管理员在 `skills/builtin/ncm_music/skill.env` 中填入 `NCM_MUSIC_U=...`，每次启动自动登录。

**方式二**：现在手动获取 MUSIC_U：
1. 浏览器打开 https://music.163.com 并登录
2. F12 → Application → Cookies → music.163.com
3. 找到 MUSIC_U 并复制值，传给我"

→
<tool>
{
  "skill": "ncm_music",
  "tool": "login",
  "params": {"music_u": "用户的MUSIC_U值"}
}
</tool>
→ "登录成功！用户: xxx"

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
→ "找到了《勾指起誓》- 洛天依Official/ilem · 3分3秒"

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
→ "已下载《勾指起誓》到本地 music/ 文件夹 (12.3MB)"

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
→ "找到了《一路向北》- 周杰伦"

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
