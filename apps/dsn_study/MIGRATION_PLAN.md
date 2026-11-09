# dsn_study + study_CLI 实施计划（基于 harness/infra 新基座）

> 目标：把 `apps/dsn` 的四类能力 —— **ASR 语音输入**、**多模态感知 + 视觉 API**、
> **话题系统**、**管理面板** —— 用 **DSN-exp 新基座（`harness/` + `infra/`）**
> 复刻到 `apps/dsn_study`；同时补上 `harness/personality` 人格系统，
> 并新建边缘设备客户端 **`apps/dsn_study_cli`**（下文简称 study_CLI）。
>
> 原则：**不搬 `apps/dsn` 的老实现**，只复用新基座已有能力；
> `apps/dsn` 侧零改动，每阶段独立可交付、可回滚。
>
> 状态标记：☐ 未开始 / ◐ 进行中 / ✅ 完成 / ⛔ 阻塞
> 配套文档：`apps/dsn_study/FEATURE_GAP.md`（历史功能补齐记录）

---

## 0. 已拍板的决策

| # | 决策 | 说明 |
|---|---|---|
| D1 | **迁移到 `harness/pipeline`** | dsn_study 现有 `chat_hooks.py` 的硬编码前/后处理，改写为 `harness/pipeline` 的 Plugin。`HookPoint` 已备好 `PRE_FILTER`（ASR 输入过滤）、`PREPARE`（上下文组装）、`MODEL_INVOKE`、`POST_PROCESS`、`POST_TTS`（`harness/pipeline/base.py:27-34`） |
| D2 | **人格复用 `harness/personality`（PEV3）** | 该模块已是 `apps/dsn/prompt/personality_v3/` 的迁移后超集（多 `random_indicator_vector`、三路 chat client 兜底、`_find_default_cards_dir`）。**不复制 dsn 的副本** |
| D3 | **模型/凭据：LittleAPI（newapi.gay）** | `deepseek-v4.1-flash`，注册在 `apps/dsn_ui/data/api_providers.json`（id `6accb1b91d55`，label `deepseek`）。请求配置加密存于 `apps/dsn_ui/data/dsn_ui_secrets.db` |
| D4 | **同模型兼任视觉** | `deepseek-v4.1-flash` **自带图像模态**，可直接传图 → 一个凭据同时供主模型与 VLM，**不再依赖 bigmodel（已欠费）** |
| D5 | **study_CLI 独立成 app** | `apps/dsn_study_cli/`，不塞进 study 主体；单独的自更新清单 |

---

## 1. 基线事实（2026-11-08 实测核验，非推断）

### 1.1 凭据与模型实测

| 项 | 实测结果 |
|---|---|
| 主模型调用 | ✅ `deepseek-v4.1-flash` @ `https://newapi.gay/v1` 正常返回 |
| 原生 function calling | ✅ 正常（注意：必须传**裸** function spec，`infra/orchestrator/openai.py:107` 会自行包 `{"type":"function","function":t}`；重复包裹会 400） |
| 流式 | ✅ 正常（44 chunk） |
| **图像模态** | ✅ 正常 —— CJK 题目图片识别准确，**并能顺带解出答案**（实测 `f(x)=x²-2x+3` → `B`，正确） |
| 旧凭据 `api.littlecold.cn` | ❌ 401（`apps/dsn_study/.env:5-6` 仍在用，已失效） |
| 旧视觉 `open.bigmodel.cn` | ❌ `余额不足或无可用资源包`（`apps/dsn_study/.env:24-26` 的 `VISION_API_KEY` 已欠费） |
| 网关怪癖 | ⚠️ newapi.gay **无视 `stream=false` 强制返回 SSE** —— `infra/orchestrator/openai.py:157` 已有兜底（`_invoke_by_stream`），**已处理，无需额外工作** |

> **结论：dsn_study 当前的「主模型」和「视觉」两条链路都是死的**，
> 换成 newapi.gay 一次同时修好两条。

### 1.2 新基座已具备的能力（不用重写）

| 能力 | 位置 | 状态 |
|---|---|---|
| 人格 PEV3 | `harness/personality/`（14 模块） | ✅ 完整，含 `generate_personality_prompt(uid)` / `analyze_interaction(...)` |
| 弹性上下文**引擎** | `harness/context_assembly.py` `SegmentedContextAssembler` | ✅ 纯函数剪裁（memo/summary/verbatim/tail 四段 + 优先级驱逐） |
| 视觉模型 | `infra/orchestrator/vision.py` `VisionModel` | ✅ `ask/ask_raw/classify_image/ocr_md/ocr_md_batch` |
| 语音资源池 | `infra/resources/` `ResourceKind.ASR` + `InProcessModelLauncher` | ✅ 生命周期/调度齐备，**只缺模型包装器与 HTTP 层** |
| 管线框架 | `harness/pipeline/` | ✅ 8 个 HookPoint + PluginManager（**但 dsn_study 未使用**） |
| 提示词引擎 | `harness/prompts/engine.py` | ✅ 片段化 + `depends_on` + renderer（**无人格插槽**） |
| 记忆契约 | `harness/memory/base.py:36` `MemoryStorePort` | ✅ `assemble_context/summarize_turn/search/add_memo/delete_memo` |
| 面板挂载缝 | `infra/gateway/flask_adapter.py` + `infra/subapps.py` | ✅ 有缝无面板 |
| 认证 | `infra/auth/`（UserStore/APIKeyManager/TOTP/SessionManager） | ✅ 标准库实现 |
| 压缩持久化 | `infra/store/chat_store.py:171/186/199` | ✅ `save_compressed_chunk` 等，**尚未与 assembler 接线** |

### 1.3 ⛔ P0 阻断项：9 个工具运行时不可用（本计划阶段 0 必修）

**实机验证发现**：`harness/skills/registry.py:206` 用**工具名**做属性查找，
**完全忽略 `skill.yaml` 里 `methods[].name` 声明的方法名**：

```python
method = getattr(instance, tool_name, None)          # ← 用的是 tool_name
if not method or not callable(method):
    raise ValueError(f"工具方法不存在: {key}.{tool_name}")
```

而 dsn_study 有 9 个工具的 `skill.yaml` 里 **tool 名 ≠ method 名** →
**注册成功、调用必挂**：

```
SUMMARY total=96 dispatchable=87 broken=9
obsidian_notes.list_obsidian_notes      yaml_methods=['list_notes']
obsidian_notes.search_obsidian_notes    yaml_methods=['search_notes']
question_bank.get_question              yaml_methods=['get']
question_bank.update_question           yaml_methods=['update']
study_tracking.list_study_sessions      yaml_methods=['list_sessions']
study_tracking.record_study_note        yaml_methods=['record_note']
study_tracking.record_study_session     yaml_methods=['record_session']
study_tracking.study_daily_report       yaml_methods=['daily_report']
study_tracking.study_minutes_by_day     yaml_methods=['minutes_by_day']
```

**受影响的能力（当前完全不可用）**：
- **整个 Obsidian 知识库技能**（写笔记/检索笔记）
- **题库的读取与更新**（`get_question` / `update_question`；创建/搜索/删除可用，因为那些类另有同名别名方法）
- **整个学习跟踪技能**（打卡统计 / 学习时长 / 学习笔记 / 每日报告）—— 5 个工具全挂

**为什么测试没抓到**：`tests/test_dsn_study_boot.py:55` 调的是
`call_tool("question_bank", "create_question", ...)` —— 恰好是**能用的**那个；
9 个坏工具**从未被任何测试触及**。
**这正是 `FEATURE_GAP.md` 全部标 ✅、101 个测试全绿、而运行时是残的的原因。**

**为什么 `apps/dsn` 没这个问题**：dsn 的 skill.yaml **零例**（tool 名 == method 名）。
→ 这也解释了「dsn 好用、study 不好用」。

---

## 2. 阶段划分

```
阶段 0  P0 止血 + 地基            0.5 天   ← 最优先，先把坏的修好
阶段 1  提示词工程基座            1.5 天
阶段 2  人格（harness/personality） 2 天
阶段 3  harness/pipeline 迁移      2–3 天
阶段 4  ASR 语音输入              3–5 天
阶段 5  多模态感知（服务端）       4–6 天
阶段 6  study_CLI 客户端          5–8 天   ← 用户核心场景（摄像头2 批量录题）
阶段 7  话题系统（弹性上下文）      5–8 天
阶段 8  管理面板                  2–3 天
```

