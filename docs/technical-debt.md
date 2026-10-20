# 已知技术债与修复优先级

> 读者：准备动手改代码的维护者。**先读这篇，再读源码。**
> **状态（2026-10-20 更新）**：本文列出的 P0 问题**全部已修复**。
> 保留条目是为了记录「曾经出过的错」与修复思路 —— 按仓库惯例，
> 「注释即缺陷数据库」，历史同样有留存价值。
> 当前测试基线：**547 通过 / 0 失败 / 0 收集错误**（另有 18 个按 marker 排除）。

> 本文所有条目均经过源码核对或实际运行验证；标注「未验证」的是静态阅读推断。

---

## 优先级定义

| 级别 | 含义 |
|---|---|
| **P0** | 功能受损，用户可感知。建议尽快修 |
| **P1** | 能力「已写未接」或口径不一致，会造成困惑与隐性错误 |
| **P2** | 设计与一致性问题，不紧急但影响可维护性 |

---

## P0-1. 收束轮的角色序列非法

**位置**：`harness/agent/loop.py:515-519`

**现象**：Agent 达到 `max_steps` 且最后一轮仍在调用工具时，用户看到的是
占位文本「…[已达到步数上限，且未能生成收束答复…]」，而不是总结。

**原因**：收束轮把 user 消息直接追加在 **tool 消息之后**：

```python
finalize_msgs = list(msgs) + [ChatMessage.user("已达到本次自主执行的步数上限…")]
```

此时 `msgs` 尾部是 tool 消息。多数 chat_template（Qwen / Llama-3 / DeepSeek）要求
tool 消息必须紧跟在含 `tool_calls` 的 assistant 之后，`tool → user` 序列会抛错。
该异常被 `loop.py:537` 的 `except Exception` 静默吞掉，只留一条 warning。

**影响范围**：仅「步数耗尽且末轮仍在调工具」这一条路径；`run_async` 与 `run_stream` 都有。

**建议修法**：收束轮内把尾部 tool 消息合并成一条 user/system 文本，或对收束轮使用
不含 tool 角色的精简历史。

---

## P0-2. EventBus 异步订阅失效

**位置**：`harness/pipeline/events.py:22` 与 `:64`

**现象**：通过 `EventBus.subscribe()` 注册的 **async** 处理器，在同步 `publish()`
时收不到事件（或收到后副作用不生效），日志里只有一条含糊的「事件 X 处理器异常」。

**原因**：

```python
def __init__(self):
    _bus_tasks: set[asyncio.Task] = set()   # ← 局部变量！

def publish(self, event, payload=None):
    ...
    _bus_tasks.add(task)                    # ← 引用未定义的全局名
```

**实测复现**（本仓库 conda 环境）：

```text
事件 x 处理器异常
Traceback (most recent call last):
  File "harness/pipeline/events.py", line 65, in publish
    _bus_tasks.add(task)
NameError: name '_bus_tasks' is not defined
```

**建议修法**：一行改动——`self._bus_tasks = set()`，并把两处引用改为 `self._bus_tasks`。
这是全仓库**投入产出比最高**的修复。

---

## P0-6. `killpg(0)` 误杀宿主进程（2026-10-20 修复）

**位置**：`infra/orchestrator/local_engine.py::kill_process_tree`

**现象**：跑 `pytest tests/test_harness_strata.py` 时，**pytest 进程被自己的
SIGTERM 打死**（exit 143）；日志尾部只剩「已终止」，连外层 shell 进程组一起带走。
全量 `pytest` 更是在打印完 `538 passed` 之后**挂死**，直到被 `timeout` 杀掉。

**原因**：原实现直接执行

```python
os.killpg(os.getpgid(pid), signal.SIGTERM)
```

而 `os.getpgid()` 对**内核线程**返回 **0**（本机 PID 99 = `kworker/R-blkcg`，
其 pgid 就是 0）。按 POSIX，`killpg(0, sig)` 等价于 `kill(-0, sig)`——
给**调用者自己所在的进程组**发信号，而不是给目标进程组发。

触发路径：`tests/test_harness_strata.py` 曾 mock `proc.pid = 99` →
atexit 的 `_cleanup_active_launchers()` → `launcher.stop()` →
`kill_process_tree()` → `killpg(0, SIGTERM)` → **pytest 进程自杀**。

