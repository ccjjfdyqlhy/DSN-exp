# dsn_study 功能补齐计划（对照 apps/dsn）

> 目标：把 `apps/dsn`（即参考版 DSN-exp 的库内形态）中"陪伴型基础设施"搬进
> `apps/dsn_study`，使其从"无状态题库"升级为"有记忆、会主动提醒的学习伴侣"。
> 方式：**cp + 接线**，不搬 apps/dsn 的自成体系模型层/插件全家桶，一切底层
> 原语走 harness/infra（这正是 harness 重构后的既有格局）。
>
> 状态标记：☐ 未开始 / ◐ 进行中 / ✅ 完成。
> 每完成一个阶段更新本文档。

## 背景结论（2026-10-26 摸底）

- `apps/dsn` 已具备全部目标功能：tasks.py(52K) / memory(172K) /
  semantic_cache(164K) / tracking(352K) / api/{checkin,reminder,alarm,heartbeat,agent}.py。
- harness 重构已下沉底层：`tasks.py` 用 `infra.tasks`（TaskExecutor/TaskStatus/
  TaskPriority），`memory/core.py` 用 `harness.memory`（cosine_similarity、
  embedding 打包）。剩余 `apps.dsn.*` 耦合收敛为 **Config / db.chat / models**
  三类，每模块 0–13 处改写。
- docs/apps.md 所述"dsn_study 四文件软链指向 dsn"**已过时**（实测均为普通文件），
  搬代码不会静默影响 dsn；回归仍建议双端跑。
- 先例：`engine_support.py` 就是当年搬 `api/scan.py` 时建的契约垫片
  （PluginContext + engine.pipeline.process + models_plugin.send_message），
  本计划的 compat 层沿用同一模式。

## 阶段 0：compat 垫片 ✅

**结论（2026-10-26 实施时验证）：无需独立垫片。** dsn_study 已存在与 dsn 同名同签名的对应物：

| dsn 侧契约 | dsn_study 侧实现 | 状态 |
|---|---|---|
| `apps.dsn.config.Config`（字段读取） | `apps.dsn_study.config.Config`（MAIN_MODEL/OPENAI/LMSTUDIO/REASONER/ACTION_TIMEOUT/TASK_*/REMINDER_LIST_LIMIT 字段全齐） | ✅ 直接可用 |
| `ChatDBManager._get_connection()` | `QuestionBankDBManager._get_connection()`（同名方法，Row 工厂齐全） | ✅ 直接可用 |
| `OpenAIChat.send_message` | `LLMService.send_message`（engine_support.py，构造注入而非 import） | ✅ 注入式适配 |
| `db.plan_engine/plan_store` | `apps.dsn_study.db.plan_engine/plan_store`（generate_daily_plan 同签名，DailyTask.title/duration_min 同名） | ✅ 直接可用 |
| `utils.workspace.get_workspace_manager` | `apps.dsn_study.workspace.get_workspace_manager`（同名；user_dir→user_documents_dir、resolve→join 需微调） | ✅ 调用点适配 |
| `models.DETAIL_ACTIONS` | 移植文件内模块常量（env `STUDY_DETAIL_ACTIONS` 可开） | ✅ 本地化 |

适配落点：全部在被移植文件内部（import 路径改写 + 少量调用点调整），不引入新抽象层。

## 阶段 1（P0）：定时任务 + 提醒/闹钟/心跳 ✅

**交付物（2026-10-26）：**

| 文件 | 说明 |
|---|---|
| `apps/dsn_study/tasks.py` | TaskManager 全量移植（8 种任务类型 + 持久化恢复 + 通知表 + 正计时 + ComplexityAnalyzer） |
| `apps/dsn_study/api/reminder.py` | /api/reminder/{list,done,cancel,skip} |
| `apps/dsn_study/api/alarm.py` | /api/alarms CRUD + now/status + check_and_trigger（users 表迁移查询加防御） |
| `apps/dsn_study/api/heartbeat.py` | /api/heartbeat + /dismiss（去掉视觉分支与 after_request 注入段；适配 StudyEngine.chat 纯文本返回） |
| `apps/dsn_study/skills/builtin/study_tasks/` | 17 个技能工具（create_reminder/habit/countdown/daily_plan/periodic、stopwatch ×5、list/cancel/skip/done、create_reasoner、execute_action ×2），skill.yaml 自 dsn system 技能抽取 |
| `boot.py` | TaskManager 装配（TASK_MANAGER_ENABLED 开关）+ runtime.on_stop 关停 + 三蓝图挂载 + 技能依赖注入 |
| `bundles.py` | PlanBundle 扩为 plan + reminder + alarm + heartbeat |
| `tests/test_dsn_study_tasks.py` | 10 个用例：过期提醒立即执行→通知→投递、HABIT 自动重排、REASONER（无 LLM 失败/有 LLM 完成）、正计时全生命周期、复杂度分析、闹钟同分钟防重触发、技能工具注入、boot 路由冒烟 |