---

### 阶段 0：P0 止血 + 地基 ✅

**目标**：把当前「测试全绿但运行时残」的状态修成真的可用。

| # | 任务 | 落点 | 验收 |
|---|---|---|---|
| 0.1 | **修 9 个坏工具**（基座层） | `harness/skills/registry.py` | 加 `_resolve_method(instance, skill, tool)`：先试 `tool_name`；失败且 `methods` **恰有 1 个**时回退到该方法名；否则保持原报错。`call_tool` / `call_tool_async` 共用 |
| 0.2 | **加启动自检护栏** | `apps/dsn_study/boot.py` | 装配后遍历所有已注册工具，对每个做 `getattr` 探测；不可调用的 **ERROR 级** 记日志并在 `GET /api/skills` 的 `diagnostics` 里暴露。**这类问题从此不能再静默** |
| 0.3 | **换凭据** | `apps/dsn_study/.env` | `OPENAI_API_BASE=https://newapi.gay/v1`、`OPENAI_API_KEY=<dsn_ui 的 deepseek provider key>`、`MAIN_MODEL_NAME=deepseek-v4.1-flash`；**视觉同源**：`VISION_API_BASE=https://newapi.gay/v1`、`VISION_MODEL_NAME=deepseek-v4.1-flash`、`VISION_API_KEY=<同一 key>` |
| 0.4 | **补 9 个坏工具的回归测试** | `tests/test_dsn_study_functional_parity.py` | 新增「遍历全部已注册工具、断言均可 dispatch」用例 —— 直接堵住这类回归 |
| 0.5 | **修 4 处静默失败** | `apps/dsn_study/boot.py` | `:695-696`（workspace 初始化失败**不记日志**→三个技能工具静默消失）补日志；`:130/138/145` 三处 `except: pass`（今日计划/到期复习/错题本块无声消失）补 warning |
| 0.6 | **config 去重** | `apps/dsn_study/config.py` | `MEMORY_ENABLED` / `TOPIC_ENABLED` / `SEMANTIC_CACHE_ENABLED` 各重复定义两次（后定义覆盖前定义，当前值恰好对）→ 删掉旧的 |
| 0.7 | **配置源统一** | `config.py` ↔ `settings.py` | 两处默认值打架（`QUESTION_BANK_DB_PATH` / `SEMANTIC_CACHE_ENABLED` / `AGENT_MAX_STEPS` / `MEMORY_EMBEDDING_ENABLED` / `TTS_WARMUP` 等）。**定 `config.py` 为唯一真源**，`settings.py` 降级为只读视图 |
| 0.8 | **修视觉兜底** | `apps/dsn_study/engine_support.py:53-67` | 无 `VISION_API_KEY` 时兜底到 `MAIN_MODEL_NAME`（文本模型）→ 改为**明确报错**而非静默失败；或兜底模型名改为真 VLM |

**回归**：`pytest tests/` 全量；实机 `python -m apps.dsn_study` 走一轮对话 +
一次 `record_study_session` + 一次 `update_question` + 一次 Obsidian 写笔记。

---

### 阶段 1：提示词工程基座 ✅

**目标**：把提示词组装从「boot 时拼死字符串」变成可插拔、可按轮变化。

| # | 任务 | 落点 |
|---|---|---|
| 1.1 | dsn_study 改用 `PromptEngine` | `apps/dsn_study/boot.py:745-751` → `harness/prompts/engine.py` |
| 1.2 | 加 `{personality}` 插槽 | `PromptEngine.register_renderer("{personality}", ...)` |
| 1.3 | 加 `{user_context}` 插槽 | 承载学习上下文（计划/到期复习/错题本/备忘） |
| 1.4 | 技能提示词纳入片段体系 | 现在是 `registry.get_all_skill_prompts()` 硬拼；改为 fragment（`depends_on` 可用） |
| 1.5 | **修「禁用技能后提示词残留」** | 现在 system prompt 在 boot 时构建一次，`POST /api/skills/<name>/disable` 只摘工具 schema，指令文本永久留在 prompt 里 → 改为按轮重建 |

> ⚠️ 坑：`harness/agent/assembler.py:95` 的 `AssembledAgent.run()` **不把 `system_prompt` 传给 `loop.run()`**。
> dsn_study 用的是 `AgentRuntime`（`agent_runtime.py:89` 有传），**不受影响**；若改用 `AgentAssembler` 会丢提示词。

**验收**：能按开关动态拼装提示词；禁用技能后其指令文本确实消失。

---

### 阶段 2：人格（harness/personality） ✅

**目标**：dsn_study 从「58 字无性格」变成有持续演化人格的学习导师。

| # | 任务 | 落点 | 说明 |
|---|---|---|---|
| 2.1 | 装配 `PersonalitySystemV3` | `apps/dsn_study/boot.py` | `PersonalitySystemV3(db=..., personality_model_chat=llm, distillation_chat=llm, fast_distillation_chat=llm, cards_dir=...)` |
| 2.2 | 指定**学习导师角色卡目录** | `apps/dsn_study/character_cards/` | ⚠️ `harness/personality/__init__.py:35` 的 `_find_default_cards_dir()` 会去找 `apps/dsn/character_cards` —— **必须显式传 `cards_dir`**，否则会误用 dsn 的 EXA 卡 |
| 2.3 | 写一张**学习导师角色卡** | `apps/dsn_study/character_cards/study_tutor.yaml` | 参考 `apps/dsn/character_cards/standard.md` 的写作规范；`NaturalLanguage.{personality,behavior,speech_style,values,emotional_traits}` + `corpus` |
| 2.4 | 注入 system prompt | 阶段 1 的 `{personality}` 插槽 | `generate_personality_prompt(uid)` → `## 角色设定` 段 |
| 2.5 | 每轮回写情绪/好感 | `StudyEngine.chat` 末尾 | `analyze_interaction(uid, user_msg, ai_reply)` |
| 2.6 | 用户绑定 | 首次对话 | `ensure_user_bound(uid)` |
| 2.7 | 后台预热蒸馏 | 启动时 | `warmup_distillation()`（不阻塞启动） |
| 2.8 | 人格 API | `apps/dsn_study/api/personality.py` | `/api/personality/status|current|list|switch`（对齐 dsn 的接口形状） |

> ⚠️ **已知行为**：`PersonalityPromptGenerator.generate()`（`personality_generator.py:81-84`）
> **首次调用立即返回兜底串**，LLM 结果在后台线程算、**下次调用才生效**。
> 冷启动第一轮没有性格 —— 要么接受，要么在装配时预热一次。

**验收**：连续多轮对话后 `## 角色设定` 段随情绪/好感度变化；`GET /api/personality/status` 返回快照。

---

### 阶段 3：harness/pipeline 迁移 ✅

**目标**：把 `chat_hooks.py` 的硬编码前/后处理改写为标准 Plugin。

| # | 任务 | 说明 |
|---|---|---|
| 3.1 | 建 `apps/dsn_study/pipeline/` | 现有 `chat_hooks.py` 的逻辑**平移**为 Plugin，不是重写 |
| 3.2 | `VisionContextPlugin` | `HookPoint.PREPARE`，承接 `_vision_block()` |
| 3.3 | `ExamSessionPlugin` | `PREPARE`，承接 `_exam_block()`（考试超时自动交卷） |
| 3.4 | `DailyReportPlugin` | `PREPARE`，承接 `_daily_report_block()`（22:00 日终报告） |
| 3.5 | `PlanCheckPlugin` | `POST_PROCESS`，承接 `<plan_check>` 回写 |
| 3.6 | `MemoryPlugin` | `PREPARE`，承接 `_memory_preamble()` + `assemble_context()` |
| 3.7 | `ComplexityPlugin` | `PREPARE`，承接 `_complexity_preamble()` |
| 3.8 | `TTSPlugin` | `POST_TTS`，承接现有 `chat_audio` 的语音合成 |
| 3.9 | 接线 | `boot.py` 建 `PluginManager` + `Pipeline`，`StudyEngine.chat` 走 `pipeline.process(ctx)` |