**生产侧同样危险**：若引擎子进程的 pgid 解析出 0 或与本进程同组，
`stop()` 会把整个应用进程组一起带走（`dsn_ui` 会连同前端一起消失）。

**修法**（已落地）：新增 `_resolve_kill_pgid()` 做三道护栏，任一命中即判为不可信，
调用方退回 `process.terminate()` 只终止目标进程本身：

+ `pgid <= 0`（0 = 调用者自己的组，负数无意义）；
+ `pgid == 本进程所在组`（同样会误伤自己）；
+ `getpgid()` 抛错（子进程已退出 / pid 非法）。

另新增 `_kill_descendants()`（可选依赖 psutil）在退化场景下逐个回收后代进程，
保住 Strata「C++ 引擎是孙进程」必须整棵树收干净的语义。

**回归测试**：`tests/test_killpg_guard.py`（9 个用例）——

+ 断言 `killpg` 在 pgid 为 0 / 负数 / 与自己同组 / `getpgid` 抛错时**从不被调用**；
+ 断言正常场景（子进程独立进程组）仍然走 `killpg`，语义不回归。

**连带修复**：

+ `tests/test_harness_strata.py` 的 `mock_proc.pid` 由 `99` 改为 `4294967`
  （超出 Linux PID 上限 2^22），不再依赖宿主机的 PID 表；
+  该 mock 进程改为「被 terminate 即视为已退出」，避免 atexit 对着一个
  「永不退出」的 mock 空等满 15s 超时（收尾耗时 19s → 5s）；
+ `tests/conftest.py` 的 autouse fixture 增加清理 `_ACTIVE_LAUNCHERS`，
  消除 pytest 关闭输出流之后 atexit 仍在打日志导致的
  `Logging error: I/O operation on closed file` 噪声。

---

## P1-1. Token 经济闭环未接入

**位置**：`harness/agent/assembler.py:74-83`

`AgentSpec` 接收 `router` / `budget`，`AgentAssembler` 也真的构造了
`ModelRouter` / `TokenMeter` / `TokenBudget` / `DurationPredictor` 并注册进 Runtime。
**但 `AgentLoop` 从不读它们**：

```python
def run(self, message):
    self.router.select(...)      # 调了，但结果没被使用
    self.meter.record({}, ...)   # 记录的是空 usage（注释自认「占位」）
    # budget.check() 从未被调用
```

**影响**：旧文档宣称的「Agent 自己会省钱」在框架层并不成立。
DSN 应用侧另有一套自己的实现，这也是为什么 `apps/dsn` 看起来能用。

**建议**：要么把 policy 真正接到循环（`_invoke` 后回填 usage、每轮 `budget.check()`），
要么在文档与代码注释里明确标注「预留能力」。**当前最危险的是文档与代码不一致。**

---

## P1-2. 「已写未接」的能力（零调用点）

以下模块功能完整、有测试，但**在生产代码里没有任何调用点**：

| 能力 | 位置 | 说明 |
|---|---|---|
| `SpeculativePrefetch` / `PrefetchPlaceholders` | `harness/agent/context.py` | 符号预取与 FETCH 协议，全仓仅定义处 |
| `FileWatcher` | `harness/codegraph/watcher.py` | 文件变更监听 |
| `ImportResolver` | `harness/codegraph/imports.py` | import 路径映射 |
| `OutputFilter` | `harness/pipeline/filters.py` | ANSI/时间戳/UUID 过滤，未接入回喂链路 |
| `SwarmRuntime` | `harness/agent/swarm.py` | 群组共识，apps 中零引用 |
| `create_agent` / `Agent` | `harness/sdk.py` | 仅测试使用，apps 不调用 |
| `SemanticCache` | `infra/cache.py` | 仅被 `harness/__init__` 重导出；业务用的是 `apps/dsn/semantic_cache/` |
| `EventLogger` | `infra/observability/core.py` | 全仓无调用者，且是逆向依赖 |

**建议**：这不是必须修的 bug，但它们让「框架能力」的描述容易夸大。
文档中应如实标注状态，或在 README 里区分「已接入」与「可选用」。

---

