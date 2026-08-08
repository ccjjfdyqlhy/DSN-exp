# 用户跟踪系统（tracking）— 设计文档

## 1. 定位

用户跟踪系统（tracking）是一个 **infra 基础设施子系统**，也是用户的**个人行为日记本**。
它的核心目的：

> 通过不断观察获取数据，以多模态方式记录用户行动（拍照 / 录像 / 录音 / 文件 / 文本），
> 建模用户作息规律 / 生活节奏 / 项目进度等各种事项，形成一份持续更新的**个人日志系统**。

它不是一个具体的对话功能，而是**数据采集 + 建模**的底层能力，供上层（闲时感知、
主 AI 技能、未来功能）复用。

```
多模态观察（拍照 / 录像 / 录音 / 文件 / 文本）
        │
        ▼
  MediaManager（媒体落盘，按用户隔离）
        │
        ▼
  tracking.db（独立加密数据库：payload/meta 经 AES-256-GCM 加密，按用户派生密钥）
        │        ├── tracking_events（统一多模态观察事件）
        │        └── tracking_models（建模结果）
        ▼
  关键词 / 时间范围搜索
        │
        ▼
  建模（作息 rhythm / 节奏 / 项目进度 progress）→ tracking_models
        │
        ▼
  AI 技能查询/添加（TrackingTools，用户启用后完全访问）→ 生成口语化答复
```

## 2. 模块结构

独立目录 `tracking/`：

| 文件 | 职责 |
|------|------|
| `tracking/__init__.py` | 包入口，导出 `TrackingEngine` / `TrackingStore` / `MediaManager` / `AudioListeningMonitor` / `VisionCapture` |
| `tracking/store.py` | 数据层：**按天分表** `tracking_events_YYYYMMDD`（每天独立单元）+ `tracking_models`（建模结果）读写 |
| `tracking/media.py` | 媒体底座：`MediaManager` 统一管理 拍照/录像/录音/任意文件 落盘，按 用户/日期/类型 分目录 |
| `tracking/core.py` | `TrackingEngine` 核心引擎：聚合多模态记录 + 建模（`record_audio/photo/video/file/text`、`capture_audio/photo/video`、`add_file/import_file/add_text`） |
| `tracking/audio_listen.py` | 聆听能力：`AudioListeningMonitor`（从原 `IdleSensingMonitor` 抽取），捕捉环境声音 |
| `tracking/vision_capture.py` | 采集能力：`VisionCapture` 拍照 / 录像 / 主动录音（infra 原语） |
| `tracking/vision_observe.py` | 主动视觉观察服务：`VisionObservationService`（替代原 active_vision 插件），照片保存 + VisionModel 描述 → 写入跟踪日志 |
| `tracking/tools.py` | AI 技能工具：`TrackingTools`（只读查询观察日志、建模作息 / 建模进度） |
| `tracking/skill.yaml` | （并入 system skill 的工具注册） |

## 3. 数据模型（独立加密数据库）

跟踪日志存放在**独立加密数据库**（默认 `tracking.db`），与主聊天库 `chats.db` 完全隔离。
所有模态数据的 `payload`（文本/识别结果/内容）与 `meta`（JSON）均经
`MessageCipher`（AES-256-GCM，密钥由 SHA-256(主密钥 + user_id) 派生）**加密后落盘**。

### tracking_events_YYYYMMDD（观察事件，按天分表）

事件**按天存放在独立的表** `tracking_events_YYYYMMDD` 中（每天一个单元，
首次写入当天自动建表），与媒体按天分目录（`<root>/<uid>/<YYYYMMDD>/<kind>/`）一致。
所有用户跟踪日志因此**分天存储在不同的单元里**。

```sql
CREATE TABLE tracking_events_20260808 (   -- 每张天表同构
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    chat_id INTEGER DEFAULT NULL,
    etype TEXT DEFAULT 'text',   -- audio | image | video | file | text | note
    payload TEXT DEFAULT '',     -- 密文：识别文本 / 描述 / 内容
    source TEXT DEFAULT 'tracking',
    meta TEXT DEFAULT '{}',      -- 密文 JSON: rms_level / media_path / duration 等
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

查询 `search_events` 跨天表聚合；时间范围 (since/until) 在表路由层过滤
（只查相关天表），关键词对解密后的 payload 做内存匹配。

### tracking_models（建模结果，不分天）

```sql
CREATE TABLE tracking_models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    model_type TEXT NOT NULL,    -- routine | rhythm | project | progress | habit
    title TEXT DEFAULT '',
    content TEXT DEFAULT '',     -- 密文
    meta TEXT DEFAULT '{}',      -- 密文 JSON
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, model_type, title)
);
```

### 搜索

- **时间范围**（since/until）：SQL 层用明文 `created_at` 过滤，高效。
- **关键词**（keyword）：对解密后的 `payload` 做包含匹配（支持多关键词，空格分隔取并集）。
- **类型**（etype）：`audio` / `image` / `video` / `file` / `text`。
- 所有查询严格按 `user_id` 隔离。

### 数据库文件位置

- `TRACKING_DB_PATH` 指定独立库路径；缺省放 `<TRACKING_MEDIA_ROOT>/../tracking/tracking.db`。
- 旧 `sensing_events`（在 `chats.db`）保留，通过 `TrackingEngine` 的 legacy_writer 回写兼容。

## 4. 与闲时感知的关系

闲时感知（仅音频）**依赖** tracking 子系统的聆听能力：

- 旧 `IdleSensingMonitor` 的"监听"逻辑抽取到 `tracking/audio_listen.py`。
- 客户端 `psychoscope/minimal.py` 的 `IdleSensingMonitor` 退化为**薄适配器**，绑定
  `AudioListeningMonitor`，transport 把捕捉到的音频转 WAV base64 上报后端
  `/api/sensing/event`。
- 后端 `/api/sensing/event` 优先写入统一 `tracking_events`（`record_audio`），并回写旧
  `sensing_events` 保持兼容。

**拍照 / 录像（`VisionCapture`）当前为 infra 能力，尚未接入闲时感知**——按需求，
现阶段仅把聆听接入闲时感知。**闲时感知只主动记录音频**，不会记录其他模态。

## 4.1 主动视觉观察服务（VisionObservationService）

替代原 `plugins/builtin/active_vision_plugin.py`（已删除），改为 tracking 子系统内的
服务，实现方式与闲时感知语音类似（不依赖插件系统）：

```
minimal.py VisionObserver 定时抓帧
  → POST /api/vision/observation → VisionObservationService.ingest_observation()
     1. 照片保存进媒体库（MediaManager，按 用户/日期/类型 分目录）→ record_photo
     2. VisionModel 生成画面描述 → record_text 写入文本日志（【视觉】前缀）
     3. 场景变化检测 → 写 task_notifications（保持主动通知能力）