**移植时的关键适配（diff 要点）：**
1. DDL 去掉对 `chats` 表的 FOREIGN KEY——study 库无聊天表，且连接开 `PRAGMA foreign_keys=ON`，保留会导致 INSERT 失败；
2. `_execute_reasoner_task` 改用注入的 LLMService（dsn 原版自建 OpenAIChat/LMStudioChat/failover 三分支收敛为一）；
3. 动作类任务 workspace：`user_dir(uid)` → `user_documents_dir(uid)`，相对路径 join 到用户文档目录；
4. TaskTools 技能：兼容两种注入模式（实例属性 setattr + 类级 `_ctx`），`_uid()` 默认 1（对齐 LocalAuthManager，否则技能建的提醒 API 查不到）；
5. REASONER/ACTION 类型不自动调度、由调用方 `execute_task`（保持 dsn 原语义）。

**验收结果**：`pytest tests/test_dsn_study_tasks.py tests/test_dsn_study_boot.py` 22 过；全量 578 passed / 0 失败（dsn 侧零改动）。

## 阶段 2（P0）：记忆系统 ✅

**交付物（2026-10-26）：**

| 文件 | 说明 |
|---|---|
| `apps/dsn_study/memory/core.py` | MemorySystem 全量移植：exp/memo 双类型记忆、混合检索（关键词 + 可选向量）、`<recall>`/`<memo>` 标签处理、上下文装配、摘要重建 |
| `apps/dsn_study/memory/summary.py` | LLMSummaryModel 适配：包装 LLMService（提示词与接口签名对齐 dsn 原版），失败静默降级 |
| `apps/dsn_study/memory/embeddings.py` | 最小 OpenAI 兼容嵌入客户端（兼容 LM Studio / Ollama），失败返回 None 降级为纯关键词 |
| `apps/dsn_study/skills/builtin/study_memory/` | recall / save_memo 两个工具 + 提示词（何时存/何时查的行动指引） |
| `boot.py` | MemorySystem 装配（MEMORY_ENABLED 开关）+ StudyEngine 记忆闭环接线 |
| `tests/test_dsn_study_memory.py` | 9 个用例：memo CRUD、轮次记录 + 摘要 + detail 还原、标签处理、关键词检索、上下文装配、摘要降级、嵌入降级、boot 装配冒烟 |

**关键适配（diff 要点）：**
1. 加密改明文直通（study 库无 MessageCipher，与题库主库"不加密便于移植"定位一致）；
2. 原始对话轮次改存 study 自有 `chat_rounds` 表（StudyEngine 每轮 `record_round` 写入），`get_detail`/`_build_round_messages`/`reindex_embeddings` 随之改写——替代 dsn 的 messages/chats 表；
3. **话题系统休眠**：topics.py 对 dsn 聊天表耦合深（get_messages_by_topic 等 4 个方法），study 侧 `_topics` 恒 None、`TOPIC_ENABLED=false`，全部走 memo/exp 装配路径；
4. StudyEngine.chat 记忆闭环：备忘/记忆前置注入 → 执行 → `record_round` + 异步 `summarize_turn` → `handle_tags` 消费回复中的标签；会话 → 整数 chat_id 稳定映射；
5. Agent 绑定同步逻辑保留 hasattr 守卫，study 库无对应方法时自动 no-op。

**验收结果**：dsn_study 三套测试 31 过；全量 587 passed / 0 失败。
**后续可选项**：错题事件自动入 memo（当前由 AI 经 save_memo 工具自主完成，够用）；话题系统如需启用再评估移植。