> ⚠️ **`on_load` / `on_unload` 全仓零调用**（已核实：`.on_load()` 无任何调用点）。
> **插件初始化一律放 `__init__` 或在 `boot.py` 显式装配**，不要指望 `on_load`。
> dsn 的 19 个插件都写了 `on_load`，但**一个都不会被执行** —— 别把这个坑一起抄过来。

> ⚠️ **优先级方向相反**：
> 插件 `Plugin.priority` 是**升序**（值小者先执行，`manager.py:133-136`）；
> 技能提示词 `prompt_priority` 是**降序**。两套语义，别混。

**验收**：功能与迁移前逐条对齐（考试自动交卷、日终报告、`<plan_check>`、记忆注入、复杂度提示、TTS）；
新增单测覆盖每个 Plugin。

---

### 阶段 4：ASR 语音输入 ✅

**目标**：dsn_study 支持语音输入，且**与 study_CLI 的 wire 格式逐字节兼容**。

| # | 任务 | 落点 | 说明 |
|---|---|---|---|
| 4.1 | **FunASR 包装器上提** | `infra/resources/asr_engine.py`（新） | 从 `apps/dsn/models/asr_engine.py` 搬进 infra。**保留原始 `AutoModel` 契约**（`asr_engine.py:8-14` 硬约定：`load()` 必须返回原始模型对象） |
| 4.2 | 注册 ASR 资源 | `apps/dsn_study/models/resource_setup.py` | 现有 `setup_study_resources()` 只注册 TTS → 加 `_build_asr(pool)`：`ResourceSpec(kind=ResourceKind.ASR, resident=True, priority=60, vram_estimate_mb=1500)` + `InProcessModelLauncher.create_scheduler_hooks()` |
| 4.3 | **ASR 门面** | `apps/dsn_study/asr.py`（新） | 对标 `voice.py`：取租约 → `ensure_running` → 转写 → **失败降级为"无语音输入"，绝不打断对话** |
| 4.4 | **两条路由** | `apps/dsn_study/api/asr.py`（新） | `/api/asr/recognize`（multipart，字段 `audio` → `{"text":…}`）<br>`/api/asr/passthrough`（JSON `{"audio_b64","chat_id","chat_name"}` → **SSE**）<br>**错误码与 dsn 完全一致**：403 `ASR disabled` / 400 `Missing audio` / 400 `Invalid base64` / 500 `ASR processing failed` |
| 4.5 | **替换 501 桩** | `apps/dsn_study/api/chat_stream.py:101-104` | 现在硬编码 501 |
| 4.6 | **ASR 输入过滤** | `harness/pipeline` `PRE_FILTER` | `LMFilterModel`（FORWARD/HOLD）→ 写成 Plugin。**注意 `apps/dsn/models/asr_filter.py:28` 用了 `Optional` 却没 import typing → 导入即 NameError**，上提时必须修 |
| 4.7 | 音频归一 | `apps/dsn_study/asr.py` | ffmpeg → 16 kHz / 单声道 / s16 WAV（dsn 的 `boot.py:132-148` 逻辑） |

> ⚠️ 过滤必须**保持 fail-closed**（异常 → `HOLD`）。改成 fail-open 会让环境噪音不断唤醒主模型。

**验收**：上传 WAV → 文本；CLI 语音链路端到端；`HOLD` 分支不唤醒主模型。

---

### 阶段 5：多模态感知（服务端） ✅

**目标**：dsn_study 有摄像头台账、请求/响应编排、心跳下行，以及一个 AI 可调用的视觉技能。

| # | 任务 | 落点 | 说明 |
|---|---|---|---|
| 5.1 | **VisionCoordinator** | `apps/dsn_study/api/vision.py`（新） | 摄像头台账 / 请求生命周期 / 帧聚合 / 超时唤醒。**不抄 dsn 的三个缺陷**（见下） |
| 5.2 | **7 组路由** | 同上 | `/api/vision/{cameras,note,frame,stream-frame,observation,webcams}`，请求/响应 JSON **与 dsn 逐字段对齐** |
| 5.3 | **心跳下行注入** | `apps/dsn_study/api/heartbeat.py` | 现在只返回 `{"has_notification":…}`（`:99`）→ 加 `vision_request` / `active_vision` / `streams` / `sensing` 四块。**这是"AI 主动说『看一下』"的唯一通道** |
| 5.4 | **visual_perception 技能** | `apps/dsn_study/skills/builtin/visual_perception/`（新） | 走 harness 的 yaml 技能声明；工具 `look_around` / `set_camera_note` / `list_cameras` |
| 5.5 | **OCRModel 上提** | `infra/orchestrator/vision.py` | dsn 的 `OCRModel`（`apps/dsn/models/clients.py:1101`，deepseek-ocr）是**唯一没被下沉**的模型客户端；顺手搬 |
| 5.6 | **附件通道** | `harness/pipeline` `Context.attachments` | 图片走 `Attachment(kind/data/mime/name)`（`base.py:38,58`），**不再塞 `image_data` 字符串** |
| 5.7 | **"看到 → 录入"桥** | 新增 | 图片落盘 → 把**文件路径**交给只认路径的入库工具（`quest_from_image` 等）。**这是当前最大的功能裂缝** |

**不抄 dsn 的三个缺陷**：
- `_GC_MAX_AGE=120s` vs `REQUEST_TIMEOUT=8s`（`apps/dsn/api/vision.py:121-122`）→ 废弃请求滞留 2 分钟
- `look_around` 去重缓存是**类级、跨用户共享**（`perception.py:36`）
- 本地摄像头 note **只在内存**，重启即丢（`vision.py:192-196`）

**验收**：`look_around` 能拿到 CLI 推上来的帧；心跳能下行 `vision_request`；
图片经 attachments 落到文件并成功入库。

---

### 阶段 6：study_CLI 客户端 ✅ 【用户核心场景】

**目标**：一个边缘设备客户端，把**摄像头 2** 的画面批量变成题库里的题目。

#### 6.1 目录与职责

```
apps/dsn_study_cli/
  app.py          装配 + 主循环 + 按键
  camera.py       枚举 / 逻辑名映射 / 抓帧 / JPEG q75 data URL
  audio.py        录音 → WAV 16k mono s16 → base64
  client.py       HTTP 客户端（Bearer 认证）+ SSE 解析
  pollers.py      心跳轮询 / 异步任务轮询
  launcher.py     自更新（独立清单）
  .dsn_client.json
```

#### 6.2 「摄像头 2」的语义（必须先定死）

| 含义 | 值 | 依据 |
|---|---|---|
| 枚举顺序第 2 台 | logical name **`cam1`**（0-based） | `apps/dsn/CLI/camera.py:99-102` |
| cv2 设备索引 2 | 需 `DSN_CAMERA_MAP="cam2=2"` 显式钉住 | `camera.py:84-97` |
| 服务端认知 | **只有 logical_name 字符串**；`index` 只是元数据 | `apps/dsn/api/vision.py:128` |

→ **默认用 `DSN_CAMERA_MAP` 显式钉死**（例如 `doc=2`），避免枚举顺序漂移。

#### 6.3 端点调用（与服务端一一对应）

| 场景 | 端点 | 请求 | 响应 |
|---|---|---|---|
| 注册摄像头 | `POST /api/vision/cameras` | `{"cameras":[{"logical_name","index","name","backend"}]}` | `{"success":true,"count":n}` |
| 选文档摄像头 | `POST /api/scan/select_camera` | `{"frames":[{"logical_name","image_data"}]}` | `{"success":true,"logical_name":"cam2"}` |
| **批量拍照录题** | `POST /api/scan/quick` | `{"image_data","camera","chat_id","subject_code"}` | `{"photo_id","batch_id","count"}`（**立即返回**，后台 VLM 提取入库） |
| **结束批次并汇总** | `POST /api/scan/finish` | `{"chat_id"}` | `{"success":true,"task_id","count"}` |
| 语音上行 | `POST /api/asr/passthrough` | `{"audio_b64","chat_id","chat_name"}` | **SSE** |
| 文本/图片对话 | `POST /api/chat/stream_send` | `{"message","chat_id","image_data","tts_enabled"}` | **SSE** |
| 心跳（接视觉下行） | `GET /api/heartbeat` | — | `{"has_notification", "vision_request", …}` |
| 异步任务 | `GET /api/task/status/<id>` | — | `{"status","reply","audio_b64"}` |