## P1-3. 声明了但不生效的字段

| 字段 | 位置 | 实际情况 |
|---|---|---|
| `ContextBudget.tail_rounds` / `max_open_topics` | `harness/context_assembly.py` | `plan()` **从不读取**，仅构造时赋值 |
| `ContextGatherer.MAX_FILE_SIZE` | `harness/context_gatherer.py` | 常量定义但未使用 |
| `@grep` 的 glob 参数 | 同上 | 能解析但不生效 |
| `AsyncTaskStore._ttl` | `infra/tasks/async_store.py` | 声明后从未使用 |
| `ToolResult.data` | `harness/tools/base.py` | `AgentLoop` 打包结果时**丢弃** `data` 字段 |
| `AgentSpec.tools` 的 list 形式 | `harness/agent/assembler.py:118` | 只识别字面量 `standard`，其余元素静默忽略 |
| `DSN_UI_MODEL_PROFILES_DIR` | `apps/dsn_ui/config.py:60` | 目录写死为 `apps/dsn/model_profiles`，**没有读环境变量** |

**这类问题的危害**：读者按名字以为能力存在，排查时浪费大量时间。
建议统一处理：要么实现，要么删除，要么在字段旁注明「预留」。

---

## P1-4. 三个装配路径并存

| 路径 | 位置 | 记忆语义 |
|---|---|---|
| `AgentAssembler` | `harness/agent/assembler.py` | 注入 `InMemoryStore` 但不使用 |
| `AgentRuntime` | `harness/agent_runtime.py` | 记忆**只写不读**（写入后从不进入上下文） |
| `sdk.Agent` | `harness/sdk.py` | 内部其实走 `AgentAssembler` |

外加应用侧还有四个平行的「Agent 门面」：`DSNUIAgentCoordinator`、`StudyEngine`、
`EmotionExpAgent`、以及 `dsn` 的 `DSNEngine`。

**建议**：短期在文档中明确「新代码用 `AgentRuntime` 或直接 `AgentLoop`」；
长期收敛到一到两个入口。

---

## P1-5. 应用层的装配路径分叉（`apps/dsn`）

`apps/dsn` 有**三套并存**的装配逻辑：

| 路径 | 位置 | 备注 |
|---|---|---|
| `boot.create_application()` | `apps/dsn/boot.py:399` | 生产路径，658 行、约 106 个分支 |
| `DSNEngine(subapp_path)` | `apps/dsn/engine.py:156` | SubApp 路径 |
| `create_engine_with_defaults()` | `apps/dsn/engine.py:1140` | 主应用复用 boot 组件 |

「DI 注册 + 4 遍插件加载」这段逻辑在 `engine.py:635-724` 与 `engine.py:1231-1338`
**写了两遍且已经分叉**（后者缺 `enable_set` / `disable_set` 与 `complexity_analyzer`）。

另一个分叉：prompt 目录在 SubApp 路径只加载 `{core, capabilities}`，
而主路径加载 `{core, capabilities, extensions}`——**同一份配置在两条路径下内容不同**。

---

## P1-6. `infra.models` 兼容 shim 的隐性导入顺序

`infra/models/` 下只有一个 `__init__.py`，它把 `infra.orchestrator.*` 镜像进
`sys.modules`。因此：

- `from infra.models.base import X` **只有在 `infra.models` 已被导入过时才成立**；
- 它没有映射 `infra.models.router`，覆盖并不完整。

**建议**：新代码一律写 `infra.orchestrator.*`；适时删除 shim。

---

## P1-7. 两处 `infra → harness` 逆向依赖

分层契约规定 `infra` 不依赖 `harness`，当前有两处违规：

| 文件 | 依赖 | 风险评估 |
|---|---|---|
| `infra/observability/core.py:12` | `from harness.pipeline.events import EventBus` | `EventLogger` 全仓无调用者，**可直接删除** |
| `infra/cache.py:10` | `from harness.memory.vector import VectorIndex` | 与 `harness/memory/vector.py:13` 反向依赖 `infra.models.base` **构成循环**；`SemanticCache` 无真实消费者，**可整体移出或删除** |

两者指向的都是没有消费者的代码，**斩断成本很低**。

---

## P2-1. 巨型文件与高复杂度函数

