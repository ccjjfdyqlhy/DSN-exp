# apps/ —— 应用层

> 读者：要给某个应用加功能、或要照着写一个新应用的维护者。
> 核心问题：**同一个框架，为什么七个应用长得完全不一样？**

---

## 一、先看这张总表

| 应用 | 行数 | 入口 | 默认端口 | Web 框架 | 用 Runtime/AppBundle | 定位 |
|---|---:|---|---|---|---|---|
| **`dsn_ui`** | 11.5k | `python main.py --app dsn_ui` | 8888 | FastAPI + uvicorn | ❌ | **日常主入口**，Web 控制台 |
| `dsn` | 58.6k | `python main.py`（默认） | 5000 | Flask + 终端 | ✅ 9 个 bundle | 语音陪伴，历史最长 |
| `dsn_study` | 10.0k | `python main.py --app dsn_study` | 5000 | Flask + FlaskGateway | ✅ 4 个 bundle | **Web 应用的正规范例** |
| `densechat` | 3.0k | `python -m apps.densechat` | 8080 | FastAPI + WebSocket | ❌ | WebUI 复刻，第二个完整产品 |
| `emotion_exp` | 836 | `python -m apps.emotion_exp` | — | 无（REPL） | ✅ 手写 | 人格 + 情绪组合范例，**零配置可跑** |
| `harness_lab` | 2271 | `python -m apps.harness_lab` | — | 无（CLI） | ❌ | **记忆与人格验证台**，离线可跑，产出验证报告 |
| `coding_agent` | 186 | `python -m apps.coding_agent` | — | 无（REPL） | 经 AgentRuntime | **最小可读范例** |
| `text_agent` | 106 | 无入口（库） | — | 无 | ✅ 手写 | 最小模板 |

### 三种装配风格

```
① harness 原生      text_agent → coding_agent
   直接用 AgentLoop / AgentRuntime，零 DSN 依赖。学它的写法最省心。

② 标准 Web 应用    dsn_study
   Runtime + Settings + ModelProviderRegistry + AgentRuntime
   + AppBundle + FlaskGateway。写新 Web 应用照抄这个。

③ 自成体系         dsn_ui / densechat / dsn
   历史原因各有自研的模型层、上下文、路由注册。功能最全，但绕开了框架门面。
```

---

## 二、`apps/dsn_ui` —— Web 控制台（主入口）

### 2.1 启动

```bash
python -m apps.dsn_ui.server --host 0.0.0.0 --port 8888 --slots 2
```

三个参数都可由环境变量覆盖：`DSN_UI_HOST` / `DSN_UI_PORT` / `DSN_UI_DEFAULT_SLOTS`。
**单进程**——SSE 广播与流会话注册表都是进程内单例，不要用多 worker 部署。

### 2.2 `create_app` 的装配顺序

```
1. DSNUIEngine          （内部持有 ModelOrchestrator 单例）
2. 外周资源池 ASR/TTS/VLM  失败置 None，不阻塞启动
3. Orchestrator 状态监听 → SSE 广播
4. ThoughtCacheService  ⚠️ 必须在 start() 前 set_emitter，否则首个事件丢失
5. lifespan            每 60s 清理流会话；退出时 shutdown
6. CORS                默认只放行本机，allow_credentials=False
7. 路由注册            ⚠️ 全部必须在 SPA catch-all 之前
8. SPA catch-all       未命中的 GET 一律返回 index.html
```

### 2.3 路由地图

| 分组 | 代表路径 |
|---|---|
| llama-ui 兼容 | `/props` `/models` `/models/load` `/models/unload` `/models/sse` `/slots` `/tools` |
| OpenAI 兼容 | `/v1/chat/completions` `/chat/completions` |
| 可恢复流 | `/v1/streams/lookup` `/v1/stream`（GET/DELETE） |
| DSN 记忆与情绪 | `/api/emotion` `/api/agent/prompt` `/api/topic/converged` `/api/context/stats` |
| Agent 设置 | `/api/agent/tools` `/api/agent/settings` `/api/agent/context-strategies` |
| 思考链缓存 | `/api/thought-cache/{status,templates,config,distill,recall}` |
| 系统资源 | `/api/system/resources` `/api/resources/{start,stop,slots}` `/api/system/kv-offload` |
| 设置与健康 | `/api/settings` `/api/health` |
| 启动参数预设 | `/api/models/launch-params*` `/api/models/launch-once` |
| 远程 Provider | `/api/providers*` |
| System-1 决策 | `/v1/decide` `/v1/decide/capabilities` |
| 接入配置 | `/api/onboarding/*` `/api/tts/*` |
| ASR | `/api/asr/recognize` |
| 集成 | `/v1/integration/*` `/v1/messages`（Anthropic 兼容） |