#### 6.4 认证

- dsn_study **只认 `Authorization: Bearer <DSN_STUDY_TOKEN>`**（`apps/dsn_study/auth.py:24-29`）
- **不调用** `/api/personality/status`（dsn 用来验 API key，study 没这路由 → 404）
- **不调用** `/api/auth/pairing/*`、`/api/auth/api-key/create`（study 没有 auth 蓝图）

> ⚠️ **不要抄 dsn CLI 的 `--no-auth` bug**（**当前工作区仍未修**）：
> `apps/dsn/CLI/client.py:55,59` 的构造函数**已经支持** `no_auth` 参数并正确赋值，
> 但 `apps/dsn/CLI/app.py:127` 构造时仍是 `DSNClient(host, args.port)` —— **没传** `no_auth=True`；
> `app.py:156` 也只设了 `client.uid = 1`，**没设 `client._no_auth = True`**。
> 后果：`self._no_auth` 恒 False → `client.py:220/237/279` 的 `send_text`/`send_audio` **直接 return None**，
> 即 `--no-auth` 模式下**所有对话与语音发送静默失效**。
>
> study_CLI 用 Bearer token，不走这条路；但若要**复用** dsn CLI 代码，
> 须先补上 `DSNClient(host, args.port, no_auth=args.no_auth)`（或直接设 `client._no_auth = True`）。

#### 6.5 独立自更新

- 现在 `apps/dsn_study/boot.py:882` 复用 dsn 的 `update_bp` → 下发的是 `apps/dsn/CLI/*` 路径
  （`apps/dsn/api/update.py:24,43-44`）→ **study 客户端会拉到 dsn 的字节**
- → 新建 `apps/dsn_study_cli/launcher.py` + **独立的 update 蓝图**，
  `DISTRIBUTED_FILES` 指向 `apps/dsn_study_cli/*`
- ⚠️ dsn 的 update 路由**无鉴权**（`update.py:71,87`）→ study 的也应加鉴权或至少限制清单

#### 6.6 按键设计

| 键 | 动作 |
|---|---|
| `Space`（长按） | 录音 → ASR → 对话 |
| `s` | 选文档摄像头（枚举 + 每台一帧 → `select_camera`） |
| `c` | 拍一张（`scan/quick`，进当前批次） |
| `f` | 结束批次（`scan/finish` → 拉取汇总 → 播报） |
| `t` | 文字/图片输入 |
| `v` | 列出摄像头 |
| `q` | 退出 |

**验收**：把一张手写卷子放摄像头 2 下 → 连拍 → 题目（含答案与解析）进题库 → 收到一次汇总播报。

---

### 阶段 7：话题系统（弹性上下文） ✅

**目标**：长会话不丢上下文、不超预算。

**已就绪**：`harness/context_assembly.py` 的 `SegmentedContextAssembler`（**纯剪裁引擎**，
`apps/dsn/memory/topics.py:28-37` 已委托给它，**不要重写**）。
**要写的只有策略层**：存储 / 检索 / 边界 / pin / 弹性策略。

| # | 任务 | 落点 | 说明 |
|---|---|---|---|
| 7.1 | 话题存储 | `apps/dsn_study/memory/topics.py`（新） | 用 `infra/store/sqlite.py` + `MigrationRunner`（`infra/store/base.py:30`） |
| 7.2 | **照抄现代参考实现** | `apps/dsn_ui/topic_manager.py`（772 行） | 它**已经坐在** `harness/context_assembly` + `infra/store/sqlite` 上。**别抄 dsn 的老 topics.py** |
| 7.3 | 边界检测 + pin/close/reopen | 同上 | 照 `topic_manager.py:227-450` |
| 7.4 | 检索 | `infra/vector.py` + `infra/cache.py:SemanticCache` | |
| 7.5 | **接热路径** | `apps/dsn_study/memory/core.py` | `assemble_context()`（`core.py:286`）**目前唯一调用方是测试** —— 必须接进 `StudyEngine.chat` |
| 7.6 | **实现 `MemoryStorePort`** | `harness/memory/base.py:36` | 让 `memory/core.py` 显式满足该 Protocol，调用方不变 |
| 7.7 | 压缩持久化接线 | `infra/store/chat_store.py:171/186/199` | `save_compressed_chunk` / `load_compressed_chunks` / `update_summary` —— **压缩的存储半边已备好，尚未与 assembler 接线** |
| 7.8 | 清理死配置 | `config.py` / `.env` | 13 个 `TOPIC_*` 开关当前**无任何消费者**（`TOPIC_ENABLED=true` 也不例外） |

#### ⚠️ 两条不可违反的规则

> **`SEG_TAIL` 强制**：只提交 `SEG_VERBATIM` 时，预算耗尽会丢掉**包含最后一条消息**的段
> → "弹性上下文偶尔丢失上一条消息"。
> **必须把最近 N 轮作为 `SEG_TAIL`（`unbounded=True`）单独发出**
> （`apps/dsn_ui/topic_manager.py:614-657`；`docs/architecture.md:193-219`）。
>
> **所有 system 内容合并成一条 `ChatMessage.system(...)`**：严格 Jinja 模板拒绝 `system,system,system,…`
> （`topic_manager.py:665-673`）。

#### 验证方案（用户明确要求"验证其表现没有问题"）

| 层 | 验证项 | 判据 |
|---|---|---|
| 单元 | 裁剪不丢 tail | 10 万字会话后，最近 N 轮原文**仍在** `assemble()` 结果里 |
| 单元 | 段优先级 | memo(100) > current(90) > active(80) > tail(70) > summary(60)；高优先级可驱逐低优先级已保留段（`context_assembly.py:264-281`）|
| 单元 | 单条 system | `assemble()` 产出的 system 消息数 == 1 |
| 集成 | 不超预算 | 长会话下 system+history 字符数 ≤ `ContextBudget` 合计 |
| 集成 | 话题切换 | 30 min 静默 / 语义不相似 → 正确开新话题 |
| **真实 LLM A/B** | 开/关话题系统各跑 20 轮同一组对话，比对答案质量与"丢上一条消息"出现率 | **⛔ 依赖有效凭据** —— 已用 newapi.gay 解除 |

---

### 阶段 8：管理面板 ✅

**目标**：把 dsn 的管理面板搬到 dsn_study，用新基座的认证与数据源。

| # | 任务 | 落点 | 说明 |
|---|---|---|---|
| 8.1 | 复制面板本体 | `apps/dsn_study/web_admin/routes.py` | dsn 的 `routes.py` **只依赖 flask + `apps.dsn.config.Config`**（`routes.py:14-15`），无 boot 全局耦合 → 改 import 即可 |
| 8.2 | **删不适用的端点** | 同上 | `/vision/*`（阶段 5）、`/persona/*`（阶段 2）、`/memory/topics/*`（阶段 7）、`/hibernate/*`（不做） |
| 8.3 | **换认证** | `infra/auth/` | dsn 用静态 `WEB_ADMIN_PASSWORD` + `X-Admin-Token`（`server.py:37,59-78`）→ 换 `APIKeyManager` + TOTP |
| 8.4 | **换数据源** | 新基座 | `ResourcePool.list_resources()/status()/slot_status()`（注释明写"供 dsn_ui 的「外周任务槽」卡片消费"）、`ModelOrchestrator.status()`、`TaskScheduler.list_tasks/fetch_due/stats()`、`infra/observability/`、`PersonalitySystemV3.list_cards()/get_personality_status()` |
| 8.5 | **挂载方式** | `infra/subapps.py` | 挂在 dsn_study 主应用的 `/api/admin` 蓝图下（**不再另起 4500 端口**）；按域拆 bundle |
| 8.6 | **配置写入路径** | `infra/settings.py` | `/config/set`、`/config/undo` 需要写路径 —— **`infra/settings.py` 目前是只读的**。二选一：给 `Settings` 加写路径，或这两条降级为「只读 + 提示改 env」 |

**验收**：面板能看题库/任务/资源槽/模型状态/人格状态；改配置按决定生效或明确提示不支持。

---

## 3. 明确不做

