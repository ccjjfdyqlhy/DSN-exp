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

## 播放控制示例

用户: "下一首"
→
<tool>
{
  "skill": "ncm_music",
  "tool": "music_control",
  "params": {"action": "next"}
}
</tool>
→ "已切到下一首"

用户: "现在在放什么歌"
→
<tool>
{
  "skill": "ncm_music",
  "tool": "music_control",
  "params": {"action": "status"}
}
</tool>
→ "正在播放: 七里香.mp3"

用户: "暂停一下"
→
<tool>
{
  "skill": "ncm_music",
  "tool": "music_control",
  "params": {"action": "pause"}
}
</tool>
→ "已暂停"

用户: "放晴天"
→
（先搜索 → 下载 → 然后播放）
<tool>
{
  "skill": "ncm_music",
  "tool": "music_control",
  "params": {"action": "play", "value": "晴天.mp3"}
}
</tool>
→ "正在播放: 晴天.mp3"

## 搜索歌手示例

用户: "周杰伦有什么歌"
→
<tool>
{
  "skill": "ncm_music",
  "tool": "get_artist_tracks",
  "params": {"artist_id": 6452, "num": 5}
}
</tool>
→ "周杰伦热门歌曲：1.七里香 2.晴天 3.夜曲 4.稻香 5.青花瓷"

## 搜索专辑示例

用户: "查一下周杰伦的专辑《叶惠美》"
→
<tool>
{
  "skill": "ncm_music",
  "tool": "search",
  "params": {"keyword": "叶惠美 周杰伦", "search_type": "album"}
}
</tool>
→
<tool>
{
  "skill": "ncm_music",
  "tool": "get_album",
  "params": {"album_id": "上一步返回的ID"}
}
</tool>
→ "《叶惠美》是周杰伦2003年的专辑，包含晴天、以父之名等10首歌"

## 歌单管理示例

用户: "看看我收藏的歌单"
→
<tool>
{
  "skill": "ncm_music",
  "tool": "get_user_playlists",
  "params": {}
}
</tool>
→ "你有3个歌单：1.我喜欢的音乐(12首) 2.开车必备(25首) 3.深夜循环(8首)"

用户: "把这周杰伦的歌加到我的歌单"
→
（先搜到歌曲 → 然后用:）
<tool>
{
  "skill": "ncm_music",
  "tool": "add_to_playlist",
  "params": {"playlist_id": "歌单ID", "track_ids": [歌曲ID]}
}
</tool>
→ "已添加到歌单"

## 每日签到示例

用户: "签到网易云"
→
<tool>
{
  "skill": "ncm_music",
  "tool": "daily_signin",
  "params": {"type": "mobile"}
}
</tool>
→ "签到成功！手机端+4经验"

## 每日推荐示例

用户: "今天推荐什么歌"
→
<tool>
{
  "skill": "ncm_music",
  "tool": "get_daily_recommend",
  "params": {}
}
</tool>
→ "今日推荐: 1.xxx 2.xxx ..."

## 私人 FM 示例

用户: "随便放点歌听听"
→
<tool>
{
  "skill": "ncm_music",
  "tool": "get_personal_fm",
  "params": {"limit": 3}
}
</tool>
→ "FM推荐: 1.xxx 2.xxx 3.xxx 想听哪首？"

## 歌曲评论示例

用户: "看看七里香的评论"
→
<tool>
{
  "skill": "ncm_music",
  "tool": "get_track_comments",
  "params": {"track_id": 185709}
}
</tool>
→ "热门评论：'前奏一响起，仿佛回到了那个夏天...'(赞 12345)"

## 喜欢歌曲示例

用户: "这首歌太好听了，点个喜欢"
→
<tool>
{
  "skill": "ncm_music",
  "tool": "like_track",
  "params": {"track_id": "歌曲ID", "like": true}
}
</tool>
→ "已添加到我喜欢"

## MV 示例

用户: "看看七里香的MV"
→
<tool>
{
  "skill": "ncm_music",
  "tool": "get_mv",
  "params": {"mv_id": "MV ID"}
}
</tool>
→ "七里香MV(4分58秒) - 播放地址: ..."

## 歌手详情示例

用户: "查一下 Taylor Swift 的资料"
→
<tool>
{
  "skill": "ncm_music",
  "tool": "search",
  "params": {"keyword": "Taylor Swift", "search_type": "artist"}
}
</tool>
→
<tool>
{
  "skill": "ncm_music",
  "tool": "get_artist",
  "params": {"artist_id": "上一步的ID"}
}
</tool>
→ "Taylor Swift · 美国歌手 · 专辑数: 10 · 歌曲数: 178"