## 阶段 3（P1）：语义缓存 ☐ → ✅

**交付物（2026-10-26）：**

| 文件 | 说明 |
|---|---|
| `apps/dsn_study/semantic_cache/` | 整包移植（CacheStore / L1 / L2 / L3 / Engine，约 1.5k 行），import 改写 9 处 |
| `engine.py` 意图裁剪 | INTENT_KEYWORDS 收敛为学习场景：组卷 / 搜索 / 计划 / 提醒 / 一般问题；dsn 专属的扫描/打印/天气/音乐/视觉意图移除 |
| `store.py` 维度适配 | `dims` 构造参数 + 空索引时自动适配首向量维度（dsn 原版锁死 768，换嵌入模型会静默丢向量）+ 维度不符时显式告警 |
| `boot.py` | CacheEngine 装配（SEMANTIC_CACHE_ENABLED 开关，默认 false；嵌入复用记忆系统的 OpenAIEmbeddingClient） |
| `StudyEngine.chat` | 对齐 dsn CacheInterceptorPlugin 的三级读路径（L1 → L2 重放 → 语义搜索）+ 写路径 + 负反馈观察衰减（"不对"类回复触发 decay） |
| `tests/test_dsn_study_cache.py` | 7 个用例：意图裁剪、cache key 归一、写入→语义命中、无嵌入降级、负信号/衰减、L1 短语、boot 关闭态冒烟 |

**意外发现并修复的上游 bug**：dsn 的 `semantic_cache/store.py` 缺 `import numpy as np`——空库时 `_load_index` 靠三元表达式短路侥幸初始化，一写入向量即 NameError（被捕获静默吞掉），**dsn 的语义缓存从未真正写入过数据**。dsn 与 study 两份 store.py 均已补上该 import（dsn 默认 SEMANTIC_CACHE_ENABLED=false，修复无行为风险；启用后该功能才第一次真正可用）。

**验收结果**：cache 测试 7 过；全量 620 passed / 0 失败。
**使用提示**：L2/语义命中需要 `MEMORY_EMBEDDING_ENABLED=true` + 可用的嵌入后端；仅 L1 语用短语不依赖嵌入（study 场景通常不命中）。组卷是最贵请求，启用嵌入后重复组卷直接回放历史回复。

## 阶段 4（P1）：打卡 + 学习跟踪 lite ✅

**交付物（2026-10-27）：**

| 文件 | 说明 |
|---|---|
| `apps/dsn_study/db/checkin_store.py` | checkins 表 + 全套方法（4点边界归并、当日有效打卡、连续天数、日历视图），自 dsn db/chat.py 移植；去掉 users 表外键 |
| `apps/dsn_study/api/checkin.py` | record（纯文本 JSON，去媒体/ASR/tracking）/ status / history + 新增 calendar（打卡日历数据） |
| `apps/dsn_study/tracking_lite/` | TrackingStore 整包移植（分天表 + 关键词搜索 + 建模产物，恒等 cipher 替代 MessageCipher）+ `StudyLog` 门面（record_session / sessions / minutes_by_day / daily_report 聚合打卡+时段+计划完成度） |
| `apps/dsn_study/api/studylog.py` | POST session/note、GET sessions/report 四个端点 |
| `boot.py` + `bundles.py` | CheckinStore / TrackingStore（题库库旁 tracking.db）/ StudyLog 装配；checkin+studylog 蓝图挂 StudyBundle |
| `tests/test_dsn_study_checkin.py` | 7 个用例：4点边界、有效打卡规则、连续天数、日历、时段累计、每日报告、双 API 流程冒烟 |

**验收结果**：7 过；全量 627 passed / 0 失败。
**设计取舍**：dsn 版打卡经摄像头录像+麦克风录音+ASR 存档；study 版为纯软件（文本打卡），媒体列保留对齐 schema 但恒空。学习时段当前经 API/程序化记录；后续可在时间表 checkout 时自动挂一次 `record_session`。

## 阶段 5（P1）：视觉 OCR 通道（VISION_OVERRIDE 等价物） ✅