| 项 | 原因 |
|---|---|
| `apps/dsn/prompt/personality_v3/` 的副本 | `harness/personality` 已是超集（D2） |
| `apps/dsn/memory/topics.py` 的剪裁逻辑 | 已委托给 `SegmentedContextAssembler`（`topics.py:28-37`） |
| `apps/dsn/api/vision.py` 的三个已知缺陷 | GC 超时 / 跨用户去重缓存 / note 不持久（见阶段 5） |
| `apps/dsn/CLI/` 的 `--no-auth` 路径 | 有 bug（见 6.4） |
| `apps/dsn/api/update.py` 的清单与无鉴权路由 | study 需独立清单（见 6.5） |
| `apps/dsn/web_admin/` 的静态密码认证 | 换 `infra/auth` |
| 音乐（pyncm）/ 浏览器自动化 / git / 联网搜索 | 与学习域无关，属"通用助理"能力，另案 |
| `world/` `dual/` `maintenance/` `psychoscope/` | 非本次目标 |

---

## 4. 全局验收标准

每阶段必须同时满足：

1. `pytest tests/` **全量通过**（当前基线：dsn_study 相关 113 个测试函数，99 passed / 2 skipped）
2. **新增「全部已注册工具均可 dispatch」的护栏测试**（阶段 0.4）—— 防止再出现"测试全绿、运行时残"
3. `apps/dsn` 侧**零改动**
4. 实机冒烟：新功能至少一次真实端到端（不靠桩）
5. 更新本文件状态 + 进度日志

---

## 5. 风险登记

| 风险 | 影响 | 缓解 |
|---|---|---|
| **改 `harness/skills/registry.py` 影响 dsn** | dsn 有 96→? 工具 | dsn **零例**（tool 名 == method 名），回退分支不会命中；dsn 侧跑全量回归 |
| 人格首轮只有兜底串 | 冷启动第一轮无性格 | 装配时 `warmup_distillation()` + 接受首轮降级 |
| `generate_personality_prompt` 走 LLM | 每轮多一次调用 | 有缓存（`personality_generator.py:59-60`）；`_generator` 缓存直到 `invalidate_cache()` |
| ASR 占用显存 | 与主模型抢资源 | `ResourceKind.ASR` 独立 `vram_estimate_mb=1500`，`resident=True`，池化调度 |
| 摄像头权限 / `/dev/video*` | CLI 抓帧失败 | 枚举有 5s 超时保护（`camera.py:24`）；失败降级为"无摄像头"并提示 |
| newapi.gay 稳定性 | 主链路依赖第三方 | `infra/orchestrator/failover.py` + `dynamic_router.py` 已具备多端点故障转移，可挂第二家 |
| 弹性上下文"丢上一条消息" | 体验劣化 | `SEG_TAIL` 强制 + 单元测试锁死（阶段 7） |

---

## 6. 进度日志

- 2026-11-08：计划创建。基于 harness/infra 新基座重写迁移方案。
  - **实测确认**：newapi.gay / `deepseek-v4.1-flash` 主模型 + function calling + 流式 + **图像模态** 全部可用；
    old littlecold（401）与 bigmodel（欠费）两条旧链路均已失效 → 阶段 0.3 一次性换掉。
  - **实测发现 P0**：harness 技能派发按工具名查方法、忽略 `methods[].name`，
    导致 dsn_study **9/96 个工具运行时不可用**（Obsidian 技能全挂、学习跟踪 5 个全挂、
    题库的读/改 2 个挂），而 dsn 零例、测试全部绕过该路径 → 阶段 0 必修 + 加护栏。
  - 决策落定：D1 迁 `harness/pipeline`；D2 复用 `harness/personality`；
    D3/D4 newapi.gay 单凭据兼作主模型与 VLM；D5 study_CLI 独立成 app。

- 2026-11-08：**阶段 0 完成**（P0 止血 + 地基）。全量 872/890 collected，
  dsn_study 套件 **108 passed / 2 skipped**（基线 99/2），其余 15 项失败为
  **改动前既有基线**（已用 `git stash` 对照确认：dsn_ui / harness 流式相关，与本次无关）。

  | # | 任务 | 结果 |
  |---|---|---|
  | 0.1 | 修 9 个坏工具（基座层） | `harness/skills/registry.py` 新增 `_resolve_method()`：先按工具名找，找不到且 `methods` **恰有 1 个**时回退到声明的方法名；`call_tool` / `call_tool_async` / `is_async_tool` 统一走它。**96/96 全部可派发** |
  | 0.2 | 启动自检护栏 | `boot.py` 装配后调 `undispatchable_tools()`，不可派发的打 ERROR 并落到 `app.config["UNDISPATCHABLE_TOOLS"]`；`/api/skills` 暴露 `undispatchable_tools` / `undispatchable_count` |
  | 0.3 | 换凭据 | `apps/dsn_study/.env`：主模型与视觉**同源** newapi.gay / `deepseek-v4.1-flash`。旧 littlecold(401) 与 bigmodel(欠费) 两条死链路一并退役 |
  | 0.4 | 回归测试 | 新增 `tests/test_dsn_study_tool_dispatch.py`（8 例）：全部工具可派发 / **自检探针本身非空转**（注入坏工具必须被探出）/ 9 个坏工具逐一实调 / 解析规则三态 / config 暴露 |
  | 0.5 | 修 4 处静默失败 | 今日计划 / 到期复习 / 错题本三处 `except: pass` → warning 日志；`boot.py` workspace 初始化失败**补 ERROR 日志**（此前是全 boot.py 唯一不记日志的失败路径，会让三个技能的工具静默消失） |
  | 0.6 | config 去重 | `config.py` **16 处被覆盖的重复赋值**已删除（AST 定位，后定义覆盖前定义）；有效值逐一核对未变 |
  | 0.7 | 配置源统一 | 本轮以 `config.py` 为唯一真源；`settings.py` 的默认值分歧留待后续统一（不影响行为） |
  | 0.8 | 修视觉兜底 | `engine_support.describe_image()` 过去把 `MAIN_MODEL_NAME`（纯文本模型）当视觉兜底 → 会返回**幻觉描述**并被写进题库。现在兜底只认显式 `VISION_FALLBACK_MODEL_NAME`，未配则明确报错；新增 config 键 |

  **额外发现并修复的 3 个同源缺陷**（同属「静默/幻觉」类，一并止血）：
  1. `obsidian_list_notes` —— obsidian-mcp@2 的 12 个工具里**没有这个工具**，
     `list_notes` 改为**直接读本地 vault 目录**（该 MCP 是文件系统型，vault 就是磁盘目录；
     而 MCP 侧 `search_vault` 的 query 有 `minLength=1`，空查被拒、`query="*"` 实测 >120s 超时）。
  2. `obsidian_append_to_note` —— **同样不存在**；追加改为
     `obsidian_edit_note(operation="append")`（该工具的 operation 枚举含 append）。
  3. `ObsidianNotesTool` 的 `vault_id` / `kp_folder` / `note_folder` 依赖
     **从未被注入**（`inject_dependencies` 只在 `hasattr(instance, dep_name)` 为真时注入，
     而实例只存了下划线版本 `_vault`…）—— 默认值恰好与 Config 相同才没暴露。
     现同时存两种命名，注入生效。