```

- 记录**两种模态**：照片（image）+ 文本描述（text）。
- 与闲时感知的区别：闲时感知只记录音频；主动视觉记录照片与文本。
- boot.py 初始化服务并注入 `app.config["VISION_OBSERVATION_SERVICE"]`。

## 5. 配置

在 `config.py` 新增：

```ini
TRACKING_ENABLED=false           # 主开关（聆听能力）
TRACKING_AI_ACCESS_ENABLED=false # 允许 AI 通过技能查询/建模（只读）观察日志
TRACKING_MEDIA_ROOT=.dsn/tracking_media  # 拍照/录像/录音/文件保存根目录
TRACKING_DB_PATH=                # 独立加密库路径；为空放 <MEDIA_ROOT>/../tracking/tracking.db
TRACKING_SAVE_AUDIO=true         # 闲时感知音频是否同时保存真实 WAV（完整日记）
```

heartbeat 响应同时下发 `tracking` 与 `sensing` 字段，客户端优先用 `tracking`。

## 6. AI 技能接入

在 `skills/system/skill.yaml` 注册五个工具（模块指向
`skills/system/tools/tracking_tools.py`，内部再导入 `tracking.tools.TrackingTools`）：

- `query_observations` — 搜索观察日志（audio/image/video/file/text，etype/since/until/keyword/limit）
- `query_models` — 查询已有建模结果
- `model_routines` — 建模作息规律 / 生活节奏
- `model_progress` — 建模事项 / 项目观察统计
- `query_checkin_stats` — 查询打卡统计（累计/连续天数、今日状态）

**AI 访问原则（只读 + 仅文本）**：
- AI 为**只读**：不提供任何写工具（已移除 `add_text_entry` / `add_file_entry`），
  AI 无法主动修改用户跟踪系统记录的数据。
- AI 只能看到**文本数据**（含从其他模态转换来的文本：音频 ASR 文本、`【打卡】`记录等）。
  文件路径（`media_path`/`video_path`/`audio_path`）在返回给 AI 前一律剥离。
- 未开启 `TRACKING_AI_ACCESS_ENABLED` 时所有工具返回 `enabled:false`，不泄露任何数据。
- 所有操作严格按 `user_id` 隔离。

**模态转换原则**：只对**音频**做 ASR 转录成文本（闲时感知/打卡的音频），
视频/图片/文件**原样存档**，不分析其内容。

## 6.1 多模态记录一览

| 模态 | etype | 引擎 API | AI 可见 |
|------|-------|----------|---------|
| 拍照 | image | `capture_photo()` / `record_photo()` | 文本描述（如"拍摄了一张照片"） |
| 录像 | video | `capture_video()` / `record_video()` | 文本描述（如"录制了一段视频"） |
| 录音 | audio | `capture_audio()` / `record_audio()` | ASR 文本（聆听由闲时感知接入） |
| 文件 | file | `add_file()` / `import_file()` / `record_file()` | 文本描述 + 文件类型 |
| 文本 | text | `add_text()` / `record_text()` | 原文（如 `【打卡】...`） |

> 所有引擎 API 均只由用户侧/系统侧调用（打卡、闲时感知、未来功能），**不对 AI 开放写权限**。
> AI 查询（`query_observations`）返回的仅为文本 + 少量安全元数据，路径一律剥离。

所有媒体文件经 `MediaManager` 按用户隔离存储于
`TRACKING_MEDIA_ROOT/<uid>/<date>/<kind>/`。

## 7. 迁移兼容

- 旧 `sensing_events` 表保留，`/api/sensing/event` 落库时经 tracking 回写，旧查询不受影响。
- 旧技能 `query_sensing_events`（`sensing_tools.py`）已移除，由 `query_observations` 取代。
- `minimal.py` 的 `IdleSensingMonitor` 对外接口（`configure/start/stop/enabled`）保持不变。