> ⚠️ **最常见的故障模式**：新增 GET 路由注册在 SPA catch-all 之后 → 返回 index.html
> → 前端报 `Unexpected token '<'`。所有子模块路由都要在 `create_app` 中、
> catch-all 之前用 `register_*_routes(app, engine)` 挂载。

### 2.4 对话主路径的四个分支（最重要的一节）

`apps/dsn_ui/agent.py` 的 `chat_stream()` 是所有行为的汇聚点：

```
请求进来
  │
  ├─ api_mode == "passthrough" ?
  │     是 → 不注入提示词、不跑情绪、不读写记忆，messages 原样送模型
  │     否 ↓
  ├─ 请求方给了 system_prompt_override ?
  │     是 → 只用请求方文本
  │     否 ↓
  ├─ 请求带 client_tools ?
  │     是 → 保留完整对话结构（否则 tool 往返会被话题装配破坏）
  │     否 → topic_mgr.assemble_context_messages() 弹性剪裁
  │
  └─ execution_mode ?
        agent  → AgentLoop.run_stream()，服务端执行工具
        client → orchestrator.stream()，把 tool_calls 交还客户端
```

> ⚠️ **高发工单**：「模型调不了工具」通常是因为传了 `tools` 但没开 `execution_mode`，
> 服务端因此不执行任何工具。

### 2.5 两条必须同时修改的路径

`chat_stream()`（流式）与 `chat_invoke()`（非流式）是**两份重复的分支逻辑**。
后者还缺多模态 parts、上下文策略、context_stats 事件与流式 usage。
**改一个必须检查另一个。**

### 2.6 断线重连

`stream_sessions.py` 实现「后台生产者 + 字节缓冲 + 多订阅者 + TTL」：

- 客户端凭 `X-Conversation-Id` 恢复，用 `/v1/stream?from=N` 续读；
- 偏移会被吸附到 `data:` 事件边界（`resolve_offset()`）；
- 心跳 `: ping` **不写入缓冲**，避免污染偏移；
- 默认 TTL 600s、缓冲上限 256MB。

### 2.7 System-1 决策接口

`system1_api.py`。**这里有一个容易误解的点**：`/v1/decide` 是**本模块自己实现**的端点，
不是 llama.cpp 提供的。实现方式是 `max_tokens=1 + logprobs=true + top_logprobs=32`，
读首 token 的概率分布，再取出选项 token 的概率并归一化。

`/v1/decide/capabilities` 会先用 `/props` 校验 model_path 身份，再真发一次探针请求；
因为所有本地 llama.cpp 默认都占 8080，不校验就会打到别的模型上。


### 2.8 数据与凭据

`apps/dsn_ui/data/` 下散落多个独立存储（整个目录已被 .gitignore 忽略）：

| 文件 | 内容 |
|---|---|
| `dsn_ui_memory.db` | 记忆 |
| `dsn_ui_secrets.db` | 凭据**密文**（Fernet `enc:v1:`） |
| `thought_cache.db` | 思考链模板 |
| `api_providers.json` | Provider 名单（**明文**，密钥在密文库） |
| `model_launch_overrides.json` | 启动参数覆盖 |
| `agent_settings.json` | Agent 设置（⚠️ **整文件覆盖**写入） |

> ⚠️ **备份时 `.secret_key` 必须一起备份。** 丢了它又没设 `DSN_UI_SECRET_KEY`，
> 所有 provider 的 base_url / api_key 都无法恢复。

### 2.9 前端

- SvelteKit 5 + Svelte 5 + Tailwind 4，hash 路由，`bundleStrategy: 'single'`。
- `npm run build` = 生成 PWA 资源 → `vite build` → `scripts/sync-to-static.cjs`。
- ⚠️ `sync-to-static.cjs` **先 `rm -rf` 整个 `static/` 再拷贝**，手工放进去的文件会被冲掉。
- ⚠️ `npm run dev` 已失效（脚本 cd 到不存在的 `tools/ui`），请直接 `npx vite dev`。

---

## 三、`apps/dsn_study` —— 标准 Web 应用范例

**要写一个新的 AICF Web 应用，请以这个为模板。**

### 3.1 装配链（`boot.py`）