`fuck-u-code` 静态分析给出的热点（按「糟糕指数」排序）：

| 文件 | 指数 | 最复杂函数 |
|---|---:|---|
| `apps/dsn/plugins/pipeline.py` | 56.55 | `_dsn_agent_round` (44)、`_poll_pending_tasks` (38) |
| `apps/dsn/psychoscope/minimal.py` | 56.50 | `main`、`_poll_loop` |
| `apps/dsn/main.py` | 52.68 | `_cmd_reminder` (31)、`_cmd_plan` (21) |
| `apps/densechat/static/app.js` | 52.50 | `handleMessage` (62) |
| `apps/dsn_ui/server.py` | 48.64 | `_produce_sse` (72)、`chat_completions` (57) |
| `apps/dsn/memory/core.py` | 46.89 | `search` (39) |
| `infra/orchestrator/anthropic.py` | 45.35 | `_split_system` (34) |
| `apps/dsn/engine.py` | 45.33 | `_init_plugins_via_loader` (38) |
| `apps/dsn_ui/agent.py` | 41.98 | `chat_stream` (64) |
| `harness/agent/loop.py` | 40.46 | `run_stream` (49) |

**改动这些函数前请先补测试。** 最值得拆分的三个：

1. `boot.create_application()`（658 行）——按子系统拆成多个 `_init_*` 函数；
2. `plugins/pipeline.py::process_stream`（412 行）——抽出 SSE 编码层；
3. `dsn_ui/server.py::_produce_sse`（复杂度 72）——抽出事件生成器。

---

## P2-2. 错误处理：静默吞异常

`fuck-u-code` 显示错误处理项得分仅 31.37%，是 11 项指标中最低的。

`apps/dsn` 有大量 `except Exception: pass` 与 `logger.warning("Operation failed")` 式
通用文案。子系统初始化失败只是置为 `None` 然后继续启动（world / tracking /
semantic_cache / TTS 都是这样）。

**直接后果**：「某功能没反应」时，第一现场是启动日志里的一条 warning，而不是异常栈。
这也是 [getting-started.md](getting-started.md) 把「先看 warning」列为排障第一原则的原因。

**建议**：给启动失败加一个 degraded-mode 汇总报告，在启动结束时一次性打印
「以下子系统不可用：…」，而不是散落在几百行日志里。

---

## P2-3. 命名与日志不一致

- `ModelProfile.llama_config` 被 Strata 复用（字段名说 llama，实际装 Strata 配置）；
- logger 名五花八门：`ModelOrchestrator` / `harness-scheduler` / `infra.anthropic`，
  `infra` 层大量残留 harness 命名；
- 文件头注释与真实路径不符（`infra/orchestrator/base.py:1` 写成 `infra/models/base.py`，而该文件并不存在）；
- `used_slots` 在 `ModelOrchestrator` 与 `ResourcePool` 里**语义不同**。

---

## P2-4. 前端构建脚本失效

`apps/dsn_ui/frontend` 的 `npm run dev` 会 cd 到不存在的 `tools/ui`（llama.cpp 上游遗留路径）。
本地开发请直接 `npx vite dev`。另外 `vite.config.ts` 默认指向 `localhost:8080`，
与 `dsn_ui` 默认端口 8888 **不一致**，需要手动设置。

---

## 实际修复记录（2026-10-20）

| 原级别 | 问题 | 修复位置 | 状态 |
|---|---|---|---|
| P0-1 | 收束轮角色序列非法 | `harness/agent/loop.py::_fold_trailing_tools` | ✅ 已修 |
| P0-2 | EventBus 异步订阅失效 | `harness/pipeline/events.py` | ✅ 已修 |
| P0-3 | 测试文件硬编码凭据 | `tests/test_chat_with_user.py` | ✅ 代码已改，**凭据需轮换** |
| P0-4 | 显式切换被自动降级覆盖 | `infra/policy/router.py` | ✅ 已修 |
| P0-5 | 收束轮回复重复拼接 | `harness/agent/loop.py` | ✅ 已修 |
| P1-1 | Token 经济闭环未接入 | `AgentLoop.on_usage` + `assembler._record_usage` | ✅ 已接入 |
| P1-7 | 两处逆向依赖 | `infra/cache.py`、`infra/observability/core.py` | ✅ 已斩断 |
| P1-3 | 声明但不生效的字段 | `AsyncTaskStore.ttl`、`ContextGatherer` | ✅ 已实现 |
| P1-6 | `infra.models` shim | `infra/models/__init__.py` | ✅ 已重写 |
| P2 | 管线计时断裂 | `harness/pipeline/pipeline.py` | ✅ 已修 |
| P2 | dsn_ui 不读 .env | `apps/dsn_ui/dotenv_boot.py` | ✅ 已修 |
| P2 | APIKeyManager 存明文 | `infra/auth/api_key.py` | ✅ 已修 |
| **P0-6** | **`killpg(0)` 误杀宿主进程** | `infra/orchestrator/local_engine.py` | ✅ 已修 |