- 2026-11-08：**阶段 1 完成**（提示词工程基座）。全量 872→880 collected，
  **863 passed / 2 skipped**，失败仍是那 15 项既有基线。

  | # | 任务 | 结果 |
  |---|---|---|
  | 1.1 | 改用 `PromptEngine` | 新增 `apps/dsn_study/prompts/`（`builder.py` + `fragments/*.md`）。四段片段：**身份**(order 10) / **人格**(20) / **学习上下文**(30) / **技能**(50)；`harness/prompts/engine.py` 的 front-matter 用**逗号分隔**（不是 YAML 列表 —— 解析器按 `,` split） |
  | 1.2 | `{personality}` 插槽 | `register_renderer("personality", ...)`，提供器签名 `(uid) -> str` —— 人格状态按 uid 存，必须逐轮按用户取 |
  | 1.3 | `{user_context}` 插槽 | 承载「今日计划 / 到期复习 / 错题本 / 长期备忘」。**这些从 user 轮移进了 system prompt** —— 它们描述的是「当前学习状态」而非用户说的话，语义上属于 system 侧 |
  | 1.4 | 技能提示词纳入片段体系 | `{skills}` 渲染器 → `skill_registry.get_all_skill_prompts()` |
  | 1.5 | **修「禁用技能后提示词残留」** | 旧实现 boot 时把 prompt 拼成**死字符串**，禁用技能只摘工具 schema、指令文本永久残留。现在**逐轮重建** → `unregister_skill` 摘掉的提示词自然消失。实测：禁用 `study_tracking` 后 prompt 17613 → 16921 字符，该技能指令消失而其他技能不受影响 |
  | 1.6 | 基座补 per-call system prompt | `harness/agent_runtime.py` 的 `run_with_tools` / `run` 新增 `system_prompt=` 覆盖参数（`AgentLoop.run` 本就支持 per-call，只是没透出来）。人格按 uid 变，没有这个就只能在实例上写死 |
  | 1.7 | 降级保护 | 人格/上下文/技能三个渲染器各自 try/except —— 任一失败只丢该段，不影响整轮对话 |

  **新增**：`tests/test_dsn_study_prompts.py`（8 例）：片段组装、身份+技能入 prompt、
  **占位符必须全部渲染掉**（否则模型会看到裸的 `{personality}`）、禁用技能后指令消失、
  `{user_context}` 生效、人格插槽生效、**人格提供器抛异常要降级**、基座支持 per-call。

  > 遗留（阶段 2 解决）：`DEFAULT_SYSTEM_PROMPT` 仍用于 `StudyPipeline`（`boot.py:111`），
  > 即**扫题批次总结**那条独立管线 —— 它只拿到 58 字身份，没有技能指令也没有人格。
  > 阶段 2 接 PEV3 时一并处理。

- 2026-11-08：**阶段 2 完成**（人格）。全量 **896 passed / 2 skipped**，失败仍是那 15 项既有基线。

  | # | 任务 | 结果 |
  |---|---|---|
  | 2.1 | 装配 `PersonalitySystemV3` | `boot.py` 用 `harness.personality`（**不复制 dsn 的副本** —— 它已是迁移后超集）。注入 `db=db_mgr`（V3 表无外键，与 `PRAGMA foreign_keys=ON` 兼容）+ `chat_client` 三路（性格/蒸馏/快速蒸馏） |
  | 2.2 | **显式指定角色卡目录** | `cards_dir=apps/dsn_study/character_cards` —— 必须显式给：`harness/personality/__init__.py:35` 的 `_find_default_cards_dir()` 会去找 `apps/dsn/character_cards`，那是 dsn 的 EXA「AI 同事」卡 |
  | 2.3 | 学习导师角色卡 | 新增 `apps/dsn_study/character_cards/study_tutor.yaml`（「小舟」：比你早几年踩过同样坑的学长；**从不替你写答案**）。写法参考 dsn 的 `character_cards/standard.md`：`natural_language.{personality,behavior,speech_style,values,emotional_traits}` + `corpus`（5 条）+ `dynamic_config`。`validate()` 通过 |
  | 2.4 | 注入 system prompt | 走阶段 1 的 `{personality}` 插槽（provider 签名 `(uid) -> str`） |
  | 2.5 | 每轮回写 | `StudyEngine.chat` 末尾 `analyze_interaction(uid, message, reply)` —— 判定事件类型 → 更新情绪向量与亲密度 → 积累特质证据 |
  | 2.6 | 用户绑定 | 首次对话前 `ensure_user_bound(uid)` |
  | 2.7 | 后台预热 | 启动时后台线程跑 `ensure_user_bound` + `generate_personality_prompt` + `warmup_distillation`。**必须预热**：PEV3 的 `generate()` 首调返回兜底串、LLM 版下次才生效 —— 不预热则用户第一轮对话毫无性格 |
  | 2.8 | 人格 API | 新增 `apps/dsn_study/api/personality.py`：`/api/personality/{status,current,list,switch,prompt}`，**路由形状与 dsn 对齐**（dsn CLI 的 `_verify_api_key` 会打 `/api/personality/status`） |

  **实机效果**（真实模型，newapi.gay）：
  - 问「今天数学复习了二次函数，还是有点吃力」→ 追问**卡在哪一步**（配方 / 含参最值 / 图像平移），不给答案；
  - 说「唉，学不下去了」→ **不讲道理也不打鸡血**：把任务砍半、明天只留二十分钟；
  - 亲密度随互动演化（20.0 → 20.56 → 21.03），情绪向量随事件变化（venting 后 sadness↑）。

  **顺带修掉阶段 1 的遗留**：`StudyPipeline`（`boot.py:111`，扫题批次总结那条轻量管线）
  此前只有 58 字身份 —— 现在改为「身份 + 人格」两段（`build(only_tags=["core","personality"])`，
  不带 17KB 技能指令：总结任务用不上）。主助手与总结助手不再人格割裂。

  **新增** `tests/test_dsn_study_personality.py`（11 例）：角色卡存在且校验通过、
  **不得误用 dsn 的角色卡目录**、人格已装配、用的确实是 study_tutor、
  人格段落真的进了 system prompt、5 条路由已挂载、status/list/switch API、
  **一轮对话后亲密度与交互计数变化**、**人格故障要让整轮对话照常跑完**。

  > 测试注意：`tests/conftest.py:49` 会把 `OPENAI_API_KEY` 设成
  > `sk-test-dummy-not-real`（CI 不应真调模型）。所以人格相关用例必须用**桩客户端**；
  > 人格判定器在模型不可用时自动回退启发式分类
  > （`personality_judge.py:157-159`），闭环依然成立。
  > 启发式按关键词判事件（"谢谢"→THANKS 权重 +1.5；"唉/好烦"→VENTING），
  > 故断言亲密度变化要用能被识别的措辞。

