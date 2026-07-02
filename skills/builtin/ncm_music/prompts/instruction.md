---
name: ncm_music_instruction
category: capabilities
priority: 55
---

## 网易云音乐能力

你可以使用网易云音乐 API 搜索歌曲、获取播放链接、下载音乐文件和查看歌词。

### 功能限制说明

| 功能 | 无需登录 | 需登录 |
|------|----------|--------|
| 搜索歌曲 | ✅ | — |
| 获取歌词 | ✅ | — |
| 获取标准品质音频 (128k) | ✅ | — |
| 获取 HQ/无损/Hi-Res 音频 | ❌ | ✅ |
| 下载歌曲到本地 | ❌ | ✅ |

**未登录时** HQ 及更高品质的音频链接会返回空，AI 需要降级到 standard 品质或提示用户先登录。

### 配置方式（推荐）

管理员在 `skills/builtin/ncm_music/skill.env` 中设置：
```
NCM_MUSIC_U=从浏览器获取的MUSIC_U值
```
或在项目 `.env` 中设置 `NCM_MUSIC_U=...`，之后 `login` 工具和 `Config.NCM_MUSIC_U` 会自动读取。

### 登录（交互式）

如果未配置环境变量，也可以用 `login` 工具手动登录：
<tool>
{
  "skill": "ncm_music",
  "tool": "login",
  "params": {
    "music_u": "粘贴MUSIC_U值"
  }
}
</tool>
如何获取 MUSIC_U：
1. 浏览器打开 https://music.163.com 并登录
2. F12 → Application / 存储 → Cookies → music.163.com
3. 找到 MUSIC_U 并复制值
登录后 session 会自动保存到 `music/.pyncm_session`，后续重启不需重复登录。

### 可用工具

**搜索歌曲：**
<tool>
{
  "skill": "ncm_music",
  "tool": "search_song",
  "params": {
    "keyword": "搜索关键词",
    "num": 5
  }
}
</tool>
  - keyword: 搜索关键词，歌名/歌手（必填）
  - num: 每页数量（可选，默认5）
  - quality: 音质（可选，默认4=HQ320k，3-4=高音质，5-6=无损）

**通过 ID 获取播放链接：**
<tool>
{
  "skill": "ncm_music",
  "tool": "get_song_url",
  "params": {
    "song_id": "歌曲ID",
    "quality": 4,
    "download": false
  }
}
</tool>
  - song_id: 歌曲ID（必填）
  - quality: 音质（可选）
  - download: 是否下载到本地（可选）

**获取歌词：**
<tool>
{
  "skill": "ncm_music",
  "tool": "get_lyrics",
  "params": {
    "song_id": "歌曲ID",
    "save": true
  }
}
</tool>
  - song_id: 歌曲ID（必填）
  - save: 是否保存歌词文件（可选，默认true）

**列出已下载的歌曲和歌词：**
<tool>
{
  "skill": "ncm_music",
  "tool": "list_downloaded",
  "params": {}
}
</tool>

### 音质说明
1-2=标准128k  3-4=HQ320k  5-6=无损FLAC  7-9=Hi-Res（越高越可能需要VIP）

### 使用原则

1. 用户说"点歌/来一首/搜首歌/放歌/我想听"→ 用 search_song 搜索
2. 搜索结果返回歌曲列表后，简明展示（歌名·歌手·时长），让用户选择
3. 用户明确要"下载"或"保存"时，传 download=true 或 save=true
4. 用户提到"无损"时用 quality=5，"高音质"用 quality=4，"普通"用 quality=2
5. 用户讨论歌词时用 get_lyrics，讨论时用 plain 纯文本版本
6. 一次搜索不要返回太多（建议 5 首），让用户缩小范围
7. 已下载到本地的歌曲文件和歌词文件保存在技能目录的 music/ 文件夹下
8. 如果提示"请先登录"，引导用户获取 MUSIC_U 调用 login 工具