### ⚠️ 仍需人工处理

1. **轮换凭据**：`tests/test_chat_with_user.py` 里的 littleskin `client_secret` 与
   一个 `sk-` 密钥已进入 git 历史。代码已改为读环境变量，但**旧值必须轮换**，
   仅改代码不足以消除风险。

2. ~~**`/docs/` 仍在 `.gitignore` 里**~~ —— **已于 2026-10-20 处理**：
   移除该行，`docs/` 下 17 篇文档已全部入库（见下方「文档与仓库卫生」）。

3. **`test_prompt_ecosystem` / `test_skills_system` 的 10 个用例**已标记为
   `known_broken`（资产漂移），需要重做断言而不是恢复旧资产。

---
## 文档与仓库卫生

### `docs/` 已恢复入库（2026-10-20）

**历史**：`.gitignore` 曾包含 `/docs/` 一行，导致 **`docs/` 下的 17 篇架构与维护文档
完全不被 git 跟踪**——clone 仓库的新成员看不到任何架构信息。
本仓库的文档密度极高（12 篇 / 2949 行），不入库等于这些知识只活在某一台机器上。

**现状**：已从 `.gitignore` 移除该行，`docs/` 全量入库（含 `docs/archive/`
的旧版文档与一次性完成记录，其自带 `README.md` 明确标注「架构已过时」）。

**入库前已核查**（仓库为 **public** 可见，故逐项排查过）：

| 检查项 | 结果 |
|---|---|
| 密钥 / token / `sk-` 前缀串 | 无（仅一处**提及**轮换要求的文字，不含值） |
| `client_secret` / `password` / 私钥 | 无 |
| 个人邮箱 | 无 |
| 绝对家目录路径 | 无 |
| 二进制文件 | 无（17 个文件全为 `.md`） |
| 外链 | 仅 `127.0.0.1` / `localhost` / `api.deepseek.com` |

### 运行产物散落仓库根目录

以下文件属于运行时产物，虽已被 `.gitignore` 覆盖（`*.db`），但会留在工作副本里：

| 路径 | 性质 |
|---|---|
| `DSN_usrdata.db` | DSN 用户数据 |
| `.dekacode_web.db` / `.emotion_exp.db` | 各应用数据 |
| `logs/` | 日志 |
| `temp/` | 开发临时区（含 `dsn_study_backup` 等） |
| `MagicMock/` | 测试副作用产物（**不是源码**）。跑一次 `tests/test_harness_strata.py` 就会新增若干 `MagicMock/mock.agent.data_dir/<id>/thought_cache.db`——因为测试里 `data_dir` 是 MagicMock，被当真路径用了。**注意：它没有被 .gitignore 显式忽略**，只是因为 `*.db` 规则侥幸没入库 |
| `__pycache__/` / `.pytest_cache/` / `.ruff_cache/` | 缓存 |
| `apps/dsn_ui/frontend/node_modules/` | 前端依赖（很大，会干扰按 `.py` 统计行数的脚本） |

### 统计代码规模时要注意

直接 `find . -name '*.py'` 会扫到 `temp/`、`prototypes/`、`node_modules/` 里的文件，
得到虚高的数字。正确做法是排除这些目录：

```bash
find . -name '*.py' -not -path './.git/*' -not -path '*/__pycache__/*' \
     -not -path './temp/*' -not -path './prototypes/*' -not -path '*/node_modules/*' \
     | xargs wc -l | tail -1
```