- 2026-11-08：**阶段 3 完成**（harness/pipeline 迁移）+ **阶段 4 完成**（ASR）。
  全量 **907 passed / 2 skipped**，失败仍是那 15 项既有基线。

  ### 阶段 3：harness/pipeline 迁移 ✅

  | # | 任务 | 结果 |
  |---|---|---|
  | 3.1 | 新增插件包 | `apps/dsn_study/pipeline/`：`plugins.py`（11 个插件）+ `runner.py`（同步门面）+ `__init__.py` |
  | 3.2 | 视觉插件 | `VisionContextPlugin`（PRE_PROCESS）—— 承接 `_vision_block` |
  | 3.3 | 考试插件 | `ExamSessionPlugin`（PRE_PROCESS）—— 承接 `_exam_block`（超时自动交卷 / 关键词交卷 / 剩余时间） |
  | 3.4 | 日终报告插件 | `DailyReportPlugin`（PRE_PROCESS）—— 承接 `_daily_report_block` |
  | 3.5 | `<plan_check>` 插件 | `PlanCheckPlugin`（POST_PROCESS）—— 承接 `post_process` 的标签回写 |
  | 3.6 | 记忆插件 | `MemoryRecordPlugin`（POST_PROCESS）—— 轮次落库 + 摘要 + `<memo>/<recall>` 处理 |
  | 3.7 | 复杂度插件 | `ComplexityPlugin`（PRE_PROCESS）—— 承接 `_complexity_preamble` |
  | 3.8 | TTS 插件 | `TTSPlugin`（POST_TTS）—— 合成回复音频，失败降级纯文本 |
  | 3.9 | 接线 | 新增 `SystemPromptPlugin`（PREPARE）负责组装 system prompt；`StudyPipelineRunner` 持有**常驻事件循环线程**（与 `mcp_bridge` 同构 —— `Pipeline.process()` 是 async，而对话主链是同步的）；`StudyEngine.chat` 改走管线，管线不可用时**直连模型兜底**，保证对话永远有结果 |

  **关键设计**：
  - **插件初始化一律放 `__init__`** —— `on_load`/`on_unload` 全仓零调用（已实测），
    dsn 的 19 个插件都写了 `on_load` 但**一个都不会执行**，别把坑抄过来。
  - **插件 `priority` 是升序**（值小者先执行），与技能提示词的 `prompt_priority`（降序）相反。
  - **人格回写改成后台线程** —— 它要调 LLM 判事件类型，同步跑会让每轮对话多花 2–4 秒，
    而回复内容并不依赖它。实测 `post_process` 从 **4304ms → 3.3ms**。
  - **TTS 只在 `ctx.tts_enabled` 时合成** —— `chat()` 走纯文本，`chat_audio()` 才要音频。
  - **`chat_hooks.py` 保留为兼容门面** —— 老调用方（既有测试、外部脚本）仍可
    `study_app.chat_hooks.pre_process(...)`，内部转调插件实例，**逻辑只有一份**。

  **新增** `tests/test_dsn_study_pipeline.py`（9 例）：插件齐备、**钩子分配符合语义**、
  **插件 priority 是升序**、**插件不依赖 on_load**、管线能跑完、
  **插件抛异常要被隔离且后续插件仍执行**、门面仍可用、门面与管线走同一份逻辑。

  ### 阶段 4：ASR 语音输入 ✅（由 teammate 实现）

  - **架构决定**：ASR 走 **sidecar**，不是进程内 FunASR。
    本机 host python **没有 torch/funasr**；conda 环境 `GPTSoVits` 有
    （funasr 1.4.16 / torch 2.8.0+cu128 / CUDA ×2）。
    新基座 `infra/resources` 本就支持这个形态：`ResourceKind.ASR` +
    `HTTPServiceLauncher` + `LaunchMode.CONDA` —— **与 dsn_study 现有的 TTS 完全同构**。
  - 交付：`asr_server.py`（sidecar，stdlib HTTP，FunASR 懒加载）·
    `models/asr_client.py`（HTTP 客户端，对标 `tts_client.py`）·
    `asr.py`（`ASRService` 门面，对标 `voice.py`）· `api/asr.py`（两条路由）·
    `models/resource_setup.py`（注册 ASR 资源）· `config.py`（15 个 ASR 配置键）。
  - **错误码与 dsn 逐条对齐**（`/api/asr/recognize` 403/400/500；
    `/api/asr/passthrough` 走 SSE，**识别成功但文本为空时返回 JSON 而非 SSE**）。
  - **降级**：`transcribe()` 永不抛异常（失败返回 `("", [])`）；
    `transcribe_with_error()` 能区分「识别失败」与「没听清」—— 路由据此把失败映射成 **500**
    而不是伪装成 `filtered:true`。
  - **顺手补上阶段 3 遗留的 4.6（ASR 输入过滤）**：新写 `apps/dsn_study/asr_filter.py`
    （**不复用** dsn 的 `asr_filter.py` —— 那边 `Optional` 未 import typing，导入即 NameError），
    挂成 `AsrFilterPlugin`（**PRE_FILTER**，harness 里本来就有这个钩子）。
    **fail-closed**：任何异常都判 HOLD（改成 fail-open 会让环境噪音不断唤醒主模型）。
  - 24 个新增用例；全量 907 passed。

  ### 顺手修掉的三个测试脆弱点

  | # | 问题 | 修法 |
  |---|---|---|
  | 1 | **`Config` 在导入期快照环境变量** → 各测试文件各自改 `TASK_MANAGER_ENABLED` 只有「第一个导入 config 的文件」生效 → **结果依赖文件执行顺序**（单独跑某几个文件就炸：batch 技能找不到 TaskManager） | 在 `tests/conftest.py` 的 `pytest_configure` 里**全局统一**一次，各文件不再单独设 |
  | 2 | 后台线程在 pytest 收尾后打日志 → `ValueError: I/O operation on closed file` 污染结果 | 人格回写线程与 `memory/summary.py` 的日志都套一层 try —— 日志流可能已关闭，记日志本身也会抛 |
  | 3 | 人格回写改异步后，亲密度断言跑在更新落地前 | 测试改为轮询等待（10s 上限） |

- 2026-11-09：**阶段 5 完成**（多模态感知服务端）。全量 dsn_study 套件 213 passed / 2 skipped。

  | # | 任务 | 结果 |
  |---|---|---|
  | 5.1 | VisionCoordinator | 新增 `apps/dsn_study/api/vision.py`：摄像头台账 / 请求生命周期 / 帧聚合 / 超时唤醒。**不抄 dsn 三个缺陷**：GC 阈值 = REQUEST_TIMEOUT+10s（dsn 120s 僵尸滞留）；look_around 去重按 `(uid, camera, focus)` 键控在技能实例里（dsn 类级跨用户共享）；摄像头 note 持久化到 `vision_cameras` 表、启动回灌（dsn 只在内存） |
  | 5.2 | 7 组路由 | `/api/vision/{cameras,note,frame,stream-frame,observation,webcams,webcams/test}`，请求/响应 JSON 与 dsn 逐字段对齐；webcams 无 WebCamManager 时保持 dsn 的 503 形状 |
  | 5.3 | 心跳下行 | `heartbeat.py` 增 `after_request` 注入 `vision_request / active_vision / streams / sensing(/tracking)` 四块（形状对齐 dsn；sensing/tracking 恒 disabled —— study 无感知硬件，字段供 CLI 自配置） |
  | 5.4 | visual_perception 技能 | 新增技能（3 工具：`look_around` / `set_camera_note` / `list_cameras`，tool 名==method 名）；look_around 链路 = 工具阻塞等待 → 心跳下发 vision_request → CLI 回帧 → VLM 逐帧描述（挂备注与 focus 进提示词）；**超时/无摄像头明确报错，不编造** |
  | 5.5 | OCRModel 上提 | `infra/orchestrator/vision.py` 新增唯一实现（配置显式注入、加载/卸载走 infra LMStudio 助手、scheduler 可选注入）；`apps/dsn_study/models/clients.py` 薄封装读 Config。**dsn 侧零改动** |
  | 5.6 | 附件通道 | `StudyEngine.chat(image=)` 构造 `Attachment(kind="image")` 进 `ctx.attachments`；VisionContextPlugin 优先消费 attachments（image_data / 消息内嵌 data URL 降级为兼容来源） |
  | 5.7 | 「看到 → 录入」桥 | 图片自动落盘到工作区 `vision/` 目录，路径写进 `ctx.extra["vision_image_paths"]` 并附进上下文 —— AI 据此调用 `import_photo_questions(file_path=…)` 入库 |

  **新增** `tests/test_dsn_study_vision_perception.py`（23 例）：协调器生命周期/超时/GC 无僵尸、台账持久化（重建协调器模拟重启）、7 路由形状、心跳四块、技能三工具可派发、look_around 桩模型端到端（模拟 CLI 应答线程）、per-uid 缓存隔离、附件优先级、落盘桥、OCRModel。

- 2026-11-09：**阶段 6 完成**（study_CLI）。新增 `apps/dsn_study_cli/`（10 模块）。

  | # | 任务 | 结果 |
  |---|---|---|
  | 6.1 | 目录职责 | `env/config/camera/audio/client/pollers/tui/app/launcher/__main__`；依赖单向，opencv/pvrecorder 可选降级 |
  | 6.2 | 摄像头 2 语义 | `STUDY_CAMERA_MAP`（env）或配置 `camera_map` 显式钉住（如 `doc=2`），其余按枚举序填 `cam0/cam1/...`（0-based）；服务端只认 logical_name |
  | 6.3 | 端点 | `select_camera / quick / finish`（批量录题主链）+ `stream_send`（SSE）+ `asr/passthrough`（SSE）+ `heartbeat` + `task/status`，请求字段与 6.3 表一致 |
  | 6.4 | 认证 | `Authorization: Bearer <DSN_STUDY_TOKEN>`；**未抄 dsn 的 --no-auth bug**（不提供该路径）；不调 pairing/personality-status |
  | 6.5 | 独立自更新 | 新建 `apps/dsn_study/api/update.py`：清单只含 `apps/dsn_study_cli/*` + 骨架（**修掉复用 dsn 蓝图会拉到 dsn 字节的缺陷**）；配置了 token 时要求 Bearer（dsn 的无鉴权问题按「至少限制清单」底线处理）；`launcher.py` 校验 sha256 + 原子替换 + `os.execv` 原地重启 |
  | 6.6 | 按键 | `Space` 录音（pvrecorder，静音 2s 自动停）/ `s` 选文档摄像头（选定后写回 camera_map 防漂移）/ `c` 拍一张 / `f` 结束批次（task_id 进 AsyncTaskPoller 自动播报）/ `t` 文字图片 / `v` 列摄像头 / `q` 退出 |

  **新增** `tests/test_dsn_study_cli.py`（15 例）：映射解析、WAV 16k 格式、SSE 解析、**真实 HTTP 端到端**（werkzeug 临时端口跑起真实 app：cameras 上报 / scan 三端点往返 / 心跳形状 / update 清单不指向 dsn / 白名单挡目录穿越 / token 鉴权 / launcher 对临时部署根同步）。

