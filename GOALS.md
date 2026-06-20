# DSN-exp

-> 本文件不是文档，文档往这看：[![zread](https://img.shields.io/badge/Ask_Zread-_.svg?style=flat&color=00b0aa&labelColor=000000&logo=data%3Aimage%2Fsvg%2Bxml%3Bbase64%2CPHN2ZyB3aWR0aD0iMTYiIGhlaWdodD0iMTYiIHZpZXdCb3g9IjAgMCAxNiAxNiIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHBhdGggZD0iTTQuOTYxNTYgMS42MDAxSDIuMjQxNTZDMS44ODgxIDEuNjAwMSAxLjYwMTU2IDEuODg2NjQgMS42MDE1NiAyLjI0MDFWNC45NjAxQzEuNjAxNTYgNS4zMTM1NiAxLjg4ODEgNS42MDAxIDIuMjQxNTYgNS42MDAxSDQuOTYxNTZDNS4zMTUwMiA1LjYwMDEgNS42MDE1NiA1LjMxMzU2IDUuNjAxNTYgNC45NjAxVjIuMjQwMUM1LjYwMTU2IDEuODg2NjQgNS4zMTUwMiAxLjYwMDEgNC45NjE1NiAxLjYwMDFaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik00Ljk2MTU2IDEwLjM5OTlIMi4yNDE1NkMxLjg4ODEgMTAuMzk5OSAxLjYwMTU2IDEwLjY4NjQgMS42MDE1NiAxMS4wMzk5VjEzLjc1OTlDMS42MDE1NiAxNC4xMTM0IDEuODg4MSAxNC4zOTk5IDIuMjQxNTYgMTQuMzk5OUg0Ljk2MTU2QzUuMzE1MDIgMTQuMzk5OSA1LjYwMTU2IDE0LjExMzQgNS42MDE1NiAxMy43NTk5VjExLjAzOTlDNS42MDE1NiAxMC42ODY0IDUuMzE1MDIgMTAuMzk5OSA0Ljk2MTU2IDEwLjM5OTlaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik0xMy43NTg0IDEuNjAwMUgxMS4wMzg0QzEwLjY4NSAxLjYwMDEgMTAuMzk4NCAxLjg4NjY0IDEwLjM5ODQgMi4yNDAxVjQuOTYwMUMxMC4zOTg0IDUuMzEzNTYgMTAuNjg1IDUuNjAwMSAxMS4wMzg0IDUuNjAwMUgxMy43NTg0QzE0LjExMTkgNS42MDAxIDE0LjM5ODQgNS4zMTM1NiAxNC4zOTg0IDQuOTYwMVYyLjI0MDFDMTQuMzk4NCAxLjg4NjY0IDE0LjExMTkgMS42MDAxIDEzLjc1ODQgMS42MDAxWiIgZmlsbD0iI2ZmZiIvPgo8cGF0aCBkPSJNNCAxMkwxMiA0TDQgMTJaIiBmaWxsPSIjZmZmIi8%2BCjxwYXRoIGQ9Ik00IDEyTDEyIDQiIHN0cm9rZT0iI2ZmZiIgc3Ryb2tlLXdpZHRoPSIxLjUiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIvPgo8L3N2Zz4K&logoColor=ffffff)](https://zread.ai/ccjjfdyqlhy/DSN-exp)  
-> 代码库复杂度分析往这看：[**屎山代码分析报告**](https://github.com/ccjjfdyqlhy/DSN-exp/blob/main/REPORT.md)  

所以，我最近在干嘛？

**本次更新：工作区系统 + Document 子系统（文档录入/OCR/HMD 管线）**

## 下一步往哪儿走

**用户了解体系重构**：做到私人知识库那种级别。先走Concepts/记忆系统路线。  
**纸制品交互**：通过打印机/扫描仪完成基于纸制品的交互界面。  
**环境感知**：摄像头主动抓帧，感知用户状态、环境光线、作息习惯。  
~~**规划引擎**：大目标拆解、日计划自动生成、执行追踪、日终反馈。搞定！~~  
~~**交互大改**：实现一个真正没webui、靠硬件驱动的交互策略。做完辣！~~  


## 议题

Concepts
---
- [x] 写个技能接入ncm！！
- [x] 从ncm技能的歌词蒸馏人格特点
- [x] 休眠时自动备份。
- [ ] 剧本系统：两端皆可使用，起到引导用户/做游戏的作用（？
- [ ] 开发提交前钩子——屎山分析、编年史添加、README更新，自动化。
- [x] 更大更强的记忆系统！（转后端）
- [x] Minimal Psychoscope CLI实现，完全无UI也能交互！
- [ ] 图书馆——接入Obsidian笔记系统。
- [x] 规划引擎：目标拆解、三层任务(Goal/Phase/DailyTask)模型、沉浸式闹钟
- [ ] 视觉感知协议正式落地：CameraWatcher后台抓帧 + 环境状态描述注入管线

后端
---
- [x] 优化响应速度：并行推理、分段传输响应
- [x] 复活本地lms，完善请求接口全部适应，拓宽协议支持传输图片
- [x] 使用本地lms作为主模型的模态转换模型
- [x] 融合engine到app（虽然现在app代码量还是比较多的，但是复用了不少）
- [x] 后端API集线器收集更多模型信息，比如消耗Tokens
- [x] PersonalitySystemV3、印象系统新版本：更加主动，基于随机种子生成人格模型，允许自定义人格方向。角色卡。
- [x] 数据库加密。
- [x] 基于AI的TTS文本预处理，输出极为TTS友好的文本。还要特别生动！
- [x] 复活叙事世界感知系统：修复记忆不注入
- [x] 计费账单系统。
- [x] 完善语音交互逻辑
- [x] **修复记忆系统BUG**，重写记忆模型提示词。
- [x] **修复Agent循环中技能系统BUG**
- [x] 连续对话模式：语音感知通话。
- [x] 人格蒸馏系统完善
- [x] 待机功能：掌握用户的请求节律，用户不用的时候待机，进行记忆整理、人格蒸馏、声音克隆什么的长期任务。
- [x] 内置GitHub技能。
- [x] 优化处理效率（第一波）
- [x] 优化性格抽取模型的异步流程。（第二波）
- [x] 支持并行/串行推理TTS，以及对应的profile handling
- [x] 角色卡从数据库独立，后者仅仅保存人格状态。
- [x] 用户观察日记系统。
- [x] 优化TTS处理模型提示词。
- [x] 剧本系统00：初始化设定initialization.md，入戏引导词
- [ ] 剧本系统01：给AI写的脚本以及ooc检测
- [ ] 接入IM！
- [ ] 话题管理系统、多层提示词系统
- [ ] 优化世界叙述现实系统：提示词重写、种子生成世界什么的。
- [ ] **实用性增强**，用作Vibe coding client。
- [ ] 动态视觉：环境感知协议Part1（挖，那是诱人的
- [ ] 话题系统和记忆系统的整合。
- [ ] 设备管理器核心：和环境感知协议整合——旨在让系统控制多台计算机。
- [x] 增强视觉：自动区分、处理、格式化文档
- [ ] 图书馆：存放个人UGC，闲置的时候读一读，加深了解。
- [x] 检查并修复记忆系统的提示词丢失问题。
- [ ] （转前端10）
- [x] 升级记忆系统为向量数据库检索。
- [x] 全新亲密度系统！
- [ ] 根据DeepSeek官方文档，提供更可控的主模型生成。
- [x] 角色卡蒸馏系统BUG大修、彻底独立于数据库，性格提取修复
- [x] 修复Tasks系统不持久化、服务器重启就失效的问题
- [x] 制作打印机/扫描仪控制模块和技能。
- [x] 提醒事项系统增强：重启恢复、DAILY_PLAN/COUNTDOWN/HABIT任务类型、standby也推送
- [ ] 视觉感知系统：CameraWatcher线程、运动/人脸检测、环境状态注入system_prompt、主动发话
- [x] 计划系统引擎：PlanEngine(create_goal/breakdown_phase/generate_daily_plan/check_off)、PlanPlugin、日终报告、资金成就
- [x] 工作区系统：WorkspaceManager 全局单例、用户隔离目录、WORKSPACE_DIR 配置、笔记/扫描/仓库默认路径
- [x] ScannerTool/PrinterTool 技能
- [x] OCRModel（deepseek-ocr，用完即释放）
- [x] .hmd 格式与DocProcessor

前端
---
- [x] 支持LanaPixel字体的Markdown渲染。支持换行。
- [x] 滚动判定（更新）
- [x] 回复计时计价，融合token_calc.py
- [x] 底栏：DSN-exp V4-API [Alt] 查看键位 XX:XX
- [x] 键位说明，游戏风格。
- [x] 打字机效果语气增强。
- [ ] 实时显示插件状态：EMO ^/v 0.x MEM () 21%
- [ ] F5前/后显示内容对齐。
- [ ] 左右面板开拓：可以让插件能自定义显示一些面板
- [ ] 解决异步调用返回webui仍然需要F5的问题（你怎么又回来了）
- [ ] 计划面板：日计划看板、完成进度可视化、成就/资金展示
- [x] 最小客户端完成实现和修BUG

仓库维生系统
---
- [x] 实现无AI部分：提交前运行脚本文件`run_before_sub.py`，自动执行代码复杂度检查，生成报告。
- [ ] 实现有AI部分：这个脚本还会调用本地模型总结本次修改的改动位点，自动填充Commit message，然后让模型续写项目编年史，记录开发历程。  

## API 端点总览

> 标注 `🔒` 的端点需要认证（JWT Session / API Key / 设备 Token）。

### 聊天

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/chat/send` 🔒 | 发送消息，获取 AI 回复 + TTS 音频 (JSON) |
| `POST` | `/api/chat/stream_send` 🔒 | 发送消息，流式返回 AI 回复 + TTS 音频 (SSE) |
| `GET` | `/api/chat/list` 🔒 | 列出当前用户的聊天会话列表 |
| `GET` | `/api/chat/<chat_id>` 🔒 | 获取指定聊天会话的历史消息 |
| `DELETE` | `/api/chat/<chat_id>` 🔒 | 删除指定聊天会话 |

<details>
<summary>请求/响应示例</summary>

**POST /api/chat/send**
```json
// Request
{
  "message": "你好",
  "chat_id": 1,          // 可选，不传则新建会话
  "chat_name": "闲聊",    // 可选
  "model_type": "fast",  // 可选: "deep"(DeepSeek) / "fast"(LMStudio)
  "tts_enabled": true,   // 可选，默认 true
  "is_asr_input": false, // 可选
  "image_data": ""       // 可选，base64 图片
}
// Response
{
  "reply": "你好！有什么可以帮你的？",
  "chat_id": 1,
  "audio": "<base64-wav>",     // TTS 合成音频
  "tts_error": null,
  "confirm_requested": false
}
```

**POST /api/chat/stream_send** — SSE 事件流:
```
event: data
data: {"status":"filtering"}
event: data
data: {"status":"parsing"}
event: data
data: {"status":"text_ready","reply":"你好！...","chat_id":1}
event: data
data: {"status":"thinking","text":"正在处理...","plugin":"memory"}
event: data
data: {"status":"line","index":0,"total":1,"text":"你好！...","audio_b64":"..."}
event: data
data: {"status":"completed","chat_id":1,"timing":{...}}
```
</details>

---

### 人格系统 V3

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/v3/card/list` 🔒 | 列出所有角色卡 |
| `GET` | `/api/v3/card/<card_id>` 🔒 | 获取角色卡详情（YAML → JSON） |
| `POST` | `/api/v3/card/upload` 🔒 | 上传/更新角色卡 YAML |
| `POST` | `/api/v3/card/<card_id>/distill` 🔒 | 触发角色卡蒸馏（4-Pass LLM 提炼 50 维人格向量） |
| `GET` | `/api/v3/card/<card_id>/distillation` 🔒 | 获取蒸馏产物（行为模式/言语模式/情绪模型/50维向量） |
| `POST` | `/api/v3/user/bind` 🔒 | 将当前用户绑定到指定角色卡 |

<details>
<summary>请求/响应示例</summary>

**POST /api/v3/card/upload**
```json
// Request
{ "yaml": "card_id: my_carda\nname: 测试角色\nnatural_language:\n  personality: 友善\n..." }
// Response
{ "success": true, "card_id": "my_card" }
```

**POST /api/v3/card/<card_id>/distill**
```json
// Response
{
  "success": true,
  "distillation_id": "distill_exa_sha256:a1b2c3d4e5f6",
  "fingerprint": "sha256:a1b2c3d4e5f6..."
}
```

**POST /api/v3/user/bind**
```json
// Request
{ "card_id": "exa" }
// Response
{ "success": true }
```
</details>

---

### 人格系统 (V2/V3 兼容)

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/personality/status` 🔒 | 获取当前人格状态摘要 (V3 优先，回退 V2) |
| `GET` | `/api/personality/current` 🔒 | 获取完整人格状态（含 50 维向量/情绪/亲密度） |
| `GET` | `/api/personality/list` 🔒 | 列出所有可用人格 (V3 角色卡 + V2 预设) |
| `POST` | `/api/personality/switch` 🔒 | 切换人格：V3 绑定角色卡 / V2 切换预设 |

<details>
<summary>响应示例</summary>

**GET /api/personality/status** (V3)
```json
{
  "uid": 1,
  "card_id": "exa",
  "total_interactions": 42,
  "mood": {"joy": 0.62, "sadness": 0.18, "anger": 0.05, "fear": 0.10},
  "affinity_value": 55.3,
  "affinity_level": {"level": 3, "label": "密友"},
  "labels": {"A1": "开放性中正", "E1": "话量略偏健谈", ...}
}
```

**POST /api/personality/switch**
```json
// V3: 通过 card_id 切换角色卡
{ "card_id": "exa" }
// V2: 通过 preset 切换预设
{ "preset": "tsundere" }
```
</details>

---

### 用户印象

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/impressions` 🔒 | 查询用户印象。可选 `?category=` `&min_confidence=` |
| `POST` | `/api/impressions` 🔒 | 手动添加印象 |
| `DELETE` | `/api/impressions/<impression_id>` 🔒 | 删除指定印象 |
| `GET` | `/api/impressions/suggest` 🔒 | 检查是否应建议启动 SSP (全面了解协议) |

---

### 语音 & ASR

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/asr/recognize` 🔒 | 上传音频文件（multipart/form-data `audio` 字段）→ 返回识别文本 |
| `POST` | `/api/asr/passthrough` 🔒 | Base64 音频 → ASR 识别 → 直接注入聊天管线 (SSE 流式返回) |

<details>
<summary>请求示例</summary>

**POST /api/asr/passthrough**
```json
{
  "audio_b64": "<base64-webm/wav>",
  "chat_id": 1,           // 可选
  "sensing": false        // 可选，true 时注入环境感知提示词
}
// 返回 SSE 流，同 /api/chat/stream_send
```
</details>

---

### 认证

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/auth/status` | 获取服务器认证状态（可用方法列表） |
| `GET` | `/api/auth/users` | 列出用户（ID + 显示名） |
| **L0 配对码** |||
| `GET` | `/api/auth/pairing/status` | 当前配对码状态 |
| `POST` | `/api/auth/pairing/verify` | 提交配对码 + 显示名 → 创建用户、返回 session。**仅限内网** |
| **L1 会话** |||
| `POST` | `/api/auth/session/recover` | 信任设备恢复登录（需 Cookie `dsn_device`） |
| `GET` | `/api/auth/sessions` 🔒 | 列出当前用户活跃会话 |
| `DELETE` | `/api/auth/session` 🔒 | 退出当前会话 |
| **L2 WebAuthn** |||
| `POST` | `/api/auth/webauthn/register/begin` 🔒 | 开始注册通行密钥 |
| `POST` | `/api/auth/webauthn/register/complete` 🔒 | 完成注册 |
| `POST` | `/api/auth/webauthn/login/begin` | 开始通行密钥登录 |
| `POST` | `/api/auth/webauthn/login/complete` | 完成登录 → 返回 session |
| **L3 TOTP** |||
| `POST` | `/api/auth/totp/setup` 🔒 | 生成 TOTP 种子（返回 URI + 密钥） |
| `POST` | `/api/auth/totp/activate` 🔒 | 激活 TOTP（验证一次性码） |
| `POST` | `/api/auth/totp/verify` | TOTP 登录验证 → 返回 session |
| **L4 API Key** |||
| `POST` | `/api/auth/api-key/create` 🔒 | 创建 API Key（**仅返回一次原始密钥**） |
| `GET` | `/api/auth/api-key/list` 🔒 | 列出当前用户的 API Key（不返回原始密钥） |
| `DELETE` | `/api/auth/api-key/<key_hash>` 🔒 | 撤销指定 API Key |
| **LittleSkin OAuth（旧版）** |||
| `GET` | `/api/auth/littleskin/start` | 开始 OAuth 流程。参数 `?redirect_uri=` |
| `GET` | `/api/auth/littleskin/callback` | OAuth 回调（由 LittleSkin 跳转） |

<details>
<summary>使用方法</summary>

所有 `🔒` 端点需在 Header 中携带认证信息（三选一）：

```
Authorization: Session <session_id>
Authorization: Bearer <api_key>
X-DSN-API-Key: <api_key>
```

首次使用流程：
1. 服务端运行 `/newbind` 生成配对码
2. 前端 `POST /api/auth/pairing/verify` 提交配对码 → 获得 `session_id` + Cookie `dsn_device`
3. 后续请求带 `Authorization: Session <session_id>` 即可
4. 会话过期后可 `POST /api/auth/session/recover` 恢复
</details>

---

### 服务器维护

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/maintenance/status` | 服务器状态（ready / maint / standby）+ 活跃度信息 |
| `GET` | `/api/maintenance/sse` | SSE 流：实时推送维护任务进度 |
| `POST` | `/api/maintenance/trigger` | 手动触发维护（记忆整理 + 人格蒸馏 + 日志清理） |
| `POST` | `/api/maintenance/toggle_standby` | 切换待机模式（在 READY ↔ STANDBY 之间切换） |

<details>
<summary>响应示例</summary>

**GET /api/maintenance/status**
```json
{
  "state": "ready",
  "request_count": 42,
  "idle_minutes": 3,
  "idle_probability": 0.85,
  "schedule_strategy": "predictive"
}
```
</details>

---

### Todo 计划进度

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/todo/stream/<todo_id>` | SSE 流：实时推送指定 todo 计划的执行进度 |
| `GET` | `/api/todo/plan/<todo_id>` | 获取 todo 计划当前状态（单次查询） |
| `GET` | `/api/todo/list` | 列出 todo 计划。可选 `?user_id=` `&chat_id=` |

---

### Psychoscope 可视化

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/` | Psychoscope 人格可视化面板 (独立端口) |
