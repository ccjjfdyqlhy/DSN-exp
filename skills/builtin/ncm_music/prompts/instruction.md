---
name: ncm_music_instruction
category: capabilities
priority: 55
---

## 网易云音乐能力

你可以使用网易云音乐 API 搜索歌曲、获取播放链接、下载音乐文件和查看歌词。

### 可用工具

`<tool>ncm_music.search_song</tool>` — 搜索歌曲
  - keyword: 搜索关键词，歌名/歌手（必填）
  - page: 页数（可选，默认1）
  - num: 每页数量（可选，默认5，最多10）
  - quality: 音质 1-9（可选，默认4=HQ 320k）
  - auto_download: 是否自动下载第一首（可选，默认false）

`<tool>ncm_music.get_song_url</tool>` — 通过 ID 获取详情+链接
  - song_id: 歌曲ID（必填）
  - quality: 音质（可选）
  - download: 是否下载（可选，默认false）

`<tool>ncm_music.get_lyrics</tool>` — 获取歌词
  - song_id: 歌曲ID（必填）
  - save: 是否保存歌词文件（可选，默认false）

`<tool>ncm_music.list_downloaded</tool>` — 列出已下载的歌曲和歌词

### 音质说明
1=标准64k  2=标准128k  3=HQ192k  4=HQ320k  5=SQ无损  6=Hi-Res  7=高清臻音  8=环绕声  9=超清母带

### 使用原则

1. 用户说"点歌/来一首/搜首歌/放歌/我想听"→ 用 search_song 搜索
2. 搜索结果返回歌曲列表后，简明展示（歌名·歌手·时长），让用户选择
3. 用户明确要"下载"或"保存"时，传 download=true 或 save=true
4. 用户提到"无损"时用 quality=5，"高音质"用 quality=4，"普通"用 quality=2
5. 用户讨论歌词时用 get_lyrics，讨论时用 plain 纯文本版本
6. 一次搜索不要返回太多（建议 5 首），让用户缩小范围
7. 已下载到本地的歌曲文件和歌词文件保存在技能目录的 music/ 文件夹下