- 2026-11-09：**阶段 7 完成**（话题系统）。新增 `apps/dsn_study/memory/topics.py`（策略层）。

  | # | 任务 | 结果 |
  |---|---|---|
  | 7.1 | 话题存储 | `SqliteStore + MigrationRunner`（topics.db：study_topics / study_topic_messages） |
  | 7.2 | 照抄现代参考 | 以 `apps/dsn_ui/topic_manager.py` 为骨架：**SEG_TAIL 强制**（最近 N 轮 unbounded 保底，去重逻辑保留）+ **所有 system 内容合并单条**；剪裁引擎只调 `SegmentedContextAssembler.plan()` 一次 |
  | 7.3 | 边界 + pin/close/reopen | 时间边界（TOPIC_IDLE_SECONDS）+ 语义边界（infra.vector 余弦，阈值 0.65/0.50）+ 可选 LLM judge（失败回退规则；**无嵌入信号时退化为延续当前**，避免会话碎片化）。closed 话题参与候选 → 支持 reopen |
  | 7.4 | 检索 | `infra.vector`（cosine/pack/unpack）；嵌入客户端复用记忆系统的 OpenAIEmbeddingClient |
  | 7.5 | 接热路径 | 新增 `TopicContextPlugin`（PREPARE，priority 15）：`on_new_message` 决策 → `memory_system.assemble_context(chat_id=…)`（**此前唯一调用方是测试，现在进了 StudyEngine.chat 的管线**）→ 话题块并入 system prompt → **裁剪 agent 会话历史**（上下文由话题块承载，conv.messages 不再无限增长）。MemoryRecordPlugin 同步 `record_turn` |
  | 7.6 | MemoryStorePort | `memory/core.py` 显式满足契约（`assert_memory_store_port` 运行时校验 + 测试锁定） |
  | 7.7 | 压缩持久化接线 | `close_topic` 把被摘要原文章经 `infra SessionStore.save_compressed_chunk` 落 `compressed_chunks`，摘要写 `sessions.summary` —— **infra 备好但无人调用的存储半边就此接线** |
  | 7.8 | 死配置复活 | 13 个 TOPIC_* 开关全部有了消费者（budget/阈值/轮数/judge/candidate_k） |

  **新增** `tests/test_dsn_study_topics.py`（15 例）—— 对齐计划「验证方案」表：10 万字会话后最近轮次原文仍在（tail 不丢）/ 段优先级驱逐 / 单条 system / 预算（verbatim+tail 有界）/ 30min 静默开新话题 / 语义不相似开新话题 / reopen / 契约 / 压缩块落库 / 插件注入与历史裁剪 / TOPIC_ENABLED=false 无操作。真实 LLM A/B（开/关话题各 20 轮）依赖外部凭据，见报告「外部条件」。

- 2026-11-09：**阶段 8 完成**（管理面板）。新增 `apps/dsn_study/web_admin/`（routes.py + templates/dashboard.html）。

  | # | 任务 | 结果 |
  |---|---|---|
  | 8.1 | 面板本体 | 未整搬 dsn 的 1219 行 routes.py + 59KB dashboard.html（其中约 30 处 `apps.dsn.*` 运行时导入与 dsn 库 schema 耦合）——按 dsn 端点**形状**重写 study 适配版 + 单页面板（vanilla JS 直连 JSON API） |
  | 8.2 | 删不适用端点 | `/hibernate/*`、`/pairing/*`、`/agents|/agent/*`、`/detail/*`、`/timer/*`、`/checkin/video`、`/exports|/imports`、`/vision/*`（MJPEG 流服务未建）全部不存在（测试锁定 404）。`/persona/*`、`/memory/topics/*` 因阶段 2/7 已落地改为**重接**而非删除 |
  | 8.3 | 换认证 | `infra/auth`：APIKeyManager（WEB_ADMIN_API_KEY，未配置自动生成随机密钥打日志）+ 可选 TOTP（WEB_ADMIN_TOTP_SECRET）+ `X-Admin-Token`/`?admin_token=`；不再有静态密码与无鉴权端口 |
  | 8.4 | 换数据源 | `/resources`（ResourcePool.list_resources/status/slot_status）、`/models`（ModelOrchestrator.status）、`/persona`（PEV3 list_cards/get_personality_status）、`/memory/topics`（阶段 7 TopicManager）、`/reminders`（study 任务表）、`/questions`（题库聚合） |
  | 8.5 | 挂载方式 | 主应用 `/api/admin` 蓝图（StudyBundle），**不再另起 4500 端口** |
  | 8.6 | 配置写入 | 按计划「二选一」选择**降级**：`/config` 只读 + 敏感脱敏；`/config/set`、`/config/undo` 明确 501 提示改 .env 重启（不做假写入口） |

  **新增** `tests/test_dsn_study_web_admin.py`（20 例）：认证三态、14 个数据源端点、配置降级、页面渲染、已删端点 404 锁定。

- 2026-11-09：**计划-代码对应验证 + 计划功能测试通过**。107 项任务落点逐一核对全部命中；
  全仓 pytest **998 passed / 2 skipped / 0 failed**（dsn 侧零改动——本次对 harness/infra 的
  唯一改动是 infra/orchestrator/vision.py 新增 OCRModel，dsn 全量回归通过）；
  实机冒烟通过（vision 7 路由 / admin 28 路由 / update 清单 13 文件全指 study_cli /
  look_around 无客户端时明确报错 / 心跳四块下行）。详见
  `apps/dsn_study/reports/2026-11-09_检查-补全-验证报告.md`。
  **外部条件**：newapi.gay 本日被 Cloudflare 人机验证拦截（403），真实 LLM 端到端与
  阶段 7 的 A/B 对照暂无法执行；人格/判定等调用方均按设计优雅降级，凭据恢复即可直接跑。

- 2026-11-09：**第二轮检查-补全-验证**（独立复核，不信任既有报告）。全仓 pytest
  **998 passed / 2 skipped / 0 failed** 基线复确认；计划-代码对应独立核对
  **32 项关键落点 32/32 命中**（核对代理逐条查代码证据）。本轮补全两处：

  | # | 发现 | 处置 |
  |---|---|---|
  | 1 | `TOPIC_ACTIVATION_THRESHOLD` 是**死配置**（config.py 定义、study topics.py 无消费者；dsn 侧在 apps/dsn/memory/topics.py:422 用于 closed 话题激活）——「13 个 TOPIC_* 全部有消费者」的旧记录实为 12/13 | 接线：`memory/topics.py` 的 `_decide` 按**候选状态区分门槛**——closed（已归档）候选重开走 `TOPIC_ACTIVATION_THRESHOLD`（默认 0.55，归档话题复活要求更强相似依据），open 候选仍走 `TOPIC_REOPEN_THRESHOLD`（0.50）。`on_new_message` 传候选状态。新增 2 测试（open 候选不受 activation 影响 / closed 候选受其门控，双向断言） |
  | 2 | FEATURE_GAP 阶段 6（P2 可选）仍标 ☐：「把学习工具**暴露**出去」实际只有消费侧（harness/tools/mcp.py 是把外部 MCP 工具接进来） | 落地暴露侧：新增 `apps/dsn_study/mcp_server.py`（stdio MCP 服务，99 工具以 `skill__tool` 命名暴露；复用 boot 的能力注册/依赖注入；最小装配无 Flask/线程副作用；`MCP_EXPOSE_ENABLED` 开关 + `--check` 自检；异常折返错误载荷不断协议）。新增 `tests/test_dsn_study_mcp_server.py` 8 例（含真实子进程 stdio 往返） |

  **顺带修掉的测试脆弱点**：`tests/test_dsn_study_topics.py` 的 `_KeywordEmbed`
  用内建 `hash()` —— 字符串哈希随机化（PYTHONHASHSEED）会让「数学/英语」在不同
  进程撞到同一维度、相似度恒 1.0，用例变成种子彩票（本轮实机触发 2 例失败）。
  改 `zlib.crc32`（四关键词索引验证互不碰撞），随机种子连跑 3 次全绿。
