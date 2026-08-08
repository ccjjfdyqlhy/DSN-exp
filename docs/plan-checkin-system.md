# 打卡系统（Check-in / Attendance）— 设计文档

## 1. 定位

打卡系统是一个**用户每日主动记录**的日志功能，同时起到**打卡坚持**的效果。
它基于 **tracking 子系统**：每次打卡的视频/音频经 tracking 媒体库存档，ASR 结果以
`【打卡】`前缀写入 tracking 用户日志。

```
minimal.py 按 [d]（第一次）
      │
      ▼
主摄像头（AI 备注为主摄像头）录像  +  麦克风录音
      │
minimal.py 按 [d]（第二次，停止）
      │
      ▼
视频 + 音频 → POST /api/checkin/record（multipart）
      │
      ▼
后端：
  1. 媒体存入 tracking 媒体库（MediaManager）
  2. 视频+音频 ffmpeg 合并存档
  3. 音频 ASR
  4. tracking 写入文本日志「【打卡】<ASR 文本>」
  5. 标记今日已打卡（4点边界归并，最早一次为有效打卡）
```

## 2. 每日规则

- **打卡日归并**：按"凌晨4点边界"——当天 0:00–3:59 的打卡归属于前一天。
  （`db.checkin_date_for`：若 `hour < 4` 则日期减一天。）
- **每天多次打卡**：每天有多次打卡机会，只要打一次即为有效日。
- **有效打卡**：同一打卡日内**最早一次**打卡记录为当日有效打卡（`is_valid=1`），
  其余为附加记录（`is_valid=0`）。

## 3. 数据库

在 `chats.db` 新增 `checkins` 表：

```sql
CREATE TABLE checkins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    checkin_date TEXT NOT NULL,   -- 4点边界归并的日期 (YYYY-MM-DD)
    checkin_time TEXT NOT NULL,   -- 本次打卡时刻 (HH:MM:SS)
    media_path TEXT DEFAULT '',   -- 合并后的存档路径
    video_path TEXT DEFAULT '',
    audio_path TEXT DEFAULT '',
    text TEXT DEFAULT '',         -- 【打卡】+ ASR 文本
    is_valid INTEGER DEFAULT 1,   -- 当日有效打卡（最早一次=1）
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

方法：`checkin_date_for` / `add_checkin` / `get_today_checkin` /
`get_valid_checkin_time` / `count_checkin_days` / `query_checkins`。

## 4. 后端 API（api/checkin.py）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/checkin/record` | POST | 接收 video/audio（multipart）+ 可选 text；保存媒体、合并、ASR、写 tracking、标记打卡 |
| `/api/checkin/status` | GET | 今日是否已打卡、今日最早打卡时间、累计天数 |
| `/api/checkin/history` | GET | 打卡历史（时间倒序） |

record 流程：
1. 保存视频/音频进 tracking 媒体库（`MediaManager.save_audio` / `save_file`）
2. ffmpeg 合并为 mp4（无则退回单独文件）
3. ASR 音频（`boot.asr_model`）；若用户带了 text 则优先用
4. `tracking.record_text(content="【打卡】...", source="checkin")`
5. `db.add_checkin(...)` 标记今日打卡

## 5. 前端（psychoscope/minimal.py）

- **`CheckinRecorder`** 类：管理打卡录制会话。
  - `start()`：解析主摄像头（AI 备注含"主/用户/正面"的摄像头，回退 `CAMERA_DEVICE_ID`），
    用 cv2 `VideoCapture` 录像 + `PvRecorder` 录音；让闲置监听让出麦克风（`_SENSING_PAUSE`）。
  - `stop()`：停止录制，音频 PCM→WAV，multipart 上传 `/api/checkin/record`，清理临时文件。
- **按键**：
  - `[d]` 打卡：按下开始录制，再按停止上传（音乐模式下 d 为上一首，让位）。
  - `[c]` 打卡状态：显示今日是否已打卡、打卡时间、累计天数。

## 6. 与 tracking 的关系

- 媒体存档复用 `tracking.media`（MediaManager）。
- ASR 文本以 `【打卡】` 前缀写入 `tracking_events`（etype=text, source=checkin），
  与闲时感知（sensing）的记录可被 AI 通过 `query_observations` 统一检索。

## 7. 主 AI 查询工具

在 `TrackingTools` 中新增 `query_checkin_stats`（已注册到 `skills/system/skill.yaml`）：

- 返回：`total_days`（累计打卡天数）、`streak`（连续打卡天数）、
  `today_checked`（今日是否已打卡）、`today_checkin_time`、`recent`（最近记录）。
- 用户问「我打卡多少天了」「连续打卡几天」「今天打卡了吗」时 AI 调用。
- 严格按当前用户隔离；未开启 `TRACKING_AI_ACCESS_ENABLED` 时拒绝。

连续打卡天数由 `db.compute_checkin_streak` 计算：以今天为基准从 `checkin_date`
往前数连续天数；若今天未打卡则从昨天开始数（保持"截至最近一次"的连续）。

## 8. Web Admin 打卡日历面板

- **侧边栏**：新增「打卡日历」页（`web_admin/templates/dashboard.html` 的
  `pageHandlers.checkin`）。
- **大字体连续天数**：顶部 `checkin-streak` 渐变卡片，56px 大字显示连续打卡天数；
  旁有累计天数、今日打卡状态、今日打卡时间统计卡。
- **本月日历**：`calendar-grid` 七列网格展示当月日期，打卡日高亮为绿色可点击；
  支持「上月/下月」切换；当日有蓝色描边。
- **点打卡日看视频**：点击打卡日 → `showDayVideos` 展示当日所有打卡记录
  （含有效/附加徽章、打卡时间、ASR 文本、播放按钮）→ 点「播放视频」在
  `<video>` 中播放。
- **后端端点**（`web_admin/routes.py`）：
  - `GET /api/admin/checkin/calendar?uid=&year=&month=` — 连续/累计天数 + 月历数据。
  - `GET /api/admin/checkin/video?path=&admin_token=` — 带 HTTP Range 支持的视频播放，
    并限制只能访问 `TRACKING_MEDIA_ROOT` 下的文件（越权返回 403）。
- 视频播放的 `admin_token` 走 query 参数（`<video>` 标签无法携带自定义头），
  `server.py` 的 `check_auth` 已放行 query token。