```
Flask + Config + 日志
  → Runtime + Settings（命名空间绑定）
  → ModelProviderRegistry（openai / lmstudio / llamacpp 三个工厂）
  → 本地认证垫片 + 题库主库（12 张题库表 + plan 3 + timetable 3 + async_tasks）
  → 学习子系统栈（题库/模板/模考/图谱/扫描/时间表/任务/计划）
  → SkillRegistry + SkillManager（扫描 builtin + 按技能注入依赖）
  → AgentRuntime（技能工具桥接进 ToolRegistry + 技能提示词聚合）
  → StudyEngine 门面（对话 + 学习上下文注入）
  → AppBundleRegistry + FlaskGateway 挂载蓝图
```

### 3.2 12 个内置技能

| 技能 | 工具数 | 典型工具 |
|---|---:|---|
| `question_bank` | 10 | create_question / search_questions / compose_exam / analyze_error |
| `exam_sim` | 4 | create_exam / start_exam / submit_answer / finish_exam |
| `exam_review` | 6 | get_exam_history / get_wrong_questions / mark_mastered |
| `knowledge_graph` | 6 | update_knowledge_state / get_due_reviews / analyze_weakness |
| `plan` | 7 | create_goal / add_phase / generate_daily_plan / check_off |
| `study_timetable` | 5 | get_today / check_in / check_out / get_stats |
| 其余 6 个 | 1–2 各 | quick_question / batch_import / text_extract / doc_to_questions / quest_from_image / question_print |

所有技能 `auto_activate` 均为 false，靠关键词触发两阶段 toolbox 激活。

> 数量以运行时为准：`GET /api/skills` 的 `skills` 字段是权威列表。

### 3.3 启动

```bash
python -m apps.dsn_study           # 终端 REPL
python -m apps.dsn_study --web     # Flask，默认 0.0.0.0:5000
python main.py --app dsn_study     # 等价于 --web
```

### 3.4 技能系统

技能系统的**唯一实现**在 `harness/skills/`，`apps/dsn` 与 `apps/dsn_study` 共用
（loader / manager / registry 三个文件都只是转发）。

* 目录：`apps/dsn_study/skills/{builtin,custom}/<技能名>/`
* `custom/` 是**插件目录**：放进去的技能即插即用；目录不存在时启动会自动创建
  并写一份说明（README.md）
* 依赖注入走**能力（capability）**机制：应用注册语义能力，工具类用
  `needs = {"question_store": "_store"}` 声明 —— 写新技能不必改 `boot.py`
* 加载期做一致性校验（类/方法/参数/能力/wire 名），问题可查：
  `GET /api/skills`
* 运行时管理（装/卸/启停/重载）：`POST /api/skills/install|reload|<name>/<action>`

详见 [skills.md](skills.md)。

> 2026-10 之前 `apps/dsn_study/skills/{loader,manager}.py` 与 `api/__init__.py`
> 是指向 `apps/dsn/` 的**软链**，改一边会静默改变另一边。
> 现已全部下沉到 harness 并改成普通转发文件，行为一致且无文件系统耦合。

---

## 四、`apps/dsn` —— 语音陪伴（最大，也最需要小心）

### 4.1 启动链路

```
python main.py
  → apps/dsn/entry.py main()
  → apps/dsn/main.py main()
       ├─ 导入 apps.dsn.api.app（该模块导入时即构建全部组件）
       ├─ Flask 起在 5000（daemon 线程）
       ├─ 可选：调试口 5050、Web Admin 8008、驻守模型
       └─ 进入 REPL：/ 开头是命令，其余发给驻守模型
```

### 4.2 终端命令

`/newbind` `/cleanup_users` `/users` `/status` `/plugin` `/memory` `/prompt`
`/config` `/listconfig` `/persona` `/login` `/export` `/import` `/reminder`
`/plan` `/detail` `/timer` `/help` `/agent` `/webcam`
，表外另有 `/stop` `/reboot` `/hibernate`。

### 4.3 引擎与插件

`engine.py` 的 `DSNEngine` 是中枢，`plugins/pipeline.py` 的 `ChatPipeline` 串起：

```
PRE_FILTER → 组装 prompt → PRE_PROCESS → MODEL_INVOKE
           → POST_PROCESS → AgentLoop → POST_TTS
```

16 个 builtin 插件：cache_interceptor、asr_filter、memory、models、impression、
personality_v3、personality、tts、tool、notebook、task、plan、recall、vision、todo、distill。