**摸底修正（2026-10-27）**：实施时发现视觉基础设施已基本就位——视觉实现早已下沉
`infra/orchestrator/vision.py`（dsn/dsn_study 共用），study 的 `models/clients.py`
（VisionModel + LMStudioVisionFallback 配置注入）与 Config 的 VISION_* 字段全部在位，
scan API 主链路（`_extract_and_store`）本来就是视觉直取。真正的断链是三处死点：

| 修复 | 说明 |
|---|---|
| `LLMService.describe_image` | ScannerPipeline 期望的图片描述契约此前无人实现（调用必挂 AttributeError）——现在 VisionModel 优先、未配 VISION_API_KEY 时回退 LMStudio 兜底，接受文件路径或 data URL |
| `quest_from_image` fallback NameError | LMStudio 兜底分支引用了未导入的 `LMStudioChat`——改用本就导入的 `LMStudioVisionFallback`（自带 describe_image） |
| `HmdClient.convert_via_vision` | VISION_OVERRIDE 等价物：视觉模型逐页 `ocr_md` 直出 Markdown，组装与 2md 管线同构的 .hmd 包，下游 `process_hmd` 无感；不依赖 2md API |
| `doc_to_questions.process_images` | 新工具：图片列表 → convert_via_vision → 提题入库（skill.yaml 已声明，AI 可直接调用） |

**验收**：`tests/test_dsn_study_vision.py` 6 过（describe_image 双通道 + 文件路径入参、
convert_via_vision 建包往返、空参校验、process_images 全链路桩管线）；全量 633 passed / 0 失败。

## 阶段 6.5（P0/P1，2026-11-01）：对照参考版全量补齐 ✅

> 对照基准：`/home/darkstar/DSN-exp-test/study/DSN-exp`（参考实现，git 分支 `study`）。
> 本阶段把"学习域"功能补到与参考版一致，并把移植时遗留的坏导入彻底修掉。

### 6.5.1 P0：坏导入（曾导致两个技能实际不可用）

| 位置 | 症状 | 修复 |
|---|---|---|
| `skills/builtin/knowledge_graph/tools/knowledge_tools.py:88` | `from knowledge_graph.builder import ...` → ModuleNotFoundError，**「从考纲构建知识图谱」工具完全不可用** | 改为 `apps.dsn_study.knowledge_graph.builder` |
| `skills/builtin/question_print/tools/print_tool.py:117,191` | `from utils.workspace` / `from document.printer` → ModuleNotFoundError，**「出题打印」技能实际失效** | 改为 `apps.dsn_study.workspace` / `apps.dsn_study.document.printer`；并给 `workspace.WorkspaceManager` 补 `user_subdir/register_subdir/root_subdir` 契约 |
| `api/scan.py:84,93` | `from config import Config` → 扫题回退分支 ImportError | 改为 `apps.dsn_study.config` |
| `skills/builtin/text_extract/tools/text_extract.py:114,134` | 指向 `plugins.base` / `apps.dsn.models.clients` 的死路径 | 改为 `apps.dsn_study.engine_support` / `apps.dsn_study.models.clients` |
| `boot.py:122` | 到期复习注入取 `d.get("name")`，而 `get_due_reviews` 返回列名是 `kp_name` → 知识点名称永远显示为编码 | 改取 `kp_name` |
| 依赖声明 | `weasyprint` 未进 requirements.txt（打印技能硬依赖）；本机缺 `schedule/croniter/numpy` | 补声明并安装 |

### 6.5.2 P1：补齐参考版有、dsn_study 缺的能力

