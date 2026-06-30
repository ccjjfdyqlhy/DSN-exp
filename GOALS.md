# DSN-exp

-> 这不是文档。文档看 [README.md](README.md) 和 [README_zh.md](README_zh.md)。  
-> 代码复杂度分析看 [REPORT.md](REPORT.md)。

## 最新更新

**跨聊天全局记忆 + OpenAI 兼容重构 + AI Agent API**  
全局记忆：记忆按用户而非按聊天存储，聊天不再碎片化。OpenAI 兼容重构：DeepSeekChat → OpenAIChat，支持任意 OpenAI 格式 API。AI Agent API：本地 AI Agent 可通过专用接口与主 AI 对话，双向记忆互访。

## 下一步方向

**AI Agent 系统**：已实现基础框架（API 端点 + CLI 脚本 + 绑定管理 + 双向记忆同步），后续需接入更多 Agent 框架。  
**OpenAI 兼容**：配置项 `OPENAI_API_BASE` 已添加，支持切换任意 API 后端。  
**全局记忆**：chat_id 维度已移除，新聊天自动注入用户所有历史记忆。  
**跨聊天 Agent 对话同步**：用户与 Agent 对话时，未同步的 Agent 聊天记录按时间戳注入上下文。  
- [ ] Agent 接入更多框架（OpenClaw / Claude Code / CodeAct）文档示例
- [ ] Agent API 密钥撤销和轮换机制
- [ ] Agent 对话历史 WebUI 查看
- [ ] 多 Agent 支持（1 用户多 Agent）

## 议题

### Concepts
- [x] 写个技能接入 ncm！！
- [x] 从 ncm 技能的歌词蒸馏人格特点
- [x] 休眠时自动备份。
- [ ] 剧本系统：两端皆可使用，起到引导用户/做游戏的作用（？
- [ ] 开发提交前钩子——屎山分析、编年史添加、README 更新，自动化。
- [x] 更大更强的记忆系统！（转后端）
- [x] Minimal Psychoscope CLI 实现，完全无 UI 也能交互！
- [ ] 图书馆——接入 Obsidian 笔记系统。
- [x] 规划引擎：目标拆解、三层任务(Goal/Phase/DailyTask)模型、沉浸式闹钟
- [ ] 视觉感知协议正式落地：CameraWatcher 后台抓帧 + 环境状态描述注入管线
- [x] 语义缓存系统：L1 静态语素 + L2 向量语义检索 + TTS 复用，拦截重复请求
- [x] **跨聊天全局记忆**：记忆按用户聚合，聊天不再隔离
- [x] **OpenAI 兼容重构**：支持任意 OpenAI 格式 API，配置 `OPENAI_API_BASE`
- [x] **AI Agent API**：本地 AI Agent 通过专用接口与主 AI 对话，双向记忆同步