插件通过 `PluginDIContainer` 按**构造函数参数名**注入依赖（`container.py:35`），
引擎用 4 遍循环处理插件间依赖（`engine.py:697`）。

### 4.4 子包速查

| 子包 | 职责 |
|---|---|
| `api/` | 13 个 Blueprint + 若干路由（chat / asr / vision / plan / reminder / todo / music / auth ...） |
| `audio/` | 语音推理客户端（VocalExp） |
| `auth/` | L0–L4 分层认证（配对 / TOTP / WebAuthn / API Key / 会话） |
| `db/` | `ChatDBManager`（数据库 schema 中枢） |
| `document/` | 扫描、打印、OCR、HMD 自有文档格式 |
| `dual/` | Instant + Main 双模对话 |
| `maintenance/` | 三态状态机 + 待机 |
| `memory/` | `MemorySystem` + 话题记忆 |
| `models/` | 客户端 / 多账号 failover / TTS / ASR（**与 infra 重复，历史遗留**） |
| `prompt/` | V2 / V3 人格 + `PromptEngine` |
| `plugins/` | 插件框架 + 16 个 builtin |
| `CLI/` | 边缘设备多模态终端客户端（TUI + 感知来源，实验性；原 `psychoscope/minimal.py` 拆分而来） |
| `psychoscope/` | 客户端 Web 面板（`server.py` + `static/`，实验性） |
| `pyncm/` | 网易云音乐客户端（**vendored**，不要改） |
| `semantic_cache/` | L1/L2/L3 三层缓存 |
| `skills/` | 技能框架 + 10 个 builtin 技能 |
| `tracking/` | 行为日记本（摄像头 / 音频） |
| `web_admin/` | 独立管理后台（8008） |
| `world/` | 叙事世界引擎（**实验性**） |

### 4.5 这个应用特有的坑

- **三套并存的装配路径**：`DSNEngine(subapp_path)` 与 `create_engine_with_defaults()`
  是两条不同的初始化路线，字段可能不一致。
- **双事件循环**：引擎持有一个持久 loop（`_get_event_loop`），管线里又可能起线程。
- **静默 except**：大量 `except Exception: pass`，出问题不报错只降级。排查时先开 DEBUG。
- **端口不一致**：`config.py` 里 PSYCHOSCOPE_PORT 默认 5000，而 psychoscope 服务端默认 5500。

---

## 五、示例应用：该抄哪个

### 推荐阶梯

```
text_agent（106 行）  看懂「Runtime + ToolRegistry + AgentLoop」的最小组合
      ↓
coding_agent（186 行）加上 AgentRuntime 门面、工具注册、会话持久化
      ↓
dsn_study（10k 行）   加上 AppBundle、技能 yaml、Web 网关、多子系统
```

### `coding_agent` —— 最小可读范例

```bash
python -m apps.coding_agent
```

读环境变量 `OPENAI_API_KEY` / `OPENAI_API_BASE` / `MAIN_MODEL_NAME`，
`CODING_AGENT_DB` 指定会话持久化位置。6 个工具：read/write/list/bash/grep/git_diff。

> ⚠️ 它的 `run_bash` 用 `shell=True` 且无路径校验。**给新应用抄代码时不要抄这里。**

### `emotion_exp` —— 唯一能零配置跑起来的示例

```bash
python -m apps.emotion_exp
```

没有 `OPENAI_API_KEY` 时自动降级到 `StubChatClient`（三句固定回复），
因此**可以直接跑起来看流程**。演示了人格系统 PEV3 + 5D 情绪 + 话题上下文剪裁的组合。

### `text_agent` —— 模板

没有可运行入口（`entry.py` 只打印提示），价值在于展示「手写 Runtime + 手动注册工具」
的最短形式（106 行）。

### `densechat` —— 事件流翻译的参考

```bash
python -m apps.densechat --host 0.0.0.0 --port 8080 --project .
```

它的价值在于 `engine.py` 的 `_run_harness_loop()`：把 `AgentLoop` 的
`round_start / reasoning / delta / tool_call` 事件翻译成前端 WebSocket 时间轴。
**要做「Agent 事件 → 前端展示」时读这里。**

代价：它自己实现了 config / store / profiles / tools，是「框架能力被业务重写」的样本。

---

## 六、横向对比：为什么它们不一样