| 能力 | 参考版位置 | dsn_study 落地 |
|---|---|---|
| **考试超时自动交卷 + 交卷关键词触发** | `plugins/builtin/exam_sim_plugin.py:34-67`（注：REF 侧 `ctx.extra["exam_session_id"]` 无写入方，实为死代码） | `chat_hooks.py`：按 user_id 查 `exam_sessions` 找进行中会话 → 超时自动 `auto_submit`；关键词收窄为明确交卷语义（"交卷/提交试卷/答完了…"），避免误伤"提交作业" |
| **`<plan_check>` 标签勾选任务** | `plugins/builtin/plan_plugin.py:73-108` | `chat_hooks.post_process()` 解析标签 → `PlanEngine.check_off/skip_task` → 从回复中移除标签；`daily_summary` 补 `task_id`、今日计划注入补 `id=`，使标签可用 |
| **22:00 日终报告注入** | `plugins/builtin/plan_plugin.py:110-134` | `chat_hooks._daily_report_block()`（每日一次） |
| **聊天内图片转文字** | `plugins/builtin/vision_plugin.py` | `chat_hooks._vision_block()` + `/api/chat/send` 接受 `image` 字段（data URL 或路径） |
| **document 子系统** | `document/doc_processor.py`(267) + `document/inputs.py`(33) + `models/clients.py` 的 OCRModel/GradingModel | 移植 `document/doc_processor.py`、`document/inputs.py`；新增 `document/ocr.py`（OCRModel 薄封装，走 infra 视觉层 `ocr_md`）、`document/grading.py`（GradingModel 移植） |
| **document 技能（10 工具）** | `skills/builtin/document/` | 全量移植（扫描/打印/HMD/描述图片/扫描入题/**扫描作答卷判分**），import 路径改写 + 依赖注入（题库 + 模型） |
| **打卡/学习日志的 AI 可达性** | `skills/system/tools/tracking_tools.py` | 新增 `study_tracking` 技能（7 工具：打卡/打卡统计/学习时段/学习笔记/时段列表/每日时长/每日报告） |
| **批量操作技能** | `skills/batch/` | 新增 `batch` 技能（2 工具），依赖注入 TaskManager |
| **异步对话入口** | `POST /chat/async_send` | 新增 `POST /api/chat/async_send`（后台线程跑 StudyEngine.chat，错误正确落库） |
| **`<tool>` XML 标签调用协议** | `plugins/builtin/tool_plugin.py:191-240` | 新增 `tool_adapter.SkillTagToolCallAdapter`（原生 function calling 优先，标签兜底）+ `harness/agent_runtime.py` 新增可选 `adapter` 注入口 |
| **ComplexityAnalyzer 接线** | `engine.py:223` → todo_plugin | 实例化并接到对话主链（复杂问题提示走 `create_reasoner`）+ 暴露 `analyze_complexity` 工具 |

### 6.5.3 验收

- 新增 `tests/test_dsn_study_functional_parity.py`（19 用例）：技能加载 / 题库往返 / 组卷 /
  计划流程 / 任务与复杂度 / 打卡与学习日志 / document 工具可达 / batch / plan_check 回写 /
  考试超时自动交卷 / 日终报告 / `<tool>` 标签协议 / **桩模型完整对话回路（原生 + XML 两条路径）** /
  **依赖注入回归**（防 dep_map 键名与工具属性名不一致）/ **坏导入回归**（防未加前缀 import 复现）。
- 既有 dsn_study 测试 66 → 全绿；全量 620 passed（17 项失败为改动前既有基线，已用 git stash 对照确认）。
- 实机冒烟：`python -m apps.dsn_study --web` 起服务，10 个 GET + 4 个 POST 端点 200；
  出题打印实测生成 PDF 并投递 CUPS 打印（job_id 39 / G3010LAN）。

### 6.5.4 遗留（需外部条件）

- LLM 端到端对话需要可用模型凭据：当前 `apps/dsn_study/.env` 的 `OPENAI_API_KEY`
  对 `https://api.littlecold.cn/v1` 返回 **401 Invalid token**；本机无 LMStudio/llama.cpp 服务。
  代码路径已用桩模型验证通过，换有效凭据即可直接跑。

## 阶段 8（P1，2026-11-01）：Obsidian MCP 接入（知识点库索引 + 笔记）✅

> 诉求：给 dsn_study 连接 Obsidian 的 MCP，允许其用 Obsidian 做**知识点库索引**和**笔记**。

### 8.1 选型

| 候选 | 机制 | 是否采用 |
|---|---|---|
| `obsidian-mcp@2`（npm, StevenStavrakis） | 直接操作 vault 里的 Markdown，**Obsidian 桌面端无需运行**；无需社区插件 / API Key / 端口 | ✅ **采用** |
| `obsidian-mcp-server`（npm, cyanheads） | 需要 Obsidian 的 Local REST API 插件 + 应用常驻 + API Key | ✗ |
| `mcp-obsidian`（npm, steipete） | 同上，依赖 REST API 插件 | ✗ |

本机已装 `/opt/Obsidian`，vault 位于 `/home/darkstar/dsn_workspace/library/library`（含 `.obsidian/`）。
选文件系统型 MCP 的原因：dsn_study 是后台长期运行的应用，不该依赖一个 GUI 应用常驻。

### 8.2 落地内容

| 文件 | 说明 |
|---|---|
| `apps/dsn_study/mcp_servers.yaml` | dsn_study 专属 MCP 声明：`obsidian` 服务器（stdio → `npx obsidian-mcp@2 serve --vault study=...`） |
| `apps/dsn_study/mcp_bridge.py` | `MCPBridge`：加载 YAML → **专属常驻事件循环** → 连接 → 把 12 个远端工具注册给 AgentRuntime（命名空间 `mcp.obsidian.*`）；失败隔离、状态快照、跨线程调用 |
| `apps/dsn_study/skills/builtin/obsidian_notes/` | 「Obsidian 知识库」技能（4 工具）：`index_knowledge_points`（知识点批量索引）、`write_study_note`（写笔记）、`search_obsidian_notes`、`list_obsidian_notes` |
| `apps/dsn_study/api/obsidian.py` | `GET /api/obsidian/status`、`POST /api/obsidian/index` |
| `apps/dsn_study/skills/registry.py` | 新增 `call_tool_async` / `is_async_tool`（支持需要 await 外部资源的技能工具） |
| `apps/dsn_study/boot.py` | 装配 MCPBridge（后台线程）→ 注入技能依赖 → 异步工具以 async handler 桥接 |
| `harness/tools/mcp.py` | **前向兼容**：MCP SDK 2.x 把 `streamablehttp_client` 改名、`read_timeout_seconds` 从 timedelta 改为 float —— 两种 SDK 版本都能用 |

### 8.3 关键设计决策

1. **专属常驻事件循环**：MCP 会话（stdio 子进程 + anyio task group）必须活在与它同一个事件循环里。
   用 `asyncio.run()` 建连再退出，循环关闭会把会话一起销毁，表现为「工具列出来了但调用永远失败」。
   现在由 `MCPBridge` 持一个常驻 loop 线程，跨线程调用用 `run_coroutine_threadsafe`。
2. **原始 MCP 工具 + 领域技能并存**：12 个 `mcp.obsidian.*` 工具直接给 AI（自由读写笔记），
   技能补的是「知识点图谱 → 结构化笔记」这类需要 dsn_study 内部数据的复合动作。
3. **索引幂等**：已存在的笔记默认跳过；`overwrite=true` 才覆盖刷新。
4. **ALREADY_EXISTS 按文本判定**：obsidian-mcp 把「笔记已存在」当**成功**返回（正文带标记），
   不能只看 `success`，否则会把「已存在」误判成「索引成功」。
5. **连接不阻塞启动**：stdio 子进程冷启动数秒（npx 拉包），连接放后台线程；
   MCP 不可用时其余功能完全不受影响。
6. **删除可恢复**：obsidian-mcp 默认走 trash（`.obsidian-mcp/trash`），永久删除需显式确认。

### 8.4 验收

- `tests/test_dsn_study_obsidian.py` **16 用例**（配置声明与 env 展开 / MCPBridge 生命周期 /
  索引渲染与跳过覆盖语义 / 笔记写入与追加 / 依赖注入命中 / 异步工具不重复注册 / 路由 /
  **真实 MCP 往返**（`MCP_LIVE_TEST=1`））。
- **实测**：MCP 连接成功、**12 个工具**注册进 AgentLoop；索引 2 个知识点 →
  vault 里生成 `知识点库/<科目>/<kp_code>.md`（frontmatter 含 kp_code/科目/掌握度/下次复习）；
  `GET /api/obsidian/status` 返回 `connected=true, tool_count=12`。

## 阶段 7（P1，2026-11-01）：TTS 语音合成（直接对接 infra 资源池）✅

> 诉求：GPT-SoVITS 依赖在 conda 环境 `GPTSoVits` 里，用该环境的**独立 Python** 启动；
> dsn_study **直接对接 infra** 调度该资源；**不做 AI 主动合成的 speak 工具**。

### 7.1 落地内容

| 文件 | 说明 |
|---|---|
| `apps/dsn_study/models/resource_setup.py` | 把 TTS 注册进 `infra.resources.ResourcePool`（`ResourceKind.TTS`、`resident=True`、`immediate=False`）；启动策略走 `LaunchMode.CONDA`，由 infra 拼出 `conda run -n GPTSoVits --cwd <dir> --no-capture-output <env python> api.py -p 9880 -d cuda` |
| `apps/dsn_study/models/tts_client.py` | GPT-SoVITS HTTP 客户端（minimal 版）：按架构选端点（parallel→`/tts`，serial→`/`）、POST → 音频字节、`probe()` 就绪探测 |
| `apps/dsn_study/models/tts_profile.py` | 音色 profile 管理器（移植自 apps/dsn）：YAML 多 profile、默认 profile、参考音频相对路径解析、parallel/serial 两套参数字段 |
| `apps/dsn_study/TTS_profiles/` | 音色资产（default.yaml + ref.wav + ref_advanced.wav；参考音频与 prompt 文本必须与训练音色对齐） |
| `apps/dsn_study/voice.py` | `VoiceService` 门面：**取 infra 租约 → 保证服务就绪 → 合成 → base64**；任何失败都降级为纯文本，绝不打断对话 |
| `apps/dsn_study/api/voice.py` | 语音控制 API：`GET /api/voice/status`、`POST /api/voice/start`、`POST /api/voice/stop` |
| `apps/dsn_study/boot.py` | 装配 `VoiceService`（注册进 runtime）→ 传入 `StudyEngine`；`StudyEngine.chat_audio()` 返回 `{reply, audio_b64, tts_error}` |
| `apps/dsn_study/api/chat.py` / `api/heartbeat.py` | 响应体新增 `audio_b64` / `tts_error`（提醒播报与对话回复都带语音） |
| `apps/dsn_study/config.py` / `settings.py` / `.env` | 新增 TTS 资源托管参数（AUTOSTART / LAUNCH_MODE / CONDA_ENV / CONDA_EXE / SERVER_DIR / PORT / DEVICE / GPU_ID / LOAD_TIMEOUT / WARMUP / PROFILE_NAME …），`voice` 命名空间同步扩充 |

### 7.2 关键设计决策

1. **调度全部交给 infra**：dsn_study 只做「注册 + 取租约」，FIFO 队列 / 插槽上限 /
   优先级驱逐 / 常驻保护等调度语义零重复实现（`ResourcePool` 继承 `ModelScheduler`）。
2. **独立 Python**：`argv[0]` 固定为 conda 环境内的解释器
   （`/home/darkstar/anaconda3/envs/GPTSoVits/bin/python`）；base env 的 python 拉不起来
   （缺 fast_langdetect / split_lang / peft / opencc）。
3. **resident=True**：TTS 是重量级长驻服务（加载权重分钟级），若 immediate 会在每次
   合成归还时立刻卸载 → 每次都重拉整个服务。
4. **不做 speak 工具**：语音只跟随对话回复自动生成（对齐参考实现的 POST_TTS 语义），
   AI 无主动合成入口。
5. **按需拉起**：`TTS_WARMUP` 默认 false —— 启动不预热，首次合成时由资源池拉起；
   需要预热用 `POST /api/voice/start`。预热期间对话照常返回纯文本。
6. **失败即降级**：TTS 不可用/超时/报错 → `audio_b64=null, tts_error=...`，对话不受影响。

### 7.3 验收

- `tests/test_dsn_study_voice.py` 13 用例（profile 载入与两种架构参数 / 客户端与错误 /
  VoiceService 合成与降级 / 文本清洗 / 资源池注册 / conda 启动策略 / chat_audio 附带音频 /
  TTS 失败降级 / 语音路由 / **真实服务联调**（`TTS_LIVE_TEST=1` 才跑））。
- **实测**：资源池拉起 GPT-SoVITS **9.5–24s 就绪**；合成「今天我们复习一下二次函数的顶点公式。」
  → 产出 **276KB / 48kHz / 2.88s WAV**；`POST /api/chat/send` 返回 `audio_b64` 368700 字符，
  `GET /api/voice/status` 显示 `loaded=true, managed=true`。

## 阶段 6（P2，可选）：外部 Agent / 人格 ☐

- Agent 接入不走 cp（api/agent.py 依赖记忆同步链），改用 **harness MCP 桥接**
  把学习工具暴露出去（2026-10 已交付 harness/tools/mcp.py）。
- 人格：`harness/personality`（PEV3）配导师卡；cp `prompt/personality_v3`
  （1.1M）成本高，另行评估。

## 明确不搬清单

`audio/`、`dual/`、`plugins/`（904K，harness pipeline 已承接）、`world/`、
`pyncm/`、`web_admin`、`maintenance/`、`onboarding.py`、`psychoscope/`。

## 实施纪律

1. 每阶段独立可交付、独立可回滚；完成即更新本文件状态与备注。
2. 双端回归：`python -m pytest -q`（dsn_study 相关 + 全量），dsn 侧不动。
3. 保持 docs/apps.md"标准 Web 应用范例"定位：不引入 dsn 的 boot 全家桶。
4. 搬运代码保留原注释风格；改写处加一行说明（来源 + 为什么改）。

## 进度日志


- 2026-10-26：计划创建。摸底完成（依赖面量化 + 软链风险排除）。
- 2026-10-26：阶段 0 完成——验证结论为无需独立 compat 模块（同名契约已对齐，适配内联进被移植文件）。
- 2026-10-26：阶段 1 完成——TaskManager + 提醒/闹钟/心跳 API + 17 工具技能 + boot 装配；新增 10 测试，全量 578 过。
- 2026-10-26：阶段 2 完成——MemorySystem + 摘要/嵌入适配 + study_memory 技能 + StudyEngine 记忆闭环；话题系统休眠（文档已注明）；新增 9 测试，全量 587 过。
- 2026-10-26：阶段 3 完成——semantic_cache 整包移植 + 意图裁剪 + 维度自适应 + chat 三级缓存接线；意外修复 dsn 上游 numpy 缺 import bug（dsn 缓存此前从未真正写入过）；新增 7 测试，全量 620 过。
- 2026-10-27：阶段 4 完成——checkin 打卡（纯软件版，4点边界/有效打卡/连续天数/日历）+ tracking-lite（分天事件存储 + StudyLog 门面 + 每日报告）+ 5 个新端点；新增 7 测试，全量 627 过。
- 2026-10-27：阶段 5 完成——摸底发现视觉基建已下沉 infra 且 study 侧配置齐全，实际修复三处死点（LLMService.describe_image 契约、quest_from_image 兜底 NameError）+ 新增 convert_via_vision/process_images 视觉直录通道；新增 6 测试，全量 633 过。
- 2026-10-27：P0/P1 五阶段全部完成。阶段 6（P2 可选：MCP 暴露学习工具 / 导师人格）保留待办。dsn_study 当前 15 个技能（原 12 + study_tasks 17 工具 + study_memory 2 工具），boot 桥接约 84 个工具。
- 2026-11-01：阶段 6.5 完成——对照参考版全量补齐：修 5 处坏导入（含让「知识图谱构建」「出题打印」两个技能从不可用变可用）、补考试超时自动交卷 / `<plan_check>` / 日终报告 / 聊天内图片、移植 document 子系统与 document 技能（10 工具，含扫描作答卷判分）、新增 study_tracking（7 工具）与 batch（2 工具）技能、新增 async_send 端点与 `<tool>` 标签降级适配器；新增 19 用例功能完整性测试（含桩模型完整对话回路），dsn_study 侧 66→全绿。
- 2026-11-01：阶段 7 完成——TTS 接入：经 infra 资源池以 conda 模式（GPTSoVits 环境的独立 Python）托管 GPT-SoVITS；新增 VoiceService 门面 / TTS 客户端 / profile 管理器 / 音色资产 / voice 控制 API；对话与提醒响应新增 audio_b64；新增 13 用例（含真实服务联调）。
- 2026-11-01：阶段 8 完成——Obsidian MCP 接入：经 harness MCPManager 以 stdio 接入 obsidian-mcp@2（Obsidian 桌面端无需运行），12 个 mcp.obsidian.* 工具进 AgentLoop；新增 Obsidian 知识库技能（知识点索引/写笔记/搜索/列举）与 obsidian 控制 API；MCPBridge 采用专属常驻事件循环；harness 兼容 MCP SDK 1.x/2.x；新增 16 用例。