### 后端
- [x] 优化响应速度：并行推理、分段传输响应
- [x] 复活本地 lms，完善请求接口全部适应，拓宽协议支持传输图片
- [x] 使用本地 lms 作为主模型的模态转换模型
- [x] 融合 engine 到 app
- [x] 后端 API 集线器收集更多模型信息，比如消耗 Tokens
- [x] PersonalitySystemV3、印象系统新版本
- [x] 数据库加密。
- [x] 基于 AI 的 TTS 文本预处理
- [x] 复活叙事世界感知系统
- [x] 计费账单系统。
- [x] 完善语音交互逻辑
- [x] **修复记忆系统 BUG**，重写记忆模型提示词。
- [x] **修复 Agent 循环中技能系统 BUG**
- [x] 连续对话模式：语音感知通话。
- [x] 人格蒸馏系统完善
- [x] 待机功能
- [x] 内置 GitHub 技能。
- [x] 优化处理效率（第一波）
- [x] 优化性格抽取模型的异步流程。（第二波）
- [x] 支持并行/串行推理 TTS，以及对应的 profile handling
- [x] 角色卡从数据库独立
- [x] 用户观察日记系统。
- [x] 优化 TTS 处理模型提示词。
- [x] 剧本系统 00：初始化设定 initialization.md，入戏引导词
- [x] 剧本系统 01：引擎初始化 + Pipeline 接入（PluginContext.skip_model 跳过 MODEL_INVOKE）
- [x] 语义缓存引擎
- [x] 语义缓存插件
- [x] **Tool Call 原生升级**：废弃 `<tool>` XML 标签
- [x] **技能加载器重构**
- [x] **系统技能标准化**
- [x] **技能调用上下文**
- [x] **Token 节省**
- [x] **SSP 信号回调**
- [x] **模型失败短路**
- [x] **DeepSeek API 兼容**
- [x] **Agent Loop 原生模式**
- [x] **文档工具精简**
- [x] **异步任务系统**
- [x] **Pipeline 自动异步切换**
- [x] **前端异步轮询**
- [x] **execute_action 脱离 DB**
- [x] **Pipeline 异常保护**
- [x] **全局记忆系统**：chat_id 维度移除，记忆按用户聚合
- [x] **OpenAI 兼容重构**：DeepSeekChat → OpenAIChat，新增 `OPENAI_API_KEY` / `OPENAI_API_BASE`
- [x] **AI Agent API**：`POST /api/agent/send` + agent_send.py CLI + 绑定管理 + 双向记忆同步
- [ ] 接入 IM！
- [ ] 话题管理系统、多层提示词系统
- [ ] 优化世界叙述现实系统
- [ ] **实用性增强**，用作 Vibe coding client。
- [ ] 动态视觉：环境感知协议 Part1
- [ ] 话题系统和记忆系统的整合。
- [ ] 设备管理器核心
- [x] 增强视觉：自动区分、处理、格式化文档
- [ ] 图书馆：存放个人 UGC
- [x] 检查并修复记忆系统的提示词丢失问题。
- [x] 升级记忆系统为向量数据库检索。
- [x] 全新亲密度系统！
- [ ] 根据 DeepSeek 官方文档，提供更可控的主模型生成。
- [x] 角色卡蒸馏系统 BUG 大修
- [x] 修复 Tasks 系统不持久化问题
- [x] 制作打印机/扫描仪控制模块和技能。
- [x] 提醒事项系统增强
- [ ] 视觉感知系统：CameraWatcher 线程
- [x] 计划系统引擎
- [x] 工作区系统
- [x] ScannerTool/PrinterTool 技能
- [x] OCRModel
- [x] .hmd 格式与 DocProcessor
- [x] plan 技能（7 tools）
- [x] PlanEngine 增强
- [x] 提醒 DAILY_PLAN 每日计划
- [x] 提醒 PERIODIC 通用 cron
- [x] POST /api/reminder/skip 跳过提醒端点
- [x] minimal.py：跳过提醒/系统信息/手动同步键位 (#k #i #r)
- [x] 提示词缓存系统
- [x] 模型共存管理器：ModelScheduler
- [x] Agent 任务循环
- [x] /detail chats /detail actions 控制台命令
- [x] minimal.py 首条 TTS 音频计时节点
- [x] TTS 预处理禁止拼音输出
- [x] OCR 分类修复
- [x] Pipeline TTS 改用 ctx.reply
- [x] 任务失败也生成 LLM 错误回复
- [x] handled_by_pipeline 标记
- [x] 首次启动引导系统
- [x] onboarding.py AI 引导流程
- [x] 配置向导网络容错

### 前端
- [x] 支持 LanaPixel 字体的 Markdown 渲染
- [x] 滚动判定（更新）
- [x] 回复计时计价
- [x] 底栏：DSN-exp V4-API [Alt] 查看键位 XX:XX
- [x] 键位说明，游戏风格。
- [x] 打字机效果语气增强。
- [ ] 实时显示插件状态
- [ ] F5 前后显示内容对齐。
- [ ] 左右面板开拓
- [ ] 解决异步调用返回 webui 仍然需要 F5 的问题
- [ ] 计划面板
- [x] 最小客户端完成实现和修 BUG

### 仓库维生系统
- [x] 实现无 AI 部分：提交前运行脚本 `run_before_sub.py`
- [ ] 实现有 AI 部分：调用本地模型总结修改，自动填充 Commit message

## API 端点总览

> 标注 `🔒` 的端点需要认证。

### 聊天

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/chat/send` 🔒 | 发送消息，获取 AI 回复 + TTS 音频 (JSON) |
| `POST` | `/api/chat/stream_send` 🔒 | 发送消息，流式返回 AI 回复 + TTS 音频 (SSE) |
| `GET` | `/api/chat/list` 🔒 | 列出当前用户的聊天会话列表 |
| `GET` | `/api/chat/<chat_id>` 🔒 | 获取指定聊天会话的历史消息 |
| `DELETE` | `/api/chat/<chat_id>` 🔒 | 删除指定聊天会话 |

### AI Agent

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/agent/send` 🔒 | Agent 发送消息，同步返回主 AI 回复（仅 API Key 认证） |
| `GET` | `/api/agent/...` | Agent 管理命令（服务端 `/agent create/bind/list/unbind`） |

### 人格系统 V3

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/v3/card/list` 🔒 | 列出所有角色卡 |
| `GET` | `/api/v3/card/<card_id>` 🔒 | 获取角色卡详情 |
| `POST` | `/api/v3/card/upload` 🔒 | 上传/更新角色卡 YAML |
| `POST` | `/api/v3/card/<card_id>/distill` 🔒 | 触发角色卡蒸馏 |
| `GET` | `/api/v3/card/<card_id>/distillation` 🔒 | 获取蒸馏产物 |
| `POST` | `/api/v3/user/bind` 🔒 | 将当前用户绑定到指定角色卡 |

### 语音 & ASR

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/asr/recognize` 🔒 | 上传音频文件 → 返回识别文本 |
| `POST` | `/api/asr/passthrough` 🔒 | Base64 音频 → ASR → 直接注入聊天管线 (SSE) |

### 认证

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/auth/status` | 服务器认证状态 |
| **L0 配对码** | | |
| `POST` | `/api/auth/pairing/verify` | 提交配对码 → 创建用户 → 返回 session |
| **L1 会话** | | |
| `POST` | `/api/auth/session/recover` | 信任设备恢复登录 |
| **L2 WebAuthn** | | |
| `POST` | `/api/auth/webauthn/register/begin` 🔒 | 注册通行密钥 |
| `POST` | `/api/auth/webauthn/register/complete` 🔒 | 完成注册 |
| `POST` | `/api/auth/webauthn/login/begin` | 开始通行密钥登录 |
| `POST` | `/api/auth/webauthn/login/complete` | 完成登录 |
| **L3 TOTP** | | |
| `POST` | `/api/auth/totp/setup` 🔒 | 生成 TOTP 种子 |
| `POST` | `/api/auth/totp/activate` 🔒 | 激活 TOTP |
| `POST` | `/api/auth/totp/verify` | TOTP 登录验证 |
| **L4 API Key** | | |
| `POST` | `/api/auth/api-key/create` 🔒 | 创建 API Key |
| `GET` | `/api/auth/api-key/list` 🔒 | 列出 API Key |
| `DELETE` | `/api/auth/api-key/<key_hash>` 🔒 | 撤销 API Key |

### 记忆

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/memory/query` 🔒 | 语义搜索记忆（按用户全局搜索，不限定聊天） |
| `POST` | `/api/memory/memo` 🔒 | 手动添加备忘 |
| `DELETE` | `/api/memory/memo/<id>` 🔒 | 删除备忘 |

### 维护

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/maintenance/status` | 服务器状态 |
| `POST` | `/api/maintenance/trigger` | 手动触发维护 |
| `POST` | `/api/maintenance/toggle_standby` | 切换待机模式 |

### 服务器控制台命令

| 命令 | 说明 |
|------|------|
| `/newbind` | 生成新配对码 |
| `/users` | 列出所有注册用户 |
| `/status` | 服务器状态摘要 |
| `/agent create <名称> [用户ID]` | 创建 AI Agent 身份 + 生成 API Key |
| `/agent list` | 列出所有 Agent 绑定关系 |
| `/agent bind <AgentUID> <用户ID>` | 绑定 Agent 到用户 |
| `/agent unbind <AgentUID>` | 解除绑定 |
| `/memory users` | 用户记忆统计 |
| `/memory query <用户ID> <关键词...>` | 全局搜索记忆 |
| `/memory reindex start [用户ID]` | 重建向量索引 |
| `/config set <键> <值>` | 动态修改配置 |
| `/persona list` | 列出角色卡 |
| `/hibernate sleep` | 进入待机 |
| `/stop` | 安全停止服务器 |