| 维度 | dsn_ui | dsn_study | densechat | emotion_exp | coding_agent | text_agent |
|---|---|---|---|---|---|---|
| DI Runtime | ❌ | ✅ | ❌ | ✅ | 间接 | ✅ |
| AppBundle | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ |
| 直接调用 AgentLoop | ✅ | 经 AgentRuntime | ✅ | ✅ | 经 AgentRuntime | ✅ |
| 模型来源 | 自建 Orchestrator | ModelProviderRegistry | 自管 provider | OpenAICompatClient | 同左 | 调用方注入 |
| 工具来源 | standard + toolbox | 技能 yaml 桥接 | standard + 自建 | 手写 3 个 | tool_from_function | 手写 2 个 |
| 上下文 | 自研 topic_manager | AgentRuntime | 自研 | 自研 | ThreeZoneContext | Conversation |

### 历史遗留（改代码时会撞上）

1. **`apps/*/models/` 与 `infra/orchestrator` 三套模型层并存。**
   新代码请用 `infra.orchestrator`，旧的不急着动。
2. **`dsn_ui` 完全不参与 Runtime/AppBundle 体系**，却直接 import `harness.agent.loop` 等内部件。
3. **四个平行的「Agent 门面」**：`AgentRuntime` / `DSNUIAgentCoordinator` /
   `StudyEngine` / `EmotionExpAgent`。它们的职责高度重叠但各写各的。

---

## 七、`apps/harness_lab` —— 记忆与人格验证台

> 定位：**不是产品，是验证台**。回答「harness 现有的记忆与人格系统，
> 是否真的按预期工作」。

| 项 | 说明 |
|---|---|
| 入口 | `python -m apps.harness_lab`（默认离线、无需凭据、1~2 秒跑完 56 项检查） |
| 覆盖 | `harness/personality`（PEV3 十四模块）、`harness/memory`（契约 + 向量原语）、`harness/context_assembly`（预算剪裁） |
| 方法 | 预设 10 个**人格演化方向**（连续表扬 / 连续冲突 / 情绪宣泄 / 奖惩交替 / 长期消失 / 越界 / 空白卡演化 / 蒸馏保真度 / 记忆累积 / 上下文预算），每条对应 PEV3 里一条明确机制 |
| 关键手法 | 桩客户端**如实遵守 `max_tokens`** → 离线复现线上的截断类故障；`--no-truncate` 作对照组把根因锁死 |
| 产出 | `.dsn/harness_lab/report.md` + `report.json`（每条失败附证据） |
| 测试 | `tests/test_harness_lab.py`：每条检查一项用例，已知缺陷标 `xfail(strict=True)` |

当前基线（2026-11-11）：**60/60 通过**。最初跑出 51/56，5 项失败全部指向 harness
的真实缺陷（蒸馏产物因 `max_tokens` 截断而全空、证据只存内存导致重启失忆、
`plan()` 就地改写入参、兜底串串味、缓存不分用户），当天全部修掉，
并把每条改成"必须持续通过"的回归项。详见 `apps/harness_lab/README.md`。

---

## 八、dsn_study 的两个内核（2026-11-11 重建）

> 背景与决策见 `apps/dsn_study/REFACTOR_PLAN.md`（含实施记录 §14）。

| 包 | 职责 | 关键设计 |
|---|---|---|
| `apps/dsn_study/context/` | 长上下文内核：学习状态 / 长期事实 / 会话摘要 / 最近对话 → 统一预算 → 一条文本进 system prompt | 6 模块单向依赖；全局硬预算**含 tail**；截断保留**尾部**；禁止静默丢中段；纯函数不改入参；每轮产出 `ContextTrace` |
| `apps/dsn_study/persona/` | 人格薄层：规则信号（零 LLM）+ 提示词呈现（≤800 字）+ API 形状 | 复用**已修好的** PEV3 底座；判定默认走关键词规则（不与主回复抢 provider 队列）；卡片进版本库 |
| `apps/dsn_study/gating.py` | 运行时可求值的开关层 | 改文件即生效，不用重启；优先级 env > 文件 > 默认；求值失败回退默认 |

关键修复（同一批）：会话 id 跨进程稳定（`session_chat_ids` 表）、contextvars 残留、
流式路径补跑 PRE_PROCESS、`<plan_check>` 不再外泄到用户可见文本与 TTS、
角色卡从被 `.gitignore` 忽略的目录迁进版本库。

回归：上下文内核 28 条 + 人格内核 51 条 + 端到端接线 8 条单测；
全仓 `pytest tests/` 1227 passed，失败项与改动前**完全一致**（均为环境问题）。
