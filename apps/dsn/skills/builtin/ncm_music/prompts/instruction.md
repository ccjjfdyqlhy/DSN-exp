---
name: ncm_music_instruction
category: capabilities
priority: 55
---

## 网易云音乐能力

你可以使用网易云音乐 API 搜索歌曲/专辑/歌手/歌单、获取播放链接、下载音乐、管理歌单、私人FM、MV播放、每日签到、喜欢歌曲、获取评论等。

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

### 音质说明
1-2=标准128k  3-4=HQ320k  5-6=无损FLAC  7-9=Hi-Res（越高越可能需要VIP）

### 可用工具

#### 搜索
- **search_song** — 搜索歌曲（suggestion: 默认用这个）
- **search** — 通用搜索，支持 song/album/artist/playlist/user/mv/video/dj/lyrics
- **get_album** — 获取专辑详情和曲目列表
- **get_artist** — 获取歌手资料
- **get_artist_albums** — 歌手的专辑列表
- **get_artist_tracks** — 歌手的热门歌曲

#### 歌曲操作
- **get_song_url** — 获取播放链接，song_id 或 keyword，可选 quality/download
- **get_lyrics** — 获取歌词（LRC + plain）
- **get_track_comments** — 获取歌曲评论（含热门评论）
- **like_track** — 喜欢/取消喜欢歌曲
- **get_mv** — 获取 MV 详情和播放地址

#### 歌单管理
- **get_playlist** — 歌单详情（不含完整曲目）
- **get_playlist_tracks** — 获取歌单全部歌曲
- **get_user_playlists** — 用户自己的歌单列表
- **create_playlist** — 创建新歌单
- **add_to_playlist** — 添加歌曲到歌单
- **remove_from_playlist** — 从歌单移除歌曲

#### 推荐与 FM
- **get_daily_recommend** — 每日推荐歌曲
- **get_personal_fm** — 私人 FM 随机推荐
- **skip_fm_track** — 跳过当前 FM 歌曲
- **like_fm_track** — 喜欢/取消喜欢 FM 歌曲

#### 账户
- **login** — 用 MUSIC_U Cookie 登录
- **login_logout** — 退出登录
- **get_user_detail** — 查看账户资料
- **daily_signin** — 每日签到（手机+4exp / 网页+1exp）

#### 本地文件
- **list_downloaded** — 列出已下载的歌曲和歌词
- **music_control** — 播放/暂停/切歌/调音量

### 使用原则

1. 用户说"点歌/来一首/搜首歌/放歌/我想听"→ 用 search_song 搜索
2. 搜索结果返回歌曲列表后，简明展示（歌名·歌手·时长），让用户选择
3. 用户明确要"下载"或"保存"时，传 download=true 或 save=true
4. 用户提到"无损"时用 quality=5，"高音质"用 quality=4，"普通"用 quality=2
5. 用户讨论歌词时用 get_lyrics，讨论时用 plain 纯文本版本
6. 一次搜索不要返回太多（建议 5 首），让用户缩小范围
7. 已下载到本地的歌曲和歌词保存在 workspace/<用户>/music/ 目录下，可用 `workspace_file` 工具的 `find` 或 `list_dir` 子命令查看
8. 如果提示"请先登录"，引导用户获取 MUSIC_U 调用 login 工具
9. 用户说"我收藏的歌单" → get_user_playlists；"推荐点歌" → get_daily_recommend
10. 用户说"随便放点" → get_personal_fm；"这个歌手的歌" → search 或 get_artist_tracks

### 音乐播放控制

你可以通过 `music_control` 工具控制音乐播放器（minimal.py 客户端上的 pygame 播放器）。

**查看播放状态：**
<tool>
{
  "skill": "ncm_music",
  "tool": "music_control",
  "params": {"action": "status"}
}
</tool>

**播放/切歌：**
- `{"action": "next"}` — 下一首
- `{"action": "prev"}` — 上一首
- `{"action": "pause"}` — 暂停
- `{"action": "resume"}` — 恢复播放
- `{"action": "stop"}` — 停止
- `{"action": "play", "value": "晴天.mp3"}` — 播放指定歌曲
- `{"action": "volume", "value": "0.5"}` — 调音量 0.0~1.0

**查看歌单：**
<tool>
{
  "skill": "ncm_music",
  "tool": "music_control",
  "params": {"action": "list"}
}
</tool>

**使用原则：**
- 用户说"下一首""换一首" → `next`
- 用户说"暂停""停一下" → `pause`
- 用户说"继续放" → `resume`
- 用户说"现在在放什么" → 先 `status` 获取状态，再回复用户
- 用户说"放XX歌" → 先用 `search_song` 搜索，下载后用 `play` 播放
- 客户端不在音乐模式时，播放控制命令会被排队，进入音乐模式后自动消费
